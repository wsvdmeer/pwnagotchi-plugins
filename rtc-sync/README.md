# rtc-sync (v1.0.0)

Keeps the Pwnagotchi system clock in sync with a hardware **DS3231 / DS1307**
RTC over I²C — **no kernel RTC driver or device-tree overlay required**. It
talks to the chip directly (like the other plugins here), so it works on a
stock Pwnagotchi image where `/dev/rtc` and `hwclock` don't exist.

Pwnagotchi has no internet most of the time, so after a reboot its clock is
wrong until it next gets NTP (e.g. over `bt-tether`). This plugin fixes that:
it **restores the clock from the RTC at boot**, and **writes good system time
back to the RTC** whenever the clock is valid — including right after tethering
brings the network up.

## What it does

- 🕓 **Boot restore** — if the system clock isn't set yet but the RTC holds a
  valid time, sets the system clock from the RTC (UTC).
- 💾 **Persist** — periodically writes the system time to the RTC once the clock
  is trustworthy, and clears the DS3231 **oscillator-stopped (OSF)** flag.
- 🔗 **Tether-aware** — listens for `bt_tether_connected` and, a short while
  after (once NTP has likely landed), persists the fresh time to the RTC.
- 🌍 **UTC in the RTC** — stores UTC on the chip regardless of the Pi's
  timezone, so it round-trips cleanly.

## Hardware

- A DS3231 (recommended — temperature-compensated) or DS1307 RTC on I²C bus 1,
  default address `0x68`. Many Waveshare e-ink HATs include one on-board.
- I²C enabled (`dtparam=i2c_arm=on`).

Check it's present:

```bash
i2cdetect -y 1   # expect a device at 0x68
```

> **Coin cell:** the RTC only keeps time across a full power-off if its backup
> battery is good. If it reads a nonsense date after a cold boot, replace the
> cell — this plugin will then re-seed it from NTP-synced system time.

## Installation

```bash
sudo cp rtc-sync.py /usr/local/share/pwnagotchi/custom-plugins/
pwnkill
```

Only depends on `smbus`, already present on Pwnagotchi images.

## Configuration

```toml
[main.plugins.rtc-sync]
enabled = true

i2c_bus = 1
i2c_address = "0x68"              # DS3231/DS1307 address (string or decimal)

set_system_from_rtc_on_boot = true  # restore clock from RTC at boot
write_rtc_when_synced = true         # persist good system time to the RTC
min_valid_year = 2024                # clock/RTC below this is treated as invalid
sync_interval = 3600                 # seconds between RTC writes (default 1 h)
post_connect_delay = 20              # seconds to wait after bt-tether connects
                                     # before writing the RTC (let NTP land)
```

### Notes

- **`min_valid_year`** guards against seeding either direction with a bogus
  epoch date. A clock reading before this year is considered "not set."
- Requires root to set the system clock — Pwnagotchi's plugin process runs as
  root, so no extra setup is needed.
- Works great alongside [`rtc-datetime`](../rtc-datetime/), which *displays* the
  clock; this plugin keeps the underlying clock correct.

## License

GPL3

## Author

**wsvdmeer**
