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
   pwnkill
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

### Using raspi-config

```bash
sudo raspi-config
```

1. Select `5 Localisation Options`
2. Select `L2 Timezone`
3. Select your geographic area
4. Select your city/timezone
5. Exit and reboot

## Troubleshooting

### Plugin Not Showing

- Check plugin is enabled in `/etc/pwnagotchi/config.toml`
- Verify position is within screen bounds (e-ink display is typically 250x122 pixels)
- Check logs: `sudo journalctl -u pwnagotchi -f`

### Time Format Not Working

- Verify format string syntax: `man strftime`
- Test format in terminal: `date "+%H:%M %d-%m"`
- Ensure quotes are properly escaped in TOML config

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
