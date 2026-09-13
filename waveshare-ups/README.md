# waveshare-ups (v1.1.0)

Battery percentage display for the **Waveshare UPS HAT (C)** on Pwnagotchi, using
the on-board INA219 fuel-gauge over I²C.

Shows the estimated charge level on the e-ink screen, detects when the pack is
charging, and re-initialises the I²C device on its own if it wasn't ready at
boot — so it doesn't get stuck showing `--%`.

## Features

- **Battery icon + %** on the e-ink screen: a compact upright (or horizontal) battery glyph sized to match the status-bar text height, next to the exact percentage
- **Segmented gauge**: the battery fills as discrete bars (3 by default) that render crisply on a 1-bit display, or a proportional fill if you prefer
- **Smooth reading**: interpolated Li-ion discharge curve + rolling average, instead of coarse voltage steps that lurch between values
- **Charging detection**: reads INA219 current; appends `+` while the pack is charging (positive current)
- **Self-healing init**: if the I²C bus/device isn't ready when the plugin loads, it keeps retrying (rate-limited) rather than dying on the first failure
- **Configurable**: I²C bus/address, icon style/orientation/segments, screen position, update interval, and thresholds
- **Optional safe shutdown** at a critical charge level (opt-in, off by default)
- **Well-behaved**: does not force the pwnagotchi face expression

## Hardware

- Waveshare **UPS HAT (C)** (INA219 fuel gauge, default I²C address `0x43`, 0.1 Ω shunt)
- I²C enabled on the Pi (`dtparam=i2c_arm=on`)

Verify the chip is visible:

```bash
i2cdetect -y 1   # expect a device at 0x43
```

## Installation

1. **Copy the plugin to your custom plugins directory:**

   ```bash
   sudo cp waveshare-ups.py /usr/local/share/pwnagotchi/custom-plugins/
   ```

2. **Enable it in `config.toml`** (see below), then restart:

   ```bash
   pwnkill
   ```

The only dependency is `smbus`, already present on Pwnagotchi images.

## Configuration

```toml
[main.plugins.waveshare-ups]
enabled = true

# Hardware
i2c_bus = 1
i2c_address = "0x43"      # INA219 address; string ("0x43") or decimal (67)

# Display
battery_icon = true       # true: battery glyph; false: plain "BAT" text label
orientation = "vertical"  # "vertical" (upright, compact) or "horizontal"
segments = 3              # bars in the gauge (>1); set to 1 for a proportional fill
label = "BAT"             # text label used only when battery_icon = false
# position = [130, 0]     # [x, y]; omit to auto-place (top, right of centre)
update_interval = 10      # seconds between reads
smoothing = 3             # rolling-average window over readings (1 = off)
show_voltage = false      # show "3.94V" instead of "%" (ignored while charging)

# Charging / thresholds
charge_current_ma = 15    # current above this (mA) counts as "charging"
low_battery = 10          # log a warning at/below this %
critical_battery = 5      # % that counts as critical
shutdown_on_critical = false  # opt-in: safely power off at critical %
```

### Notes

- **`i2c_address`**: TOML has no hex literals, so pass the address as a string
  (`"0x43"`) or its decimal value (`67`).
- **Icon appearance**: the glyph auto-sizes to the status-bar digit height, so
  it lines up with the surrounding text. `orientation = "vertical"` is the
  compact upright battery; `"horizontal"` draws a wider battery with a terminal
  nub. `segments` controls how many discrete bars fill the gauge (`1` = smooth
  proportional fill). Set `battery_icon = false` to fall back to a plain `BAT`
  text label.
- **Charging sign**: verified on real hardware — a *positive* INA219 current
  means the pack is charging (discharge reads negative, idle ≈ 0 mA). Near a
  full charge the current tapers to only a few tens of mA, which is why the
  default threshold is a low `15 mA`. It's only used to show the `+` marker;
  it never affects the percentage.
- **`shutdown_on_critical`** is off by default. When enabled, the Pi runs a
  clean `pwnagotchi.shutdown()` once the (non-charging) level drops to
  `critical_battery`.

## How the percentage is estimated

Li-ion voltage sags under load and rises while charging, so a raw voltage
reading is noisy. This plugin:

1. reads the INA219 bus voltage every `update_interval` seconds,
2. averages the last `smoothing` readings, and
3. maps the result through an interpolated resting-discharge curve
   (4.20 V ≈ 100 %, 3.30 V ≈ 3 %, 3.00 V = 0 %).

It's an estimate, not a coulomb counter — expect a few percent of drift,
especially under heavy recon load.

## Troubleshooting

- **Always shows `--%`** — the INA219 isn't answering. Check `i2cdetect -y 1`
  for a device at `0x43`, confirm I²C is enabled, and check `pwnlog` for the
  `INA219 init failed` warning. The plugin retries every 30 s, so fixing the
  wiring/config clears it without a reboot.
- **Wrong address** — set `i2c_address` to whatever `i2cdetect` reports.
- **`+` never appears while charging** — your current sign/threshold differs;
  lower `charge_current_ma` or check the HAT is actually charging.

## License

GPL3

## Author

**wsvdmeer**
