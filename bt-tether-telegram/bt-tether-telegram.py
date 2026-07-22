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
import time
import threading
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
    __version__ = "1.1.0"
    __license__ = "GPL3"
    __description__ = "Sends Telegram notifications when bt-tether connects/disconnects"

    # Suppress a repeat of the same connect/disconnect state within this window.
    DEBOUNCE_SECONDS = 30

    def on_loaded(self):
        self.telegram_bot_token = self.options.get("telegram_bot_token", "")
        self.telegram_chat_id = self.options.get("telegram_chat_id", "")
        # Debounce state, guarded by _debounce_lock because bt-tether may dispatch
        # events from more than one worker thread.
        self._debounce_lock = threading.Lock()
        self._last_state = None
        self._last_time = 0.0

        if self.telegram_bot_token and self.telegram_chat_id:
            logging.info("[bt-tether-telegram] Loaded with Telegram bot configured")
        else:
            logging.warning(
                "[bt-tether-telegram] Loaded but Telegram credentials not fully configured"
            )

    @staticmethod
    def _md_escape(value):
        """Neutralize characters that break legacy-Markdown parsing.

        Dynamic values are rendered inside `...` code spans. A backtick would end
        the span early and Telegram rejects the whole message with HTTP 400
        (legacy Markdown has no in-code-span escape), so we replace backticks.
        We also drop the emphasis characters * and _ so a value used outside a
        code span can't unbalance the formatting.
        """
        text = str(value)
        for ch in ("`", "*", "_"):
            text = text.replace(ch, " ")
        return text

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

    def _send_async(self, message):
        """Fire the Telegram request on a daemon thread so a slow/unreachable API
        can't stall bt-tether's worker thread (events are dispatched
        synchronously via plugins.on())."""
        threading.Thread(target=self._notify, args=(message,), daemon=True).start()

    def on_bt_tether_connected(self, agent, event_data):
        """Handle bt-tether connection event"""
        ip = self._md_escape(event_data.get("ip", "unknown"))
        ipv6 = event_data.get("ipv6")
        device = self._md_escape(event_data.get("device", "unknown"))
        pwnagotchi_name = self._md_escape(
            event_data.get("pwnagotchi_name") or pwnagotchi.name()
        )

        if not self._should_notify("connected"):
            return

        logging.info(
            f"[bt-tether-telegram] Connected: {pwnagotchi_name} - {ip} via {device}"
        )

        lines = [
            "🔷 *Bluetooth Tethering Connected*",
            "",
            f"*Pwnagotchi:* `{pwnagotchi_name}`",
            f"*Device:* `{device}`",
            f"*IP Address:* `{ip}`",
        ]
        if ipv6:
            lines.append(f"*IPv6:* `{self._md_escape(ipv6)}`")
        lines.append(f"*Web Interface:* http://{ip}:8080/")

        self._send_async("\n".join(lines))

    def on_bt_tether_disconnected(self, agent, event_data):
        """Handle bt-tether disconnection event"""
        device = self._md_escape(event_data.get("device", "unknown"))
        reason = self._md_escape(event_data.get("reason", "unknown"))
        pwnagotchi_name = self._md_escape(
            event_data.get("pwnagotchi_name") or pwnagotchi.name()
        )

        if not self._should_notify("disconnected"):
            return

        logging.info(
            f"[bt-tether-telegram] Disconnected: {pwnagotchi_name} from {device} ({reason})"
        )

        message = (
            f"🔴 *Bluetooth Tethering Disconnected*\n\n"
            f"*Pwnagotchi:* `{pwnagotchi_name}`\n"
            f"*Device:* `{device}`\n"
            f"*Reason:* `{reason}`"
        )
        self._send_async(message)

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
            # Don't interpolate the exception: its string form can contain the
            # full api_url, which embeds the bot token.
            logging.error(
                f"[bt-tether-telegram] Telegram error: {type(e).__name__}"
            )
