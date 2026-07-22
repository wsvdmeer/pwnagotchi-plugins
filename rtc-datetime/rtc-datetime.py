import time
import logging
import pwnagotchi.plugins as plugins
import pwnagotchi.ui.fonts as fonts
from pwnagotchi.ui.components import LabeledValue
from pwnagotchi.ui.view import BLACK


class TimeDatePlugin(plugins.Plugin):
    __author__ = "wsvdmeer"
    __version__ = "1.0.1"
    __license__ = "GPL3"
    __description__ = "Display current date/time (from the OS system clock)"

    DEFAULT_POSITION = (0, 92)  # default X, Y
    DEFAULT_FORMAT = "%H:%M %d-%m"  # 24h + day-month

    def __init__(self):
        self.position = self.DEFAULT_POSITION
        self.format = self.DEFAULT_FORMAT

    def on_loaded(self):
        position = self.options.get("position")
        if isinstance(position, (list, tuple)) and len(position) == 2:
            self.position = tuple(position)
        elif position is not None:
            logging.warning(
                "[datetime] ignoring invalid 'position' option %r; using %s",
                position,
                self.DEFAULT_POSITION,
            )

        fmt = self.options.get("format")
        if isinstance(fmt, str) and fmt:
            self.format = fmt
        elif fmt is not None:
            logging.warning(
                "[datetime] ignoring invalid 'format' option %r; using %r",
                fmt,
                self.DEFAULT_FORMAT,
            )

        logging.info(f"[datetime] plugin loaded with position {self.position}")

    def on_ui_setup(self, ui):
        ui.add_element(
            "datetime",
            LabeledValue(
                color=BLACK,
                label="",
                value="--:--",
                position=self.position,
                label_font=fonts.Small,
                text_font=fonts.Small,
            ),
        )

    def on_ui_update(self, ui):
        # Reads the OS system clock (which the Pi keeps via NTP or a hardware RTC
        # configured at the OS level). A malformed format string would raise here
        # on every refresh, so fall back to the default rather than spam the loop.
        try:
            current = time.strftime(self.format)
        except (ValueError, TypeError):
            logging.warning(
                "[datetime] invalid format %r; falling back to default", self.format
            )
            self.format = self.DEFAULT_FORMAT
            current = time.strftime(self.format)
        ui.set("datetime", current)
