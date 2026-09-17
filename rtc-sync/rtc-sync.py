import logging
import subprocess
import threading
import time

import pwnagotchi.plugins as plugins


class DS3231:
    """Minimal userspace driver for a DS3231/DS1307-compatible RTC at 0x68.

    Time is stored in the RTC as UTC. No kernel rtc driver / overlay is
    required — we talk to the chip directly over I2C.
    """

    # register map (DS1307/DS3231 share the time registers)
    REG_SECONDS = 0x00
    REG_STATUS = 0x0F  # DS3231 status; bit7 = OSF (oscillator stopped)

    def __init__(self, i2c_bus=1, addr=0x68):
        import smbus

        self.bus = smbus.SMBus(i2c_bus)
        self.addr = addr

    @staticmethod
    def _bcd2int(v):
        return (v >> 4) * 10 + (v & 0x0F)

    @staticmethod
    def _int2bcd(v):
        return ((v // 10) << 4) | (v % 10)

    def oscillator_stopped(self):
        """True if the RTC lost power / its time is not trustworthy."""
        try:
            return bool(self.bus.read_byte_data(self.addr, self.REG_STATUS) & 0x80)
        except Exception:
            return False

    def _clear_osf(self):
        try:
            st = self.bus.read_byte_data(self.addr, self.REG_STATUS)
            self.bus.write_byte_data(self.addr, self.REG_STATUS, st & 0x7F)
        except Exception:
            pass  # DS1307 has no status register; harmless

    def read_utc(self):
        """Return the RTC time as a UTC time.struct_time."""
        r = self.bus.read_i2c_block_data(self.addr, self.REG_SECONDS, 7)
        sec = self._bcd2int(r[0] & 0x7F)
        minute = self._bcd2int(r[1] & 0x7F)
        hour = self._bcd2int(r[2] & 0x3F)  # force 24h interpretation
        date = self._bcd2int(r[4] & 0x3F)
        month = self._bcd2int(r[5] & 0x1F)
        year = 2000 + self._bcd2int(r[6])
        return time.struct_time((year, month, date, hour, minute, sec, 0, 0, 0))

    def write_utc(self, t):
        """Write a UTC time.struct_time to the RTC and clear the OSF flag."""
        data = [
            self._int2bcd(t.tm_sec) & 0x7F,
            self._int2bcd(t.tm_min),
            self._int2bcd(t.tm_hour) & 0x3F,   # 24h mode
            self._int2bcd(t.tm_wday + 1),      # 1..7
            self._int2bcd(t.tm_mday),
            self._int2bcd(t.tm_mon),
            self._int2bcd(t.tm_year % 100),
        ]
        self.bus.write_i2c_block_data(self.addr, self.REG_SECONDS, data)
        self._clear_osf()


class RTCSync(plugins.Plugin):
    __author__ = "wsvdmeer"
    __version__ = "1.0.0"
    __license__ = "GPL3"
    __description__ = "Keeps the system clock in sync with a DS3231/DS1307 RTC: restore time at boot, persist good time back to the RTC (no kernel overlay needed)."

    def __init__(self):
        self.rtc = None
        self.options = {}
        self._worker = None
        self._running = False

    def _opt(self, key, default):
        return self.options.get(key, default)

    def _address(self):
        addr = self._opt("i2c_address", 0x68)
        if isinstance(addr, str):
            return int(addr, 0)
        return int(addr)

    def _min_year(self):
        return int(self._opt("min_valid_year", 2024))

    def _system_time_is_good(self):
        return time.gmtime().tm_year >= self._min_year()

    def _rtc_time_is_good(self):
        if self.rtc is None:
            return False
        if self.rtc.oscillator_stopped():
            return False
        try:
            return self.rtc.read_utc().tm_year >= self._min_year()
        except Exception:
            return False

    def _set_system_from_rtc(self):
        try:
            t = self.rtc.read_utc()
            stamp = time.strftime("%Y-%m-%d %H:%M:%S", t)
            # pwnagotchi runs as root, so setting the clock is permitted.
            subprocess.run(
                ["date", "-u", "-s", stamp],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            logging.info("[rtc-sync] system clock set from RTC: %s UTC", stamp)
            return True
        except Exception as e:
            logging.warning("[rtc-sync] could not set system clock from RTC: %s", e)
            return False

    def _write_rtc_from_system(self):
        try:
            self.rtc.write_utc(time.gmtime())
            logging.info(
                "[rtc-sync] RTC updated from system clock: %s UTC",
                time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
            )
            return True
        except Exception as e:
            logging.warning("[rtc-sync] could not write RTC: %s", e)
            return False

    def on_loaded(self):
        try:
            self.rtc = DS3231(
                i2c_bus=int(self._opt("i2c_bus", 1)), addr=self._address()
            )
        except Exception as e:
            logging.error("[rtc-sync] RTC init failed: %s", e)
            self.rtc = None
            return

        logging.info("[rtc-sync] plugin loaded")

        # At boot: if the system clock is not yet set (offline) but the RTC
        # holds a valid time, restore it from the RTC.
        if self._opt("set_system_from_rtc_on_boot", True):
            if not self._system_time_is_good() and self._rtc_time_is_good():
                self._set_system_from_rtc()
            elif self.rtc.oscillator_stopped():
                logging.info(
                    "[rtc-sync] RTC oscillator flag set (time invalid); "
                    "will write it once the system clock is good"
                )

        self._running = True
        self._worker = threading.Thread(
            target=self._sync_loop, name="rtc-sync", daemon=True
        )
        self._worker.start()

    def _sync_loop(self):
        interval = max(60, int(self._opt("sync_interval", 3600)))
        while self._running:
            try:
                if self._opt("write_rtc_when_synced", True) and self._system_time_is_good():
                    self._write_rtc_from_system()
            except Exception as e:
                logging.debug("[rtc-sync] sync loop: %s", e)
            for _ in range(interval):
                if not self._running:
                    break
                time.sleep(1)

    def on_bt_tether_connected(self, agent, event_data):
        """When tethering comes up the OS usually gets NTP shortly after —
        persist that good time to the RTC (best-effort, non-blocking)."""
        if self.rtc is None:
            return

        def _later():
            time.sleep(int(self._opt("post_connect_delay", 20)))
            if self._system_time_is_good():
                self._write_rtc_from_system()

        threading.Thread(target=_later, name="rtc-sync-onconnect", daemon=True).start()

    def on_unload(self, ui):
        self._running = False
