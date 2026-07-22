# bt-tether-telegram (v1.1.0)

A Pwnagotchi plugin that sends Telegram notifications when Bluetooth tethering connects or disconnects.

## Features

- 📱 Sends Telegram messages when Bluetooth tethering connects **and** when it disconnects
- 📊 Includes IP address (IPv4 + IPv6 when available) and device information in notifications
- 🔗 Includes link to Pwnagotchi web interface
- 🧵 Non-blocking: the API call runs on a background thread, so a slow/unreachable Telegram endpoint never stalls `bt-tether`
- 🔁 Debounced: repeated events of the same kind within 30 seconds are suppressed to avoid rate-limit spam
- 🛡️ Device/pwnagotchi names are Markdown-escaped so special characters can't break the message (HTTP 400)
- ✅ Error handling and logging for troubleshooting (bot token is never written to the logs)

## Requirements

- Pwnagotchi with [`bt-tether`](../bt-tether/) plugin installed
- Telegram bot credentials (bot token and chat ID)

## Installation

1. Install the plugin by placing it in the plugins directory
2. Create a Telegram bot:
   - Open [@BotFather](https://t.me/botfather) on Telegram
   - Send `/newbot` and follow the instructions
   - Copy the **bot token** (e.g., `123456789:ABCdefGHIjklmnoPQRstuvWXYZ`)

3. Get your Telegram chat ID:
   - Send any message to your newly created bot
   - Visit: `https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates`
   - Look for `"chat":{"id":YOUR_CHAT_ID}`
   - Copy the **chat_id** number

4. Configure in `/etc/pwnagotchi/config.toml`:

```toml
[main.plugins.bt-tether-telegram]
enabled = true
telegram_bot_token = "123456789:ABCdefGHIjklmnoPQRstuvWXYZ"
telegram_chat_id = "987654321"
```

5. Restart Pwnagotchi to apply changes

## Configuration Options

| Option               | Type   | Description             | Required |
| -------------------- | ------ | ----------------------- | -------- |
| `telegram_bot_token` | string | Your Telegram bot token | Yes      |
| `telegram_chat_id`   | string | Your Telegram chat ID   | Yes      |

## How It Works

The plugin listens for events from the [`bt-tether`](../bt-tether/) plugin:

- **Connection Event**: When Bluetooth tethering connects, sends a notification with:
  - Pwnagotchi device name
  - Connected device name
  - IP address (IPv4, plus IPv6 when a global address is available)
  - Link to web interface
- **Disconnection Event**: When the link drops or is torn down by the user, sends a notification with the device name and the reason (`connection_dropped` / `user_request`).

Both notifications are sent on a background daemon thread and are debounced (same event kind within 30 s is skipped).

## Requirements (versions)

- `bt-tether` plugin **v1.3.0+** (provides the events, including the `ipv6` field)

## Troubleshooting

### No notifications being sent

1. **Check plugin is enabled**:

   ```bash
   grep -A 3 "bt-tether-telegram" /etc/pwnagotchi/config.toml
   ```

2. **Verify bot token and chat ID**:

   ```bash
   # Test Telegram API directly
   curl "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getMe"
   ```

3. **Check logs**:

   ```bash
   tail -f /var/log/pwnagotchi.log | grep bt-tether-telegram
   ```

4. **Restart Pwnagotchi**:
   ```bash
   sudo systemctl restart pwnagotchi
   ```

### Telegram API errors

- `403 Forbidden`: Invalid bot token or chat ID
- `400 Bad Request`: Check that chat ID is a string (wrapped in quotes)
- `429 Too Many Requests`: Telegram rate limit, wait and retry

## Related Plugins

- **[bt-tether](../bt-tether/)**: Bluetooth tethering plugin (required)
- **[bt-tether-discord](../bt-tether-discord/)**: Discord notifications variant

## Author

**wsvdmeer**

- Based on `bt-tether-discord` by wsvdmeer
- Telegram variant adapted from the helper plugin's Telegram notification code

## License

GPL3
