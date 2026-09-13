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
- 🎮 **Discord notifications** (optional)

**[📖 Full documentation →](bt-tether/README.md)**

> **Note:** Previously named `bt-tether-helper`. See [migration guide](bt-tether-helper/README.md) for old links.

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
