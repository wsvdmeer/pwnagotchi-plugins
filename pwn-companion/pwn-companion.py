"""
Pwn Companion Plugin for Pwnagotchi

Enables real-time bidirectional communication with mobile app via WebSocket.
Connects as client to app's WebSocket server discovered via UDP announcements.

Required System Packages:
    sudo pip3 install websockets

Features:
- Automatic app discovery via UDP announcements on port 8888
- WebSocket client connection (lightweight, single connection)
- Custom command execution
- GPS coordinate support with periodic requests
- Real-time connection status on screen
- Periodic screenshot push (configurable interval)
- Async/await architecture (non-blocking)

Setup:
1. Install: sudo pip3 install websockets
2. Copy plugin to /usr/local/share/pwnagotchi/custom-plugins/
3. Enable in config.toml: [main.plugins.pwn-companion] enabled = true
4. Tether with Android device; app broadcasts endpoint via UDP:8888
5. Plugin auto-connects via WebSocket

Configuration (config.toml):

    [main.plugins.pwn-companion]
    enabled = true
    show_on_screen = true                       # Show status on display
    status_position = [0, 0]                    # Position for status display [x, y]
    show_latitude = true                        # Show latitude on display
    latitude_position = [0, 72]                 # Position for latitude display [x, y]
    show_longitude = true                       # Show longitude on display
    longitude_position = [0, 82]                # Position for longitude display [x, y]
    show_accuracy = true                        # Show GPS accuracy on display
    accuracy_position = [0, 92]                 # Position for accuracy display [x, y]
    show_altitude = true                        # Show GPS altitude on display
    altitude_position = [0, 102]                # Position for altitude display [x, y]
    push_image_interval = 0                     # Push screenshot every N seconds (0 = disabled)
    request_gps_interval = 5                    # Request GPS every N seconds (0 = disabled)

Mobile App Protocol:

    App announces via UDP:8888:
    {"type": "announce", "endpoint": "ws://192.168.x.x:8081", ...}

    Send Custom Command:
    {"type": "command", "action": "do_something", "params": {"key": "value"}}

    Send GPS:
    {"type": "gps", "latitude": 37.7749, "longitude": -122.4194, "accuracy": 10, "altitude": 50}

    Request Status:
    {"type": "status_request"}

    Request GPS (sent by plugin):
    {"type": "gps_request"}

    Image Response (sent by plugin):
    {"type": "image", "data": "<base64>", "content_type": "image/png", "timestamp": 1234567890.5}

GPS Data Persistence:
- GPS coordinates are automatically saved to .gps.json files alongside captured .pcap files
- Each handshake capture includes location data from the last GPS update
"""

import logging
import json
import asyncio
import threading
import socket
import time
import base64
import requests

try:
    import websockets
except ImportError:
    websockets = None

from pwnagotchi.plugins import Plugin
from flask import jsonify
from pwnagotchi.ui.components import LabeledValue
from pwnagotchi.ui.view import BLACK
import pwnagotchi.ui.fonts as fonts


log = logging.getLogger(__name__)

# Suppress verbose websockets handshake errors
logging.getLogger("websockets").setLevel(logging.WARNING)
logging.getLogger("websockets.server").setLevel(logging.WARNING)
logging.getLogger("websockets.protocol").setLevel(logging.WARNING)
logging.getLogger("websockets.asyncio").setLevel(logging.WARNING)
logging.getLogger("websockets.asyncio.server").setLevel(logging.WARNING)


# Custom filter to suppress only specific noisy errors
class HandshakeErrorFilter(logging.Filter):
    def filter(self, record):
        msg = record.getMessage().lower()
        # Suppress only the specific "stream ends after 0 bytes" noise, keep other errors
        if (
            "stream ends after 0 bytes" in msg
            or "connection closed while reading" in msg
        ):
            return False
        return True


# Apply filter to websockets loggers
for logger_name in [
    "websockets",
    "websockets.server",
    "websockets.protocol",
    "websockets.asyncio",
    "websockets.asyncio.server",
]:
    logging.getLogger(logger_name).addFilter(HandshakeErrorFilter())

# ============================================================
#  Pwn Companion Plugin
# ============================================================


class PwnCompanion(Plugin):
    __author__ = "wsvdmeer"
    __version__ = "2.0.0"
    __description__ = "WebSocket client for communication with pwn-companion android app (app-hosted server)"

    csrf_exempt = True

    def __init__(self):
        # UI config
        self.show_on_screen = True
        self.status_position = [0, 0]
        self.show_latitude = True
        self.latitude_position = [0, 72]
        self.show_longitude = True
        self.longitude_position = [0, 82]
        self.show_accuracy = True
        self.accuracy_position = [0, 92]
        self.show_altitude = True
        self.altitude_position = [0, 102]

        # Periodic sync config
        self.push_image_interval = 1  # 0 = disabled, >0 = seconds between pushes
        self.request_gps_interval = 5  # Request GPS every 5 seconds by default

        # State
        self.discovering = False
        self.app_websocket = None
        self.app_connected = False
        self.app_endpoint = None
        self.discovery_task = None
        self.listen_task = None
        self.periodic_tasks = []
        self.lock = threading.Lock()

        # Data storage
        self.last_gps = None
        self.last_command = None
        self.start_time = time.time()

        # Device info
        self.device_name = "pwnagotchi"
        self.device_status = "initialized"

        # Network info
        self.current_ip = "unknown"
        self.tether_interface = None

        # UI components
        self.status_label = None
        self.latitude_label = None
        self.longitude_label = None
        self.accuracy_label = None
        self.altitude_label = None

        # Event loop for async operations
        self.loop = None

        if websockets is None:
            log.warning(
                "[pwn-companion] websockets not installed. Install with: pip3 install websockets"
            )

        log.info("[pwn-companion] Plugin initialized")

    def on_loaded(self):
        """Plugin loaded"""
        # Load UI config options
        if "show_on_screen" in self.options:
            self.show_on_screen = self.options["show_on_screen"]
        if "status_position" in self.options:
            self.status_position = self.options["status_position"]
        if "show_latitude" in self.options:
            self.show_latitude = self.options["show_latitude"]
        if "latitude_position" in self.options:
            self.latitude_position = self.options["latitude_position"]
        if "show_longitude" in self.options:
            self.show_longitude = self.options["show_longitude"]
        if "longitude_position" in self.options:
            self.longitude_position = self.options["longitude_position"]
        if "show_accuracy" in self.options:
            self.show_accuracy = self.options["show_accuracy"]
        if "accuracy_position" in self.options:
            self.accuracy_position = self.options["accuracy_position"]
        if "show_altitude" in self.options:
            self.show_altitude = self.options["show_altitude"]
        if "altitude_position" in self.options:
            self.altitude_position = self.options["altitude_position"]

        # Load periodic sync config
        if "push_image_interval" in self.options:
            self.push_image_interval = self.options["push_image_interval"]
        if "request_gps_interval" in self.options:
            self.request_gps_interval = self.options["request_gps_interval"]

        if websockets is None:
            log.error("[pwn-companion] websockets library not installed, aborting")
            return

        log.info(
            f"[pwn-companion] Plugin loaded. Image push: {self.push_image_interval}s, "
            f"GPS request: {self.request_gps_interval}s"
        )

    def on_unloaded(self):
        """Plugin unloaded"""
        log.info("[pwn-companion] Plugin unloading")
        self._stop_client_discovery()

    def on_ui_setup(self, ui):
        """Setup UI components"""
        if self.show_on_screen:
            self.status_label = LabeledValue(
                label="PWN:",
                value="○ 0x",
                position=tuple(self.status_position),
                label_font=fonts.Small,
                text_font=fonts.Small,
                color=BLACK,
            )
            ui.add_element("pwn_companion_status", self.status_label)

            if self.show_latitude:
                self.latitude_label = LabeledValue(
                    color=BLACK,
                    label="LAT:",
                    value="--",
                    position=tuple(self.latitude_position),
                    label_font=fonts.Small,
                    text_font=fonts.Small,
                )
                ui.add_element("pwn_companion_latitude", self.latitude_label)

            if self.show_longitude:
                self.longitude_label = LabeledValue(
                    color=BLACK,
                    label="LNG:",
                    value="--",
                    position=tuple(self.longitude_position),
                    label_font=fonts.Small,
                    text_font=fonts.Small,
                )
                ui.add_element("pwn_companion_longitude", self.longitude_label)

            if self.show_accuracy:
                self.accuracy_label = LabeledValue(
                    color=BLACK,
                    label="ACC:",
                    value="--",
                    position=tuple(self.accuracy_position),
                    label_font=fonts.Small,
                    text_font=fonts.Small,
                )
                ui.add_element("pwn_companion_accuracy", self.accuracy_label)

            if self.show_altitude:
                self.altitude_label = LabeledValue(
                    color=BLACK,
                    label="ALT:",
                    value="--",
                    position=tuple(self.altitude_position),
                    label_font=fonts.Small,
                    text_font=fonts.Small,
                )
                ui.add_element("pwn_companion_altitude", self.altitude_label)

    def on_ui_update(self, ui):
        """Update UI display"""
        with self.lock:
            gps_snapshot = self.last_gps
            app_connected = self.app_connected

        if self.status_label:
            # Show connection indicator: ● if connected to app, ○ if not
            indicator = "●" if app_connected else "○"
            self.status_label.value = indicator

        if gps_snapshot and app_connected:
            lat = gps_snapshot.get("latitude", 0)
            lon = gps_snapshot.get("longitude", 0)
            acc = gps_snapshot.get("accuracy", 0)
            alt = gps_snapshot.get("altitude", 0)

            if self.latitude_label:
                self.latitude_label.value = f"{lat:.8f}"
            if self.longitude_label:
                self.longitude_label.value = f"{lon:.8f}"
            if self.accuracy_label:
                self.accuracy_label.value = f"±{acc:.1f}m"
            if self.altitude_label:
                self.altitude_label.value = f"{alt:.1f}m"
        else:
            # No GPS data - show placeholders
            if self.latitude_label:
                self.latitude_label.value = "--"
            if self.longitude_label:
                self.longitude_label.value = "--"
            if self.accuracy_label:
                self.accuracy_label.value = "--"
            if self.altitude_label:
                self.altitude_label.value = "--"

    def on_bt_tether_connected(self, agent, event_data):
        """Handle bt-tether connected event - start discovery"""
        try:
            ip = event_data.get("ip")
            iface = event_data.get("interface")
            device = event_data.get("device", "unknown")

            if ip and ip != "unknown":
                self.current_ip = ip
                self.tether_interface = iface
                log.info(
                    f"[pwn-companion] ✓ bt-tether connected: {self.current_ip} via {iface} ({device})"
                )
                # Start discovery (pass the interface IP for UDP listening)
                self._start_client_discovery(iface)
        except Exception as e:
            log.error(f"[pwn-companion] Error in bt_tether_connected: {e}")

    def on_bt_tether_disconnected(self, agent, event_data):
        """Handle bt-tether disconnected event - stop discovery"""
        self.tether_interface = None
        self.current_ip = "unknown"
        log.info("[pwn-companion] bt-tether disconnected")
        self._stop_client_discovery()

    def on_handshake(self, agent, filename, access_point, client_station):
        """Save GPS data when a handshake is captured"""
        try:
            if not self.last_gps:
                return

            # Only save if we have valid coordinates
            lat = self.last_gps.get("latitude", 0)
            lon = self.last_gps.get("longitude", 0)

            if lat == 0 and lon == 0:
                log.debug("[pwn-companion] Skipping GPS save - no valid coordinates")
                return

            # Create GPS filename alongside the pcap
            gps_filename = filename.replace(".pcap", ".gps.json")

            # Prepare GPS data
            gps_data = {
                "latitude": self.last_gps.get("latitude"),
                "longitude": self.last_gps.get("longitude"),
                "accuracy": self.last_gps.get("accuracy"),
                "altitude": self.last_gps.get("altitude"),
                "timestamp": self.last_gps.get("timestamp"),
            }

            # Save GPS data
            with open(gps_filename, "w") as fp:
                json.dump(gps_data, fp, indent=2)

            log.info(
                f"[pwn-companion] ✓ GPS data saved to {gps_filename} "
                f"(lat: {lat:.6f}, lon: {lon:.6f})"
            )

        except Exception as e:
            log.error(f"[pwn-companion] Error saving GPS on handshake: {e}")

    def _start_client_discovery(self, iface=None):
        """Start UDP discovery + WebSocket client in background thread"""
        if self.discovering:
            return

        self.discovering = True
        self.loop = asyncio.new_event_loop()
        self.ws_thread = threading.Thread(
            target=self._run_discovery,
            args=(iface,),
            daemon=True,
            name="pwn-companion-discovery",
        )
        self.ws_thread.start()
        iface_str = f" on {iface}" if iface else ""
        log.info(
            f"[pwn-companion] 🔍 Discovery started, listening on UDP:8888{iface_str}"
        )

    def _run_discovery(self, iface=None):
        """Run discovery + connection in event loop"""
        try:
            asyncio.set_event_loop(self.loop)
            self.loop.run_until_complete(self._discovery_loop(iface))
        except Exception as e:
            log.error(f"[pwn-companion] Discovery error: {e}")
            self.discovering = False
        finally:
            try:
                if self.app_websocket:
                    self.loop.run_until_complete(self.app_websocket.close())
            except:
                pass
            try:
                self.loop.close()
            except:
                pass
            log.info("[pwn-companion] Discovery loop stopped")

    async def _discovery_loop(self, iface=None):
        """Main discovery and connection loop"""
        udp_socket = None
        last_connection_attempt = 0
        connection_retry_delay = 1  # Start with 1s, backoff up to 30s
        consecutive_failures = 0  # Track failed connection attempts
        MAX_FAILURES_BEFORE_RESET = 5  # Reset to listening after 5 failures

        try:
            # Create UDP socket for discovering announcements
            udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

            # If interface is provided, bind to the broadcast address on that interface
            # For receiving broadcasts, we should bind to 0.0.0.0 but on the specific interface
            if iface:
                try:
                    # On Linux, use SO_BINDTODEVICE to bind to specific interface (bnep0)
                    import socket as socket_module

                    SO_BINDTODEVICE = 25
                    udp_socket.setsockopt(
                        socket.SOL_SOCKET, SO_BINDTODEVICE, iface.encode()
                    )
                    log.debug(f"[pwn-companion] Bound UDP socket to interface {iface}")
                except (AttributeError, OSError) as e:
                    log.debug(
                        f"[pwn-companion] Could not bind to interface {iface}: {e}, using all interfaces"
                    )

            # Bind to all interfaces on port 8888
            udp_socket.bind(("", 8888))
            udp_socket.setblocking(False)
            log.info(
                f"[pwn-companion] UDP socket listening on :8888 (broadcast enabled)"
                + (f" on {iface}" if iface else "")
            )

            loop = asyncio.get_event_loop()

            while self.discovering:
                # Try to receive announcement using asyncio's socket wrapper
                try:
                    data, addr = await asyncio.wait_for(
                        loop.sock_recvfrom(udp_socket, 1024), timeout=2.0
                    )
                    try:
                        msg = json.loads(data.decode("utf-8"))
                        log.info(
                            f"[pwn-companion] 📨 UDP received from {addr}: type={msg.get('type')}"
                        )

                        if msg.get("type") == "announce":
                            endpoint = msg.get("endpoint")
                            ip = msg.get("ip")
                            port = msg.get("port")

                            if endpoint and endpoint != self.app_endpoint:
                                self.app_endpoint = endpoint
                                log.info(
                                    f"[pwn-companion] 📢 App announcement: {ip}:{port} → {endpoint}"
                                )
                                # Reset backoff + error counter on new announcement
                                connection_retry_delay = 1
                                last_connection_attempt = 0
                                consecutive_failures = 0
                                # Try to connect
                                await self._connect_to_app()
                    except json.JSONDecodeError as je:
                        log.debug(f"[pwn-companion] Invalid JSON from {addr}: {je}")
                    except Exception as parse_ex:
                        log.debug(
                            f"[pwn-companion] Error parsing announcement: {parse_ex}"
                        )

                except asyncio.TimeoutError:
                    pass  # No announcement received within timeout, continue
                except Exception as e:
                    log.debug(f"[pwn-companion] UDP receive error: {type(e).__name__}")

                # Check if we've had too many failures - reset and listen for new announcement
                if (
                    self.app_endpoint
                    and consecutive_failures >= MAX_FAILURES_BEFORE_RESET
                ):
                    log.warning(
                        f"[pwn-companion] ⚠️ {consecutive_failures} connection failures to {self.app_endpoint}, "
                        f"resetting to listen for new announcements"
                    )
                    self.app_endpoint = None
                    connection_retry_delay = 1
                    last_connection_attempt = 0
                    consecutive_failures = 0
                    continue

                # Try to connect if we have endpoint but no connection (with backoff)
                now = time.time()
                if (
                    self.app_endpoint
                    and not self.app_connected
                    and not self.app_websocket
                    and (now - last_connection_attempt) >= connection_retry_delay
                ):
                    last_connection_attempt = now
                    log.debug(
                        f"[pwn-companion] Attempting reconnection (retry delay: {connection_retry_delay}s, failures: {consecutive_failures}/{MAX_FAILURES_BEFORE_RESET})..."
                    )
                    try:
                        await self._connect_to_app()
                        # Reset backoff + error counter on successful connection
                        connection_retry_delay = 1
                        consecutive_failures = 0
                    except asyncio.TimeoutError:
                        log.warning(
                            f"[pwn-companion] ⏱️ Connection timeout to {self.app_endpoint}"
                        )
                        consecutive_failures += 1
                        # Increase backoff delay up to 30s
                        connection_retry_delay = min(30, connection_retry_delay * 1.5)
                    except Exception as ce:
                        log.warning(
                            f"[pwn-companion] ❌ Connection failed: {type(ce).__name__}: {str(ce)[:60]}"
                        )
                        consecutive_failures += 1
                        # Increase backoff delay up to 30s
                        connection_retry_delay = min(30, connection_retry_delay * 1.5)

                # Brief sleep to prevent busy-waiting
                await asyncio.sleep(0.1)

        except Exception as e:
            log.error(
                f"[pwn-companion] Discovery loop error: {type(e).__name__}: {e}",
                exc_info=True,
            )
        finally:
            if udp_socket:
                try:
                    udp_socket.close()
                except:
                    pass
            self.discovering = False
            with self.lock:
                self.app_websocket = None
                self.app_connected = False
            log.info("[pwn-companion] Discovery loop ended")

    async def _connect_to_app(self):
        """Connect to app's WebSocket endpoint"""
        if not self.app_endpoint or self.app_connected:
            return

        try:
            log.info(f"[pwn-companion] 🔗 Connecting to {self.app_endpoint}...")
            self.app_websocket = await asyncio.wait_for(
                websockets.connect(self.app_endpoint), timeout=5.0
            )
            with self.lock:
                self.app_connected = True
            log.info(f"[pwn-companion] ✓ Connected to app!")

            # Send ready signal to initiate app polling (on both initial connect and reconnect)
            log.info(
                f"[pwn-companion] 📡 Sending READY signal (initial or reconnect)..."
            )
            await self._send_to_app({"type": "ready"})
            log.info("[pwn-companion] ✓ Ready signal sent to app")

            # Send initial status message
            await self._send_status_message("Connected to companion app")

            # Start periodic tasks (image push, GPS requests)
            self._start_periodic_tasks()

            # Listen for messages from app
            await self._listen_to_app()
        except asyncio.TimeoutError:
            log.warning(
                f"[pwn-companion] ⏱️ Connection timeout (5s) to {self.app_endpoint}"
            )
        except websockets.exceptions.InvalidStatus as ise:
            # HTTP error during WebSocket handshake
            log.warning(
                f"[pwn-companion] ❌ HTTP {ise.status} during WebSocket handshake: {ise.reason}"
            )
            log.warning(
                f"[pwn-companion] ⚠️ Check if app is running and listening on :8081"
            )
        except websockets.exceptions.WebSocketException as e:
            log.warning(
                f"[pwn-companion] ❌ WebSocket error: {type(e).__name__}: {str(e)[:80]}"
            )
        except ConnectionRefusedError as e:
            log.warning(f"[pwn-companion] ❌ Connection refused by {self.app_endpoint}")
        except OSError as e:
            log.warning(
                f"[pwn-companion] ❌ Network error: {type(e).__name__}: {str(e)[:80]}"
            )
        except Exception as e:
            log.warning(
                f"[pwn-companion] ❌ Connection error: {type(e).__name__}: {str(e)[:80]}"
            )
        finally:
            # Cancel periodic tasks
            self._stop_periodic_tasks()
            with self.lock:
                self.app_connected = False
                self.app_websocket = None

    async def _listen_to_app(self):
        """Listen for messages from connected app"""
        try:
            async for message in self.app_websocket:
                try:
                    await self._handle_message(message)
                except Exception as e:
                    log.error(f"[pwn-companion] Message handler error: {e}")
        except websockets.ConnectionClosed as cc:
            log.info(
                f"[pwn-companion] 🔌 Connection closed by app "
                f"(code: {cc.rcvd.code if cc.rcvd else 'N/A'}, "
                f"reason: {cc.rcvd.reason if cc.rcvd else 'unknown'})"
            )
            # Clear endpoint to force listening for new announcements instead of retrying
            log.info(
                "[pwn-companion] ⏸️ Clearing endpoint, will wait for new announcements..."
            )
            self.app_endpoint = None
        except Exception as e:
            log.warning(
                f"[pwn-companion] ⚠️ Listen error: {type(e).__name__}: {str(e)[:80]}"
            )

    def _start_periodic_tasks(self):
        """Start periodic background tasks (image push, GPS requests)"""
        self.periodic_tasks = []

        # Start image push task if configured
        if self.push_image_interval > 0:
            task = asyncio.create_task(self._periodic_image_push())
            self.periodic_tasks.append(task)
            log.info(
                f"[pwn-companion] 📸 Periodic image push started ({self.push_image_interval}s)"
            )

        # Start GPS request task if configured
        if self.request_gps_interval > 0:
            task = asyncio.create_task(self._periodic_gps_request())
            self.periodic_tasks.append(task)
            log.info(
                f"[pwn-companion] 📍 Periodic GPS request started ({self.request_gps_interval}s)"
            )

    def _stop_periodic_tasks(self):
        """Stop all periodic background tasks"""
        for task in self.periodic_tasks:
            if task and not task.done():
                task.cancel()
        self.periodic_tasks = []

    async def _periodic_image_push(self):
        """Periodically fetch and push screenshot to app"""
        while self.app_connected:
            try:
                await asyncio.sleep(self.push_image_interval)
                if self.app_connected:
                    await self._handle_image_request()
            except asyncio.CancelledError:
                log.debug("[pwn-companion] Image push task cancelled")
                break
            except Exception as e:
                log.error(
                    f"[pwn-companion] Periodic image push error: {type(e).__name__}: {str(e)[:80]}"
                )
                await asyncio.sleep(1)  # Brief delay before retry

    async def _periodic_gps_request(self):
        """Periodically request GPS data from app"""
        while self.app_connected:
            try:
                await asyncio.sleep(self.request_gps_interval)
                if self.app_connected:
                    await self._send_to_app(
                        {"type": "gps_request", "timestamp": int(time.time())}
                    )
                    log.debug("[pwn-companion] 📍 GPS request sent")
            except asyncio.CancelledError:
                log.debug("[pwn-companion] GPS request task cancelled")
                break
            except Exception as e:
                log.error(
                    f"[pwn-companion] Periodic GPS request error: {type(e).__name__}: {str(e)[:80]}"
                )
                await asyncio.sleep(1)  # Brief delay before retry

    async def _handle_message(self, message: str):
        """Handle incoming WebSocket message from app"""
        try:
            log.debug(f"[pwn-companion] Processing message: {message[:100]}")

            data = json.loads(message)
            msg_type = data.get("type")

            log.debug(f"[pwn-companion] Message type: {msg_type}")

            # Process messages
            try:
                if msg_type == "command":
                    await self._handle_command(data)
                elif msg_type == "gps":
                    await self._handle_gps(data)
                elif msg_type == "gps_response":
                    await self._handle_gps(data)  # App responding to our gps_request
                elif msg_type == "status_request":
                    await self._handle_status_request()
                elif msg_type == "image_request":
                    log.info(f"[pwn-companion] Processing image request")
                    await self._handle_image_request()
                elif msg_type == "ready":
                    # App acknowledging ready signal
                    log.info(f"[pwn-companion] App acknowledged ready signal")
                else:
                    log.warning(f"[pwn-companion] Unknown message type: {msg_type}")
                    await self._send_to_app(
                        {
                            "type": "error",
                            "message": f"Unknown message type: {msg_type}",
                        },
                    )
            except websockets.ConnectionClosed:
                log.warning(
                    f"[pwn-companion] Connection closed while handling {msg_type}"
                )
                raise
            except Exception as handler_ex:
                log.error(
                    f"[pwn-companion] Error in {msg_type} handler: {type(handler_ex).__name__}: {handler_ex}",
                    exc_info=True,
                )
                try:
                    await self._send_to_app(
                        {
                            "type": "error",
                            "message": f"Handler error: {str(handler_ex)[:100]}",
                        },
                    )
                except Exception as send_ex:
                    log.error(
                        f"[pwn-companion] Failed to send error message: {send_ex}"
                    )

        except json.JSONDecodeError as je:
            log.error(f"[pwn-companion] Invalid JSON: {je}")
            try:
                await self._send_to_app({"type": "error", "message": "Invalid JSON"})
            except Exception as send_ex:
                log.error(
                    f"[pwn-companion] Failed to send JSON error response: {send_ex}"
                )
        except websockets.ConnectionClosed:
            log.warning(f"[pwn-companion] Connection closed during message processing")
            raise
        except Exception as e:
            log.error(
                f"[pwn-companion] Error processing message: {type(e).__name__}: {e}",
                exc_info=True,
            )

    async def _handle_command(self, data: dict):
        """Handle custom command from mobile app"""
        action = data.get("action")
        params = data.get("params", {})

        log.info(f"[pwn-companion] Command received: {action}, params: {params}")

        with self.lock:
            self.last_command = {
                "action": action,
                "params": params,
                "timestamp": time.time(),
            }

        # Send confirmation
        await self._send_to_app({"type": "command_received", "action": action})

        # TODO: Execute the command based on action
        # Example: if action == "scan": trigger_scan()
        # if action == "shutdown": shutdown_pwnagotchi()
        self.execute_command(action, params)

    async def _handle_gps(self, data: dict):
        """Handle GPS coordinate update from mobile app"""
        try:
            latitude = float(data.get("latitude"))
            longitude = float(data.get("longitude"))
            accuracy = float(data.get("accuracy", 0))
            altitude = float(data.get("altitude", 0))

            log.info(
                f"[pwn-companion] ✓ GPS received: {latitude:.6f}, {longitude:.6f} (±{accuracy:.1f}m, alt:{altitude:.1f}m)"
            )

            with self.lock:
                self.last_gps = {
                    "latitude": latitude,
                    "longitude": longitude,
                    "accuracy": accuracy,
                    "altitude": altitude,
                    "timestamp": time.time(),
                }

            # Send confirmation
            response = {
                "type": "gps_received",
                "lat": latitude,
                "lon": longitude,
            }
            await self._send_to_app(response)
            log.debug(f"[pwn-companion] GPS confirmation sent")

            # TODO: Store GPS or trigger location-based actions

        except (ValueError, TypeError) as e:
            log.error(f"[pwn-companion] Invalid GPS data: {type(e).__name__}: {e}")
            await self._send_to_app({"type": "error", "message": "Invalid GPS data"})
        except Exception as e:
            log.error(
                f"[pwn-companion] Error in GPS handler: {type(e).__name__}: {e}",
                exc_info=True,
            )
            await self._send_to_app(
                {
                    "type": "error",
                    "message": f"GPS handler error: {str(e)[:100]}",
                },
            )

    async def _handle_status_request(self):
        """Send pwnagotchi status to app"""
        with self.lock:
            uptime = int(time.time() - self.start_time)

        status = {
            "type": "status",
            "uptime": uptime,
            "connected": self.app_connected,
            "last_gps": self.last_gps,
            "last_command": self.last_command,
        }

        await self._send_to_app(status)
        log.debug(f"[pwn-companion] Status sent to app")

    async def _handle_image_request(self):
        """Handle image request from mobile app - fetch UI screenshot and send to app"""
        try:
            log.info(f"[pwn-companion] 📸 Image request received from app")

            # Fetch the UI screenshot from pwnagotchi web interface
            url = "http://127.0.0.1:8080/ui"
            log.info(f"[pwn-companion] 🌐 Fetching screenshot from {url}...")

            try:
                loop = asyncio.get_event_loop()
                response = await loop.run_in_executor(
                    None, lambda: requests.get(url, timeout=10)
                )
                log.info(
                    f"[pwn-companion] ✓ Got response from UI: status={response.status_code}, size={len(response.content)} bytes"
                )
                response.raise_for_status()
            except requests.exceptions.Timeout as te:
                log.error(f"[pwn-companion] ❌ TIMEOUT fetching screenshot: {te}")
                await self._send_to_app(
                    {"type": "error", "message": f"UI server timeout: {str(te)}"},
                )
                return
            except requests.exceptions.ConnectionError as ce:
                log.error(
                    f"[pwn-companion] ❌ CONNECTION ERROR fetching screenshot: {ce}"
                )
                await self._send_to_app(
                    {"type": "error", "message": f"Cannot connect to UI at {url}"},
                )
                return
            except requests.exceptions.HTTPError as he:
                log.error(
                    f"[pwn-companion] ❌ HTTP ERROR {response.status_code} from UI"
                )
                await self._send_to_app(
                    {
                        "type": "error",
                        "message": f"UI returned HTTP {response.status_code}",
                    },
                )
                return
            except Exception as re:
                log.error(f"[pwn-companion] ❌ ERROR fetching screenshot: {re}")
                await self._send_to_app(
                    {
                        "type": "error",
                        "message": f"Failed to fetch screenshot: {str(re)}",
                    },
                )
                return

            # Ensure content is bytes before encoding
            if isinstance(response.content, bytearray):
                image_bytes = bytes(response.content)
            else:
                image_bytes = response.content

            log.info(
                f"[pwn-companion] Converting {len(image_bytes)} bytes to base64..."
            )

            # Send image without caching (lightweight - no image hashing)
            image_data = base64.b64encode(image_bytes).decode("utf-8")
            log.info(
                f"[pwn-companion] ✓ Encoded to base64: {len(image_data)} characters"
            )

            # Create response object with proper JSON serialization
            response_obj = {
                "type": "image",
                "data": image_data,
                "content_type": response.headers.get("content-type", "image/png"),
                "timestamp": int(time.time()),
            }

            log.info(
                f"[pwn-companion] 📤 Sending image message (payload size: {len(image_data)} chars)..."
            )
            await self._send_to_app(response_obj)

            log.info(
                f"[pwn-companion] ✓✓✓ Image successfully sent to app ({len(image_bytes)} bytes)"
            )

        except Exception as e:
            log.error(
                f"[pwn-companion] ❌ CRITICAL ERROR in image handler: {type(e).__name__}: {e}",
                exc_info=True,
            )
            try:
                await self._send_to_app(
                    {"type": "error", "message": f"Image error: {str(e)[:100]}"},
                )
            except:
                log.error("[pwn-companion] Failed to send error response to app")

    async def _send_status_message(self, message: str):
        """Send status message to app (on connection or important events)"""
        status_obj = {
            "type": "status",
            "message": message,
            "device_name": self.device_name,
            "status": "running",
            "timestamp": int(time.time()),
        }
        await self._send_to_app(status_obj)
        log.info(f"[pwn-companion] 📊 Status sent: {message}")

    async def _send_to_app(self, data: dict):
        """Send JSON message to app"""
        if not self.app_websocket or not self.app_connected:
            log.debug(
                f"[pwn-companion] Not connected to app, cannot send {data.get('type')}"
            )
            return

        try:
            msg_json = json.dumps(data)
            await self.app_websocket.send(msg_json)
            log.debug(f"[pwn-companion] ✓ Message sent to app: {data.get('type')}")
        except websockets.ConnectionClosed:
            log.warning(f"[pwn-companion] App connection closed, cannot send message")
            with self.lock:
                self.app_connected = False
                self.app_websocket = None
        except Exception as e:
            log.error(f"[pwn-companion] Error sending to app: {type(e).__name__}: {e}")
            with self.lock:
                self.app_connected = False
                self.app_websocket = None

    def on_webhook(self, response, path):
        """Handle web requests to /plugins/pwn-companion/"""
        return jsonify(
            {
                "status": "running",
                "connected": self.app_connected,
                "endpoint": self.app_endpoint,
                "discovering": self.discovering,
            }
        )

    # Optional: Add more command handlers below
    def execute_command(self, action, params):
        """Execute command based on action type"""
        try:
            if action == "scan":
                # Trigger WiFi scan
                log.info("[pwn-companion] Executing scan command")
                # TODO: Implement scan
                pass

            elif action == "status":
                # Return status
                log.info("[pwn-companion] Executing status command")
                # TODO: Implement status return
                pass

            elif action == "message":
                # Display message on screen
                msg = params.get("text", "")
                log.info(f"[pwn-companion] Message: {msg}")
                # TODO: Implement message display
                pass

            else:
                log.warning(f"[pwn-companion] Unknown action: {action}")

        except Exception as e:
            log.error(f"[pwn-companion] Command execution error: {e}")

    def _stop_client_discovery(self):
        """Stop discovery and close WebSocket connection"""
        self.discovering = False

        # Close WebSocket if open
        if self.app_websocket:
            try:
                if not self.loop.is_closed():
                    self.loop.run_until_complete(self.app_websocket.close())
            except Exception as e:
                log.debug(f"[pwn-companion] Error closing websocket: {e}")
            self.app_websocket = None

        # Stop the event loop
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)

        # Wait for thread to finish
        if self.ws_thread:
            self.ws_thread.join(timeout=5)

        log.info("[pwn-companion] Client discovery stopped")
