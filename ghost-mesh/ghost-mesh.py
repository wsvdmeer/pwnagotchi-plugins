import logging
import os
import json
import hmac as hmac_mod
import hashlib
import threading
import time
import re
import subprocess
import requests
from flask import render_template_string
from pwnagotchi.plugins import Plugin
from pwnagotchi import plugins

# ============================================================
#  GhostMesh v44.2 — Broadcasting via direct HCI
# ============================================================
# Author: Gemini & Mutagenic
# Goal: Stealth-first, zero-log, zero-heavy-write ghost mesh.
# Transport: Direct HCI commands via hcitool (no dependencies)
# — runs alongside scanning without interfering.

PWNGRID_HOT = "http://127.0.0.1:8666/api/v1/units/hot"
# btmon may show manufacturer ID 0xDEAD as big-endian "dead" or
# little-endian wire order "adde".  Match either + our 0xBE magic byte.
BLE_MARKERS = ["deadbe", "addebe"]
SECRET = b"pwngrid_public_mesh"
MANUFACTURER_ID = 0xDEAD


class GhostMesh(Plugin):
    __author__ = "Gemini & GhostMesh"
    __version__ = "1.0.0"

    # Allow POST requests without CSRF token
    csrf_exempt = True

    # Configuration options (can be overridden in config.toml)
    options = {
        "enabled": {"default": True, "help": "Enable/disable GhostMesh plugin"},
        "stealth": {"default": True, "help": "Start in stealth mode (no broadcasting)"},
        "broadcast_interval": {
            "default": 60,
            "help": "Seconds between broadcast cycles (15s on + rest off)",
        },
        "peer_detection_cooldown": {
            "default": 5,
            "help": "Cooldown period in seconds before detecting same peer again",
        },
        "scanner_heartbeat": {
            "default": 30,
            "help": "Scanner status log interval in seconds",
        },
        "pwngrid_timeout": {
            "default": 10,
            "help": "Local pwngrid request timeout in seconds",
        },
        "grid_sync_interval": {
            "default": 300,
            "help": "Periodic grid sync interval in seconds (auto mode only)",
        },
    }

    def __init__(self):
        self.running = False
        self.lock = threading.Lock()
        self.peers = {}
        self.identity_cache = {}
        self._hmac_index = {}
        self._seen_hmacs = {}  # Track HMACs with peer_detection_cooldown

        self.plugin_dir = os.path.dirname(os.path.realpath(__file__))
        self.history_path = os.path.join(self.plugin_dir, "ghost-mesh-peers.json")

        # Load config with defaults
        self.stealth_mode = self.options["stealth"]["default"]
        self.broadcast_interval = self.options["broadcast_interval"]["default"]
        self.peer_detection_cooldown = self.options["peer_detection_cooldown"][
            "default"
        ]
        self.scanner_heartbeat = self.options["scanner_heartbeat"]["default"]
        self.pwngrid_timeout = self.options["pwngrid_timeout"]["default"]
        self.grid_sync_interval = self.options["grid_sync_interval"]["default"]

        self.sync_status = "Waiting..."
        self.pulse_status = "Off"
        self.packets_processed = 0  # RAM-only heartbeat
        self.last_sync_time = 0  # Track when we last attempted sync
        self.sync_attempts = 0  # Count sync attempts

        self._lescan_proc = None
        self._my_hmac = None

        self._broadcast_thread = None
        self._broadcast_stop = threading.Event()
        self._sync_thread = None
        self._sync_stop = threading.Event()
        self._agent = None
        self._last_known_mode = None  # Track mode for detecting switches

    # --- UI & WEBHOOK LOGIC ---------------------------------------------------

    def on_webhook(self, path, request):
        from flask import jsonify

        clean_path = path.lstrip("/") if path else ""

        # --- Action endpoints (GET-based) ---
        if clean_path == "toggle-stealth":
            self.stealth_mode = not self.stealth_mode
            if self.stealth_mode:
                self._stop_broadcasting()
            else:
                self._start_broadcasting()
            return jsonify({"success": True, "stealth": self.stealth_mode})

        if clean_path == "test-scan":
            """Simulate receiving a peer's advertisement for testing parser logic."""
            # Create a simulated peer HMAC (different from ours)
            sim_hmac = "aabbccddee11"  # Fake peer

            # Test both PRIMARY and EIR formats
            results = {"primary": False, "eir": False}

            # Test 1: PRIMARY format — btmon shows "Manufacturer Data (0xDEAD): be <HMAC_12_chars> ..."
            primary_payload = f"be:{sim_hmac[0:2]}:{sim_hmac[2:4]}:{sim_hmac[4:6]}:{sim_hmac[6:8]}:{sim_hmac[8:10]}:{sim_hmac[10:12]}:00:00:00:00"
            primary_line = f"Manufacturer Data (0xDEAD): {primary_payload}"
            logging.info(f"[ghost-mesh] TEST PRIMARY: {primary_line}")

            hex_part = primary_line.split(":", 1)[1].strip()
            hex_data = hex_part.replace(" ", "").replace(":", "").lower()
            mfg_pattern = r"be([0-9a-f]{12})"
            matches = re.findall(mfg_pattern, hex_data)
            if matches:
                results["primary"] = True
                for rx_hmac in matches:
                    logging.info(f"[ghost-mesh] ✓ PRIMARY parser found HMAC: {rx_hmac}")
                    if rx_hmac != self._my_hmac:
                        self._resolve_and_update(rx_hmac)
            else:
                logging.info(
                    f"[ghost-mesh] ✗ PRIMARY parser failed to find HMAC in: {hex_data}"
                )

            # Test 2: EIR format — raw 0xFF ADDE BE <HMAC_12_chars> pattern
            eir_payload = f"ffaddabe{sim_hmac}"
            eir_line = f"Unknown EIR field 0xFF[0]: {eir_payload}"
            logging.info(f"[ghost-mesh] TEST EIR: {eir_line}")

            hex_part = eir_line.split(":", 1)[1].strip()
            hex_data = hex_part.replace(" ", "").lower()
            eir_patterns = [
                r"ffaddabe([0-9a-f]{12})",
                r"ffdeadbe([0-9a-f]{12})",
                r"ff\s*adde\s*be([0-9a-f]{12})",
                r"ff\s*dead\s*be([0-9a-f]{12})",
            ]
            for pattern in eir_patterns:
                matches = re.findall(pattern, hex_data, re.IGNORECASE)
                if matches:
                    results["eir"] = True
                    for rx_hmac in matches:
                        logging.info(f"[ghost-mesh] ✓ EIR parser found HMAC: {rx_hmac}")
                        if rx_hmac != self._my_hmac:
                            self._resolve_and_update(rx_hmac)
                    break
            if not results["eir"]:
                logging.info(
                    f"[ghost-mesh] ✗ EIR parser failed to find HMAC in: {hex_data}"
                )

            return jsonify(
                {
                    "success": results["primary"] or results["eir"],
                    "message": f"Test results — PRIMARY: {results['primary']}, EIR: {results['eir']}",
                    "test_hmac": sim_hmac,
                    "peers_detected": len(self.peers),
                }
            )

        if clean_path == "status":
            seconds_since_sync = (
                int(time.time() - self.last_sync_time) if self.last_sync_time else -1
            )
            return jsonify(
                {
                    "stealth": self.stealth_mode,
                    "pulse": self.pulse_status,
                    "packets": self.packets_processed,
                    "sync": self.sync_status,
                    "peer_count": len(self.peers),
                    "polling_active": self._sync_thread
                    and self._sync_thread.is_alive(),
                    "sync_attempts": self.sync_attempts,
                    "seconds_since_last_sync": seconds_since_sync,
                    "grid_sync_interval": self.grid_sync_interval,
                    "peers": {
                        k: {**v, "last_seen": int(time.time() - v.get("last_seen", 0))}
                        for k, v in self.peers.items()
                    },
                }
            )

        # --- Main UI page ---
        bg_color = "#121212" if self.stealth_mode else "#000"
        accent = "#ff4444" if self.stealth_mode else "#0f0"

        html = """
        <html><head>
        <style>
            body { background:{{bg}}; color:#0f0; font-family:monospace; padding:20px; margin:0; }
            .header { display:flex; justify-content:space-between; align-items:center; margin-bottom:20px; }
            .button { background:#222; color:{{acc}}; border:1px solid {{acc}}; padding:8px 15px; cursor:pointer; font-family:monospace; }
            .status-panel { font-size:0.9em; color:#888; border:1px solid #222; padding:15px; margin:20px 0; background:#0a0a0a; }
            .peers-container { margin-top:20px; }
            .peer-item { margin-bottom:15px; border-left:3px solid #0f0; padding-left:10px; }
            .peer-name { font-size:1.2em; margin-right:5px; }
            .peer-info { color:#fff; font-weight:bold; }
            .peer-id { color:#444; font-size:0.85em; }
            .no-peers { color:#333; }
        </style>
        </head><body>
        <div class='header'>
            <h2 style='margin:0;'>(⇀‿‿↼) Ghost Mesh</h2>
            <button class='button' id='btn-stealth' onclick='toggleStealth()'>
                {{ "DISABLE STEALTH" if stealth else "ENABLE STEALTH" }}
            </button>
        </div>

        <div class='status-panel'>
            <b style='color:#aaa;'>PULSE:</b> <span style='color:{{acc}};' id='pulse-status'>{{ pulse }}</span><br>
            <b style='color:#aaa;'>SCANNER:</b> <span style='color:#0f0;' id='scanner-status'>LIVE</span> (<span id='packet-count'>{{ pkts }}</span> packets)<br>
            <b style='color:#aaa;'>GRID:</b> <span id='grid-status'>{{ status }}</span><br>
            <b style='color:#aaa;'>SOULS:</b> <span style='color:#0f0;' id='peer-count'>{{ peer_count }}</span>
        </div>

        <h3 style='border-bottom:1px solid #222; padding-bottom:5px; color:#555;'>DETECTED SOULS</h3>
        <div class='peers-container' id='peers-list'>
            {% for k,d in p.items() %}
                <div class='peer-item'>
                    <span class='peer-name'>{{ d.face }}</span> <span class='peer-info'>{{ d.name }}</span><br>
                    <span class='peer-id'>ID: {{ d.hmac }} | Seen: <span class='seen-time'>{{ (n-d.last_seen)|int }}</span>s ago</span>
                </div>
            {% endfor %}
            {% if not p %}<p class='no-peers'>No ghosts heard yet. Scanning the ether...</p>{% endif %}
        </div>

        <script>
        // Poll status every 2 seconds and update DOM without full refresh
        function updateStatus() {
            fetch('/plugins/ghost-mesh/status')
                .then(r => r.json())
                .then(data => {
                    document.getElementById('pulse-status').textContent = data.pulse || 'Off';
                    document.getElementById('packet-count').textContent = data.packets.toLocaleString();
                    document.getElementById('grid-status').textContent = data.sync || 'Unknown';
                    document.getElementById('peer-count').textContent = data.peer_count;
                    
                    // Update peers list
                    const peersList = document.getElementById('peers-list');
                    const peers = data.peers || {};
                    
                    if (Object.keys(peers).length === 0) {
                        peersList.innerHTML = '<p class="no-peers">No ghosts heard yet. Scanning the ether...</p>';
                    } else {
                        let html = '';
                        const now = Math.floor(Date.now() / 1000);
                        for (const [k, peer] of Object.entries(peers)) {
                            const seenAgo = now - peer.last_seen;
                            html += `
                                <div class='peer-item'>
                                    <span class='peer-name'>${peer.face}</span> <span class='peer-info'>${peer.name}</span><br>
                                    <span class='peer-id'>ID: ${peer.hmac} | Seen: ${seenAgo}s ago</span>
                                </div>
                            `;
                        }
                        peersList.innerHTML = html;
                    }
                })
                .catch(e => console.error('Status fetch failed:', e));
        }
        
        function toggleStealth() {
            fetch('/plugins/ghost-mesh/toggle-stealth').then(r => r.json()).then(d => { 
                if(d.success) location.reload(); 
            });
        }
        
        // Load status immediately and then every 2 seconds
        updateStatus();
        setInterval(updateStatus, 2000);
        </script>
        </body></html>
        """
        return render_template_string(
            html,
            bg=bg_color,
            acc=accent,
            stealth=self.stealth_mode,
            pulse=self.pulse_status,
            pkts=f"{self.packets_processed:,}",
            status=self.sync_status,
            p=self.peers,
            peer_count=len(self.peers),
            n=time.time(),
        )

    # --- BROADCAST VIA DIRECT HCI --------------------------------------------------

    def _start_broadcasting(self):
        """Start mesh pulse via direct HCI."""
        if self._broadcast_thread and self._broadcast_thread.is_alive():
            return

        self._broadcast_stop.clear()
        self._broadcast_thread = threading.Thread(
            target=self._broadcast_loop,
            daemon=True,
            name="ghost-mesh-pulse",
        )
        self._broadcast_thread.start()

        self.pulse_status = "STARTING"
        logging.info("[ghost-mesh] Broadcasting started via direct HCI")

    def _stop_broadcasting(self):
        """Stop mesh broadcasting."""
        self._broadcast_stop.set()
        self.pulse_status = "SILENT"

    def _broadcast_loop(self):
        """Send periodic BLE pulses via direct HCI commands."""
        error_count = 0
        while self.running and not self._broadcast_stop.is_set():
            try:
                payload = self._build_broadcast_payload()
                if not payload:
                    self._broadcast_stop.wait(30)
                    continue

                success = self._broadcast_ble_direct(payload, duration=15)

                if success:
                    self.pulse_status = "ACTIVE"
                    error_count = 0
                else:
                    self.pulse_status = "FAILED"
                    error_count += 1
                    if error_count >= 3:
                        logging.warning(
                            "[ghost-mesh] Broadcast failed 3x, check BLE adapter"
                        )

                # 15s broadcast + silence = broadcast_interval cycle
                self._broadcast_stop.wait(self.broadcast_interval)

            except Exception as e:
                logging.error(f"[ghost-mesh] Broadcast error: {e}")
                self.pulse_status = "ERROR"
                error_count += 1
                self._broadcast_stop.wait(30)

    def _build_broadcast_payload(self):
        """Build BLE manufacturer data payload.

        Layout (12 bytes):
            Byte  0:     0xBE (magic — combined with manufacturer 0xDEAD = "deadbe")
            Bytes 1-6:   HMAC identity (6 bytes from fingerprint hash)
            Byte  7:     Peer count (0-255)
            Bytes 8-11:  Unix timestamp low 32 bits (replay detection)

        In btmon output this appears as:
            Company: 0xdead
            Data: be XX XX XX XX XX XX ...

        The scanner regex matches "deadbe" + 12 hex chars of the HMAC.
        """
        try:
            if not self._my_hmac:
                return None

            hmac_bytes = bytes.fromhex(self._my_hmac[:12])  # 6 bytes
            peer_count = min(len(self.peers), 255)
            ts = int(time.time()) & 0xFFFFFFFF

            payload = bytearray()
            payload.append(0xBE)  # magic tail — makes "deadbe" in btmon
            payload.extend(hmac_bytes)  # 6 bytes identity
            payload.append(peer_count)  # 1 byte
            payload.extend(ts.to_bytes(4, "big"))  # 4 bytes timestamp

            return bytes(payload)  # 12 bytes total

        except Exception as e:
            logging.error(f"[ghost-mesh] Payload build error: {e}")
            return None

    def _broadcast_ble_direct(self, data_bytes, duration=15):
        """Broadcast BLE manufacturer data directly via HCI commands."""
        try:
            if not isinstance(data_bytes, (bytes, bytearray)):
                return False
            if len(data_bytes) > 27:
                return False

            mfr_low = MANUFACTURER_ID & 0xFF
            mfr_high = (MANUFACTURER_ID >> 8) & 0xFF
            mfr_payload = bytes([mfr_low, mfr_high]) + data_bytes
            ad_struct = bytes([len(mfr_payload) + 1, 0xFF]) + mfr_payload

            flags_ad = bytes([0x02, 0x01, 0x06])
            full_ad = flags_ad + ad_struct

            if len(full_ad) > 31:
                return False

            ad_padded = full_ad + bytes(31 - len(full_ad))
            hci_params = [f"{len(full_ad):02x}"] + [f"{b:02x}" for b in ad_padded]

            result = subprocess.run(
                ["hcitool", "-i", "hci0", "cmd", "0x08", "0x0008"] + hci_params,
                capture_output=True,
                timeout=5,
            )
            if result.returncode != 0:
                return False

            result = subprocess.run(
                ["hcitool", "-i", "hci0", "cmd", "0x08", "0x000a", "01"],
                capture_output=True,
                timeout=5,
            )
            return result.returncode == 0

        except FileNotFoundError:
            logging.warning("[ghost-mesh] hcitool not found - install bluez")
            return False
        except Exception as e:
            logging.error(f"[ghost-mesh] Broadcast failed: {e}")
            return False

    def _process_hmac(self, rx_hmac, source):
        """Process detected HMAC with configurable peer_detection_cooldown.

        Args:
            rx_hmac: HEX string of detected HMAC (e.g., '2f3ca25da826')
            source: String describing where detection came from (e.g., 'EIR', 'PRIMARY')
        """
        current_time = time.time()

        # Check cooldown period
        last_seen = self._seen_hmacs.get(rx_hmac, 0)
        if current_time - last_seen < self.peer_detection_cooldown:
            return  # Already detected recently, skip

        # Update last seen time
        self._seen_hmacs[rx_hmac] = current_time

        # Don't log our own broadcasts
        if rx_hmac == self._my_hmac:
            return

        # Log and update peer list
        self._resolve_and_update(rx_hmac)
        self.packets_processed += 1
        logging.info(f"[ghost-mesh] ✓ Peer detected ({source}): {rx_hmac}")

    # --- SCANNER (hcitool lescan output parsing) --------------------------------

    def _scanner_loop(self):
        """Adaptive BLE scanner - tries multiple backends to capture manufacturer data.

        CRITICAL: We need FULL advertisement payloads, not just MAC addresses.
        Only btmon and hcidump show manufacturer data. This scanner:
        1. Starts an active LE scan (hcitool lescan --passive --duplicates)
        2. Starts btmon to monitor HCI traffic and extract manufacturer data
        3. Logs raw lines to help debug format issues

        NOTE: Both lescan and btmon must run in parallel. lescan triggers the
        adapter to actively scan for LE advertisements, and btmon then sees
        those advertisements in the HCI event stream.
        """
        lescan_proc = None
        while self.running:
            try:
                logging.info("[ghost-mesh] Starting BLE scanner...")

                # Ensure BLE adapter is up
                try:
                    logging.info(
                        "[ghost-mesh] Bringing up BLE interface (hcitool leup)..."
                    )
                    subprocess.run(
                        ["hcitool", "leup"],
                        timeout=5,
                        capture_output=True,
                    )
                except Exception as e:
                    logging.debug(f"[ghost-mesh] hcitool leup: {e}")

                # Start passive LE scan (required to trigger HCI LE Advertising Reports)
                try:
                    logging.info(
                        "[ghost-mesh] Starting hcitool lescan (passive, duplicates enabled)..."
                    )
                    lescan_proc = subprocess.Popen(
                        ["hcitool", "lescan", "--passive", "--duplicates"],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        universal_newlines=True,
                        bufsize=1,
                    )
                    logging.info("[ghost-mesh] ✓ hcitool lescan started")
                except Exception as e:
                    logging.warning(f"[ghost-mesh] lescan start failed: {e}")
                    lescan_proc = None

                # ATTEMPT 1: btmon with explicit device and error capture
                logging.info(
                    "[ghost-mesh] Attempting btmon -i hci0 (will capture LE Advertising Reports)..."
                )

                try:
                    self._lescan_proc = subprocess.Popen(
                        ["btmon", "-i", "hci0"],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        universal_newlines=True,
                        bufsize=1,  # Line buffered
                    )

                    logging.info("[ghost-mesh] ✓ btmon -i hci0 started successfully")
                    self._scan_with_btmon()

                except FileNotFoundError:
                    logging.warning(
                        "[ghost-mesh] btmon not found, trying lescan fallback..."
                    )
                    self._scan_with_lescan()
                except Exception as e:
                    logging.warning(f"[ghost-mesh] btmon failed: {e}, trying lescan...")
                    self._scan_with_lescan()

            except Exception as e:
                logging.error(f"[ghost-mesh] Scanner critical error: {e}")
                import traceback

                logging.error(traceback.format_exc())
                time.sleep(5)
            finally:
                if self._lescan_proc:
                    try:
                        self._lescan_proc.kill()
                        self._lescan_proc.wait(timeout=3)
                    except Exception:
                        pass
                    self._lescan_proc = None
                if lescan_proc:
                    try:
                        lescan_proc.kill()
                        lescan_proc.wait(timeout=3)
                    except Exception:
                        pass
                    lescan_proc = None

    def _scan_with_btmon(self):
        """Parse btmon output line-by-line with state machine.

        Watches for "Company: not assigned (57005)" which marks 0xDEAD manufacturer data.
        Then grabs the HMAC from the next "Data[" line containing BE markers.

        Format observed in btmon:
            Company: not assigned (57005)    <-- 57005 = 0xDEAD
            Data[12]: be2f3ca25da8260069a9fbfd
        """
        last_log_time = time.time()
        total_lines = 0
        found_company = False

        try:
            for line in iter(self._lescan_proc.stdout.readline, ""):
                if not self.running:
                    break

                line = line.strip()
                if not line:
                    continue

                total_lines += 1

                # Track when we see 0xDEAD manufacturer ID (57005 decimal)
                if "Company: not assigned (57005)" in line:
                    found_company = True
                    continue

                # When we see a Data field after Company, extract HMAC
                if found_company and "Data" in line and ":" in line:
                    try:
                        hex_part = line.split(":", 1)[1].strip()
                        hex_data = hex_part.replace(" ", "").lower()

                        # Look for BE markers (deadbe, addebe) OR direct BE magic byte
                        # Pattern 1: Full markers from multi-field advertisements
                        for marker in BLE_MARKERS:
                            if marker in hex_data:
                                pattern = marker + r"([0-9a-f]{12})"
                                matches = re.findall(pattern, hex_data)
                                for rx_hmac in matches:
                                    if rx_hmac != self._my_hmac:
                                        self._process_hmac(rx_hmac, f"Data[{marker}]")
                                found_company = False
                                break

                        # Pattern 2: Direct BE magic byte at start (common in Data[N] format)
                        if (
                            found_company
                        ):  # Only try if we haven't found with markers yet
                            be_pattern = r"^be([0-9a-f]{12})"
                            matches = re.findall(be_pattern, hex_data)
                            if matches:
                                for rx_hmac in matches:
                                    if rx_hmac != self._my_hmac:
                                        self._process_hmac(rx_hmac, "Data[BE-direct]")
                                found_company = False

                    except Exception as e:
                        found_company = False

                # Reset state on new advertisement event
                if "> HCI Event:" in line:
                    found_company = False

                # Keep-alive logging every scanner_heartbeat seconds
                current_time = time.time()
                if current_time - last_log_time >= self.scanner_heartbeat:
                    peer_count = len(self.peers)
                    logging.info(
                        f"[ghost-mesh] Scanner: {peer_count} peers, {self.packets_processed} packets"
                    )
                    last_log_time = current_time

        except Exception as e:
            logging.error(f"[ghost-mesh] btmon error: {e}")

    def _scan_with_lescan(self):
        """Fallback: hcitool lescan (shows devices but not manufacturer data).

        NOTE: This won't detect our payload since it doesn't show advertisement data!
        But it proves the adapter and scanning infrastructure works.
        """
        logging.info(
            "[ghost-mesh] ⚠ Using lescan fallback (limited - no manufacturer data)"
        )

        try:
            self._lescan_proc = subprocess.Popen(
                ["hcitool", "lescan", "--passive", "--duplicates"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                bufsize=1,
            )

            line_count = 0
            for line in iter(self._lescan_proc.stdout.readline, ""):
                if not self.running:
                    break

                line = line.strip()
                if not line or line.startswith("LE"):
                    continue

                if ":" in line:
                    line_count += 1
                    self.packets_processed += 1
                    # This only shows MAC and name, no payload
                    if line_count <= 3:
                        logging.info(
                            f"[ghost-mesh] SCAN (lescan) #{line_count}: {line}"
                        )

        except FileNotFoundError:
            logging.error("[ghost-mesh] hcitool not found - please install bluez")
            if self.running:
                time.sleep(30)
        except Exception as e:
            logging.error(f"[ghost-mesh] lescan error: {e}")

    def _resolve_and_update(self, rx_hmac):
        """Match received HMAC to a known identity via reverse lookup, or create ghost entry.

        Logic:
        1. Try reverse HMAC lookup: compute HMAC for each known fingerprint
        2. If match found → update peer with known identity
        3. If no match → create ghost entry and save to disk
        """
        with self.lock:
            # Try reverse HMAC lookup against known fingerprints
            matched_fp = None
            for fp in self.identity_cache.keys():
                computed_hmac = self._make_hmac(fp)
                if computed_hmac == rx_hmac:
                    matched_fp = fp
                    break

            if matched_fp:
                # Known peer matched
                id_data = self.identity_cache.get(matched_fp, {})
                self.peers[matched_fp] = {
                    "name": id_data.get("name", f"Peer [{rx_hmac}]"),
                    "face": id_data.get("face", "(◕‿◕)"),
                    "last_seen": time.time(),
                    "hmac": rx_hmac,
                }
            else:
                # Unknown HMAC — create ghost entry
                ghost_key = f"ghost_{rx_hmac}"
                self.peers[ghost_key] = {
                    "name": f"Ghost [{rx_hmac}]",
                    "face": "( ? _ ? )",
                    "last_seen": time.time(),
                    "hmac": rx_hmac,
                }
                # Save peers (known + ghosts) to disk
                self._save_peers_to_disk()

    def _sync_loop(self):
        """Background thread for periodic grid sync.

        Only runs in auto mode to avoid interfering with bettercap startup.
        Retries every grid_sync_interval seconds. Useful for picking up
        grid units once internet connectivity becomes available.
        Also detects mode switches and triggers immediate sync on manual→auto.
        """
        while self.running and not self._sync_stop.is_set():
            # Check current mode and only sync in auto
            current_mode = self._get_mode()

            # On mode switch to auto, trigger immediate sync
            if (
                self._last_known_mode
                and self._last_known_mode != "auto"
                and current_mode == "auto"
            ):
                logging.info(
                    f"[ghost-mesh] Mode switched to auto! Triggering immediate sync..."
                )
                try:
                    self._pwngrid_sync_once()
                except Exception as e:
                    logging.error(f"[ghost-mesh] Mode-switch sync error: {e}")

            self._last_known_mode = current_mode

            # Only sync in auto mode
            if current_mode == "auto":
                try:
                    self._pwngrid_sync_once()
                except Exception as e:
                    logging.error(f"[ghost-mesh] Sync loop error: {e}")
            else:
                # In manual/ai/unknown mode, just update status
                if self.sync_status not in ["Waiting...", f"Mode: {current_mode}"]:
                    self.sync_status = f"Mode: {current_mode}"

            # Wait for next sync interval, but be responsive to stop signal
            self._sync_stop.wait(self.grid_sync_interval)

    # --- GRID SYNC ------------------------------------------------------------

    def _pwngrid_sync_once(self):
        """Pull identities from local pwngrid hot units list."""
        self.last_sync_time = time.time()
        self.sync_attempts += 1
        logging.debug(
            f"[ghost-mesh] Sync attempt #{self.sync_attempts} to {PWNGRID_HOT}"
        )

        try:
            self.sync_status = "Syncing..."
            r = requests.get(PWNGRID_HOT, timeout=self.pwngrid_timeout)
            logging.debug(f"[ghost-mesh] Pwngrid response: {r.status_code}")

            if r.status_code == 200:
                data = r.json()
                units = data if isinstance(data, list) else data.get("units", [])
                if units:
                    self._process_units(units)
                    self.sync_status = f"✓ Synced ({len(self.identity_cache)} souls)"
                    logging.info(
                        f"[ghost-mesh] ✓ Synced {len(units)} units from local pwngrid"
                    )
                    return
                else:
                    self.sync_status = "No units published yet"
                    logging.info("[ghost-mesh] Pwngrid returned 200 but no units")
            else:
                self.sync_status = f"Pwngrid {r.status_code}"
                logging.warning(
                    f"[ghost-mesh] Local pwngrid returned {r.status_code} — is pwngrid running?"
                )

        except requests.exceptions.ConnectionError as e:
            self.sync_status = "Grid offline"
            logging.debug(f"[ghost-mesh] Local pwngrid connection refused: {e}")
        except requests.exceptions.Timeout:
            self.sync_status = "Grid timeout"
            logging.warning(
                f"[ghost-mesh] Local pwngrid timeout ({self.pwngrid_timeout}s)"
            )
        except Exception as e:
            self.sync_status = "Sync error"
            logging.error(f"[ghost-mesh] Grid sync failed: {e}")

    def _process_units(self, units):
        """Process unit list from any source (pwngrid or OpenPwnGrid)."""
        new_found = False
        with self.lock:
            for u in units:
                fp = u.get("fingerprint")
                if fp and fp not in self.identity_cache:
                    self.identity_cache[fp] = {
                        "name": u.get("name", "Unknown"),
                        "face": u.get("face", "(◕‿◕)"),
                    }
                    self._hmac_index[self._make_hmac(fp)] = fp
                    new_found = True

        if new_found:
            # Save all peers (known + ghosts) to disk
            self._save_peers_to_disk()

    # --- HELPERS --------------------------------------------------------------

    def _save_peers_to_disk(self):
        """Persist all peers (known identities + ghosts) to disk."""
        try:
            with open(self.history_path, "w") as f:
                json.dump(self.peers, f, indent=2)
        except Exception:
            pass

    def _make_hmac(self, fingerprint: str) -> str:
        """Create a 12-char hex HMAC from a fingerprint string."""
        return hmac_mod.new(SECRET, fingerprint.encode(), hashlib.sha256).hexdigest()[
            :12
        ]

    def _get_mode(self):
        """Return current pwnagotchi mode (auto/manual/ai)."""
        try:
            if self._agent and hasattr(self._agent, "mode"):
                return self._agent.mode
        except Exception:
            pass
        return "unknown"

    # --- LIFECYCLE ------------------------------------------------------------

    def on_loaded(self):
        """Plugin loaded — set up identity and start scanner."""
        # Identity setup
        fp_path = "/etc/pwnagotchi/fingerprint"
        my_fp = "unknown"
        if os.path.exists(fp_path):
            try:
                with open(fp_path, "r") as f:
                    my_fp = f.read().strip()[:24]
            except Exception:
                pass
        self._my_hmac = self._make_hmac(my_fp)

        # Load peers from disk (both known identities and ghosts)
        if os.path.exists(self.history_path):
            try:
                with open(self.history_path, "r") as f:
                    data = json.load(f)
                    self.peers = data  # Load all (ghosts + known)
                    # Separate known peers from ghosts to rebuild identity cache
                    for k, v in data.items():
                        if not k.startswith("ghost_"):
                            self.identity_cache[k] = v
                    # Rebuild HMAC index from known identities
                    self._hmac_index = {
                        self._make_hmac(fp): fp for fp in self.identity_cache
                    }
            except Exception:
                self.identity_cache = {}
                self._hmac_index = {}
                self.peers = {}
        else:
            self.identity_cache = {}
            self._hmac_index = {}
            self.peers = {}

        self.running = True

        # Start broadcasting only if NOT in stealth mode
        if not self.stealth_mode:
            self._start_broadcasting()

        logging.info(f"[ghost-mesh] v{self.__version__} loaded | hmac={self._my_hmac}")

    def on_ready(self, agent):
        """Called when pwnagotchi is fully ready."""
        # Store agent ref for mode detection
        self._agent = agent
        self._last_known_mode = self._get_mode()

        if not self.stealth_mode:
            self._start_broadcasting()

        # Start background sync thread for periodic retries (only syncs in auto mode)
        self._sync_stop.clear()
        self._sync_thread = threading.Thread(
            target=self._sync_loop, daemon=True, name="ghost-mesh-sync"
        )
        self._sync_thread.start()

        mode = self._get_mode()
        logging.info(
            f"[ghost-mesh] Periodic grid sync started (interval: {self.grid_sync_interval}s, mode: {mode}, syncs in AUTO mode only)"
        )

    def on_bt_tether_connected(self, agent, data):
        """Called when BLE adapter is fully ready.

        Starts passive BLE scanner to detect peer broadcasts.
        """
        logging.info("[ghost-mesh] Starting passive BLE scanner")
        threading.Thread(
            target=self._scanner_loop, daemon=True, name="ghost-mesh-scanner"
        ).start()

    def on_unload(self, ui):
        """Clean shutdown."""
        self.running = False
        self._broadcast_stop.set()
        self._sync_stop.set()
        if self._lescan_proc:
            try:
                self._lescan_proc.kill()
                self._lescan_proc.wait(timeout=3)
            except Exception:
                pass
        logging.info("[ghost-mesh] Unloaded.")
