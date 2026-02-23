# bt-tether-telegram

A Pwnagotchi plugin that sends Telegram notifications when Bluetooth tethering connects.

## Features

- 📱 Sends Telegram messages when Bluetooth tethering is established
- 📊 Includes IP address and device information in notifications
- 🔗 Includes link to Pwnagotchi web interface
- ✅ Error handling and logging for troubleshooting

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
  - IP address
  - Link to web interface

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
