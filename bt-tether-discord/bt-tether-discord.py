"""
Bluetooth Tether Discord Plugin

Listens to bt-tether plugin events and forwards them to Discord via webhook.

Configuration (config.toml):

    [main.plugins.bt-tether-discord]
    enabled = true
    discord_webhook_url = "https://discord.com/api/webhooks/..."  # required
"""

import logging
import json
import time
import threading
import pwnagotchi
from pwnagotchi.plugins import Plugin

try:
    import urllib.request
    import urllib.error

    URLLIB_AVAILABLE = True
except ImportError:
    URLLIB_AVAILABLE = False
    logging.warning(
        "[bt-tether-discord] urllib not available, Discord notifications disabled"
    )


class BTTetherDiscord(Plugin):
    __author__ = "wsvdmeer"
    __version__ = "1.1.0"
    __license__ = "GPL3"
    __description__ = "Sends Discord notifications when bt-tether connects/disconnects"

    # Suppress a repeat of the same connect/disconnect state within this window.
    # bt-tether's reconnect loop can emit connect/drop churn; without this a flap
    # would spam the webhook.
    DEBOUNCE_SECONDS = 30

    COLOR_CONNECTED = 3447003  # Blue
    COLOR_DISCONNECTED = 15158332  # Red

    def on_loaded(self):
        self.discord_webhook_url = self.options.get("discord_webhook_url", "")
        # Debounce state, guarded by _debounce_lock because bt-tether may dispatch
        # events from more than one worker thread.
        self._debounce_lock = threading.Lock()
        self._last_state = None
        self._last_time = 0.0

        if self.discord_webhook_url:
            logging.info("[bt-tether-discord] Loaded with Discord webhook configured")
        else:
            logging.warning(
                "[bt-tether-discord] Loaded but no discord_webhook_url configured"
            )

    def _should_notify(self, state):
        """Return True if a notification for `state` should be sent right now.

        Suppresses duplicate same-state events inside DEBOUNCE_SECONDS, and only
        allows a "disconnected" notification if we previously reported "connected".
        """
        with self._debounce_lock:
            now = time.monotonic()
            if state == "disconnected" and self._last_state != "connected":
                return False
            if state == self._last_state and (now - self._last_time) < self.DEBOUNCE_SECONDS:
                return False
            self._last_state = state
            self._last_time = now
            return True

    def _send_async(self, **kwargs):
        """Fire the webhook on a daemon thread so a slow/unreachable Discord
        endpoint can't stall bt-tether's worker thread (events are dispatched
        synchronously via plugins.on())."""
        threading.Thread(target=self._notify, kwargs=kwargs, daemon=True).start()

    def on_bt_tether_connected(self, agent, event_data):
        ip = event_data.get("ip", "unknown")
        ipv6 = event_data.get("ipv6")
        device = event_data.get("device", "unknown")
        pwnagotchi_name = event_data.get("pwnagotchi_name") or pwnagotchi.name()

        if not self._should_notify("connected"):
            return

        logging.info(
            f"[bt-tether-discord] Connected: {pwnagotchi_name} - {ip} via {device}"
        )
        fields = [
            {"name": "Pwnagotchi", "value": pwnagotchi_name, "inline": True},
            {"name": "Device", "value": device, "inline": True},
            {"name": "IP Address", "value": f"`{ip}`", "inline": True},
        ]
        if ipv6:
            fields.append({"name": "IPv6", "value": f"`{ipv6}`", "inline": True})
        fields.append(
            {"name": "Web Interface", "value": f"http://{ip}:8080/", "inline": False}
        )
        self._send_async(
            title="🔷 Bluetooth Tethering Connected",
            description=f"**{pwnagotchi_name}** is now connected via Bluetooth",
            color=self.COLOR_CONNECTED,
            fields=fields,
        )

    def on_bt_tether_disconnected(self, agent, event_data):
        device = event_data.get("device", "unknown")
        reason = event_data.get("reason", "unknown")
        pwnagotchi_name = event_data.get("pwnagotchi_name") or pwnagotchi.name()

        if not self._should_notify("disconnected"):
            return

        logging.info(
            f"[bt-tether-discord] Disconnected: {pwnagotchi_name} from {device} ({reason})"
        )
        self._send_async(
            title="🔴 Bluetooth Tethering Disconnected",
            description=f"**{pwnagotchi_name}** lost its Bluetooth connection",
            color=self.COLOR_DISCONNECTED,
            fields=[
                {"name": "Pwnagotchi", "value": pwnagotchi_name, "inline": True},
                {"name": "Device", "value": device, "inline": True},
                {"name": "Reason", "value": reason, "inline": True},
            ],
        )

    def _notify(self, title, description, color=COLOR_CONNECTED, fields=None):
        """Send a Discord embed via webhook"""
        if not URLLIB_AVAILABLE or not self.discord_webhook_url:
            return

        embed = {
            "title": title,
            "description": description,
            "color": color,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
            "footer": {"text": "pwnagotchi · bt-tether-discord"},
        }
        if fields:
            embed["fields"] = fields

        payload = json.dumps({"embeds": [embed]}).encode("utf-8")

        try:
            req = urllib.request.Request(
                self.discord_webhook_url,
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "Pwnagotchi-BT-Tether/1.0",
                },
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 204:
                    logging.info(
                        "[bt-tether-discord] ✓ Discord notification sent successfully"
                    )
                else:
                    logging.warning(
                        f"[bt-tether-discord] Webhook returned status {resp.status}"
                    )
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8") if e.fp else ""
            logging.error(
                f"[bt-tether-discord] Webhook HTTP error {e.code}: {e.reason} {error_body}"
            )
        except urllib.error.URLError as e:
            logging.error(f"[bt-tether-discord] Webhook network error: {e.reason}")
        except Exception as e:
            logging.error(f"[bt-tether-discord] Webhook error: {e}")
