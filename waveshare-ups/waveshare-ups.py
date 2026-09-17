import logging
import threading
import time

import pwnagotchi.plugins as plugins
import pwnagotchi.ui.fonts as fonts
from pwnagotchi.ui.components import LabeledValue, Widget
from pwnagotchi.ui.view import BLACK

# INA219 register map
_REG_CONFIG = 0x00
_REG_SHUNT_VOLTAGE = 0x01
_REG_BUS_VOLTAGE = 0x02
_REG_POWER = 0x03
_REG_CURRENT = 0x04
_REG_CALIBRATION = 0x05


class INA219:
    """Minimal INA219 driver calibrated for the Waveshare UPS HAT (C).

    Based on Waveshare's public reference driver. Provides bus voltage (V)
    and current (mA); a positive current means the pack is charging.
    """

    def __init__(self, i2c_bus=1, addr=0x43):
        import smbus  # imported lazily so a missing smbus doesn't kill import

        self.bus = smbus.SMBus(i2c_bus)
        self.addr = addr

        # UPS HAT (C): 0.1 ohm shunt, 32V / 2A calibration.
        # current LSB = 0.1 mA/bit, cal = 4096.
        self._current_lsb = 0.1
        self._cal_value = 4096
        self._configure()

    def _write(self, reg, value):
        data = [(value >> 8) & 0xFF, value & 0xFF]
        for attempt in range(3):  # absorb transient I2C glitches
            try:
                self.bus.write_i2c_block_data(self.addr, reg, data)
                return
            except OSError:
                if attempt == 2:
                    raise
                time.sleep(0.05)

    def _read(self, reg):
        for attempt in range(3):
            try:
                data = self.bus.read_i2c_block_data(self.addr, reg, 2)
                return (data[0] << 8) | data[1]
            except OSError:
                if attempt == 2:
                    raise
                time.sleep(0.05)

    def _configure(self):
        self._write(_REG_CALIBRATION, self._cal_value)
        # 32V range, /8 gain (320mV), 12-bit bus & shunt ADC, continuous.
        config = (0x01 << 13) | (0x03 << 11) | (0x0D << 7) | (0x0D << 3) | 0x07
        self._write(_REG_CONFIG, config)

    def bus_voltage(self):
        # Re-assert calibration in case the chip browned out / reset.
        self._write(_REG_CALIBRATION, self._cal_value)
        raw = self._read(_REG_BUS_VOLTAGE)
        return (raw >> 3) * 0.004  # volts

    def current_ma(self):
        raw = self._read(_REG_CURRENT)
        if raw > 32767:  # two's complement
            raw -= 65536
        return raw * self._current_lsb


# Resting Li-ion discharge curve as (voltage, percent) breakpoints, high -> low.
# Interpolated for a smooth reading instead of coarse steps.
_CURVE = [
    (4.20, 100),
    (4.10, 95),
    (4.00, 85),
    (3.90, 75),
    (3.80, 60),
    (3.75, 50),
    (3.70, 40),
    (3.65, 30),
    (3.60, 22),
    (3.50, 12),
    (3.40, 6),
    (3.30, 3),
    (3.00, 0),
]


class BatteryGauge(Widget):
    """A small battery glyph that auto-sizes to the text font, drawn to the
    left of the percentage. With ``segments > 1`` it renders as N discrete
    bars (crisp on 1-bit e-ink); otherwise it uses a proportional fill.

    ``value`` holds the percentage text (set via ``ui.set``) so change
    detection still triggers a redraw; ``percent`` / ``charging`` drive the
    glyph and are updated directly on the instance.
    """

    def __init__(self, position=(0, 0), font=None, color=BLACK,
                 segments=3, orientation="vertical", label_spacing=4):
        super().__init__(position, color)
        self.value = ""
        self.font = font
        self.percent = 0
        self.charging = False
        self.segments = segments
        self.orientation = orientation
        self.label_spacing = label_spacing

    def _font_height(self):
        try:
            ascent, descent = self.font.getmetrics()
            return ascent + descent
        except Exception:
            return 12

    def draw(self, canvas, drawer):
        if self.orientation == "horizontal":
            self._draw_horizontal(drawer)
        else:
            self._draw_vertical(drawer)

    def _draw_text(self, drawer, tx, ty):
        if self.value is not None:
            drawer.text((tx, ty), str(self.value), font=self.font, fill=self.color)

    def _lit(self, p, segs):
        lit = int(round(p / 100.0 * segs))
        if p > 0 and lit == 0:  # any charge shows at least one bar
            lit = 1
        return lit

    def _draw_vertical(self, drawer):
        """Compact upright battery sized to the digit cap-height (so it matches
        the surrounding status text), no terminal nub. Segments stack and fill
        from the bottom up."""
        x, y = self.xy

        # Narrow body sized to the digit cap-height so it lines up with the
        # capital letters beside it; a 1px terminal nub pokes out the top.
        try:
            bb = self.font.getbbox("8")
            cap_top, cap_h = bb[1], bb[3] - bb[1]
        except Exception:
            cap_top, cap_h = 3, 7
        h = max(6, cap_h)                       # body == cap height (matches "C")
        w = max(5, int(round(h * 0.72)))        # narrow
        top = y + cap_top
        bottom = top + h - 1
        right = x + w - 1

        # 1px terminal nub centered just above the body, then body outline.
        # Width leaves a 1px shoulder each side so it stays centered and reads
        # clearly as a nub.
        nub_w = max(3, w - 2)
        nub_x0 = x + (w - nub_w) // 2
        drawer.rectangle((nub_x0, top - 1, nub_x0 + nub_w - 1, top - 1),
                         fill=self.color)
        drawer.rectangle((x, top, right, bottom), outline=self.color)

        p = max(0, min(100, int(self.percent)))
        inner_l, inner_r = x + 1, right - 1
        inner_t, inner_b = top + 1, bottom - 1
        inner_h = inner_b - inner_t + 1

        if self.segments and self.segments > 1 and inner_h >= 2 * int(self.segments) - 1:
            segs = int(self.segments)
            gap = 1
            bar_h = max(1, (inner_h - gap * (segs - 1)) // segs)
            for i in range(self._lit(p, segs)):
                by1 = inner_b - i * (bar_h + gap)   # fill bottom-up
                drawer.rectangle((inner_l, by1 - bar_h + 1, inner_r, by1),
                                 fill=self.color)
        else:
            # Too short for clean segments -> proportional fill.
            fill_h = int(inner_h * p / 100.0)
            if p > 0 and fill_h == 0:
                fill_h = 1
            if fill_h > 0:
                drawer.rectangle((inner_l, inner_b - fill_h + 1, inner_r, inner_b),
                                 fill=self.color)

        # Percentage text to the right, aligned to the same baseline.
        self._draw_text(drawer, right + 1 + self.label_spacing, y)

    def _draw_horizontal(self, drawer):
        x, y = self.xy
        fh = self._font_height()
        h = max(8, fh - 3)
        w = int(h * 2.4)
        nub_w = max(2, h // 5)
        nub_h = max(3, h // 2)
        top = y + 1
        right = x + w

        drawer.rectangle((x, top, right, top + h), outline=self.color)
        ny0 = top + (h - nub_h) // 2
        drawer.rectangle((right, ny0, right + nub_w, ny0 + nub_h), fill=self.color)

        p = max(0, min(100, int(self.percent)))
        inner_l, inner_r = x + 2, right - 2
        inner_t, inner_b = top + 2, top + h - 2

        if self.segments and self.segments > 1:
            segs = int(self.segments)
            gap = 1
            bar_w = max(2, ((inner_r - inner_l) - gap * (segs - 1)) // segs)
            for i in range(self._lit(p, segs)):
                bx0 = inner_l + i * (bar_w + gap)
                drawer.rectangle((bx0, inner_t, bx0 + bar_w - 1, inner_b),
                                 fill=self.color)
        else:
            fill_w = int((inner_r - inner_l) * p / 100.0)
            if fill_w > 0:
                drawer.rectangle((inner_l, inner_t, inner_l + fill_w, inner_b),
                                 fill=self.color)

        self._draw_text(drawer, right + nub_w + self.label_spacing, y)


class WaveshareUPS(plugins.Plugin):
    __author__ = "wsvdmeer"
    __version__ = "1.2.0"
    __license__ = "GPL3"
    __description__ = "Battery gauge for the Waveshare UPS HAT (C): segmented battery icon, charging detection, self-healing I2C init, self-driven refresh."

    def __init__(self):
        self.ina = None
        self.options = {}
        self._gauge = None
        self._use_icon = True
        self._ui = None
        self._last_update = 0
        self._last_init_attempt = 0
        self._last_text = None
        self._samples = []
        self._lock = threading.Lock()
        self._worker = None
        self._running = False

    # ---- config helpers ---------------------------------------------------

    def _opt(self, key, default):
        return self.options.get(key, default)

    def _address(self):
        addr = self._opt("i2c_address", 0x43)
        if isinstance(addr, str):
            return int(addr, 0)  # accepts "0x43" or "67"
        return int(addr)

    def _try_init(self):
        """(Re)initialise the INA219, rate-limited so a missing HAT
        doesn't spam the log. Returns True on success."""
        now = time.time()
        if now - self._last_init_attempt < 30:
            return False
        self._last_init_attempt = now
        try:
            self.ina = INA219(
                i2c_bus=int(self._opt("i2c_bus", 1)),
                addr=self._address(),
            )
            logging.info("[waveshare-ups] INA219 initialised")
            return True
        except Exception as e:
            self.ina = None
            logging.warning("[waveshare-ups] INA219 init failed, will retry: %s", e)
            return False

    # ---- battery math -----------------------------------------------------

    def _voltage_to_percent(self, v):
        if v >= _CURVE[0][0]:
            return 100
        if v <= _CURVE[-1][0]:
            return 0
        for (hv, hp), (lv, lp) in zip(_CURVE, _CURVE[1:]):
            if lv <= v <= hv:
                # linear interpolation between the two breakpoints
                frac = (v - lv) / (hv - lv)
                return int(round(lp + frac * (hp - lp)))
        return 0

    def _smoothed(self, value):
        window = max(1, int(self._opt("smoothing", 3)))
        self._samples.append(value)
        if len(self._samples) > window:
            self._samples = self._samples[-window:]
        return sum(self._samples) / len(self._samples)

    # ---- plugin lifecycle -------------------------------------------------

    def on_loaded(self):
        logging.info("[waveshare-ups] plugin loaded")
        self._try_init()  # best-effort; on_ui_update retries if this fails

    def on_ui_setup(self, ui):
        pos = self._opt("position", None)
        if pos is None:
            pos = (ui.width() // 2 + 10, 0)
        pos = (int(pos[0]), int(pos[1]))

        self._use_icon = bool(self._opt("battery_icon", True))
        if self._use_icon:
            self._gauge = BatteryGauge(
                position=pos,
                font=fonts.Medium,
                color=BLACK,
                segments=int(self._opt("segments", 3)),
                orientation=self._opt("orientation", "vertical"),
            )
            ui.add_element("ups", self._gauge)
        else:
            ui.add_element(
                "ups",
                LabeledValue(
                    color=BLACK,
                    label=self._opt("label", "BAT"),
                    value="--%",
                    position=pos,
                    label_font=fonts.Bold,
                    text_font=fonts.Medium,
                ),
            )

        # With ui.fps = 0 the view only re-renders on other changes, so drive
        # our own refresh: a background thread reads the battery and forces a
        # redraw only when the displayed value actually changes.
        self._ui = ui
        if self._worker is None:
            self._running = True
            self._worker = threading.Thread(
                target=self._refresh_loop, name="waveshare-ups", daemon=True
            )
            self._worker.start()

    def _refresh_loop(self):
        while self._running:
            try:
                if self._read_and_apply(self._ui) and self._ui is not None:
                    # Force the e-ink refresh; only reached when the value moved.
                    self._ui.update(force=True)
            except Exception as e:
                logging.debug("[waveshare-ups] refresh loop: %s", e)
            # Sleep in 1s slices so unload/shutdown stays responsive.
            for _ in range(max(1, int(self._opt("update_interval", 10)))):
                if not self._running:
                    break
                time.sleep(1)

    def on_ui_update(self, ui):
        # Runs inside the normal render cycle (when other elements change).
        # Rate-limited and idempotent; the background loop drives idle updates.
        self._read_and_apply(ui)

    def _read_and_apply(self, ui):
        """Read the gauge and push the value into the UI element. Returns True
        only when the displayed text changed (so the caller can force a redraw).
        Rate-limited by ``update_interval`` and safe to call concurrently."""
        if ui is None:
            return False
        with self._lock:
            now = time.time()
            if now - self._last_update < int(self._opt("update_interval", 10)):
                return False
            self._last_update = now

            if self.ina is None and not self._try_init():
                return self._apply_text(ui, "--%", None, None)

            try:
                voltage = self._smoothed(self.ina.bus_voltage())
                percent = self._voltage_to_percent(voltage)

                charging = False
                try:
                    charging = self.ina.current_ma() > float(
                        self._opt("charge_current_ma", 15)
                    )
                except Exception:
                    pass  # current is a nice-to-have; never break the readout

                text = "{:d}%".format(percent)
                if charging:
                    text += "+"
                elif self._opt("show_voltage", False):
                    text = "{:.2f}V".format(voltage)

                low = int(self._opt("low_battery", 10))
                if (
                    self._opt("shutdown_on_critical", False)
                    and not charging
                    and percent <= int(self._opt("critical_battery", 5))
                ):
                    logging.warning(
                        "[waveshare-ups] battery critical (%d%%), shutting down", percent
                    )
                    import pwnagotchi

                    pwnagotchi.shutdown()
                elif percent <= low and not charging:
                    logging.info("[waveshare-ups] battery low: %d%%", percent)

                return self._apply_text(ui, text, percent, charging)

            except Exception as e:
                logging.error("[waveshare-ups] read error: %s", e)
                self.ina = None  # force a re-init on the next cycle
                return self._apply_text(ui, "--%", None, None)

    def _apply_text(self, ui, text, percent, charging):
        if self._use_icon and self._gauge is not None:
            if percent is not None:
                self._gauge.percent = percent
            if charging is not None:
                self._gauge.charging = charging
        ui.set("ups", text)
        if text != self._last_text:
            self._last_text = text
            return True
        return False

    def on_unload(self, ui):
        self._running = False
        try:
            with ui._lock:
                ui.remove_element("ups")
        except Exception:
            pass
