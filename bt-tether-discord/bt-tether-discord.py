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
    __version__ = "1.0.0"
    __license__ = "GPL3"
    __description__ = "Sends Discord notifications when bt-tether connects"

    def on_loaded(self):
        self.discord_webhook_url = self.options.get("discord_webhook_url", "")

        if self.discord_webhook_url:
            logging.info("[bt-tether-discord] Loaded with Discord webhook configured")
        else:
            logging.warning(
                "[bt-tether-discord] Loaded but no discord_webhook_url configured"
            )

    def on_bt_tether_connected(self, agent, event_data):
        ip = event_data.get("ip", "unknown")
        device = event_data.get("device", "unknown")
        pwnagotchi_name = pwnagotchi.name()

        logging.info(
            f"[bt-tether-discord] Connected: {pwnagotchi_name} - {ip} via {device}"
        )
        self._notify(
            title="🔷 Bluetooth Tethering Connected",
            description=f"**{pwnagotchi_name}** is now connected via Bluetooth",
            color=3447003,  # Blue
            fields=[
                {"name": "Pwnagotchi", "value": pwnagotchi_name, "inline": True},
                {"name": "Device", "value": device, "inline": True},
                {"name": "IP Address", "value": f"`{ip}`", "inline": True},
                {
                    "name": "Web Interface",
                    "value": f"http://{ip}:8080/",
                    "inline": False,
                },
            ],
        )

    def _notify(self, title, description, color=3447003, fields=None):
        """Send a Discord embed via webhook"""
        if not URLLIB_AVAILABLE or not self.discord_webhook_url:
            return

        import time

        embed = {
            "title": title,
            "description": description,
            "color": color,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
            "footer": {"text": "pwnagotchi \u00b7 bt-tether-discord"},
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
