# bt-tether-discord (v1.0.0)

> Sends a Discord notification when Bluetooth tethering connects with internet access.

Listens to events emitted by the `bt-tether` plugin and posts a formatted embed to a Discord webhook when the device is fully connected (IP confirmed).

---

## Events

`bt-tether` emits the following events that any plugin can listen to:

### `bt_tether_connected`

Fired when internet connectivity is confirmed after a successful connection.

```python
event_data = {
    "mac": "AA:BB:CC:DD:EE:FF",
    "device": "iPhone 15",
    "ip": "192.168.x.x",
    "interface": "bnep0",
    "pwnagotchi_name": "pwnagotchi",
}
```

### `bt_tether_disconnected`

Fired when the device disconnects (either dropped or user-initiated).

```python
event_data = {
    "mac": "AA:BB:CC:DD:EE:FF",
    "device": "iPhone 15",
    "reason": "connection_dropped",  # or "user_request"
    "pwnagotchi_name": "pwnagotchi",
}
```

---

## Installation

1. **Copy the plugin:**

   ```bash
   sudo cp bt-tether-discord.py /usr/local/share/pwnagotchi/custom-plugins/
   ```

2. **Enable in `config.toml`:**

   ```toml
   [main.plugins.bt-tether-discord]
   enabled = true
   discord_webhook_url = "https://discord.com/api/webhooks/YOUR_WEBHOOK_ID/YOUR_WEBHOOK_TOKEN"
   ```

3. **Restart Pwnagotchi:**

   ```bash
   pwnkill
   ```

---

## Configuration

```toml
[main.plugins.bt-tether-discord]
enabled = true
discord_webhook_url = "https://discord.com/api/webhooks/..."  # required
```

To get a webhook URL: right-click a Discord channel → **Edit Channel** → **Integrations** → **Webhooks** → **New Webhook** → **Copy Webhook URL**.

---

## Creating Custom Listener Plugins

To listen to `bt-tether` events, define `on_<event_name>` methods directly on your plugin class. Pwnagotchi calls them automatically — no registration needed.

```python
from pwnagotchi.plugins import Plugin

class MyPlugin(Plugin):
    __author__ = "you"
    __version__ = "1.0.0"
    __license__ = "GPL3"
    __description__ = "Reacts to bt-tether events"

    def on_bt_tether_connected(self, agent, event_data):
        ip = event_data.get("ip")
        device = event_data.get("device")
        name = event_data.get("pwnagotchi_name")
        # your logic here

    def on_bt_tether_disconnected(self, agent, event_data):
        reason = event_data.get("reason")
        # your logic here
```

### Example: Custom webhook

```python
import json
import logging
import urllib.request
from pwnagotchi.plugins import Plugin

class BtTetherWebhook(Plugin):
    __author__ = "example"
    __version__ = "1.0.0"
    __license__ = "GPL3"
    __description__ = "POST bt-tether events to a custom webhook"

    def on_loaded(self):
        self.webhook_url = self.options.get("webhook_url", "")

    def on_bt_tether_connected(self, agent, event_data):
        if not self.webhook_url:
            return
        try:
            payload = json.dumps(event_data).encode("utf-8")
            req = urllib.request.Request(
                self.webhook_url,
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=5)
        except Exception as e:
            logging.error(f"[bt-tether-webhook] Error: {e}")
```

---

## Dependencies

- `bt-tether` plugin v1.2.4+ (provides the events)

## Troubleshooting

- **No notification received** — check that `bt-tether` is installed and enabled, and that internet is confirmed (not just BT connected)
- **Webhook errors** — verify the URL in `config.toml` and test it with `curl`
- **View logs** — `sudo tail -f /var/log/pwnagotchi.log | grep bt-tether`
