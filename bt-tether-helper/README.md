# bt-tether-helper

> **🚧 Work in Progress:** This plugin is currently under active development. Features and functionality may change.
>
> **ℹ️ Note:** This plugin is a full replacement for the default [bt-tether.py](https://github.com/jayofelony/pwnagotchi/blob/noai/pwnagotchi/plugins/default/bt-tether.py) shipped with Pwnagotchi. It is not a helper or add-on for that plugin, but a standalone alternative with expanded features and improved reliability.
>
> **⚠️ Warning:** Do not enable both this plugin and the default bt-tether.py at the same time. Only one Bluetooth tethering plugin should be active to avoid conflicts.
>
> **⚠️ Ghost Connections Warning:** If you previously used the default `bt-tether.py` plugin, you may have ghost connection profiles left behind in NetworkManager. These can cause conflicts with D-Bus/BlueZ. See [Troubleshooting](#ghost-connections-from-previous-bt-tether-plugin) section for cleanup instructions.
>
> **✅ Important:** This plugin has been tested on an **Android 15 / 16** and **iOS 26.1** with [Pwnagotchi v2.9.5.4](https://github.com/jayofelony/pwnagotchi/releases/tag/v2.9.5.4). **Bluetooth tethering must be enabled on your device** for this plugin to work. Compatibility with other versions has not been tested.
>
> **⚠️ Android 16 Bug:** There is a known bug in Android 16 where Bluetooth tethering stays active after disconnecting Bluetooth. If you are using Android 16, you may need to manually disable Bluetooth tethering on your phone after disconnecting.

A comprehensive Bluetooth tethering plugin that provides guided setup and automatic connection management for sharing your phone's internet connection with your Pwnagotchi.

![bt-tether-helper Web Interface](ui.png)

![bt-tether-helper Screen Interface](screen.png)

## Tested Hardware Configuration

**Development & Testing:**

- **Device:** Raspberry Pi Zero 2WH
- **Display:** Waveshare 2.13-inch e-ink display (with built-in RTC chip and battery)
- **Power Management:** Waveshare UPS HAT (C)

_Optimizations have been applied for RPi Zero W2's resource constraints (512MB RAM, 1GB storage, slower CPU)._

## System Requirements

**Software:**

- Python 3.7+
- Pwnagotchi v2.9.5.4 or compatible
- Packages: bluez, network-manager, dbus-python, toml (all pre-included in Pwnagotchi)
- Services: bluetooth, NetworkManager (systemd)

**Hardware:**

- Bluetooth adapter with 5.0+ support recommended (NAP profile required)
- Network interface for DHCP configuration (bnep0 for tethering)
- Tested on Raspberry Pi Zero W2 (512MB RAM) - works well on higher-spec devices

**Tested Devices:**

- ✅ Android 15+ (NAP profile support required)
- ✅ iOS 26.1+ (NAP profile support required)
- ⚠️ Android 16 (see known issues in warnings above)

## Features

- **Web Interface**: User-friendly web UI for managing Bluetooth connections
- **Automatic Pairing**: Interactive pairing with passkey display and confirmation
- **Connection Management**: Connect and disconnect devices with one click
- **Auto-Reconnect**: Automatically detects and reconnects dropped connections
- **Device Scanning**: Scan for nearby Bluetooth devices to find and copy MAC addresses
- **Status Display**: Real-time connection status on Pwnagotchi screen
- **PAN (Personal Area Network) Support**: Automatic network interface configuration
- **Discord Notifications**: Optional webhook notifications when connected with IP address

## Installation

1. Copy `bt-tether-helper.py` to your Pwnagotchi's custom plugins directory:

   ```bash
   sudo cp bt-tether-helper.py /usr/local/share/pwnagotchi/custom-plugins/
   ```

2. Add the plugin to `/etc/pwnagotchi/config.toml`:

   ```toml
   [main.plugins.bt-tether-helper]
   enabled = true
   ```

   > See [Configuration Options](#configuration-options) for additional settings (display, auto-reconnect, Discord notifications, etc.)

3. Restart Pwnagotchi:
   ```bash
   pwnkill
   ```

> **Note:**
>
> - All required dependencies (`dbus-python`, `toml`, `bluez`) are already included in Pwnagotchi - no additional packages needed!
> - No MAC address configuration required - you can pair devices directly from the web interface
> - The plugin automatically saves your last connected device to `bt-tether-helper.state`

## Usage

### Web Interface

Access the web interface at: `http://<pwnagotchi-ip>:8080/plugins/bt-tether-helper`

**Features:**

- **Trusted Devices List**: View all paired and trusted devices
- **Connect**: Select and connect to any trusted device with one click
- **Forget**: Remove device from trusted devices list
- **Scan**: Discover nearby Bluetooth devices to add new connections
- **Status**: Real-time connection and internet status
- **Device Auto-Rotation**: When reconnection fails, automatically cycles through available trusted devices
- **Internet Test**: Test connectivity with detailed diagnostics (ping, DNS, IP, routing)
- **Active Route Display**: Shows which network interface is handling internet traffic

### Network Priority

When multiple network interfaces are active (e.g., USB and Bluetooth), the web interface displays:

- **Active Route Indicator**: Shows which interface (usb0, bnep0, etc.) is currently handling internet traffic
- **USB Priority Warning**: Alerts when USB connection has priority over Bluetooth (USB typically has lower route metric)

> **Note:** When multiple network interfaces are available (such as USB, Ethernet, or Bluetooth), internet traffic is always routed through the best available connection by default. Typically, the system prioritizes interfaces in this order: Ethernet (`eth0`), USB (`usb0`), then Bluetooth (`bnep0`). Bluetooth tethering remains active as a standby connection and will automatically take over if higher-priority connections (like USB or Ethernet) are disconnected. You can view the currently active interface and routing details in the web interface's status section. This ensures your Pwnagotchi always uses the most reliable and fastest available connection for internet access.

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

2. **Adding a New Device (First Time):**
   - Click "Scan" in the web interface to discover nearby devices
   - Select your phone from the device list
   - A pairing dialog will appear on your phone
   - Verify the passkey matches on both devices
   - Tap "Pair" on your phone
   - Wait for connection to complete (up to 90 seconds)
   - Once successfully connected, the device is automatically saved to your trusted devices list

   > **iOS Note:** iOS pairing follows the same flow. Ensure Bluetooth tethering is enabled in Settings → Personal Hotspot → Allow Others to Join.

3. **Subsequent Connections:**
   - Select your device from the "Trusted Devices" list
   - Click "Connect"
   - Device will automatically connect and establish internet connection (no pairing dialog needed)

4. **Removing a Device:**
   - Click "Forget" next to the device in the trusted devices list
   - The device will be unpaired and removed from the list

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
[main.plugins.bt-tether-helper]
# Core Settings
enabled = true  # Enable/disable the plugin (default: true)

# Display Settings - Master Switch
show_on_screen = true  # Master switch: enable/disable all screen displays (default: true)

# Display Settings - Mini Status (single-letter indicator)
show_mini_status = true  # Show mini status indicator (default: true)
mini_status_position = [110, 0]  # Position [x, y] for mini status (default: [110, 0])

# Display Settings - Detailed Status (full status line with IP)
show_detailed_status = true  # Show detailed status line with IP (default: true)
detailed_status_position = [0, 82]  # Position for detailed status (default: [0, 82])

# Auto-Reconnect Settings
auto_reconnect = true  # Automatically reconnect when connection drops (default: true)
reconnect_interval = 60  # Check connection every N seconds (default: 60)
reconnect_failure_cooldown = 300  # Cooldown after max failures in seconds (default: 300 = 5 minutes)

# Device Rotation
# When reconnection fails with multiple trusted devices available:
# - Automatically cycles through all available devices before pausing
# - Each failed device is marked in a cycle and next untried device is attempted
# - Rotation list resets after successful connection or when cooldown period expires

# Discord Notifications (Optional)
discord_webhook_url = ""  # Send IP notifications to Discord (optional)
```

### Display Options

**Master Switch (`show_on_screen`):**

- Global toggle to enable/disable all screen displays
- When set to `false`, no status information will be shown on screen
- Default: `true`

**Mini Status (`show_mini_status`):**

- Shows single-letter status indicator at top-right corner
- Position can be customized with `mini_status_position` as `[x, y]` coordinates (default: `[110, 0]`)
- Requires `show_on_screen = true`
- **I** = Initializing (plugin startup)
- **S** = Scanning for devices
- **C** = Connected with internet (PAN active)
- **T** = Connected and trusted (no internet yet)
- **N** = Connected but not trusted
- **P** = Paired but not connected / Pairing in progress
- **>** = Connecting in progress
- **R** = Reconnecting
- **W** = Switching devices
- **D** = Disconnecting
- **X** = Disconnected (no device)
- **?** = Unknown/Error

For custom positioning, use coordinates like `mini_status_position = [100, 10]` where [x, y] represents pixels from top-left.

**Detailed Status (`show_detailed_status`):**

- Shows full status at configurable position (default: [0, 82])
- **BT:Initializing...** = Plugin initializing
- **BT:10.199.236.17** = Connected with IP address
- **BT:Trusted** = Connected and trusted but no IP yet
- **BT:Connected** = Connected but not trusted
- **BT:Paired** = Paired but not connected
- **BT:Connecting...** = Connection in progress
- **BT:Reconnecting...** = Auto-reconnection in progress
- **BT:Disconnecting...** = Disconnection in progress
- **BT:Untrusting...** = Removing trust from device
- **BT:Disconnected** = Not connected
- **BT:Error** = Error/unknown state

Customize position with `detailed_status_position = [x, y]`.

### Auto-Reconnect with Device Rotation

The plugin includes intelligent automatic reconnection monitoring with device rotation and failure backoff:

- **Enabled by default**: Monitors your Bluetooth connection and automatically reconnects if it drops
- **Configurable interval**: Checks connection status every 60 seconds by default (via `reconnect_interval`)
- **Smart reconnection**: Only attempts reconnection when device is paired/trusted but disconnected
- **Device rotation**: When reconnection fails with multiple trusted devices available:
  - Automatically cycles through all available devices before pausing
  - Each failed device is marked and next untried device is attempted
  - Ensures resilience when a single phone becomes unavailable or unresponsive
  - Rotation list resets after successful connection or when cooldown expires
- **Failure handling**: After 5 consecutive failed attempts on a device, enters a 5-minute cooldown period
- **Non-intrusive**: Won't interfere with manual connection/disconnection operations
- **Respects user actions**: Doesn't auto-reconnect if you manually disconnected the device
- **Persistent state**: Last successfully connected device is saved to `bt-tether-helper.state`

To disable auto-reconnect:

```toml
[main.plugins.bt-tether-helper]
auto_reconnect = false
```

## Connection & Reconnection Flows

### Initial Connection Flow (First Time Pairing)

1. **User scans for devices** via web interface
2. **Device discovery** - Uses modern `bluetoothctl scan` to find nearby devices
3. **User selects device** from discovered list
4. **Trust status check** - Plugin checks if device is already trusted
5. **Pwnagotchi becomes discoverable** - Bluetooth adapter set to pairable/discoverable mode
6. **Pairing request sent** - Pwnagotchi requests pairing with phone
7. **Passkey dialog appears** on phone - User must accept within 90 seconds
8. **Trust device** - After successful pairing, device is marked as trusted for auto-connect
9. **Connect NAP service** - Establishes Bluetooth network connection (PAN profile) via D-Bus
10. **Wait for network interface** - bnep0 interface creation (up to 5 seconds)
11. **Configure network** - DHCP request to obtain IP address from phone
12. **Verify internet** - Tests connectivity to ensure tethering is working
13. **Status: CONNECTED** - Display shows "C" with IP address
14. **Device saved** - Automatically added to trusted devices list for future connections

**Typical duration:** 20-45 seconds for first-time pairing

### Subsequent Connection Flow (Already Paired)

1. **User selects device** from trusted devices list
2. **Verify device status** - Check if paired and trusted
3. **Ensure trust** - Re-verify trust status to enable auto-connect
4. **Connect NAP service** - Establish tethering connection via D-Bus ConnectProfile(NAP_UUID)
5. **Wait for interface** - bnep0 appears
6. **Configure network** - DHCP configuration
7. **Verify internet** - Connectivity test
8. **Status: CONNECTED** - Ready to use
9. **State saved** - Device with internet connection saved to `bt-tether-helper.state`

**Typical duration:** 10-20 seconds (no pairing dialog needed)

### Automatic Reconnection Flow with Device Rotation

When connection drops (phone BT disabled, out of range, etc.) with multiple trusted devices:

1. **Monitor detects disconnection** - Checks via `bluetoothctl info` and network interface status
2. **Device rotation enabled** - If multiple trusted devices available:
   - Attempts connection to next untried device in rotation list
   - Each failed device is marked and skipped in current cycle
   - Continues cycling through all available devices
3. **Success handling:**
   - Resets failure counter
   - Saves connected device to `bt-tether-helper.state`
   - Rotates back to start (will retry this device first on next failure)
   - Updates status to CONNECTED
   - Continues monitoring
4. **Failure handling:**
   - Increments failure counter for current device (max 5 attempts)
   - After 5 failures on a single device: Enters cooldown mode for 5 minutes
   - After cooldown expires: Resets counter and rotation cycle, tries again
   - When all devices in cycle exhausted: Waits for cooldown before new cycle
   - Logs warnings to help diagnose issues

**Benefits:**

- When primary phone becomes unavailable, automatically tries backup devices
- Ensures continuous connectivity when multiple trusted phones are available
- Rotation list automatically resets after successful connection

**Reconnection intervals:**

- **Normal**: Every 60 seconds (configurable via `reconnect_interval`)
- **After 5 failures**: 5-minute cooldown (configurable via `reconnect_failure_cooldown`)

### Disconnection Detection Methods

The plugin uses multiple layers to detect when a device disconnects:

1. **Fast Path - Network Interface Check:**

   ```bash
   ip link show  # Check for bnep interface
   ip addr show bnep0  # Check for IP address
   ```

   If bnep interface disappears or loses IP → Connection lost

2. **Bluetooth Status Check (Modern `bluetoothctl`):**

   ```bash
   bluetoothctl info <MAC_ADDRESS>
   ```

   Parses output for:
   - `Connected: yes/no` - Bluetooth connection status
   - `Paired: yes/no` - Pairing status
   - `Trusted: yes/no` - Trust/auto-connect status

3. **State Comparison:**
   - Compares current `connected` status with previous check
   - If was connected (`True`) and now isn't (`False`) → Disconnection detected
   - Triggers auto-reconnect flow with device rotation (unless user manually disconnected)

**What triggers reconnection:**

- Phone Bluetooth disabled → `Connected: no`
- Phone out of range → `Connected: no`
- Tethering disabled on phone → bnep interface disappears
- Connection lost for any reason → Status change detection
- Device unresponsive/NoReply errors → Tracks 3 failed attempts, then reduces polling frequency instead of removing pairing to ensure resilience for intermittently unavailable devices

### Manual Disconnection and Device Management

**Disconnect:**

When you click "Disconnect" in the web interface:

1. **Disconnect initiated** - Sets flag to prevent auto-reconnect
2. **NAP disconnect** - Closes Bluetooth network connection
3. **Block device** - Temporarily prevents automatic reconnection
4. **Status: DISCONNECTED** - Monitor won't attempt auto-reconnect
5. **Interface cleanup** - bnep interface removed

To reconnect, simply select the device and click "Connect" again.

**Forget Device:**

When you click "Forget" next to a trusted device:

1. **Unpair initiated** - Device is removed from trusted list
2. **Device forgotten** - Removed from pairing and trust cache
3. **State file updated** - Device no longer available for auto-connect
4. **Reconnection impossible** - Cannot auto-reconnect until re-paired

To use this device again, scan for it and pair it as a new device.

### Discord Notifications

Get notified when your Pwnagotchi connects via Bluetooth tethering:

- **Optional Feature**: Only activates when `discord_webhook_url` is configured
- **IP Address Notifications**: Automatically sends your device's IP address to a private Discord channel
- **Works with Auto-Reconnect**: Notifications sent both on manual connections and automatic reconnections
- **Easy Setup**: Just create a Discord webhook and add the URL to your config
- **Non-Blocking**: Runs in background thread, won't delay connection even if webhook fails

**How to set up Discord webhook:**

1. In your Discord server, go to Server Settings → Integrations → Webhooks
2. Click "New Webhook"
3. Give it a name (e.g., "Pwnagotchi BT")
4. Select the channel where you want notifications
5. Copy the webhook URL
6. Add it to your config:
   ```toml
   [main.plugins.bt-tether-helper]
   discord_webhook_url = "YOUR_WEBHOOK_URL"
   ```
7. Restart Pwnagotchi: `pwnkill`

When your device connects, you'll receive a notification with the IP address and device name!

**Troubleshooting Discord Notifications:**

- Check logs with `pwnlog` to see if the webhook is being called
- Verify the webhook URL is correct in your config
- Make sure your Pwnagotchi has internet access via the Bluetooth connection
- Test the webhook URL directly with a tool like curl to verify it's working

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

### Device Unresponsive or NoReply Errors

**Symptoms:**

- Connection attempts timeout
- "NoReply" errors in logs
- Device intermittently unavailable but not permanently off

**Handling:**

- The plugin automatically handles unresponsive devices with intelligent backoff:
  - First 3 failed connection attempts: Full retry
  - After 3 failures: Reduces polling frequency to avoid excessive log spam
  - Device remains paired and trusted for future reconnection attempts
  - Does NOT remove pairing, allowing the device to reconnect when responsive again
- This is more resilient than automatic unpair, especially for intermittently available devices
- If the device becomes permanently unavailable, use "Forget" to remove it from trusted devices

### Ghost Connections from Previous bt-tether Plugin

**⚠️ Important:** If you previously used the default `bt-tether.py` plugin and are now switching to `bt-tether-helper`, you may have "ghost" connection profiles left behind by NetworkManager. These can cause conflicts between NetworkManager and D-Bus/BlueZ, resulting in strange connection issues, failed pairings, or inability to connect.

**Symptoms:**

- Connection fails intermittently with D-Bus/BlueZ errors
- Strange behavior when pairing or connecting
- Multiple connection attempts required to establish connection
- "Device already connected" errors despite no active connection

**To Check for Ghost Profiles:**

```bash
# List all NetworkManager connections
sudo nmcli connection show

# List stored connection files
ls /etc/NetworkManager/system-connections/
```

Look for any Bluetooth tethering connections from your previous phone device names.

**To Remove Ghost Profiles:**

```bash
# Remove by UUID (from nmcli connection show output)
sudo nmcli connection delete <uuid>

# Remove stored connection file by name
sudo rm /etc/NetworkManager/system-connections/'phonename.nmconnection'
```

Replace `<uuid>` with the UUID from the `nmcli connection show` output and `phonename.nmconnection` with the actual filename.

After removing ghost profiles, restart the plugin:

```bash
pwnkill
```

## Performance & Resource Usage

**Tested Performance (RPi Zero W2, 512MB RAM):**

- **Memory usage:** ~15-25 MB (including web server)
- **CPU usage:** <5% during monitoring (polling every 60 seconds)
- **Network overhead:** Minimal - one ping per status check, no continuous polling
- **Thread usage:** 2 active (connection monitor + optional logging)

**Connection Timing:**

- **Device discovery:** 30-second scan, finds 8-15 devices
- **First-time pairing:** ~20-45 seconds from scan start to connected
- **Subsequent connections:** ~10-20 seconds (no pairing dialog)
- **Reconnection on drop:** ~10-15 seconds
- **DHCP assignment:** ~3-5 seconds
- **Total to internet verified:** ~30 seconds from scan initiation

**Optimization Notes:**

- `/status` endpoint uses cached device name - eliminates subprocess overhead on every 2-10s web UI poll
- Regex patterns compiled at class-level to avoid recompilation on each call
- Polling intervals configurable to balance responsiveness vs resource usage
- Native D-Bus connection instead of command-line tools for profile management

## Advanced

### Device State File

The plugin automatically maintains a state file at `~/.config/pwnagotchi/bt-tether-helper.state` that stores:

- **Last connected device**: MAC address and name of the device that last successfully connected with internet
- **Connection history**: Used by auto-reconnect to prioritize recently-working devices
- **Rotation state**: Tracks which devices have been attempted during the current reconnection cycle

This state file is:

- Automatically created and updated on first run
- Persisted in user's home config directory for multi-session continuity
- Used during auto-reconnection for intelligent device selection and rotation
- Resets when automatic reconnection cooldown expires
- Can be safely deleted to reset reconnection history: `rm ~/.config/pwnagotchi/bt-tether-helper.state`

**Full path:** `~/.config/pwnagotchi/bt-tether-helper.state` (typically `/root/.config/pwnagotchi/bt-tether-helper.state` on Pwnagotchi)

### Finding Your Phone's MAC Address

**Android:**

```
Settings → About Phone → Status → Bluetooth address
```

**iOS:**

```
Settings → General → About → Bluetooth
```

**Via Plugin:**

Use the web interface "Scan" feature to discover nearby devices and their MAC addresses - the simplest method!

### Network Configuration

**DHCP Setup:**

The plugin automatically handles DHCP configuration with built-in fallback:

- **Primary:** `dhcpcd` (recommended)
- **Fallback:** `dhclient` if `dhcpcd` unavailable
- **Interface:** bnep0 (NAP profile interface)
- **Automatic:** No manual configuration required

**DNS Configuration:**

- DNS servers are automatically provided by phone's DHCP response
- Verified via DNS resolution test (`google.com`)
- Displayed in web interface diagnostics
- Stored in `/etc/resolv.conf`

**Routing Priority:**

When multiple interfaces active, Linux routing metric determines priority:

- Ethernet (`eth0`): Typically metric 100-200 (highest priority)
- USB (`usb0`): Typically metric 300 (medium priority)
- Bluetooth (`bnep0`): Set to metric 200-500 (lower but still functional)

You can view active routes with: `ip route show`

## API Endpoints

The plugin provides REST API endpoints for external control and automation:

- `GET /plugins/bt-tether-helper` - Web interface
- `POST /plugins/bt-tether-helper/connect?mac=XX:XX:XX:XX:XX:XX` - Initiate connection to device
- `POST /plugins/bt-tether-helper/disconnect?mac=XX:XX:XX:XX:XX:XX` - Disconnect device
- `POST /plugins/bt-tether-helper/forget?mac=XX:XX:XX:XX:XX:XX` - Forget/unpair device from trusted list
- `GET /plugins/bt-tether-helper/status` - Get current connection status (uses cached device name for performance - no subprocess calls)
- `GET /plugins/bt-tether-helper/trusted-devices` - List all trusted devices with connection history
- `GET /plugins/bt-tether-helper/connection-status?mac=XX:XX:XX:XX:XX:XX` - Full connection details for device
- `GET /plugins/bt-tether-helper/scan` - Scan for devices (30 seconds using modern bluetoothctl)
- `GET /plugins/bt-tether-helper/test-internet` - Test internet connectivity with detailed diagnostics

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for detailed version history, improvements, and bug fixes.

## License

GPL3

## Author

**wsvdmeer**

## Support

For issues or questions:

1. Check the [troubleshooting section](#troubleshooting) above
2. Check [Performance & Resource Usage](#performance--resource-usage) for timing expectations
3. Review Pwnagotchi logs: `pwnlog` or `tail -f ~/.local/share/pwnagotchi/pwnagotchi.log`
4. Verify no ghost connections exist (see [Ghost Connections](#ghost-connections-from-previous-bt-tether-plugin))
5. Open an issue with detailed error messages and configuration
