"""
Bluetooth Tether Helper Plugin for Pwnagotchi

Required System Packages:
    sudo apt-get update
    sudo apt-get install -y bluez network-manager python3-dbus python3-toml

Features:
- Bluetooth tethering to mobile phones (iOS & Android)
- Auto-discovery of trusted devices with tethering capability
- Works with iOS randomized MAC addresses
- Auto-reconnect functionality
- Web UI for easy device pairing and management
- No manual MAC configuration needed

Setup:
1. Install packages: sudo apt-get install -y bluez network-manager python3-dbus python3-toml
2. Enable services:
   sudo systemctl enable bluetooth && sudo systemctl start bluetooth
   sudo systemctl enable NetworkManager && sudo systemctl start NetworkManager
3. Access web UI at http://<pwnagotchi-ip>:8080/plugins/bt-tether-helper
4. Scan and pair your phone - it will auto-connect from then on!

Configuration options (TOML format in /etc/pwnagotchi/config.toml):
[main.plugins.bt-tether-helper]
enabled = true
auto_reconnect = true         # Auto reconnect on disconnect (default: true)
show_on_screen = true         # Master switch: Show status on display
show_mini_status = true       # Show mini status indicator (single letter)
mini_status_position = [110, 0]  # Position for mini status [x, y]
show_detailed_status = true   # Show detailed status line with IP
detailed_status_position = [0, 82]  # Position for detailed status line
discord_webhook_url = ""      # Discord webhook for IP notifications (optional)
"""

import subprocess
import threading
import time
import logging
import os
import re
import traceback
import datetime
import json
from pwnagotchi.plugins import Plugin
from flask import render_template_string, request, jsonify
import pwnagotchi.ui.fonts as fonts
from pwnagotchi.ui.components import LabeledValue
from pwnagotchi.ui.view import BLACK

try:
    import urllib.request
    import urllib.error

    URLLIB_AVAILABLE = True
except ImportError:
    URLLIB_AVAILABLE = False
    logging.warning("[bt-tether-helper] urllib not available, Discord webhook disabled")

try:
    import dbus
    import dbus.service

    DBUS_AVAILABLE = True
except ImportError:
    DBUS_AVAILABLE = False
    logging.warning(
        "[bt-tether-helper] dbus/GLib not available, BLE advertising disabled"
    )


HTML_TEMPLATE = """<!DOCTYPE html>
<html>
  <head>
    <title>Bluetooth Tether</title>
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Cpath fill='%2358a6ff' d='M50 10 L70 25 L70 45 L50 60 L50 90 L30 75 L30 55 L50 40 L50 10 M50 40 L50 60'/%3E%3C/svg%3E" />
    <style>
      body { font-family: sans-serif; padding: 20px; max-width: 600px; margin: 0 auto; background: #0d1117; color: #d4d4d4; }
      .card { background: #161b22; padding: 20px; border-radius: 8px; margin-bottom: 16px; box-shadow: 0 2px 4px rgba(0,0,0,0.3); border: 1px solid #30363d; }
      h2 { margin: 0 0 20px 0; color: #58a6ff; }
      h3 { color: #d4d4d4; }
      h4 { color: #8b949e; }
      input { padding: 10px; font-size: 14px; border: 1px solid #30363d; border-radius: 4px; text-transform: uppercase; background: #0d1117; color: #d4d4d4; }
      input:focus { outline: none; border-color: #58a6ff; background: #161b22; }
      button { padding: 10px 20px; background: transparent; color: #d4d4d4; border: 1px solid #484f58; cursor: pointer; font-size: 14px; border-radius: 4px; margin-right: 8px; min-height: 42px; display: inline-flex; align-items: center; justify-content: center; }
      button:hover { background: rgba(139, 148, 158, 0.1); border-color: #8b949e; }
      button.danger { color: #d4d4d4; border-color: #484f58; background: transparent; }
      button.danger:hover { background: rgba(139, 148, 158, 0.1); border-color: #8b949e; }
      button.success { color: #d4d4d4; border-color: #484f58; background: transparent; }
      button.success:hover { background: rgba(139, 148, 158, 0.1); border-color: #8b949e; }
      button:disabled { background: transparent; color: #8b949e; cursor: not-allowed; border-color: #30363d; }
      .status-item { padding: 8px; margin: 4px 0; border-radius: 4px; background: #161b22; border: 1px solid #30363d; color: #d4d4d4; }
      .status-good { background: rgba(46, 160, 67, 0.15); color: #3fb950; border-color: #3fb950; }
      .status-bad { background: rgba(248, 81, 73, 0.15); color: #f85149; border-color: #f85149; }
      .device-item { padding: 8px; margin: 4px 0; border: 1px solid #30363d; border-radius: 4px; cursor: pointer; display: flex; justify-content: space-between; align-items: center; background: #0d1117; color: #d4d4d4; }
      .device-item:hover { background: #161b22; border-color: #58a6ff; }
      .message-box { padding: 12px; border-radius: 4px; margin: 12px 0; border-left: 4px solid; }
      .message-info { background: rgba(88, 166, 255, 0.1); color: #79c0ff; border-color: #79c0ff; }
      .message-success { background: rgba(63, 185, 80, 0.1); color: #3fb950; border-color: #3fb950; }
      .message-warning { background: rgba(214, 159, 0, 0.1); color: #d29922; border-color: #d29922; }
      .message-error { background: rgba(248, 81, 73, 0.1); color: #f85149; border-color: #f85149; }
      .spinner { display: inline-block; width: 14px; height: 14px; border: 2px solid #30363d; 
                 border-top: 2px solid #58a6ff; border-radius: 50%; animation: spin 1s linear infinite; margin-right: 8px; vertical-align: middle; }
      @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
      .mac-editor { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
      .mac-editor input { flex: 1; min-width: 200px; }
      .mac-editor button { white-space: nowrap; }
      .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; padding-bottom: 12px; border-bottom: 1px solid #30363d; }
      .header h2 { margin: 0; flex-grow: 1; }
      .header-nav { display: flex; gap: 8px; }
      .header-nav a { color: #58a6ff; text-decoration: none; padding: 8px 12px; border: 1px solid #30363d; border-radius: 4px; display: inline-flex; align-items: center; gap: 6px; transition: all 0.2s; font-size: 14px; }
      .header-nav a:hover { background: rgba(88, 166, 255, 0.1); border-color: #58a6ff; }
      @media (max-width: 600px) {
        .mac-editor { flex-direction: column; align-items: stretch; }
        .mac-editor input { width: 100%; }
        .mac-editor button { width: 100%; margin: 0 !important; }
      }
    </style>
  </head>
  <body>
    <div class="header">
      <h2>🔷 Bluetooth Tether</h2>
      <div class="header-nav">
        <a href="/plugins">Plugins</a>
      </div>
    </div>
    
    <!-- Phone Connection & Status -->
    <div class="card" id="phoneConnectionCard">
      <h3 style="margin: 0 0 12px 0;">📱 Connection Status</h3>
      
      <!-- Network Routes & Metrics -->
      <div id="networkMetricsInfo" style="background: #0d1117; color: #d4d4d4; padding: 12px; border-radius: 4px; margin-bottom: 16px; font-family: 'Courier New', monospace; font-size: 12px; line-height: 1.5;">
        <div style="color: #888; margin-bottom: 8px;">📊 Network Routes (sorted by priority):</div>
        <div id="networkMetricsContent" style="font-size: 13px;">
          <div style="color: #888;">Fetching metrics...</div>
        </div>
      </div>
      
      <!-- Hidden input for JavaScript to access MAC value -->
      <input type="hidden" id="macInput" value="{{ mac }}" />
      
      <!-- Trusted Devices Section (now includes status info) -->
      <div id="trustedDevicesSection" style="display: none;">
        <h4 style="margin: 0 0 8px 0;">Trusted Devices</h4>
        
        <!-- Combined Status Section - shown inside trustedDevicesSection -->
        <div id="combinedStatus" style="background: #0d1117; color: #d4d4d4; padding: 8px; margin-bottom: 8px; border-radius: 4px; font-family: 'Courier New', monospace; font-size: 12px; line-height: 1.4;">
          <div id="statusDevice" style="display: none; margin: 2px 0;">Device: <span></span></div>
          <div id="statusPaired" style="margin: 2px 0;">Paired: <span>Checking...</span></div>
          <div id="statusTrusted" style="margin: 2px 0;">Trusted: <span>Checking...</span></div>
          <div id="statusConnected" style="margin: 2px 0;">Connected: <span>Checking...</span></div>
          <div id="statusInternet" style="margin: 2px 0;">Internet: <span>Checking...</span></div>
          <div id="statusIP" style="display: none; margin: 2px 0;">IP Address: <span></span></div>
        </div>
        
        <!-- Device List -->
        <div id="trustedDevicesList" style="margin-bottom: 8px;"></div>
        
        <!-- Scan Button (always shown in trusted devices area) -->
        <button class="success" onclick="scanDevices()" id="scanBtn" style="width: 100%; margin: 0 0 8px 0;">
          Scan for Devices
        </button>
        
        <!-- Discovered Devices List -->
        <div id="scanResults" style="display: none; margin-bottom: 8px;">
          <h5 style="margin: 0 0 6px 0; color: #8b949e; font-size: 12px;">Discovered:</h5>
          <div id="scanStatus" style="color: #8b949e; margin: 4px 0; font-size: 12px;">Scanning...</div>
          <div id="deviceList"></div>
        </div>
      </div>
      
      <!-- Output Section (shown above connect button) -->
      <div style="margin-bottom: 12px; margin-top: 16px; padding-top: 16px; border-top: 1px solid #30363d;">
        <h4 style="margin: 0 0 8px 0; color: #8b949e; font-size: 14px;">📋 Output</h4>
        <div id="logViewer">
          <div style="background: #0d1117; color: #d4d4d4; padding: 12px; padding-right: 16px; border-radius: 4px; font-family: 'Courier New', monospace; font-size: 12px; max-height: 300px; overflow-y: auto; line-height: 1.5;" id="logContent">
            <div style="color: #888;">Fetching logs...</div>
          </div>
        </div>
        <style>
          #logContent::-webkit-scrollbar {
            width: 5px;
          }
          #logContent::-webkit-scrollbar-track {
            background: #0d1117;
            border-radius: 4px;
          }
          #logContent::-webkit-scrollbar-thumb {
            background: #30363d;
            border-radius: 4px;
          }
          #logContent::-webkit-scrollbar-thumb:hover {
            background: #484f58;
          }
        </style>
      </div>
    </div>
    
    <!-- Test Internet Connectivity -->
    <div class="card" id="testInternetCard" style="display: none;">
      <h3 style="margin: 0 0 12px 0;">Test Internet Connectivity</h3>
      <button onclick="testInternet()" id="testInternetBtn" style="width: 100%; margin: 0 0 12px 0;">
        Test Internet Connectivity
      </button>
      
      <!-- Test Results -->
      <div id="testResults" style="display: none;">
        <div id="testResultsMessage" class="message-box message-info"></div>
      </div>
    </div>
    
    <script>
      const macInput = document.getElementById("macInput");
      let statusInterval = null;
      let isDisconnecting = false;
      let logInterval = null;
      let lastMetricsState = null;
      let switchingDeviceMac = null;
      let lastConnectionInProgress = false;
      let lastDataConnected = false;

      loadTrustedDevicesSummary();
      loadNetworkMetrics();
      
      setInitializingStatus();
      setTimeout(checkConnectionStatus, 1000);
      
      refreshLogs();
      startLogPolling();
      function setInitializingStatus() {
        document.getElementById("statusPaired").innerHTML = 
          `Paired: <span style="color: #8b949e;">Initializing...</span>`;
        
        document.getElementById("statusTrusted").innerHTML = 
          `Trusted: <span style="color: #8b949e;">Initializing...</span>`;
        
        document.getElementById("statusConnected").innerHTML = 
          `Connected: <span style="color: #8b949e;">Initializing...</span>`;
        
        document.getElementById("statusInternet").innerHTML = 
          `Internet: <span style="color: #8b949e;">Initializing...</span>`;
        
        document.getElementById('statusIP').style.display = 'none';
      }

      async function checkConnectionStatus() {
        const mac = macInput.value.trim();
        if (!/^([0-9A-F]{2}:){5}[0-9A-F]{2}$/i.test(mac)) {
          try {
            const statusResponse = await fetch(`/plugins/bt-tether-helper/status`);
            const statusData = await statusResponse.json();
            
            if (statusData.mac && /^([0-9A-F]{2}:){5}[0-9A-F]{2}$/i.test(statusData.mac)) {
              const response = await fetch(`/plugins/bt-tether-helper/connection-status?mac=${encodeURIComponent(statusData.mac)}`);
              const data = await response.json();
              
              macInput.value = statusData.mac;
              updateStatusDisplay(statusData, data);
              return;
            }
          } catch (err) {
            console.error('Failed to get backend status:', err);
          }
          
          document.getElementById("statusPaired").innerHTML = 
            `Paired: <span style="color: #f48771;">No</span>`;
          
          document.getElementById("statusTrusted").innerHTML = 
            `Trusted: <span style="color: #f48771;">No</span>`;
          
          document.getElementById("statusConnected").innerHTML = 
            `Connected: <span style="color: #f48771;">No</span>`;
          
          document.getElementById("statusInternet").innerHTML = 
            `Internet: <span style="color: #f48771;">Not Active</span>`;
          
          document.getElementById('statusIP').style.display = 'none';
          
          return;
        }
        
        try {
          const statusResponse = await fetch(`/plugins/bt-tether-helper/status`);
          const statusData = await statusResponse.json();
          
          const response = await fetch(`/plugins/bt-tether-helper/connection-status?mac=${encodeURIComponent(mac)}`);
          const data = await response.json();
          
          updateStatusDisplay(statusData, data);
          
        } catch (error) {
          console.error('Status check failed:', error);
        }
      }
      
      function updateStatusDisplay(statusData, data) {
        // Detect connection failure: connection_in_progress was true but now false, and not connected
        if (lastConnectionInProgress && !statusData.connection_in_progress && !data.connected && switchingDeviceMac) {
          console.warn(`Connection failed for ${switchingDeviceMac}`);
          showFeedback("Connection failed. Please ensure Bluetooth tethering is enabled on your phone.", "error");
          switchingDeviceMac = null;
          // Cancel any pending switch timeout
          if (window.switchTimeoutId) {
            clearTimeout(window.switchTimeoutId);
            window.switchTimeoutId = null;
          }
          // Re-enable buttons
          const allButtons = document.querySelectorAll('.device-item button');
          allButtons.forEach(btn => btn.disabled = false);
          loadTrustedDevicesSummary();
        }
        
        // Track connection progress state
        lastConnectionInProgress = statusData.connection_in_progress;
        
        // Skip metrics updates during network transitions to avoid querying unstable routing table
        const isTransitioning = statusData.connection_in_progress || statusData.disconnecting || statusData.untrusting || statusData.switching_in_progress || statusData.initializing;
        
        if (!isTransitioning) {
          const currentMetricsState = `${data.connected}-${data.pan_active}-${data.interface}`;
          if (currentMetricsState !== lastMetricsState) {
            lastMetricsState = currentMetricsState;
            loadNetworkMetrics();
          }
        }
        
        // If disconnecting or untrusting, show transitional state immediately
        if (statusData.disconnecting || isDisconnecting) {
          document.getElementById("statusPaired").innerHTML = 
            `Paired: <span style="color: #f0883e;">Disconnecting...</span>`;
          
          document.getElementById("statusTrusted").innerHTML = 
            `Trusted: <span style="color: #f0883e;">Disconnecting...</span>`;
          
          document.getElementById("statusConnected").innerHTML = 
            `Connected: <span style="color: #f0883e;">Disconnecting...</span>`;
          
          document.getElementById("statusInternet").innerHTML = 
            `Internet: <span style="color: #f0883e;">Disconnecting...</span>`;
          
          document.getElementById('statusIP').style.display = 'none';
          
          // Hide test card during disconnect
          const testInternetCard = document.getElementById('testInternetCard');
          testInternetCard.style.display = 'none';
          
          return;  // Don't process further updates during disconnect
        }
        
        let screenStatus = 'D';
        if (data.pan_active) {
          screenStatus = 'C';
        } else if (data.connected) {
          screenStatus = 'N';
        } else if (data.paired) {
          screenStatus = 'P';
        }
        
        // Show device name in combined status
        const statusDeviceElement = document.getElementById('statusDevice');
        if (statusData.last_connected_name) {
          statusDeviceElement.style.display = 'block';
          statusDeviceElement.innerHTML = `Device: <span style="color: #58a6ff;">${statusData.last_connected_name}</span>`;
        } else {
          statusDeviceElement.style.display = 'none';
        }
        
        document.getElementById("statusPaired").innerHTML = 
          `Paired: <span style="color: ${data.paired ? '#4ec9b0' : '#f48771'};">${data.paired ? 'Yes' : 'No'}</span>`;
        
        document.getElementById("statusTrusted").innerHTML = 
          `Trusted: <span style="color: ${data.trusted ? '#4ec9b0' : '#f48771'};">${data.trusted ? 'Yes' : 'No'}</span>`;
        
        document.getElementById("statusConnected").innerHTML = 
          `Connected: <span style="color: ${data.connected ? '#4ec9b0' : '#f48771'};">${data.connected ? 'Yes' : 'No'}</span>`;
        
        document.getElementById("statusInternet").innerHTML = 
          `Internet: <span style="color: ${data.pan_active ? '#4ec9b0' : '#f48771'};">${data.pan_active ? 'Active' : 'Not Active'}</span>${data.interface ? ` <span style="color: #888;">(${data.interface})</span>` : ''}`;
        
        const testInternetCard = document.getElementById('testInternetCard');
        if (data.pan_active && !isDisconnecting) {
          testInternetCard.style.display = 'block';
        } else {
          testInternetCard.style.display = 'none';
        }
        
        const statusIPElement = document.getElementById('statusIP');
        if (data.ip_address && data.pan_active) {
          statusIPElement.style.display = 'block';
          statusIPElement.innerHTML = `IP Address: <span style="color: #4ec9b0;">${data.ip_address}</span>`;
        } else {
          statusIPElement.style.display = 'none';
        }
        
        // Detect transition to connected state (works regardless of polling interval)
        if (data.connected && !lastDataConnected) {
          // Clear switching state since connection is now complete
          if (switchingDeviceMac) {
            switchingDeviceMac = null;
            if (window.switchTimeoutId) {
              clearTimeout(window.switchTimeoutId);
              window.switchTimeoutId = null;
            }
            const allButtons = document.querySelectorAll('.device-item button');
            allButtons.forEach(btn => btn.disabled = false);
          }
          loadTrustedDevicesSummary();
          // Refresh routes after a short delay to let routing table stabilise
          setTimeout(loadNetworkMetrics, 2000);
          // Transition to slow polling after 10 seconds
          setTimeout(() => {
            if (statusInterval && statusInterval._interval === 2000) {
              console.log('Switching to slow polling (10s)');
              stopStatusPolling();
              statusInterval = setInterval(checkConnectionStatus, 10000);
              statusInterval._interval = 10000;
            }
          }, 10000);
        }
        lastDataConnected = data.connected;

        // Manage polling based on connection state
        if (statusData.status === 'PAIRING' || statusData.status === 'TRUSTING' || statusData.status === 'CONNECTING' || statusData.status === 'RECONNECTING' || statusData.connection_in_progress) {
          // Actively connecting - poll faster (every 2 seconds)
          if (!statusInterval || statusInterval._interval !== 2000) {
            console.log('Connection in progress - fast polling (2s)');
            stopStatusPolling();
            statusInterval = setInterval(checkConnectionStatus, 2000);
            statusInterval._interval = 2000;
          }
        } else if (data.connected) {
          // Connected - ensure we're on fast polling initially
          if (!statusInterval || statusInterval._interval !== 2000) {
            console.log('Connected - fast polling (2s) for initial update');
            stopStatusPolling();
            statusInterval = setInterval(checkConnectionStatus, 2000);
            statusInterval._interval = 2000;
          }
        } else if (data.paired) {
          // Paired but not connected - poll every 10 seconds
          if (!statusInterval || statusInterval._interval !== 10000) {
            console.log('Paired - slow polling (10s)');
            stopStatusPolling();
            statusInterval = setInterval(checkConnectionStatus, 10000);
            statusInterval._interval = 10000;
          }
        } else {
          // Disconnected and not paired - poll very slowly (every 30 seconds) to catch new devices
          if (!statusInterval || statusInterval._interval !== 30000) {
            console.log('Disconnected - slow polling (30s)');
            stopStatusPolling();
            statusInterval = setInterval(checkConnectionStatus, 30000);
            statusInterval._interval = 30000;
          }
        }

        
        if (!window.lastStatusUpdate || 
            (window.lastStatusUpdate.connected !== (statusData.mac && data.connected)) ||
            (window.lastStatusUpdate.scanning !== statusData.scanning)) {
          loadTrustedDevicesSummary();
          window.lastStatusUpdate = {
            connected: statusData.mac && data.connected,
            scanning: statusData.scanning
          };
        }
      }

      function startStatusPolling() {
        if (statusInterval) clearInterval(statusInterval);
        statusInterval = setInterval(checkConnectionStatus, 2000);
      }

      function stopStatusPolling() {
        if (statusInterval) {
          clearInterval(statusInterval);
          statusInterval = null;
        }
      }
      async function scanDevices() {
        const scanBtn = document.getElementById('scanBtn');
        const scanResults = document.getElementById('scanResults');
        const scanStatus = document.getElementById('scanStatus');
        const deviceList = document.getElementById('deviceList');
        
        const statusResponse = await fetch(`/plugins/bt-tether-helper/status`);
        const statusData = await statusResponse.json();
        
        const isConnecting = statusData.initializing || 
                             statusData.disconnecting ||
                             statusData.untrusting ||
                             statusData.connection_in_progress ||
                             statusData.status === 'PAIRING' || 
                             statusData.status === 'CONNECTING' || 
                             statusData.status === 'RECONNECTING';
        
        if (isConnecting) {
          showFeedback("Cannot scan while connecting. Please wait for current operation to complete.", "warning");
          return;
        }
        
        scanBtn.disabled = true;
        scanBtn.innerHTML = '<span class="spinner"></span> Scanning...';
        scanResults.style.display = 'block';
        deviceList.innerHTML = '';
        scanStatus.innerHTML = '<span class="spinner"></span> Scanning for devices...';
        
        showFeedback("Scanning for devices... Keep phone Bluetooth settings open!", "info");
        
        try {
          const response = await fetch('/plugins/bt-tether-helper/scan', { method: 'GET' });
          let data = await response.json();
          
          // Start polling for scan progress every 2 seconds
          let pollCount = 0;
          const maxPolls = 16;
          let lastDeviceCount = 0;
          let scanProgressInterval = setInterval(async () => {
            pollCount++;
            
            try {
              const progressResponse = await fetch('/plugins/bt-tether-helper/scan-progress');
              const progressData = await progressResponse.json();
              
              if (progressData.devices && progressData.devices.length > lastDeviceCount) {
                lastDeviceCount = progressData.devices.length;
                deviceList.innerHTML = '';
                progressData.devices.forEach(device => {
                  const div = document.createElement('div');
                  div.className = 'device-item';
                  div.innerHTML = `
                    <div style="flex: 1; font-family: 'Courier New', monospace; font-size: 12px;">
                      <b>${device.name}</b><br>
                      <small style="color: #888;">${device.mac}</small>
                    </div>
                    <button onclick="pairAndConnectDevice('${device.mac}', '${device.name.replace(/'/g, "\\'")}'); return false;" class="success" style="margin: 0; padding: 6px 12px; font-size: 12px;">Pair</button>
                  `;
                  deviceList.appendChild(div);
                });
                scanStatus.innerHTML = `<span class="spinner"></span> Found ${progressData.devices.length} device(s)... still scanning`;
              }
              
              if (!progressData.scanning) {
                clearInterval(scanProgressInterval);
                
                if (progressData.devices && progressData.devices.length > 0) {
                  scanStatus.textContent = `Scan complete - Found ${progressData.devices.length} device(s):`;
                  showFeedback(`Found ${progressData.devices.length} device(s). Click Pair to connect!`, "success");
                } else {
                  scanStatus.textContent = 'Scan complete - No devices found';
                  deviceList.innerHTML = '';
                  showFeedback("No devices found. Make sure phone Bluetooth is ON and visible.", "warning");
                }
                
                scanBtn.disabled = false;
                scanBtn.innerHTML = 'Scan for Devices';
              } else if (pollCount >= maxPolls) {
                clearInterval(scanProgressInterval);
                scanStatus.textContent = 'Scan complete';
                scanBtn.disabled = false;
                scanBtn.innerHTML = 'Scan for Devices';
              }
            } catch (e) {
              console.log('Scan progress poll error:', e);
            }
          }, 2000);
          
        } catch (error) {
          scanStatus.textContent = 'Scan failed';
          showFeedback("Scan failed: " + error.message, "error");
          scanBtn.disabled = false;
          scanBtn.innerHTML = 'Scan for Devices';
        }
      }

      async function loadTrustedDevicesSummary() {
        try {
          const statusResponse = await fetch('/plugins/bt-tether-helper/status');
          const statusData = await statusResponse.json();
          
          const summaryDiv = document.getElementById('trustedDevicesSummary');
          const trustedDevicesSection = document.getElementById('trustedDevicesSection');
          const trustedDevicesList = document.getElementById('trustedDevicesList');
          const statusConnectedDiv = document.getElementById('statusConnected');
          const scanBtn = document.getElementById('scanBtn');
          
          const isConnecting = statusData.initializing ||  
                               statusData.disconnecting ||
                               statusData.untrusting ||
                               statusData.switching_in_progress ||
                               statusData.connection_in_progress ||
                               statusData.status === 'PAIRING' || 
                               statusData.status === 'CONNECTING' || 
                               statusData.status === 'RECONNECTING';
          
          // Disable scan button while connecting
          if (scanBtn) {
            scanBtn.disabled = isConnecting;
          }
          
          if (statusData.initializing) {
            if (summaryDiv) {
              summaryDiv.innerHTML = '<span style="color: #8b949e;">🔄 Initializing Bluetooth...</span>';
            }
            if (trustedDevicesSection) {
              trustedDevicesSection.style.display = 'none';
            }
            // Poll again in 2 seconds to detect when initialization completes
            setTimeout(loadTrustedDevicesSummary, 2000);
            return;
          }
          
          if (statusData.disconnecting) {
            if (summaryDiv) {
              summaryDiv.innerHTML = '<span style="color: #f85149;">Disconnecting...</span>';
            }
            if (trustedDevicesSection) {
              trustedDevicesSection.style.display = 'none';
            }
            return;
          }
          
          if (statusData.untrusting) {
            if (summaryDiv) {
              summaryDiv.innerHTML = '<span style="color: #f85149;">🔓 Removing trust...</span>';
            }
            if (trustedDevicesSection) {
              trustedDevicesSection.style.display = 'none';
            }
            return;
          }
          
          if (statusData.switching_in_progress) {
            if (summaryDiv) {
              summaryDiv.innerHTML = '<span style="color: #58a6ff;">🔄 Switching device...</span>';
            }
            // Don't hide the device list - keep showing it with the spinner on the target device
            // Poll again to detect when switch completes
            setTimeout(loadTrustedDevicesSummary, 2000);
          }

          // Keep polling while any connection is in progress so the loader
          // on the target device stays visible and clears when done.
          if (isConnecting && !statusData.switching_in_progress && !statusData.initializing) {
            setTimeout(loadTrustedDevicesSummary, 2000);
          }
          
          const response = await fetch('/plugins/bt-tether-helper/trusted-devices');
          const data = await response.json();
          
          if (data.devices && data.devices.length > 0) {
            const napDevices = data.devices.filter(d => d.has_nap);
            const connectedDevice = napDevices.find(d => d.connected);
            const buttonsDisabled = isConnecting ? 'disabled' : '';

            // Determine which device is being actively connected.
            // switchingDeviceMac is set by explicit UI actions (Connect / Pair).
            // If not set but a connection is in progress, use the server-side
            // phone_mac so auto-reconnects and backend-initiated connects
            // also show the loader on the correct device list item.
            const connectingMac = switchingDeviceMac
              || (isConnecting && statusData.mac ? statusData.mac.toUpperCase() : null);
            
            if (trustedDevicesSection) {
              trustedDevicesSection.style.display = 'block';
            }
            if (trustedDevicesList) {
              trustedDevicesList.innerHTML = '';
            }
            
            napDevices.forEach(device => {
              const div = document.createElement('div');
              div.className = 'device-item';
              div.style.display = 'flex';
              div.style.justifyContent = 'space-between';
              div.style.alignItems = 'center';
              div.style.marginBottom = '8px';
              
              const isDeviceConnecting = connectingMac && connectingMac.toUpperCase() === device.mac.toUpperCase();
              
              if (isDeviceConnecting) {
                div.style.background = 'rgba(88, 166, 255, 0.08)';
                div.style.borderLeft = '3px solid #58a6ff';
                div.style.borderColor = '#58a6ff';
              } else if (device.connected) {
                div.style.background = 'rgba(88, 166, 255, 0.1)';
                div.style.borderLeft = '3px solid #58a6ff';
              }
              
              let connectionDetails = '';
              if (device.connected) {
                const ipInfo = device.ip_address ? `${device.ip_address}` : '';
                const ifaceInfo = device.interface ? `${device.interface}` : '';
                const separator = ipInfo && ifaceInfo ? ' • ' : '';
                connectionDetails = `<small style="color: #3fb950; margin-left: 8px;">${ifaceInfo}${separator}${ipInfo}</small>`;
              }
              
              // Check if this device is currently being connected/switched
              let buttonContent = '';
              if (isDeviceConnecting) {
                // Show connecting state for the device being connected
                buttonContent = `<span style="color: #58a6ff; font-size: 12px;">Connecting...</span>`;
              } else {
                // Normal button content
                buttonContent = !device.connected ? `<button onclick="switchToDevice('${device.mac}', '${device.name.replace(/'/g, "\\'")}'); return false;" class="success" style="margin: 0; padding: 6px 12px; font-size: 12px;" ${buttonsDisabled}>Connect</button>` : '';
              }
              
              div.innerHTML = `
                <div style="flex: 1; font-family: 'Courier New', monospace; font-size: 12px;">
                  <b>${device.name}</b><br>
                  <small style="color: #888;">${device.mac} ${connectionDetails}</small>
                </div>
                <div style="display: flex; gap: 6px; margin-left: 12px;">
                  ${buttonContent}
                  ${isDeviceConnecting ? '' : `<button onclick="untrustDevice('${device.mac}', '${device.name.replace(/'/g, "\\'")}'); return false;" class="danger" style="margin: 0; padding: 6px 12px; font-size: 12px;" ${buttonsDisabled}>Forget</button>`}
                </div>
              `;
              if (trustedDevicesList) {
                trustedDevicesList.appendChild(div);
              }
            });
            
          } else {
            if (trustedDevicesSection) {
              trustedDevicesSection.style.display = 'block';
            }
            if (trustedDevicesList) {
              trustedDevicesList.innerHTML = '';
            }
            if (isConnecting && statusData.status !== 'CONNECTED') {
              if (summaryDiv) {
                summaryDiv.innerHTML = '<span style="color: #8b949e;">Connecting...</span>';
              }
            } else {
              if (summaryDiv) {
                summaryDiv.innerHTML = '<span style="color: #8b949e;">No paired devices - scan to pair a device</span>';
              }
            }
          }
        } catch (error) {
          const summaryDiv = document.getElementById('trustedDevicesSummary');
          if (summaryDiv) {
            summaryDiv.innerHTML = '<span style="color: #f85149;">Error loading devices</span>';
          }
        }
      }

      async function loadNetworkMetrics() {
        try {
          const response = await fetch('/plugins/bt-tether-helper/network-metrics');
          const data = await response.json();
          
          const metricsDiv = document.getElementById('networkMetricsContent');
          
          if (data.success && data.routes && data.routes.length > 0) {
            let html = '';
            
            data.routes.forEach((route, idx) => {
              const priority = route.is_primary ? 'PRIMARY' : `BACKUP-${idx}`;
              const priorityColor = route.is_primary ? '#3fb950' : '#888';
              const isBT = route.interface === data.bluetooth_status.interface;
              const btIndicator = isBT ? ' 🔵' : '';
              
              html += `<div style="margin: 6px 0; padding: 6px; background: ${route.is_primary ? 'rgba(63, 185, 80, 0.1)' : 'rgba(48, 54, 61, 0.3)'}; border-left: 3px solid ${priorityColor}; border-radius: 3px;">`;
              html += `<div><span style="color: ${priorityColor}; font-weight: bold;">[${priority}]</span> ${route.interface}${btIndicator} <span style="color: #888;">(${route.type})</span></div>`;
              html += `<div style="color: #888; font-size: 11px; margin-top: 2px;">Metric: ${route.metric}, Gateway: ${route.gateway}</div>`;
              html += `</div>`;
            });
            
            // Add Bluetooth status if connected but not in routes
            if (data.bluetooth_status.connected && !data.routes.some(r => r.interface === data.bluetooth_status.interface)) {
              html += `<div style="margin: 6px 0; padding: 6px; background: rgba(88, 166, 255, 0.1); border-left: 3px solid #58a6ff; border-radius: 3px;">`;
              html += `<div><span style="color: #58a6ff; font-weight: bold;">[INFO]</span> 🔵 ${data.bluetooth_status.interface} <span style="color: #888;">(Bluetooth PAN)</span></div>`;
              html += `<div style="color: #888; font-size: 11px; margin-top: 2px;">Connected but no default route</div>`;
              html += `</div>`;
            }
            
            metricsDiv.innerHTML = html;
          } else if (data.success && data.routes.length === 0) {
            metricsDiv.innerHTML = '<div style="color: #888;">No default routes found</div>';
          } else {
            metricsDiv.innerHTML = '<div style="color: #f48771;">Failed to fetch metrics</div>';
          }
        } catch (error) {
          console.error('Failed to load network metrics:', error);
          document.getElementById('networkMetricsContent').innerHTML = '<div style="color: #f48771;">Error loading metrics</div>';
        }
      }

      async function pairAndConnectDevice(mac, name) {
        showFeedback(`Starting pairing with ${name}... Watch for pairing dialog!`, "info");

        // Track which device is being connected so the device list shows a loader
        switchingDeviceMac = mac;
        loadTrustedDevicesSummary();

        const scanResults = document.getElementById('scanResults');
        const deviceList = document.getElementById('deviceList');
        const scanStatus = document.getElementById('scanStatus');
        if (scanResults) {
          scanResults.style.display = 'none';
        }
        if (deviceList) {
          deviceList.innerHTML = '';
        }
        if (scanStatus) {
          scanStatus.innerHTML = '';
        }
        
        // Hide scan card immediately when pairing starts
        const scanCard = document.getElementById('scanCard');
        if (scanCard) {
          scanCard.style.display = 'none';
        }
        
        try {
          const response = await fetch(`/plugins/bt-tether-helper/pair-device?mac=${encodeURIComponent(mac)}&name=${encodeURIComponent(name)}`, { method: 'GET' });
          const data = await response.json();
          
          if (data.success) {
            showFeedback(`Pairing started with ${name}! Accept the dialog on your phone.`, "success");
            
            macInput.value = mac;
            
            const phoneConnectionCard = document.getElementById('phoneConnectionCard');
            if (phoneConnectionCard) {
              phoneConnectionCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }
            
            startStatusPolling();
            
            loadTrustedDevicesSummary();
            checkConnectionStatus();
            setTimeout(() => {
              checkConnectionStatus();
              loadTrustedDevicesSummary();
            }, 2000);
          } else {
            showFeedback(`Pairing failed: ${data.message}`, "error");
          }
        } catch (error) {
          showFeedback(`Pairing failed: ${error.message}`, "error");
        }
      }

      async function switchToDevice(mac, name, buttonElement) {
        if (!confirm(`Switch to ${name}?\n\nThis will disconnect the current device and connect to ${name}.`)) {
          return;
        }
        
        showFeedback(`Switching to ${name}...`, "info");
        
        // Track which device is being switched
        switchingDeviceMac = mac;
        // Reset metrics state so routes refresh after the switch completes
        lastMetricsState = null;
        
        // Immediately re-render device list to show spinner/loading state
        loadTrustedDevicesSummary();
        
        // Disable all device action buttons
        const allButtons = document.querySelectorAll('.device-item button');
        allButtons.forEach(btn => btn.disabled = true);
        
        // Set a timeout to clear the switching state if it takes too long
        const switchTimeoutId = setTimeout(() => {
          if (switchingDeviceMac === mac) {
            console.warn(`Switch operation to ${mac} timed out after 60s`);
            showFeedback(`Switch operation timed out. Please check your device settings.`, "warning");
            switchingDeviceMac = null;
            allButtons.forEach(btn => btn.disabled = false);
            loadTrustedDevicesSummary();
          }
        }, 60000);
        
        try {
          const response = await fetch(`/plugins/bt-tether-helper/switch-device?mac=${encodeURIComponent(mac)}`, { method: 'GET' });
          const data = await response.json();
          
          if (data.success) {
            showFeedback(`Switching to ${name}... This may take a moment.`, "success");
            
            macInput.value = mac;
            
            startStatusPolling();
            
            setTimeout(loadTrustedDevicesSummary, 2000);
            setTimeout(checkConnectionStatus, 1000);
            // Keep buttons disabled and timeout active - they'll be cleared when the operation completes
            // Store the timeout ID so we can cancel it on success
            window.switchTimeoutId = switchTimeoutId;
          } else {
            clearTimeout(switchTimeoutId);
            showFeedback(`Switch failed: ${data.message}`, "error");
            switchingDeviceMac = null;
            allButtons.forEach(btn => btn.disabled = false);
          }
        } catch (error) {
          clearTimeout(switchTimeoutId);
          showFeedback(`Switch failed: ${error.message}`, "error");
          switchingDeviceMac = null;
          allButtons.forEach(btn => btn.disabled = false);
        }
      }

      async function untrustDevice(mac, name) {
        if (!confirm(`Remove trust for ${name}?\n\nThis will disconnect and unpair the device. You'll need to scan and pair again to use it.`)) {
          return;
        }
        
        showFeedback(`Removing trust for ${name}...`, "info");
        
        // Track which device is being untrusted
        switchingDeviceMac = mac;
        
        // Disable all device action buttons
        const allButtons = document.querySelectorAll('.device-item button');
        allButtons.forEach(btn => btn.disabled = true);
        
        try {
          const response = await fetch(`/plugins/bt-tether-helper/untrust?mac=${encodeURIComponent(mac)}`, { method: 'GET' });
          const data = await response.json();
          
          if (data.success) {
            showFeedback(`${name} has been untrusted and removed.`, "success");
            
            if (macInput.value.toUpperCase() === mac.toUpperCase()) {
              macInput.value = '';
            }
            
            switchingDeviceMac = null;
            setTimeout(loadTrustedDevicesSummary, 1000);
            setTimeout(checkConnectionStatus, 500);
            // Keep buttons disabled - they'll be re-enabled when the operation completes
          } else {
            showFeedback(`Untrust failed: ${data.message}`, "error");
            switchingDeviceMac = null;
            allButtons.forEach(btn => btn.disabled = false);
          }
        } catch (error) {
          showFeedback(`Untrust failed: ${error.message}`, "error");
          switchingDeviceMac = null;
          allButtons.forEach(btn => btn.disabled = false);
        }
      }

      async function testInternet() {
        const testBtn = document.getElementById('testInternetBtn');
        const testResults = document.getElementById('testResults');
        const testResultsMessage = document.getElementById('testResultsMessage');
        
        testBtn.disabled = true;
        testBtn.innerHTML = '<span class="spinner"></span> Testing...';
        testResults.style.display = 'block';
        testResultsMessage.className = 'message-box message-info';
        testResultsMessage.innerHTML = '<span class="spinner"></span> Running connectivity tests...';
        
        try {
          const response = await fetch('/plugins/bt-tether-helper/test-internet', { method: 'GET' });
          const data = await response.json();
          
          let resultHtml = '<div style="font-family: monospace; font-size: 13px; line-height: 1.6;">';
          
          // Ping test (IPv4 + IPv6)
          resultHtml += `<div style="margin-bottom: 8px;">`;
          resultHtml += `<b>📡 Ping Test:</b> `;
          if (data.ping_success && !data.ping6_success) {
            resultHtml += '<span style="color: #28a745;">✓ IPv4 Success</span>';
          } else if (!data.ping_success && data.ping6_success) {
            resultHtml += '<span style="color: #28a745;">✓ IPv6 only</span>';
          } else if (data.ping_success && data.ping6_success) {
            resultHtml += '<span style="color: #28a745;">✓ IPv4 + IPv6</span>';
          } else {
            resultHtml += '<span style="color: #dc3545;">✗ Failed</span>';
          }
          resultHtml += `</div>`;
          
          // DNS test
          resultHtml += `<div style="margin-bottom: 8px;">`;
          resultHtml += `<b>🔍 DNS Test (google.com):</b> `;
          resultHtml += data.dns_success ? '<span style="color: #28a745;">✓ Success</span>' : '<span style="color: #dc3545;">✗ Failed</span>';
          resultHtml += `</div>`;
          
          if (data.dns_servers) {
            resultHtml += `<div style="margin-bottom: 8px; padding-left: 20px; font-size: 12px;">`;
            resultHtml += `<span style="color: #666;">DNS Servers:</span> <span style="color: #0066cc;">${data.dns_servers}</span>`;
            resultHtml += `</div>`;
          }
          
          if (!data.dns_success && data.dns_error) {
            resultHtml += `<div style="margin-bottom: 8px; padding-left: 20px; font-size: 11px; background: #fff3cd; padding: 6px; border-radius: 3px;">`;
            resultHtml += `<span style="color: #856404;">Error: ${data.dns_error.substring(0, 150)}...</span>`;
            resultHtml += `</div>`;
          }
          
          resultHtml += `<div style="margin-bottom: 8px;">`;
          resultHtml += `<b>💻 Interface IPv4:</b> `;
          resultHtml += data.bnep0_ip ? `<span style="color: #28a745;">${data.bnep0_ip}</span>` : '<span style="color: #dc3545;">No IPv4 assigned</span>';
          resultHtml += `</div>`;
          
          resultHtml += `<div style="margin-bottom: 8px;">`;
          resultHtml += `<b>🌐 Interface IPv6:</b> `;
          resultHtml += data.bnep0_ipv6 ? `<span style="color: #28a745;">${data.bnep0_ipv6}</span>` : '<span style="color: #888;">No global IPv6</span>';
          resultHtml += `</div>`;
          
          resultHtml += `<div style="margin-bottom: 8px;">`;
          resultHtml += `<b>🚦 Default Route:</b> `;
          resultHtml += data.default_route ? `<span style="color: #0066cc;">${data.default_route}</span>` : '<span style="color: #dc3545;">None</span>';
          resultHtml += `</div>`;
          
          resultHtml += `<div style="margin-bottom: 8px;">`;
          resultHtml += `<b>🏠 Localhost Route:</b> `;
          if (data.localhost_routes) {
            const isLoopback = data.localhost_routes.includes('lo') || data.localhost_routes.includes('local');
            const routeColor = isLoopback ? '#28a745' : '#dc3545';
            const routeIcon = isLoopback ? '✓' : '⚠️';
            resultHtml += `<span style="color: ${routeColor};">${routeIcon} ${data.localhost_routes}</span>`;
            if (!isLoopback) {
              resultHtml += `<div style="margin-top: 4px; padding: 6px; background: #fff3cd; border-radius: 3px; font-size: 11px;">`;
              resultHtml += `<span style="color: #856404;">⚠️ WARNING: Localhost not routing through 'lo' interface! This may prevent bettercap API from working.</span>`;
              resultHtml += `</div>`;
            }
          } else {
            resultHtml += '<span style="color: #dc3545;">None</span>';
          }
          resultHtml += `</div>`;
          
          resultHtml += '</div>';
          
          if (data.ping_success && data.dns_success) {
            testResultsMessage.className = 'message-box message-success';
          } else if (data.ping_success || data.dns_success) {
            testResultsMessage.className = 'message-box message-warning';
          } else {
            testResultsMessage.className = 'message-box message-error';
          }
          
          testResultsMessage.innerHTML = resultHtml;
          
        } catch (error) {
          testResultsMessage.className = 'message-box message-error';
          testResultsMessage.textContent = 'Test failed: ' + error.message;
        } finally {
          testBtn.disabled = false;
          testBtn.innerHTML = 'Test Internet Connectivity';
        }
      }

      function showFeedback(message, type = "info") {
        // Just log to console since feedback element was removed
        console.log(`[${type.toUpperCase()}] ${message}`);
      }
      
      async function refreshLogs() {
        try {
          const response = await fetch('/plugins/bt-tether-helper/logs');
          const data = await response.json();
          const logContent = document.getElementById('logContent');
          
          // Check if user is scrolled to bottom before updating
          // Allow 50px tolerance for "near bottom"
          const isScrolledToBottom = logContent.scrollHeight - logContent.clientHeight <= logContent.scrollTop + 50;
          
          if (data.logs && data.logs.length > 0) {
            logContent.innerHTML = data.logs.map(log => {
              const timestamp = log.timestamp || '';
              const level = (log.level || 'INFO').toUpperCase();
              const message = log.message || '';
              
              let color = '#d4d4d4';
              if (level === 'ERROR') color = '#f48771';
              else if (level === 'WARNING') color = '#dcdcaa';
              else if (level === 'INFO') color = '#4fc1ff';
              else if (level === 'DEBUG') color = '#888';
              
              return `<div><span style=\"color: #888;\">${timestamp}</span> <span style=\"color: ${color}; font-weight: bold;\">[${level}]</span> ${message}</div>`;
            }).join('');
            
            // Only auto-scroll if user was already at the bottom
            if (isScrolledToBottom) {
              logContent.scrollTop = logContent.scrollHeight;
            }
          } else {
            logContent.innerHTML = '<div style=\"color: #888;\">No logs available</div>';
          }
        } catch (error) {
          console.error('Failed to fetch logs:', error);
        }
      }
      
      function startLogPolling() {
        if (logInterval) clearInterval(logInterval);
        // Poll logs every 5 seconds (less aggressive than before)
        logInterval = setInterval(refreshLogs, 5000);
      }
      
      function stopLogPolling() {
        if (logInterval) {
          clearInterval(logInterval);
          logInterval = null;
        }
      }
      
      // Page visibility management - stop polling when page is hidden
      document.addEventListener('visibilitychange', function() {
        if (document.hidden) {
          console.log('Page hidden - stopping all polling');
          stopStatusPolling();
          stopLogPolling();
        } else {
          console.log('Page visible - resuming polling');
          checkConnectionStatus();
          refreshLogs();
          loadNetworkMetrics();
          startLogPolling();
        }
      });
      
      // Clean up intervals when page is unloaded
      window.addEventListener('beforeunload', function() {
        console.log('Page unloading - cleaning up');
        stopStatusPolling();
        stopLogPolling();
      });
    </script>
  </body>
</html>
"""


class BTTetherHelper(Plugin):
    __author__ = "wsvdmeer"
    __version__ = "1.3.0-beta"
    __license__ = "GPL3"
    __description__ = "Guided Bluetooth tethering with user instructions"

    # State constants for detailed status display
    STATE_IDLE = "IDLE"
    STATE_INITIALIZING = "INITIALIZING"
    STATE_SCANNING = "SCANNING"
    STATE_PAIRING = "PAIRING"
    STATE_TRUSTING = "TRUSTING"
    STATE_CONNECTING = "CONNECTING"
    STATE_CONNECTED = "CONNECTED"
    STATE_RECONNECTING = "RECONNECTING"
    STATE_SWITCHING = "SWITCHING"
    STATE_DISCONNECTING = "DISCONNECTING"
    STATE_UNTRUSTING = "UNTRUSTING"
    STATE_DISCONNECTED = "DISCONNECTED"
    STATE_ERROR = "ERROR"

    # Web UI polling intervals (milliseconds - for JavaScript)
    WEB_STATUS_POLL_FAST_MS = 2000
    WEB_STATUS_POLL_NORMAL_MS = 10000
    WEB_STATUS_POLL_SLOW_MS = 30000
    WEB_LOG_POLL_MS = 5000
    SCAN_PROGRESS_POLL_MS = 2000
    SCAN_WAIT_BUFFER_MS = 1000

    # Standard timeouts (seconds)
    QUICK_TIMEOUT = 2
    STANDARD_TIMEOUT = 5
    LONG_TIMEOUT = 10

    # Small delays (seconds)
    BRIEF_WAIT = 0.5
    SHORT_WAIT = 1
    MEDIUM_WAIT = 2
    LONG_WAIT = 3

    # Timing constants
    BLUETOOTH_SERVICE_STARTUP_DELAY = 3
    MONITOR_INITIAL_DELAY = 5
    MONITOR_PAUSED_CHECK_INTERVAL = 10
    MONITOR_CONNECTED_CHECK_INTERVAL = (
        10  # Seconds between checks when connected (fast disconnect detection)
    )

    # Bluetooth Service UUIDs
    NAP_UUID = "00001116-0000-1000-8000-00805f9b34fb"  # Network Access Point service

    SCAN_DURATION = 30
    SCAN_DISCOVERY_WAIT = 1
    SCAN_DISCOVERY_MAX_ATTEMPTS = 60
    DEVICE_OPERATION_DELAY = 1
    DEVICE_OPERATION_LONGER_DELAY = 2
    SCAN_STOP_DELAY = 0.5
    INTERFACE_INIT_WAIT = (
        1  # Reduced from 3 — NAP already returned bnep0, minimal kernel settle time
    )
    TETHERING_INIT_WAIT = (
        1  # Reduced from 2 — dhcpcd handles retry if phone DHCP isn't ready yet
    )
    NAP_DISCONNECT_RETRY_DELAY = 1
    PROCESS_CLEANUP_DELAY = 0.2
    DBUS_OPERATION_RETRY_DELAY = 0.1
    NAME_UPDATE_INTERVAL = 30
    AGENT_LOG_MONITOR_TIMEOUT = 90  # Seconds to monitor agent log for passkey
    FALLBACK_INIT_TIMEOUT = 30  # Seconds to wait for on_ready() before fallback init (increased for testing)
    PAN_INTERFACE_WAIT = 2  # Seconds to wait for PAN interface after connection
    INTERNET_VERIFY_WAIT = 2  # Seconds to wait before verifying internet connectivity
    DHCP_KILL_WAIT = 0.5  # Wait after killing dhclient
    DHCP_RELEASE_WAIT = 1  # Wait after releasing DHCP lease
    PHONE_READY_WAIT = 1  # Reduced from 3 — 1s is enough for already-paired devices
    NAP_RETRY_DELAY = 5  # Wait between NAP connection retries (increased from 3s to allow BlueZ cleanup)
    DHCLIENT_TIMEOUT = 30  # Timeout for dhclient DHCP request
    DHCPCD_TIMEOUT = (
        30  # Timeout for dhcpcd DHCP request (increased to give phone DHCP server time)
    )
    DHCP_IP_CHECK_MAX_ATTEMPTS = (
        20  # Max attempts to check for IP (20×2s=40s) — Pixel 6 DHCP can be very slow
    )
    DHCP_RETRY_MAX = (
        3  # Max DHCP retry attempts (some phones like Pixel 6 need extra time)
    )
    DHCP_RETRY_WAIT = 5  # Seconds to wait between DHCP retries
    DHCP_RETRY_IP_CHECK_ATTEMPTS = (
        15  # IP check attempts on retry (15×2s=30s) — dhcpcd still running
    )
    PAIRING_DEVICE_DISCOVERY_TIMEOUT = (
        60  # Seconds to wait for device discovery during pairing
    )
    PAIRING_DISCOVERY_LOG_INTERVAL = (
        5  # Log progress every N seconds during pairing discovery
    )
    PAIRING_MODE_SETUP_DELAY = 1  # Wait after setting pairable/discoverable mode
    PAIRING_DISCOVERY_POLL_INTERVAL = (
        1  # Check for device every N seconds during pairing
    )
    NAP_CONNECTION_MAX_RETRIES = (
        4  # Max retries for NAP connection (4th attempt is after adapter reset)
    )
    DEFAULT_CMD_TIMEOUT = 10  # Default timeout for shell commands

    # Bluetooth service restart constants
    BLUETOOTH_RESTART_SYSTEMCTL_TIMEOUT = (
        20  # Timeout for systemctl stop/start on slow hardware (RPi may be very slow)
    )
    BLUETOOTH_RESTART_PROCESS_CLEANUP_WAIT = 1  # Wait after killing processes
    BLUETOOTH_RESTART_BETWEEN_STOP_START = 2  # Wait between stop and start
    BLUETOOTH_RESTART_POLL_INTERVAL = (
        0.2  # Poll interval when waiting for service state
    )
    BLUETOOTH_RESTART_POLL_TIMEOUT = 10  # Total timeout for polling service state
    BLUETOOTH_DBUS_SIGNAL_TIMEOUT = 3  # Timeout for D-Bus signal-based readiness check

    # Reconnect configuration constants
    DEFAULT_RECONNECT_INTERVAL = 60  # Default seconds between reconnect checks
    MAX_RECONNECT_FAILURES = 5  # Max consecutive failures before cooldown
    DEFAULT_RECONNECT_FAILURE_COOLDOWN = 300  # Default cooldown in seconds (5 minutes)
    DHCP_FAILURE_COOLDOWN = 180  # Seconds to skip a device after DHCP failure (3 min)

    # UI and buffer constants
    UI_LOG_MAXLEN = 100  # Maximum number of log messages in UI buffer

    # Status dict templates (used with _update_cached_ui_status)
    STATUS_FULLY_DISCONNECTED = {
        "paired": False,
        "trusted": False,
        "connected": False,
        "pan_active": False,
        "interface": None,
        "ip_address": None,
    }
    STATUS_PAIRED_DISCONNECTED = {
        "paired": True,
        "trusted": True,
        "connected": False,
        "pan_active": False,
        "interface": None,
        "ip_address": None,
    }
    STATUS_UNTRUSTED_DISCONNECTED = {
        "paired": True,
        "trusted": False,
        "connected": False,
        "pan_active": False,
        "interface": None,
        "ip_address": None,
    }

    # Compiled regex patterns (avoid re-compiling on every call)
    MAC_VALIDATE_PATTERN = re.compile(r"^([0-9A-F]{2}:){5}[0-9A-F]{2}$")
    ANSI_ESCAPE_PATTERN = re.compile(r"\x1b\[[0-9;]*[mGKHF]|\x01|\x02")
    SCAN_MAC_PATTERN = re.compile(
        r"([0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2})"
    )
    SCAN_ANSI_PATTERN = re.compile(r"(\x1b\[[0-9;]*m|\x08)")

    # Route and network constants
    ROUTE_METRIC_BLUETOOTH = 200
    ROUTE_METRIC_MAX_FILTER = 500000
    PAN_INTERFACE_POLL_INTERVAL = 0.5

    # Pairing constants
    PAIRING_SCAN_WAIT_TIMEOUT = 15
    PAIRING_DIALOG_TIMEOUT = 90
    NAP_DBUS_CONNECT_TIMEOUT = 25
    NAP_DBUS_WARM_RETRY_TIMEOUT = 15  # Shorter timeout for retry after ConnectProfile warms the link

    def __init__(self):
        """Initialize plugin instance - called before on_loaded()"""
        super().__init__()

        # Critical: Threading attributes MUST exist before on_loaded()
        self.lock = threading.Lock()
        self._ui_log_lock = threading.Lock()
        self._bluetoothctl_lock = threading.Lock()
        self._cached_ui_status_lock = threading.Lock()

        self._monitor_stop = threading.Event()
        self._monitor_wakeup = threading.Event()  # Signal monitor to check immediately
        self._monitor_paused = threading.Event()
        self._name_update_stop = threading.Event()
        self._initialization_done = threading.Event()
        self._bluetooth_ready = (
            threading.Event()
        )  # Signaled when Bluetooth becomes ready

        self._monitor_thread = None
        self._name_update_thread = None
        self._fallback_thread = None
        self._ui_update_timer = None

    def on_loaded(self):
        """Initialize plugin configuration and data structures only - no heavy operations"""
        from collections import deque

        self.phone_mac = ""
        self._last_connected_mac = None  # Track last successfully connected device MAC
        self._last_connected_name = None  # Track last successfully connected device NAME (more reliable than MAC)
        self._nap_interface = (
            None  # Interface name returned by Network1.Connect (e.g. "bnep0")
        )
        self._switching_in_progress = (
            False  # Flag to prevent auto-reconnect during device switch
        )
        self._status = self.STATE_IDLE
        self._message = "Ready"
        self._scanning = False
        self._stop_scan = False  # Flag to stop scan early when connecting
        self._last_scan_devices = []
        self._scan_complete_time = 0
        self._discovered_devices = {}
        self._scan_process = None
        self._scan_start_time = None
        self.agent_process = None
        self.agent_log_fd = None
        self.agent_log_path = None
        self.current_passkey = None

        self._ui_logs = deque(maxlen=self.UI_LOG_MAXLEN)

        # Load last connected device from state file (persists across reboots)
        # Must be after _ui_logs init so _log() works
        self._load_state()

        self.show_on_screen = self.options.get("show_on_screen", True)
        self.show_mini_status = self.options.get("show_mini_status", True)
        self.mini_status_position = self.options.get("mini_status_position", [110, 0])

        self.show_detailed_status = self.options.get("show_detailed_status", True)
        self.detailed_status_position = self.options.get(
            "detailed_status_position", [0, 82]
        )

        self.auto_reconnect = self.options.get("auto_reconnect", True)
        self.reconnect_interval = self.options.get(
            "reconnect_interval", self.DEFAULT_RECONNECT_INTERVAL
        )

        self.discord_webhook_url = self.options.get("discord_webhook_url", "")

        if self.discord_webhook_url:
            masked_url = self.discord_webhook_url
            if "/" in masked_url:
                parts = masked_url.split("/")
                if len(parts) > 0:
                    parts[-1] = "***" + parts[-1][-4:] if len(parts[-1]) > 4 else "****"
                    masked_url = "/".join(parts)
            logging.info(f"[bt-tether-helper] Discord webhook configured: {masked_url}")
        else:
            logging.info("[bt-tether-helper] Discord webhook not configured")

        self._connection_in_progress = False
        self._connection_start_time = None
        self._disconnecting = False
        self._disconnect_start_time = None
        self._untrusting = False
        self._untrust_start_time = None
        self._initializing = True

        self.OPERATION_TIMEOUT = 120

        self._last_known_connected = False
        self._reconnect_failure_count = 0
        self._max_reconnect_failures = self.MAX_RECONNECT_FAILURES
        self._reconnect_failure_cooldown = self.options.get(
            "reconnect_failure_cooldown", self.DEFAULT_RECONNECT_FAILURE_COOLDOWN
        )
        self._first_failure_time = None
        self._user_requested_disconnect = False

        # Device rotation tracking for switching between multiple devices on reconnection
        self._device_rotation_list = []  # List of available devices to cycle through
        self._dhcp_failed_macs = (
            {}
        )  # MAC -> timestamp of DHCP failure (skip device until cooldown)
        self._devices_tried_in_cycle = (
            set()
        )  # Set of device MACs tried in current failure cycle

        self._screen_needs_refresh = False
        self._ui_update_active = False
        self._ui_last_seen_connected = (
            False  # Track UI-side connection state for fast wakeup
        )

        self._cached_ui_status = self.STATUS_FULLY_DISCONNECTED.copy()
        self._ui_reference = (
            None  # Store UI reference for triggering updates from threads
        )

        # Add initial log entry
        self._log("INFO", "Plugin configuration loaded")

    def on_ready(self, agent):
        """Called when everything is ready and the main loop is about to start"""
        pass

    def _initialize_bluetooth_services(self):
        """Initialize Bluetooth services"""
        with self.lock:
            self._initializing = True
            self._screen_needs_refresh = True

        try:
            # Kill any existing bluetoothctl processes that might be holding discovery state
            self._log("INFO", "Cleaning up existing Bluetooth processes...")
            try:
                self._run_cmd(["pkill", "-9", "bluetoothctl"], timeout=2)
                time.sleep(0.5)
            except Exception as e:
                logging.debug(f"[bt-tether-helper] pkill error (expected): {e}")

            # Restart Bluetooth service to clear any stuck discovery state
            self._log("INFO", "Restarting Bluetooth service...")
            try:
                self._run_cmd(
                    ["sudo", "systemctl", "restart", "bluetooth"],
                    capture=True,
                    timeout=self.BLUETOOTH_RESTART_SYSTEMCTL_TIMEOUT,
                )
                time.sleep(2)  # Wait for service to fully restart

                # Check if service is actually ready with comprehensive validation
                if not self._check_bluetooth_ready(timeout=10):
                    self._log("WARNING", "Bluetooth service may not be fully ready")
                self._log("DEBUG", "Bluetooth service restarted and ready")
            except Exception as e:
                self._log("WARNING", f"Failed to restart Bluetooth: {e}")
                logging.debug(f"[bt-tether-helper] Bluetooth restart error: {e}")

            # Just start the pairing agent, don't do aggressive service restarts
            try:
                self._verify_localhost_route()
            except Exception as e:
                self._log("WARNING", f"Initial localhost check failed: {e}")

            self._start_pairing_agent()

            # Start monitoring only if auto-reconnect is enabled AND there are trusted devices
            if self.auto_reconnect:
                # Check if there are any trusted devices to monitor
                trusted_devices = self._get_trusted_devices()
                if trusted_devices:
                    self._start_monitoring_thread()
                else:
                    self._log(
                        "INFO",
                        "No trusted devices yet. Monitor will start after first pairing.",
                    )

            # Set Bluetooth device name
            self._set_device_name()

            self._log("INFO", "Bluetooth services initialized")

            if self.auto_reconnect:
                self._log("INFO", "Checking for trusted devices to auto-connect...")
                best_device = self._find_best_device_to_connect(log_results=False)
                if best_device:
                    self._log(
                        "INFO",
                        f"Found trusted device: {best_device['name']}, starting connection...",
                    )
                    self._update_cached_ui_status(mac=best_device["mac"])

                    with self.lock:
                        self._connection_in_progress = True
                        self._connection_start_time = time.time()
                        self._user_requested_disconnect = False
                        self.phone_mac = best_device["mac"]
                        self._initializing = False
                        self.status = self.STATE_CONNECTING
                        self.message = f"Auto-connecting to {best_device['name']}..."
                        self._screen_needs_refresh = True
                    self._log(
                        "INFO",
                        f"Initialization complete (auto-connect starting) - initializing flag cleared: {not self._initializing}",
                    )

                    self._monitor_paused.clear()
                    threading.Thread(
                        target=self._connect_thread, args=(best_device,), daemon=True
                    ).start()
                else:
                    self._log(
                        "INFO", "No trusted devices found. Pair a device via web UI."
                    )
                    self._update_cached_ui_status(status=self.STATUS_FULLY_DISCONNECTED)
                    with self.lock:
                        self._initializing = False
                        self._screen_needs_refresh = True

                    if self._ui_reference:
                        try:
                            self.on_ui_update(self._ui_reference)
                        except Exception as e:
                            logging.debug(
                                f"[bt-tether-helper] Error forcing UI update after init: {e}"
                            )
                    self._log(
                        "INFO",
                        f"Initialization complete - initializing flag cleared: {not self._initializing}",
                    )
            else:
                self._update_cached_ui_status()
                with self.lock:
                    self._initializing = False
                    self._screen_needs_refresh = True
                self._log(
                    "INFO",
                    f"Initialization complete (auto-reconnect disabled) - initializing flag cleared: {not self._initializing}",
                )

                if self._ui_reference:
                    try:
                        self.on_ui_update(self._ui_reference)
                    except Exception as e:
                        logging.debug(
                            f"[bt-tether-helper] Error forcing UI update after init: {e}"
                        )
        except Exception as e:
            self._log("ERROR", f"Failed to initialize Bluetooth services: {e}")
            self._update_cached_ui_status()
            with self.lock:
                self._initializing = False
                self._screen_needs_refresh = True
            self._log(
                "INFO",
                f"Initialization error handler - initializing flag cleared: {not self._initializing}",
            )
            self._log("ERROR", f"Traceback: {traceback.format_exc()}")

            if self._ui_reference:
                try:
                    self.on_ui_update(self._ui_reference)
                except Exception as update_error:
                    logging.debug(
                        f"[bt-tether-helper] Error forcing UI update after init error: {update_error}"
                    )

    def on_unload(self, ui):
        """Cleanup when plugin is unloaded"""
        try:
            self._log("INFO", "Unloading plugin, cleaning up resources...")

            if self._monitor_thread and self._monitor_thread.is_alive():
                self._monitor_stop.set()
                self._monitor_thread.join(timeout=5)

            if self._name_update_thread and self._name_update_thread.is_alive():
                self._name_update_stop.set()
                self._name_update_thread.join(timeout=5)
            if self.agent_process and self.agent_process.poll() is None:
                try:
                    self.agent_process.terminate()
                    self.agent_process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    logging.warning(
                        "[bt-tether-helper] Agent didn't terminate, killing..."
                    )
                    try:
                        self.agent_process.kill()
                        self.agent_process.wait(timeout=1)
                    except Exception as kill_err:
                        logging.error(
                            f"[bt-tether-helper] Agent kill failed: {kill_err}"
                        )
                except Exception as e:
                    logging.debug(f"[bt-tether-helper] Agent terminate failed: {e}")

            # Close agent log file
            if self.agent_log_fd:
                try:
                    if isinstance(self.agent_log_fd, int):
                        os.close(self.agent_log_fd)
                    else:
                        self.agent_log_fd.close()
                    self.agent_log_fd = None
                except Exception as e:
                    logging.debug(f"[bt-tether-helper] Failed to close agent log: {e}")

            if self.agent_log_path and os.path.exists(self.agent_log_path):
                try:
                    os.remove(self.agent_log_path)
                except Exception as e:
                    logging.debug(f"[bt-tether-helper] Failed to remove agent log: {e}")

            self._log("INFO", "Plugin unloaded successfully")
        except Exception as e:
            logging.error(f"[bt-tether-helper] Error during unload: {e}")

    def _log(self, level, message):
        """Log to both system logger and UI log buffer"""
        # Log to system
        full_message = f"[bt-tether-helper] {message}"
        if level == "ERROR":
            logging.error(full_message)
        elif level == "WARNING":
            logging.warning(full_message)
        elif level == "DEBUG":
            logging.debug(full_message)
        else:
            logging.info(full_message)

        with self._ui_log_lock:
            self._ui_logs.append(
                {
                    "timestamp": datetime.datetime.now().strftime("%H:%M:%S"),
                    "level": level,
                    "message": message,
                }
            )

    @property
    def status(self):
        return self._status

    @status.setter
    def status(self, value):
        self._status = value

    @property
    def message(self):
        return self._message

    @message.setter
    def message(self, value):
        self._message = value

    def on_ui_setup(self, ui):
        """Setup UI elements to display Bluetooth status on screen"""
        # Store UI reference for triggering updates from background threads
        self._ui_reference = ui

        # Initialize Bluetooth services now that UI is being set up
        # This happens before on_ui_update() is ever called, so display will be ready
        logging.info(
            "[bt-tether-helper] Initializing Bluetooth services in on_ui_setup()"
        )
        if not self._initialization_done.is_set():
            self._initialization_done.set()
            self._fallback_thread = threading.Thread(
                target=self._initialize_bluetooth_services, daemon=True
            )
            self._fallback_thread.start()

        # Guard: on_loaded() may not have run yet (Pwnagotchi race condition)
        if not hasattr(self, "show_on_screen"):
            return

        if self.show_on_screen and self.show_mini_status:
            pos = (
                self.mini_status_position
                if self.mini_status_position
                else (ui.width() / 2, 0)
            )
            ui.add_element(
                "bt-status",
                LabeledValue(
                    color=BLACK,
                    label="BT",
                    value="D",
                    position=pos,
                    label_font=fonts.Bold,
                    text_font=fonts.Medium,
                ),
            )

        if self.show_on_screen and self.show_detailed_status:
            ui.add_element(
                "bt-detail",
                LabeledValue(
                    color=BLACK,
                    label="",
                    value="BT:--",
                    position=tuple(self.detailed_status_position),
                    label_font=fonts.Small,
                    text_font=fonts.Small,
                ),
            )

    def on_ui_update(self, ui):
        """Update Bluetooth status on screen - MUST be non-blocking"""
        # Guard: on_loaded() may not have run yet (Pwnagotchi race condition)
        if not hasattr(self, "lock"):
            return
        if not getattr(self, "show_on_screen", True):
            return

        try:
            with self.lock:
                initializing = self._initializing
                connection_in_progress = self._connection_in_progress
                connection_start_time = self._connection_start_time
                disconnecting = self._disconnecting
                disconnect_start_time = self._disconnect_start_time
                untrusting = self._untrusting
                untrust_start_time = self._untrust_start_time
                phone_mac = self.phone_mac
                screen_needs_refresh = self._screen_needs_refresh
                status_str = self.status
                message_str = self.message
                scanning = self._scanning
                if screen_needs_refresh:
                    self._screen_needs_refresh = False

            with self._cached_ui_status_lock:
                cached_status = self._cached_ui_status.copy()

            current_time = time.time()

            if connection_in_progress and connection_start_time:
                if current_time - connection_start_time > self.OPERATION_TIMEOUT:
                    logging.warning(
                        f"[bt-tether-helper] Connection timeout ({self.OPERATION_TIMEOUT}s) - clearing stuck flag"
                    )
                    with self.lock:
                        self._connection_in_progress = False
                        self._connection_start_time = None
                        self.status = self.STATE_ERROR
                        self.message = "Connection timeout - operation took too long"
                        self._screen_needs_refresh = True
                    # Update cached UI to show error
                    self._update_cached_ui_status()
                    connection_in_progress = False

            if disconnecting and disconnect_start_time:
                if current_time - disconnect_start_time > self.OPERATION_TIMEOUT:
                    logging.warning(
                        f"[bt-tether-helper] Disconnect timeout ({self.OPERATION_TIMEOUT}s) - clearing stuck flag"
                    )
                    with self.lock:
                        self._disconnecting = False
                        self._disconnect_start_time = None
                    disconnecting = False

            if untrusting and untrust_start_time:
                if current_time - untrust_start_time > self.OPERATION_TIMEOUT:
                    logging.warning(
                        f"[bt-tether-helper] Untrust timeout ({self.OPERATION_TIMEOUT}s) - clearing stuck flag"
                    )
                    with self.lock:
                        self._untrusting = False
                        self._untrust_start_time = None
                    untrusting = False

            # Handle state transitions first (highest priority)
            # These flags are set during operations and should display immediately
            if initializing:
                if self.show_mini_status:
                    ui.set("bt-status", "I")  # I = Initializing
                if self.show_detailed_status:
                    ui.set("bt-detail", "BT:Initializing")
                return

            if scanning:
                if self.show_mini_status:
                    ui.set("bt-status", "S")  # S = Scanning
                if self.show_detailed_status:
                    ui.set("bt-detail", "BT:Scanning")
                return

            if getattr(self, "_switching_in_progress", False):
                if self.show_mini_status:
                    ui.set("bt-status", "W")  # W = sWitching
                if self.show_detailed_status:
                    ui.set("bt-detail", "BT:Switching")
                return

            if disconnecting:
                if self.show_mini_status:
                    ui.set("bt-status", "D")  # D = Disconnecting
                if self.show_detailed_status:
                    ui.set("bt-detail", "BT:Disconnecting")
                return

            if untrusting:
                if self.show_mini_status:
                    ui.set("bt-status", "T")  # T = Untrusting
                if self.show_detailed_status:
                    ui.set("bt-detail", "BT:Untrusting")
                return

            if connection_in_progress:
                # Check current status to show appropriate transition state
                # PAIRING -> TRUSTING -> CONNECTING -> CONNECTED
                if status_str == self.STATE_CONNECTED:
                    # Connection actually completed! Fall through to show connected status below
                    # Don't return - show the actual connection status from cache
                    pass
                elif status_str == self.STATE_PAIRING:
                    if self.show_mini_status:
                        ui.set("bt-status", "P")  # P = Pairing
                    if self.show_detailed_status:
                        ui.set("bt-detail", "BT:Pairing")
                    return
                elif status_str == self.STATE_TRUSTING:
                    if self.show_mini_status:
                        ui.set("bt-status", "T")  # T = Trusting
                    if self.show_detailed_status:
                        ui.set("bt-detail", "BT:Trusting")
                    return
                elif status_str == self.STATE_CONNECTING:
                    if self.show_mini_status:
                        ui.set("bt-status", ">")  # > = Connecting
                    if self.show_detailed_status:
                        ui.set("bt-detail", "BT:Connecting")
                    return
                elif status_str == self.STATE_RECONNECTING:
                    # Check if reconnection actually completed
                    if cached_status.get("connected") or cached_status.get(
                        "pan_active"
                    ):
                        # Reconnection succeeded! Fall through to show connected status
                        pass
                    else:
                        # Still reconnecting
                        if self.show_mini_status:
                            ui.set("bt-status", "R")  # R = Reconnecting
                        if self.show_detailed_status:
                            ui.set("bt-detail", "BT:Reconnecting")
                        return
                else:
                    if self.show_mini_status:
                        ui.set("bt-status", ">")  # > = Connecting (default)
                    if self.show_detailed_status:
                        ui.set("bt-detail", "BT:Connecting")
                    return

            # If no phone_mac is set AND not paired in cached status, show disconnected
            # (Check cached status to handle race conditions where phone_mac cleared but device still exists)
            if not phone_mac and not cached_status.get("paired", False):
                # No device configured yet, show disconnected
                # Update cached status to ensure web UI also reflects this state
                if cached_status.get("connected", False) or cached_status.get(
                    "pan_active", False
                ):
                    # Cached status is stale - update it in background
                    threading.Thread(
                        target=self._update_cached_ui_status,
                        args=(self.STATUS_FULLY_DISCONNECTED,),
                        daemon=True,
                    ).start()

                if self.show_mini_status:
                    ui.set("bt-status", "X")
                if self.show_detailed_status:
                    ui.set("bt-detail", "BT:No device")
                return

            # Detect disconnection from UI side and wake the monitor immediately
            # This ensures fast reconnection when the phone drops BT/tethering
            was_connected = getattr(self, "_ui_last_seen_connected", False)
            is_connected = cached_status.get("connected", False) or cached_status.get(
                "pan_active", False
            )
            self._ui_last_seen_connected = is_connected
            if was_connected and not is_connected and not connection_in_progress:
                # Connection just dropped — wake the monitor loop immediately
                self._monitor_wakeup.set()

            # Use cached status for display - background thread updates this
            # I = Initializing, > = Connecting/Pairing in progress, U = Untrusting, X = Disconnecting/Disconnected
            # C = Connected (with internet), T = Connected+Trusted (no internet), N = Connected+Untrusted, P = Paired only
            if cached_status.get("pan_active", False):
                display = (
                    "C"  # Connected with internet - will show IP in detailed status
                )
            elif cached_status.get("connected", False) and cached_status.get(
                "trusted", False
            ):
                display = "T"  # Connected and trusted but no internet yet
            elif cached_status.get("connected", False):
                display = "N"  # Connected but not trusted
            elif cached_status.get("paired", False):
                display = "P"  # Paired but not connected
            else:
                display = "X"  # Disconnected

            # Update mini status if enabled
            if self.show_mini_status:
                ui.set("bt-status", display)

            # Update detailed status line if enabled
            if self.show_detailed_status:
                try:
                    detailed = self._format_detailed_status(cached_status)
                    ui.set("bt-detail", detailed)
                except Exception as detail_error:
                    logging.debug(
                        f"[bt-tether-helper] Detailed status error: {detail_error}"
                    )
                    # Fallback to basic status on error
                    ui.set("bt-detail", f"BT:{display}")

        except Exception as e:
            # Log error but don't crash
            logging.debug(f"[bt-tether-helper] UI update error: {e}")
            # Set to unknown state if error occurs
            try:
                if self.show_mini_status:
                    ui.set("bt-status", "?")
                if self.show_detailed_status:
                    ui.set("bt-detail", "BT:Error")
            except Exception as ui_err:
                logging.debug(f"[bt-tether-helper] Failed to set error UI: {ui_err}")

    def _format_detailed_status(self, status):
        """Format detailed status line for screen display"""
        # Check if we're disconnecting
        with self.lock:
            disconnecting = self._disconnecting
            connection_in_progress = self._connection_in_progress
            untrusting = self._untrusting
            switching = self._switching_in_progress

        # Get connection state
        connected = status.get("connected", False)
        paired = status.get("paired", False)
        trusted = status.get("trusted", False)
        pan_active = status.get("pan_active", False)
        ip_address = status.get("ip_address", None)

        # Get status for more specific messaging
        with self.lock:
            status_str = self.status

        # Build status string
        if switching:
            return "BT:Switching..."
        elif disconnecting:
            return "BT:Disconnecting..."
        elif untrusting:
            return "BT:Untrusting..."
        elif connection_in_progress:
            # If we're already connected, show actual status instead of "Connecting"
            if status_str == self.STATE_CONNECTED:
                pass  # Fall through to show actual connected status
            elif status_str == self.STATE_RECONNECTING:
                return "BT:Reconnecting..."
            else:
                return "BT:Connecting..."

        # Show actual connection status
        if pan_active:
            # Connected via PAN - show IP if available, otherwise just "Connected"
            if ip_address:
                return f"BT:{ip_address}"
            else:
                return "BT:Connected"
        elif connected and trusted:
            # Connected and trusted but no PAN yet
            return "BT:Trusted"
        elif connected:
            # Connected but not trusted
            return "BT:Connected"
        elif paired:
            # Only paired
            return "BT:Paired"
        else:
            # Disconnected
            return "BT:Disconnected"

    def _update_cached_ui_status(self, status=None, mac=None):
        """Update the cached UI status from a background thread.
        This is the ONLY place that should call _get_current_status or do blocking I/O.
        """
        try:
            if status is None:
                # Fetch fresh status if not provided
                target_mac = mac if mac else self.phone_mac
                if target_mac:
                    status = self._get_current_status(target_mac)
                else:
                    status = self.STATUS_FULLY_DISCONNECTED

            # Update the cached status thread-safely
            with self._cached_ui_status_lock:
                self._cached_ui_status = status.copy()

            # Mark that screen needs refresh
            with self.lock:
                self._screen_needs_refresh = True

        except Exception as e:
            logging.debug(f"[bt-tether-helper] Failed to update cached UI status: {e}")

    def _start_pairing_agent(self):
        """Start a persistent bluetoothctl agent to handle pairing requests"""
        try:
            if self.agent_process and self.agent_process.poll() is None:
                self._log("INFO", "Pairing agent already running")
                return

            self._log("INFO", "Starting persistent pairing agent...")

            # Use KeyboardDisplay agent - shows a passkey on both devices for confirmation
            # This is the most compatible method for Android phones
            agent_commands = """power on
agent KeyboardDisplay
default-agent
"""

            env = dict(os.environ)
            env["NO_COLOR"] = "1"
            env["TERM"] = "dumb"

            # Create log file for agent output so we can see passkeys
            import tempfile

            self.agent_log_fd, self.agent_log_path = tempfile.mkstemp(
                prefix="bt-agent-", suffix=".log"
            )
            logging.info(
                f"[bt-tether-helper] Agent output will be logged to: {self.agent_log_path}"
            )

            self.agent_process = subprocess.Popen(
                ["bluetoothctl"],
                stdin=subprocess.PIPE,
                stdout=self.agent_log_fd,
                stderr=self.agent_log_fd,
                text=False,  # Use binary mode for file descriptor
                env=env,
            )

            # Send commands to bluetoothctl
            self.agent_process.stdin.write(agent_commands.encode())
            self.agent_process.stdin.flush()
            # Don't close stdin - keep it open for interactive prompts

            logging.info(
                "[bt-tether-helper] ✓ Persistent pairing agent started (KeyboardDisplay mode - passkey will be shown)"
            )
            logging.info(
                f"[bt-tether-helper] 🔑 Passkeys will appear in: {self.agent_log_path}"
            )
        except Exception as e:
            logging.error(f"[bt-tether-helper] Failed to start pairing agent: {e}")
            # Clean up on failure
            if self.agent_log_fd:
                try:
                    os.close(self.agent_log_fd)
                except:
                    pass
                self.agent_log_fd = None
            if self.agent_log_path and os.path.exists(self.agent_log_path):
                try:
                    os.remove(self.agent_log_path)
                except:
                    pass
                self.agent_log_path = None

    def _start_monitoring_thread(self):
        """Start background thread to monitor connection and auto-reconnect if dropped"""
        try:
            if self._monitor_thread and self._monitor_thread.is_alive():
                self._log("INFO", "Monitoring thread already running")
                return

            self._monitor_stop.clear()
            self._monitor_thread = threading.Thread(
                target=self._connection_monitor_loop, daemon=True
            )
            self._monitor_thread.start()
            self._log(
                "INFO",
                f"Started connection monitoring (interval: {self.reconnect_interval}s)",
            )
        except Exception as e:
            logging.error(f"[bt-tether-helper] Failed to start monitoring thread: {e}")

    def _stop_monitoring_thread(self):
        """Stop the connection monitoring thread"""
        try:
            if self._monitor_thread and self._monitor_thread.is_alive():
                logging.info("[bt-tether-helper] Stopping monitoring thread...")
                self._monitor_stop.set()
                self._monitor_thread.join(timeout=5)
                logging.info("[bt-tether-helper] Monitoring thread stopped")
        except Exception as e:
            logging.error(f"[bt-tether-helper] Error stopping monitoring thread: {e}")

    def _connection_monitor_loop(self):
        """Background loop to monitor connection status and reconnect if needed"""
        self._log("INFO", "Connection monitor started")

        # Brief wait before starting to monitor to let plugin initialize
        time.sleep(self.MONITOR_INITIAL_DELAY)

        while not self._monitor_stop.is_set():
            try:
                # Skip monitoring if connection/pairing is already in progress OR if a device switch is happening
                with self.lock:
                    connection_in_progress = self._connection_in_progress
                    switching_in_progress = self._switching_in_progress

                if connection_in_progress or switching_in_progress:
                    self._monitor_wakeup.wait(timeout=self.reconnect_interval)
                    self._monitor_wakeup.clear()
                    continue

                # Find the best device to monitor/reconnect to
                # Don't log results to reduce spam when already connected
                best_device = self._find_best_device_to_connect(log_results=False)

                if not best_device:
                    # No suitable devices - pause monitoring but periodically recheck
                    if not self._monitor_paused.is_set():
                        self._log(
                            "INFO", "No trusted devices to monitor. Monitor paused."
                        )
                        self._monitor_paused.set()

                        # Update cached UI to show disconnected state
                        self._update_cached_ui_status(
                            status=self.STATUS_FULLY_DISCONNECTED
                        )
                    # Silently recheck every 60s when paused (no logging)

                    # Sleep and then recheck for devices (don't wait indefinitely)
                    self._monitor_wakeup.wait(timeout=self.reconnect_interval)
                    self._monitor_wakeup.clear()
                    # Don't clear pause flag yet - keep it set until we find a device
                    continue

                current_mac = best_device["mac"]
                device_name = best_device["name"]

                # Clear paused flag since we found a device
                if self._monitor_paused.is_set():
                    self._monitor_paused.clear()
                    logging.info(
                        f"[bt-tether-helper] Monitor resumed - found device: {device_name}"
                    )

                # Check current connection status for this device
                status = self._get_full_connection_status(current_mac)

                # Update cached UI status for the display (non-blocking for on_ui_update)
                self._update_cached_ui_status(status=status, mac=current_mac)

                # Only log monitoring status if not connected (reduce spam)
                if not status["connected"]:
                    self._log(
                        "DEBUG", f"Monitoring device: {device_name} ({current_mac})"
                    )

                # Detect if connection was dropped (was connected, now not)
                # Don't auto-reconnect if user manually disconnected
                with self.lock:
                    user_requested_disconnect = self._user_requested_disconnect

                if (
                    self._last_known_connected
                    and not status["connected"]
                    and not user_requested_disconnect
                ):
                    logging.warning(
                        f"[bt-tether-helper] Connection to {device_name} dropped! Attempting to reconnect..."
                    )

                    # First show DISCONNECTED status on screen
                    with self.lock:
                        self.status = self.STATE_DISCONNECTED
                        self.message = f"Connection to {device_name} dropped"
                        self._screen_needs_refresh = True

                    # Force cached UI to show disconnected (clear any lingering IP/interface)
                    self._update_cached_ui_status(
                        status=self.STATUS_PAIRED_DISCONNECTED,
                        mac=current_mac,
                    )

                    # Now set to RECONNECTING and attempt to reconnect
                    with self.lock:
                        self.status = self.STATE_RECONNECTING
                        self.message = (
                            f"Connection lost to {device_name}, reconnecting..."
                        )
                        self._connection_in_progress = True
                        self._connection_start_time = time.time()
                        self._initializing = (
                            False  # Ensure initializing flag is cleared
                        )
                        self._screen_needs_refresh = True

                    # Attempt to reconnect to this device
                    success = self._reconnect_device()

                    if success:
                        # Update phone_mac to the device we successfully connected to
                        self.phone_mac = current_mac

                    with self.lock:
                        self._screen_needs_refresh = True

                    # Re-check status after reconnect attempt to avoid the
                    # "not connected" path firing again in the same iteration
                    status = self._get_full_connection_status(current_mac)

                # Update last known state (do this AFTER checking for changes)
                self._last_known_connected = status["connected"]

                # Only try to reconnect if device is BOTH paired AND trusted (and not blocked)
                # Also check if we haven't exceeded max failures and user didn't manually disconnect
                with self.lock:
                    connection_in_progress = self._connection_in_progress
                    user_requested_disconnect = self._user_requested_disconnect

                if (
                    status["paired"]
                    and status["trusted"]
                    and not status["connected"]
                    and not connection_in_progress
                    and self._reconnect_failure_count < self._max_reconnect_failures
                    and not user_requested_disconnect
                ):
                    logging.info(
                        f"[bt-tether-helper] Device {device_name} is paired/trusted but not connected. Attempting connection..."
                    )
                    with self.lock:
                        self.status = self.STATE_CONNECTING
                        self.message = f"Reconnecting to {device_name}..."
                        self._connection_in_progress = True
                        self._connection_start_time = time.time()
                        self._initializing = (
                            False  # Ensure initializing flag is cleared
                        )
                        self._screen_needs_refresh = True

                    # Update cached UI to show disconnected immediately before reconnecting
                    # This ensures the UI shows the transition through the connecting state
                    self._update_cached_ui_status(status=status, mac=current_mac)

                    success = self._reconnect_device()

                    if success:
                        # Reset failure counter on successful connection
                        self._reconnect_failure_count = 0
                        self._first_failure_time = None
                        self._device_rotation_list = []
                        self._devices_tried_in_cycle = set()
                        # Clear DHCP failure for this device on success
                        self._dhcp_failed_macs.pop(current_mac.upper(), None)
                        # Update phone_mac to the successful device
                        self.phone_mac = current_mac
                    else:
                        # Device reconnection failed - mark this device as tried in this cycle
                        self._devices_tried_in_cycle.add(current_mac.upper())
                        self._reconnect_failure_count += 1

                        # Track when failures started
                        if self._first_failure_time is None:
                            self._first_failure_time = time.time()

                        # Update cached UI to show disconnected state after failure
                        self._update_cached_ui_status(mac=current_mac)

                        # DEVICE SWITCHING: When reconnection fails, try other trusted devices
                        trusted_devices = self._get_trusted_devices()
                        nap_devices = [d for d in trusted_devices if d["has_nap"]]

                        # Build rotation list if we have multiple devices and haven't done so yet
                        if len(nap_devices) > 1 and not self._device_rotation_list:
                            # Create rotation list of all devices except the currently failing one
                            self._device_rotation_list = [
                                d
                                for d in nap_devices
                                if d["mac"].upper() != current_mac.upper()
                                and not d["connected"]
                            ]
                            if self._device_rotation_list:
                                device_names = [
                                    d["name"] for d in self._device_rotation_list
                                ]
                                self._log(
                                    "INFO",
                                    f"Multiple devices found. Will switch between: {', '.join(device_names)}",
                                )

                        # Try next device in rotation if available and we haven't tried all yet
                        if self._device_rotation_list and len(
                            self._devices_tried_in_cycle
                        ) <= len(nap_devices):
                            # Find next untried device in rotation
                            next_device = None
                            for device in self._device_rotation_list:
                                if (
                                    device["mac"].upper()
                                    not in self._devices_tried_in_cycle
                                ):
                                    next_device = device
                                    break

                            if next_device:
                                self._log(
                                    "WARNING",
                                    f"Reconnection to {device_name} failed. Switching to {next_device['name']}...",
                                )
                                # Full bridge cleanup before switching — a phantom BNEP
                                # bridge from the failed device will block ALL subsequent
                                # NAP connections with br-connection-busy
                                self._log(
                                    "INFO",
                                    "Running bridge cleanup before switching...",
                                )
                                self._cleanup_bnep_bridge(mac=current_mac)

                                # Try the next device
                                with self.lock:
                                    self.status = self.STATE_CONNECTING
                                    self.message = (
                                        f"Switching to {next_device['name']}..."
                                    )
                                    self._connection_in_progress = True
                                    self._connection_start_time = time.time()
                                    self._screen_needs_refresh = True

                                next_success = self._reconnect_device_with_mac(
                                    next_device["mac"]
                                )
                                if next_success:
                                    self._log(
                                        "INFO",
                                        f"✓ Connected to {next_device['name']}",
                                    )
                                    self._reconnect_failure_count = 0
                                    self._first_failure_time = None
                                    self._device_rotation_list = []
                                    self._devices_tried_in_cycle = set()
                                    self.phone_mac = next_device["mac"]
                                    self._last_connected_mac = next_device["mac"]
                                    self._last_connected_name = next_device["name"]
                                    self._save_state()
                                    self._update_cached_ui_status(
                                        status=self._get_full_connection_status(
                                            next_device["mac"]
                                        ),
                                        mac=next_device["mac"],
                                    )
                                else:
                                    self._log(
                                        "WARNING",
                                        f"{next_device['name']} also failed to connect",
                                    )
                                    # Mark this device as tried and will try next one on next iteration
                                    self._devices_tried_in_cycle.add(
                                        next_device["mac"].upper()
                                    )

                        # Check if we've tried all devices or exceeded max failures
                        all_devices_tried = (
                            len(self._devices_tried_in_cycle) >= len(nap_devices)
                            if nap_devices
                            else False
                        )

                        if (
                            self._reconnect_failure_count
                            >= self._max_reconnect_failures
                            or all_devices_tried
                        ):
                            self._log(
                                "WARNING",
                                f"⚠️  Auto-reconnect paused after {self._reconnect_failure_count} failed attempts",
                            )
                            self._log(
                                "INFO",
                                f"📱 Will retry after {self._reconnect_failure_cooldown}s cooldown, or reconnect manually via web UI",
                            )
                            with self.lock:
                                self.status = self.STATE_DISCONNECTED
                                self.message = f"Auto-reconnect paused - retrying in {self._reconnect_failure_cooldown}s"
                                self._connection_in_progress = False
                                self._screen_needs_refresh = True
                            # Reset device rotation for next cycle
                            self._device_rotation_list = []
                            self._devices_tried_in_cycle = set()
                elif self._reconnect_failure_count >= self._max_reconnect_failures:
                    # Already exceeded max failures - check if cooldown period has elapsed
                    if self._first_failure_time:
                        time_since_first_failure = (
                            time.time() - self._first_failure_time
                        )
                        if time_since_first_failure >= self._reconnect_failure_cooldown:
                            # Cooldown period elapsed, reset counter and try again
                            self._log(
                                "INFO",
                                f"Cooldown period elapsed ({self._reconnect_failure_cooldown}s), resetting failure counter and retrying...",
                            )
                            # Full bridge cleanup before retrying — the bridge may
                            # still be stuck from the previous failed cycle
                            self._cleanup_bnep_bridge()
                            self._reconnect_failure_count = 0
                            self._first_failure_time = None
                            self._device_rotation_list = []
                            self._devices_tried_in_cycle = set()
                elif not status["paired"] or not status["trusted"]:
                    # Device not paired/trusted (or blocked), don't attempt auto-reconnect
                    # Reset failure counter since this is intentional
                    self._reconnect_failure_count = 0
                    self._first_failure_time = None
                    self._device_rotation_list = []
                    self._devices_tried_in_cycle = set()
                    logging.debug(
                        f"[bt-tether-helper] Device not ready for auto-reconnect (paired={status['paired']}, trusted={status['trusted']})"
                    )

            except Exception as e:
                logging.error(f"[bt-tether-helper] Monitor loop error: {e}")

            # Wait for next check — use shorter interval when connected for fast disconnect detection
            if self._last_known_connected:
                wait_time = self.MONITOR_CONNECTED_CHECK_INTERVAL
            else:
                wait_time = self.reconnect_interval
            self._monitor_wakeup.wait(timeout=wait_time)
            self._monitor_wakeup.clear()

        self._log("INFO", "Connection monitor stopped")

    def _perform_reconnect(self, mac, device_info=None, pre_cleanup=False):
        """Core reconnection logic shared by _reconnect_device and _reconnect_device_with_mac.

        Args:
            mac: Target device MAC address
            device_info: Optional dict with device info (name, etc.) for notifications
            pre_cleanup: If True, clean up stale BNEP bridge before connecting
        """
        try:
            with self.lock:
                self._connection_in_progress = True
                self._connection_start_time = time.time()
                self._initializing = False

            self._log("INFO", f"Reconnecting to {mac}...")

            # Pre-cleanup of stale BNEP bridge (used when switching between devices)
            if pre_cleanup:
                try:
                    ifaces_out = subprocess.check_output(
                        ["ip", "link", "show"], text=True, timeout=5
                    )
                    if "bnep0" in ifaces_out:
                        self._log(
                            "INFO", "Cleaning up stale BNEP bridge before reconnect..."
                        )
                        self._cleanup_bnep_bridge(mac=mac)
                except Exception:
                    pass

            # Check if device is blocked
            devices_output = self._run_cmd(
                ["bluetoothctl", "devices", "Blocked"], capture=True, timeout=5
            )
            if devices_output and devices_output != "Timeout" and mac in devices_output:
                self._log("INFO", f"Unblocking device {mac}...")
                self._run_cmd(["bluetoothctl", "unblock", mac], capture=True)
                time.sleep(self.DEVICE_OPERATION_DELAY)

            # Trust the device
            self._log("INFO", f"Ensuring device is trusted...")
            self._run_cmd(["bluetoothctl", "trust", mac], capture=True)
            time.sleep(self.DEVICE_OPERATION_DELAY)

            # Start monitoring thread if this is the first trusted device
            if self.auto_reconnect and not (
                self._monitor_thread and self._monitor_thread.is_alive()
            ):
                self._log(
                    "INFO", "First device trusted, starting connection monitor..."
                )
                self._start_monitoring_thread()

            # Try NAP connection
            self._log("INFO", f"Attempting NAP connection...")
            nap_connected = self._connect_nap_dbus(mac)

            # If NAP failed, check if BlueZ is stuck and retry once after recovery
            if not nap_connected:
                last_error = getattr(self, "_last_nap_error", "") or ""
                if (
                    "NoReply" in last_error
                    or "Did not receive a reply" in last_error
                    or "Timeout" in last_error
                    or "br-connection-busy" in last_error
                ):
                    self._log(
                        "WARNING",
                        f"NAP failed with '{last_error[:60]}' — checking BlueZ health...",
                    )
                    recovered = self._recover_bluez_if_stuck(mac=mac)
                    if recovered:
                        self._log("INFO", "Retrying NAP after BlueZ recovery...")
                        nap_connected = self._connect_nap_dbus(mac)

            if nap_connected:
                self._log("INFO", f"✓ Reconnection successful")

                # Get PAN interface
                iface = getattr(self, "_nap_interface", None)
                if iface:
                    self._log("INFO", f"✓ Network1 returned interface: {iface}")
                else:
                    # Use 20s timeout — after warm retry the bridge may take longer
                    self._log("INFO", "Waiting for PAN interface to appear...")
                    iface = self._wait_for_pan_interface(timeout=20)

                if iface:
                    self._log("INFO", f"✓ PAN interface active: {iface}")

                    # Setup network with DHCP
                    dhcp_ok = self._setup_network_dhcp(iface)
                    if not dhcp_ok:
                        self._log(
                            "WARNING",
                            f"DHCP failed during reconnect — cleaning up bnep0",
                        )
                        self._dhcp_failed_macs[mac.upper()] = time.time()
                        self._cleanup_bnep_bridge(mac=mac)
                        with self.lock:
                            if self.phone_mac and self.phone_mac.upper() == mac.upper():
                                self.phone_mac = None
                        return False

                    self._log("INFO", f"✓ Network setup successful")

                    # Verify internet connectivity
                    time.sleep(self.INTERNET_VERIFY_WAIT)
                    has_internet = self._check_internet_connectivity()

                    if has_internet:
                        self._log("INFO", f"✓ Internet connectivity verified!")
                    else:
                        self._log("WARNING", "Reconnected but no internet detected")

                    # Remember this device as last successfully connected
                    self._last_connected_mac = mac
                    self._dhcp_failed_macs.pop(mac.upper(), None)
                    if device_info and "name" in device_info:
                        self._last_connected_name = device_info["name"]
                    else:
                        info_output = self._run_cmd(
                            ["bluetoothctl", "info", mac], capture=True, timeout=5
                        )
                        if info_output:
                            name_match = re.search(
                                r"Name: (.+)$", info_output, re.MULTILINE
                            )
                            if name_match:
                                self._last_connected_name = name_match.group(1).strip()
                    self._save_state()

                    # Send notifications on successful internet connection
                    if has_internet:
                        try:
                            current_ip = self._get_current_ip()
                            current_ipv6 = self._get_global_ipv6(iface)

                            if current_ip:
                                self._log("INFO", f"Current IPv4 address: {current_ip}")
                            if current_ipv6:
                                self._log(
                                    "INFO", f"Current IPv6 address: {current_ipv6}"
                                )

                            if current_ip and self.discord_webhook_url:
                                self._log(
                                    "INFO",
                                    "Discord webhook configured, starting notification thread...",
                                )
                                device_name_discord = None
                                if device_info:
                                    device_name_discord = device_info.get("name")
                                if not device_name_discord:
                                    info_out = self._run_cmd(
                                        ["bluetoothctl", "info", mac],
                                        capture=True,
                                        timeout=5,
                                    )
                                    if info_out:
                                        nm = re.search(r"Name:\s+(.+)", info_out)
                                        if nm:
                                            device_name_discord = nm.group(1).strip()
                                threading.Thread(
                                    target=self._send_discord_notification,
                                    args=(current_ip, device_name_discord),
                                    daemon=True,
                                ).start()

                            if not current_ip and not current_ipv6:
                                self._log(
                                    "WARNING",
                                    "Could not get any IP address for notifications",
                                )
                        except Exception as e:
                            self._log("ERROR", f"Failed to send notifications: {e}")

                    # Update cached UI status FIRST while flag is still True
                    self._update_cached_ui_status(mac=mac)

                    # Then update status and clear flags
                    msg = (
                        f"✓ Reconnected! Internet via {iface}"
                        if has_internet
                        else f"Reconnected via {iface} but no internet"
                    )
                    with self.lock:
                        self.status = self.STATE_CONNECTED
                        self.message = msg
                        self._connection_in_progress = False
                        self._connection_start_time = None
                        self._initializing = False
                        self._screen_needs_refresh = True
                    return True
                else:
                    self._log(
                        "WARNING",
                        "NAP connected but no interface detected — cleaning up bridge",
                    )
                    self._cleanup_bnep_bridge(mac=mac)
                    with self.lock:
                        self.status = self.STATE_DISCONNECTED
                        self.message = "NAP profile didn't create interface"
                        self._connection_in_progress = False
                        self._connection_start_time = None
                        self._initializing = False
                        self._screen_needs_refresh = True
                    return False
            else:
                self._log("WARNING", "Reconnection failed")
                with self.lock:
                    self.status = self.STATE_DISCONNECTED
                    self.message = "Reconnection failed. Will retry later."
                    self._connection_in_progress = False
                    self._connection_start_time = None
                    self._initializing = False
                    self._screen_needs_refresh = True
                self._update_cached_ui_status(
                    status=self.STATUS_PAIRED_DISCONNECTED,
                    mac=mac,
                )
                return False

        except Exception as e:
            self._log("ERROR", f"Reconnection error: {e}")
            with self.lock:
                self.status = self.STATE_DISCONNECTED
                self.message = f"Reconnection error: {str(e)[:50]}"
                self._connection_in_progress = False
                self._connection_start_time = None
                self._initializing = False
                self._screen_needs_refresh = True
            self._update_cached_ui_status(
                status=self.STATUS_PAIRED_DISCONNECTED,
                mac=mac,
            )
            return False
        finally:
            with self.lock:
                if self._connection_in_progress:
                    self._connection_in_progress = False
                    self._connection_start_time = None

    def _reconnect_device(self):
        """Attempt to reconnect to a previously paired device"""
        best_device = None
        mac = None

        if self._last_connected_mac:
            try:
                status = self._check_pair_status(self._last_connected_mac)
                if status["paired"] and status["trusted"]:
                    mac = self._last_connected_mac
                    self._log("INFO", f"Using last connected device: {mac}")
                else:
                    self._log(
                        "WARNING",
                        f"Last connected device {self._last_connected_mac} is no longer paired/trusted, finding alternative...",
                    )
                    best_device = self._find_best_device_to_connect()
                    if not best_device:
                        self._log("DEBUG", "No trusted devices found for reconnection")
                        return False
                    mac = best_device["mac"]
            except Exception as e:
                self._log(
                    "WARNING",
                    f"Error checking last connected device: {e}, finding alternative...",
                )
                best_device = self._find_best_device_to_connect()
                if not best_device:
                    self._log("DEBUG", "No trusted devices found for reconnection")
                    return False
                mac = best_device["mac"]
        else:
            best_device = self._find_best_device_to_connect()
            if not best_device:
                self._log("DEBUG", "No trusted devices found for reconnection")
                return False
            mac = best_device["mac"]

        self.phone_mac = mac
        return self._perform_reconnect(mac, device_info=best_device)

    def _reconnect_device_with_mac(self, mac):
        """Attempt to reconnect to a specific device by MAC address (used for device rotation)"""
        return self._perform_reconnect(mac, pre_cleanup=True)

    def _monitor_agent_log_for_passkey(self, passkey_found_event):
        """Monitor agent log file for passkey display in real-time and auto-confirm"""
        try:
            logging.info("[bt-tether-helper] Monitoring agent log for passkey...")

            # Tail the agent log file
            with open(self.agent_log_path, "r") as f:
                # Seek to end of file
                f.seek(0, 2)

                # Monitor for configured timeout
                start_time = time.time()
                last_prompt = None
                while time.time() - start_time < self.AGENT_LOG_MONITOR_TIMEOUT:
                    # Exit early if passkey found
                    if passkey_found_event.is_set():
                        logging.info(
                            "[bt-tether-helper] Passkey found, stopping log monitor"
                        )
                        break

                    line = f.readline()
                    if line:
                        clean_line = self._strip_ansi_codes(line.strip())
                        if clean_line:
                            # Look for passkey or confirmation request
                            if (
                                "passkey" in clean_line.lower()
                                or "confirm passkey" in clean_line.lower()
                            ):
                                # Extract passkey number (usually 6 digits)

                                passkey_match = re.search(
                                    r"passkey\s+(\d{6})", clean_line, re.IGNORECASE
                                )
                                if passkey_match:
                                    self.current_passkey = passkey_match.group(1)
                                    self._log(
                                        "WARNING",
                                        f"🔑 PASSKEY: {self.current_passkey} - Confirm on phone!",
                                    )
                                    logging.info(
                                        f"[bt-tether-helper] 🔑 PASSKEY: {self.current_passkey} captured from agent log"
                                    )

                                    # Update status message so it shows prominently in web UI
                                    with self.lock:
                                        self.status = self.STATE_PAIRING
                                        self.message = f"🔑 PASSKEY: {self.current_passkey}\n\nVerify this matches on your phone, then tap PAIR!"

                                    # Auto-confirm passkey on Pwnagotchi side
                                    if (
                                        self.agent_process
                                        and self.agent_process.poll() is None
                                    ):
                                        try:
                                            self._log(
                                                "INFO",
                                                "✅ Auto-confirming on Pwnagotchi & waiting for phone...",
                                            )
                                            if (
                                                self.agent_process.stdin
                                                and not self.agent_process.stdin.closed
                                            ):
                                                self.agent_process.stdin.write(b"yes\n")
                                                self.agent_process.stdin.flush()
                                        except Exception as confirm_err:
                                            logging.error(
                                                f"[bt-tether-helper] Failed to auto-confirm: {confirm_err}"
                                            )

                                passkey_found_event.set()
                            elif "request confirmation" in clean_line.lower():
                                self._log("INFO", f"📱 {clean_line}")
                            elif clean_line.endswith("#"):
                                # Only log prompt changes to reduce spam
                                if clean_line != last_prompt:
                                    last_prompt = clean_line
                                    logging.debug(
                                        f"[bt-tether-helper] Prompt: {clean_line}"
                                    )
                            elif not clean_line.startswith("[CHG]"):
                                # Log other important output at debug level
                                logging.debug(f"[bt-tether-helper] Agent: {clean_line}")
                    else:
                        # No new data, sleep briefly
                        time.sleep(self.DBUS_OPERATION_RETRY_DELAY)

            self._log(
                "INFO",
                f"Agent log monitoring timeout ({self.AGENT_LOG_MONITOR_TIMEOUT}s)",
            )
        except Exception as e:
            self._log("ERROR", f"Error monitoring agent log: {e}")

    def on_webhook(self, path, request):
        try:
            # Guard: on_loaded() may not have run yet (Pwnagotchi race condition)
            if not hasattr(self, "lock"):
                return "Plugin initializing...", 503

            # Normalize path by stripping leading slash
            clean_path = path.lstrip("/") if path else ""

            if not clean_path:
                with self.lock:
                    return render_template_string(
                        HTML_TEMPLATE,
                        mac=self.phone_mac,
                        status=self.status,
                        message=self.message,
                    )

            if clean_path == "trusted-devices":
                devices = self._get_trusted_devices()
                logging.debug(
                    f"[bt-tether-helper] Returning {len(devices)} trusted devices to web UI"
                )
                return jsonify({"devices": devices})

            if clean_path == "logs":
                with self._ui_log_lock:
                    logs = list(self._ui_logs)
                logging.debug(
                    f"[bt-tether-helper] Returning {len(logs)} logs to web UI"
                )
                return jsonify({"logs": logs})

            if clean_path == "network-metrics":
                # Get current routing metrics for web UI
                metrics = self._get_network_metrics()
                return jsonify(metrics)

            if clean_path == "connect":
                mac = request.args.get("mac", "").strip().upper()

                # If MAC provided, use it; otherwise find best device automatically
                if mac and self._validate_mac(mac):
                    with self.lock:
                        self.phone_mac = mac
                    self.start_connection()
                    # Force immediate screen update to show connecting state
                    if self._ui_reference:
                        try:
                            self.on_ui_update(self._ui_reference)
                        except Exception as e:
                            logging.debug(
                                f"[bt-tether-helper] Error forcing UI update on connect: {e}"
                            )
                    return jsonify(
                        {"success": True, "message": f"Connection started to {mac}"}
                    )
                else:
                    # No MAC or invalid MAC - use smart device selection
                    best_device = self._find_best_device_to_connect()
                    if best_device:
                        with self.lock:
                            self.phone_mac = best_device["mac"]
                        self.start_connection()
                        # Force immediate screen update to show connecting state
                        if self._ui_reference:
                            try:
                                self.on_ui_update(self._ui_reference)
                            except Exception as e:
                                logging.debug(
                                    f"[bt-tether-helper] Error forcing UI update on connect: {e}"
                                )
                        return jsonify(
                            {
                                "success": True,
                                "message": f"Connection started to {best_device['name']} ({best_device['mac']})",
                            }
                        )
                    else:
                        return jsonify(
                            {
                                "success": False,
                                "message": "No suitable devices found - pair a device first or set MAC address",
                            }
                        )

            if clean_path == "pair-device":
                mac = request.args.get("mac", "").strip().upper()
                if mac and self._validate_mac(mac):
                    with self.lock:
                        self.phone_mac = mac

                        if self._connection_in_progress:
                            return jsonify(
                                {
                                    "success": False,
                                    "message": "Connection already in progress",
                                }
                            )

                        if self._scanning:
                            self._scanning = False
                            if self._scan_process and self._scan_process.poll() is None:
                                try:
                                    self._scan_process.stdin.write("scan off\nexit\n")
                                    self._scan_process.stdin.flush()
                                    self._scan_process.terminate()
                                except:
                                    pass
                            self._scan_process = None

                        self._connection_in_progress = True
                        self._connection_start_time = time.time()
                        self._user_requested_disconnect = False
                        self._screen_needs_refresh = True

                    self._reconnect_failure_count = 0
                    self._monitor_paused.clear()

                    device_info = {
                        "mac": mac,
                        "name": request.args.get("name", "Unknown Device"),
                        "paired": False,
                        "trusted": False,
                        "connected": False,
                        "has_nap": True,
                    }

                    # Stop any ongoing scan when user selects a device
                    self._stop_scan = True
                    threading.Thread(
                        target=self._connect_thread, args=(device_info,), daemon=True
                    ).start()

                    if self._ui_reference:
                        self.on_ui_update(self._ui_reference)

                    return jsonify(
                        {"success": True, "message": f"Pairing started with {mac}"}
                    )
                else:
                    return jsonify({"success": False, "message": "Invalid MAC address"})

            if clean_path == "status":
                with self.lock:
                    # Get last connected device name if available
                    last_connected_name = self._last_connected_name

                    return jsonify(
                        {
                            "status": self.status,
                            "message": self.message,
                            "mac": self.phone_mac,
                            "last_connected_mac": self._last_connected_mac,
                            "last_connected_name": last_connected_name,
                            "disconnecting": self._disconnecting,
                            "untrusting": self._untrusting,
                            "initializing": self._initializing,
                            "connection_in_progress": self._connection_in_progress,
                            "switching_in_progress": self._switching_in_progress,
                        }
                    )

            if clean_path == "disconnect":
                mac = request.args.get("mac", "").strip().upper()
                if mac and self._validate_mac(mac):
                    # Update cached UI status FIRST to show disconnected state immediately
                    # This clears any lingering "Test Internet Connectivity" messages
                    self._update_cached_ui_status(
                        status=self.STATUS_UNTRUSTED_DISCONNECTED,
                        mac=mac,
                    )

                    # Set flags immediately so UI shows disconnecting state
                    with self.lock:
                        self._user_requested_disconnect = True
                        self._disconnecting = True
                        self._disconnect_start_time = time.time()
                        self.status = self.STATE_DISCONNECTING
                        self.message = "Disconnecting..."
                        self._screen_needs_refresh = True

                    # Run disconnect in background thread so UI can update
                    def do_disconnect():
                        try:
                            self._disconnect_device(mac)
                        except Exception as e:
                            logging.error(
                                f"[bt-tether-helper] Background disconnect error: {e}"
                            )
                            with self.lock:
                                self._disconnecting = False
                                self._connection_in_progress = False

                    thread = threading.Thread(target=do_disconnect, daemon=True)
                    thread.start()

                    if self._ui_reference:
                        try:
                            self.on_ui_update(self._ui_reference)
                        except Exception as e:
                            logging.debug(
                                f"[bt-tether-helper] Error forcing UI update on disconnect: {e}"
                            )

                    return jsonify({"success": True, "message": "Disconnect started"})
                else:
                    return jsonify({"success": False, "message": "Invalid MAC"})

            if clean_path == "unpair":
                mac = request.args.get("mac", "").strip().upper()
                if mac and self._validate_mac(mac):
                    result = self._unpair_device(mac)
                    return jsonify(result)
                else:
                    return jsonify({"success": False, "message": "Invalid MAC"})

            if clean_path == "pair-status":
                mac = request.args.get("mac", "").strip().upper()
                if mac and self._validate_mac(mac):
                    status = self._check_pair_status(mac)
                    return jsonify(status)
                else:
                    return jsonify({"paired": False, "connected": False})

            if clean_path == "scan":
                current_time = time.time()
                with self.lock:
                    if self._scanning:
                        devices_to_return = list(self._discovered_devices.values())
                        return jsonify({"devices": devices_to_return, "scanning": True})

                    # Clear devices list and scan state for fresh scan
                    self._last_scan_devices = []
                    self._discovered_devices = {}
                    self._scan_complete_time = 0
                    self._scanning = True
                    self._screen_needs_refresh = True

                def run_scan_bg():
                    try:
                        devices = self._scan_devices()
                        with self.lock:
                            self._last_scan_devices = devices
                            # Rebuild self._discovered_devices from devices list to ensure it has all data
                            self._discovered_devices = {
                                device["mac"]: device for device in devices
                            }
                            self._scan_complete_time = time.time()
                            self._scanning = False  # Mark scan as complete
                        logging.info(
                            f"[bt-tether-helper] Scan complete, found {len(devices)} devices"
                        )
                    except Exception as e:
                        logging.error(f"[bt-tether-helper] Background scan error: {e}")
                        with self.lock:
                            self._scanning = False  # Clear flag even on error

                thread = threading.Thread(target=run_scan_bg, daemon=True)
                thread.start()

                if self._ui_reference:
                    try:
                        self.on_ui_update(self._ui_reference)
                    except Exception as e:
                        logging.debug(
                            f"[bt-tether-helper] Error forcing UI update: {e}"
                        )

                return jsonify({"devices": [], "scanning": True})

            if clean_path == "scan-progress":
                with self.lock:
                    devices = list(self._discovered_devices.values())
                    scanning = self._scanning
                return jsonify(
                    {"scanning": scanning, "devices": devices, "count": len(devices)}
                )

            if clean_path == "untrust":
                mac = request.args.get("mac", "").strip().upper()
                if mac and self._validate_mac(mac):
                    try:
                        # Set untrusting flag so UI shows transitional state
                        with self.lock:
                            self._untrusting = True
                            self._untrust_start_time = time.time()
                            self._user_requested_disconnect = True
                            self._screen_needs_refresh = True

                        # Update cached UI to show disconnected state immediately
                        self._update_cached_ui_status(
                            status=self.STATUS_FULLY_DISCONNECTED,
                            mac=mac,
                        )

                        self._log("INFO", f"Forgetting device {mac}...")

                        # Step 1: Disconnect
                        self._run_cmd(
                            ["bluetoothctl", "disconnect", mac],
                            capture=True,
                            timeout=self.STANDARD_TIMEOUT,
                        )
                        time.sleep(self.SHORT_WAIT)

                        # Step 2: Untrust
                        self._run_cmd(
                            ["bluetoothctl", "untrust", mac],
                            capture=True,
                            timeout=self.STANDARD_TIMEOUT,
                        )

                        # Step 3: Block to prevent auto-reconnection
                        self._run_cmd(
                            ["bluetoothctl", "block", mac],
                            capture=True,
                            timeout=self.STANDARD_TIMEOUT,
                        )

                        # Step 4: Remove/unpair the device completely
                        self._run_cmd(
                            ["bluetoothctl", "remove", mac],
                            capture=True,
                            timeout=self.STANDARD_TIMEOUT,
                        )

                        with self.lock:
                            if self.phone_mac and self.phone_mac.upper() == mac.upper():
                                self.phone_mac = ""
                            # Clear last connected tracking so monitor doesn't try to reconnect
                            if (
                                self._last_connected_mac
                                and self._last_connected_mac.upper() == mac.upper()
                            ):
                                self._last_connected_mac = None
                                self._last_connected_name = None
                            # Reset device rotation state
                            self._device_rotation_list = []
                            self._devices_tried_in_cycle = set()

                        self._log("INFO", f"Device {mac} forgotten successfully")

                        return jsonify(
                            {"success": True, "message": f"Device {mac} untrusted"}
                        )
                    except Exception as e:
                        self._log("ERROR", f"Untrust failed: {e}")
                        return jsonify({"success": False, "message": str(e)})
                    finally:
                        with self.lock:
                            self._untrusting = False
                            self._untrust_start_time = None
                            self._screen_needs_refresh = True
                else:
                    return jsonify({"success": False, "message": "Invalid MAC"})

            if clean_path == "switch-device":
                new_mac = request.args.get("mac", "").strip().upper()
                if not new_mac or not self._validate_mac(new_mac):
                    return jsonify({"success": False, "message": "Invalid MAC"})

                # Determine if we need to disconnect an old device first
                old_mac = (
                    self.phone_mac
                    if (self.phone_mac and self.phone_mac.upper() != new_mac.upper())
                    else None
                )

                if old_mac:
                    # Set flag to prevent connection monitor from auto-reconnecting during switch
                    self._switching_in_progress = True
                    try:
                        self._log(
                            "INFO",
                            f"Switching from {old_mac} to {new_mac}...",
                        )

                        # Set new phone_mac immediately so device selection prefers the new device
                        with self.lock:
                            self.phone_mac = new_mac
                            # Clear last connected device to force selection of new_mac
                            self._last_connected_name = None
                            self._last_connected_mac = None
                            self._user_requested_disconnect = False
                            self.status = self.STATE_SWITCHING
                            self.message = f"Switching to new device..."
                            self._screen_needs_refresh = True

                        # === Disconnect old device and release BNEP bridge ===
                        # Uses Network1.Disconnect() first (clean BlueZ path),
                        # falls back to aggressive cleanup only if bnep0 persists.
                        self._log("INFO", f"Releasing bridge from {old_mac}...")
                        self._cleanup_bnep_bridge(mac=old_mac)

                        # Verify bnep0 is gone
                        try:
                            ifaces_check = subprocess.check_output(
                                ["ip", "link", "show"], text=True, timeout=5
                            )
                            if "bnep0" in ifaces_check:
                                self._log(
                                    "WARNING",
                                    "bnep0 persists after cleanup — retrying...",
                                )
                                time.sleep(2)
                                self._cleanup_bnep_bridge(mac=old_mac)
                        except Exception as cleanup_err:
                            logging.debug(
                                f"[bt-tether-helper] bnep verify: {cleanup_err}"
                            )
                    except Exception as e:
                        logging.debug(
                            f"[bt-tether-helper] Disconnect during switch: {e}"
                        )
                    finally:
                        # Clear switch flag to allow monitor to resume
                        self._switching_in_progress = False
                else:
                    # No old device to disconnect, or same MAC — just set phone_mac and clear tracking
                    with self.lock:
                        self.phone_mac = new_mac
                        self._last_connected_name = None
                        self._last_connected_mac = None
                        self._user_requested_disconnect = False

                self.start_connection()
                return jsonify({"success": True, "message": f"Switching to {new_mac}"})

            if clean_path == "connection-status":
                mac = request.args.get("mac", "").strip().upper()
                if mac and self._validate_mac(mac):
                    status = self._get_full_connection_status(mac)
                    return jsonify(status)
                else:
                    return jsonify(
                        {
                            "paired": False,
                            "trusted": False,
                            "connected": False,
                            "pan_active": False,
                            "interface": None,
                            "ip_address": None,
                            "default_route_interface": None,
                        }
                    )

            if clean_path == "test-internet":
                result = self._test_internet_connectivity()
                return jsonify(result)

            return "Not Found", 404
        except Exception as e:
            logging.error(f"[bt-tether-helper] Webhook error: {e}")
            return "Error", 500

    def _validate_mac(self, mac):
        """Validate MAC address format"""

        return bool(self.MAC_VALIDATE_PATTERN.match(mac))

    def _disconnect_device(self, mac):
        """Disconnect from a Bluetooth device and remove trust to prevent auto-reconnect"""
        try:
            # Update cached UI FIRST to immediately clear any lingering status messages
            # This must happen before setting flags to ensure UI shows clean disconnecting state
            self._update_cached_ui_status(
                status=self.STATUS_UNTRUSTED_DISCONNECTED,
                mac=mac,
            )

            # Set flags to stop auto-reconnect and indicate disconnecting state
            with self.lock:
                self._user_requested_disconnect = True
                # Don't set _connection_in_progress during disconnect - causes "Connecting" to show
                self._disconnecting = True  # Set disconnecting flag for UI
                self._disconnect_start_time = time.time()  # Track disconnect start time
                self._initializing = False  # Clear initializing flag
                self.status = self.STATE_DISCONNECTING  # Set status for consistency
                self.message = f"Disconnecting from device..."
                self._screen_needs_refresh = (
                    True  # Force screen update to show disconnecting
                )

            # Force immediate screen update to clear any lingering messages
            if self._ui_reference:
                try:
                    self.on_ui_update(self._ui_reference)
                except Exception as e:
                    logging.debug(
                        f"[bt-tether-helper] Error forcing UI update at disconnect start: {e}"
                    )

            # Wait briefly for any ongoing reconnect to complete
            time.sleep(0.5)

            self._log("INFO", f"Disconnecting from device {mac}...")

            # Release dhcpcd BEFORE tearing down the bridge — prevents stale
            # daemon from interfering with future connections
            try:
                subprocess.run(
                    ["dhcpcd", "--release", "bnep0"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=3,
                )
            except Exception:
                pass
            try:
                subprocess.run(
                    ["pkill", "-f", "dhcpcd.*bnep"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=3,
                )
            except Exception:
                pass

            # Disconnect NAP via Network1 (proper BlueZ path) or
            # DisconnectProfile as fallback
            try:
                import dbus

                bus = dbus.SystemBus()
                manager = dbus.Interface(
                    bus.get_object("org.bluez", "/"),
                    "org.freedesktop.DBus.ObjectManager",
                )
                objects = manager.GetManagedObjects()
                device_path = None
                has_network1 = False
                for path, interfaces in objects.items():
                    if "org.bluez.Device1" in interfaces:
                        props = interfaces["org.bluez.Device1"]
                        if props.get("Address") == mac:
                            device_path = path
                            has_network1 = "org.bluez.Network1" in interfaces
                            break

                if device_path:
                    nap_disconnected = False
                    # Try Network1.Disconnect first — proper BNEP bridge teardown
                    if has_network1:
                        try:
                            self._log("INFO", "Disconnecting NAP via Network1...")
                            net_iface = dbus.Interface(
                                bus.get_object("org.bluez", device_path),
                                "org.bluez.Network1",
                            )
                            net_iface.Disconnect()
                            nap_disconnected = True
                            time.sleep(self.DEVICE_OPERATION_DELAY)
                            self._log("INFO", "NAP disconnected via Network1")
                        except Exception as e:
                            logging.debug(
                                f"[bt-tether-helper] Network1.Disconnect: {e}"
                            )
                    # Fallback to DisconnectProfile if Network1 failed or unavailable
                    if not nap_disconnected:
                        try:
                            self._log("INFO", "Disconnecting NAP profile...")
                            device = dbus.Interface(
                                bus.get_object("org.bluez", device_path),
                                "org.bluez.Device1",
                            )
                            device.DisconnectProfile(self.NAP_UUID)
                            time.sleep(self.DEVICE_OPERATION_DELAY)
                            self._log("INFO", "NAP profile disconnected")
                        except Exception as e:
                            logging.debug(f"[bt-tether-helper] NAP disconnect: {e}")
            except Exception as e:
                logging.debug(f"[bt-tether-helper] DBus operation: {e}")

            # Disconnect the Bluetooth connection
            self._log("INFO", "Disconnecting Bluetooth...")
            result = self._run_cmd(["bluetoothctl", "disconnect", mac], capture=True)
            self._log("INFO", f"Disconnect result: {result}")
            time.sleep(self.DEVICE_OPERATION_LONGER_DELAY)

            self._log("INFO", "Removing trust to prevent auto-reconnect...")

            self._update_cached_ui_status(
                status=self.STATUS_UNTRUSTED_DISCONNECTED,
                mac=mac,
            )

            trust_result = self._run_cmd(["bluetoothctl", "untrust", mac], capture=True)
            self._log("INFO", f"Untrust result: {trust_result}")
            time.sleep(self.DEVICE_OPERATION_DELAY)

            with self.lock:
                # Keep disconnecting state throughout - don't switch states
                self._disconnect_start_time = time.time()
                self.message = f"Finalizing disconnect..."
                self._screen_needs_refresh = True

            # Block the device BEFORE removing it to prevent reconnection attempts
            self._log("INFO", "Blocking device to prevent reconnection...")
            block_result = self._run_cmd(["bluetoothctl", "block", mac], capture=True)
            self._log("INFO", f"Block result: {block_result}")
            time.sleep(self.DEVICE_OPERATION_DELAY)

            # Unpair (remove) the device completely
            self._log("INFO", "Removing device to unpair...")
            remove_result = self._run_cmd(["bluetoothctl", "remove", mac], capture=True)
            self._log("INFO", f"Remove result: {remove_result}")
            time.sleep(
                self.DEVICE_OPERATION_LONGER_DELAY
            )  # Wait longer for changes to propagate

            self._log(
                "INFO", f"Device {mac} disconnected, blocked and removed successfully"
            )

            # Update cached UI status to disconnected state FIRST
            self._update_cached_ui_status(status=self.STATUS_FULLY_DISCONNECTED)

            # Then update internal state - CRITICAL: Clear flags BEFORE returning
            with self.lock:
                self.status = self.STATE_DISCONNECTED
                self.message = "No device"  # Show "No device" when fully disconnected
                self._disconnecting = False  # Clear disconnecting flag BEFORE returning
                self._disconnect_start_time = None
                self._last_known_connected = False
                # Clear phone_mac so monitor doesn't try to reconnect
                self.phone_mac = None
                # Clear passkey after disconnect
                self.current_passkey = None
                self._screen_needs_refresh = True

            # Force immediate screen update to show fully disconnected state
            if self._ui_reference:
                try:
                    self.on_ui_update(self._ui_reference)
                except Exception as e:
                    logging.debug(
                        f"[bt-tether-helper] Error forcing UI update on disconnected: {e}"
                    )

            # Small delay to ensure flag change propagates before frontend polls
            time.sleep(0.1)

            # Return success - flag is already cleared above
            return {
                "success": True,
                "message": f"Device {mac} disconnected, unpaired, and blocked",
            }
        except Exception as e:
            self._log("ERROR", f"Disconnect error: {e}")
            # Update cached UI status to show error FIRST
            self._update_cached_ui_status()

            with self.lock:
                self.status = self.STATE_ERROR
                self.message = f"Disconnect failed: {str(e)[:50]}"
                self._initializing = False  # Clear initializing flag
                self._screen_needs_refresh = True
            return {"success": False, "message": f"Disconnect failed: {str(e)}"}
        finally:
            # Always clear the flags, even if disconnect fails
            with self.lock:
                self._disconnecting = False
                self._disconnect_start_time = None
                # Reset device rotation for next reconnection cycle
                self._device_rotation_list = []
                self._devices_tried_in_cycle = set()
                self._untrusting = False
                self._untrust_start_time = None

    def _unpair_device(self, mac):
        """Unpair a Bluetooth device"""
        try:
            # Invalidate status cache before unpair

            self._log("INFO", f"Unpairing device {mac}...")
            result = self._run_cmd(
                ["bluetoothctl", "remove", mac], capture=True, timeout=10
            )

            if result == "Timeout":
                self._log("WARNING", "Unpair command timed out")
                # Still consider it successful - device is likely already gone
                return {
                    "success": True,
                    "message": "Device was already unpaired or removed",
                }
            elif result and "Device has been removed" in result:
                self._log("INFO", f"Device {mac} unpaired successfully")

                # Update internal state
                with self.lock:
                    self.status = self.STATE_DISCONNECTED
                    self.message = "Device unpaired"
                    self._last_known_connected = False
                    # Clear passkey after unpair
                    self.current_passkey = None
                    self._screen_needs_refresh = True

                # Update cached UI status
                self._update_cached_ui_status()

                return {
                    "success": True,
                    "message": f"Device {mac} unpaired successfully",
                }
            elif result and (
                "not available" in result or "not found" in result.lower()
            ):
                self._log("INFO", f"Device {mac} was already removed")
                return {
                    "success": True,
                    "message": f"Device {mac} was already unpaired",
                }
            else:
                self._log("WARNING", f"Unpair result: {result}")
                return {"success": True, "message": f"Unpair command sent: {result}"}
        except Exception as e:
            self._log("ERROR", f"Unpair error: {e}")
            return {"success": False, "message": f"Unpair failed: {str(e)}"}

    def _check_pair_status(self, mac):
        """Check if a device is already paired"""
        try:
            info = self._run_cmd(["bluetoothctl", "info", mac], capture=True)
            if not info or "Device" not in info:
                return {"paired": False, "trusted": False, "connected": False}

            paired = "Paired: yes" in info
            connected = "Connected: yes" in info
            trusted = "Trusted: yes" in info

            logging.debug(
                f"[bt-tether-helper] Device {mac} - Paired: {paired}, Trusted: {trusted}, Connected: {connected}"
            )
            return {"paired": paired, "trusted": trusted, "connected": connected}
        except Exception as e:
            self._log("ERROR", f"Pair status check error: {e}")
            return {"paired": False, "trusted": False, "connected": False}

    def _get_current_status(self, mac):
        """Get current connection status - no cache, direct check"""
        try:
            # Quick check: look for active bnep interface first (fastest indicator)
            try:
                # Check for bnep interface directly
                pan_result = subprocess.run(
                    ["ip", "link", "show"], capture_output=True, text=True, timeout=2
                )
                if pan_result.returncode == 0 and "bnep" in pan_result.stdout:
                    # Check if bnep interface has an IP address
                    try:
                        ip_result = subprocess.run(
                            ["ip", "addr", "show", "bnep0"],
                            capture_output=True,
                            text=True,
                            timeout=2,
                        )
                        if ip_result.returncode == 0 and "inet " in ip_result.stdout:
                            # Extract IP address from the output - simplified parsing
                            ip_address = None
                            for line in ip_result.stdout.split("\n"):
                                if "inet " in line and not "127.0.0.1" in line:
                                    # Find the IP address in format "inet x.x.x.x/xx"
                                    parts = line.strip().split()
                                    for part in parts:
                                        if part.startswith("inet"):
                                            continue
                                        if "/" in part and "." in part:
                                            ip_address = part.split("/")[0]
                                            break
                                    if ip_address:
                                        break

                            # Skip IPv4LL (169.254.x.x) — this means DHCP failed
                            # and the device is NOT actually providing internet
                            if ip_address and ip_address.startswith("169.254."):
                                logging.debug(
                                    f"[bt-tether-helper] bnep0 has IPv4LL ({ip_address}) — not a real connection"
                                )
                            elif ip_address:
                                # PAN interface exists and has a real IP
                                return {
                                    "paired": True,
                                    "trusted": True,
                                    "connected": True,
                                    "pan_active": True,
                                    "interface": "bnep0",
                                    "ip_address": ip_address,
                                }
                    except Exception as ip_err:
                        logging.debug(f"[bt-tether-helper] IP check failed: {ip_err}")
            except Exception as bnep_err:
                logging.debug(f"[bt-tether-helper] bnep check failed: {bnep_err}")

            # Quick bluetoothctl check with minimal timeout
            try:
                result = subprocess.run(
                    ["bluetoothctl", "info", mac],
                    capture_output=True,
                    text=True,
                    timeout=3,
                )

                if result.returncode == 0 and result.stdout:
                    info = result.stdout
                    paired = "Paired: yes" in info
                    connected = "Connected: yes" in info
                    trusted = "Trusted: yes" in info

                    return {
                        "paired": paired,
                        "trusted": trusted,
                        "connected": connected,
                        "pan_active": False,  # Already checked above
                        "interface": None,
                        "ip_address": None,
                    }
            except Exception as bt_err:
                logging.debug(f"[bt-tether-helper] bluetoothctl check failed: {bt_err}")

            # Fallback to disconnected if all checks fail
            return {
                "paired": False,
                "trusted": False,
                "connected": False,
                "pan_active": False,
                "interface": None,
                "ip_address": None,
            }

        except Exception as e:
            logging.debug(f"[bt-tether-helper] Status check error: {e}")
            return {
                "paired": False,
                "trusted": False,
                "connected": False,
                "pan_active": False,
                "interface": None,
                "ip_address": None,
            }

    def _get_full_connection_status(self, mac):
        """Get complete connection status for web UI - includes additional fields"""
        # Get base status
        status = self._get_current_status(mac)

        # Add default_route_interface for web UI display
        try:
            status["default_route_interface"] = self._get_default_route_interface()
        except Exception as e:
            logging.debug(
                f"[bt-tether-helper] Failed to get default route interface: {e}"
            )
            status["default_route_interface"] = None

        return status

    def _get_trusted_devices(self):
        """Get list of all trusted Bluetooth devices with their info"""
        try:
            trusted_devices = []

            # Get current active connection MAC to determine which device is truly connected
            active_mac = None
            if self._pan_active():
                active_mac = self.phone_mac

            # Get list of all paired devices
            devices_output = self._run_cmd(
                ["bluetoothctl", "devices", "Paired"], capture=True, timeout=10
            )

            if not devices_output or devices_output == "Timeout":
                return trusted_devices

            # Check each device for trust status and get detailed info
            for line in devices_output.split("\n"):
                if line.strip() and line.startswith("Device"):
                    parts = line.strip().split(" ", 2)
                    if len(parts) >= 2:
                        mac = parts[1]
                        name = parts[2] if len(parts) > 2 else "Unknown Device"

                        # Get device info to check trust status and capabilities
                        info = self._run_cmd(
                            ["bluetoothctl", "info", mac], capture=True, timeout=5
                        )
                        if info and "Trusted: yes" in info:
                            # Only mark as "connected" if this is the device with active internet
                            # (not just Bluetooth connected, but actually providing internet)
                            is_bt_connected = "Connected: yes" in info
                            is_active_connection = (
                                active_mac and mac.upper() == active_mac.upper()
                            )

                            # Parse additional device info
                            device_info = {
                                "mac": mac,
                                "name": name,
                                "trusted": True,
                                "paired": "Paired: yes" in info,
                                "connected": is_active_connection,  # Only true if providing internet
                                "bt_connected": is_bt_connected,  # Bluetooth connection status
                                "has_nap": self.NAP_UUID in info,  # NAP UUID
                            }
                            trusted_devices.append(device_info)

            return trusted_devices

        except Exception as e:
            self._log("ERROR", f"Failed to get trusted devices: {e}")
            return []

    def _find_best_device_to_connect(self, log_results=True):
        """Find the best device to connect to (prioritizes last connected, then trusted devices)

        Args:
            log_results: Whether to log the results (default True, set False to reduce spam)
        """
        try:
            trusted_devices = self._get_trusted_devices()
            nap_devices = [d for d in trusted_devices if d["has_nap"]]

            if nap_devices:
                if log_results:
                    self._log(
                        "INFO",
                        f"Found {len(nap_devices)} trusted device(s) with tethering capability",
                    )

                # Filter out DHCP-failed devices (with cooldown expiry)
                now = time.time()
                active_nap_devices = []
                for d in nap_devices:
                    fail_time = self._dhcp_failed_macs.get(d["mac"].upper())
                    if fail_time and (now - fail_time) < self.DHCP_FAILURE_COOLDOWN:
                        if log_results:
                            remaining = int(
                                self.DHCP_FAILURE_COOLDOWN - (now - fail_time)
                            )
                            self._log(
                                "DEBUG",
                                f"Skipping {d['name']} — DHCP failed {int(now - fail_time)}s ago (cooldown: {remaining}s left)",
                            )
                        continue
                    else:
                        # Cooldown expired — remove from failed set
                        if fail_time:
                            del self._dhcp_failed_macs[d["mac"].upper()]
                        active_nap_devices.append(d)

                # If all devices are DHCP-failed, fall back to full list
                # (better to retry than do nothing)
                if not active_nap_devices:
                    if log_results:
                        self._log(
                            "WARNING",
                            "All devices DHCP-failed — retrying all (cooldowns cleared)",
                        )
                    self._dhcp_failed_macs.clear()
                    active_nap_devices = nap_devices

                nap_devices = active_nap_devices

                # Priority 1: Explicitly configured phone_mac (set by UI switch)
                # This represents the user's intent and takes top priority.
                if self.phone_mac:
                    for device in nap_devices:
                        if device["mac"].upper() == self.phone_mac.upper():
                            if log_results:
                                self._log(
                                    "INFO",
                                    f"Using configured device: {device['name']} ({device['mac']})",
                                )
                            return device

                # Priority 2: Currently connected device (unless we're switching)
                if not self._switching_in_progress:
                    connected_devices = [d for d in nap_devices if d["connected"]]
                    if connected_devices:
                        device = connected_devices[0]
                        if log_results:
                            self._log(
                                "INFO",
                                f"Using already connected device: {device['name']} ({device['mac']})",
                            )
                        return device

                # Priority 3: Last successfully connected device (by name, then MAC)
                if self._last_connected_name:
                    for device in nap_devices:
                        if device["name"].lower() == self._last_connected_name.lower():
                            if log_results:
                                self._log(
                                    "INFO",
                                    f"Using last connected device (by name): {device['name']} ({device['mac']})",
                                )
                            return device

                # Fallback: Try to match by MAC if device name wasn't found
                if self._last_connected_mac:
                    for device in nap_devices:
                        if device["mac"].upper() == self._last_connected_mac.upper():
                            if log_results:
                                self._log(
                                    "INFO",
                                    f"Using last connected device (by MAC): {device['name']} ({device['mac']})",
                                )
                            return device

                # Priority 4: First available device
                device = nap_devices[0]
                if log_results:
                    self._log(
                        "INFO",
                        f"Auto-selected device: {device['name']} ({device['mac']})",
                    )
                return device

            if log_results:
                self._log(
                    "WARNING",
                    "No trusted devices with tethering capability found",
                )
            return None

        except Exception as e:
            self._log("ERROR", f"Failed to find best device: {e}")
            return None

    def _scan_devices(self):
        """Scan for Bluetooth devices using interactive bluetoothctl session"""
        try:
            logging.info("[bt-tether-helper] Starting device scan...")

            # Reset stop flag at start of new scan
            self._stop_scan = False

            self._log("INFO", "Starting scan...")
            self._log("INFO", f"Scanning for {self.SCAN_DURATION} seconds...")

            discovered_devices = {}
            device_types = {}  # Track whether each device is NEW or CHG

            # Pre-populate with cached paired devices so they appear immediately in the UI
            self._log("DEBUG", "Loading existing paired devices...")
            try:
                paired_output = self._run_cmd(
                    ["bluetoothctl", "devices", "Paired"], capture=True, timeout=5
                )
                if paired_output and paired_output != "Timeout":
                    for line in paired_output.split("\n"):
                        if line.strip() and line.startswith("Device"):
                            parts = line.strip().split(" ", 2)
                            if len(parts) >= 3:
                                mac = parts[1].upper()
                                name = parts[2]
                                if mac not in discovered_devices:
                                    discovered_devices[mac] = name
                                    device_types[mac] = "PAIRED"
                                    self._log(
                                        "DEBUG",
                                        f"Pre-loaded cached device: {name} ({mac})",
                                    )
            except Exception as e:
                logging.debug(
                    f"[bt-tether-helper] Error pre-loading paired devices: {e}"
                )

            # Update _discovered_devices with cached devices
            with self.lock:
                self._discovered_devices = {
                    mac: {
                        "mac": mac,
                        "name": discovered_devices[mac],
                        "type": device_types.get(mac, "UNKNOWN"),
                    }
                    for mac in discovered_devices
                }
            lines_read = 0

            try:
                # Use bluetoothctl in interactive mode to capture scan output
                # This is the only reliable way to get real-time device discovery events
                self._log("DEBUG", "Starting Bluetooth device scan...")

                # Ensure Bluetooth is powered on
                self._log("DEBUG", "Ensuring Bluetooth is powered on...")
                self._run_cmd(["bluetoothctl", "power", "on"], timeout=5)
                time.sleep(0.5)

                mac_pattern = self.SCAN_MAC_PATTERN
                ansi_pattern = self.SCAN_ANSI_PATTERN

                self._log("DEBUG", "Starting bluetoothctl in interactive mode...")
                scan_start = time.time()
                scan_process = None

                try:
                    # Start bluetoothctl in interactive mode with scan on command
                    # This requires sending stdin to keep the process alive
                    # Use TERM=dumb to disable colors and special formatting
                    env = dict(os.environ)
                    env["TERM"] = "dumb"

                    scan_process = subprocess.Popen(
                        ["bluetoothctl"],
                        stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        bufsize=1,  # Line buffered
                        env=env,
                    )

                    # Send scan on command to start scanning
                    # Note: No need for scan off - already cleaned up during initialization
                    scan_process.stdin.write("scan on\n")
                    scan_process.stdin.flush()

                except Exception as e:
                    self._log("ERROR", f"Failed to start scan: {e}")
                    scan_process = None

                if scan_process:
                    # Let scan run for specified duration, reading output
                    self._log("DEBUG", f"Scanning for {self.SCAN_DURATION} seconds...")
                    self._log("DEBUG", f"Process started, PID: {scan_process.pid}")
                    scan_end_time = time.time() + self.SCAN_DURATION

                    try:
                        while time.time() < scan_end_time and not self._stop_scan:
                            # Try to read output with select timeout
                            try:
                                import select

                                ready = select.select(
                                    [scan_process.stdout], [], [], 0.5
                                )
                                if ready[0]:
                                    line = scan_process.stdout.readline()
                                    if not line:
                                        break

                                    line = line.strip()
                                    if not line:
                                        continue

                                    lines_read += 1

                                    # Strip ANSI codes only for pattern matching
                                    clean_line = ansi_pattern.sub("", line)

                                    # Parse discovery events: "[NEW] Device MAC Name"
                                    if "[NEW]" in clean_line and "Device" in clean_line:
                                        mac_match = mac_pattern.search(clean_line)
                                        if mac_match:
                                            mac = mac_match.group(1).upper()

                                            # Extract device name (everything after the MAC)
                                            remainder = clean_line[
                                                mac_match.end() :
                                            ].strip()
                                            name = (
                                                remainder if remainder else "(unnamed)"
                                            )

                                            if mac not in discovered_devices:
                                                discovered_devices[mac] = name
                                                device_types[mac] = "NEW"

                                                # Log compact format
                                                self._log(
                                                    "INFO",
                                                    f"[NEW] {name} ({mac})",
                                                )

                                                # Add to persistent list for pairing
                                                with self.lock:
                                                    self._discovered_devices[mac] = {
                                                        "mac": mac,
                                                        "name": name,
                                                        "type": device_types[mac],
                                                    }
                            except select.error:
                                # Timeout or error, continue
                                pass
                    finally:
                        # Stop scan and close bluetoothctl
                        self._log("DEBUG", "Stopping scan...")
                        try:
                            # Force stop discovery via a fresh bluetoothctl call
                            # (the scan process might be broken)
                            logging.info(
                                "[bt-tether-helper] Force stopping discovery via fresh call"
                            )
                            try:
                                self._run_cmd(
                                    ["bluetoothctl", "scan", "off"], timeout=3
                                )
                            except:
                                pass

                            time.sleep(0.5)

                            # Now kill the scan process
                            scan_process.stdin.write("quit\n")
                            scan_process.stdin.flush()

                            try:
                                scan_process.wait(timeout=2)
                                logging.info(
                                    "[bt-tether-helper] Bluetoothctl process exited cleanly"
                                )
                            except subprocess.TimeoutExpired:
                                # Force kill if quit doesn't work
                                logging.info(
                                    "[bt-tether-helper] Force killing bluetoothctl after timeout"
                                )
                                scan_process.kill()
                                scan_process.wait(timeout=1)
                        except Exception as e:
                            logging.debug(
                                f"[bt-tether-helper] Error stopping scan: {e}"
                            )
                            # Force cleanup even if there's an error
                            try:
                                scan_process.kill()
                            except:
                                pass

                elapsed = time.time() - scan_start
                self._log(
                    "INFO",
                    f"Scan completed in {elapsed:.1f}s, found {len(discovered_devices)} NEW devices",
                )

            except Exception as e:
                self._log("ERROR", f"Error during scan: {e}")
                logging.exception("[bt-tether-helper] Scan exception:")

            # Also add any existing paired devices to the discovered list (they won't show as NEW/CHG)
            # Note: Paired devices are now pre-loaded at the beginning of the scan, so they're
            # available to users immediately without waiting for the full scan to complete.
            # This code is kept for safety in case any devices were paired during the scan itself.
            self._log("DEBUG", "Checking for any newly paired devices...")
            try:
                paired_output = self._run_cmd(
                    ["bluetoothctl", "devices", "Paired"], capture=True, timeout=5
                )
                if paired_output and paired_output != "Timeout":
                    for line in paired_output.split("\n"):
                        if line.strip() and line.startswith("Device"):
                            parts = line.strip().split(" ", 2)
                            if len(parts) >= 3:
                                mac = parts[1].upper()
                                name = parts[2]
                                # Only add if not already discovered during active scan
                                if mac not in discovered_devices:
                                    discovered_devices[mac] = name
                                    device_types[mac] = "PAIRED"
                                    with self.lock:
                                        self._discovered_devices[mac] = {
                                            "mac": mac,
                                            "name": name,
                                            "type": "PAIRED",
                                        }
                                    self._log(
                                        "INFO",
                                        f"Found device paired during scan: {name} ({mac})",
                                    )
            except Exception as e:
                logging.debug(
                    f"[bt-tether-helper] Error checking for newly paired devices: {e}"
                )

            # Convert to list format
            devices = [
                {
                    "mac": mac,
                    "name": discovered_devices[mac],
                    "type": device_types.get(mac, "UNKNOWN"),
                }
                for mac in discovered_devices
            ]

            logging.info(
                f"[bt-tether-helper] Scan complete. Found {len(devices)} devices"
            )

            # Log all discovered devices
            if len(devices) > 0:
                self._log("INFO", f"=== Discovered {len(devices)} device(s) ===")
                for i, device in enumerate(devices, 1):
                    self._log("INFO", f"  [{i}] {device['name']} ({device['mac']})")
            else:
                self._log("WARNING", "No devices found during scan")
                self._log("WARNING", "Ensure phone Bluetooth is ON and discoverable")

            return devices

        except Exception as e:
            self._log("ERROR", f"Scan error: {e}")
            logging.exception("[bt-tether-helper] Scan exception:")
            return []

    def start_connection(self):
        # Find best device OUTSIDE the lock — _find_best_device_to_connect() does
        # blocking I/O (bluetoothctl calls) which would hold the lock for 10+ seconds
        # and freeze UI updates + webhooks.
        best_device = self._find_best_device_to_connect()

        with self.lock:
            if not best_device:
                self.status = self.STATE_ERROR
                self.message = "No trusted devices found - scan and pair a device first"
                self._screen_needs_refresh = True
                return

            # Update current target MAC
            self.phone_mac = best_device["mac"]

            # Check if connection is already in progress (prevents multiple threads)
            if self._connection_in_progress:
                self._log(
                    "WARNING",
                    "Connection already in progress, ignoring duplicate request",
                )
                self.message = "Connection already in progress"
                self._screen_needs_refresh = True
                return

            if self.status in [self.STATE_PAIRING, self.STATE_CONNECTING]:
                self._log(
                    "WARNING", "Already pairing/connecting, ignoring duplicate request"
                )
                self.message = "Connection already in progress"
                self._screen_needs_refresh = True
                return

            # Set flag INSIDE the lock to prevent race condition
            self._connection_in_progress = True
            self._connection_start_time = time.time()
            self._user_requested_disconnect = False
            self.status = self.STATE_CONNECTING
            self.message = f"Connecting to {best_device['name']}..."

        # Update cached UI status immediately so screen shows connecting state
        # Use current status - device may be paired/trusted from before
        self._update_cached_ui_status(mac=best_device["mac"])

        # Reset failure counter on manual reconnect
        self._reconnect_failure_count = 0

        # Unpause monitor since we have a device to monitor
        self._monitor_paused.clear()

        # Pass device info to connection thread
        threading.Thread(
            target=self._connect_thread, args=(best_device,), daemon=True
        ).start()

    def _connect_thread(self, target_device):
        """Full automatic connection thread with pairing and connection logic"""
        try:
            mac = target_device["mac"]
            device_name = target_device["name"]
            self._log("INFO", f"Starting connection to {device_name} ({mac})...")

            # --- Disconnect any currently-connected device that isn't the target ---
            # The RPi Zero W2 BT adapter can only maintain one PAN link at a time.
            # If we don't tear down the existing connection first, pairing/connect
            # to the new device will fail with ConnectionAttemptFailed (status 0x04).
            currently_connected_mac = self._last_connected_mac
            if (
                currently_connected_mac
                and currently_connected_mac.upper() != mac.upper()
            ):
                # Verify the old device is actually still connected
                old_status = self._check_pair_status(currently_connected_mac)
                if old_status.get("connected"):
                    self._log(
                        "INFO",
                        f"Disconnecting current device {currently_connected_mac} before switching to {device_name}...",
                    )
                    with self.lock:
                        self.message = f"Disconnecting current device..."
                        self._screen_needs_refresh = True

                    # Full bridge cleanup: tries Network1.Disconnect() first (clean),
                    # then falls back to DisconnectProfile/Device1.Disconnect/
                    # bluetoothctl/ip-link if bnep0 persists.
                    self._cleanup_bnep_bridge(mac=currently_connected_mac)

                    self._log(
                        "INFO",
                        f"Previous device disconnected, proceeding with {device_name}",
                    )
                    time.sleep(0.5)  # Brief settle time for the BT adapter

            # Check if Bluetooth is responsive, restart if needed
            if not self._check_bluetooth_ready(timeout=5):
                self._log(
                    "WARNING",
                    "Bluetooth not ready, attempting restart...",
                )
                if not self._restart_bluetooth_safe(max_attempts=2):
                    self._log(
                        "ERROR",
                        "Bluetooth service is unresponsive and couldn't be restarted",
                    )
                    with self.lock:
                        self.status = self.STATE_ERROR
                        self.message = "Bluetooth service unresponsive. Try: sudo systemctl restart bluetooth"
                        self._connection_in_progress = False
                    return

            # Make Pwnagotchi discoverable and pairable
            self._log("INFO", f"Making Pwnagotchi discoverable...")
            with self.lock:
                self.message = f"Making Pwnagotchi discoverable for {device_name}..."
                self._screen_needs_refresh = True
            self._run_cmd(["bluetoothctl", "discoverable", "on"], capture=True)
            self._run_cmd(["bluetoothctl", "pairable", "on"], capture=True)
            time.sleep(self.DEVICE_OPERATION_LONGER_DELAY)

            # First check current pairing status
            with self.lock:
                self.message = f"Checking pairing status with {device_name}..."
                self._screen_needs_refresh = True
            pair_status = self._check_pair_status(mac)

            # If device is not trusted/paired, we need to pair first
            if not pair_status["paired"]:
                # Not paired - proceed directly to pairing
                # Don't remove the device unless it's in a bad state, just pair it
                self._log(
                    "INFO",
                    f"Device not paired. Preparing to pair with {device_name}...",
                )
                with self.lock:
                    self.message = f"Preparing to pair with {device_name}..."
                    self._screen_needs_refresh = True

                self._log("INFO", f"Unblocking {device_name} in case it was blocked...")
                with self.lock:
                    self.message = f"Unblocking {device_name}..."
                    self._screen_needs_refresh = True
                self._run_cmd(["bluetoothctl", "unblock", mac], capture=True)
                time.sleep(self.DEVICE_OPERATION_DELAY)

                # Start pairing process - set PAIRING state
                self._log(
                    "INFO",
                    f"Device not paired. Starting pairing process with {device_name}...",
                )
                with self.lock:
                    self.status = self.STATE_PAIRING
                    self.message = f"Pairing with {device_name}..."
                    self._screen_needs_refresh = True

                # Brief delay to ensure PAIRING state is displayed
                time.sleep(0.5)

                # Attempt pairing - this will show dialog on phone
                if not self._pair_device_interactive(mac):
                    self._log("ERROR", f"Pairing with {device_name} failed!")
                    with self.lock:
                        self.status = self.STATE_ERROR
                        self.message = f"Pairing with {device_name} failed. Did you accept the dialog?"
                        self._connection_in_progress = False
                        self._stop_scan = False  # Re-enable scanning on pairing failure
                        self._screen_needs_refresh = True
                    # Force immediate screen update to show error state
                    if self._ui_reference:
                        try:
                            self.on_ui_update(self._ui_reference)
                        except Exception as e:
                            logging.debug(
                                f"[bt-tether-helper] Error forcing UI update on pairing error: {e}"
                            )
                    return

                self._log("INFO", f"Pairing with {device_name} successful!")

                # Check if device is already trusted, if not then mark as trusted
                device_info = self._run_cmd(
                    ["bluetoothctl", "info", mac], capture=True, timeout=5
                )
                if device_info and "Trusted: yes" not in device_info:
                    self._log("INFO", f"Marking {device_name} as trusted...")
                    self._run_cmd(
                        ["bluetoothctl", "trust", mac], capture=True, timeout=5
                    )
                else:
                    self._log("INFO", f"Device {device_name} is already trusted")
            else:
                self._log("INFO", f"Device {device_name} already paired")

                # Check trust status FIRST before doing any connection tests
                # This avoids unnecessary re-pairing if device just needs trust
                device_info = self._run_cmd(
                    ["bluetoothctl", "info", mac], capture=True, timeout=5
                )
                is_trusted = device_info and "Trusted: yes" in device_info

                if not device_info:
                    self._log(
                        "WARNING",
                        f"Could not retrieve device info for {device_name}, assuming not trusted",
                    )

                if is_trusted:
                    self._log(
                        "INFO", f"Device {device_name} is already paired and trusted"
                    )
                else:
                    # Device is paired but not trusted - just trust it without re-pairing
                    self._log(
                        "INFO",
                        f"Device {device_name} is paired but not trusted - marking as trusted...",
                    )

                    # Just mark it as trusted, don't re-pair
                    self._run_cmd(
                        ["bluetoothctl", "trust", mac], capture=True, timeout=5
                    )
                    time.sleep(0.5)

                    # Verify it's now trusted
                    device_info = self._run_cmd(
                        ["bluetoothctl", "info", mac], capture=True, timeout=5
                    )
                    if device_info and "Trusted: yes" in device_info:
                        self._log("INFO", f"✓ Device {device_name} is now trusted")
                    else:
                        self._log(
                            "WARNING",
                            f"Could not verify trust status for {device_name}",
                        )

                # If we get here, device is already paired and trusted
                with self.lock:
                    self.message = f"Device {device_name} ready ✓"
                    self._screen_needs_refresh = True

            # Wait for phone to be ready after pairing/trust
            logging.info(f"[bt-tether-helper] Waiting for {device_name} to be ready...")
            with self.lock:
                self.message = f"Waiting for {device_name} to be ready..."
                self._screen_needs_refresh = True
            time.sleep(self.PHONE_READY_WAIT)

            # Proceed to NAP connection
            # Note: Skip bluetoothctl connect here - DBus NAP will handle Bluetooth connection
            # and doing bluetoothctl connect can leave the stack in "br-connection-busy" state
            self._log("INFO", "Connecting to NAP profile...")
            with self.lock:
                self.status = self.STATE_CONNECTING
                self.message = "Connecting to NAP profile for internet..."
                self._screen_needs_refresh = True

            # State update is asynchronous, no need to sleep for display

            # Try to establish PAN connection
            self._log("INFO", "Establishing PAN connection...")
            with self.lock:
                self.status = self.STATE_CONNECTING
                self.message = "Connecting to NAP profile for internet..."
                self._screen_needs_refresh = True

            # Try DBus connection to NAP profile (with retry for br-connection-busy)
            nap_connected = False
            br_busy_count = 0
            for retry in range(self.NAP_CONNECTION_MAX_RETRIES):
                if retry > 0:
                    # Use exponential backoff for br-connection-busy errors
                    # These indicate BlueZ/kernel needs more time to clean up
                    retry_delay = self.NAP_RETRY_DELAY
                    if br_busy_count > 0:
                        retry_delay = self.NAP_RETRY_DELAY * (2 ** (br_busy_count - 1))
                        self._log(
                            "WARNING",
                            f"Connection busy {br_busy_count}x - waiting {retry_delay}s before retry",
                        )

                    self._log(
                        "INFO",
                        f"Retrying NAP connection (attempt {retry + 1}/{self.NAP_CONNECTION_MAX_RETRIES})...",
                    )
                    with self.lock:
                        self.message = f"NAP retry {retry + 1}/{self.NAP_CONNECTION_MAX_RETRIES}..."
                        self._screen_needs_refresh = True
                    time.sleep(retry_delay)

                nap_connected = self._connect_nap_dbus(mac)
                if nap_connected:
                    break
                else:
                    self._log("WARNING", f"NAP attempt {retry + 1} failed")

                    # Check if it was a br-connection-busy error
                    # These are persistent - may need to reset pairing
                    last_error = None
                    if hasattr(self, "_last_nap_error"):
                        last_error = self._last_nap_error

                    if last_error and "br-connection-busy" in last_error:
                        br_busy_count += 1

                        # Release BNEP bridge — tries Network1.Disconnect() first,
                        # falls back to aggressive cleanup if bnep0 persists.
                        self._cleanup_bnep_bridge(mac=mac)

                        if br_busy_count >= 3:
                            # Nuclear option: reset the HCI adapter to force the kernel
                            # to release all BNEP bridges.  This is the only reliable way
                            # to recover from a stuck bridge when all D-Bus calls fail.
                            self._log(
                                "WARNING",
                                "Persistent br-connection-busy — resetting BT adapter to release stuck bridge...",
                            )
                            self.reset_bt()
                            time.sleep(2)
                            # Re-start the pairing agent since reset killed it
                            self._start_pairing_agent()

                    elif last_error and (
                        "NoReply" in last_error
                        or "Did not receive a reply" in last_error
                        or "Timeout" in last_error
                    ):
                        # D-Bus timeout — BlueZ may be stuck processing the
                        # previous request.  This is the root cause of the
                        # "works after reboot, fails after a while" pattern.
                        self._log(
                            "WARNING",
                            f"D-Bus timeout detected (attempt {retry + 1}) — "
                            "checking if BlueZ is stuck...",
                        )
                        recovered = self._recover_bluez_if_stuck(mac=mac)
                        if recovered:
                            self._log(
                                "INFO",
                                "BlueZ recovered — next retry should start clean",
                            )

                    with self.lock:
                        self.message = f"NAP attempt {retry + 1}/{self.NAP_CONNECTION_MAX_RETRIES} failed..."
                        self._screen_needs_refresh = True

            if nap_connected:
                self._log("INFO", "NAP connection successful!")

                # Get PAN interface — Network1.Connect returns it directly,
                # ConnectProfile fallback needs polling
                iface = getattr(self, "_nap_interface", None)
                if iface:
                    self._log("INFO", f"✓ Network1 returned interface: {iface}")
                else:
                    # ConnectProfile was used (no Network1), poll for bnep0
                    # Use 20s timeout — after warm retry the bridge may take longer
                    self._log("INFO", "Waiting for PAN interface to appear...")
                    iface = self._wait_for_pan_interface(timeout=20)

                if iface:
                    self._log("INFO", f"✓ PAN interface active: {iface}")

                    # Wait for interface initialization
                    self._log("INFO", "Waiting for interface initialization...")
                    time.sleep(self.INTERFACE_INIT_WAIT)

                    # Wait additional time for phone to initialize tethering
                    self._log("INFO", "Waiting for phone tethering to initialize...")
                    time.sleep(self.TETHERING_INIT_WAIT)

                    # Setup network with DHCP
                    if self._setup_network_dhcp(iface):
                        self._log("INFO", "✓ Network setup successful")

                        # Ensure DNS is configured from DHCP
                        self._log("INFO", "Verifying DNS configuration...")
                        try:
                            with open("/etc/resolv.conf", "r") as f:
                                resolv_content = f.read()
                                nameservers = [
                                    line.strip()
                                    for line in resolv_content.split("\n")
                                    if line.strip().startswith("nameserver")
                                ]
                                if nameservers:
                                    self._log(
                                        "INFO",
                                        f"✓ DNS configured: {', '.join([ns.split()[1] for ns in nameservers])}",
                                    )
                                else:
                                    self._log(
                                        "WARNING",
                                        "No nameservers found in /etc/resolv.conf - DNS may not work",
                                    )
                        except Exception as e:
                            self._log("WARNING", f"Could not verify DNS config: {e}")
                    else:
                        # DHCP failed — phone's BT tethering DHCP server
                        # is not responding.  This is a known Android 16
                        # issue where the phone's tethering service gets
                        # stuck after switching devices.  The phone thinks
                        # it is still tethered but its DHCP server is dead.
                        # This is a phone-side bug — we cannot fix it from
                        # the Pi.  Tell the user to toggle tethering.
                        self._log(
                            "WARNING",
                            f"DHCP failed for {device_name} — phone's "
                            "tethering DHCP server is not responding. "
                            "This is a known Android issue after switching "
                            "devices. Please toggle Bluetooth tethering "
                            "OFF and ON on your phone, then reconnect.",
                        )

                        # Mark this device as DHCP-failed so device selection
                        # skips it and tries other trusted devices instead
                        self._dhcp_failed_macs[mac.upper()] = time.time()
                        self._log(
                            "INFO",
                            f"Marked {device_name} as DHCP-failed — will skip for {self.DHCP_FAILURE_COOLDOWN}s",
                        )

                        # Clean up the dead connection so we're in a
                        # consistent state for the next attempt
                        self._cleanup_bnep_bridge(mac=mac)

                        # Clear phone_mac so device selection doesn't
                        # immediately re-pick this failed device
                        with self.lock:
                            if self.phone_mac and self.phone_mac.upper() == mac.upper():
                                self.phone_mac = None
                            self.status = self.STATE_DISCONNECTED
                            self.message = (
                                f"DHCP fail on {device_name} — trying other devices"
                            )
                            self._connection_in_progress = False
                            self._connection_start_time = None
                            self._initializing = False
                            self._screen_needs_refresh = True

                        # Force immediate screen update
                        if self._ui_reference:
                            try:
                                self.on_ui_update(self._ui_reference)
                            except Exception as e:
                                logging.debug(
                                    f"[bt-tether-helper] Error forcing UI update on DHCP failure: {e}"
                                )

                        # Return early — no point checking internet on a dead bridge
                        return

                    # Verify internet connectivity
                    self._log("INFO", "Checking internet connectivity...")
                    with self.lock:
                        self.message = "Verifying internet connection..."
                        self._screen_needs_refresh = True

                    if self._check_internet_connectivity():
                        self._log("INFO", "✓ Internet connectivity verified!")

                        # Remember this device as last successfully connected
                        self._last_connected_mac = mac
                        # Clear DHCP failure for this device on success
                        self._dhcp_failed_macs.pop(mac.upper(), None)
                        device_info = self._run_cmd(
                            ["bluetoothctl", "info", mac], capture=True, timeout=5
                        )
                        if device_info:
                            name_match = re.search(
                                r"Name: (.+)$", device_info, re.MULTILINE
                            )
                            if name_match:
                                self._last_connected_name = name_match.group(1).strip()
                        self._save_state()

                        try:
                            current_ip = self._get_current_ip()
                            current_ipv6 = self._get_global_ipv6(iface)

                            if current_ip:
                                self._log("INFO", f"Current IPv4 address: {current_ip}")
                            if current_ipv6:
                                self._log(
                                    "INFO", f"Current IPv6 address: {current_ipv6}"
                                )

                            # Test DNS resolution if we have any IP
                            if current_ip or current_ipv6:
                                self._log("INFO", "Testing DNS resolution...")
                                try:
                                    import socket

                                    socket.gethostbyname("google.com")
                                    self._log("INFO", "✓ DNS resolution working")
                                except socket.gaierror:
                                    self._log(
                                        "WARNING",
                                        "DNS resolution failed - check /etc/resolv.conf",
                                    )
                                except Exception as dns_e:
                                    self._log("WARNING", f"DNS test error: {dns_e}")

                            # Send Discord notification (IPv4 only, maintains compatibility)
                            if current_ip and self.discord_webhook_url:
                                self._log(
                                    "INFO",
                                    "Discord webhook configured, starting notification thread...",
                                )
                                threading.Thread(
                                    target=self._send_discord_notification,
                                    args=(current_ip, device_name),
                                    daemon=True,
                                ).start()

                            if not current_ip and not current_ipv6:
                                self._log(
                                    "WARNING",
                                    "Could not get any IP address for notifications",
                                )
                        except Exception as e:
                            self._log("ERROR", f"Failed to send notifications: {e}")

                        # Update cached UI status with fresh data FIRST
                        self._update_cached_ui_status(mac=mac)

                        # Then set status and clear flags atomically
                        with self.lock:
                            self.status = self.STATE_CONNECTED
                            self.message = f"✓ Connected! Internet via {iface}"
                            self._connection_in_progress = False
                            self._connection_start_time = None
                            self._initializing = False
                            self._screen_needs_refresh = True

                        # Log for debugging
                        self._log("DEBUG", "Connection complete, flags cleared")

                        # Force immediate screen update to show IP/connected state
                        if self._ui_reference:
                            try:
                                self.on_ui_update(self._ui_reference)
                            except Exception as e:
                                logging.debug(
                                    f"[bt-tether-helper] Error forcing UI update on success: {e}"
                                )

                    else:
                        self._log("WARNING", "No internet connectivity detected")
                        # Update cached UI status FIRST
                        self._update_cached_ui_status(mac=mac)

                        with self.lock:
                            self.status = self.STATE_CONNECTED
                            self.message = (
                                f"Connected via {iface} but no internet access"
                            )
                            self._connection_in_progress = False
                            self._connection_start_time = None
                            self._initializing = False
                            self._screen_needs_refresh = True

                        # Force immediate screen update
                        if self._ui_reference:
                            try:
                                self.on_ui_update(self._ui_reference)
                            except Exception as e:
                                logging.debug(
                                    f"[bt-tether-helper] Error forcing UI update on no-internet: {e}"
                                )
                else:
                    self._log(
                        "WARNING",
                        "NAP connected but no interface detected - treating as connection failure",
                    )
                    # NAP reported success but PAN interface never appeared.
                    # This leaves a phantom bridge — clean it up to prevent
                    # br-connection-busy on the next attempt.
                    self._cleanup_bnep_bridge(mac=mac)

                    with self.lock:
                        self.status = self.STATE_DISCONNECTED
                        self.message = "NAP profile didn't create interface"
                        self._connection_in_progress = False
                        self._connection_start_time = None
                        self._initializing = False
                        self._screen_needs_refresh = True
            else:
                self._log("WARNING", "NAP connection failed")

                # Check if device is paired but potentially not properly trusted
                info = self._run_cmd(["bluetoothctl", "info", mac], capture=True)
                if info:
                    is_paired = "Paired: yes" in info
                    is_trusted = "Trusted: yes" in info
                    if is_paired and not is_trusted:
                        self._log(
                            "ERROR",
                            f"Device is paired but NOT trusted - this could cause connection failures",
                        )
                        self._log(
                            "INFO",
                            "Attempting to re-pair device for fresh authentication...",
                        )
                        # Remove and re-pair
                        self._run_cmd(["bluetoothctl", "remove", mac], capture=True)
                        time.sleep(1)
                        self._pair_device_interactive(mac)

                # Update cached UI status FIRST
                self._update_cached_ui_status(mac=mac)

                # Then clear flags so on_ui_update doesn't show connecting
                with self.lock:
                    self.status = self.STATE_CONNECTED
                    self.message = "Bluetooth connected but tethering failed. Enable tethering on phone."
                    self._connection_in_progress = False  # Clear connection flag
                    self._connection_start_time = None
                    self._initializing = False  # Clear initializing flag
                    self._screen_needs_refresh = True
                # Force immediate screen update
                if self._ui_reference:
                    try:
                        self.on_ui_update(self._ui_reference)
                    except Exception as e:
                        logging.debug(
                            f"[bt-tether-helper] Error forcing UI update on NAP failure: {e}"
                        )

        except Exception as e:
            self._log("ERROR", f"Connection thread error: {e}")
            self._log("ERROR", f"Traceback: {traceback.format_exc()}")
            # Update cached UI status to show error FIRST
            self._update_cached_ui_status()

            with self.lock:
                self.status = self.STATE_ERROR
                self.message = f"Connection error: {str(e)}"
                self._connection_in_progress = False
                self._connection_start_time = None
                self._screen_needs_refresh = True
        finally:
            # Clear the flag if not already cleared (error cases)
            # Invalidate cache first to ensure fresh status on next UI update
            with self.lock:
                if self._connection_in_progress:
                    self._connection_in_progress = False
                    self._connection_start_time = None

            # Force immediate screen update to show final state (connected or error)
            if self._ui_reference:
                try:
                    self.on_ui_update(self._ui_reference)
                except Exception as e:
                    logging.debug(
                        f"[bt-tether-helper] Error forcing UI update in finally: {e}"
                    )

    def _strip_ansi_codes(self, text):
        """Remove ANSI color/control codes from text"""
        if not text:
            return text

        # Remove ANSI escape sequences
        text = self.ANSI_ESCAPE_PATTERN.sub("", text)

        # Filter out bluetoothctl status lines ([CHG], [DEL], [NEW]) to prevent log parser errors
        # These cause pwnagotchi's log parser to throw errors like "time data 'CHG' does not match format"
        lines = text.split("\n")
        filtered_lines = []
        for line in lines:
            # Skip lines that start with bluetoothctl status markers
            stripped = line.strip()
            if not (
                stripped.startswith("[CHG]")
                or stripped.startswith("[DEL]")
                or stripped.startswith("[NEW]")
            ):
                filtered_lines.append(line)

        return "\n".join(filtered_lines)

    def _check_bluetooth_ready(self, timeout=10):
        """
        Comprehensive check if Bluetooth service is ready for operations.
        Validates: bluetoothctl responsiveness, systemd service status, and adapter availability.
        """
        start_time = time.time()
        last_error = None

        while time.time() - start_time < timeout:
            try:
                # Check 1: Can bluetoothctl respond?
                result = subprocess.run(
                    ["bluetoothctl", "show"], capture_output=True, timeout=2, text=True
                )
                if result.returncode != 0:
                    last_error = f"bluetoothctl show failed: {result.stderr}"
                    time.sleep(0.5)
                    continue

                # Check 2: Is the service running in systemd?
                result = subprocess.run(
                    ["systemctl", "is-active", "bluetooth"],
                    capture_output=True,
                    timeout=2,
                    text=True,
                )
                if "active" not in result.stdout:
                    last_error = f"Service not active: {result.stdout}"
                    time.sleep(0.5)
                    continue

                # Check 3: Can we list adapters?
                result = subprocess.run(
                    ["bluetoothctl", "list"], capture_output=True, timeout=2, text=True
                )
                if result.returncode != 0:
                    last_error = f"bluetoothctl list failed: {result.stderr}"
                    time.sleep(0.5)
                    continue

                # All checks passed
                self._log("INFO", "Bluetooth service is ready")
                return True

            except subprocess.TimeoutExpired:
                last_error = "Bluetooth command timeout"
                time.sleep(0.5)
            except Exception as e:
                last_error = str(e)
                time.sleep(0.5)

        self._log("ERROR", f"Bluetooth not ready after {timeout}s: {last_error}")
        return False

    def _check_bluez_responsive(self, timeout=5):
        """Check if the BlueZ D-Bus service is still responsive.

        After a Network1.Connect() timeout (NoReply), BlueZ can be left in a
        stuck state where subsequent D-Bus calls also hang.  This method does
        a quick GetManagedObjects() probe to detect that condition.

        Returns True if BlueZ responds within *timeout* seconds, False if it
        hangs or is unreachable.
        """
        if not DBUS_AVAILABLE:
            return True  # can't check, assume OK

        result = [None]  # mutable container for thread result

        def _probe():
            try:
                bus = dbus.SystemBus()
                manager = dbus.Interface(
                    bus.get_object("org.bluez", "/"),
                    "org.freedesktop.DBus.ObjectManager",
                )
                manager.GetManagedObjects()
                result[0] = True
            except Exception:
                result[0] = False

        t = threading.Thread(target=_probe, daemon=True)
        t.start()
        t.join(timeout=timeout)

        if t.is_alive():
            self._log(
                "WARNING",
                f"BlueZ D-Bus not responding after {timeout}s — stuck state detected",
            )
            return False
        if not result[0]:
            self._log(
                "WARNING",
                "BlueZ D-Bus probe failed — service may be crashed or unresponsive",
            )
            return False

        return True

    def _recover_bluez_if_stuck(self, mac=None):
        """Detect and recover from a stuck BlueZ/D-Bus state.

        Called after a NAP connection attempt that failed with a D-Bus timeout
        (NoReply / 'Did not receive a reply').  These timeouts leave BlueZ
        holding internal state that blocks all subsequent connection attempts
        until the service is restarted — the same thing a reboot fixes.

        Strategy:
        1. Probe BlueZ with a quick D-Bus call to confirm it is stuck.
        2. If stuck → full adapter reset (hciconfig down/up + systemctl restart).
        3. Restart the pairing agent (killed by the reset).
        4. Brief settle time before the caller retries the connection.

        Returns True if recovery was performed, False if BlueZ was healthy.
        """
        # First check: is BlueZ actually stuck?
        if self._check_bluez_responsive(timeout=5):
            # BlueZ is responding — the failure may be transient.
            # Still try a lighter cleanup: tear down any lingering BNEP bridge
            # that could cause br-connection-busy on the next attempt.
            if mac:
                try:
                    ifaces_out = subprocess.check_output(
                        ["ip", "link", "show"], text=True, timeout=5
                    )
                    if "bnep0" in ifaces_out:
                        self._log(
                            "INFO",
                            "BlueZ responsive but stale bnep0 found — cleaning up",
                        )
                        self._cleanup_bnep_bridge(mac=mac)
                except Exception:
                    pass
            return False

        # BlueZ is stuck — full reset required (same effect as a reboot)
        self._log(
            "WARNING",
            "BlueZ is unresponsive — performing full adapter reset to recover...",
        )
        self.reset_bt()
        time.sleep(2)

        # Restart the pairing agent (killed by the adapter reset)
        self._start_pairing_agent()

        # Give BlueZ a moment to finish initializing
        time.sleep(1)

        # Verify recovery
        if self._check_bluez_responsive(timeout=5):
            self._log("INFO", "✓ BlueZ recovered after adapter reset")
        else:
            self._log(
                "ERROR",
                "BlueZ still unresponsive after reset — connection will likely fail",
            )

        return True

    def reset_bt(self):
        """Reset Bluetooth adapter at hardware level (needed on Trixie)"""
        self._log("INFO", "Performing hardware-level Bluetooth reset...")
        cmds = [
            ["hciconfig", "hci0", "down"],
            ["hciconfig", "hci0", "up"],
            ["systemctl", "restart", "bluetooth"],
        ]
        for c in cmds:
            try:
                subprocess.run(
                    c, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5
                )
                time.sleep(0.5)
            except Exception as e:
                self._log("WARNING", f"Command {' '.join(c)} failed: {e}")

    def _is_bluetooth_service_active(self):
        """Check if Bluetooth service is currently active"""
        try:
            result = subprocess.run(
                ["systemctl", "is-active", "bluetooth"],
                capture_output=True,
                timeout=2,
                text=True,
            )
            return "active" in result.stdout
        except Exception as e:
            self._log("DEBUG", f"Failed to check service status: {e}")
            return False

    def _wait_for_service_state(self, target_state="active", timeout=None):
        """
        Wait for service state change using D-Bus signals (event-driven).
        Falls back to polling if D-Bus unavailable.
        target_state: 'active', 'inactive', or 'failed'
        """
        if timeout is None:
            timeout = self.BLUETOOTH_RESTART_POLL_TIMEOUT

        # Try D-Bus signal approach first (if available)
        if DBUS_AVAILABLE:
            if self._wait_for_service_state_dbus(target_state, timeout):
                return True

        # Fall back to polling if D-Bus not available or timed out
        self._log("DEBUG", f"Using polling to wait for service {target_state}")
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                result = subprocess.run(
                    ["systemctl", "is-active", "bluetooth"],
                    capture_output=True,
                    timeout=2,
                    text=True,
                )
                current_state = result.stdout.strip()
                if target_state in current_state:
                    return True
            except Exception as e:
                self._log("DEBUG", f"Service state check failed: {e}")

            time.sleep(self.BLUETOOTH_RESTART_POLL_INTERVAL)

        return False

    def _wait_for_service_state_dbus(self, target_state="active", timeout=None):
        """
        Event-driven wait for Bluetooth service state using D-Bus signals.
        Much more efficient than polling.
        """
        if timeout is None:
            timeout = self.BLUETOOTH_DBUS_SIGNAL_TIMEOUT

        try:
            import dbus
            from dbus.exceptions import DBusException

            bus = dbus.SystemBus()

            # Set up signal handlers for service state changes
            ready_event = threading.Event()

            def on_properties_changed(interface, changed, invalidated):
                """Handle D-Bus PropertyChanged signal from systemd"""
                if "ActiveState" in changed:
                    active_state = changed["ActiveState"]
                    self._log(
                        "DEBUG", f"D-Bus signal: ActiveState changed to {active_state}"
                    )
                    if target_state in str(active_state):
                        ready_event.set()

            # Subscribe to systemd service PropertyChanged signals
            bus.add_signal_receiver(
                on_properties_changed,
                dbus_interface="org.freedesktop.DBus.Properties",
                signal_name="PropertiesChanged",
                path="/org/freedesktop/systemd1/unit/bluetooth_2eservice",
                arg0="org.freedesktop.systemd1.Unit",
            )

            # Wait for signal with timeout
            if ready_event.wait(timeout):
                self._log(
                    "DEBUG", f"Service state '{target_state}' detected via D-Bus signal"
                )
                return True
            else:
                self._log("DEBUG", f"D-Bus signal timeout after {timeout}s")
                return False

        except (ImportError, DBusException, Exception) as e:
            self._log("DEBUG", f"D-Bus signal approach failed: {e}")
            return False

    def _restart_bluetooth_safe(self, max_attempts=3):
        """
        Safely initialize/restart Bluetooth service with minimal disruption.
        Strategy:
        1. Kill hanging bluetoothctl processes only (NOT bluetoothd!)
        2. Try to start the service (start is idempotent - safe if already running)
        3. Verify it's responsive
        4. Only do a full restart (stop/start) if step 2-3 fails

        This avoids unnecessary downtime if the service is already working.
        """
        for attempt in range(max_attempts):
            try:
                # Step 1: Kill hanging bluetoothctl processes ONLY
                # IMPORTANT: Do NOT kill bluetoothd - that's the Bluetooth daemon
                # Killing it breaks all Bluetooth operations including scanning!
                self._log(
                    "INFO",
                    f"Cleaning up stale bluetoothctl processes (attempt {attempt+1}/{max_attempts})...",
                )
                subprocess.run(
                    ["pkill", "-9", "bluetoothctl"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=2,
                )
                # NOTE: Removed pkill bluetoothd - this was breaking scanning!
                time.sleep(self.BLUETOOTH_RESTART_PROCESS_CLEANUP_WAIT)

                # Step 2: Try to start the service (idempotent - safe if already running)
                self._log("INFO", "Starting Bluetooth service...")
                subprocess.run(
                    ["systemctl", "start", "bluetooth"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=self.BLUETOOTH_RESTART_SYSTEMCTL_TIMEOUT,
                )

                # Step 3: Verify it's responsive
                if self._check_bluetooth_ready(timeout=5):
                    # Already logged by _check_bluetooth_ready()
                    return True

                # Step 4: If it's not responding, do a full restart
                self._log(
                    "WARNING",
                    f"Service not responsive on attempt {attempt+1}, attempting full restart...",
                )

                # Full restart: stop first, then start
                if self._is_bluetooth_service_active():
                    self._log("INFO", "Stopping Bluetooth service...")
                    try:
                        subprocess.run(
                            ["systemctl", "stop", "bluetooth"],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            timeout=self.BLUETOOTH_RESTART_SYSTEMCTL_TIMEOUT,
                        )
                        # Wait for service to actually stop
                        if not self._wait_for_service_state(target_state="inactive"):
                            self._log(
                                "WARNING",
                                "Service didn't stop cleanly, forcing kill...",
                            )
                            subprocess.run(
                                ["pkill", "-KILL", "bluetoothd"],
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                            )
                            time.sleep(1)
                    except subprocess.TimeoutExpired:
                        self._log(
                            "WARNING", "systemctl stop timed out, forcing kill..."
                        )
                        subprocess.run(
                            ["pkill", "-KILL", "bluetoothd"],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                        )
                        time.sleep(1)

                time.sleep(self.BLUETOOTH_RESTART_BETWEEN_STOP_START)

                # Restart service
                self._log("INFO", "Restarting Bluetooth service...")
                subprocess.run(
                    ["systemctl", "start", "bluetooth"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=self.BLUETOOTH_RESTART_SYSTEMCTL_TIMEOUT,
                )

                # Wait for service to actually be active
                if not self._wait_for_service_state(target_state="active"):
                    self._log(
                        "WARNING",
                        f"Service didn't start within expected time (attempt {attempt+1})",
                    )
                    time.sleep(2)
                    continue

                # Verify it's actually ready
                if self._check_bluetooth_ready(timeout=5):
                    self._log("INFO", "Bluetooth service successfully restarted")
                    return True
                else:
                    self._log(
                        "WARNING",
                        f"Service restarted but not responding (attempt {attempt+1})",
                    )
                    time.sleep(2)

            except subprocess.TimeoutExpired:
                self._log(
                    "WARNING", f"Restart timeout on attempt {attempt+1}, retrying..."
                )
                time.sleep(2)
            except Exception as e:
                self._log("ERROR", f"Restart failed: {e}")
                time.sleep(2)

        # Last resort: Try hardware-level reset (needed on Trixie)
        self._log(
            "WARNING", "All restart attempts failed, trying hardware-level reset..."
        )
        try:
            self.reset_bt()
            time.sleep(2)
            if self._check_bluetooth_ready(timeout=5):
                self._log("INFO", "Hardware-level reset successful")
                return True
        except Exception as e:
            self._log("ERROR", f"Hardware-level reset failed: {e}")

        return False

    def _run_cmd(self, cmd, capture=False, timeout=None):
        """Run shell command with error handling and deadlock prevention"""
        if timeout is None:
            timeout = self.DEFAULT_CMD_TIMEOUT
        # Use lock to prevent multiple bluetoothctl commands from running simultaneously
        with self._bluetoothctl_lock:
            try:
                # Disable bluetoothctl color output to prevent ANSI codes in logs
                env = dict(os.environ)
                env["NO_COLOR"] = "1"  # Standard env var to disable colors
                env["TERM"] = "dumb"  # Make terminal report as non-color capable

                if capture:
                    result = subprocess.run(
                        cmd, capture_output=True, text=True, timeout=timeout, env=env
                    )
                    # Return combined output with ANSI codes stripped to prevent log parser errors
                    output = result.stdout + result.stderr
                    return self._strip_ansi_codes(output)
                else:
                    subprocess.run(
                        cmd,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=timeout,
                        env=env,
                    )
                    return None
            except subprocess.TimeoutExpired:
                logging.error(
                    f"[bt-tether-helper] Command timeout ({timeout}s): {' '.join(cmd)}"
                )
                # Kill hung bluetoothctl after timeout (only if it's a bluetoothctl command)
                if cmd and cmd[0] == "bluetoothctl":
                    try:
                        subprocess.run(
                            ["pkill", "-9", "bluetoothctl"],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            timeout=2,
                        )
                        time.sleep(
                            self.PROCESS_CLEANUP_DELAY
                        )  # Brief pause to let process die
                    except Exception as e:
                        self._log("DEBUG", f"Process kill failed: {e}")
                return "Timeout"
            except Exception as e:
                logging.error(f"[bt-tether-helper] Command failed: {' '.join(cmd)}")
                logging.error(f"[bt-tether-helper] Exception: {e}")
                return f"Error: {e}"

    def _setup_network_dhcp(self, iface):
        """Setup network for bnep0 interface using DHCP with retry logic.

        After switching devices, the new phone's Bluetooth tethering DHCP server
        may take several seconds to initialize. We retry DHCP if the first attempt
        fails to get a real (non-link-local) IP address.

        IMPORTANT: On retries, we do NOT kill/restart dhcpcd. Once daemonized with
        IPv4LL, dhcpcd keeps sending periodic DISCOVERs in the background (~every
        5-10s). Killing it and restarting wastes time and resets the DHCP state
        machine. Instead we bounce the interface (dhcpcd detects carrier change
        via netlink and re-solicits) and just poll for the IP.
        """
        try:
            self._log("INFO", f"Setting up network for {iface}...")

            # Ensure interface is up
            self._log("INFO", f"Ensuring {iface} is up...")
            subprocess.run(
                ["sudo", "ip", "link", "set", iface, "up"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=5,
            )

            # First attempt: start dhcpcd fresh and poll for IP (40s window)
            if self._setup_dhclient(iface):
                return True

            # ── Fast-path: detect dead phone DHCP server ──
            # IPv4LL (169.254.x.x) means dhcpcd sent DISCOVERs for ~13 seconds
            # with ZERO response from the phone, then fell back to link-local.
            # This is a strong signal that the phone's BT tethering DHCP server
            # is not running at all (common after device switching on Android 16).
            # Bouncing the interface won't fix a dead phone-side DHCP server —
            # only a full NAP reconnect (Network1.Disconnect + bluetoothctl
            # disconnect + reconnect) can force the phone to reinitialize it.
            # Return False immediately so _connect_thread does the NAP reconnect
            # instead of wasting ~70 seconds on useless interface bouncing.
            try:
                _fpath_check = subprocess.run(
                    ["ip", "addr", "show", iface],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=5,
                )
                if _fpath_check.returncode == 0:
                    _fpath_match = re.search(
                        r"inet\s+(\d+\.\d+\.\d+\.\d+)", _fpath_check.stdout
                    )
                    if _fpath_match and _fpath_match.group(1).startswith("169.254."):
                        self._log(
                            "WARNING",
                            f"Phone DHCP server unresponsive (got IPv4LL "
                            f"{_fpath_match.group(1)}) — skipping interface "
                            f"bouncing, NAP reconnect needed",
                        )
                        return False
            except Exception:
                pass

            # dhcpcd is still running in background, sending periodic DISCOVERs.
            # On retries: bounce the interface to trigger phone-side DHCP reinit
            # and dhcpcd carrier-change re-solicitation. DON'T restart dhcpcd.
            for retry in range(1, self.DHCP_RETRY_MAX):
                self._log(
                    "WARNING",
                    f"DHCP retry {retry + 1}/{self.DHCP_RETRY_MAX} — bouncing {iface} to trigger phone DHCP re-init...",
                )

                # Bounce the interface down/up.
                # dhcpcd detects carrier loss via netlink, releases IPv4LL, and when
                # the interface comes back up, starts fresh DHCP DISCOVER.
                # This also triggers the phone's BT tethering to re-initialize.
                try:
                    subprocess.run(
                        ["sudo", "ip", "link", "set", iface, "down"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=3,
                    )
                    time.sleep(1)
                    subprocess.run(
                        ["sudo", "ip", "link", "set", iface, "up"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=3,
                    )
                    self._log("DEBUG", f"Bounced {iface} down/up")
                except Exception as e:
                    self._log("DEBUG", f"Failed to bounce {iface}: {e}")

                self._log(
                    "INFO", f"Waiting {self.DHCP_RETRY_WAIT}s for phone DHCP server..."
                )
                time.sleep(self.DHCP_RETRY_WAIT)

                # Verify interface still exists
                iface_check = subprocess.run(
                    ["ip", "link", "show", iface],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=3,
                )
                if iface_check.returncode != 0:
                    self._log("ERROR", f"{iface} disappeared during DHCP retry")
                    return False

                # Check if dhcpcd is still running for this interface.
                # It should survive the bounce, but if it exited, restart it.
                dhcpcd_alive = False
                try:
                    pidof = subprocess.run(
                        ["pidof", "dhcpcd"],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        timeout=3,
                    )
                    if pidof.returncode == 0 and pidof.stdout.strip():
                        for pid in pidof.stdout.strip().split():
                            try:
                                ps = subprocess.run(
                                    ["ps", "-p", pid, "-o", "args="],
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE,
                                    text=True,
                                    timeout=2,
                                )
                                if ps.returncode == 0:
                                    args = ps.stdout.strip().split()
                                    if args and args[-1] == iface:
                                        dhcpcd_alive = True
                                        break
                            except Exception:
                                pass
                except Exception:
                    pass

                if dhcpcd_alive:
                    self._log(
                        "INFO", "dhcpcd still running — polling for DHCP response..."
                    )
                else:
                    # dhcpcd exited after bounce — restart fresh
                    self._log("INFO", "dhcpcd exited after bounce — restarting...")
                    try:
                        subprocess.run(
                            ["sudo", "ip", "addr", "flush", "dev", iface],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            timeout=3,
                        )
                        subprocess.run(
                            [
                                "sudo",
                                "dhcpcd",
                                "-4",
                                "-m",
                                str(self.ROUTE_METRIC_BLUETOOTH),
                                iface,
                            ],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True,
                            timeout=self.DHCPCD_TIMEOUT,
                        )
                    except subprocess.TimeoutExpired:
                        self._kill_dhcpcd_for_interface(iface)
                    except Exception as e:
                        self._log("DEBUG", f"dhcpcd restart failed: {e}")

                # Poll for a real (non-link-local) IP address.
                # dhcpcd is sending DISCOVERs in background — we just need to wait.
                retry_checks = self.DHCP_RETRY_IP_CHECK_ATTEMPTS
                ip_found = False
                for check in range(retry_checks):
                    try:
                        ip_result = subprocess.run(
                            ["ip", "addr", "show", iface],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True,
                            timeout=5,
                        )
                        if ip_result.returncode == 0:
                            ip_match = re.search(
                                r"inet\s+(\d+\.\d+\.\d+\.\d+)", ip_result.stdout
                            )
                            if ip_match:
                                ip_addr = ip_match.group(1)
                                if not ip_addr.startswith("169.254."):
                                    self._log("INFO", f"✓ {iface} got IP: {ip_addr}")
                                    self._verify_localhost_route()
                                    self._set_route_metric(
                                        iface, self.ROUTE_METRIC_BLUETOOTH
                                    )
                                    return True
                                elif check % 5 == 0:
                                    self._log(
                                        "DEBUG",
                                        f"Still link-local ({ip_addr}), dhcpcd still soliciting...",
                                    )
                    except Exception:
                        pass

                    if check < retry_checks - 1:
                        time.sleep(2)

                self._log(
                    "WARNING",
                    f"DHCP retry {retry + 1} failed — no real IP after {retry_checks * 2}s",
                )

            self._log("ERROR", "All DHCP attempts failed")
            return False

        except subprocess.TimeoutExpired:
            self._log("ERROR", "Network setup timed out")
            return False
        except Exception as e:
            self._log("ERROR", f"Network setup error: {e}")
            return False

    def _kill_dhclient_for_interface(self, iface):
        """Kill dhclient processes specifically managing the given interface.

        Uses PID-based targeting to avoid killing dhclient processes for other interfaces.
        Only kills processes where the interface appears as a separate argument.
        """
        try:
            # Get all dhclient PIDs
            result = subprocess.run(
                ["pidof", "dhclient"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=3,
            )

            if result.returncode != 0 or not result.stdout.strip():
                # No dhclient processes running
                return

            pids = result.stdout.strip().split()
            killed_any = False

            for pid in pids:
                try:
                    # Get command line for this PID
                    ps_result = subprocess.run(
                        ["ps", "-p", pid, "-o", "args="],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        timeout=2,
                    )

                    if ps_result.returncode != 0:
                        continue

                    cmdline = ps_result.stdout.strip()

                    # Parse dhclient command line more carefully
                    # dhclient command format: dhclient [options] [interface]
                    # The interface is typically the last argument
                    args = cmdline.split()

                    # The interface must be the LAST argument and match EXACTLY
                    # This prevents matching "dhclient eth0" when looking for "eth0-backup"
                    # or "dhclient bnep0" matching a config file path containing "bnep0"
                    if args and args[-1] == iface:
                        self._log(
                            "DEBUG",
                            f"Killing dhclient PID {pid} for {iface} (cmdline: {cmdline})",
                        )
                        subprocess.run(
                            ["sudo", "kill", pid],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            timeout=3,
                        )
                        killed_any = True
                    else:
                        self._log(
                            "DEBUG",
                            f"Skipping PID {pid} - not managing {iface} (cmdline: {cmdline})",
                        )
                except Exception as e:
                    self._log("DEBUG", f"Error checking PID {pid}: {e}")
                    continue

            if killed_any:
                time.sleep(0.5)  # Brief wait for processes to exit

        except Exception as e:
            self._log("DEBUG", f"Error in _kill_dhclient_for_interface: {e}")

    def _kill_dhcpcd_for_interface(self, iface):
        """Kill dhcpcd processes specifically managing the given interface.

        Uses PID-based targeting to avoid killing dhcpcd processes for other interfaces.
        """
        try:
            # Get all dhcpcd PIDs
            result = subprocess.run(
                ["pidof", "dhcpcd"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=3,
            )

            if result.returncode != 0 or not result.stdout.strip():
                # No dhcpcd processes running
                self._log("DEBUG", f"No dhcpcd processes found for {iface}")
                return

            pids = result.stdout.strip().split()
            self._log("DEBUG", f"Found dhcpcd PIDs: {pids}")
            killed_any = False

            for pid in pids:
                try:
                    # Get command line for this PID
                    ps_result = subprocess.run(
                        ["ps", "-p", pid, "-o", "args="],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        timeout=2,
                    )

                    if ps_result.returncode != 0:
                        continue

                    cmdline = ps_result.stdout.strip()

                    # Parse dhcpcd command line
                    # dhcpcd command format: dhcpcd [options] [interface]
                    # Interface must be the LAST argument and match EXACTLY
                    args = cmdline.split()
                    if args and args[-1] == iface:
                        self._log(
                            "INFO",
                            f"Killing dhcpcd PID {pid} for {iface}",
                        )
                        subprocess.run(
                            ["sudo", "kill", pid],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            timeout=3,
                        )
                        killed_any = True
                    else:
                        self._log(
                            "DEBUG",
                            f"Skipping PID {pid} - not managing {iface} (cmdline: {cmdline})",
                        )
                except Exception as e:
                    self._log("DEBUG", f"Error checking PID {pid}: {e}")
                    continue

            if killed_any:
                time.sleep(0.5)  # Brief wait for processes to exit

        except Exception as e:
            self._log("DEBUG", f"Error in _kill_dhcpcd_for_interface: {e}")

    def _setup_dhclient(self, iface):
        """Request DHCP on interface"""
        try:
            self._log("INFO", f"Setting up {iface} for DHCP...")

            # Bring interface up
            subprocess.run(
                ["sudo", "ip", "link", "set", iface, "up"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=5,
            )

            # NOTE: We intentionally do NOT disable IPv6 on this interface.
            # Some Android devices (e.g. Pixel 6) provide IPv6-only connectivity
            # over Bluetooth tethering. Disabling IPv6 would block that path.
            # The plugin supports dual-stack: IPv4 and IPv6 connectivity checks.

            # Check which DHCP client is available
            has_dhcpcd = (
                subprocess.run(["which", "dhcpcd"], capture_output=True).returncode == 0
            )
            has_dhclient = (
                subprocess.run(["which", "dhclient"], capture_output=True).returncode
                == 0
            )

            self._log("INFO", f"Requesting DHCP on {iface}...")
            dhcp_success = False

            if has_dhcpcd:
                self._log("INFO", "Using dhcpcd...")
                # Kill any existing dhcpcd for this interface (PID-based targeting)
                self._kill_dhcpcd_for_interface(iface)
                time.sleep(self.DHCP_KILL_WAIT)

                # Remove ALL old lease/state files to force completely fresh DHCP discovery
                # dhcpcd 10.x stores state in multiple locations
                try:
                    lease_patterns = [
                        f"/var/lib/dhcpcd/{iface}.lease",
                        f"/var/lib/dhcpcd/{iface}-*.lease",
                    ]
                    for pattern in lease_patterns:
                        subprocess.run(
                            ["sudo", "bash", "-c", f"rm -f {pattern}"],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            timeout=3,
                        )
                    # Also clean runtime state
                    subprocess.run(
                        ["sudo", "bash", "-c", f"rm -f /run/dhcpcd/{iface}*"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=3,
                    )
                    self._log("DEBUG", f"Cleaned dhcpcd lease/state files for {iface}")
                except Exception as e:
                    self._log("DEBUG", f"Failed to clean lease files: {e}")

                # Flush any stale IP addresses from the interface before starting dhcpcd.
                # Without this, a killed dhcpcd leaves its IPv4LL (169.254.x.x) bound to
                # bnep0. The new dhcpcd sees it and reuses it immediately (skipping the
                # ARP probe phase), which can confuse some phones' DHCP servers.
                try:
                    subprocess.run(
                        ["sudo", "ip", "addr", "flush", "dev", iface],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=3,
                    )
                    self._log("DEBUG", f"Flushed IP addresses from {iface}")
                except Exception as e:
                    self._log("DEBUG", f"Failed to flush IPs: {e}")

                # Request new lease with fresh DHCP DISCOVER (not rebind/renew)
                # -4: IPv4 only
                # -m 200: Route metric (backup connection priority)
                # No -n flag: forces fresh DISCOVER instead of trying RENEW on stale lease
                # NO --noipv4ll: We WANT dhcpcd to fall back to IPv4LL so it can daemonize.
                #   With --noipv4ll, dhcpcd blocks forever if no DHCP response, our subprocess
                #   timeout kills it, and no background retry is possible.
                #   Without it, dhcpcd gets IPv4LL at ~13s, daemonizes, and keeps sending
                #   DHCP DISCOVERs in the background while our IP check loop polls for a real IP.
                #   The IP check loop already rejects 169.254.x.x addresses.
                self._log(
                    "DEBUG",
                    f"Running: dhcpcd -4 -m {self.ROUTE_METRIC_BLUETOOTH} {iface}",
                )
                try:
                    result = subprocess.run(
                        [
                            "sudo",
                            "dhcpcd",
                            "-4",
                            "-m",
                            str(self.ROUTE_METRIC_BLUETOOTH),
                            iface,
                        ],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        timeout=self.DHCPCD_TIMEOUT,
                    )
                    self._log("DEBUG", f"dhcpcd return code: {result.returncode}")
                    if result.stdout.strip():
                        self._log("INFO", f"dhcpcd stdout: {result.stdout.strip()}")
                    if result.stderr.strip():
                        self._log("INFO", f"dhcpcd stderr: {result.stderr.strip()}")
                    if result.returncode == 0:
                        dhcp_success = True
                    else:
                        self._log(
                            "WARNING", f"dhcpcd failed with code {result.returncode}"
                        )
                except subprocess.TimeoutExpired:
                    # dhcpcd blocked for the full timeout — rare without --noipv4ll
                    # but can happen if the interface is completely unresponsive.
                    # subprocess.run kills 'sudo' but may leave dhcpcd as an orphan.
                    self._log(
                        "WARNING", f"dhcpcd timed out after {self.DHCPCD_TIMEOUT}s"
                    )
                    self._kill_dhcpcd_for_interface(iface)

            elif has_dhclient:
                self._log("INFO", "Using dhclient...")
                # Kill any existing dhclient for this interface (PID-based targeting)
                self._kill_dhclient_for_interface(iface)
                time.sleep(self.DHCP_KILL_WAIT)

                # Request new lease with better error handling
                try:
                    result = subprocess.run(
                        ["sudo", "dhclient", "-4", "-v", iface],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        timeout=self.DHCLIENT_TIMEOUT,
                    )
                    combined = f"{result.stdout} {result.stderr}".strip()

                    # Check for common error messages
                    if "Network error: Software caused connection abort" in combined:
                        self._log("WARNING", "dhclient: Connection aborted by phone")
                        self._log(
                            "WARNING",
                            "📱 Make sure Bluetooth tethering is ENABLED on your phone!",
                        )
                        self._log(
                            "WARNING",
                            "📱 Settings → Network → Hotspot & tethering → Bluetooth tethering",
                        )
                    elif "DHCPDISCOVER" in combined and "No DHCPOFFERS" in combined:
                        self._log("WARNING", "dhclient: No DHCP response from phone")
                        self._log(
                            "WARNING",
                            "📱 Phone is not providing DHCP - enable Bluetooth tethering!",
                        )

                    # Only log dhclient output if there's an error
                    if result.returncode != 0 and combined:
                        # Truncate long output
                        self._log("INFO", f"dhclient: {combined[:200]}")

                    if result.returncode == 0:
                        dhcp_success = True
                    else:
                        self._log("WARNING", f"dhclient returned {result.returncode}")

                except subprocess.TimeoutExpired:
                    self._log("WARNING", "dhclient timed out after 30s")
                    # Kill hung dhclient (PID-based targeting)
                    try:
                        # Get all dhclient PIDs
                        result = subprocess.run(
                            ["pidof", "dhclient"],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True,
                            timeout=3,
                        )

                        if result.returncode == 0 and result.stdout.strip():
                            pids = result.stdout.strip().split()

                            for pid in pids:
                                try:
                                    # Get command line for this PID
                                    ps_result = subprocess.run(
                                        ["ps", "-p", pid, "-o", "args="],
                                        stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE,
                                        text=True,
                                        timeout=2,
                                    )

                                    if ps_result.returncode != 0:
                                        continue

                                    cmdline = ps_result.stdout.strip()

                                    # Check if this dhclient is managing our interface
                                    # The interface MUST be the last argument
                                    args = cmdline.split()
                                    if args and args[-1] == iface:
                                        self._log(
                                            "DEBUG",
                                            f"Force killing dhclient PID {pid} for {iface} (cmdline: {cmdline})",
                                        )
                                        subprocess.run(
                                            ["sudo", "kill", "-9", pid],
                                            stdout=subprocess.DEVNULL,
                                            stderr=subprocess.DEVNULL,
                                            timeout=3,
                                        )
                                    else:
                                        self._log(
                                            "DEBUG",
                                            f"Skipping force-kill PID {pid} - not managing {iface} (cmdline: {cmdline})",
                                        )
                                except Exception as e:
                                    self._log(
                                        "DEBUG", f"Error force-killing PID {pid}: {e}"
                                    )
                                    continue
                    except Exception as e:
                        self._log("DEBUG", f"Error in timeout dhclient cleanup: {e}")

            else:
                self._log(
                    "ERROR",
                    "No DHCP client found! Install dhclient: sudo apt install isc-dhcp-client",
                )
                return False

            # Check for IP with extended wait time (tethering may take time to fully start)
            ip_addr = None
            max_checks = self.DHCP_IP_CHECK_MAX_ATTEMPTS

            # Fast-fail: if dhcpcd fell back to IPv4LL, the phone's DHCP server
            # is completely dead (zero responses to 13s of DISCOVERs).  Polling
            # for 40s won't help — the daemon sends background DISCOVERs but the
            # phone won't respond.  Reduce to 5 checks (10s) so we reach the
            # NAP reconnect recovery path ~30s faster.
            _dhcpcd_output = ""
            try:
                _dhcpcd_output = getattr(result, "stderr", "") or ""
            except Exception:
                pass
            if "using IPv4LL address" in _dhcpcd_output:
                self._log(
                    "WARNING",
                    "dhcpcd fell back to IPv4LL — phone DHCP server unresponsive, "
                    "reducing IP poll to 10s (was 40s)",
                )
                max_checks = 5

            for attempt in range(max_checks):
                ip_result = subprocess.run(
                    ["ip", "addr", "show", iface],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=5,
                )

                if ip_result.returncode == 0:
                    ip_match = re.search(
                        r"inet\s+(\d+\.\d+\.\d+\.\d+)", ip_result.stdout
                    )
                    if ip_match:
                        ip_addr = ip_match.group(1)
                        if not ip_addr.startswith("169.254."):
                            self._log("INFO", f"✓ {iface} got IP: {ip_addr}")
                            break
                        else:
                            self._log(
                                "DEBUG", f"Link-local IP {ip_addr}, waiting for DHCP..."
                            )
                            ip_addr = None

                if attempt < max_checks - 1:
                    self._log("DEBUG", f"Waiting for IP... ({(attempt+1)*2}s)")
                    time.sleep(2)

            if ip_addr:
                self._verify_localhost_route()
                # Adjust route metric to make Bluetooth a backup connection
                self._set_route_metric(iface, self.ROUTE_METRIC_BLUETOOTH)
                return True
            else:
                self._log("ERROR", f"❌ No IP on {iface} after {max_checks * 2}s")
                self._log("ERROR", "📱 Enable Bluetooth tethering on your phone!")
                self._log(
                    "ERROR",
                    "📱 Settings → Network & internet → Hotspot & tethering → Bluetooth tethering",
                )
                return False

        except Exception as e:
            logging.error(f"[bt-tether-helper] Network setup error: {e}")
            return False

    def _verify_localhost_route(self):
        """Verify localhost routes correctly through loopback interface (critical for bettercap API)"""
        try:
            # Check localhost routing
            result = subprocess.run(
                ["ip", "route", "get", "127.0.0.1"],
                capture_output=True,
                text=True,
                timeout=3,
            )

            if result.returncode == 0:
                route_output = result.stdout.strip()
                # Localhost should use 'lo' interface or 'local' keyword
                if "lo" not in route_output and "local" not in route_output:
                    logging.warning(
                        f"[bt-tether-helper] ⚠️  Localhost routing misconfigured: {route_output}"
                    )
                    logging.warning(
                        "[bt-tether-helper] ⚠️  This may prevent bettercap API from working!"
                    )
                    logging.info(
                        "[bt-tether-helper] Attempting to fix localhost route..."
                    )

                    # Ensure loopback interface is up
                    subprocess.run(
                        ["sudo", "ip", "link", "set", "lo", "up"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=3,
                    )

                    # Add explicit localhost route if missing
                    subprocess.run(
                        ["sudo", "ip", "route", "add", "127.0.0.0/8", "dev", "lo"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=3,
                    )

                    logging.info(
                        "[bt-tether-helper] ✓ Localhost route protection applied"
                    )
                else:
                    logging.debug(
                        f"[bt-tether-helper] Localhost route OK: {route_output}"
                    )
            else:
                logging.warning("[bt-tether-helper] Could not verify localhost routing")

        except Exception as e:
            logging.error(
                f"[bt-tether-helper] Localhost route verification failed: {e}"
            )

    def _set_route_metric(self, iface, metric=None):
        """Set the metric for default route through interface to make it a backup connection.

        Lower metric = higher priority
        Common metrics:
        - 0-100: Primary connections (Ethernet, USB tethering)
        - 200: Bluetooth (backup connection)
        - 300+: Low priority backup connections
        """
        if metric is None:
            metric = self.ROUTE_METRIC_BLUETOOTH
        try:
            # Check if there's a default route for this interface
            result = subprocess.run(
                ["ip", "route", "show", "default", "dev", iface],
                capture_output=True,
                text=True,
                timeout=5,
            )

            if result.returncode != 0 or not result.stdout.strip():
                self._log("DEBUG", f"No default route found for {iface}")
                return False

            # Parse the existing route
            route_line = result.stdout.strip().split("\n")[0]

            # Check if metric already set correctly
            if f"metric {metric}" in route_line:
                self._log("DEBUG", f"Route metric for {iface} already set to {metric}")
                return True

            # Extract gateway
            gateway_match = re.search(r"via\s+(\S+)", route_line)
            if not gateway_match:
                self._log("DEBUG", f"No gateway found in route for {iface}")
                return False

            gateway = gateway_match.group(1)

            # Delete old route
            self._log(
                "INFO",
                f"Adjusting route metric for {iface} to {metric} (backup priority)",
            )
            subprocess.run(
                ["sudo", "ip", "route", "del", "default", "dev", iface],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=5,
            )

            # Add new route with metric
            result = subprocess.run(
                [
                    "sudo",
                    "ip",
                    "route",
                    "add",
                    "default",
                    "via",
                    gateway,
                    "dev",
                    iface,
                    "metric",
                    str(metric),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=5,
            )

            if result.returncode == 0:
                self._log(
                    "INFO",
                    f"✓ Set {iface} route metric to {metric} (will be backup to lower-metric connections)",
                )
                return True
            else:
                self._log(
                    "WARNING",
                    f"Failed to set route metric: {result.stderr.decode().strip()}",
                )
                return False

        except Exception as e:
            self._log("DEBUG", f"Error setting route metric: {e}")
            return False

    def _check_internet_connectivity(self):
        """Check if internet is accessible via Bluetooth interface specifically (IPv4 or IPv6)"""
        try:
            # Get the BT interface
            bt_iface = self._get_pan_interface() or "bnep0"

            # First verify interface has an IP - check for both IPv4 and IPv6
            ip_result = subprocess.run(
                ["ip", "addr", "show", bt_iface],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=5,
            )

            if ip_result.returncode != 0:
                logging.warning(f"[bt-tether-helper] {bt_iface} interface not found")
                return False

            # Check for IPv4 address (exclude link-local 169.254.x.x)
            ipv4_match = re.search(r"inet\s+(\d+\.\d+\.\d+\.\d+)", ip_result.stdout)
            has_ipv4 = ipv4_match and not ipv4_match.group(1).startswith("169.254.")

            # Check for IPv6 address (exclude link-local fe80::)
            ipv6_match = re.search(r"inet6\s+([0-9a-fA-F:]+)", ip_result.stdout)
            has_ipv6 = ipv6_match and not ipv6_match.group(1).startswith("fe80")

            if not has_ipv4 and not has_ipv6:
                logging.warning(
                    f"[bt-tether-helper] {bt_iface} has no valid IP (IPv4 or IPv6)"
                )
                return False

            if has_ipv4:
                logging.info(
                    f"[bt-tether-helper] {bt_iface} has IPv4: {ipv4_match.group(1)}"
                )
            if has_ipv6:
                logging.info(
                    f"[bt-tether-helper] {bt_iface} has IPv6: {ipv6_match.group(1)}"
                )

            # Log current routing table for diagnostics
            route_check = subprocess.run(
                ["ip", "route", "show"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=5,
            )
            if route_check.returncode == 0:
                logging.info(
                    f"[bt-tether-helper] Current routes:\n{route_check.stdout}"
                )

            # Try IPv4 connectivity first (if we have IPv4)
            if has_ipv4:
                logging.info(
                    f"[bt-tether-helper] Testing IPv4 connectivity to 8.8.8.8 via {bt_iface}..."
                )
                result = subprocess.run(
                    ["ping", "-c", "1", "-W", "2", "-I", bt_iface, "8.8.8.8"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=10,
                )

                if result.returncode == 0:
                    logging.info(
                        f"[bt-tether-helper] ✓ IPv4 ping to 8.8.8.8 successful"
                    )

                    # Also verify DNS resolution works
                    logging.info(f"[bt-tether-helper] Testing DNS resolution...")
                    try:
                        dns_result = subprocess.run(
                            ["nslookup", "google.com"],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            timeout=5,
                        )
                        if dns_result.returncode == 0:
                            logging.info(f"[bt-tether-helper] ✓ DNS resolution working")
                            return True
                        else:
                            logging.warning(
                                f"[bt-tether-helper] DNS resolution failed but ping works"
                            )
                            return True  # Ping works, so basic connectivity is there
                    except:
                        logging.warning(
                            f"[bt-tether-helper] DNS test failed but ping works"
                        )
                        return True  # Ping works, so basic connectivity is there
                else:
                    logging.warning(f"[bt-tether-helper] IPv4 ping to 8.8.8.8 failed")
                    logging.debug(f"[bt-tether-helper] Ping stderr: {result.stderr}")
                    logging.debug(f"[bt-tether-helper] Ping stdout: {result.stdout}")

            # Try IPv6 connectivity (if we have IPv6 and IPv4 failed or wasn't available)
            if has_ipv6:
                logging.info(
                    f"[bt-tether-helper] Testing IPv6 connectivity via {bt_iface}..."
                )
                result = subprocess.run(
                    ["ping", "-6", "-c", "1", "-W", "2", "-I", bt_iface, "google.com"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=10,
                )

                if result.returncode == 0:
                    logging.info(f"[bt-tether-helper] ✓ IPv6 connectivity verified")
                    return True
                else:
                    logging.warning(f"[bt-tether-helper] IPv6 ping failed")
                    logging.debug(f"[bt-tether-helper] Ping stderr: {result.stderr}")
                    logging.debug(f"[bt-tether-helper] Ping stdout: {result.stdout}")

            # Both IPv4 and IPv6 failed - do gateway diagnostics for IPv4 if available
            if has_ipv4:
                gateway_check = subprocess.run(
                    ["ip", "route", "show", "default"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=5,
                )
                if gateway_check.returncode == 0 and gateway_check.stdout:
                    match = re.search(r"default via ([\d.]+)", gateway_check.stdout)
                    if match:
                        gateway = match.group(1)
                        logging.info(
                            f"[bt-tether-helper] Testing connectivity to gateway {gateway}..."
                        )
                        gw_result = subprocess.run(
                            ["ping", "-c", "2", "-W", "3", gateway],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True,
                            timeout=10,
                        )
                        if gw_result.returncode == 0:
                            logging.warning(
                                f"[bt-tether-helper] Gateway ping works, but internet ping failed - possible NAT/firewall issue"
                            )
                        else:
                            logging.warning(
                                f"[bt-tether-helper] Gateway ping also failed - phone may not be providing internet"
                            )

            return False
        except subprocess.TimeoutExpired:
            logging.warning(
                f"[bt-tether-helper] Ping timeout - no internet connectivity"
            )
            return False
        except Exception as e:
            logging.error(f"[bt-tether-helper] Internet check error: {e}")
            return False

    def _pan_active(self):
        """Check if any PAN interface (bnep/bt-pan) is active - optimized for RPi Zero W2"""
        try:
            # More efficient: use ip link show instead of full ip a output
            result = subprocess.run(
                ["ip", "link", "show"],
                capture_output=True,
                text=True,
                timeout=3,  # Reduced timeout for efficiency
            )

            # Check for both bnep and bt-pan interfaces
            has_bnep = "bnep" in result.stdout
            has_bt_pan = "bt-pan" in result.stdout

            if has_bnep or has_bt_pan:
                logging.debug(
                    f"[bt-tether-helper] Found PAN interface (bnep={has_bnep}, bt-pan={has_bt_pan})"
                )
                return True

            logging.debug("[bt-tether-helper] No PAN interface found (bnep/bt-pan)")
            return False
        except Exception as e:
            logging.error(f"[bt-tether-helper] Failed to check PAN: {e}")
            return False

    def _cleanup_bnep_bridge(self, mac=None):
        """Release the BNEP bridge so a new device can connect.

        IMPORTANT: Always release dhcpcd FIRST, before tearing down the bridge.
        If dhcpcd is left running, it will detect the new bnep0 (from the next
        Network1.Connect) and immediately try to RENEW the old device's lease,
        confusing the new phone's DHCP server.

        Phase 1 — Clean disconnect via Network1.Disconnect():
            This is the proper BlueZ API for tearing down a PAN connection.
            If it works, the BNEP bridge is released cleanly and we're done.

        Phase 2 — Aggressive fallback (only if Phase 1 failed):
            DisconnectProfile, Device1.Disconnect, bluetoothctl, ip link delete.
            This is the "br-connection-busy" recovery path.
        """
        try:
            self._log("INFO", "Releasing BNEP bridge...")

            # ── Step 0: Always kill dhcpcd BEFORE tearing down the bridge ──
            # dhcpcd runs as a daemon on bnep0.  If we remove bnep0 (via
            # Network1.Disconnect) while dhcpcd is still alive, it loses carrier
            # but stays resident.  When a new bnep0 appears (next device), the
            # OLD dhcpcd immediately sends a RENEW for a lease from the PREVIOUS
            # phone, which the new phone ignores → DHCP fails → IPv4LL.
            try:
                subprocess.run(
                    ["dhcpcd", "--release", "bnep0"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=3,
                )
            except Exception:
                pass
            try:
                subprocess.run(
                    ["pkill", "-f", "dhcpcd.*bnep"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=3,
                )
            except Exception:
                pass

            # ── Phase 1: Clean Network1.Disconnect() ──
            # This is all BlueZ should need to tear down the bridge.
            bridge_released = False
            try:
                import dbus

                bus = dbus.SystemBus()
                manager = dbus.Interface(
                    bus.get_object("org.bluez", "/"),
                    "org.freedesktop.DBus.ObjectManager",
                )
                objects = manager.GetManagedObjects()

                # Find devices with an active Network1 connection
                for path, interfaces in objects.items():
                    if "org.bluez.Network1" not in interfaces:
                        continue
                    net_props = interfaces.get("org.bluez.Network1", {})
                    dev_props = interfaces.get("org.bluez.Device1", {})
                    addr = dev_props.get("Address", "")
                    is_net_connected = net_props.get("Connected", False)

                    # Only disconnect the target MAC, or any device holding
                    # an active Network1 connection (= holding the bridge)
                    if addr == mac or is_net_connected:
                        try:
                            net_iface = dbus.Interface(
                                bus.get_object("org.bluez", path),
                                "org.bluez.Network1",
                            )
                            t = threading.Thread(
                                target=lambda ni=net_iface: ni.Disconnect(),
                                daemon=True,
                            )
                            t.start()
                            t.join(timeout=5)
                            if not t.is_alive():
                                self._log(
                                    "INFO",
                                    f"Network1.Disconnect() OK for {addr or path}",
                                )
                                bridge_released = True
                            else:
                                self._log(
                                    "WARNING",
                                    f"Network1.Disconnect() timed out for {addr or path}",
                                )
                        except Exception as e:
                            self._log(
                                "DEBUG",
                                f"Network1.Disconnect({addr or path}): {e}",
                            )
            except Exception as e:
                self._log("DEBUG", f"Phase 1 (Network1) cleanup error: {e}")

            # Check if bnep0 is actually gone
            if bridge_released:
                time.sleep(1)
                try:
                    ifaces_out = subprocess.check_output(
                        ["ip", "link", "show"], text=True, timeout=5
                    )
                    if "bnep0" not in ifaces_out:
                        self._log("INFO", "BNEP bridge released cleanly via Network1")

                        # ── IMPORTANT: Do NOT disconnect the ACL link ──
                        # Network1.Disconnect() tears down the BNEP bridge
                        # (PAN session) cleanly on both sides.  The underlying
                        # Bluetooth ACL link stays alive intentionally.
                        #
                        # Why: Android 16 (Pixel 6) keeps its BT tethering
                        # DHCP server running as long as the ACL link is alive.
                        # If we also sever the ACL link (bluetoothctl disconnect),
                        # the phone's tethering service shuts down its DHCP
                        # server — and does NOT properly reinitialize it on
                        # the next NAP connection.  Result: DHCP fails → IPv4LL.
                        #
                        # By keeping the ACL link alive, the phone still sees
                        # us as "connected" at the BT level.  When we do
                        # Network1.Connect later, the phone starts a new PAN
                        # session on the existing ACL link and its (still-running)
                        # DHCP server responds immediately.
                        #
                        # This is safe for other phones too (Motorola, etc) —
                        # they work fine either way.
                        if mac:
                            self._log(
                                "INFO",
                                f"Keeping ACL link to {mac} alive — "
                                f"phone tethering DHCP server stays running",
                            )
                        return
                    else:
                        self._log(
                            "WARNING",
                            "Network1.Disconnect() returned OK but bnep0 still exists — "
                            "falling back to aggressive cleanup",
                        )
                except Exception:
                    pass

            # ── Phase 2: Aggressive fallback ──
            # Only reached if Network1.Disconnect() failed or bnep0 is stuck.
            self._log("WARNING", "Phase 2: aggressive BNEP bridge cleanup...")

            # dhcpcd already killed in Step 0 above

            # D-Bus fallback: DisconnectProfile + Device1.Disconnect
            try:
                import dbus

                bus = dbus.SystemBus()
                manager = dbus.Interface(
                    bus.get_object("org.bluez", "/"),
                    "org.freedesktop.DBus.ObjectManager",
                )
                objects = manager.GetManagedObjects()

                for path, interfaces in objects.items():
                    if "org.bluez.Device1" not in interfaces:
                        continue
                    dev_props = interfaces["org.bluez.Device1"]
                    addr = dev_props.get("Address", "")
                    has_network = "org.bluez.Network1" in interfaces

                    if addr != mac and not has_network:
                        continue

                    dev_label = addr or path

                    # DisconnectProfile(NAP_UUID)
                    try:
                        device = dbus.Interface(
                            bus.get_object("org.bluez", path),
                            "org.bluez.Device1",
                        )
                        t = threading.Thread(
                            target=lambda d=device: d.DisconnectProfile(self.NAP_UUID),
                            daemon=True,
                        )
                        t.start()
                        t.join(timeout=3)
                        self._log(
                            "DEBUG", f"DisconnectProfile(NAP) sent to {dev_label}"
                        )
                    except Exception as e:
                        self._log("DEBUG", f"DisconnectProfile(NAP) {dev_label}: {e}")

                    # Device1.Disconnect — drop the ACL link entirely
                    if addr == mac or has_network:
                        try:
                            device = dbus.Interface(
                                bus.get_object("org.bluez", path),
                                "org.bluez.Device1",
                            )
                            t = threading.Thread(
                                target=lambda d=device: d.Disconnect(),
                                daemon=True,
                            )
                            t.start()
                            t.join(timeout=3)
                            self._log(
                                "DEBUG", f"Device1.Disconnect() sent to {dev_label}"
                            )
                        except Exception as e:
                            self._log("DEBUG", f"Device1.Disconnect({dev_label}): {e}")

            except Exception as e:
                self._log("DEBUG", f"Phase 2 D-Bus cleanup error: {e}")

            # bluetoothctl disconnect — target specific MAC
            if mac:
                self._run_cmd(
                    ["bluetoothctl", "disconnect", mac], capture=True, timeout=5
                )
            else:
                self._run_cmd(["bluetoothctl", "disconnect"], capture=True, timeout=5)
            time.sleep(1)

            # Remove bnep0 if it's still lingering
            try:
                ifaces_out = subprocess.check_output(
                    ["ip", "link", "show"], text=True, timeout=5
                )
                if "bnep0" in ifaces_out:
                    subprocess.run(
                        ["ip", "link", "set", "bnep0", "down"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=5,
                    )
                    time.sleep(0.5)
                    subprocess.run(
                        ["ip", "link", "delete", "bnep0"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=5,
                    )
                    self._log("DEBUG", "Removed stale bnep0")
            except Exception:
                pass

            time.sleep(1)
            self._log("INFO", "BNEP bridge cleanup complete")
        except Exception as e:
            self._log("DEBUG", f"BNEP bridge cleanup error: {e}")

    def _get_default_route_interface(self):
        """Get the network interface that has the default route (lowest metric)"""
        try:
            result = subprocess.check_output(
                ["ip", "route", "show", "default"], text=True, timeout=5
            )

            if not result:
                return None

            # Parse default route lines to find the one with lowest metric
            # Format: "default via 192.168.1.1 dev eth0 metric 100"

            routes = []
            for line in result.strip().split("\n"):
                if "default" in line:
                    # Extract interface name
                    dev_match = re.search(r"dev\s+(\S+)", line)
                    if dev_match:
                        iface = dev_match.group(1)

                        # Extract metric (default to 0 if not specified)
                        metric_match = re.search(r"metric\s+(\d+)", line)
                        metric = int(metric_match.group(1)) if metric_match else 0

                        routes.append((iface, metric))

            if not routes:
                return None

            # Sort by metric (lowest first) and return the interface
            routes.sort(key=lambda x: x[1])
            return routes[0][0]

        except Exception as e:
            logging.debug(f"[bt-tether-helper] Failed to get default route: {e}")
            return None

    def _test_internet_connectivity(self):
        """Test internet connectivity and return detailed results"""
        try:
            result = {
                "ping_success": False,
                "ping6_success": False,
                "dns_success": False,
                "bnep0_ip": None,
                "bnep0_ipv6": None,
                "default_route": None,
                "dns_servers": None,
                "dns_error": None,
                "localhost_routes": None,
            }

            # Test IPv4 ping to 8.8.8.8
            try:
                ping_result = subprocess.run(
                    ["ping", "-c", "2", "-W", "3", "8.8.8.8"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=5,
                )
                result["ping_success"] = ping_result.returncode == 0
                logging.info(
                    f"[bt-tether-helper] IPv4 ping test: {'Success' if result['ping_success'] else 'Failed'}"
                )
            except Exception as e:
                logging.warning(f"[bt-tether-helper] IPv4 ping test error: {e}")

            # Test IPv6 ping (automatic fallback)
            try:
                ping6_result = subprocess.run(
                    ["ping", "-6", "-c", "2", "-W", "3", "google.com"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=8,
                )
                result["ping6_success"] = ping6_result.returncode == 0
                logging.info(
                    f"[bt-tether-helper] IPv6 ping test: {'Success' if result['ping6_success'] else 'Failed'}"
                )
            except Exception as e:
                logging.warning(f"[bt-tether-helper] IPv6 ping test error: {e}")

            # Mark overall ping success if either works
            result["ping_success"] = result["ping_success"] or result["ping6_success"]

            # Test DNS resolution
            try:
                import socket

                # Try to resolve google.com using Python's socket library
                socket.gethostbyname("google.com")
                result["dns_success"] = True
                logging.info("[bt-tether-helper] DNS test: Success")
            except socket.gaierror as e:
                result["dns_success"] = False
                result["dns_error"] = f"DNS resolution failed: {str(e)}"
                logging.warning(f"[bt-tether-helper] DNS test failed: {e}")
            except Exception as e:
                result["dns_success"] = False
                result["dns_error"] = str(e)
                logging.warning(f"[bt-tether-helper] DNS test error: {e}")

            # Get DNS servers from resolv.conf
            try:
                with open("/etc/resolv.conf", "r") as f:
                    resolv_content = f.read()
                    dns_servers = []
                    for line in resolv_content.split("\n"):
                        if line.strip().startswith("nameserver"):
                            dns_servers.append(line.strip().split()[1])
                    result["dns_servers"] = (
                        ", ".join(dns_servers) if dns_servers else "None"
                    )
                logging.info(f"[bt-tether-helper] DNS servers: {result['dns_servers']}")
            except Exception as e:
                result["dns_servers"] = f"Error: {str(e)[:50]}"
                logging.warning(f"[bt-tether-helper] Get DNS servers error: {e}")

            # Get bnep0 IP address
            try:
                ip_result = subprocess.run(
                    ["ip", "addr", "show", "bnep0"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=5,
                )
                if ip_result.returncode == 0:

                    ip_match = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", ip_result.stdout)
                    if ip_match:
                        result["bnep0_ip"] = ip_match.group(1)
                logging.info(f"[bt-tether-helper] bnep0 IPv4: {result['bnep0_ip']}")
            except Exception as e:
                logging.warning(f"[bt-tether-helper] Get bnep0 IP error: {e}")

            # Get bnep0 IPv6 address
            try:
                bt_iface = self._get_pan_interface() or "bnep0"
                ipv6_addr = self._get_global_ipv6(bt_iface)
                if ipv6_addr:
                    result["bnep0_ipv6"] = ipv6_addr
                logging.info(f"[bt-tether-helper] bnep0 IPv6: {result['bnep0_ipv6']}")
            except Exception as e:
                logging.warning(f"[bt-tether-helper] Get bnep0 IPv6 error: {e}")

            # Get default route
            try:
                route_result = subprocess.run(
                    ["ip", "route", "show", "default"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=5,
                )
                if route_result.returncode == 0 and route_result.stdout:
                    result["default_route"] = route_result.stdout.strip()
                logging.info(
                    f"[bt-tether-helper] Default route: {result['default_route']}"
                )
            except Exception as e:
                logging.warning(f"[bt-tether-helper] Get default route error: {e}")

            # Get localhost route - CRITICAL for bettercap API access
            try:
                localhost_result = subprocess.run(
                    ["ip", "route", "get", "127.0.0.1"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=5,
                )
                if localhost_result.returncode == 0 and localhost_result.stdout:
                    result["localhost_routes"] = localhost_result.stdout.strip()
                    # Localhost should use 'lo' interface
                    if (
                        "lo" not in result["localhost_routes"]
                        and "local" not in result["localhost_routes"]
                    ):
                        logging.warning(
                            f"[bt-tether-helper] ⚠️  WARNING: Localhost not routing through 'lo' interface!"
                        )
                        logging.warning(
                            f"[bt-tether-helper] ⚠️  This may prevent bettercap API from working: {result['localhost_routes']}"
                        )
                    else:
                        logging.info(
                            f"[bt-tether-helper] Localhost route: {result['localhost_routes']}"
                        )
                else:
                    result["localhost_routes"] = "Error getting localhost route"
            except Exception as e:
                result["localhost_routes"] = f"Error: {str(e)}"
                logging.warning(f"[bt-tether-helper] Get localhost route error: {e}")

            return result

        except Exception as e:
            logging.error(f"[bt-tether-helper] Internet connectivity test error: {e}")
            return {
                "ping_success": False,
                "ping6_success": False,
                "dns_success": False,
                "bnep0_ip": None,
                "bnep0_ipv6": None,
                "default_route": None,
                "dns_servers": None,
                "dns_error": str(e),
            }

    def _get_pan_interface(self):
        """Get the name of the Bluetooth PAN interface if it exists"""
        try:
            out = subprocess.check_output(["ip", "link"], text=True, timeout=5)
            # Look for bnep or bt-pan interface names
            for line in out.split("\n"):
                if "bnep" in line or "bt-pan" in line:
                    # Extract interface name (e.g., "2: bnep0:" -> "bnep0")
                    parts = line.split(":")
                    if len(parts) >= 2:
                        iface = parts[1].strip()
                        return iface
            return None
        except Exception as e:
            logging.error(f"[bt-tether-helper] Failed to get PAN interface: {e}")
            return None

    def _wait_for_pan_interface(self, timeout=10):
        """Wait for PAN interface (bnep0) to appear after NAP connects.

        When Network1.Connect("nap") is used, it returns the interface name
        directly so this polling is not needed.  This is only called as a
        fallback when ConnectProfile was used (no Network1 available).

        Args:
            timeout: Max seconds to wait for the interface

        Returns:
            Interface name (e.g. "bnep0") or None if it never appeared.
        """
        poll_interval = self.PAN_INTERFACE_POLL_INTERVAL
        elapsed = 0.0
        while elapsed < timeout:
            iface = self._get_pan_interface()
            if iface:
                return iface
            time.sleep(poll_interval)
            elapsed += poll_interval
        return None

    def _get_interface_ip(self, iface):
        """Get IP address of a network interface"""
        try:

            result = subprocess.check_output(
                ["ip", "-4", "addr", "show", iface], text=True, timeout=5
            )
            # Look for inet address (e.g., "inet 192.168.44.123/24")
            match = re.search(r"inet\s+(\d+\.\d+\.\d+\.\d+)", result)
            if match:
                return match.group(1)
            return None
        except Exception as e:
            logging.debug(f"[bt-tether-helper] Failed to get IP for {iface}: {e}")
            return None

    def _get_global_ipv6(self, iface=None):
        """Get global IPv6 address from the Bluetooth PAN interface"""
        try:
            if iface is None:
                iface = self._get_pan_interface() or "bnep0"
            result = subprocess.check_output(
                ["ip", "-6", "addr", "show", iface, "scope", "global"],
                text=True,
                timeout=5,
            )
            for line in result.splitlines():
                line = line.strip()
                if line.startswith("inet6"):
                    # Extract IPv6 address (e.g., "inet6 2a00:20:b2d5:bdeb::1/64" -> "2a00:20:b2d5:bdeb::1")
                    return line.split()[1].split("/")[0]
            return None
        except Exception as e:
            logging.debug(f"[bt-tether-helper] Failed to get IPv6 for {iface}: {e}")
            return None

    def _pair_device_interactive(self, mac):
        """Pair device - persistent agent will handle the dialog"""
        try:
            logging.info(f"[bt-tether-helper] Starting pairing with {mac}...")

            with self.lock:
                self.message = "Scanning for phone..."

            # First ensure Bluetooth is powered on and in pairable mode
            self._run_cmd(["bluetoothctl", "power", "on"], capture=True)
            time.sleep(self.PAIRING_MODE_SETUP_DELAY)
            self._run_cmd(["bluetoothctl", "pairable", "on"], capture=True)
            self._run_cmd(["bluetoothctl", "discoverable", "on"], capture=True)
            time.sleep(self.PAIRING_MODE_SETUP_DELAY)

            # CRITICAL: Keep discovery scan active during pairing to keep phone discoverable
            # Phone may enter low power mode if not actively scanned
            logging.info(
                f"[bt-tether-helper] Starting background discovery scan to keep device active..."
            )
            try:
                discovery_process = subprocess.Popen(
                    ["bluetoothctl", "scan", "on"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env=dict(os.environ, TERM="dumb", NO_COLOR="1"),
                )
            except Exception as e:
                logging.warning(
                    f"[bt-tether-helper] Could not start background discovery: {e}"
                )
                discovery_process = None

            # Wait for device to appear in BlueZ's cache before attempting pair.
            # After a device-switch disconnect, the target device may have dropped
            # from BlueZ's cache and needs to be re-discovered.
            device_visible = False
            max_scan_wait = self.PAIRING_SCAN_WAIT_TIMEOUT
            scan_start = time.time()
            logging.info(
                f"[bt-tether-helper] Waiting up to {max_scan_wait}s for {mac} to appear in scan..."
            )
            while time.time() - scan_start < max_scan_wait:
                # Check if BlueZ knows about this device
                info = self._run_cmd(
                    ["bluetoothctl", "info", mac], capture=True, timeout=3
                )
                if info and "Device" in info and "not available" not in info:
                    device_visible = True
                    break
                time.sleep(1)

            elapsed = time.time() - scan_start
            if device_visible:
                logging.info(
                    f"[bt-tether-helper] Device {mac} visible after {elapsed:.1f}s"
                )
            else:
                logging.warning(
                    f"[bt-tether-helper] Device {mac} not found after {max_scan_wait}s scan - attempting pair anyway"
                )

            with self.lock:
                self.message = "Phone found! Initiating pairing..."

            # Start monitoring agent log for passkey in background
            passkey_found = threading.Event()
            monitor_thread = threading.Thread(
                target=self._monitor_agent_log_for_passkey,
                args=(passkey_found,),
                daemon=True,
            )
            monitor_thread.start()

            # Initiate pairing from Pwnagotchi side - agent will show passkey dialog on phone
            logging.info(f"[bt-tether-helper] Running: bluetoothctl pair {mac}")
            logging.info(
                f"[bt-tether-helper] ⚠️  Pairing dialog will appear on your phone - confirm the passkey!"
            )

            try:
                # Use subprocess.Popen to capture output in real-time
                env = dict(os.environ)
                env["NO_COLOR"] = "1"
                env["TERM"] = "dumb"

                # Start pairing process
                process = subprocess.Popen(
                    ["bluetoothctl", "pair", mac],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    env=env,
                    bufsize=1,  # Line buffered
                )

                # Read output in real-time to capture passkey immediately
                output_lines = []
                passkey_found_in_output = False

                while True:
                    line = process.stdout.readline()
                    if not line:
                        # Process finished
                        break

                    output_lines.append(line)
                    clean_line = self._strip_ansi_codes(line.strip())

                    # Look for passkey in real-time
                    if not passkey_found_in_output:
                        passkey_match = re.search(
                            r"passkey\s+(\d{6})", clean_line, re.IGNORECASE
                        )
                        if passkey_match:
                            self.current_passkey = passkey_match.group(1)
                            passkey_found_in_output = True
                            self._log(
                                "WARNING",
                                f"🔑 PASSKEY: {self.current_passkey} - Confirm on phone!",
                            )
                            logging.info(
                                f"[bt-tether-helper] 🔑 PASSKEY: {self.current_passkey} captured from pair command"
                            )

                            # Update status message so it shows prominently in web UI
                            with self.lock:
                                self.status = self.STATE_PAIRING
                                self.message = f"🔑 PASSKEY: {self.current_passkey}\n\nVerify this matches on your phone, then tap PAIR!"

                        elif (
                            "Confirm passkey" in clean_line
                            or "DisplayPasskey" in clean_line
                        ):
                            # Try alternative patterns
                            display_match = re.search(r"(\d{6})", clean_line)
                            if display_match:
                                self.current_passkey = display_match.group(1)
                                passkey_found_in_output = True
                                self._log(
                                    "WARNING",
                                    f"🔑 PASSKEY: {self.current_passkey} - Confirm on phone!",
                                )
                                logging.info(
                                    f"[bt-tether-helper] 🔑 PASSKEY: {self.current_passkey} captured from pair command"
                                )

                                # Update status message so it shows prominently in web UI
                                with self.lock:
                                    self.status = self.STATE_PAIRING
                                    self.message = f"🔑 PASSKEY: {self.current_passkey}\n\nVerify this matches on your phone, then tap PAIR!"

                # Wait for process to complete
                returncode = process.wait(timeout=self.PAIRING_DIALOG_TIMEOUT)
                output = "".join(output_lines)
                clean_output = self._strip_ansi_codes(output)

                # Always stop background discovery, pairing is done
                if discovery_process:
                    try:
                        self._run_cmd(
                            ["bluetoothctl", "scan", "off"], capture=True, timeout=2
                        )
                        discovery_process.terminate()
                        discovery_process.wait(timeout=2)
                    except Exception as e:
                        logging.debug(
                            f"[bt-tether-helper] Could not stop discovery: {e}"
                        )

                # Check if pairing succeeded
                if (
                    "Pairing successful" in clean_output
                    or "AlreadyExists" in clean_output
                ):
                    logging.info(f"[bt-tether-helper] ✓ Pairing successful!")
                    # Clear passkey after successful pairing
                    self.current_passkey = None
                    return True
                elif returncode == 0:
                    # Command succeeded but output unclear - check status
                    time.sleep(2)
                    pair_status = self._check_pair_status(mac)
                    if pair_status["paired"]:
                        logging.info(f"[bt-tether-helper] ✓ Pairing successful!")
                        # Clear passkey after successful pairing
                        self.current_passkey = None
                        return True

                logging.error(f"[bt-tether-helper] Pairing failed: {clean_output}")
                return False

            except subprocess.TimeoutExpired:
                # Stop background discovery on timeout
                if discovery_process:
                    try:
                        self._run_cmd(
                            ["bluetoothctl", "scan", "off"], capture=True, timeout=2
                        )
                        discovery_process.terminate()
                        discovery_process.wait(timeout=2)
                    except Exception as e:
                        logging.debug(
                            f"[bt-tether-helper] Could not stop discovery: {e}"
                        )
                logging.error(f"[bt-tether-helper] Pairing timeout (90s)")
                return False

        except Exception as e:
            logging.error(f"[bt-tether-helper] Pairing error: {e}")
            return False

    def _send_discord_notification(self, ip_address, device_name=None):
        """Send IP address notification to Discord webhook if configured"""
        self._log(
            "INFO",
            f"Discord notification function called with IP: {ip_address}, Device: {device_name}",
        )

        if not self.discord_webhook_url:
            self._log(
                "DEBUG", "Discord webhook URL not configured, skipping notification"
            )
            return

        if not URLLIB_AVAILABLE:
            self._log(
                "WARNING", "urllib not available, cannot send Discord notification"
            )
            return

        self._log("INFO", f"Sending Discord notification to webhook...")
        try:
            pwnagotchi_name = self._get_pwnagotchi_name()
            web_url = f"http://{ip_address}:8080"
            device_display = device_name if device_name else "Unknown Device"

            data = {
                "embeds": [
                    {
                        "title": "🔷 Bluetooth Tethering Connected",
                        "description": f"**{pwnagotchi_name}** is now connected via Bluetooth\nPhone: **{device_display}**",
                        "color": 3447003,
                        "fields": [
                            {
                                "name": "Phone",
                                "value": device_display,
                                "inline": True,
                            },
                            {
                                "name": "IP Address",
                                "value": f"`{ip_address}`",
                                "inline": True,
                            },
                            {
                                "name": "Web Interface",
                                "value": web_url,
                                "inline": False,
                            },
                        ],
                        "timestamp": time.strftime(
                            "%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()
                        ),
                    }
                ]
            }

            self._log("DEBUG", f"Discord payload prepared, sending HTTP POST...")

            # Send POST request to Discord webhook
            json_data = json.dumps(data).encode("utf-8")
            req = urllib.request.Request(
                self.discord_webhook_url,
                data=json_data,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "Pwnagotchi-BT-Tether/1.0",
                },
            )

            self._log("INFO", "Sending HTTP POST to Discord webhook...")
            with urllib.request.urlopen(req, timeout=10) as response:
                status_code = response.status
                self._log("INFO", f"Discord webhook response status: {status_code}")
                if status_code == 204:
                    self._log("INFO", "✓ Discord notification sent successfully")
                else:
                    response_body = response.read().decode("utf-8")
                    self._log(
                        "WARNING",
                        f"Discord webhook returned status {status_code}: {response_body}",
                    )

        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8") if e.fp else "No response body"
            self._log("ERROR", f"Discord webhook HTTP error {e.code}: {e.reason}")
            self._log("ERROR", f"Response body: {error_body}")
        except urllib.error.URLError as e:
            self._log("ERROR", f"Discord webhook failed (network error): {e.reason}")
        except Exception as e:
            self._log("ERROR", f"Discord webhook failed: {type(e).__name__}: {e}")
            self._log("ERROR", f"Traceback: {traceback.format_exc()}")

    def _get_current_ip(self):
        """Get the current IP address from the Bluetooth PAN interface only"""
        try:
            # Only get IP from bluetooth interface - don't fall back to LAN/WiFi
            # since we're advertising the BT tethering IP
            pan_iface = self._get_pan_interface()
            if pan_iface:
                ip = self._get_interface_ip(pan_iface)
                if ip and not ip.startswith("169.254."):  # Exclude link-local
                    self._log("DEBUG", f"Found BT IP {ip} on {pan_iface}")
                    return ip

            # Also check bnep0 explicitly in case _get_pan_interface missed it
            ip = self._get_interface_ip("bnep0")
            if ip and not ip.startswith("169.254."):
                self._log("DEBUG", f"Found BT IP {ip} on bnep0")
                return ip

            self._log("DEBUG", "No IP address found on Bluetooth interface")
            return None
        except Exception as e:
            self._log("ERROR", f"Failed to get BT IP: {e}")
            return None

    # === State persistence ===

    def _get_state_file_path(self):
        """Get path for the state file, stored next to the plugin file."""
        plugin_dir = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(plugin_dir, ".bt-tether-helper.state")

    def _save_state(self):
        """Save last connected device info to disk (atomic write).

        Only writes when we have actual data. Uses write-to-tmp + rename
        to avoid corruption if the process is killed mid-write.
        """
        if not self._last_connected_mac and not self._last_connected_name:
            return
        try:
            state = {
                "last_connected_mac": self._last_connected_mac,
                "last_connected_name": self._last_connected_name,
            }
            state_file = self._get_state_file_path()
            tmp_file = state_file + ".tmp"
            with open(tmp_file, "w") as f:
                json.dump(state, f)
            os.replace(tmp_file, state_file)  # Atomic on POSIX
            self._log(
                "DEBUG",
                f"Saved state: {self._last_connected_name} ({self._last_connected_mac})",
            )
        except Exception as e:
            self._log("DEBUG", f"Failed to save state: {e}")

    def _load_state(self):
        """Load last connected device info from disk."""
        try:
            state_file = self._get_state_file_path()
            if os.path.exists(state_file):
                with open(state_file, "r") as f:
                    state = json.load(f)
                self._last_connected_mac = state.get("last_connected_mac")
                self._last_connected_name = state.get("last_connected_name")
                self._log(
                    "INFO",
                    f"Restored last connected device: {self._last_connected_name} ({self._last_connected_mac})",
                )
        except Exception as e:
            self._log("DEBUG", f"Failed to load state: {e}")

    def _get_pwnagotchi_name(self):
        """Get pwnagotchi name from config.toml"""
        try:
            import toml

            config_path = "/etc/pwnagotchi/config.toml"
            if os.path.exists(config_path):
                with open(config_path, "r") as f:
                    config = toml.load(f)
                    name = config.get("main", {}).get("name", "pwnagotchi")
                    return name
        except Exception as e:
            self._log("DEBUG", f"Failed to read pwnagotchi name: {e}")

        return "pwnagotchi"

    def _set_device_name(self):
        """Set the Bluetooth device name via bluetoothctl"""
        try:
            pwnagotchi_name = self._get_pwnagotchi_name()
            cmd = ["bluetoothctl", "set-alias", pwnagotchi_name]
            result = self._run_cmd(cmd, timeout=5)
            self._log("INFO", f"Set Bluetooth device name to: {pwnagotchi_name}")
        except Exception as e:
            self._log("WARNING", f"Failed to set device name: {e}")

    def _connect_nap_dbus(self, mac):
        """Connect to NAP service using the BlueZ Network1 D-Bus interface.

        Uses org.bluez.Network1.Connect("nap") — the proper high-level BlueZ API
        for PAN connections.  This lets BlueZ manage the BNEP bridge lifecycle
        internally, which makes device switching much cleaner than the lower-level
        Device1.ConnectProfile(NAP_UUID) approach.

        Network1.Connect("nap") returns the interface name (e.g. "bnep0") on
        success, so we no longer need to poll for the interface separately.

        Falls back to Device1.ConnectProfile(NAP_UUID) only if Network1 is
        unavailable (older BlueZ or device not yet resolved).
        """
        try:
            if not DBUS_AVAILABLE:
                logging.error("[bt-tether-helper] dbus module not available")
                return False

            logging.info("[bt-tether-helper] Connecting to system bus...")
            bus = dbus.SystemBus()
            manager = dbus.Interface(
                bus.get_object("org.bluez", "/"), "org.freedesktop.DBus.ObjectManager"
            )
            logging.info("[bt-tether-helper] System bus connected")

            # Find the device object path and check for Network1 interface
            logging.info("[bt-tether-helper] Searching for device in BlueZ...")
            objects = manager.GetManagedObjects()
            device_path = None
            has_network1 = False
            for path, interfaces in objects.items():
                if "org.bluez.Device1" in interfaces:
                    props = interfaces["org.bluez.Device1"]
                    if props.get("Address") == mac:
                        device_path = path
                        has_network1 = "org.bluez.Network1" in interfaces
                        logging.info(
                            f"[bt-tether-helper] Found device at path: {device_path} "
                            f"(Network1: {has_network1})"
                        )
                        break

            if not device_path:
                logging.error(
                    f"[bt-tether-helper] Device {mac} not found in BlueZ managed objects"
                )
                return False

            # ── Pre-flight: handle stale Network1 BNEP bridge ──
            # If BlueZ reports an active Network1 connection (= BNEP bridge
            # still held by this device from a previous session), tear it
            # down first so our new Network1.Connect() doesn't conflict.
            # We intentionally do NOT disconnect the ACL link or send any
            # bluetoothctl disconnect — keeping the ACL alive means the
            # phone's tethering DHCP server stays running and will respond
            # immediately on the next PAN connection.
            try:
                dev_ifaces = objects.get(device_path, {})
                net_connected = False
                if "org.bluez.Network1" in dev_ifaces:
                    net_connected = bool(
                        dev_ifaces["org.bluez.Network1"].get("Connected", False)
                    )
                if net_connected and has_network1:
                    logging.warning(
                        f"[bt-tether-helper] {mac} has stale Network1 bridge — "
                        "tearing it down (keeping ACL alive)..."
                    )
                    try:
                        stale_net = dbus.Interface(
                            bus.get_object("org.bluez", device_path),
                            "org.bluez.Network1",
                        )
                        t = threading.Thread(
                            target=lambda n=stale_net: n.Disconnect(),
                            daemon=True,
                        )
                        t.start()
                        t.join(timeout=5)
                    except Exception:
                        pass
                    time.sleep(1)
                else:
                    logging.debug(
                        f"[bt-tether-helper] {mac} has no stale Network1 bridge"
                    )
            except Exception as e:
                logging.debug(f"[bt-tether-helper] Pre-connect check: {e}")

            # ── Primary path: Network1.Connect("nap") ──
            # This is the canonical BlueZ API for PAN/NAP connections.
            # It handles the BNEP bridge lifecycle internally and returns
            # the interface name on success.
            if has_network1:
                logging.info(
                    '[bt-tether-helper] Using Network1.Connect("nap") — '
                    "BlueZ will manage the BNEP bridge..."
                )
                try:
                    network = dbus.Interface(
                        bus.get_object("org.bluez", device_path),
                        "org.bluez.Network1",
                    )
                    # Network1.Connect returns the network interface name (e.g. "bnep0")
                    iface_name = network.Connect(
                        "nap", timeout=self.NAP_DBUS_CONNECT_TIMEOUT
                    )
                    iface_name = str(iface_name)
                    logging.info(
                        f'[bt-tether-helper] ✓ Network1.Connect("nap") succeeded — '
                        f"interface: {iface_name}"
                    )
                    # Store the interface name so callers can skip polling
                    self._nap_interface = iface_name
                    return True
                except dbus.exceptions.DBusException as dbus_err:
                    error_msg = str(dbus_err)
                    logging.warning(
                        f"[bt-tether-helper] Network1.Connect failed: {error_msg[:120]}"
                    )
                    # If Network1 gave a meaningful error, handle it the same
                    # way we would for ConnectProfile — fall through to error
                    # handling below.
                    # But if it's a transient D-Bus error, try ConnectProfile as fallback.
                    if any(
                        kw in error_msg
                        for kw in (
                            "NotAvailable",
                            "profile-unavailable",
                            "Rejected",
                            "Denied",
                        )
                    ):
                        # These are definitive failures — don't retry with fallback
                        pass
                    else:
                        # Transient / unknown — try ConnectProfile to warm the link,
                        # then retry Network1.Connect which creates the BNEP bridge.
                        # ConnectProfile alone does NOT create a network interface.
                        logging.info(
                            "[bt-tether-helper] Falling back to Device1.ConnectProfile to warm BT link..."
                        )
                        connect_profile_ok = False
                        try:
                            device = dbus.Interface(
                                bus.get_object("org.bluez", device_path),
                                "org.bluez.Device1",
                            )
                            device.ConnectProfile(
                                self.NAP_UUID, timeout=self.NAP_DBUS_CONNECT_TIMEOUT
                            )
                            logging.info(
                                "[bt-tether-helper] ✓ ConnectProfile succeeded (BT link active)"
                            )
                            connect_profile_ok = True
                        except dbus.exceptions.DBusException as fallback_err:
                            error_msg = str(fallback_err)
                            logging.warning(
                                f"[bt-tether-helper] ConnectProfile fallback also failed: "
                                f"{error_msg[:120]}"
                            )

                        # ConnectProfile only establishes the Bluetooth transport —
                        # it does NOT create the BNEP network bridge.  Now that the
                        # ACL link is warm, retry Network1.Connect which actually
                        # creates bnep0.
                        if connect_profile_ok and has_network1:
                            logging.info(
                                "[bt-tether-helper] Retrying Network1.Connect now that BT link is warm..."
                            )
                            time.sleep(1)  # Brief settle after ConnectProfile
                            try:
                                network = dbus.Interface(
                                    bus.get_object("org.bluez", device_path),
                                    "org.bluez.Network1",
                                )
                                iface_name = network.Connect(
                                    "nap", timeout=self.NAP_DBUS_WARM_RETRY_TIMEOUT
                                )
                                iface_name = str(iface_name)
                                logging.info(
                                    f'[bt-tether-helper] ✓ Network1.Connect (warm retry) succeeded — '
                                    f'interface: {iface_name}'
                                )
                                self._nap_interface = iface_name
                                return True
                            except dbus.exceptions.DBusException as warm_err:
                                logging.warning(
                                    f"[bt-tether-helper] Network1.Connect warm retry failed: "
                                    f"{str(warm_err)[:120]}"
                                )
                                # Still return True so caller can poll for bnep0 —
                                # the BT link is up, interface may appear with delay
                                self._nap_interface = None
                                return True
                        elif connect_profile_ok:
                            # Network1 not available, ConnectProfile is all we have
                            self._nap_interface = None  # need to poll for interface
                            return True

                    # Fall through to error handling with the final error_msg
                    self._format_nap_error(error_msg)
                    self._last_nap_error = error_msg
                    return False
            else:
                # ── Fallback: Device1.ConnectProfile ──
                # Network1 interface not yet available (device not fully resolved,
                # older BlueZ, or first connection before profiles are registered).
                logging.info(
                    f"[bt-tether-helper] Network1 not available on {mac}, "
                    f"falling back to Device1.ConnectProfile(NAP_UUID)..."
                )
                try:
                    device = dbus.Interface(
                        bus.get_object("org.bluez", device_path),
                        "org.bluez.Device1",
                    )
                    device.ConnectProfile(
                        self.NAP_UUID, timeout=self.NAP_DBUS_CONNECT_TIMEOUT
                    )
                    logging.info(
                        "[bt-tether-helper] ✓ NAP profile connected via ConnectProfile"
                    )
                    self._nap_interface = None  # need to poll for interface
                    return True
                except dbus.exceptions.DBusException as dbus_err:
                    error_msg = str(dbus_err)
                    self._format_nap_error(error_msg)
                    self._last_nap_error = error_msg
                    return False

        except ImportError as e:
            logging.error(f"[bt-tether-helper] python3-dbus not installed: {e}")
            return False
        except Exception as e:
            logging.error(
                f"[bt-tether-helper] NAP connection error: {type(e).__name__}: {e}"
            )
            return False

    def _format_nap_error(self, error_msg):
        """Log user-friendly error messages for common NAP connection failures."""
        if "NotAvailable" in error_msg or "profile-unavailable" in error_msg:
            self._log(
                "ERROR",
                "⚠️ Bluetooth tethering NOT enabled on your phone!",
            )
            self._log(
                "ERROR",
                "Enable: Settings → Network & internet → Hotspot & tethering → Bluetooth tethering",
            )
        elif "Rejected" in error_msg or "Denied" in error_msg:
            self._log(
                "ERROR",
                "⚠️ Phone rejected the NAP connection request",
            )
            self._log(
                "ERROR",
                "Try: Unpair from phone, disable/enable Bluetooth tethering, re-pair",
            )
        elif "Timeout" in error_msg or "NoReply" in error_msg:
            self._log(
                "ERROR",
                "⚠️ Phone not responding to NAP request",
            )
            self._log(
                "ERROR",
                "Phone may be in low power mode or tethering is disabled",
            )
        else:
            self._log("ERROR", f"NAP connection error: {error_msg[:100]}")

    def _get_interface_type(self, interface):
        """Identify the type of network interface"""
        if interface.startswith("bnep"):
            return "Bluetooth PAN"
        elif interface.startswith("usb"):
            return "USB Tethering"
        elif interface.startswith("eth"):
            return "Ethernet"
        elif interface.startswith("wlan"):
            return "Wi-Fi"
        elif interface.startswith("wg"):
            return "WireGuard VPN"
        elif interface.startswith("tun"):
            return "TUN VPN"
        elif interface.startswith("docker"):
            return "Docker"
        else:
            return "Unknown"

    def _get_network_metrics(self):
        """Get current network routing metrics for web UI display"""
        try:
            result = subprocess.check_output(
                ["ip", "route", "show", "default"], text=True, timeout=5
            )
            routes = []
            for line in result.strip().split("\n"):
                if "default" in line:
                    dev_match = re.search(r"dev\s+(\S+)", line)
                    metric_match = re.search(r"metric\s+(\d+)", line)
                    gateway_match = re.search(r"via\s+(\S+)", line)
                    if dev_match:
                        iface = dev_match.group(1)
                        metric = int(metric_match.group(1)) if metric_match else 0
                        gateway = gateway_match.group(1) if gateway_match else "N/A"

                        # Skip invalid/transient routes
                        # Skip if no valid gateway found (skip "N/A" entries)
                        # Skip IPv4LL routes (169.254.x.x)
                        # Skip routes with extremely high metrics (> 500000, likely placeholders)
                        if (
                            gateway != "N/A"
                            and not gateway.startswith("169.254.")
                            and metric <= self.ROUTE_METRIC_MAX_FILTER
                        ):
                            routes.append(
                                {
                                    "interface": iface,
                                    "type": self._get_interface_type(iface),
                                    "metric": metric,
                                    "gateway": gateway,
                                    "is_primary": False,
                                }
                            )

            # Sort by metric and mark primary
            if routes:
                routes = sorted(routes, key=lambda x: x["metric"])
                routes[0]["is_primary"] = True

            # Get current Bluetooth status
            bt_status = {"connected": False, "interface": None, "metric": None}

            if self.phone_mac:
                status = self._get_current_status(self.phone_mac)
                if status.get("pan_active") and status.get("interface"):
                    bt_status["connected"] = True
                    bt_status["interface"] = status.get("interface")
                    # Find BT metric in routes
                    bt_route = next(
                        (
                            r
                            for r in routes
                            if r["interface"] == status.get("interface")
                        ),
                        None,
                    )
                    if bt_route:
                        bt_status["metric"] = bt_route["metric"]

            return {
                "success": True,
                "routes": routes,
                "bluetooth_status": bt_status,
                "total_routes": len(routes),
            }

        except Exception as e:
            logging.debug(f"[bt-tether-helper] Failed to get network metrics: {e}")
            return {
                "success": False,
                "error": str(e),
                "routes": [],
                "bluetooth_status": {"connected": False},
                "total_routes": 0,
            }
