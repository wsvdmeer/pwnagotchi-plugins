# Pwnagotchi IP Finder

A simple web application that uses Web Bluetooth API to find and retrieve your Pwnagotchi's IP address via BLE (Bluetooth Low Energy).

## 🌐 Live Demo

Visit the live application: [https://YOUR-USERNAME.github.io/pwnagotchi-ip-finder/](https://YOUR-USERNAME.github.io/pwnagotchi-ip-finder/)

## 📱 How It Works

1. **Plugin Side**: The `bt-tether-helper` plugin broadcasts the Pwnagotchi's IP address via BLE by encoding it in the Bluetooth device name (e.g., `Pwn-192-168-1-123`)

2. **Web App Side**: This web application uses the Web Bluetooth API to scan for nearby Bluetooth devices, find your Pwnagotchi, and extract the IP address from the device name

## ✨ Features

- 🔍 **Easy Scanning**: One-click scanning for Pwnagotchi devices
- 📡 **Web Bluetooth**: No app installation required - works directly in your browser
- 📋 **One-Click Copy**: Copy the IP address to clipboard with a single click
- 📱 **Mobile Friendly**: Works on both desktop and mobile browsers that support Web Bluetooth
- 🎨 **Modern UI**: Clean, responsive interface with status indicators

## 🔧 Requirements

### For the Plugin

- Pwnagotchi with `bt-tether-helper` plugin version 0.9.0+ with BLE broadcasting enabled
- Bluetooth tethering configured on your Pwnagotchi

### For the Web App

- **Browsers**: Chrome, Edge, or Opera (Web Bluetooth API support required)
  - Chrome 56+ (Desktop & Android)
  - Edge 79+
  - Opera 43+
  - Samsung Internet 6.4+
- **Note**: Firefox and Safari do not currently support Web Bluetooth

## 🚀 Quick Start

### Using the Hosted Version

1. Visit [https://YOUR-USERNAME.github.io/pwnagotchi-ip-finder/](https://YOUR-USERNAME.github.io/pwnagotchi-ip-finder/)
2. Make sure your Pwnagotchi is powered on and nearby
3. Click "Scan for Devices"
4. Select your Pwnagotchi from the list
5. Your IP address will be displayed!

### Hosting Your Own

1. Fork this repository
2. Go to Settings → Pages
3. Set Source to "Deploy from a branch"
4. Select the `main` branch and `/root` folder
5. Click Save
6. Your site will be available at `https://YOUR-USERNAME.github.io/pwnagotchi-ip-finder/`

### Local Development

1. Clone this repository
2. Serve the files using any web server:

   ```bash
   # Using Python
   python -m http.server 8000

   # Or using Node.js
   npx serve
   ```

3. Open `http://localhost:8000` in a supported browser
4. **Important**: Web Bluetooth requires HTTPS or localhost

## 📦 Plugin Configuration

Make sure your `bt-tether-helper` plugin has BLE broadcasting enabled in your Pwnagotchi's `config.toml`:

```toml
main.plugins.bt-tether-helper.enabled = true
main.plugins.bt-tether-helper.mac = "XX:XX:XX:XX:XX:XX"  # Your phone's MAC
main.plugins.bt-tether-helper.ble_broadcast = true  # Enable BLE broadcasting
```

## 🛠️ Technical Details

### BLE Advertising Format

The plugin advertises the IP address by encoding it in the Bluetooth device name:

- Format: `Pwn-XXX-XXX-XXX-XXX`
- Example: `Pwn-192-168-1-123` represents IP `192.168.1.123`

### Web Bluetooth API

The web app uses the standard Web Bluetooth API to:

1. Request access to Bluetooth devices with `namePrefix: 'Pwn-'`
2. Parse the device name to extract the IP address
3. Display the result to the user

## 🔒 Privacy & Security

- **No Data Collection**: This app runs entirely in your browser and doesn't send any data to external servers
- **Local Processing**: All Bluetooth scanning and IP extraction happens locally
- **Open Source**: All code is available for inspection in this repository

## 🐛 Troubleshooting

### "Browser not supported" error

- Make sure you're using Chrome, Edge, or Opera
- Update your browser to the latest version

### "No devices found" error

- Ensure your Pwnagotchi is powered on and Bluetooth is enabled
- Make sure BLE broadcasting is enabled in the plugin configuration
- Try moving your device closer to your Pwnagotchi
- Check that the plugin is properly loaded: `sudo systemctl status pwnagotchi`

### "Security error" or Bluetooth access denied

- Web Bluetooth requires HTTPS or localhost
- If self-hosting, make sure you're accessing via HTTPS or localhost
- Check your browser's site permissions for Bluetooth access

## 📄 License

MIT License - See LICENSE file for details

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 🔗 Related Projects

- [Pwnagotchi](https://pwnagotchi.ai/) - AI-powered WiFi security tool
- [bt-tether-helper Plugin](../bt-tether-helper/) - Bluetooth tethering plugin for Pwnagotchi

## 📧 Support

If you encounter any issues or have questions:

1. Check the [Troubleshooting](#-troubleshooting) section
2. Open an issue on GitHub
3. Visit the [Pwnagotchi community](https://pwnagotchi.ai/)

---

Made with ❤️ for the Pwnagotchi community
