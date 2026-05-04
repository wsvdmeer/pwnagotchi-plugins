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
    push_image_interval = 1                     # Push screenshot every N seconds (0 = disabled)
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


# ============================================================
#  AI Event Broadcaster - Sends WiFi Events to App for LLM
# ============================================================


class PwnagotchiEventBroadcaster:
    """
    Sends rich WiFi event data to the companion app for LLM personality responses
    Enables the Pwnagotchi AI to react to WiFi events in real-time
    """

    def __init__(self, websocket_send_func):
        """
        Args:
            websocket_send_func: Reference to plugin's _send_to_app method
        """
        self.send_to_app = websocket_send_func
        self.handshake_count = 0
        self.networks_discovered = set()
        log.info("[pwn-companion] 🤖 Event broadcaster initialized")

    async def on_handshakes_captured(
        self, count: int, network_name: str, security: str = "WPA2"
    ):
        """
        Called when Pwnagotchi captures handshakes

        Args:
            count: Number of handshakes captured in this burst
            network_name: SSID of the network
            security: Security type (WPA2, WPA3, Open, etc.)
        """
        try:
            self.handshake_count += count

            event = {
                "type": "network_event",
                "event_type": "handshakes_captured",
                "count": count,
                "network": network_name,
                "security": security,
                "total_captures": self.handshake_count,
                "timestamp": int(time.time()),
                "description": f"Captured {count} handshake{'s' if count != 1 else ''} from {network_name} ({security})",
            }

            log.info(f"[pwn-companion] 🤖 AI Event: {event['description']}")
            await self.send_to_app(event)
        except Exception as e:
            log.error(f"[pwn-companion] Error in on_handshakes_captured: {e}")

    async def on_network_discovered(
        self,
        ssid: str,
        bssid: str = None,
        security: str = "Unknown",
        signal_strength: int = -50,
        channel: int = 1,
    ):
        """
        Called when a new network is discovered

        Args:
            ssid: Network name
            bssid: MAC address of access point
            security: Security type
            signal_strength: Signal strength in dBm
            channel: WiFi channel
        """
        try:
            is_new = ssid not in self.networks_discovered
            self.networks_discovered.add(ssid)

            event = {
                "type": "network_event",
                "event_type": "network_discovered",
                "network": ssid,
                "bssid": bssid or "unknown",
                "security": security,
                "signal": signal_strength,
                "channel": channel,
                "is_new": is_new,
                "timestamp": int(time.time()),
                "description": f"Found network: {ssid} on CH{channel} ({security}, {signal_strength}dBm)",
            }

            if is_new:
                log.info(f"[pwn-companion] 🤖 AI Event: {event['description']}")
                await self.send_to_app(event)
        except Exception as e:
            log.error(f"[pwn-companion] Error in on_network_discovered: {e}")

    async def on_connection_success(self, network_name: str, duration: float = 0.0):
        """
        Called when successfully connected to a network

        Args:
            network_name: SSID
            duration: Connection time in seconds
        """
        try:
            event = {
                "type": "network_event",
                "event_type": "connection_success",
                "network": network_name,
                "duration": duration,
                "timestamp": int(time.time()),
                "description": f"Successfully connected to {network_name}"
                + (f" in {duration:.1f}s" if duration > 0 else ""),
            }

            log.info(f"[pwn-companion] 🤖 AI Event: {event['description']}")
            await self.send_to_app(event)
        except Exception as e:
            log.error(f"[pwn-companion] Error in on_connection_success: {e}")

    async def on_connection_failure(self, network_name: str, reason: str = "Unknown"):
        """
        Called when connection fails

        Args:
            network_name: SSID
            reason: Failure reason
        """
        try:
            event = {
                "type": "network_event",
                "event_type": "connection_failure",
                "network": network_name,
                "reason": reason,
                "timestamp": int(time.time()),
                "description": f"Failed to connect to {network_name}: {reason}",
            }

            log.warning(f"[pwn-companion] 🤖 AI Event: {event['description']}")
            await self.send_to_app(event)
        except Exception as e:
            log.error(f"[pwn-companion] Error in on_connection_failure: {e}")

    async def on_anomaly_detected(self, anomaly_type: str, details: dict = None):
        """
        Called when an anomaly is detected in network activity

        Args:
            anomaly_type: Type of anomaly (deauth_spike, unusual_probe, etc.)
            details: Additional details about the anomaly
        """
        try:
            event = {
                "type": "network_event",
                "event_type": "anomaly_detected",
                "anomaly_type": anomaly_type,
                "details": details or {},
                "timestamp": int(time.time()),
                "description": f"Anomaly detected: {anomaly_type}",
            }

            log.warning(f"[pwn-companion] 🤖 AI Event: {event['description']}")
            await self.send_to_app(event)
        except Exception as e:
            log.error(f"[pwn-companion] Error in on_anomaly_detected: {e}")

    async def on_high_value_target(self, network_name: str, reason: str = ""):
        """
        Called when a high-value target (WPA3, Enterprise, etc.) is detected

        Args:
            network_name: SSID
            reason: Why it's considered high-value
        """
        try:
            event = {
                "type": "network_event",
                "event_type": "high_value_target",
                "network": network_name,
                "reason": reason,
                "timestamp": int(time.time()),
                "description": f"High-value target found: {network_name}"
                + (f" ({reason})" if reason else ""),
            }

            log.info(f"[pwn-companion] 🤖 AI Event: {event['description']}")
            await self.send_to_app(event)
        except Exception as e:
            log.error(f"[pwn-companion] Error in on_high_value_target: {e}")

    async def on_scan_complete(self, networks_found: int, duration: float = 0.0):
        """
        Called when a WiFi scan completes

        Args:
            networks_found: Number of networks discovered
            duration: Scan duration in seconds
        """
        try:
            event = {
                "type": "network_event",
                "event_type": "scan_complete",
                "networks_found": networks_found,
                "duration": duration,
                "total_unique_networks": len(self.networks_discovered),
                "timestamp": int(time.time()),
                "description": f"Scan complete: Found {networks_found} networks"
                + (f" in {duration:.1f}s" if duration > 0 else ""),
            }

            log.info(f"[pwn-companion] 🤖 AI Event: {event['description']}")
            await self.send_to_app(event)
        except Exception as e:
            log.error(f"[pwn-companion] Error in on_scan_complete: {e}")


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
#  Constants
# ============================================================

# Network configuration
UDP_DISCOVERY_PORT = 8888
UDP_BUFFER_SIZE = 1024
UDP_RECEIVE_TIMEOUT = 2.0

PWNAGOTCHI_UI_HOST = "127.0.0.1"
PWNAGOTCHI_UI_PORT = 8080
PWNAGOTCHI_UI_URL = f"http://{PWNAGOTCHI_UI_HOST}:{PWNAGOTCHI_UI_PORT}/ui"

# WebSocket configuration
WEBSOCKET_CONNECT_TIMEOUT = 5.0

# Connection retry configuration
INITIAL_RETRY_DELAY = 1  # seconds
MAX_RETRY_DELAY = 30  # seconds
RETRY_BACKOFF_FACTOR = 1.5
DISCOVERY_LOOP_SLEEP = 0.1  # seconds

# Request timeouts
IMAGE_REQUEST_TIMEOUT = 10  # seconds
PERIODIC_TASK_RETRY_SLEEP = 1  # seconds

# String formatting
LOG_STRING_TRUNCATE_LENGTH = 80
HANDLER_ERROR_TRUNCATE_LENGTH = 100
GPS_COORD_PRECISION = 6  # decimal places
LAT_LON_FORMAT_PRECISION = 8  # decimal places
ACCURACY_FORMAT_PRECISION = 1  # decimal place

# UI display configuration
DEFAULT_STATUS_POSITION = [0, 0]
DEFAULT_LAT_POSITION = [0, 72]
DEFAULT_LNG_POSITION = [0, 82]
DEFAULT_ACC_POSITION = [0, 92]
DEFAULT_ALT_POSITION = [0, 102]

# Default periodic request intervals
SESSION_REQUEST_GPS_INTERVAL = 5  # Request GPS every 5 seconds by default

# Thread timeout
THREAD_SHUTDOWN_TIMEOUT = 5  # seconds

# Socket constants
SO_BINDTODEVICE = 25  # Linux-specific socket option

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
        self.status_position = DEFAULT_STATUS_POSITION
        self.show_latitude = True
        self.latitude_position = DEFAULT_LAT_POSITION
        self.show_longitude = True
        self.longitude_position = DEFAULT_LNG_POSITION
        self.show_accuracy = True
        self.accuracy_position = DEFAULT_ACC_POSITION
        self.show_altitude = True
        self.altitude_position = DEFAULT_ALT_POSITION

        # Periodic sync config
        self.push_image_interval = 1  # 0 = disabled, >0 = seconds between pushes
        self.request_gps_interval = (
            SESSION_REQUEST_GPS_INTERVAL  # Request GPS every N seconds by default
        )

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
        self._agent = None  # Set when first agent event fires

        # Network info
        self.current_ip = "unknown"
        self.tether_interface = None

        # Per-channel stats collected from on_epoch — used for autotune_stats message.
        # Structure: {channel_int: {"handshakes": int, "deauths": int, "associations": int}}
        self._channel_stats = {}
        self._best_channel = None
        self._total_handshakes = 0  # running total across all epochs

        # UI components
        self.status_label = None
        self.latitude_label = None
        self.longitude_label = None
        self.accuracy_label = None
        self.altitude_label = None

        # Event loop for async operations
        self.loop = None
        self.ws_thread = None

        # AI Event Broadcaster - for personality responses
        self.event_broadcaster = None

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
                self.latitude_label.value = f"{lat:.{LAT_LON_FORMAT_PRECISION}f}"
            if self.longitude_label:
                self.longitude_label.value = f"{lon:.{LAT_LON_FORMAT_PRECISION}f}"
            if self.accuracy_label:
                self.accuracy_label.value = f"±{acc:.{ACCURACY_FORMAT_PRECISION}f}m"
            if self.altitude_label:
                self.altitude_label.value = f"{alt:.{ACCURACY_FORMAT_PRECISION}f}m"
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
        self._agent = agent  # Store for auto-tune access
        try:
            ip = event_data.get("ip")
            iface = event_data.get("interface")
            device = event_data.get("device", "unknown")

            log.info(
                f"[pwn-companion] 🔍 bt-tether event received: ip={ip}, interface={iface}, device={device}"
            )

            if ip and ip != "unknown":
                self.current_ip = ip
                self.tether_interface = iface
                self.device_name = device  # Capture device name from event data
                log.info(
                    f"[pwn-companion] ✅ bt-tether connected: {self.current_ip} via {iface} ({device})"
                )
                log.info(
                    f"[pwn-companion] 🔊 Starting UDP discovery on port {UDP_DISCOVERY_PORT}..."
                )
                # Start discovery (pass the interface for UDP listening)
                self._start_client_discovery(iface)
            else:
                log.warning(
                    f"[pwn-companion] ⚠️ bt-tether event missing required data: ip={ip}"
                )
        except Exception as e:
            log.error(f"[pwn-companion] Error in bt_tether_connected: {e}")

    def on_bt_tether_disconnected(self, agent, event_data):
        """Handle bt-tether disconnected event - stop discovery"""
        self.tether_interface = None
        self.current_ip = "unknown"
        log.info("[pwn-companion] bt-tether disconnected")
        self._stop_client_discovery()

    def on_handshake(self, agent, filename, access_point, client_station):
        """Save GPS data and fire AI event when a handshake is captured"""
        self._agent = agent
        try:
            ssid = access_point.get("hostname", "") or access_point.get(
                "essid", "unknown"
            )
            security = "WPA2"  # pwnagotchi primarily captures WPA2

            # Increment running total
            self._total_handshakes += 1

            # Fire AI network_event immediately — this is the main driver of AI responses
            if self.event_broadcaster and self.app_connected:
                asyncio.run_coroutine_threadsafe(
                    self.event_broadcaster.on_handshakes_captured(
                        count=1, network_name=ssid, security=security
                    ),
                    self.loop,
                )

            # Save GPS data alongside the pcap
            if not self.last_gps:
                return

            lat = self.last_gps.get("latitude", 0)
            lon = self.last_gps.get("longitude", 0)
            if lat == 0 and lon == 0:
                log.debug("[pwn-companion] Skipping GPS save - no valid coordinates")
                return

            gps_filename = filename.replace(".pcap", ".gps.json")
            gps_data = {
                "latitude": self.last_gps.get("latitude"),
                "longitude": self.last_gps.get("longitude"),
                "accuracy": self.last_gps.get("accuracy"),
                "altitude": self.last_gps.get("altitude"),
                "timestamp": self.last_gps.get("timestamp"),
            }
            with open(gps_filename, "w") as fp:
                json.dump(gps_data, fp, indent=2)
            log.info(
                f"[pwn-companion] ✓ GPS saved to {gps_filename} "
                f"(lat: {lat:.{GPS_COORD_PRECISION}f}, lon: {lon:.{GPS_COORD_PRECISION}f})"
            )
        except Exception as e:
            log.error(f"[pwn-companion] Error in on_handshake: {e}")

    def on_association(self, agent, ap):
        """Fire network_event when Pwnagotchi associates with an AP"""
        self._agent = agent
        try:
            ssid = ap.get("hostname", "") or ap.get("essid", "unknown")
            channel = ap.get("channel", 0)
            rssi = ap.get("rssi", -100)
            security = ap.get("encryption", "Unknown")
            bssid = ap.get("mac", None)

            log.info(f"[pwn-companion] 🔗 Association: {ssid} CH{channel} ({rssi}dBm)")

            if self.event_broadcaster and self.app_connected:
                asyncio.run_coroutine_threadsafe(
                    self.event_broadcaster.on_network_discovered(
                        ssid=ssid,
                        bssid=bssid,
                        security=security,
                        signal_strength=rssi,
                        channel=channel,
                    ),
                    self.loop,
                )
        except Exception as e:
            log.debug(f"[pwn-companion] Error in on_association: {e}")

    def on_deauthentication(self, agent, ap, station):
        """Fire AI event when Pwnagotchi sends a deauth packet"""
        self._agent = agent
        try:
            channel = ap.get("channel", 0) if isinstance(ap, dict) else 0
            ssid = (
                ap.get("hostname", "") or ap.get("essid", "unknown")
                if isinstance(ap, dict)
                else str(ap)
            )
            log.debug(f"[pwn-companion] 💀 Deauth: {ssid} CH{channel}")
            if self.event_broadcaster and self.app_connected:
                asyncio.run_coroutine_threadsafe(
                    self.event_broadcaster.on_anomaly_detected(
                        anomaly_type="deauthentication",
                        details={"channel": channel, "network": ssid},
                    ),
                    self.loop,
                )
        except Exception as e:
            log.debug(f"[pwn-companion] Error in on_deauthentication: {e}")

    def on_epoch(self, agent, epoch, epoch_data):
        """
        Collect per-channel stats from each epoch and send autotune_stats to app.
        epoch_data contains: channel, num_deauths, num_associations, num_handshakes, etc.
        This runs every epoch (~60s) and is the most reliable source of channel efficiency.
        """
        self._agent = agent
        try:
            ch = epoch_data.get("channel") or epoch_data.get("current_channel")
            if ch is None:
                return

            ch = int(ch)
            if ch not in self._channel_stats:
                self._channel_stats[ch] = {
                    "handshakes": 0,
                    "deauths": 0,
                    "associations": 0,
                }

            self._channel_stats[ch]["handshakes"] += int(
                epoch_data.get("num_handshakes", 0)
            )
            self._channel_stats[ch]["deauths"] += int(epoch_data.get("num_deauths", 0))
            self._channel_stats[ch]["associations"] += int(
                epoch_data.get("num_associations", 0)
            )

            # Determine best channel by total handshakes
            if self._channel_stats:
                self._best_channel = max(
                    self._channel_stats,
                    key=lambda c: self._channel_stats[c]["handshakes"],
                )

            log.debug(
                f"[pwn-companion] Epoch {epoch}: CH{ch} "
                f"hs={epoch_data.get('num_handshakes',0)} "
                f"da={epoch_data.get('num_deauths',0)} "
                f"as={epoch_data.get('num_associations',0)}"
            )

            # Send autotune_stats to app if connected
            if self.app_connected and self._channel_stats:
                # Convert int keys to strings for JSON serialisation
                channels_payload = {str(c): v for c, v in self._channel_stats.items()}
                msg = {
                    "type": "autotune_stats",
                    "autotune_channels": channels_payload,
                    "autotune_best_channel": self._best_channel,
                    "autotune_min_rssi": None,  # filled in below if auto-tune is loaded
                    "timestamp": int(time.time()),
                }

                # Try to enrich with actual auto-tune min_rssi
                try:
                    import pwnagotchi.plugins as _plugins

                    autotune = _plugins.loaded.get("auto-tune")
                    if autotune:
                        for attr in ("_min_rssi", "min_rssi"):
                            v = getattr(autotune, attr, None)
                            if v is not None:
                                msg["autotune_min_rssi"] = int(v)
                                break
                except Exception:
                    pass

                asyncio.run_coroutine_threadsafe(self._send_to_app(msg), self.loop)

        except Exception as e:
            log.debug(f"[pwn-companion] Error in on_epoch: {e}")

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
            f"[pwn-companion] 🔍 Discovery started, listening on UDP:{UDP_DISCOVERY_PORT}{iface_str}"
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
            except Exception as e:
                log.debug(f"[pwn-companion] Error closing websocket: {e}")
            try:
                self.loop.close()
            except Exception as e:
                log.debug(f"[pwn-companion] Error closing event loop: {e}")
            log.info("[pwn-companion] Discovery loop stopped")

    async def _discovery_loop(self, iface=None):
        """Main discovery and connection loop"""
        udp_socket = None
        last_connection_attempt = 0
        connection_retry_delay = INITIAL_RETRY_DELAY
        consecutive_failures = 0  # Track failed connection attempts

        try:
            # Create UDP socket for discovering announcements
            udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

            # CRITICAL: Enable broadcast reception on this socket
            # This allows us to receive broadcasts sent from the app
            udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            log.debug("[pwn-companion] ✓ Broadcast reception enabled on UDP socket")

            # If interface is provided, bind to the broadcast address on that interface
            # For receiving broadcasts, we should bind to 0.0.0.0 but on the specific interface
            if iface:
                try:
                    # On Linux, use SO_BINDTODEVICE to bind to specific interface (bnep0)
                    import socket as socket_module

                    udp_socket.setsockopt(
                        socket.SOL_SOCKET, SO_BINDTODEVICE, iface.encode()
                    )
                    log.info(f"[pwn-companion] ✓ Bound UDP socket to interface {iface}")
                except (AttributeError, OSError) as e:
                    log.debug(
                        f"[pwn-companion] ⚠️ Could not bind to interface {iface}: {e}, listening on all interfaces"
                    )

            # Bind to all interfaces on port UDP_DISCOVERY_PORT
            udp_socket.bind(("", UDP_DISCOVERY_PORT))
            udp_socket.setblocking(False)
            log.info(
                f"[pwn-companion] ✓ UDP socket listening on :{UDP_DISCOVERY_PORT} (broadcast enabled)"
                + (f" on {iface}" if iface else "")
            )

            loop = asyncio.get_event_loop()

            while self.discovering:
                # Try to receive announcement using asyncio's socket wrapper
                try:
                    data, addr = await asyncio.wait_for(
                        loop.sock_recvfrom(udp_socket, UDP_BUFFER_SIZE),
                        timeout=UDP_RECEIVE_TIMEOUT,
                    )
                    try:
                        msg = json.loads(data.decode("utf-8"))
                        log.info(
                            f"[pwn-companion] ✅ 📨 UDP received from {addr}: type={msg.get('type')}"
                        )
                        log.debug(f"[pwn-companion] Full announcement: {msg}")

                        # CRITICAL: Log the endpoint data for verification
                        if msg.get("type") == "announcement":
                            server_ip = msg.get("serverIp")
                            server_port = msg.get("serverPort")
                            log.info(
                                f"[pwn-companion] 📡 Announcement details: serverIp={server_ip}, serverPort={server_port}"
                            )

                        if msg.get("type") == "announcement":
                            # Construct endpoint from serverIp and serverPort
                            server_ip = msg.get("serverIp")
                            server_port = msg.get("serverPort")
                            endpoint = msg.get(
                                "endpoint"
                            )  # Fallback if endpoint is provided directly

                            # If no endpoint but we have serverIp and serverPort, construct it
                            if not endpoint and server_ip and server_port:
                                endpoint = f"ws://{server_ip}:{server_port}"

                            ip = msg.get("ip", server_ip)
                            port = msg.get("port", server_port)

                            if not endpoint:
                                log.warning(
                                    f"[pwn-companion] ⚠️ Announcement missing endpoint data. Available fields: {list(msg.keys())}"
                                )
                            elif endpoint != self.app_endpoint:
                                self.app_endpoint = endpoint
                                log.info(
                                    f"[pwn-companion] 📢 App announcement: {ip}:{port} → {endpoint}"
                                )
                                # Reset backoff + error counter on new announcement
                                connection_retry_delay = INITIAL_RETRY_DELAY
                                last_connection_attempt = 0
                                consecutive_failures = 0
                                # Try to connect
                                await self._connect_to_app()
                            else:
                                log.debug(
                                    f"[pwn-companion] Announcement endpoint unchanged: {endpoint}"
                                )
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
                        f"[pwn-companion] Attempting reconnection (retry delay: {connection_retry_delay}s, failures: {consecutive_failures})..."
                    )
                    success = await self._connect_to_app()
                    if success:
                        # Reset backoff + error counter on successful connection
                        connection_retry_delay = INITIAL_RETRY_DELAY
                        consecutive_failures = 0
                    else:
                        consecutive_failures += 1
                        # Increase backoff delay up to MAX_RETRY_DELAY
                        connection_retry_delay = min(
                            MAX_RETRY_DELAY,
                            connection_retry_delay * RETRY_BACKOFF_FACTOR,
                        )

                # Brief sleep to prevent busy-waiting
                await asyncio.sleep(DISCOVERY_LOOP_SLEEP)

        except Exception as e:
            log.error(
                f"[pwn-companion] Discovery loop error: {type(e).__name__}: {e}",
                exc_info=True,
            )
        finally:
            if udp_socket:
                try:
                    udp_socket.close()
                except Exception as e:
                    log.debug(f"[pwn-companion] Error closing UDP socket: {e}")
            self.discovering = False
            with self.lock:
                self.app_websocket = None
                self.app_connected = False
            log.info("[pwn-companion] Discovery loop ended")

    async def _connect_to_app(self):
        """Connect to app's WebSocket endpoint. Returns True on success, False on failure."""
        if not self.app_endpoint or self.app_connected:
            return False

        try:
            log.info(f"[pwn-companion] 🔗 Connecting to {self.app_endpoint}...")
            log.debug(
                f"[pwn-companion] Attempting WebSocket connection with {WEBSOCKET_CONNECT_TIMEOUT}s timeout"
            )
            self.app_websocket = await asyncio.wait_for(
                websockets.connect(self.app_endpoint), timeout=WEBSOCKET_CONNECT_TIMEOUT
            )
            log.debug(
                f"[pwn-companion] WebSocket connection established, state={self.app_websocket.state}"
            )
            with self.lock:
                self.app_connected = True
            log.info(f"[pwn-companion] ✓ Connected to app!")

            # Initialize event broadcaster for AI personality
            if not self.event_broadcaster:
                self.event_broadcaster = PwnagotchiEventBroadcaster(self._send_to_app)
                log.info("[pwn-companion] 🤖 AI event broadcaster ready")

            # Send ready signal to initiate app polling (on both initial connect and reconnect)
            log.debug(
                f"[pwn-companion] 📡 Sending READY signal (initial or reconnect)..."
            )
            await self._send_to_app({"type": "ready"})

            # Send initial status message
            await self._send_status_message("Connected to companion app")

            # Send immediate GPS request (don't wait for periodic task)
            log.info("[pwn-companion] 📍 Sending initial GPS request on connection")
            await self._send_to_app(
                {
                    "type": "gps_request",
                    "timestamp": int(time.time()),
                    "source": "initial_connect",
                }
            )

            # Start periodic tasks (image push, GPS requests)
            self._start_periodic_tasks()

            # Listen for messages from app
            await self._listen_to_app()
            return True
        except asyncio.TimeoutError:
            log.warning(
                f"[pwn-companion] ⏱️ Connection timeout ({WEBSOCKET_CONNECT_TIMEOUT}s) to {self.app_endpoint}"
            )
            log.warning(
                f"[pwn-companion] ⏸️ App WebSocket server may not be listening or is blocked by network"
            )
            return False
        except websockets.exceptions.InvalidStatus as ise:
            # HTTP error during WebSocket handshake
            log.warning(
                f"[pwn-companion] ❌ HTTP {ise.status} during WebSocket handshake: {ise.reason}"
            )
            log.warning(
                f"[pwn-companion] ⚠️ App responded with HTTP error - check if WebSocket server is running"
            )
            return False
        except websockets.exceptions.WebSocketException as e:
            log.warning(
                f"[pwn-companion] ❌ WebSocket error: {type(e).__name__}: {str(e)[:LOG_STRING_TRUNCATE_LENGTH]}"
            )
            log.debug(f"[pwn-companion] Full WebSocket error: {e}", exc_info=True)
            return False
        except ConnectionRefusedError as e:
            log.warning(f"[pwn-companion] ❌ Connection refused by {self.app_endpoint}")
            # When connection is refused, clear endpoint and go back to UDP listening
            log.info(
                "[pwn-companion] 🔄 Clearing endpoint, switching back to UDP discovery mode"
            )
            self.app_endpoint = None
            return False
        except OSError as e:
            log.warning(
                f"[pwn-companion] ❌ Network error: {type(e).__name__}: {str(e)[:LOG_STRING_TRUNCATE_LENGTH]}"
            )
            return False
        except Exception as e:
            log.warning(
                f"[pwn-companion] ❌ Connection error: {type(e).__name__}: {str(e)[:LOG_STRING_TRUNCATE_LENGTH]}"
            )
            return False
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
            # Keep endpoint for reconnection attempt with exponential backoff
            # Don't clear it - let the discovery loop retry the connection
            log.info(
                "[pwn-companion] ⏸️ Connection closed, discovery loop will retry with backoff..."
            )
        except Exception as e:
            log.warning(
                f"[pwn-companion] ⚠️ Listen error: {type(e).__name__}: {str(e)[:LOG_STRING_TRUNCATE_LENGTH]}"
            )

    def _start_periodic_tasks(self):
        """Start periodic background tasks (image push, GPS requests, auto-tune stats)"""
        self.periodic_tasks = []

        if self.push_image_interval > 0:
            task = asyncio.create_task(self._periodic_image_push())
            self.periodic_tasks.append(task)
            log.debug(
                f"[pwn-companion] 📸 Periodic image push started ({self.push_image_interval}s)"
            )

        if self.request_gps_interval > 0:
            task = asyncio.create_task(self._periodic_gps_request())
            self.periodic_tasks.append(task)
            log.debug(
                f"[pwn-companion] 📍 Periodic GPS request started ({self.request_gps_interval}s)"
            )

        # Auto-tune stats — push every 30 seconds if auto-tune is loaded
        task = asyncio.create_task(self._periodic_autotune_push())
        self.periodic_tasks.append(task)
        log.debug("[pwn-companion] 📡 Periodic auto-tune stats push started (30s)")

    def _stop_periodic_tasks(self):
        """Stop all periodic background tasks"""
        if not self.periodic_tasks:
            return

        # Cancel all tasks
        for task in self.periodic_tasks:
            if task and not task.done():
                task.cancel()

        # Properly await cancellation to allow cleanup (run in event loop if available)
        try:
            loop = asyncio.get_running_loop()
            # Schedule gathering tasks to complete cancellation
            asyncio.gather(*self.periodic_tasks, return_exceptions=True)
        except RuntimeError:
            # No running loop - tasks will be cleaned up when loop runs
            pass

        self.periodic_tasks = []

    async def _periodic_autotune_push(self):
        """Push auto-tune channel efficiency stats every 30 seconds"""
        while self.app_connected:
            try:
                await asyncio.sleep(30)
                if self.app_connected and self._agent:
                    await self._send_autotune_stats(self._agent)
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.debug(f"[pwn-companion] Periodic auto-tune error: {e}")
                await asyncio.sleep(5)

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
                    f"[pwn-companion] Periodic image push error: {type(e).__name__}: {str(e)[:LOG_STRING_TRUNCATE_LENGTH]}"
                )
                await asyncio.sleep(
                    PERIODIC_TASK_RETRY_SLEEP
                )  # Brief delay before retry

    async def _periodic_gps_request(self):
        """Periodically request GPS data from app"""
        while self.app_connected:
            try:
                await asyncio.sleep(self.request_gps_interval)
                if self.app_connected:
                    log.debug(
                        f"[pwn-companion] 📍 Sending periodic GPS request (interval: {self.request_gps_interval}s)"
                    )
                    await self._send_to_app(
                        {
                            "type": "gps_request",
                            "timestamp": int(time.time()),
                            "source": "periodic",
                        }
                    )
            except asyncio.CancelledError:
                log.debug("[pwn-companion] GPS request task cancelled")
                break
            except Exception as e:
                log.error(
                    f"[pwn-companion] Periodic GPS request error: {type(e).__name__}: {str(e)[:LOG_STRING_TRUNCATE_LENGTH]}"
                )
                await asyncio.sleep(
                    PERIODIC_TASK_RETRY_SLEEP
                )  # Brief delay before retry

    async def _handle_message(self, message: str):
        """Handle incoming WebSocket message from app"""
        try:
            log.debug(
                f"[pwn-companion] Processing message: {message[:HANDLER_ERROR_TRUNCATE_LENGTH]}"
            )

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
                    log.debug(f"[pwn-companion] Processing image request")
                    await self._handle_image_request()
                elif msg_type == "ready":
                    # App acknowledging ready signal
                    log.debug(f"[pwn-companion] App acknowledged ready signal")
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
                            "message": f"Handler error: {str(handler_ex)[:HANDLER_ERROR_TRUNCATE_LENGTH]}",
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
        # Support both "action" (app JSON) and "message" (ScreenData queue format)
        action = data.get("action") or data.get("message")
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

        # Execute the command
        self.execute_command(action, params)

    def execute_command(self, action: str, params: dict):
        """
        Execute a command received from the companion app.

        Supported actions:
            restart_auto   — Restart pwnagotchi in autonomous (AUTO) mode
            restart_manual — Restart pwnagotchi in manual (MANUAL) mode
        """
        if not action:
            log.warning("[pwn-companion] execute_command: empty action")
            return

        log.info(f"[pwn-companion] ⚙️ Executing command: {action}")

        try:
            if action in ("restart_auto", "restart_manual"):
                mode = "AUTO" if action == "restart_auto" else "MANUAL"
                log.info(f"[pwn-companion] 🔄 Restarting pwnagotchi in {mode} mode...")
                try:
                    import pwnagotchi

                    pwnagotchi.restart(mode)
                except Exception as e:
                    log.error(f"[pwn-companion] Failed to restart in {mode} mode: {e}")
            else:
                log.warning(f"[pwn-companion] Unknown command action: {action}")

        except Exception as e:
            log.error(f"[pwn-companion] Error executing command '{action}': {e}")

    async def _handle_gps(self, data: dict):
        """Handle GPS coordinate update from mobile app"""
        try:
            log.debug(f"[pwn-companion] 📍 GPS handler received data: {data}")

            latitude = float(data.get("latitude"))
            longitude = float(data.get("longitude"))
            accuracy = float(data.get("accuracy", 0))
            altitude = float(data.get("altitude", 0))

            # CRITICAL: Validate GPS coordinates - reject invalid Earth coordinates
            if not (-90 <= latitude <= 90):
                raise ValueError(f"Invalid latitude: {latitude} (must be -90 to 90)")
            if not (-180 <= longitude <= 180):
                raise ValueError(
                    f"Invalid longitude: {longitude} (must be -180 to 180)"
                )
            if accuracy < 0:
                raise ValueError(f"Invalid accuracy: {accuracy} (must be >= 0)")

            log.info(
                f"[pwn-companion] ✓ GPS received: {latitude:.{GPS_COORD_PRECISION}f}, {longitude:.{GPS_COORD_PRECISION}f} (±{accuracy:.{ACCURACY_FORMAT_PRECISION}f}m, alt:{altitude:.{ACCURACY_FORMAT_PRECISION}f}m)"
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
                    "message": f"GPS handler error: {str(e)[:HANDLER_ERROR_TRUNCATE_LENGTH]}",
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

    async def _handle_image_request(self):
        """Handle image request from mobile app - fetch UI screenshot and send to app"""
        try:
            log.debug(f"[pwn-companion] 📸 Image request received from app")

            # Fetch the UI screenshot from pwnagotchi web interface
            url = PWNAGOTCHI_UI_URL
            log.debug(f"[pwn-companion] 🌐 Fetching screenshot from {url}...")

            try:
                loop = asyncio.get_event_loop()
                response = await loop.run_in_executor(
                    None, lambda: requests.get(url, timeout=IMAGE_REQUEST_TIMEOUT)
                )
                log.debug(
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

            log.debug(
                f"[pwn-companion] Converting {len(image_bytes)} bytes to base64..."
            )

            # Send image without caching (lightweight - no image hashing)
            image_data = base64.b64encode(image_bytes).decode("utf-8")
            log.debug(
                f"[pwn-companion] ✓ Encoded to base64: {len(image_data)} characters"
            )

            # Create response object with proper JSON serialization
            response_obj = {
                "type": "image",
                "data": image_data,
                "contentType": response.headers.get("content-type", "image/png"),
                "timestamp": int(time.time()),
            }

            log.debug(
                f"[pwn-companion] 📤 Sending image message (payload size: {len(image_data)} chars)..."
            )
            await self._send_to_app(response_obj)

            log.debug(
                f"[pwn-companion] ✓✓✓ Image successfully sent to app ({len(image_bytes)} bytes)"
            )

        except Exception as e:
            log.error(
                f"[pwn-companion] ❌ CRITICAL ERROR in image handler: {type(e).__name__}: {e}",
                exc_info=True,
            )
            try:
                await self._send_to_app(
                    {
                        "type": "error",
                        "message": f"Image error: {str(e)[:HANDLER_ERROR_TRUNCATE_LENGTH]}",
                    },
                )
            except:
                log.error("[pwn-companion] Failed to send error response to app")

    async def _send_to_app(self, data: dict):
        """Send a JSON message to the connected companion app via WebSocket."""
        if not self.app_websocket or not self.app_connected:
            return
        try:
            message = json.dumps(data)
            await self.app_websocket.send(message)
            log.debug(f"[pwn-companion] → Sent: type={data.get('type')}")
        except websockets.ConnectionClosed:
            log.info("[pwn-companion] Connection closed while sending")
            with self.lock:
                self.app_connected = False
        except Exception as e:
            log.debug(f"[pwn-companion] Error sending to app: {type(e).__name__}: {e}")
            with self.lock:
                self.app_connected = False

    async def _send_autotune_stats(self, agent):
        """Push auto-tune channel efficiency stats to the app."""
        try:
            if not self._channel_stats:
                return
            channels_payload = {str(c): v for c, v in self._channel_stats.items()}
            msg = {
                "type": "autotune_stats",
                "autotune_channels": channels_payload,
                "autotune_best_channel": self._best_channel,
                "autotune_min_rssi": None,
                "timestamp": int(time.time()),
            }
            try:
                import pwnagotchi.plugins as _plugins

                autotune = _plugins.loaded.get("auto-tune")
                if autotune:
                    for attr in ("_min_rssi", "min_rssi"):
                        v = getattr(autotune, attr, None)
                        if v is not None:
                            msg["autotune_min_rssi"] = int(v)
                            break
            except Exception:
                pass
            await self._send_to_app(msg)
        except Exception as e:
            log.debug(f"[pwn-companion] Error sending autotune stats: {e}")

    async def _send_status_message(self, message: str):
        """Send status message to app (on connection or important events)"""
        # Try to read the pwnagotchi's current mood name
        pwn_mood = None
        try:
            if self._agent and hasattr(self._agent, "_mood"):
                mood = self._agent._mood
                pwn_mood = getattr(mood, "name", None) or getattr(mood, "_name", None)
                if pwn_mood is None and hasattr(mood, "__class__"):
                    pwn_mood = mood.__class__.__name__.upper()
        except Exception:
            pass

        status_obj = {
            "type": "status",
            "message": message,
            "device_name": self.device_name,
            "status": "running",
            "ip": self.current_ip,
            "tether_interface": self.tether_interface,
            "pwnagotchi_mood": pwn_mood,
            "timestamp": int(time.time()),
        }
        await self._send_to_app(status_obj)
        log.info(
            f"[pwn-companion] 📊 Status sent: {message} (IP: {self.current_ip}, mood: {pwn_mood})"
        )

    def on_mood(self, agent, mood):
        """Sync pwnagotchi mood change to app immediately"""
        self._agent = agent
        try:
            mood_name = (
                getattr(mood, "name", None)
                or getattr(mood, "_name", None)
                or getattr(mood, "__class__", type(mood)).__name__.upper()
                or str(mood)
            )
            log.info(f"[pwn-companion] 😊 Mood changed: {mood_name}")
            if self.app_connected and self.loop:
                asyncio.run_coroutine_threadsafe(
                    self._send_to_app(
                        {
                            "type": "status",
                            "status": "running",
                            "message": f"Mood: {mood_name}",
                            "device_name": self.device_name,
                            "pwnagotchi_mood": mood_name,
                            "timestamp": int(time.time()),
                        }
                    ),
                    self.loop,
                )
        except Exception as e:
            log.debug(f"[pwn-companion] Error in on_mood: {e}")

    # ============================================================
    #  AI Event Triggers - Call these to send WiFi events to AI
    # ============================================================

    def trigger_handshakes_event(
        self, count: int, network_name: str, security: str = "WPA2"
    ):
        """
        Trigger AI personality response for handshake capture

        Usage:
            self.trigger_handshakes_event(5, "StarbucksWiFi", "WPA2")
        """
        if self.event_broadcaster and self.app_connected:
            try:
                asyncio.run_coroutine_threadsafe(
                    self.event_broadcaster.on_handshakes_captured(
                        count, network_name, security
                    ),
                    self.loop,
                )
            except Exception as e:
                log.error(f"[pwn-companion] Error triggering handshake event: {e}")

    def trigger_network_discovered_event(
        self,
        ssid: str,
        bssid: str = None,
        security: str = "Unknown",
        signal_strength: int = -50,
        channel: int = 1,
    ):
        """
        Trigger AI personality response for network discovery

        Usage:
            self.trigger_network_discovered_event("MyNetwork", "AA:BB:CC:DD:EE:FF", "WPA2", -45, 6)
        """
        if self.event_broadcaster and self.app_connected:
            try:
                asyncio.run_coroutine_threadsafe(
                    self.event_broadcaster.on_network_discovered(
                        ssid, bssid, security, signal_strength, channel
                    ),
                    self.loop,
                )
            except Exception as e:
                log.error(
                    f"[pwn-companion] Error triggering network discovery event: {e}"
                )

    def trigger_connection_success_event(
        self, network_name: str, duration: float = 0.0
    ):
        """
        Trigger AI personality response for successful connection

        Usage:
            self.trigger_connection_success_event("TargetNetwork", 3.5)
        """
        if self.event_broadcaster and self.app_connected:
            try:
                asyncio.run_coroutine_threadsafe(
                    self.event_broadcaster.on_connection_success(
                        network_name, duration
                    ),
                    self.loop,
                )
            except Exception as e:
                log.error(
                    f"[pwn-companion] Error triggering connection success event: {e}"
                )

    def trigger_connection_failure_event(
        self, network_name: str, reason: str = "Unknown"
    ):
        """
        Trigger AI personality response for connection failure

        Usage:
            self.trigger_connection_failure_event("TargetNetwork", "Weak signal")
        """
        if self.event_broadcaster and self.app_connected:
            try:
                asyncio.run_coroutine_threadsafe(
                    self.event_broadcaster.on_connection_failure(network_name, reason),
                    self.loop,
                )
            except Exception as e:
                log.error(
                    f"[pwn-companion] Error triggering connection failure event: {e}"
                )

    def trigger_anomaly_detected_event(self, anomaly_type: str, details: dict = None):
        """
        Trigger AI personality response for anomaly detection

        Usage:
            self.trigger_anomaly_detected_event("deauth_spike", {"count": 25, "source": "unknown"})
        """
        if self.event_broadcaster and self.app_connected:
            try:
                asyncio.run_coroutine_threadsafe(
                    self.event_broadcaster.on_anomaly_detected(
                        anomaly_type, details or {}
                    ),
                    self.loop,
                )
            except Exception as e:
                log.error(f"[pwn-companion] Error triggering anomaly event: {e}")

    def trigger_high_value_target_event(self, network_name: str, reason: str = ""):
        """
        Trigger AI personality response for high-value target detection

        Usage:
            self.trigger_high_value_target_event("CompanyHQ-5GHz", "WPA3-Enterprise")
        """
        if self.event_broadcaster and self.app_connected:
            try:
                asyncio.run_coroutine_threadsafe(
                    self.event_broadcaster.on_high_value_target(network_name, reason),
                    self.loop,
                )
            except Exception as e:
                log.error(
                    f"[pwn-companion] Error triggering high-value target event: {e}"
                )

    def trigger_scan_complete_event(self, networks_found: int, duration: float = 0.0):
        """
        Trigger AI personality response for scan completion

        Usage:
            self.trigger_scan_complete_event(15, 5.2)
        """
        if self.event_broadcaster and self.app_connected:
            try:
                asyncio.run_coroutine_threadsafe(
                    self.event_broadcaster.on_scan_complete(networks_found, duration),
                    self.loop,
                )
            except Exception as e:
                log.error(f"[pwn-companion] Error triggering scan complete event: {e}")

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
            self.ws_thread.join(timeout=THREAD_SHUTDOWN_TIMEOUT)

        log.info("[pwn-companion] Client discovery stopped")
