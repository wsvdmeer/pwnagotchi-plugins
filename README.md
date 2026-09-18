# 📱 Pwnagotchi Plugins

> Collection of custom Pwnagotchi plugins for enhanced functionality and better connectivity.

---

## 📦 Available Plugins

### 🔷 bt-tether

Comprehensive **Bluetooth tethering plugin** with web interface for managing internet connections from your phone.

- 🌐 **Web UI** for easy connection management
- 📡 **Automatic pairing** with guided setup (no manual MAC entry needed)
- 📊 **On-screen status** indicators with connection details
- 🔍 **Device scanning** and auto-discovery
- 🔄 **Auto-reconnect** with intelligent failure handling
- 📣 **Connect/disconnect notifications** via optional Discord & Telegram companion plugins (below)

**[📖 Full documentation →](bt-tether/README.md)**

> **Note:** Previously named `bt-tether-helper`. See [migration guide](bt-tether-helper/README.md) for old links.

---

### 🎮 bt-tether-discord

Companion plugin that posts a **Discord** notification when Bluetooth tethering connects or disconnects.

- 🔔 Listens to `bt-tether`'s connect/disconnect events and posts a formatted webhook embed (blue on connect, red on disconnect)
- 🌐 Includes device, interface, and IP (IPv4 + IPv6 when available)
- 🧵 **Non-blocking**: the webhook POST runs on a background thread, so a slow/unreachable Discord endpoint never stalls `bt-tether`
- 🔁 **Debounced** (30 s) to avoid spam from reconnect churn

**[📖 Full documentation →](bt-tether-discord/README.md)**

---

### ✈️ bt-tether-telegram

Companion plugin that sends a **Telegram** message when Bluetooth tethering connects or disconnects.

- 🔔 Listens to `bt-tether`'s connect/disconnect events
- 🌐 Includes device info and IP (IPv4 + IPv6 when available), plus a link to the Pwnagotchi web UI
- 🧵 **Non-blocking**: the API call runs on a background thread, so a slow/unreachable Telegram endpoint never stalls `bt-tether`

**[📖 Full documentation →](bt-tether-telegram/README.md)**

---

### 🕐 rtc-datetime

Simple plugin to display the **current time and date** (from the OS system clock) on the Pwnagotchi screen.

- ⏰ **Customizable time/date format** (strftime syntax)
- 🎯 **Configurable position** anywhere on screen
- 📖 **Display only** — reads the system clock; keeping time accurate offline (NTP / hardware RTC) is an OS-level setup
- 📍 **Bottom-left placement** by default

**[📖 Full documentation →](rtc-datetime/README.md)**

---

### 🔋 waveshare-ups

Battery gauge for the **Waveshare UPS HAT (C)**, reading the on-board INA219 fuel gauge over I²C.

- 🔋 **Battery icon + %** on the e-ink screen (compact segmented battery glyph, or plain `BAT` text)
- ⚡ **Charging detection** — shows a `+` when the pack is charging
- 📈 **Smoothed reading** via an interpolated Li-ion curve, instead of coarse voltage steps
- 📊 **Web history chart** at `/plugins/waveshare-ups` — charge % over time, persisted across reboots
- 🩹 **Self-healing I²C init** — retries if the HAT isn't ready at boot instead of getting stuck on `--%`
- 🛠️ **Configurable** icon style, orientation, segments, position, and thresholds (optional safe shutdown)

**[📖 Full documentation →](waveshare-ups/README.md)**

---

## 🚀 Quick Start

For any plugin, copy to your custom plugins directory and enable in config:

```bash
sudo cp <plugin-name>.py /usr/local/share/pwnagotchi/custom-plugins/
pwnkill  # Restart Pwnagotchi
```

Then enable in `/etc/pwnagotchi/config.toml` under `[main.plugins.<plugin-name>]`

---

## 📄 License

All plugins are licensed under **GPL3**.

## 👤 Author

**wsvdmeer**

## 🤝 Contributing

Issues and pull requests are welcome! Feel free to open an issue for bugs or feature requests.
