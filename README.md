# 📱 Pwnagotchi Plugins

> Collection of custom Pwnagotchi plugins for enhanced functionality and better connectivity.

---

## 📦 Available Plugins

### 🔷 bt-tether-helper

Comprehensive **Bluetooth tethering plugin** with web interface for managing internet connections from your phone.

- 🌐 **Web UI** for easy connection management
- 📡 **Automatic pairing** with guided setup (no manual MAC entry needed)
- 📊 **On-screen status** indicators with connection details
- 🔍 **Device scanning** and auto-discovery
- 🔄 **Auto-reconnect** with intelligent failure handling
- 🎮 **Discord notifications** (optional)

**[📖 Full documentation →](bt-tether-helper/README.md)**

---

### 🕐 rtc-datetime

Simple plugin to display **current time and date** on the Pwnagotchi screen with RTC support.

- ⏰ **Customizable time/date format** (strftime syntax)
- 🎯 **Configurable position** anywhere on screen
- 🔧 **RTC integration** with timezone support
- 📍 **Bottom-left placement** by default

**[📖 Full documentation →](rtc-datetime/README.md)**

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
