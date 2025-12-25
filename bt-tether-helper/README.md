# bt-tether-helper

A comprehensive Bluetooth tethering plugin that provides guided setup and automatic connection management for sharing your phone's internet connection with your Pwnagotchi.

> **Note:** This plugin has been tested on Android devices with [Pwnagotchi v2.9.5.3](https://github.com/jayofelony/pwnagotchi/releases/tag/v2.9.5.3). Compatibility with iOS and other Pwnagotchi versions may vary.

## Features

- **Web Interface**: User-friendly web UI for managing Bluetooth connections
- **Automatic Pairing**: Interactive pairing with passkey display and confirmation
- **Connection Management**: Connect, disconnect, and unpair devices with one click
- **Device Scanning**: Scan for nearby Bluetooth devices
- **Status Display**: Real-time connection status on Pwnagotchi screen
- **PAN (Personal Area Network) Support**: Automatic network interface configuration
- **Smart Recovery**: Automatically restarts Bluetooth service if unresponsive
- **Connection Caching**: Reduces polling to prevent performance issues

## Installation

1. Copy `bt-tether-helper.py` to your Pwnagotchi's custom plugins directory:

   ```bash
   sudo cp bt-tether-helper.py /usr/local/share/pwnagotchi/custom-plugins/
   ```

2. Install required dependencies:

   ```bash
   sudo apt-get update
   sudo apt-get install -y python3-dbus bluez
   ```

3. Enable the plugin in `/etc/pwnagotchi/config.toml`:

   ```toml
   main.plugins.bt-tether-helper.enabled = true
   main.plugins.bt-tether-helper.mac = "XX:XX:XX:XX:XX:XX"  # Optional: your phone's MAC
   main.plugins.bt-tether-helper.show_on_screen = true  # Optional: show status on display
   main.plugins.bt-tether-helper.position = [200, 0]  # Optional: custom position [x, y]
   ```

4. Restart Pwnagotchi:
   ```bash
   sudo systemctl restart pwnagotchi
   ```

## Usage

### Web Interface

Access the web interface at: `http://<pwnagotchi-ip>:8080/plugins/bt-tether-helper`

**Features:**

- **Connect**: Enter your phone's MAC address and initiate connection
- **Disconnect**: Safely disconnect from paired device
- **Unpair**: Remove pairing with a device
- **Scan**: Discover nearby Bluetooth devices
- **Status**: Real-time connection and internet status

### Connection Process

1. **Enable Bluetooth Tethering on Your Phone:**

   - **Android**: Settings → Connections → Bluetooth → More → Bluetooth tethering
   - **iPhone**: Settings → Personal Hotspot → Allow Others to Join

2. **Pairing (First Time Only):**

   - Enter your phone's MAC address in the web interface
   - Click "Connect"
   - A pairing dialog will appear on your phone
   - Verify the passkey matches on both devices
   - Tap "Pair" on your phone
   - Wait for connection to complete (up to 90 seconds)

3. **Subsequent Connections:**
   - Once paired, simply click "Connect" in the web interface
   - Device will automatically connect and establish internet connection

### On-Screen Status Indicators

When `show_on_screen` is enabled, a status indicator appears on the Pwnagotchi display:

- **C** = Connected with internet access
- **N** = Connected but no internet
- **P** = Paired but not connected
- **D** = Disconnected
- **?** = Unknown/Error

## Configuration Options

```toml
main.plugins.bt-tether-helper.enabled = true
main.plugins.bt-tether-helper.mac = ""  # Phone MAC address (optional, can set via web UI)
main.plugins.bt-tether-helper.show_on_screen = true  # Show status on display (default: true)
main.plugins.bt-tether-helper.position = [200, 0]  # Custom position [x, y] (optional)
```

## Troubleshooting

### Pairing Fails

- Ensure Bluetooth is enabled on your phone
- Make sure your phone is in Bluetooth settings (visible/discoverable)
- Check that pairing dialog appears on phone within 90 seconds
- Try unpairing the device first, then pair again

### Connection Succeeds but No Internet

- Enable Bluetooth tethering in your phone's settings
- Check that your phone has an active internet connection (mobile data or WiFi)
- Try disconnecting and reconnecting

### Bluetooth Service Unresponsive

- The plugin automatically detects and restarts hung Bluetooth services
- Manual restart: `sudo systemctl restart bluetooth`
- Check logs: `sudo journalctl -u pwnagotchi -f`

### Device Won't Disconnect

- Use the "Disconnect" button in web interface (automatically blocks device)
- Manual command: `bluetoothctl disconnect XX:XX:XX:XX:XX:XX`
- If still connected, unpair the device

## Advanced

### Finding Your Phone's MAC Address

**Android:**

```
Settings → About Phone → Status → Bluetooth address
```

**iPhone:**

```
Settings → General → About → Bluetooth
```

**Linux/Terminal:**

```bash
bluetoothctl devices
```

### Manual Commands

```bash
# List paired devices
bluetoothctl devices

# Check device info
bluetoothctl info XX:XX:XX:XX:XX:XX

# Manual connect
bluetoothctl connect XX:XX:XX:XX:XX:XX

# Manual disconnect
bluetoothctl disconnect XX:XX:XX:XX:XX:XX

# Check network interfaces
ip a
```

## API Endpoints

The plugin provides REST API endpoints for external control:

- `GET /plugins/bt-tether-helper` - Web interface
- `POST /plugins/bt-tether-helper/connect?mac=XX:XX:XX:XX:XX:XX` - Initiate connection
- `POST /plugins/bt-tether-helper/disconnect?mac=XX:XX:XX:XX:XX:XX` - Disconnect device
- `POST /plugins/bt-tether-helper/unpair?mac=XX:XX:XX:XX:XX:XX` - Unpair device
- `GET /plugins/bt-tether-helper/status` - Get current status
- `GET /plugins/bt-tether-helper/pair-status?mac=XX:XX:XX:XX:XX:XX` - Check pairing status
- `GET /plugins/bt-tether-helper/connection-status?mac=XX:XX:XX:XX:XX:XX` - Full connection details
- `GET /plugins/bt-tether-helper/scan` - Scan for devices (30 seconds)

## License

GPL3

## Author

**wsvdmeer**

## Version

1.0.0

## Support

For issues or questions:

1. Check the troubleshooting section above
2. Review Pwnagotchi logs: `sudo journalctl -u pwnagotchi -f`
3. Open an issue with detailed error messages and configuration
