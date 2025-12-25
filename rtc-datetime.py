import time
import logging
import pwnagotchi.plugins as plugins
import pwnagotchi.ui.fonts as fonts
from pwnagotchi.ui.components import LabeledValue
from pwnagotchi.ui.view import BLACK


class TimeDatePlugin(plugins.Plugin):
    __author__ = "wsvdmeer"
    __version__ = "1.0.0"
    __license__ = "GPL3"
    __description__ = "Display current time and date"

    def __init__(self):
        self.ready = False
        self.position = (0, 110)  # default X, Y
        self.format = "%H:%M %d-%m"  # 24h + day-month

    def on_loaded(self):
        if "position" in self.options:
            self.position = tuple(self.options["position"])
        if "format" in self.options:
            self.format = self.options["format"]
        logging.info(f"[datetime] plugin loaded with position {self.position}")
        self.ready = True

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
        current = time.strftime(self.format)  # uses system time / RTC
        ui.set("datetime", current)
