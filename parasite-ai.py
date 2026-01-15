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
from flask import render_template_string
import pwnagotchi.ui.fonts as fonts


# -------------------------
# HTML Template
# -------------------------

HTML_TEMPLATE = """<!DOCTYPE html>
<html>
  <head>
    <title>ParasiteAI Dashboard</title>
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <style>
      body { font-family: sans-serif; padding: 20px; max-width: 600px; margin: 0 auto; background: #0d1117; color: #d4d4d4; }
      .card { background: #161b22; padding: 20px; border-radius: 8px; margin-bottom: 16px; box-shadow: 0 2px 4px rgba(0,0,0,0.3); border: 1px solid #30363d; }
      h2 { margin: 0 0 20px 0; color: #58a6ff; }
      h3 { color: #d4d4d4; }
      h4 { color: #8b949e; }
      input { padding: 10px; font-size: 14px; border: 1px solid #30363d; border-radius: 4px; background: #0d1117; color: #d4d4d4; }
      input:focus { outline: none; border-color: #58a6ff; background: #161b22; }
      button { padding: 10px 20px; background: transparent; color: #3fb950; border: 1px solid #3fb950; cursor: pointer; font-size: 14px; border-radius: 4px; margin-right: 8px; min-height: 42px; display: inline-flex; align-items: center; justify-content: center; }
      button:hover { background: rgba(63, 185, 80, 0.1); border-color: #3fb950; }
      button.danger { color: #f85149; border-color: #f85149; }
      button.danger:hover { background: rgba(248, 81, 73, 0.1); }
      button:disabled { background: transparent; color: #8b949e; cursor: not-allowed; border-color: #30363d; }
      .status-item { padding: 8px; margin: 4px 0; border-radius: 4px; background: #161b22; border: 1px solid #30363d; color: #d4d4d4; }
      .status-good { background: rgba(46, 160, 67, 0.15); color: #3fb950; border-color: #3fb950; }
      .status-bad { background: rgba(248, 81, 73, 0.15); color: #f85149; border-color: #f85149; }
      .status-warning { background: rgba(214, 159, 0, 0.15); color: #d29922; border-color: #d29922; }
      .message-box { padding: 12px; border-radius: 4px; margin: 12px 0; border-left: 4px solid; }
      .message-info { background: rgba(88, 166, 255, 0.1); color: #79c0ff; border-color: #79c0ff; }
      .message-success { background: rgba(63, 185, 80, 0.1); color: #3fb950; border-color: #3fb950; }
      .message-warning { background: rgba(214, 159, 0, 0.1); color: #d29922; border-color: #d29922; }
      .message-error { background: rgba(248, 81, 73, 0.1); color: #f85149; border-color: #f85149; }
      .stats-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin: 12px 0; }
      .stat-box { background: #0d1117; padding: 12px; border-radius: 4px; border: 1px solid #30363d; }
      .stat-label { color: #8b949e; font-size: 12px; margin-bottom: 4px; }
      .stat-value { color: #4ec9b0; font-size: 18px; font-weight: bold; }
      .spinner { display: inline-block; width: 14px; height: 14px; border: 2px solid #30363d; 
                 border-top: 2px solid #58a6ff; border-radius: 50%; animation: spin 1s linear infinite; margin-right: 8px; vertical-align: middle; }
      @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
      .log-viewer { background: #0d1117; color: #d4d4d4; padding: 12px; border-radius: 4px; font-family: 'Courier New', monospace; font-size: 12px; max-height: 300px; overflow-y: auto; line-height: 1.5; border: 1px solid #30363d; }
      .log-entry { margin: 2px 0; }
      .log-error { color: #f48771; }
      .log-warning { color: #dcdcaa; }
      .log-info { color: #4fc1ff; }
      .log-debug { color: #888; }
      .log-timestamp { color: #888; margin-right: 8px; }
      .log-level { font-weight: bold; margin-right: 8px; }
    </style>
  </head>
  <body>
    <h2>🦠 ParasiteAI Dashboard</h2>
    
    <!-- Status Card -->
    <div class="card">
      <h3 style="margin: 0 0 12px 0;">📊 Current Status</h3>
      <div class="stats-grid">
        <div class="stat-box">
          <div class="stat-label">Current Mood</div>
          <div class="stat-value" id="moodValue">Loading...</div>
        </div>
        <div class="stat-box">
          <div class="stat-label">State</div>
          <div class="stat-value" id="stateValue">Loading...</div>
        </div>
        <div class="stat-box">
          <div class="stat-label">Aggression Level</div>
          <div class="stat-value" id="aggressionValue">Loading...</div>
        </div>
        <div class="stat-box">
          <div class="stat-label">Consecutive Fails</div>
          <div class="stat-value" id="failsValue">Loading...</div>
        </div>
      </div>
      
      <!-- Statistics -->
      <div style="background: #0d1117; color: #d4d4d4; padding: 12px; border-radius: 4px; margin-top: 12px; border: 1px solid #30363d;">
        <div style="display: flex; justify-content: space-between; margin: 8px 0;">
          <span>✓ Successful Handshakes:</span>
          <span style="color: #3fb950; font-weight: bold;" id="successCount">0</span>
        </div>
        <div style="display: flex; justify-content: space-between; margin: 8px 0;">
          <span>✗ Failed Attacks:</span>
          <span style="color: #f85149; font-weight: bold;" id="failCount">0</span>
        </div>
        <div style="display: flex; justify-content: space-between; margin: 8px 0;">
          <span>📈 Success Rate:</span>
          <span style="color: #4ec9b0; font-weight: bold;" id="successRate">0%</span>
        </div>
      </div>
    </div>
    
    <!-- Aggression Control -->
    <div class="card">
      <h3 style="margin: 0 0 12px 0;">⚡ Aggression Control</h3>
      <div style="margin-bottom: 12px;">
        <button onclick="changeAggression('mellow')" style="width: 100%; margin: 0 0 8px 0;">😴 Mellow</button>
        <button onclick="changeAggression('balanced')" style="width: 100%; margin: 0 0 8px 0;">👀 Balanced</button>
        <button onclick="changeAggression('aggro')" style="width: 100%; margin: 0 0 8px 0;">😈 Aggressive</button>
      </div>
      <small style="color: #8b949e; display: block;">Control AI aggression level and attack probability</small>
    </div>
    
    <!-- Plugin Options -->
    <div class="card">
      <h3 style="margin: 0 0 12px 0;">⚙️ Plugin Options</h3>
      <div style="background: #0d1117; color: #d4d4d4; padding: 12px; border-radius: 4px; border: 1px solid #30363d;">
        <div style="display: flex; justify-content: space-between; margin: 8px 0;">
          <span>Min RSSI:</span>
          <span style="color: #4ec9b0; font-weight: bold;" id="minRssi">-80</span>
        </div>
        <div style="display: flex; justify-content: space-between; margin: 8px 0;">
          <span>Min Clients:</span>
          <span style="color: #4ec9b0; font-weight: bold;" id="minClients">0</span>
        </div>
        <div style="display: flex; justify-content: space-between; margin: 8px 0;">
          <span>Max Consecutive Fails:</span>
          <span style="color: #4ec9b0; font-weight: bold;" id="maxFails">3</span>
        </div>
        <div style="display: flex; justify-content: space-between; margin: 8px 0;">
          <span>Save Interval:</span>
          <span style="color: #4ec9b0; font-weight: bold;" id="saveInterval">10</span>
        </div>
        <div style="display: flex; justify-content: space-between; margin: 8px 0;">
          <span>Debug Logs:</span>
          <span style="color: #4ec9b0; font-weight: bold;" id="debugLogs">OFF</span>
        </div>
      </div>
    </div>
    
    <!-- Logs -->
    <div class="card">
      <h3 style="margin: 0 0 12px 0;">📋 Logs</h3>
      <div id="logViewer" class="log-viewer">
        <div style="color: #888;">Loading logs...</div>
      </div>
    </div>
    
    <script>
      // Auto-refresh status every 2 seconds
      function updateStatus() {
        fetch('/plugins/parasite-ai/status')
          .then(r => r.json())
          .then(data => {
            console.log('Status data:', data);
            if (data.error) {
              console.error('Status API error:', data.error);
              return;
            }
            document.getElementById('stateValue').textContent = (data.state || 'UNKNOWN').toUpperCase();
            document.getElementById('moodValue').textContent = data.mood || 'Unknown';
            document.getElementById('aggressionValue').textContent = (data.aggression || 'unknown').toUpperCase();
            document.getElementById('failsValue').textContent = data.consecutive_fails || 0;
            document.getElementById('successCount').textContent = data.success || 0;
            document.getElementById('failCount').textContent = data.fail || 0;
            
            // Calculate success rate
            const total = (data.success || 0) + (data.fail || 0);
            const rate = total > 0 ? Math.round((data.success / total) * 100) : 0;
            document.getElementById('successRate').textContent = rate + '%';
          })
          .catch(e => console.error('Status fetch failed:', e));
      }
      
      function updateOptions() {
        fetch('/plugins/parasite-ai/options')
          .then(r => r.json())
          .then(data => {
            console.log('Options data:', data);
            if (data.error) {
              console.error('Options API error:', data.error);
              return;
            }
            document.getElementById('minRssi').textContent = data.min_rssi || '-80';
            document.getElementById('minClients').textContent = data.min_clients || '0';
            document.getElementById('maxFails').textContent = data.max_consecutive_fails || '3';
            document.getElementById('saveInterval').textContent = data.save_interval || '10';
            document.getElementById('debugLogs').textContent = data.enable_debug_logs ? 'ON' : 'OFF';
          })
          .catch(e => console.error('Options fetch failed:', e));
      }
      
      function updateLogs() {
        fetch('/plugins/parasite-ai/logs')
          .then(r => r.json())
          .then(data => {
            console.log('Logs data:', data);
            const logViewer = document.getElementById('logViewer');
            if (data.error) {
              console.error('Logs API error:', data.error);
              logViewer.innerHTML = '<div style="color: #f48771;">Error: ' + data.error + '</div>';
              return;
            }
            if (!data.logs || data.logs.length === 0) {
              logViewer.innerHTML = '<div style="color: #888;">No logs available</div>';
              return;
            }
            
            let html = '';
            data.logs.forEach(log => {
              let levelColor = '#d4d4d4';
              if (log.level === 'ERROR') levelColor = '#f48771';
              else if (log.level === 'WARNING') levelColor = '#dcdcaa';
              else if (log.level === 'INFO') levelColor = '#4fc1ff';
              else if (log.level === 'DEBUG') levelColor = '#888';
              
              html += '<div class="log-entry">' +
                '<span class="log-timestamp">' + log.timestamp + '</span>' +
                '<span class="log-level" style="color: ' + levelColor + ';">[' + log.level + ']</span>' +
                '<span>' + log.message + '</span>' +
                '</div>';
            });
            logViewer.innerHTML = html;
            
            // Auto-scroll to bottom
            logViewer.scrollTop = logViewer.scrollHeight;
          })
          .catch(e => console.error('Logs fetch failed:', e));
      }
      
      function changeAggression(level) {
        console.log('Aggression change requested:', level);
        // Note: This would require a webhook endpoint to actually change aggression
        // For now just notify user
        alert('Aggression control not yet implemented. Edit config.toml to set aggression level.');
      }
      
      // Initial load
      console.log('Dashboard loaded, starting data refresh');
      updateStatus();
      updateOptions();
      updateLogs();
      
      // Auto-refresh every 2 seconds
      setInterval(updateStatus, 2000);
      setInterval(updateOptions, 5000);
      setInterval(updateLogs, 3000);
    </script>
  </body>
</html>
"""


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
            # Normalize path - remove leading/trailing slashes and handle None
            normalized_path = (path or "").strip("/").lower()

            if not normalized_path or normalized_path == "":
                # Serve HTML dashboard
                return render_template_string(HTML_TEMPLATE)
            elif normalized_path == "logs":
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
            elif normalized_path == "status":
                return {
                    "state": self.state.value,
                    "mood": MOODS[self.current_aggression()],
                    "aggression": self.current_aggression(),
                    "success": self.memory["success"],
                    "fail": self.memory.get("fail", 0),
                    "consecutive_fails": self.consecutive_fails,
                }
            elif normalized_path == "options":
                # Return current plugin options
                return {
                    "min_rssi": self.min_rssi,
                    "min_clients": self.min_clients,
                    "max_consecutive_fails": self.max_consecutive_fails,
                    "save_interval": self.save_interval,
                    "enable_debug_logs": self.enable_debug_logs,
                }
            else:
                return {"error": f"Unknown path: {path}"}
        except Exception as e:
            self._log("ERROR", f"Webhook error: {e}")
            return {"error": str(e)}

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
        """Append log entry to JSON file - only log WARNING and ERROR to reduce I/O"""
        # Skip logging INFO and DEBUG to reduce file I/O
        if level not in ["ERROR", "WARNING"]:
            return

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

                # Keep only last 50 logs to prevent file bloat
                if len(logs) > 50:
                    logs = logs[-50:]

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
