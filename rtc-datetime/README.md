# rtc-datetime

A simple plugin that displays the current time and date on the Pwnagotchi screen using the system's RTC (Real-Time Clock).

## Features

- **Customizable Format**: Configure time/date format using Python strftime syntax
- **Configurable Position**: Place the time/date display anywhere on screen
- **RTC Integration**: Uses Raspberry Pi's hardware RTC or system time

## Installation

1. Copy `rtc-datetime.py` to your Pwnagotchi's custom plugins directory:

   ```bash
   sudo cp rtc-datetime.py /usr/local/share/pwnagotchi/custom-plugins/
   ```

2. Enable the plugin in `/etc/pwnagotchi/config.toml`:

   ```toml
   main.plugins.rtc-datetime.enabled = true
   main.plugins.rtc-datetime.position = [0, 92]  # Optional: [x, y] position
   main.plugins.rtc-datetime.format = "%H:%M %d-%m"  # Optional: time format
   ```

3. Restart Pwnagotchi:
   ```bash
   sudo systemctl restart pwnagotchi
   ```

## Configuration Options

```toml
main.plugins.rtc-datetime.enabled = true
main.plugins.rtc-datetime.position = [0, 92]  # Display position [x, y] (default: bottom-left)
main.plugins.rtc-datetime.format = "%H:%M %d-%m"  # Time format (default: 24h + day-month)
```

## Time Format Examples

Common strftime format codes:

- `%H:%M` - 24-hour time (14:30)
- `%I:%M %p` - 12-hour time with AM/PM (02:30 PM)
- `%d-%m-%Y` - Date as day-month-year (25-12-2025)
- `%m/%d/%Y` - Date as month/day/year (12/25/2025)
- `%A, %B %d` - Full weekday and month (Wednesday, December 25)
- `%H:%M %d-%m` - Default format (14:30 25-12)

Full list of format codes: [Python strftime documentation](https://docs.python.org/3/library/datetime.html#strftime-and-strptime-format-codes)

## Setting Timezone on Raspberry Pi

The plugin uses the system time, so it's important to configure the correct timezone on your Raspberry Pi.

### Method 1: Using raspi-config (Recommended)

```bash
sudo raspi-config
```

1. Select `5 Localisation Options`
2. Select `L2 Timezone`
3. Select your geographic area
4. Select your city/timezone
5. Exit and reboot

### Method 2: Using timedatectl

```bash
# List available timezones
timedatectl list-timezones

# Set timezone (example: US Eastern Time)
sudo timedatectl set-timezone America/New_York

# Set timezone (example: Central European Time)
sudo timedatectl set-timezone Europe/Amsterdam

# Verify timezone
timedatectl
```

### Method 3: Manual Configuration

```bash
# Create symbolic link to timezone file
sudo ln -sf /usr/share/zoneinfo/America/New_York /etc/localtime

# Update timezone configuration
echo "America/New_York" | sudo tee /etc/timezone

# Reconfigure tzdata
sudo dpkg-reconfigure -f noninteractive tzdata
```

### Common Timezones

- **US Pacific**: `America/Los_Angeles`
- **US Mountain**: `America/Denver`
- **US Central**: `America/Chicago`
- **US Eastern**: `America/New_York`
- **UK**: `Europe/London`
- **Central Europe**: `Europe/Berlin`, `Europe/Amsterdam`, `Europe/Paris`
- **Eastern Europe**: `Europe/Athens`, `Europe/Bucharest`
- **Australia**: `Australia/Sydney`, `Australia/Melbourne`
- **Japan**: `Asia/Tokyo`
- **India**: `Asia/Kolkata`

### Setting System Time Manually

If your Pwnagotchi doesn't have internet access to sync time automatically:

```bash
# Set date and time manually (YYYY-MM-DD HH:MM:SS)
sudo date -s "2025-12-25 14:30:00"

# Sync hardware clock with system time
sudo hwclock --systohc

# Read hardware clock
sudo hwclock --show
```

### Enable NTP Time Sync (if internet available)

```bash
# Install NTP
sudo apt-get install -y ntp

# Enable NTP synchronization
sudo timedatectl set-ntp true

# Check NTP status
timedatectl
```

## Troubleshooting

### Time is Incorrect

- Check timezone: `timedatectl`
- Set correct timezone (see above)
- Manually set time if no internet: `sudo date -s "YYYY-MM-DD HH:MM:SS"`
- Sync hardware clock: `sudo hwclock --systohc`

### Plugin Not Showing

- Check plugin is enabled in `/etc/pwnagotchi/config.toml`
- Verify position is within screen bounds (e-ink display is typically 250x122 pixels)
- Check logs: `sudo journalctl -u pwnagotchi -f`

### Time Format Not Working

- Verify format string syntax: `man strftime`
- Test format in terminal: `date "+%H:%M %d-%m"`
- Ensure quotes are properly escaped in TOML config

### Display Position Issues

The Pwnagotchi e-ink display is typically **250x122 pixels**. Make sure your position coordinates are within these bounds:

```toml
# Examples of valid positions:
main.plugins.rtc-datetime.position = [0, 0]      # Top-left corner
main.plugins.rtc-datetime.position = [0, 92]     # Bottom-left (default)
main.plugins.rtc-datetime.position = [180, 0]    # Top-right area
main.plugins.rtc-datetime.position = [100, 60]   # Center area
```

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
3. Test time format in terminal before applying to config
