# bt-tether-helper

A comprehensive Bluetooth tethering plugin that provides guided setup and automatic connection management for sharing your phone's internet connection with your Pwnagotchi.

![bt-tether-helper Web Interface](ui.png)

> **⚠️ IMPORTANT - Known Issues:** The main branch has known issues with network routing that can interfere with existing network connections. **Please use the development branch instead:**
>
> **Use this branch:** [feature/0.9.0-beta](https://github.com/wsvdmeer/pwnagotchi-plugins/tree/feature/0.9.0-beta)
>
> This branch includes fixes for:
>
> - DHCP conflicts with existing network interfaces
> - Routing metric issues that override primary connections
> - Interface-specific DHCP client isolation

> **🚧 Work in Progress:** This plugin is currently in **beta** and under active development. Features and functionality may change.

> **⚠️ Important:** This plugin has been tested on an **Android 15** and **iOS 26.1** with [Pwnagotchi v2.9.5.3](https://github.com/jayofelony/pwnagotchi/releases/tag/v2.9.5.3). **Bluetooth tethering must be enabled on your device** for this plugin to work. Compatibility with other versions has not been tested.

## Tested Hardware Configuration

**Development & Testing:**

- **Device:** Raspberry Pi Zero 2WH
- **Display:** Waveshare 2.13-inch e-ink display (with built-in RTC chip and battery)
- **Power Management:** Waveshare UPS HAT (C)

_Optimizations have been applied for RPi Zero W2's resource constraints (512MB RAM, 1GB storage, slower CPU)._

## Features

- **Web Interface**: User-friendly web UI for managing Bluetooth connections
- **Automatic Pairing**: Interactive pairing with passkey display and confirmation
- **Connection Management**: Connect and disconnect devices with one click
- **Auto-Reconnect**: Automatically detects and reconnects dropped connections
- **Device Scanning**: Scan for nearby Bluetooth devices to find and copy MAC addresses
- **Status Display**: Real-time connection status on Pwnagotchi screen
- **PAN (Personal Area Network) Support**: Automatic network interface configuration
- **IP Advertising**: Optional Bluetooth device name updates with IP address (useful for headless operation)

## Installation

1. Copy `bt-tether-helper.py` to your Pwnagotchi's custom plugins directory:

   ```bash
   sudo cp bt-tether-helper.py /usr/local/share/pwnagotchi/custom-plugins/
   ```

2. Find your phone's MAC address:

   - Use the web interface scan function (see Usage section below), or
   - Check in Android: Settings → About Phone → Status → Bluetooth address

3. Add your phone's MAC address to `/etc/pwnagotchi/config.toml`:

   ```toml
   main.plugins.bt-tether-helper.enabled = true
   main.plugins.bt-tether-helper.mac = "XX:XX:XX:XX:XX:XX"
   ```

   > See [Configuration Options](#configuration-options) for additional settings (display, auto-reconnect, IP advertising, etc.)

4. Restart Pwnagotchi:
   ```bash
   pwnkill
   ```

> **Note:** All required dependencies (`dbus-python`, `toml`, `bluez`) are already included in Pwnagotchi - no additional packages needed!

## Usage

### Web Interface

Access the web interface at: `http://<pwnagotchi-ip>:8080/plugins/bt-tether-helper`

**Features:**

- **Connect to Phone**: Initiate connection to your configured device
- **Disconnect**: Safely disconnect from paired device (automatically unpairs)
- **Scan**: Discover nearby Bluetooth devices
- **Status**: Real-time connection and internet status
- **Internet Test**: Test connectivity with detailed diagnostics (ping, DNS, IP, routing)
- **Active Route Display**: Shows which network interface is handling internet traffic

### Network Priority

When multiple network interfaces are active (e.g., USB and Bluetooth), the web interface displays:

- **Active Route Indicator**: Shows which interface (usb0, bnep0, etc.) is currently handling internet traffic
- **USB Priority Warning**: Alerts when USB connection has priority over Bluetooth (USB typically has lower route metric)

> **Note:** When USB is connected, internet traffic uses the USB connection by default. Bluetooth tethering remains active as a standby connection and takes over automatically when USB is disconnected.

### Testing Internet Connectivity

Use the **"Test Internet Connectivity"** button in the web interface to verify your connection:

- **Ping Test**: Verifies IP connectivity to 8.8.8.8
- **DNS Test**: Tests DNS resolution using Python's socket library (resolves google.com)
- **DNS Servers**: Shows configured DNS servers from /etc/resolv.conf
- **Interface IP**: Shows the IP address assigned to bnep0
- **Default Route**: Displays the active routing configuration
- **Localhost Route**: Verifies localhost (127.0.0.1) routes correctly through loopback interface

This is especially useful for troubleshooting when you have multiple network interfaces active.

### Connection Process

1. **Enable Bluetooth Tethering on Your Android Phone:**

   Go to: Settings → Network & internet → Hotspot & tethering → Bluetooth tethering (Enable it)

   > **Note:** Bluetooth tethering **must be enabled** before attempting to connect.

2. **Pairing (First Time Only):**

   - Make sure your phone's MAC address is configured in `/etc/pwnagotchi/config.toml` (see Installation)
   - Click "Connect to Phone" in the web interface
   - A pairing dialog will appear on your phone
   - Verify the passkey matches on both devices
   - Tap "Pair" on your phone
   - Wait for connection to complete (up to 90 seconds)

3. **Subsequent Connections:**
   - Once paired, simply click "Connect to Phone" in the web interface
   - Device will automatically connect and establish internet connection

### On-Screen Status Indicators

The plugin provides two display modes that can be used independently or together:

**1. Compact Status (top-right corner):**

- Single-letter indicator (configurable via `position`)
- Minimal screen space usage
- Quick status at a glance

**2. Detailed Status (default: position [0, 82]):**

- Full status text with IP address when connected
- Shows pairing/trust state
- Configurable via `detailed_status_position`

Both displays update in real-time based on connection state.

## Configuration Options

```toml
# Core Settings
main.plugins.bt-tether-helper.enabled = true  # Enable the plugin
main.plugins.bt-tether-helper.mac = "XX:XX:XX:XX:XX:XX"  # Required: your phone's Bluetooth MAC address

# Display Settings - Compact Status (single-letter indicator)
main.plugins.bt-tether-helper.show_on_screen = true  # Show compact status on display (default: true)
main.plugins.bt-tether-helper.position = [200, 0]  # Custom position [x, y] for compact status (optional, default: auto top-right)

# Display Settings - Detailed Status (full status line with IP)
main.plugins.bt-tether-helper.show_detailed_status = true  # Show detailed status line with IP (default: true)
main.plugins.bt-tether-helper.detailed_status_position = [0, 82]  # Position for detailed status (default: [0, 82])

# Auto-Reconnect Settings
main.plugins.bt-tether-helper.auto_reconnect = true  # Automatically reconnect when connection drops (default: true)
main.plugins.bt-tether-helper.reconnect_interval = 60  # Check connection every N seconds (default: 60)

# IP Advertising (Headless Mode)
main.plugins.bt-tether-helper.advertise_ip = false  # Show IP in Bluetooth device name (default: false, enable for headless use)
```

### Display Options

**Compact Status (`show_on_screen`):**

- Shows single-letter status in top-right corner
- **C** = Connected with internet (PAN active)
- **T** = Connected and trusted (no internet yet)
- **N** = Connected but not trusted
- **P** = Paired but not connected
- **D** = Disconnected
- **>** = Connecting/Pairing in progress
- **?** = Unknown/Error

**Detailed Status (`show_detailed_status`):**

- Shows full status at configurable position (default: [0, 82])
- **BT:10.199.236.17** = Connected with IP address
- **BT:Trusted** = Connected and trusted but no IP yet
- **BT:Connected** = Connected but not trusted
- **BT:Paired** = Paired but not connected
- **BT:Connecting...** = Connection in progress
- **BT:Disconnecting...** = Disconnection in progress
- **BT:Disconnected** = Not connected

### Auto-Reconnect

The plugin includes automatic reconnection monitoring:

- **Enabled by default**: The plugin monitors your Bluetooth connection and automatically reconnects if it drops
- **Configurable interval**: Check connection status every 60 seconds by default (configurable via `reconnect_interval`)
- **Smart reconnection**: Only attempts reconnection when device is paired/trusted but disconnected
- **Non-intrusive**: Won't interfere with manual connection/disconnection operations

To disable auto-reconnect, set `main.plugins.bt-tether-helper.auto_reconnect = false` in your config.

## IP Advertising (Headless Mode)

For headless operation, the plugin can update your Bluetooth adapter's device name to include the current IP address, making it easy to find your Pwnagotchi's IP without SSH or display access.

### What is shown

- **Device Name**: Your Pwnagotchi name (from `main.name` in config.toml)
- **IP Address**: Current IP address from active interface (Bluetooth, USB, WiFi, or Ethernet)
- **Format**: `{pwnagotchi_name} | {ip_address}`

### How to view

The device will show up in your phone's Bluetooth settings with the updated name:

- **Android**: Settings → Bluetooth
- **iOS**: Settings → Bluetooth

The device name updates once after internet connectivity is verified, then again on each reconnection.

### Configuration

```toml
main.plugins.bt-tether-helper.advertise_ip = true  # Enable IP advertising (default: false)
```

> **Note**: This feature is **disabled by default** to avoid unnecessary name changes. Enable it if you use your Pwnagotchi in headless mode (no display/SSH).

## Troubleshooting

### Pairing Fails

- Ensure Bluetooth is enabled on your phone
- Make sure your phone is in Bluetooth settings (visible/discoverable)
- Check that pairing dialog appears on phone within 90 seconds
- Try unpairing the device first, then pair again

### Connection Succeeds but No Internet

- Enable Bluetooth tethering in your phone's settings
- Check that your phone has an active internet connection (mobile data or WiFi)
- Use the **"Test Internet Connectivity"** button in the web interface to diagnose the issue
- Check if USB is connected - if so, USB may be taking priority (see Active Route display)
- Try disconnecting and reconnecting

### Bluetooth Service Unresponsive

- The plugin automatically detects and restarts hung Bluetooth services
- Manual restart: `sudo systemctl restart bluetooth`
- Check logs: `pwnlog`

### Device Won't Disconnect

- Use the "Disconnect" button in web interface (automatically blocks device)
- Manual command: `bluetoothctl disconnect XX:XX:XX:XX:XX:XX`
- If still connected, unpair the device

### IP Not Showing in Device Name

- Ensure `advertise_ip = true` is set in your config.toml
- Check plugin logs: `pwnlog | grep bt-tether-helper`
- Ensure internet connectivity is established (feature waits for connectivity verification)
- Verify Bluetooth service is running: `sudo systemctl status bluetooth`
- Try restarting Pwnagotchi: `pwnkill`
- On your phone, try refreshing the Bluetooth device list or toggling Bluetooth off/on

## Advanced

### Finding Your Phone's MAC Address

**Android:**

```
Settings → About Phone → Status → Bluetooth address
```

**Via Terminal:**

```bash
bluetoothctl devices
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
- `GET /plugins/bt-tether-helper/test-internet` - Test internet connectivity with detailed diagnostics

## License

GPL3

## Author

**wsvdmeer**

## Version

0.9.9-beta

## Support

For issues or questions:

1. Check the troubleshooting section above
2. Review Pwnagotchi logs: `pwnlog`
3. Open an issue with detailed error messages and configuration
