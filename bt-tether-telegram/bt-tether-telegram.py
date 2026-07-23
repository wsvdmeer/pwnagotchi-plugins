"""
Bluetooth Tether Telegram Plugin

Listens to bt-tether plugin events and forwards them to Telegram via bot API.

Configuration (config.toml):

    [main.plugins.bt-tether-telegram]
    enabled = true
    telegram_bot_token = "123456:ABC..."  # required - get from @BotFather
    telegram_chat_id = "123456789"         # required - get with /start command

To get these values:
1. Create a bot via @BotFather on Telegram
2. Get the bot token
3. Send any message to your bot
4. Visit: https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates
5. Extract the chat_id from the response
"""

import logging
import pwnagotchi
from pwnagotchi.plugins import Plugin
import urllib.parse

try:
    import urllib.request
    import urllib.error

    URLLIB_AVAILABLE = True
except ImportError:
    URLLIB_AVAILABLE = False
    logging.warning(
        "[bt-tether-telegram] urllib not available, Telegram notifications disabled"
    )


class BTTetherTelegram(Plugin):
    __author__ = "wsvdmeer"
    __version__ = "1.0.0"
    __license__ = "GPL3"
    __description__ = "Sends Telegram notifications when bt-tether connects"

    def on_loaded(self):
        self.telegram_bot_token = self.options.get("telegram_bot_token", "")
        self.telegram_chat_id = self.options.get("telegram_chat_id", "")

        if self.telegram_bot_token and self.telegram_chat_id:
            logging.info("[bt-tether-telegram] Loaded with Telegram bot configured")
        else:
            logging.warning(
                "[bt-tether-telegram] Loaded but Telegram credentials not fully configured"
            )

    def on_bt_tether_connected(self, agent, event_data):
        """Handle bt-tether connection event"""
        ip = event_data.get("ip", "unknown")
        device = event_data.get("device", "unknown")
        pwnagotchi_name = pwnagotchi.name()

        logging.info(
            f"[bt-tether-telegram] Connected: {pwnagotchi_name} - {ip} via {device}"
        )

        # Build message
        message = (
            f"🔷 *Bluetooth Tethering Connected*\n\n"
            f"*Pwnagotchi:* `{pwnagotchi_name}`\n"
            f"*Device:* `{device}`\n"
            f"*IP Address:* `{ip}`\n"
            f"*Web Interface:* http://{ip}:8080/"
        )

        self._notify(message)

    def _notify(self, message):
        """Send a message to Telegram using bot API"""
        if (
            not URLLIB_AVAILABLE
            or not self.telegram_bot_token
            or not self.telegram_chat_id
        ):
            return

        try:
            api_url = (
                f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
            )

            # Prepare payload with Markdown formatting
            payload = {
                "chat_id": self.telegram_chat_id,
                "text": message,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            }

            # URL encode the payload
            data = urllib.parse.urlencode(payload).encode("utf-8")

            # Create request
            req = urllib.request.Request(
                api_url,
                data=data,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "User-Agent": "Pwnagotchi-BT-Tether/1.0",
                },
            )

            # Send request
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    logging.info(
                        "[bt-tether-telegram] ✓ Telegram notification sent successfully"
                    )
                else:
                    logging.warning(
                        f"[bt-tether-telegram] Telegram API returned status {resp.status}"
                    )
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8") if e.fp else ""
            logging.error(
                f"[bt-tether-telegram] Telegram HTTP error {e.code}: {e.reason}"
            )
            if error_body:
                logging.error(f"[bt-tether-telegram] Response: {error_body}")
        except urllib.error.URLError as e:
            logging.error(f"[bt-tether-telegram] Telegram network error: {e.reason}")
        except Exception as e:
            logging.error(f"[bt-tether-telegram] Telegram error: {e}")
