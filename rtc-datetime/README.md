# 🕐 rtc-datetime

A simple plugin that displays the **current time and date** on the Pwnagotchi screen. It reads the **OS system clock** via Python's `time.strftime()` — it does not talk to any RTC hardware itself.

> **Display only.** This plugin renders whatever the operating system clock reports. Keeping that clock accurate while offline is an OS-level concern: configure NTP, and (optionally) a hardware RTC module, at the system level — see the setup notes below. This plugin does not read, write, or sync an RTC.

## ✨ Features

- **⏰ Customizable Format**: Configure time/date format using Python's strftime syntax
- **🎯 Configurable Position**: Place the display anywhere on your screen
- **🛡️ Format-safe**: an invalid format string falls back to the default instead of erroring every refresh

## 📦 Installation

### Step 1: Copy Plugin File

```bash
sudo cp rtc-datetime.py /usr/local/share/pwnagotchi/custom-plugins/
```

### Step 2: Enable in Config

Edit `/etc/pwnagotchi/config.toml` and add:

```toml
[main.plugins.rtc-datetime]
enabled = true
position = [0, 92]              # Optional: [x, y] position
format = "%H:%M %d-%m"          # Optional: time format
```

### Step 3: Restart Pwnagotchi

```bash
pwnkill
```

## ⚙️ Configuration Options

```toml
[main.plugins.rtc-datetime]
enabled = true                           # Enable/disable plugin
position = [0, 92]                       # Display position [x, y] (default: bottom-left)
format = "%H:%M %d-%m"                   # Time format (default: 24h + day-month)
```

## 📋 Time Format Examples

Common strftime format codes:

| Format        | Example                | Description                      |
| ------------- | ---------------------- | -------------------------------- |
| `%H:%M`       | 14:30                  | 24-hour time                     |
| `%I:%M %p`    | 02:30 PM               | 12-hour time with AM/PM          |
| `%d-%m-%Y`    | 25-12-2025             | Date as day-month-year           |
| `%m/%d/%Y`    | 12/25/2025             | Date as month/day/year           |
| `%A, %B %d`   | Wednesday, December 25 | Full weekday and month           |
| `%H:%M %d-%m` | 14:30 25-12            | Default format (24h + day-month) |
| `%j`          | 359                    | Day of year                      |
| `%w`          | 3                      | Day of week (0=Sunday)           |

> 📚 Full reference: [Python strftime documentation](https://docs.python.org/3/library/datetime.html#strftime-and-strptime-format-codes)

## 🌍 Setting Timezone / keeping time accurate on Raspberry Pi

The plugin displays the OS system time, so keeping that clock correct — timezone, NTP, and optionally a hardware RTC — is done at the system level, not by this plugin.

### Using raspi-config (Recommended)

```bash
sudo raspi-config
```

1. Navigate to `5 Localisation Options`
2. Select `L2 Timezone`
3. Choose your geographic area
4. Select your city/timezone
5. Exit and reboot

### Manual Check

```bash
# View current timezone
timedatectl

# List available timezones
timedatectl list-timezones

# Set timezone manually
sudo timedatectl set-timezone <timezone>
```

## 🔧 Troubleshooting

### ❌ Plugin Not Showing

- ✅ Check plugin is enabled: `grep rtc-datetime /etc/pwnagotchi/config.toml`
- ✅ Verify position is within screen bounds (e-ink display is typically 250×122 pixels)
- ✅ Check logs: `pwnlog` or `tail -f /var/log/pwnagotchi.log`

### ❌ Time Format Not Working

- ✅ Verify format string syntax: Local test in terminal
- ✅ Test format: `python3 -c "import datetime; print(datetime.datetime.now().strftime('%H:%M %d-%m'))"`
- ✅ Ensure quotes are properly escaped in TOML config
- ✅ Common issue: Missing `%` before format codes (e.g., `H:%M` instead of `%H:%M`)

### ❌ Time is Wrong

- ✅ Check system timezone: `timedatectl`
- ✅ Verify NTP is working: `timedatectl status`
- ✅ Check RTC battery: If using external RTC, verify it has power (coin-cell battery)
- ✅ Update system time: `sudo ntpdate -s pool.ntp.org` (requires internet)

## 📄 License

**GPL3**

## 👤 Author

**wsvdmeer**

## 📌 Version

**1.0.1**

## 🤝 Support

For issues or questions:

1. Check the troubleshooting section above
2. Review Pwnagotchi logs: `pwnlog`
3. Test time format in terminal before applying to config
