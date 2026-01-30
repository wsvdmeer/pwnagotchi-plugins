"""
Bluetooth Tether Helper Plugin for Pwnagotchi

Required System Packages:
    sudo apt-get update
    sudo apt-get install -y bluez network-manager python3-dbus python3-toml

Features:
- Bluetooth tethering to mobile phones (iOS & Android)
- Auto-discovery of trusted devices with tethering capability
- Signal strength (RSSI) based auto-selection of best device
- Works with Android MAC randomization (no fixed MAC needed)
- Auto-reconnect functionality
- Web UI for easy device pairing and management
- Per-device connect/disconnect controls
- Signal strength indicators for each device

Setup:
1. Install packages: sudo apt-get install -y bluez network-manager python3-dbus python3-toml
2. Enable services:
   sudo systemctl enable bluetooth && sudo systemctl start bluetooth
   sudo systemctl enable NetworkManager && sudo systemctl start NetworkManager
3. Access web UI at http://<pwnagotchi-ip>:8080/plugins/bt-tether-helper
4. Scan and pair your phones - plugin auto-selects best signal!

Configuration options:
- main.plugins.bt-tether-helper.auto_reconnect = true  # Auto reconnect on disconnect (default: true)
- main.plugins.bt-tether-helper.show_on_screen = true  # Master switch: Show status on display (disables both mini and detailed when false)
- main.plugins.bt-tether-helper.show_mini_status = true  # Show mini status indicator (single letter: C/N/P/D)
- main.plugins.bt-tether-helper.mini_status_position = null  # Position for mini status (null = auto top-right)
- main.plugins.bt-tether-helper.show_detailed_status = true  # Show detailed status line with IP
- main.plugins.bt-tether-helper.detailed_status_position = [0, 82]  # Position for detailed status line
- main.plugins.bt-tether-helper.discord_webhook_url = "https://discord.com/api/webhooks/..."  # Discord webhook for IP notifications (optional)
"""

import subprocess
import threading
import time
import logging
import os
import re
import traceback
import json
import socket
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
      button { padding: 10px 20px; background: transparent; color: #3fb950; border: 1px solid #3fb950; cursor: pointer; font-size: 14px; border-radius: 4px; margin-right: 8px; min-height: 42px; display: inline-flex; align-items: center; justify-content: center; }
      button:hover { background: rgba(63, 185, 80, 0.1); border-color: #3fb950; }
      button.danger { color: #f85149; border-color: #f85149; background: transparent; }
      button.danger:hover { background: rgba(248, 81, 73, 0.1); border-color: #f85149; }
      button.success { color: #3fb950; border-color: #3fb950; background: transparent; }
      button.success:hover { background: rgba(63, 185, 80, 0.1); border-color: #3fb950; }
      button:disabled { background: transparent; color: #8b949e; cursor: not-allowed; border-color: #30363d; }
      .status-item { padding: 8px; margin: 4px 0; border-radius: 4px; background: #161b22; border: 1px solid #30363d; color: #d4d4d4; }
      .status-good { background: rgba(46, 160, 67, 0.15); color: #3fb950; border-color: #3fb950; }
      .status-bad { background: rgba(248, 81, 73, 0.15); color: #f85149; border-color: #f85149; }
      .device-item { padding: 12px; margin: 8px 0; border: 1px solid #30363d; border-radius: 4px; cursor: pointer; display: flex; justify-content: space-between; align-items: center; background: #0d1117; color: #d4d4d4; }
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
      @media (max-width: 600px) {
        .mac-editor { flex-direction: column; align-items: stretch; }
        .mac-editor input { width: 100%; }
        .mac-editor button { width: 100%; margin: 0 !important; }
      }
    </style>
  </head>
  <body>
    <h2>🔷 Bluetooth Tether</h2>
    
    <!-- Phone Connection & Status -->
    <div class="card" id="phoneConnectionCard">
      <h3 style="margin: 0 0 12px 0;">📊 Connection Status</h3>
      
      <!-- Network Routes & Metrics -->
      <div id="networkMetricsInfo" style="background: #0d1117; color: #d4d4d4; padding: 12px; border-radius: 4px; margin-bottom: 12px; font-family: 'Courier New', monospace; font-size: 12px; line-height: 1.5;">
        <div style="color: #888; margin-bottom: 8px;">📊 Network Routes (sorted by priority):</div>
        <div id="networkMetricsContent" style="font-size: 13px;">
          <div style="color: #888;">Fetching metrics...</div>
        </div>
      </div>
      
      <!-- Status in output style -->
      <div style="background: #0d1117; color: #d4d4d4; padding: 12px; border-radius: 4px; margin-bottom: 12px; font-family: 'Courier New', monospace; font-size: 12px; line-height: 1.5;">
        <div id="statusDeviceName" style="margin: 0 0 8px 0; padding-bottom: 8px; border-bottom: 1px solid #30363d; display: none;">
          <span style="color: #888;">Device:</span> <span id="statusDeviceNameValue" style="color: #58a6ff;">Unknown</span>
        </div>
        <div id="statusActiveConnection" style="display: none; margin: 4px 0; padding: 8px; background: rgba(78, 201, 176, 0.1); border-left: 3px solid #4ec9b0; margin-bottom: 8px;"></div>
        <div id="statusPaired" style="margin: 4px 0;">📱 Paired: <span>Checking...</span></div>
        <div id="statusTrusted" style="margin: 4px 0;">🔐 Trusted: <span>Checking...</span></div>
        <div id="statusConnected" style="margin: 4px 0;">🔵 Connected: <span>Checking...</span></div>
        <div id="statusInternet" style="margin: 4px 0;">🌐 Internet: <span>Checking...</span></div>
        <div id="statusIP" style="display: none; margin: 4px 0;">🔢 IP Address: <span></span></div>
      </div>
      
      <!-- Hidden input for JavaScript to access MAC value -->
      <input type="hidden" id="macInput" value="{{ mac }}" />
      
      <!-- Trusted Devices (inside Connection Status card) -->
      <div style="margin-bottom: 12px;">
        <h4 style="margin: 0 0 8px 0; color: #8b949e; font-size: 14px;">📱 Trusted Devices</h4>
        <div id="trustedDevicesList"></div>
        <!-- Scan Results (shown when scanning) -->
        <div id="scanResultsCard" style="display: none; margin-top: 12px;">
          <h4 style="margin: 0 0 8px 0; color: #8b949e; font-size: 14px;">🔍 Discovered Devices</h4>
          <div id="scanStatus" style="color: #8b949e; margin: 8px 0; font-size: 13px;">Scanning...</div>
          <div id="deviceList"></div>
        </div>
      </div>
      
      <!-- Output Section -->
      <div style="margin-bottom: 12px;">
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
      <h3 style="margin: 0 0 12px 0;">🔍 Test Internet Connectivity</h3>
      <button onclick="testInternet()" id="testInternetBtn" style="width: 100%; margin: 0 0 12px 0;">
        🔍 Test Internet Connectivity
      </button>
      
      <!-- Test Results -->
      <div id="testResults" style="display: none;">
        <div id="testResultsMessage" class="message-box message-info"></div>
      </div>
    </div>
    
    <script>
      const macInput = document.getElementById("macInput");
      let statusInterval = null;
      let isDisconnecting = false;  // Track if disconnect is in progress
      let logInterval = null;
      let lastMetricsState = null;  // Track last metrics state to avoid unnecessary updates
      let lastTrustedDevicesState = null;  // Track trusted devices state for refresh triggers

      // Load trusted devices and network metrics on page load
      loadTrustedDevicesList();
      loadNetworkMetrics();
      
      // Show initializing state first
      setInitializingStatus();
      // Then check actual connection status
      setTimeout(checkConnectionStatus, 1000);
      
      // Start log polling immediately
      refreshLogs();
      startLogPolling();

      function setInitializingStatus() {
        document.getElementById("statusPaired").innerHTML = 
          `📱 Paired: <span style="color: #8b949e;">🔄 Initializing...</span>`;
        
        document.getElementById("statusTrusted").innerHTML = 
          `🔐 Trusted: <span style="color: #8b949e;">🔄 Initializing...</span>`;
        
        document.getElementById("statusConnected").innerHTML = 
          `🔵 Connected: <span style="color: #8b949e;">🔄 Initializing...</span>`;
        
        document.getElementById("statusInternet").innerHTML = 
          `🌐 Internet: <span style="color: #8b949e;">🔄 Initializing...</span>`;
        
        document.getElementById('statusIP').style.display = 'none';
        document.getElementById('statusActiveConnection').style.display = 'none';
      }

      async function checkConnectionStatus() {
        const mac = macInput.value.trim();
        if (!/^([0-9A-F]{2}:){5}[0-9A-F]{2}$/i.test(mac)) {
          // No valid MAC in input - try to get from backend status
          try {
            const statusResponse = await fetch(`/plugins/bt-tether-helper/status`);
            const statusData = await statusResponse.json();
            
            // If backend has a current MAC, use it
            if (statusData.mac && /^([0-9A-F]{2}:){5}[0-9A-F]{2}$/i.test(statusData.mac)) {
              // We have a MAC from backend, check its status
              const response = await fetch(`/plugins/bt-tether-helper/connection-status?mac=${encodeURIComponent(statusData.mac)}`);
              const data = await response.json();
              
              // Update UI with backend MAC
              macInput.value = statusData.mac;
              updateStatusDisplay(statusData, data);
              return;
            }
          } catch (err) {
            console.error('Failed to get backend status:', err);
          }
          
          // No valid MAC - show disconnected state
          const disconnectSection = document.getElementById('disconnectSection');
          if (disconnectSection) disconnectSection.style.display = 'none';
          
          // Update status to show disconnected/no device state
          document.getElementById("statusPaired").innerHTML = 
            `📱 Paired: <span style="color: #f48771;">✗ No</span>`;
          
          document.getElementById("statusTrusted").innerHTML = 
            `🔐 Trusted: <span style="color: #f48771;">✗ No</span>`;
          
          document.getElementById("statusConnected").innerHTML = 
            `🔵 Connected: <span style="color: #f48771;">✗ No</span>`;
          
          document.getElementById("statusInternet").innerHTML = 
            `🌐 Internet: <span style="color: #f48771;">✗ Not Active</span>`;
          
          document.getElementById('statusIP').style.display = 'none';
          document.getElementById('statusActiveConnection').style.display = 'none';
          
          return;
        }
        
        try {
          // First check the plugin's internal status
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
        // Update device name display
        const deviceNameDiv = document.getElementById('statusDeviceName');
        const deviceNameValue = document.getElementById('statusDeviceNameValue');
        if (data.device_name || statusData.mac) {
          deviceNameDiv.style.display = 'block';
          deviceNameValue.textContent = data.device_name ? `${data.device_name} (${statusData.mac})` : statusData.mac;
        } else {
          deviceNameDiv.style.display = 'none';
        }
        
        // Check if metrics state has changed before updating
        const currentMetricsState = `${data.connected}-${data.pan_active}-${data.interface}`;
        if (currentMetricsState !== lastMetricsState) {
          lastMetricsState = currentMetricsState;
          loadNetworkMetrics();
        }
        
        // If disconnecting or untrusting, show transitional state immediately
        if (statusData.disconnecting || isDisconnecting) {
          document.getElementById("statusPaired").innerHTML = 
            `📱 Paired: <span style="color: #f0883e;">⏳ Disconnecting...</span>`;
          
          document.getElementById("statusTrusted").innerHTML = 
            `🔐 Trusted: <span style="color: #f0883e;">⏳ Disconnecting...</span>`;
          
          document.getElementById("statusConnected").innerHTML = 
            `🔵 Connected: <span style="color: #f0883e;">⏳ Disconnecting...</span>`;
          
          document.getElementById("statusInternet").innerHTML = 
            `🌐 Internet: <span style="color: #f0883e;">⏳ Disconnecting...</span>`;
          
          document.getElementById('statusIP').style.display = 'none';
          document.getElementById('statusActiveConnection').style.display = 'none';
          
          // Hide test card during disconnect
          const testInternetCard = document.getElementById('testInternetCard');
          testInternetCard.style.display = 'none';
          
          return;  // Don't process further updates during disconnect
        }
        
        // Determine screen status letter (C/N/P/D)
        let screenStatus = 'D';
        if (data.pan_active) {
          screenStatus = 'C';  // Connected with internet
        } else if (data.connected) {
          screenStatus = 'N';  // Connected but no internet
        } else if (data.paired) {
          screenStatus = 'P';  // Paired but not connected
        }
        
        document.getElementById("statusPaired").innerHTML = 
          `📱 Paired: <span style="color: ${data.paired ? '#4ec9b0' : '#f48771'};">${data.paired ? '✓ Yes' : '✗ No'}</span>`;
        
        document.getElementById("statusTrusted").innerHTML = 
          `🔐 Trusted: <span style="color: ${data.trusted ? '#4ec9b0' : '#f48771'};">${data.trusted ? '✓ Yes' : '✗ No'}</span>`;
        
        document.getElementById("statusConnected").innerHTML = 
          `🔵 Connected: <span style="color: ${data.connected ? '#4ec9b0' : '#f48771'};">${data.connected ? '✓ Yes' : '✗ No'}</span>`;
        
        document.getElementById("statusInternet").innerHTML = 
          `🌐 Internet: <span style="color: ${data.pan_active ? '#4ec9b0' : '#f48771'};">${data.pan_active ? '✓ Active' : '✗ Not Active'}</span>${data.interface ? ` <span style="color: #888;">(${data.interface})</span>` : ''}`;
        
        // Show/hide test internet card based on connection status
        // Don't show if we're actively disconnecting
        const testInternetCard = document.getElementById('testInternetCard');
        if (data.pan_active && !isDisconnecting) {
          testInternetCard.style.display = 'block';
        } else {
          testInternetCard.style.display = 'none';
        }
        
        // Show IP address if available
        const statusIPElement = document.getElementById('statusIP');
        if (data.ip_address && data.pan_active) {
          statusIPElement.style.display = 'block';
          statusIPElement.innerHTML = `🔢 IP Address: <span style="color: #4ec9b0;">${data.ip_address}</span>`;
        } else {
          statusIPElement.style.display = 'none';
        }
        
        // Show active connection type inside status card
        const statusActiveConnection = document.getElementById('statusActiveConnection');
        
        if (data.default_route_interface) {
          const isUsingBluetooth = data.default_route_interface === data.interface;
          
          // Determine connection type and details
          let connType = 'Unknown';
          let connEmoji = '🔌';
          let connDetails = '';
          
          if (data.default_route_interface.startsWith('usb')) {
            connType = 'USB Tethering';
            connEmoji = '🔌';
            if (data.pan_active && !isUsingBluetooth) {
              connDetails = '<div style="color: #ce9178; margin-top: 4px; font-size: 11px;">💡 Bluetooth is on standby • USB has priority due to higher speed</div>';
            }
          } else if (data.default_route_interface.startsWith('bnep')) {
            connType = 'Bluetooth Tethering';
            connEmoji = '📱';
          } else if (data.default_route_interface.startsWith('eth')) {
            connType = 'Ethernet';
            connEmoji = '🌐';
            if (data.pan_active) {
              connDetails = '<div style="color: #ce9178; margin-top: 4px; font-size: 11px;">💡 Bluetooth is on standby • Ethernet is active</div>';
            }
          } else if (data.default_route_interface.startsWith('wlan')) {
            connType = 'Wi-Fi';
            connEmoji = '📶';
            if (data.pan_active) {
              connDetails = '<div style="color: #ce9178; margin-top: 4px; font-size: 11px;">💡 Bluetooth is on standby • Wi-Fi is active</div>';
            }
          }
          
          if (statusActiveConnection) {
            statusActiveConnection.style.display = 'block';
            statusActiveConnection.innerHTML = `${connEmoji} <span style="color: #4ec9b0; font-weight: bold;">${connType}</span> <span style="color: #888;">(${data.default_route_interface})</span>${connDetails}`;
          }
        } else {
          if (statusActiveConnection) {
            statusActiveConnection.style.display = 'none';
          }
        }
        
        // Manage polling based on connection state
        if (statusData.status === 'PAIRING' || statusData.status === 'TRUSTING' || statusData.status === 'CONNECTING' || statusData.status === 'RECONNECTING' || statusData.connection_in_progress) {
          // Actively connecting - poll faster (every 2 seconds)
          if (!statusInterval || statusInterval._interval !== 2000) {
            console.log('Connection in progress - fast polling (2s)');
            stopStatusPolling();
            statusInterval = setInterval(checkConnectionStatus, 2000);
            statusInterval._interval = 2000;
          }
        } else if (data.connected || data.paired) {
          // Connected or paired - poll slower (every 10 seconds) to keep status updated
          if (!statusInterval || statusInterval._interval !== 10000) {
            console.log('Connected/paired - slow polling (10s)');
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
        
        // Update button states - show/hide disconnect section based on connection status
        const disconnectSection = document.getElementById('disconnectSection');
        
        // Check if ANY operation is in progress
        const operationInProgress = statusData.disconnecting || statusData.untrusting || statusData.connection_in_progress || statusData.status === 'PAIRING' || statusData.status === 'TRUSTING' || statusData.status === 'CONNECTING' || statusData.status === 'RECONNECTING';
        
        // Set disconnect section visibility based on current status
        if (statusData.disconnecting || statusData.untrusting || operationInProgress) {
          // Hide disconnect section during operations
          if (disconnectSection) disconnectSection.style.display = 'none';
        } else if (data.connected) {
          // Show disconnect section when connected
          if (disconnectSection) disconnectSection.style.display = 'block';
        } else {
          // Hide disconnect section when not connected
          if (disconnectSection) disconnectSection.style.display = 'none';
        }
        
        // Refresh trusted devices when relevant state changes
        // Track: connection status, current MAC, paired/trusted state, and operation states
        const currentTrustedState = JSON.stringify({
          mac: statusData.mac,
          connected: data.connected,
          paired: data.paired,
          trusted: data.trusted,
          connecting: statusData.connection_in_progress,
          status: statusData.status
        });
        
        if (currentTrustedState !== lastTrustedDevicesState) {
          lastTrustedDevicesState = currentTrustedState;
          loadTrustedDevicesList();
        }
      }

      function startStatusPolling() {
        if (statusInterval) clearInterval(statusInterval);
        // Poll every 2 seconds during connection - passkey is shown in logs
        statusInterval = setInterval(checkConnectionStatus, 2000);
      }

      function stopStatusPolling() {
        if (statusInterval) {
          clearInterval(statusInterval);
          statusInterval = null;
        }
      }

      let scanAborted = false;  // Flag to abort scan loop when pairing starts

      async function scanDevices() {
        const scanBtn = document.getElementById('scanBtn');
        const scanResultsCard = document.getElementById('scanResultsCard');
        const scanStatus = document.getElementById('scanStatus');
        const deviceList = document.getElementById('deviceList');
        
        scanAborted = false;  // Reset abort flag
        scanBtn.disabled = true;
        scanBtn.innerHTML = '<span class="spinner"></span> Scanning...';
        scanResultsCard.style.display = 'block';
        deviceList.innerHTML = '';
        scanStatus.innerHTML = '<span class="spinner"></span> Scanning for devices... (30 seconds)';
        
        showFeedback("Scanning for devices... Keep phone Bluetooth settings open!", "info");
        
        try {
          // Start the background scan
          const response = await fetch('/plugins/bt-tether-helper/scan', { method: 'GET' });
          let data = await response.json();
          
          // Poll for results every 1 second and update UI as devices appear
          let pollCount = 0;
          const maxPolls = 32; // Poll for up to 32 seconds (32 * 1s)
          let lastDeviceCount = 0;
          
          while (pollCount < maxPolls && !scanAborted) {
            pollCount++;
            await new Promise(resolve => setTimeout(resolve, 1000)); // Wait 1 second
            
            // Check if scan was aborted (e.g., pairing started)
            if (scanAborted) {
              scanStatus.textContent = 'Scan stopped - pairing in progress';
              break;
            }
            
            // Poll for updated results
            try {
              const pollResponse = await fetch('/plugins/bt-tether-helper/scan', { method: 'GET' });
              data = await pollResponse.json();
              
              // Update device list if new devices found
              if (data.devices && data.devices.length > lastDeviceCount) {
                lastDeviceCount = data.devices.length;
                deviceList.innerHTML = '';
                data.devices.forEach(device => {
                  const div = document.createElement('div');
                  div.className = 'device-item';
                  div.innerHTML = `
                    <div>
                      <b>${device.name}</b><br>
                      <small style="color: #666;">${device.mac}</small>
                    </div>
                    <button onclick="pairAndConnectDevice('${device.mac}', '${device.name.replace(/'/g, "\\'")}'); return false;" class="success" style="margin: 0;">🔗 Pair</button>
                  `;
                  deviceList.appendChild(div);
                });
                scanStatus.innerHTML = `<span class="spinner"></span> Found ${data.devices.length} device(s)... still scanning`;
              } else if (data.devices && data.devices.length === 0) {
                const elapsed = pollCount;
                scanStatus.innerHTML = `<span class="spinner"></span> Scanning... (${Math.max(30 - elapsed, 0)}s remaining)`;
              }
            } catch (e) {
              console.log('Poll error:', e);
            }
          }
          
          // Final update after scan completes (only if not aborted)
          if (!scanAborted) {
            if (data.devices && data.devices.length > 0) {
              scanStatus.textContent = `Scan complete - Found ${data.devices.length} device(s):`;
              showFeedback(`Found ${data.devices.length} device(s). Click Pair to connect!`, "success");
            } else {
              scanStatus.textContent = 'Scan complete - No devices found';
              deviceList.innerHTML = '';
              showFeedback("No devices found. Make sure phone Bluetooth is ON and visible.", "warning");
            }
          }
        } catch (error) {
          scanStatus.textContent = 'Scan failed';
          showFeedback("Scan failed: " + error.message, "error");
        } finally {
          scanBtn.disabled = false;
          scanBtn.innerHTML = '🔍 Scan';
        }
      }

      async function loadTrustedDevicesList() {
        try {
          const response = await fetch('/plugins/bt-tether-helper/trusted-devices');
          const data = await response.json();
          
          const listDiv = document.getElementById('trustedDevicesList');
          const statusArea = document.getElementById('networkMetricsInfo').parentElement.querySelector('div:nth-child(2)');
          const networkMetrics = document.getElementById('networkMetricsInfo');
          
          // Scan button HTML to append
          const scanButtonHtml = `
            <button class="success" onclick="scanDevices()" id="scanBtn" style="width: 100%; margin-top: 12px;">
              🔍 Scan for Devices
            </button>
          `;
          
          if (data.devices && data.devices.length > 0) {
            const napDevices = data.devices.filter(d => d.has_nap);
            
            // Show status area when we have devices
            if (networkMetrics) networkMetrics.style.display = 'block';
            if (statusArea) statusArea.style.display = 'block';
            
            if (napDevices.length > 0) {
              listDiv.innerHTML = napDevices.map(device => {
                const isConnected = device.connected;
                const statusColor = isConnected ? '#3fb950' : '#8b949e';
                const statusIcon = isConnected ? '🔵' : '⚪';
                const statusText = isConnected ? 'Connected' : (device.trusted ? 'Paired & Trusted' : 'Paired');
                const btnId = `connect-btn-${device.mac.replace(/:/g, '')}`;
                
                return `
                  <div style="background: #0d1117; border: 1px solid ${isConnected ? '#3fb950' : '#30363d'}; border-radius: 4px; padding: 12px; margin-bottom: 8px;">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                      <div style="flex: 1;">
                        <div style="font-size: 14px; color: #d4d4d4; font-weight: 500;">
                          ${statusIcon} ${device.name}
                        </div>
                        <div style="font-size: 12px; color: #888; font-family: 'Courier New', monospace; margin-top: 4px;">
                          ${device.mac}
                        </div>
                        <div style="font-size: 12px; color: ${statusColor}; margin-top: 4px;">
                          ${statusText}
                        </div>
                      </div>
                      <div style="display: flex; gap: 8px; flex-wrap: wrap;">
                        ${!isConnected ? 
                          `<button class="success" id="${btnId}" onclick="connectToDevice('${device.mac}')" style="min-width: 100px;">
                            ⚡ Connect
                          </button>` : ''
                        }
                        <button class="danger" onclick="unpairDevice('${device.mac}', '${device.name.replace(/'/g, "\\'")}')" style="min-width: 90px;">
                          🗑️ Unpair
                        </button>
                      </div>
                    </div>
                  </div>
                `;
              }).join('') + scanButtonHtml;
            } else {
              listDiv.innerHTML = `<div style="color: #f85149; padding: 12px; text-align: center;">
                ${data.devices.length} paired device(s) but none support tethering
              </div>` + scanButtonHtml;
            }
          } else {
            // Hide status area when no devices
            if (networkMetrics) networkMetrics.style.display = 'none';
            if (statusArea) statusArea.style.display = 'none';
            
            listDiv.innerHTML = `<div style="color: #8b949e; padding: 12px; text-align: center;">
              No paired devices
            </div>` + scanButtonHtml;
          }
        } catch (error) {
          document.getElementById('trustedDevicesList').innerHTML = 
            '<div style="color: #f85149; padding: 12px;">Error loading devices</div>';
        }
      }
      
      async function connectToDevice(mac) {
        const btnId = `connect-btn-${mac.replace(/:/g, '')}`;
        const btn = document.getElementById(btnId);
        
        try {
          // Show loading state on button
          if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<span class="spinner"></span> Connecting...';
          }
          showFeedback("Connecting to device...", "info");
          
          const response = await fetch(`/plugins/bt-tether-helper/connect?mac=${mac}`);
          const data = await response.json();
          if (data.success) {
            showFeedback("Connection started! Check your phone for the pairing dialog.", "success");
            startStatusPolling();
            setTimeout(loadTrustedDevicesList, 1000);
          } else {
            showFeedback(`Connection failed: ${data.message}`, "error");
            setTimeout(loadTrustedDevicesList, 1000);
          }
        } catch (error) {
          console.error('Error connecting to device:', error);
          showFeedback(`Connection error: ${error.message}`, "error");
          setTimeout(loadTrustedDevicesList, 1000);
        }
      }
      
      async function disconnectSpecificDevice(mac) {
        const btnId = `disconnect-btn-${mac.replace(/:/g, '')}`;
        const btn = document.getElementById(btnId);
        
        try {
          // Show loading state on button
          if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<span class="spinner"></span> Disconnecting...';
          }
          isDisconnecting = true;
          showFeedback("Disconnecting from device...", "info");
          
          const response = await fetch(`/plugins/bt-tether-helper/disconnect?mac=${encodeURIComponent(mac)}`);
          const data = await response.json();
          if (data.success) {
            showFeedback("Device disconnected.", "success");
            stopStatusPolling();
            setTimeout(loadTrustedDevicesList, 1000);
          } else {
            showFeedback(`Disconnect failed: ${data.message}`, "error");
            setTimeout(loadTrustedDevicesList, 1000);
          }
        } catch (error) {
          console.error('Error disconnecting device:', error);
          showFeedback(`Disconnect error: ${error.message}`, "error");
          setTimeout(loadTrustedDevicesList, 1000);
        } finally {
          isDisconnecting = false;
        }
      }
      
      async function untrustDevice(mac) {
        if (!confirm(`Remove this device from trusted devices?\n\nDevice: ${mac}\n\nYou will need to pair it again to reconnect.`)) {
          return;
        }
        
        try {
          const response = await fetch(`/plugins/bt-tether-helper/untrust?mac=${mac}`);
          const data = await response.json();
          if (data.success) {
            setTimeout(loadTrustedDevicesList, 1000);
          } else {
            alert(data.message || 'Failed to remove device');
          }
        } catch (error) {
          console.error('Error removing device:', error);
          alert('Error removing device');
        }
      }

      async function unpairDevice(mac, name) {
        if (!confirm(`Completely remove this device?\n\nDevice: ${name}\nMAC: ${mac}\n\nThis will:\n- Disconnect (if connected)\n- Unpair the device\n- Remove from trusted devices\n\nYou will need to pair it again to reconnect.`)) {
          return;
        }
        
        try {
          showFeedback(`Removing ${name}...`, "info");
          const response = await fetch(`/plugins/bt-tether-helper/unpair?mac=${mac}`);
          const data = await response.json();
          if (data.success) {
            showFeedback(`${name} has been removed successfully`, "success");
            setTimeout(loadTrustedDevicesList, 1000);
          } else {
            showFeedback(data.message || 'Failed to remove device', "error");
          }
        } catch (error) {
          console.error('Error removing device:', error);
          showFeedback('Error removing device: ' + error.message, "error");
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
        // Abort any running scan
        scanAborted = true;
        
        showFeedback(`Starting pairing with ${name}... Watch for pairing dialog!`, "info");
        
        // Reset scan button state
        const scanBtn = document.getElementById('scanBtn');
        if (scanBtn) {
          scanBtn.disabled = false;
          scanBtn.innerHTML = '🔍 Scan';
        }
        
        // Hide scan results and clear device list immediately when pairing starts
        const scanResultsCard = document.getElementById('scanResultsCard');
        const deviceList = document.getElementById('deviceList');
        const scanStatus = document.getElementById('scanStatus');
        if (scanResultsCard) {
          scanResultsCard.style.display = 'none';
        }
        if (deviceList) {
          deviceList.innerHTML = '';
        }
        if (scanStatus) {
          scanStatus.innerHTML = '';
        }
        
        try {
          const response = await fetch(`/plugins/bt-tether-helper/pair-device?mac=${encodeURIComponent(mac)}&name=${encodeURIComponent(name)}`, { method: 'GET' });
          const data = await response.json();
          
          if (data.success) {
            showFeedback(`Pairing started with ${name}! Accept the dialog on your phone.`, "success");
            
            // Update MAC input field with the paired device
            macInput.value = mac;
            
            // Scroll to the connection status card
            const phoneConnectionCard = document.getElementById('phoneConnectionCard');
            if (phoneConnectionCard) {
              phoneConnectionCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }
            
            // Start status polling to show connection progress
            startStatusPolling();
            
            // Reload trusted devices list multiple times as pairing progresses
            setTimeout(loadTrustedDevicesList, 2000);
            setTimeout(loadTrustedDevicesList, 5000);
            setTimeout(loadTrustedDevicesList, 10000);
            
            // Check connection status to update UI with connect button
            setTimeout(checkConnectionStatus, 1000);
          } else {
            showFeedback(`Pairing failed: ${data.message}`, "error");
            // Reset button on failure
            connectBtn.disabled = false;
            connectBtn.innerHTML = '⚡ Connect to Phone';
          }
        } catch (error) {
          showFeedback(`Pairing failed: ${error.message}`, "error");
          // Reset button on error
          connectBtn.disabled = false;
          connectBtn.innerHTML = '⚡ Connect to Phone';
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
          
          // Ping test
          resultHtml += `<div style="margin-bottom: 8px;">`;
          resultHtml += `<b>📡 Ping Test (8.8.8.8):</b> `;
          resultHtml += data.ping_success ? '<span style="color: #28a745;">✓ Success</span>' : '<span style="color: #dc3545;">✗ Failed</span>';
          resultHtml += `</div>`;
          
          // DNS test
          resultHtml += `<div style="margin-bottom: 8px;">`;
          resultHtml += `<b>🔍 DNS Test (google.com):</b> `;
          resultHtml += data.dns_success ? '<span style="color: #28a745;">✓ Success</span>' : '<span style="color: #dc3545;">✗ Failed</span>';
          resultHtml += `</div>`;
          
          // DNS servers
          if (data.dns_servers) {
            resultHtml += `<div style="margin-bottom: 8px; padding-left: 20px; font-size: 12px;">`;
            resultHtml += `<span style="color: #666;">DNS Servers:</span> <span style="color: #0066cc;">${data.dns_servers}</span>`;
            resultHtml += `</div>`;
          }
          
          // DNS error details
          if (!data.dns_success && data.dns_error) {
            resultHtml += `<div style="margin-bottom: 8px; padding-left: 20px; font-size: 11px; background: #fff3cd; padding: 6px; border-radius: 3px;">`;
            resultHtml += `<span style="color: #856404;">Error: ${data.dns_error.substring(0, 150)}...</span>`;
            resultHtml += `</div>`;
          }
          
          // bnep0 IP
          resultHtml += `<div style="margin-bottom: 8px;">`;
          resultHtml += `<b>💻 bnep0 IP:</b> `;
          resultHtml += data.bnep0_ip ? `<span style="color: #28a745;">${data.bnep0_ip}</span>` : '<span style="color: #dc3545;">No IP assigned</span>';
          resultHtml += `</div>`;
          
          // Default route
          resultHtml += `<div style="margin-bottom: 8px;">`;
          resultHtml += `<b>🚦 Default Route:</b> `;
          resultHtml += data.default_route ? `<span style="color: #0066cc;">${data.default_route}</span>` : '<span style="color: #dc3545;">None</span>';
          resultHtml += `</div>`;
          
          // Localhost route - CRITICAL for bettercap API
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
          
          // Set overall result class
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
          testBtn.innerHTML = '🔍 Test Internet Connectivity';
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
    __version__ = "1.2.1-beta"
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
    STATE_DISCONNECTING = "DISCONNECTING"
    STATE_UNTRUSTING = "UNTRUSTING"
    STATE_DISCONNECTED = "DISCONNECTED"
    STATE_ERROR = "ERROR"

    # Timing constants
    BLUETOOTH_SERVICE_STARTUP_DELAY = 5  # Increased for RPi Zero 2W
    MONITOR_INITIAL_DELAY = 5
    MONITOR_PAUSED_CHECK_INTERVAL = 10  # Check every 10 seconds when paused
    SCAN_DURATION = 30
    SCAN_DISCOVERY_WAIT = 1  # Wait between scan discovery attempts
    SCAN_DISCOVERY_MAX_ATTEMPTS = 60  # Max attempts to discover device during scan
    DEVICE_OPERATION_DELAY = 1
    DEVICE_OPERATION_LONGER_DELAY = 2
    SCAN_STOP_DELAY = 0.5
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
    PHONE_READY_WAIT = 3  # Wait for phone to be ready after pairing/trust
    NAP_RETRY_DELAY = 3  # Wait between NAP connection retries
    NETWORK_STABILIZE_WAIT = 2  # Wait for network to stabilize
    DHCLIENT_TIMEOUT = 30  # Timeout for dhclient DHCP request
    DHCPCD_TIMEOUT = 20  # Timeout for dhcpcd DHCP request
    DHCP_IP_CHECK_MAX_ATTEMPTS = 8  # Max attempts to check for IP address after DHCP
    PAIRING_DEVICE_DISCOVERY_TIMEOUT = (
        60  # Seconds to wait for device discovery during pairing
    )
    NAP_CONNECTION_MAX_RETRIES = 3  # Max retries for NAP connection
    DEFAULT_CMD_TIMEOUT = 10  # Default timeout for shell commands

    # Reconnect configuration constants
    DEFAULT_RECONNECT_INTERVAL = 60  # Default seconds between reconnect checks
    MAX_RECONNECT_FAILURES = 5  # Max consecutive failures before cooldown
    DEFAULT_RECONNECT_FAILURE_COOLDOWN = 300  # Default cooldown in seconds (5 minutes)

    # UI and buffer constants
    UI_LOG_MAXLEN = 100  # Maximum number of log messages in UI buffer

    def __init__(self):
        """Initialize plugin instance"""
        super().__init__()
        self.lock = threading.Lock()
        self._ui_log_lock = threading.Lock()
        self._bluetoothctl_lock = threading.Lock()
        self._cached_ui_status_lock = threading.Lock()

        self._monitor_stop = threading.Event()
        self._monitor_paused = threading.Event()
        self._name_update_stop = threading.Event()
        self._initialization_done = threading.Event()

        self._monitor_thread = None
        self._name_update_thread = None
        self._fallback_thread = None
        self._ui_update_timer = None

    def on_loaded(self):
        """Initialize plugin configuration"""
        from collections import deque

        self.phone_mac = ""
        self._status = self.STATE_IDLE
        self._message = "Ready"
        self._scanning = False
        self._last_scan_devices = []
        self._scan_complete_time = 0
        self.options["csrf_exempt"] = True
        self.agent_process = None
        self.agent_log_fd = None
        self.agent_log_path = None
        self.current_passkey = None

        self._ui_logs = deque(maxlen=self.UI_LOG_MAXLEN)

        self.show_on_screen = self.options.get("show_on_screen", True)
        self.show_mini_status = self.options.get("show_mini_status", True)
        self.mini_status_position = self.options.get("mini_status_position", None)

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
        self._last_known_route = None
        self._last_known_routes = []  # Track all routes to detect changes
        self._reconnect_failure_count = 0
        self._max_reconnect_failures = self.MAX_RECONNECT_FAILURES
        self._reconnect_failure_cooldown = self.options.get(
            "reconnect_failure_cooldown", self.DEFAULT_RECONNECT_FAILURE_COOLDOWN
        )
        self._first_failure_time = None
        self._user_requested_disconnect = False

        self._screen_needs_refresh = False
        self._ui_update_active = False

        self._cached_ui_status = {
            "paired": False,
            "trusted": False,
            "connected": False,
            "pan_active": False,
            "interface": None,
            "ip_address": None,
        }
        self._ui_reference = None

        self._log("INFO", "Plugin configuration loaded - ready to connect")

    def _initialize_bluetooth_services(self):
        """Initialize Bluetooth services"""
        with self.lock:
            self._initializing = True
            self._screen_needs_refresh = True

        try:
            try:
                subprocess.run(
                    ["pkill", "-9", "bluetoothctl"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                self._log("INFO", "Cleaned up lingering bluetoothctl processes")
            except Exception as e:
                self._log("DEBUG", f"Process cleanup: {e}")
            
            # Restart Bluetooth service with longer timeout for RPi Zero 2W
            try:
                self._log("INFO", "Restarting Bluetooth service...")
                subprocess.run(
                    ["systemctl", "restart", "bluetooth"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=30,  # Increased timeout for slow hardware
                )
                time.sleep(self.BLUETOOTH_SERVICE_STARTUP_DELAY)
                self._log("INFO", "Bluetooth service restarted")
            except subprocess.TimeoutExpired:
                self._log("WARNING", "Bluetooth service restart timed out, checking if it's running anyway...")
                # Check if bluetooth service is actually running
                try:
                    status = subprocess.run(
                        ["systemctl", "is-active", "bluetooth"],
                        capture_output=True,
                        text=True,
                        timeout=5
                    )
                    if status.returncode == 0 and "active" in status.stdout:
                        self._log("INFO", "Bluetooth service is active despite timeout")
                    else:
                        self._log("ERROR", "Bluetooth service is NOT running!")
                except Exception:
                    pass
            except Exception as e:
                self._log("WARNING", f"Failed to restart Bluetooth service: {e}")

            # Ensure Bluetooth adapter is powered on
            try:
                self._log("INFO", "Powering on Bluetooth adapter...")
                power_result = subprocess.run(
                    ["bluetoothctl", "power", "on"],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                if power_result.returncode == 0:
                    self._log("INFO", "Bluetooth adapter powered on")
                else:
                    self._log("WARNING", f"Power on result: {power_result.stdout} {power_result.stderr}")
                time.sleep(1)
            except Exception as e:
                self._log("WARNING", f"Failed to power on Bluetooth: {e}")

            try:
                self._verify_localhost_route()
            except Exception as e:
                self._log("WARNING", f"Initial localhost check failed: {e}")

            self._start_pairing_agent()

            # Start monitoring if auto-reconnect is enabled (auto-discovers trusted devices)
            if self.auto_reconnect:
                self._start_monitoring_thread()

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
                    self._update_cached_ui_status(
                        status={
                            "paired": False,
                            "trusted": False,
                            "connected": False,
                            "pan_active": False,
                            "interface": None,
                            "ip_address": None,
                        }
                    )
                    with self.lock:
                        self._initializing = False
                        self._screen_needs_refresh = True

                    self._force_ui_refresh()
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

                self._force_ui_refresh()
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

            self._force_ui_refresh()

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
        import datetime

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

    def _force_ui_refresh(self):
        """Force immediate UI refresh if UI reference is available"""
        if self._ui_reference:
            try:
                self.on_ui_update(self._ui_reference)
            except Exception:
                pass  # Silently ignore UI update errors

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
            "[bt-tether-helper] on_ui_setup() called - initializing Bluetooth services"
        )
        if not self._initialization_done.is_set():
            self._initialization_done.set()
            self._fallback_thread = threading.Thread(
                target=self._initialize_bluetooth_services, daemon=True
            )
            self._fallback_thread.start()

        if self.show_on_screen and self.show_mini_status:
            pos = (
                self.mini_status_position
                if self.mini_status_position
                else (ui.width() / 2 + 50, 0)
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
        if not self.show_on_screen:
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
                if status_str == self.STATE_CONNECTED:
                    pass  # Fall through to show connected status
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
                    if cached_status.get("connected") or cached_status.get(
                        "pan_active"
                    ):
                        pass  # Reconnection succeeded
                    else:
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

            if not phone_mac and not cached_status.get("paired", False):
                if cached_status.get("connected", False) or cached_status.get(
                    "pan_active", False
                ):
                    threading.Thread(
                        target=self._update_cached_ui_status,
                        args=(
                            {
                                "paired": False,
                                "trusted": False,
                                "connected": False,
                                "pan_active": False,
                                "interface": None,
                                "ip_address": None,
                            },
                        ),
                        daemon=True,
                    ).start()

                if self.show_mini_status:
                    ui.set("bt-status", "X")
                if self.show_detailed_status:
                    ui.set("bt-detail", "BT:No device")
                return

            # Status codes: C=Connected, T=Trusted, N=Not trusted, P=Paired, X=Disconnected
            if cached_status.get("pan_active", False):
                display = "C"
            elif cached_status.get("connected", False) and cached_status.get(
                "trusted", False
            ):
                display = "T"
            elif cached_status.get("connected", False):
                display = "N"
            elif cached_status.get("paired", False):
                display = "P"
            else:
                display = "X"

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
        if disconnecting:
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

        if pan_active:
            return f"BT:{ip_address}" if ip_address else "BT:Connected"
        elif connected and trusted:
            return "BT:Trusted"
        elif connected:
            return "BT:Connected"
        elif paired:
            return "BT:Paired"
        else:
            return "BT:Disconnected"

    def _update_cached_ui_status(self, status=None, mac=None):
        """Update the cached UI status (thread-safe)"""
        try:
            if status is None:
                target_mac = mac if mac else self.phone_mac
                if target_mac:
                    status = self._get_current_status(target_mac)
                else:
                    status = {
                        "paired": False,
                        "trusted": False,
                        "connected": False,
                        "pan_active": False,
                        "interface": None,
                        "ip_address": None,
                    }

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

    def _connection_monitor_loop(self):
        """Background loop to monitor connection status and reconnect if needed"""
        self._log("INFO", "Connection monitor started")

        # Brief wait before starting to monitor to let plugin initialize
        time.sleep(self.MONITOR_INITIAL_DELAY)

        while not self._monitor_stop.is_set():
            try:
                # Skip monitoring if connection/pairing is already in progress
                with self.lock:
                    connection_in_progress = self._connection_in_progress

                if connection_in_progress:
                    time.sleep(self.reconnect_interval)
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
                            status={
                                "paired": False,
                                "trusted": False,
                                "connected": False,
                                "pan_active": False,
                                "interface": None,
                                "ip_address": None,
                            }
                        )
                    # Silently recheck every 60s when paused (no logging)

                    # Sleep and then recheck for devices (don't wait indefinitely)
                    time.sleep(self.reconnect_interval)
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

                # Check routes and only log when they change
                current_route = status.get("default_route_interface")
                if status["connected"] and current_route:
                    # Get all routes to check for changes
                    try:
                        import subprocess

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
                                    metric = (
                                        int(metric_match.group(1))
                                        if metric_match
                                        else 0
                                    )
                                    gateway = (
                                        gateway_match.group(1)
                                        if gateway_match
                                        else "N/A"
                                    )
                                    routes.append(
                                        {
                                            "interface": iface,
                                            "metric": metric,
                                            "gateway": gateway,
                                            "full_line": line.strip(),
                                        }
                                    )

                        # Sort by metric - lower metric = higher priority
                        sorted_routes = sorted(routes, key=lambda x: x["metric"])

                        # Create comparable snapshot (interface, metric, gateway)
                        current_routes_snapshot = [
                            (r["interface"], r["metric"], r["gateway"])
                            for r in sorted_routes
                        ]

                        # Check if routes changed - only log if different
                        routes_changed = (
                            current_routes_snapshot != self._last_known_routes
                        )

                        if routes_changed and routes:
                            # Routes changed - log only the primary route
                            primary = sorted_routes[0]
                            iface_type = self._get_interface_type(primary["interface"])
                            self._log(
                                "INFO",
                                f"📊 Primary route: {primary['interface']} ({iface_type}, metric: {primary['metric']})",
                            )

                            # Update the snapshot after logging
                            self._last_known_routes = current_routes_snapshot

                    except Exception as e:
                        logging.debug(
                            f"[bt-tether-helper] Failed to get route details: {e}"
                        )

                    self._last_known_route = current_route
                elif not status["connected"] and self._last_known_route:
                    # Disconnected - clear last route and routes snapshot
                    self._last_known_route = None
                    self._last_known_routes = []

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
                        status={
                            "paired": True,
                            "trusted": True,
                            "connected": False,
                            "pan_active": False,
                            "interface": None,
                            "ip_address": None,
                        },
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
                        # Update phone_mac to the successful device
                        self.phone_mac = current_mac
                    else:
                        # Increment failure counter
                        self._reconnect_failure_count += 1
                        # Track when failures started
                        if self._first_failure_time is None:
                            self._first_failure_time = time.time()
                        # Update cached UI to show disconnected state after failure
                        self._update_cached_ui_status(mac=current_mac)
                        if (
                            self._reconnect_failure_count
                            >= self._max_reconnect_failures
                        ):
                            self._log(
                                "WARNING",
                                f"⚠️  Auto-reconnect paused after {self._max_reconnect_failures} failed attempts",
                            )
                            self._log(
                                "INFO",
                                f"📱 Will retry after {self._reconnect_failure_cooldown}s cooldown, or reconnect manually via web UI",
                            )
                            with self.lock:
                                self.status = self.STATE_DISCONNECTED
                                self.message = f"Auto-reconnect paused - retrying in {self._reconnect_failure_cooldown}s"
                                self._connection_in_progress = (
                                    False  # Clear flag to show proper status
                                )
                                self._screen_needs_refresh = True
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
                            self._reconnect_failure_count = 0
                            self._first_failure_time = None
                elif not status["paired"] or not status["trusted"]:
                    # Device not paired/trusted (or blocked), don't attempt auto-reconnect
                    # Reset failure counter since this is intentional
                    self._reconnect_failure_count = 0
                    self._first_failure_time = None
                    logging.debug(
                        f"[bt-tether-helper] Device not ready for auto-reconnect (paired={status['paired']}, trusted={status['trusted']})"
                    )

            except Exception as e:
                logging.error(f"[bt-tether-helper] Monitor loop error: {e}")

            # Wait for next check
            time.sleep(self.reconnect_interval)

        self._log("INFO", "Connection monitor stopped")

    def _reconnect_device(self):
        """Attempt to reconnect to a previously paired device"""
        try:
            # Find best device if no MAC is set
            if not self.phone_mac:
                best_device = self._find_best_device_to_connect()
                if not best_device:
                    self._log("DEBUG", "No trusted devices found for reconnection")
                    return False
                mac = best_device["mac"]
                self.phone_mac = mac
            else:
                mac = self.phone_mac

            # Set flag to prevent concurrent operations
            with self.lock:
                self._connection_in_progress = True
                self._connection_start_time = (
                    time.time()
                )  # Track start time for timeout detection
                self._initializing = (
                    False  # Ensure initializing flag is cleared during reconnection
                )

            self._log("INFO", f"Reconnecting to {mac}...")

            # Check if device is blocked
            devices_output = self._run_cmd(
                ["bluetoothctl", "devices", "Blocked"], capture=True, timeout=5
            )
            if devices_output and devices_output != "Timeout" and mac in devices_output:
                self._log("INFO", f"Unblocking device {mac}...")
                self._run_cmd(["bluetoothctl", "unblock", mac], capture=True)
                time.sleep(self.DEVICE_OPERATION_DELAY)

            # Trust the device (already paired, just ensure trust is set)
            self._log("INFO", f"Ensuring device is trusted...")
            self._run_cmd(["bluetoothctl", "trust", mac], capture=True)
            time.sleep(self.DEVICE_OPERATION_DELAY)

            # Check if already connected before trying to connect
            status_check = self._check_pair_status(mac)
            if status_check.get("connected", False):
                self._log("INFO", "✓ Bluetooth already connected, proceeding to NAP")
            else:
                # Establish base Bluetooth connection first
                self._log("INFO", "Establishing Bluetooth connection...")
                connect_result = self._run_cmd(["bluetoothctl", "connect", mac], capture=True, timeout=10)
                
                if connect_result and "Connection successful" in connect_result:
                    self._log("INFO", "✓ Bluetooth connection established")
                    time.sleep(2)  # Give connection time to stabilize
                elif connect_result and "already connected" in connect_result.lower():
                    self._log("INFO", "✓ Bluetooth already connected")
                elif connect_result and "Failed to connect" in connect_result:
                    self._log("WARNING", "Bluetooth connection failed, trying NAP anyway...")
                else:
                    self._log("WARNING", "Bluetooth connect timed out, checking status...")
                    # Kill any hung bluetoothctl processes
                    self._run_cmd(["pkill", "-9", "bluetoothctl"], capture=True, timeout=2)
                    time.sleep(1)

            # Try NAP connection over the established Bluetooth link
            self._log("INFO", f"Attempting NAP connection...")
            nap_connected = self._connect_nap_dbus(mac)

            if nap_connected:
                self._log("INFO", f"✓ Reconnection successful")

                # Wait for PAN interface
                time.sleep(self.PAN_INTERFACE_WAIT)

                # Check if PAN interface is up
                if self._pan_active():
                    iface = self._get_pan_interface()
                    self._log("INFO", f"✓ PAN interface active: {iface}")

                    # Setup network with DHCP
                    if self._setup_network_dhcp(iface):
                        self._log("INFO", f"✓ Network setup successful")

                    # Verify internet connectivity
                    time.sleep(self.INTERNET_VERIFY_WAIT)
                    if self._check_internet_connectivity():
                        self._log("INFO", f"✓ Internet connectivity verified!")

                        # Get IP address and send Discord notification if configured
                        try:
                            current_ip = self._get_current_ip()
                            if current_ip:
                                self._log("INFO", f"Current IP address: {current_ip}")
                                if self.discord_webhook_url:
                                    self._log(
                                        "INFO",
                                        "Discord webhook configured, starting notification thread...",
                                    )
                                    threading.Thread(
                                        target=self._send_discord_notification,
                                        args=(current_ip,),
                                        daemon=True,
                                    ).start()
                                else:
                                    self._log(
                                        "DEBUG",
                                        "Discord webhook not configured, skipping notification",
                                    )
                            else:
                                self._log(
                                    "WARNING",
                                    "Could not get IP address for Discord notification",
                                )
                        except Exception as e:
                            self._log(
                                "ERROR", f"Failed to send Discord notification: {e}"
                            )

                        # Update cached UI status FIRST while flag is still True
                        self._update_cached_ui_status(mac=mac)

                        # Then update status and clear flags
                        with self.lock:
                            self.status = self.STATE_CONNECTED
                            self.message = f"✓ Reconnected! Internet via {iface}"
                            self._connection_in_progress = False
                            self._connection_start_time = None
                            self._initializing = False
                            self._screen_needs_refresh = True
                        return True
                    else:
                        logging.warning(
                            f"[bt-tether-helper] Reconnected but no internet detected"
                        )
                        # Update cached UI status FIRST while flag is still True
                        self._update_cached_ui_status(mac=mac)

                        # Then update status and clear flags
                        with self.lock:
                            self.status = self.STATE_CONNECTED
                            self.message = f"Reconnected via {iface} but no internet"
                            self._connection_in_progress = False
                            self._connection_start_time = None
                            self._initializing = False
                            self._screen_needs_refresh = True
                        return True
                else:
                    logging.warning(
                        f"[bt-tether-helper] NAP connected but no interface detected"
                    )
                    # Update cached UI status FIRST while flag is still True
                    self._update_cached_ui_status(mac=mac)

                    # Then update status and clear flags
                    with self.lock:
                        self.status = self.STATE_CONNECTED
                        self.message = "Reconnected but no PAN interface"
                        self._connection_in_progress = False
                        self._connection_start_time = None
                        self._initializing = False
                        self._screen_needs_refresh = True
                    return True
            else:
                logging.warning(f"[bt-tether-helper] Reconnection failed")
                with self.lock:
                    self.status = self.STATE_DISCONNECTED
                    self.message = "Reconnection failed. Will retry later."
                    self._connection_in_progress = False  # Clear flag immediately
                    self._initializing = False  # Clear initializing flag
                    self._screen_needs_refresh = True
                # Force cached UI to show disconnected (clear any lingering IP/interface)
                self._update_cached_ui_status(
                    status={
                        "paired": True,
                        "trusted": True,
                        "connected": False,
                        "pan_active": False,
                        "interface": None,
                        "ip_address": None,
                    },
                    mac=mac,
                )
                return False

        except Exception as e:
            logging.error(f"[bt-tether-helper] Reconnection error: {e}")
            with self.lock:
                self.status = self.STATE_DISCONNECTED
                self.message = f"Reconnection error: {str(e)[:50]}"
                self._connection_in_progress = False  # Clear flag immediately
                self._initializing = False  # Clear initializing flag
                self._screen_needs_refresh = True
            # Force cached UI to show disconnected (clear any lingering IP/interface)
            self._update_cached_ui_status(
                status={
                    "paired": True,
                    "trusted": True,
                    "connected": False,
                    "pan_active": False,
                    "interface": None,
                    "ip_address": None,
                },
                mac=mac,
            )
            return False
        finally:
            # Ensure flags are cleared
            with self.lock:
                if self._connection_in_progress:
                    self._connection_in_progress = False
                    self._connection_start_time = None

    def _monitor_agent_log_for_passkey(self, passkey_found_event):
        """Monitor agent log file for passkey display in real-time and auto-confirm"""
        try:
            import time

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

                                    # Invalidate cache so web UI gets fresh status with passkey

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

                # Disconnect any existing connection before connecting to new device
                # RPi Zero 2W can only handle one BT PAN connection at a time
                try:
                    current_status = (
                        self._check_device_status(self.phone_mac)
                        if self.phone_mac
                        else None
                    )
                    if current_status and current_status.get("connected"):
                        target_name = "selected device" if mac else "best device"
                        self._log(
                            "INFO",
                            f"Disconnecting current device before connecting to {target_name}...",
                        )
                        self._disconnect_current_device()
                        time.sleep(1)  # Give time for disconnect to complete
                except Exception as e:
                    self._log("DEBUG", f"Disconnect before connection warning: {e}")

                # If MAC provided, use it; otherwise find best device automatically
                if mac and self._validate_mac(mac):
                    with self.lock:
                        self.phone_mac = mac
                    self.start_connection()
                    self._force_ui_refresh()
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
                        self._force_ui_refresh()
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

                        # Check if connection is already in progress
                        if self._connection_in_progress:
                            return jsonify(
                                {
                                    "success": False,
                                    "message": "Connection already in progress",
                                }
                            )

                        # Stop any ongoing scan and clear scanning flag
                        self._scanning = False
                        self._connection_in_progress = True
                        self._connection_start_time = time.time()
                        self._user_requested_disconnect = False
                        self.status = self.STATE_PAIRING
                        self.message = "Starting pairing..."
                        self._screen_needs_refresh = True

                    # Check if device is already paired/trusted
                    is_already_paired = False
                    device_name = request.args.get("name", "Unknown Device")

                    try:
                        trusted_devices = self._get_trusted_devices()
                        for device in trusted_devices:
                            if (
                                device["mac"] == mac
                                and device["paired"]
                                and device["trusted"]
                            ):
                                is_already_paired = True
                                device_name = device["name"]
                                self._log(
                                    "INFO",
                                    f"Device {device_name} ({mac}) is already paired/trusted - switching connection",
                                )
                                break
                    except Exception as e:
                        self._log("DEBUG", f"Error checking trusted devices: {e}")

                    # Disconnect any existing connection before connecting to new device
                    # RPi Zero 2W can only handle one BT PAN connection at a time
                    # We disconnect but DON'T untrust, so devices stay paired for easy switching
                    try:
                        current_status = self._check_device_status(self.phone_mac)
                        if current_status and current_status.get("connected"):
                            self._log(
                                "INFO",
                                f"Disconnecting current device to switch to {device_name}...",
                            )
                            self._disconnect_current_device()
                            time.sleep(1)  # Give time for disconnect to complete
                    except Exception as e:
                        self._log("DEBUG", f"Disconnect before connection warning: {e}")

                    # Stop scan process if running
                    try:
                        subprocess.run(
                            ["bluetoothctl", "scan", "off"],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            timeout=2,
                        )
                    except Exception as e:
                        logging.debug(f"[bt-tether-helper] Failed to stop scan: {e}")

                    # Reset failure counter
                    self._reconnect_failure_count = 0

                    # Unpause monitor
                    self._monitor_paused.clear()

                    # Create device info - use actual pairing status
                    device_info = {
                        "mac": mac,
                        "name": device_name,
                        "paired": is_already_paired,
                        "trusted": is_already_paired,
                        "connected": False,
                        "has_nap": True,  # Assume it has NAP, will be verified during connection
                    }

                    # Start connection thread directly with device info
                    threading.Thread(
                        target=self._connect_thread, args=(device_info,), daemon=True
                    ).start()

                    self._force_ui_refresh()

                    message = (
                        f"Switching to {device_name}"
                        if is_already_paired
                        else f"Pairing started with {device_name}"
                    )
                    return jsonify({"success": True, "message": message})
                else:
                    return jsonify({"success": False, "message": "Invalid MAC address"})

            if clean_path == "status":
                with self.lock:
                    return jsonify(
                        {
                            "status": self.status,
                            "message": self.message,
                            "mac": self.phone_mac,
                            "disconnecting": self._disconnecting,
                            "untrusting": self._untrusting,
                            "initializing": self._initializing,
                            "connection_in_progress": self._connection_in_progress,
                        }
                    )

            if clean_path == "disconnect":
                mac = request.args.get("mac", "").strip().upper()
                if mac and self._validate_mac(mac):
                    # Update cached UI status FIRST to show disconnected state immediately
                    # This clears any lingering "Test Internet Connectivity" messages
                    self._update_cached_ui_status(
                        status={
                            "paired": True,
                            "trusted": False,
                            "connected": False,
                            "pan_active": False,
                            "interface": None,
                            "ip_address": None,
                        },
                        mac=mac,
                    )

                    # Set flags immediately so UI shows disconnecting state
                    with self.lock:
                        self._user_requested_disconnect = True
                        self._disconnecting = True
                        self._disconnect_start_time = (
                            time.time()
                        )  # Track when disconnect started
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
                            # Ensure flags are cleared even on error
                            with self.lock:
                                self._disconnecting = False
                                self._connection_in_progress = False

                    thread = threading.Thread(target=do_disconnect, daemon=True)
                    thread.start()

                    self._force_ui_refresh()

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

            if clean_path == "untrust":
                # Remove device from trusted list (keeps pairing, just removes trust)
                # This is different from disconnect which also removes pairing
                mac = request.args.get("mac", "").strip().upper()
                if mac and self._validate_mac(mac):
                    with self.lock:
                        self._untrusting = True
                        self._untrust_start_time = time.time()
                        self.status = self.STATE_UNTRUSTING
                        self.message = f"Removing trust from device..."
                        self._screen_needs_refresh = True

                    def do_untrust():
                        try:
                            self._log("INFO", f"Untrusting device {mac}...")

                            # Disconnect if connected
                            current_status = self._get_current_status(mac)
                            if current_status and current_status.get("connected"):
                                self._log(
                                    "INFO",
                                    "Device is connected, disconnecting first...",
                                )
                                self._disconnect_current_device()
                                time.sleep(1)

                            # Remove trust
                            result = self._run_cmd(
                                ["bluetoothctl", "untrust", mac], capture=True
                            )
                            self._log("INFO", f"Untrust result: {result}")

                            # Block device to prevent auto-reconnect
                            block_result = self._run_cmd(
                                ["bluetoothctl", "block", mac], capture=True
                            )
                            self._log("INFO", f"Block result: {block_result}")

                            # Remove device completely
                            remove_result = self._run_cmd(
                                ["bluetoothctl", "remove", mac], capture=True
                            )
                            self._log("INFO", f"Remove result: {remove_result}")

                            time.sleep(0.5)  # Wait for changes to propagate

                            # Update state
                            with self.lock:
                                self._untrusting = False
                                self._untrust_start_time = None
                                self.status = self.STATE_DISCONNECTED
                                self.message = "Device removed from trusted list"
                                # Clear phone_mac if this was the current device
                                if self.phone_mac == mac:
                                    self.phone_mac = None
                                self._screen_needs_refresh = True

                            self._force_ui_refresh()

                        except Exception as e:
                            self._log("ERROR", f"Untrust error: {e}")
                            with self.lock:
                                self._untrusting = False
                                self._untrust_start_time = None
                                self.status = self.STATE_ERROR
                                self.message = f"Untrust failed: {str(e)[:50]}"

                    thread = threading.Thread(target=do_untrust, daemon=True)
                    thread.start()

                    return jsonify({"success": True, "message": "Untrust started"})
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
                    # If already scanning, return current results
                    if self._scanning:
                        devices_to_return = self._last_scan_devices.copy()
                        return jsonify({"devices": devices_to_return})

                    # Not scanning - check if results are still fresh (< 60 seconds old)
                    # This lets web UI display results without triggering new scans
                    # Set to 60s to cover the full scan duration + polling window
                    if (
                        self._scan_complete_time
                        and (current_time - self._scan_complete_time) < 60
                    ):
                        devices_to_return = self._last_scan_devices.copy()
                        return jsonify({"devices": devices_to_return})

                    # Results are stale or no previous scan - start a new one
                    self._last_scan_devices = []
                    self._scan_complete_time = 0
                    self._scanning = True
                    self._screen_needs_refresh = True

                # Run scan in background thread
                def run_scan_bg():
                    try:
                        devices = self._scan_devices()
                        with self.lock:
                            self._last_scan_devices = devices
                            self._scan_complete_time = time.time()
                        # Note: _scan_devices() already logs completion
                    except Exception as e:
                        logging.error(f"[bt-tether-helper] Background scan error: {e}")
                        # Note: _scan_devices() has its own finally block that clears _scanning flag

                thread = threading.Thread(target=run_scan_bg, daemon=True)
                thread.start()

                self._force_ui_refresh()

                return jsonify({"devices": []})

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
        return bool(re.match(r"^([0-9A-F]{2}:){5}[0-9A-F]{2}$", mac))

    def _check_device_status(self, mac):
        """Quick check of device connection status - wrapper for _get_current_status"""
        if not mac:
            return None
        try:
            return self._get_current_status(mac)
        except Exception as e:
            logging.debug(f"[bt-tether-helper] Failed to check device status: {e}")
            return None

    def _disconnect_current_device(self):
        """Disconnect the currently connected device (keeps pairing and trust intact for easy switching).
        
        This is a lightweight disconnect that:
        - Disconnects NAP profile
        - Disconnects Bluetooth connection
        - Does NOT remove trust or pairing
        
        Use this when switching between devices in the trusted list.
        """
        try:
            mac = self.phone_mac
            if not mac:
                self._log("DEBUG", "No current device to disconnect")
                return True
            
            self._log("INFO", f"Disconnecting current device {mac} (keeping pairing)...")
            
            # Disconnect NAP profile via DBus first
            try:
                if DBUS_AVAILABLE:
                    bus = dbus.SystemBus()
                    manager = dbus.Interface(
                        bus.get_object("org.bluez", "/"),
                        "org.freedesktop.DBus.ObjectManager",
                    )
                    objects = manager.GetManagedObjects()
                    device_path = None
                    for path, interfaces in objects.items():
                        if "org.bluez.Device1" in interfaces:
                            props = interfaces["org.bluez.Device1"]
                            if props.get("Address") == mac:
                                device_path = path
                                break
                    
                    if device_path:
                        NAP_UUID = "00001116-0000-1000-8000-00805f9b34fb"
                        device = dbus.Interface(
                            bus.get_object("org.bluez", device_path), "org.bluez.Device1"
                        )
                        try:
                            device.DisconnectProfile(NAP_UUID)
                            self._log("DEBUG", "NAP profile disconnected")
                            time.sleep(0.5)
                        except Exception as e:
                            self._log("DEBUG", f"NAP disconnect: {e}")
            except Exception as e:
                self._log("DEBUG", f"DBus NAP disconnect: {e}")
            
            # Disconnect Bluetooth connection
            result = self._run_cmd(["bluetoothctl", "disconnect", mac], capture=True, timeout=5)
            self._log("DEBUG", f"Bluetooth disconnect result: {result}")
            time.sleep(0.5)
            
            # Update cached UI status to show disconnected
            self._update_cached_ui_status(
                status={
                    "paired": True,
                    "trusted": True,
                    "connected": False,
                    "pan_active": False,
                    "interface": None,
                    "ip_address": None,
                },
                mac=mac,
            )
            
            self._log("INFO", f"✓ Device {mac} disconnected (still paired)")
            return True
            
        except Exception as e:
            self._log("ERROR", f"Failed to disconnect current device: {e}")
            return False

    def _disconnect_device(self, mac):
        """Disconnect from a Bluetooth device (keeps pairing and trust intact)"""
        try:
            # Update cached UI FIRST to immediately clear any lingering status messages
            self._update_cached_ui_status(
                status={
                    "paired": True,
                    "trusted": True,
                    "connected": False,
                    "pan_active": False,
                    "interface": None,
                    "ip_address": None,
                },
                mac=mac,
            )

            # Set flags to stop auto-reconnect and indicate disconnecting state
            with self.lock:
                self._user_requested_disconnect = True
                self._disconnecting = True
                self._disconnect_start_time = time.time()
                self._initializing = False
                self.status = self.STATE_DISCONNECTING
                self.message = f"Disconnecting from device..."
                self._screen_needs_refresh = True

            self._force_ui_refresh()
            time.sleep(0.5)

            self._log("INFO", f"Disconnecting from device {mac}...")

            # Disconnect NAP profile via DBus if connected
            try:
                import dbus

                bus = dbus.SystemBus()
                manager = dbus.Interface(
                    bus.get_object("org.bluez", "/"),
                    "org.freedesktop.DBus.ObjectManager",
                )
                objects = manager.GetManagedObjects()
                device_path = None
                for path, interfaces in objects.items():
                    if "org.bluez.Device1" in interfaces:
                        props = interfaces["org.bluez.Device1"]
                        if props.get("Address") == mac:
                            device_path = path
                            break

                if device_path:
                    NAP_UUID = "00001116-0000-1000-8000-00805f9b34fb"
                    device = dbus.Interface(
                        bus.get_object("org.bluez", device_path), "org.bluez.Device1"
                    )
                    try:
                        self._log("INFO", "Disconnecting NAP profile...")
                        device.DisconnectProfile(NAP_UUID)
                        time.sleep(self.DEVICE_OPERATION_DELAY)
                        self._log("INFO", "NAP profile disconnected")
                    except Exception as e:
                        logging.debug(f"[bt-tether-helper] NAP disconnect: {e}")

                    # Also disconnect the device itself
                    try:
                        device.Disconnect()
                        self._log("INFO", "Device disconnected via DBus")
                    except Exception:
                        pass
            except Exception as e:
                logging.debug(f"[bt-tether-helper] DBus operation: {e}")

            # Also try bluetoothctl disconnect as fallback
            self._log("INFO", "Disconnecting via bluetoothctl...")
            result = self._run_cmd(["bluetoothctl", "disconnect", mac], capture=True)
            self._log("INFO", f"Disconnect result: {result}")
            time.sleep(self.DEVICE_OPERATION_DELAY)

            self._log("INFO", f"Device {mac} disconnected successfully")

            # Update cached UI status to show disconnected but still paired/trusted
            self._update_cached_ui_status(
                status={
                    "paired": True,
                    "trusted": True,
                    "connected": False,
                    "pan_active": False,
                    "interface": None,
                    "ip_address": None,
                },
                mac=mac,
            )

            # Update internal state
            with self.lock:
                self.status = self.STATE_DISCONNECTED
                self.message = "Disconnected"
                self._disconnecting = False
                self._disconnect_start_time = None
                self._last_known_connected = False
                self._screen_needs_refresh = True

            self._force_ui_refresh()
            time.sleep(0.1)

            return {
                "success": True,
                "message": f"Device {mac} disconnected",
            }
        except Exception as e:
            self._log("ERROR", f"Disconnect error: {e}")
            self._update_cached_ui_status()

            with self.lock:
                self.status = self.STATE_ERROR
                self.message = f"Disconnect failed: {str(e)[:50]}"
                self._initializing = False
                self._screen_needs_refresh = True
            return {"success": False, "message": f"Disconnect failed: {str(e)}"}
        finally:
            with self.lock:
                self._disconnecting = False
                self._disconnect_start_time = None

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
                return {"paired": False, "connected": False, "trusted": False}

            paired = "Paired: yes" in info
            connected = "Connected: yes" in info
            trusted = "Trusted: yes" in info

            logging.debug(
                f"[bt-tether-helper] Device {mac} - Paired: {paired}, Trusted: {trusted}, Connected: {connected}"
            )
            return {"paired": paired, "connected": connected, "trusted": trusted}
        except Exception as e:
            self._log("ERROR", f"Pair status check error: {e}")
            return {"paired": False, "connected": False, "trusted": False}

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

                            # PAN interface exists and has IP, we're connected with internet
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

        # Add device name from bluetoothctl info
        try:
            result = subprocess.run(
                ["bluetoothctl", "info", mac],
                capture_output=True,
                text=True,
                timeout=3,
            )
            if result.returncode == 0 and result.stdout:
                for line in result.stdout.split("\n"):
                    if line.strip().startswith("Name:"):
                        status["device_name"] = line.split(":", 1)[1].strip()
                        break
                else:
                    status["device_name"] = None
            else:
                status["device_name"] = None
        except Exception:
            status["device_name"] = None

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
        """Get list of all paired Bluetooth devices with their info"""
        try:
            trusted_devices = []

            # Get list of all paired devices
            devices_output = self._run_cmd(
                ["bluetoothctl", "devices", "Paired"], capture=True, timeout=10
            )

            if not devices_output or devices_output == "Timeout":
                return trusted_devices

            # Check each device and get detailed info
            for line in devices_output.split("\n"):
                if line.strip() and line.startswith("Device"):
                    parts = line.strip().split(" ", 2)
                    if len(parts) >= 2:
                        mac = parts[1]
                        name = parts[2] if len(parts) > 2 else "Unknown Device"

                        # Get device info to check status and capabilities
                        info = self._run_cmd(
                            ["bluetoothctl", "info", mac], capture=True, timeout=5
                        )
                        if info:
                            is_trusted = "Trusted: yes" in info
                            is_paired = "Paired: yes" in info

                            # Include all paired devices (trusted or not)
                            if is_paired:
                                # Parse RSSI (signal strength) from info output
                                rssi = None
                                for info_line in info.split("\n"):
                                    if "RSSI:" in info_line:
                                        try:
                                            rssi = int(info_line.split(":")[1].strip())
                                        except (ValueError, IndexError):
                                            pass
                                        break

                                # Parse additional device info
                                device_info = {
                                    "mac": mac,
                                    "name": name,
                                    "trusted": is_trusted,
                                    "paired": is_paired,
                                    "connected": "Connected: yes" in info,
                                    "has_nap": "00001116-0000-1000-8000-00805f9b34fb"
                                    in info,  # NAP UUID
                                    "rssi": rssi,  # Signal strength
                                }
                                trusted_devices.append(device_info)

            return trusted_devices

        except Exception as e:
            self._log("ERROR", f"Failed to get trusted devices: {e}")
            return []

    def _find_best_device_to_connect(self, log_results=True):
        """Find the best device to connect to from trusted devices.

        Selection priority:
        1. Currently connected devices
        2. Device with strongest signal (highest RSSI)
        3. First available device (fallback)

        Args:
            log_results: Whether to log the results (default True, set False to reduce spam)
        """
        try:
            # First check for trusted devices with NAP capability
            trusted_devices = self._get_trusted_devices()

            # Filter for devices that support NAP (tethering)
            nap_devices = [d for d in trusted_devices if d["has_nap"]]

            if nap_devices:
                if log_results:
                    self._log(
                        "INFO",
                        f"Found {len(nap_devices)} trusted device(s) with tethering capability",
                    )

                # Prioritization logic:
                # 1. Currently connected devices first
                # 2. Device with strongest signal (highest RSSI)
                # 3. First available device (fallback)

                connected_devices = [d for d in nap_devices if d["connected"]]
                if connected_devices:
                    device = connected_devices[0]
                    if log_results:
                        self._log(
                            "INFO",
                            f"Using already connected device: {device['name']} ({device['mac']})",
                        )
                    return device

                # Sort by signal strength (RSSI) - higher is better
                # Devices with no RSSI get -100 (worst signal)
                nap_devices_with_signal = sorted(
                    nap_devices,
                    key=lambda d: d.get("rssi") if d.get("rssi") is not None else -100,
                    reverse=True,
                )

                device = nap_devices_with_signal[0]
                rssi_info = (
                    f" (RSSI: {device['rssi']} dBm)"
                    if device.get("rssi") is not None
                    else ""
                )
                self._log(
                    "INFO",
                    f"Auto-selected device with best signal: {device['name']} ({device['mac']}){rssi_info}",
                )
                return device

            # No devices found
            # Only warn if explicitly requested to log results
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
        """Scan for Bluetooth devices and return list with MACs and names."""
        scan_process = None
        reader_thread = None
        discovered_devices = {}  # mac -> name mapping for newly discovered devices
        stop_reader = threading.Event()
        
        def output_reader(proc, devices_dict, stop_event):
            """Thread to read bluetoothctl output and parse discovered devices."""
            lines_read = 0
            new_devices_found = 0
            try:
                while not stop_event.is_set():
                    if proc.poll() is not None:
                        break
                    line = proc.stdout.readline()
                    if not line:
                        break
                    line = line.strip()
                    lines_read += 1
                    
                    # Log raw output for debugging (first 10 lines and device lines)
                    if lines_read <= 10 or "[NEW]" in line or "[DEL]" in line:
                        logging.debug(f"[bt-tether-helper] BT output: {line[:100]}")
                    
                    # Parse [NEW] Device XX:XX:XX:XX:XX:XX DeviceName lines
                    if "[NEW] Device " in line:
                        try:
                            parts = line.split("[NEW] Device ", 1)[1]
                            mac_and_name = parts.split(" ", 1)
                            mac = mac_and_name[0].upper()
                            name = mac_and_name[1] if len(mac_and_name) > 1 else "Unknown Device"
                            
                            if mac not in devices_dict:
                                devices_dict[mac] = name
                                self._log("INFO", f"Found: {name} ({mac})")
                                
                                # Update results for web UI immediately
                                with self.lock:
                                    self._last_scan_devices = [
                                        {"mac": m, "name": n} for m, n in devices_dict.items()
                                    ]
                                    self._screen_needs_refresh = True
                        except Exception as e:
                            logging.debug(f"[bt-tether-helper] Parse error: {e}")
                    
                    # Handle [CHG] Device lines that update names
                    elif "[CHG] Device " in line and "Name:" in line:
                        try:
                            parts = line.split("[CHG] Device ", 1)[1]
                            mac = parts.split(" ")[0].upper()
                            if "Name: " in parts:
                                name = parts.split("Name: ", 1)[1]
                                if mac in devices_dict:
                                    devices_dict[mac] = name
                        except Exception:
                            pass
            except Exception as e:
                logging.debug(f"[bt-tether-helper] Reader thread error: {e}")
            finally:
                # Report how many lines were read and devices found
                device_count = len(devices_dict)
                if device_count == 0:
                    logging.debug(f"[bt-tether-helper] Reader thread finished, read {lines_read} lines from bluetoothctl but found 0 devices")
                else:
                    logging.debug(f"[bt-tether-helper] Reader thread finished, read {lines_read} lines, found {device_count} device(s)")
        
        try:
            self._log("INFO", "Starting Bluetooth scan...")

            with self.lock:
                self._scanning = True
                self._screen_needs_refresh = True

            # Ensure Bluetooth service is running and responsive
            if not self._restart_bluetooth_if_needed():
                self._log("ERROR", "Bluetooth service is not responding, scan may fail")
            
            # Check Bluetooth adapter status first
            adapter_check = self._run_cmd(["bluetoothctl", "show"], capture=True, timeout=10)
            if not adapter_check or adapter_check == "Timeout":
                self._log("ERROR", "Cannot communicate with Bluetooth adapter!")
                return []
            
            self._log("DEBUG", f"Adapter status: {adapter_check[:300]}...")
            
            # Check if adapter is powered
            if "Powered: no" in adapter_check:
                self._log("WARNING", "Bluetooth adapter is powered off, powering on...")
            
            # Power on and set adapter mode - with retries
            for attempt in range(3):
                power_result = self._run_cmd(["bluetoothctl", "power", "on"], capture=True, timeout=10)
                # Check if power on succeeded (command returns "Changing power on succeeded" on success)
                if power_result and ("succeeded" in power_result.lower() or "yes" in power_result.lower()):
                    self._log("INFO", "Bluetooth adapter powered on successfully")
                    break
                elif power_result and power_result != "Timeout":
                    # Power command appears to have succeeded but we're checking anyway
                    self._log("DEBUG", f"Power on result: {power_result}")
                    break
                elif attempt < 2:
                    self._log("WARNING", f"Power on attempt {attempt + 1} failed, retrying...")
                    time.sleep(2)
                else:
                    self._log("WARNING", f"Power on final attempt result: {power_result}")
            
            time.sleep(1)  # Give adapter time to stabilize
            
            # Verify adapter is now powered
            verify_check = self._run_cmd(["bluetoothctl", "show"], capture=True, timeout=5)
            if verify_check and "Powered: yes" in verify_check:
                self._log("INFO", "Bluetooth adapter confirmed powered on")
            else:
                self._log("WARNING", "Bluetooth adapter may not be powered on properly")
            
            # Set pairable and discoverable for better scanning
            self._run_cmd(["bluetoothctl", "pairable", "on"], capture=True)
            self._run_cmd(["bluetoothctl", "discoverable", "on"], capture=True)
            time.sleep(1)
            
            # Final verification that adapter is ready
            adapter_verify = self._run_cmd(["bluetoothctl", "show"], capture=True, timeout=5)
            if adapter_verify and "Powered: yes" in adapter_verify:
                self._log("INFO", "Bluetooth adapter powered on and ready for scanning")
            else:
                self._log("WARNING", "Bluetooth adapter may not be ready - scan might fail")

            # Use dual scan approach: try interactive mode AND poll bluetoothctl devices
            self._log("INFO", "Scanning for nearby Bluetooth devices...")
            
            scan_process = None
            reader_thread = None
            
            # Start interactive bluetoothctl scan (may not work on all systems)
            try:
                scan_process = subprocess.Popen(
                    ["bluetoothctl"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                )
                self._log("DEBUG", "Started bluetoothctl interactive session")
                
                # Start reader thread to capture output
                reader_thread = threading.Thread(
                    target=output_reader,
                    args=(scan_process, discovered_devices, stop_reader),
                    daemon=True
                )
                reader_thread.start()
                
                # Send scan on command
                scan_process.stdin.write("scan on\n")
                scan_process.stdin.flush()
                self._log("DEBUG", "Sent 'scan on' command to bluetoothctl")
                
            except Exception as e:
                self._log("WARNING", f"Failed to start interactive scan: {e}")
                scan_process = None
            
            # Wait for scan to start - give it a moment to begin reporting devices
            time.sleep(2)
            
            # Parallel polling approach: continuously poll bluetoothctl devices
            # This works even if interactive mode isn't producing output
            self._log("DEBUG", "Starting active device polling...")
            
            # Wait for scan duration, polling periodically
            scan_start = time.time()
            last_device_count = 0
            last_poll_time = scan_start
            has_logged_scan_start = False
            
            while time.time() - scan_start < self.SCAN_DURATION:
                # Check if scan was cancelled
                with self.lock:
                    if not self._scanning:
                        self._log("INFO", "Scan cancelled")
                        break
                
                time.sleep(1)
                
                # Poll bluetoothctl devices every 2 seconds
                current_time = time.time()
                if current_time - last_poll_time >= 2:
                    last_poll_time = current_time
                    try:
                        poll_result = subprocess.run(
                            ["bluetoothctl", "devices"],
                            capture_output=True,
                            text=True,
                            timeout=3
                        )
                        if poll_result.returncode == 0:
                            for line in poll_result.stdout.split("\n"):
                                if line.strip().startswith("Device"):
                                    parts = line.strip().split(" ", 2)
                                    if len(parts) >= 2:
                                        mac = parts[1].upper()
                                        name = parts[2] if len(parts) > 2 else "Unknown Device"
                                        if mac not in discovered_devices:
                                            discovered_devices[mac] = name
                                            self._log("INFO", f"Found: {name} ({mac})")
                                            with self.lock:
                                                self._last_scan_devices = [
                                                    {"mac": m, "name": n} for m, n in discovered_devices.items()
                                                ]
                                                self._screen_needs_refresh = True
                    except Exception as e:
                        logging.debug(f"[bt-tether-helper] Device poll error: {e}")
                
                # Log progress if new devices found
                current_count = len(discovered_devices)
                if current_count > last_device_count:
                    last_device_count = current_count
                    self._log("INFO", f"Scan progress: {current_count} device(s) found")
                elif not has_logged_scan_start and time.time() - scan_start > 5:
                    # After 5 seconds with no devices, log that scan is running
                    self._log("DEBUG", f"Scan running ({int(time.time() - scan_start)}s elapsed, 0 devices found so far)")
                    has_logged_scan_start = True
                
                # Also poll bluetoothctl devices to catch any we might have missed
                # (devices discovered before our reader started, or during gaps)
                try:
                    poll_result = subprocess.run(
                        ["bluetoothctl", "devices"],
                        capture_output=True,
                        text=True,
                        timeout=3
                    )
                    if poll_result.returncode == 0:
                        for line in poll_result.stdout.split("\n"):
                            if line.strip().startswith("Device"):
                                parts = line.strip().split(" ", 2)
                                if len(parts) >= 2:
                                    mac = parts[1].upper()
                                    name = parts[2] if len(parts) > 2 else "Unknown Device"
                                    if mac not in discovered_devices:
                                        discovered_devices[mac] = name
                                        self._log("INFO", f"Found: {name} ({mac})")
                                        with self.lock:
                                            self._last_scan_devices = [
                                                {"mac": m, "name": n} for m, n in discovered_devices.items()
                                            ]
                                            self._screen_needs_refresh = True
                except Exception as e:
                    logging.debug(f"[bt-tether-helper] Poll error: {e}")

            # Stop scanning
            self._log("DEBUG", "Stopping scan...")
            stop_reader.set()
            
            if scan_process and scan_process.poll() is None:
                try:
                    scan_process.stdin.write("scan off\n")
                    scan_process.stdin.write("quit\n")
                    scan_process.stdin.flush()
                    scan_process.wait(timeout=3)
                except Exception:
                    pass
            
            # Also run bluetoothctl scan off separately to ensure scan is stopped
            try:
                subprocess.run(
                    ["bluetoothctl", "scan", "off"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=3,
                )
            except Exception:
                pass

            # Wait for reader thread to finish
            if reader_thread and reader_thread.is_alive():
                reader_thread.join(timeout=2)

            # Final poll to get any remaining devices
            self._log("DEBUG", "Running final device poll...")
            try:
                final_result = subprocess.run(
                    ["bluetoothctl", "devices"],
                    capture_output=True,
                    text=True,
                    timeout=3
                )
                final_count = 0
                if final_result.returncode == 0:
                    for line in final_result.stdout.split("\n"):
                        if line.strip().startswith("Device"):
                            final_count += 1
                            parts = line.strip().split(" ", 2)
                            if len(parts) >= 2:
                                mac = parts[1].upper()
                                name = parts[2] if len(parts) > 2 else "Unknown Device"
                                if mac not in discovered_devices:
                                    discovered_devices[mac] = name
                    if final_count > 0:
                        self._log("DEBUG", f"Final poll found {final_count} device(s)")
                else:
                    self._log("WARNING", f"Final poll failed with return code {final_result.returncode}")
            except Exception as e:
                self._log("DEBUG", f"Final poll error: {e}")

            # Build final device list
            devices = [{"mac": mac, "name": name} for mac, name in discovered_devices.items()]
            if len(devices) == 0:
                self._log("WARNING", "Scan complete - found 0 device(s). Make sure Bluetooth devices are nearby and discoverable.")
            else:
                self._log("INFO", f"Scan complete - found {len(devices)} device(s)")
            return devices

        except Exception as e:
            self._log("ERROR", f"Scan error: {e}")
            import traceback
            logging.debug(f"[bt-tether-helper] Scan traceback: {traceback.format_exc()}")
            return []
        finally:
            # Signal reader to stop
            stop_reader.set()
            
            # Clean up scan process
            if scan_process and scan_process.poll() is None:
                try:
                    scan_process.terminate()
                    scan_process.wait(timeout=2)
                except Exception:
                    try:
                        scan_process.kill()
                    except Exception:
                        pass
            
            # Always clear scanning flag
            with self.lock:
                self._scanning = False
                self._screen_needs_refresh = True

    def _parse_bluetooth_devices(self):
        """Parse bluetoothctl devices output into list of dicts."""
        devices = []
        seen_macs = set()

        output = self._run_cmd(["bluetoothctl", "devices"], capture=True)
        if not output or output == "Timeout":
            return devices

        for line in output.split("\n"):
            if line.strip().startswith("Device"):
                parts = line.strip().split(" ", 2)
                if len(parts) >= 2:
                    mac = parts[1]
                    if mac not in seen_macs:
                        seen_macs.add(mac)
                        name = parts[2] if len(parts) > 2 else "Unknown Device"
                        devices.append({"mac": mac, "name": name})

        return devices

    def start_connection(self):
        with self.lock:
            # If phone_mac is already set (e.g., from /connect endpoint), find that specific device
            # Otherwise, find the best device to connect to
            if self.phone_mac:
                # User selected a specific device - find it in trusted devices
                target_mac = self.phone_mac
                best_device = None

                try:
                    trusted_devices = self._get_trusted_devices()
                    for device in trusted_devices:
                        if device["mac"] == target_mac:
                            best_device = device
                            self._log(
                                "INFO",
                                f"Connecting to user-selected device: {device['name']} ({device['mac']})",
                            )
                            break

                    # If not found in trusted devices, create a basic device info
                    if not best_device:
                        self._log(
                            "WARNING",
                            f"Selected device {target_mac} not in trusted devices, attempting connection anyway",
                        )
                        best_device = {
                            "mac": target_mac,
                            "name": "Unknown Device",
                            "paired": False,
                            "trusted": False,
                            "connected": False,
                            "has_nap": True,
                        }
                except Exception as e:
                    self._log("ERROR", f"Error finding selected device: {e}")
                    best_device = None
            else:
                # No specific device selected - find the best one automatically
                best_device = self._find_best_device_to_connect()

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
            self._connection_start_time = time.time()  # Track when connection started
            self._user_requested_disconnect = False  # Re-enable auto-reconnect
            self.status = self.STATE_CONNECTING
            self.message = f"Connecting to {best_device['name']}..."
            self.phone_mac = best_device[
                "mac"
            ]  # Set phone_mac immediately so screen knows which device we're connecting to

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

            # Disconnect any existing connections first (can only tether to one device at a time)
            try:
                devices_output = self._run_cmd(
                    ["bluetoothctl", "devices", "Connected"], capture=True
                )
                if devices_output and devices_output != "Timeout":
                    for line in devices_output.split("\n"):
                        if line.strip() and line.startswith("Device"):
                            parts = line.strip().split(" ", 2)
                            if len(parts) >= 2:
                                connected_mac = parts[1]
                                if (
                                    connected_mac != mac
                                ):  # Don't disconnect the device we're connecting to
                                    connected_name = (
                                        parts[2] if len(parts) > 2 else "Unknown"
                                    )
                                    self._log(
                                        "INFO",
                                        f"Disconnecting from {connected_name} ({connected_mac})...",
                                    )
                                    self._run_cmd(
                                        ["bluetoothctl", "disconnect", connected_mac],
                                        capture=True,
                                    )
                                    time.sleep(1)
            except Exception as e:
                self._log("WARNING", f"Failed to check for existing connections: {e}")

            # Check if Bluetooth is responsive, restart if needed
            if not self._restart_bluetooth_if_needed():
                self._log(
                    "ERROR",
                    "Bluetooth service is unresponsive and couldn't be restarted",
                )
                with self.lock:
                    self.status = self.STATE_ERROR
                    self.message = "Bluetooth service unresponsive. Try: sudo systemctl restart bluetooth"
                    self._connection_in_progress = False
                return

            # First check current pairing status
            with self.lock:
                self.message = f"Checking pairing status with {device_name}..."
                self._screen_needs_refresh = True
            pair_status = self._check_pair_status(mac)

            # If device is already paired and trusted, skip directly to connection
            if pair_status["paired"] and pair_status.get("trusted", False):
                self._log("INFO", f"Device {device_name} already paired and trusted, connecting...")
                with self.lock:
                    self.message = f"Device {device_name} ready, connecting..."
                    self._screen_needs_refresh = True
                
                # Unblock just in case
                self._run_cmd(["bluetoothctl", "unblock", mac], capture=True)
                time.sleep(self.DEVICE_OPERATION_DELAY)
            else:
                # Need to pair/trust the device first
                self._log("INFO", f"Making Pwnagotchi discoverable...")
                with self.lock:
                    self.message = f"Making Pwnagotchi discoverable for {device_name}..."
                    self._screen_needs_refresh = True
                self._run_cmd(["bluetoothctl", "discoverable", "on"], capture=True)
                self._run_cmd(["bluetoothctl", "pairable", "on"], capture=True)
                time.sleep(self.DEVICE_OPERATION_LONGER_DELAY)

                # If device is not paired, we need to pair first
                if not pair_status["paired"]:
                    # Not paired - just unblock in case it was blocked
                    self._log("INFO", f"Unblocking {device_name} in case it was blocked...")
                    with self.lock:
                        self.message = f"Preparing to pair with {device_name}..."
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
                            self._screen_needs_refresh = True
                        self._force_ui_refresh()
                        return

                    self._log("INFO", f"Pairing with {device_name} successful!")
                else:
                    self._log("INFO", f"Device {device_name} already paired")
                    with self.lock:
                        self.message = f"Device {device_name} already paired ✓"
                        self._screen_needs_refresh = True

                # Trust the device - set TRUSTING state
                logging.info(f"[bt-tether-helper] Trusting device {device_name}...")
                with self.lock:
                    self.status = self.STATE_TRUSTING
                    self.message = f"Trusting {device_name}..."
                    self._screen_needs_refresh = True

                # Brief delay to ensure TRUSTING state is displayed
                time.sleep(0.5)

                self._run_cmd(["bluetoothctl", "trust", mac])

                # Wait for phone to be ready after pairing/trust
                logging.info(f"[bt-tether-helper] Waiting for {device_name} to be ready...")
                with self.lock:
                    self.message = f"Waiting for {device_name} to be ready..."
                    self._screen_needs_refresh = True
                time.sleep(self.PHONE_READY_WAIT)

            # Check if already connected before trying to connect
            status_check = self._check_pair_status(mac)
            if status_check.get("connected", False):
                self._log("INFO", "✓ Bluetooth already connected, proceeding to NAP")
            else:
                # Establish base Bluetooth connection first (required before NAP)
                self._log("INFO", "Establishing Bluetooth connection...")
                with self.lock:
                    self.status = self.STATE_CONNECTING
                    self.message = "Connecting via Bluetooth..."
                    self._screen_needs_refresh = True
                
                # Try bluetoothctl connect with reasonable timeout
                connect_result = self._run_cmd(["bluetoothctl", "connect", mac], capture=True, timeout=10)
                
                if connect_result and "Connection successful" in connect_result:
                    self._log("INFO", "✓ Bluetooth connection established")
                    time.sleep(2)  # Give connection time to stabilize
                elif connect_result and "already connected" in connect_result.lower():
                    self._log("INFO", "✓ Bluetooth already connected")
                elif connect_result and "Failed to connect" in connect_result:
                    self._log("WARNING", "Bluetooth connection failed, trying NAP anyway...")
                else:
                    self._log("WARNING", "Bluetooth connect timed out, checking status...")
                    # Kill any hung bluetoothctl processes
                    self._run_cmd(["pkill", "-9", "bluetoothctl"], capture=True, timeout=2)
                    time.sleep(1)
            
            # Now try NAP connection over the established Bluetooth link
            self._log("INFO", "Connecting to NAP profile...")
            with self.lock:
                self.status = self.STATE_CONNECTING
                self.message = "Connecting to NAP profile for internet..."
                self._screen_needs_refresh = True

            nap_connected = self._connect_nap_dbus(mac)

            if nap_connected:
                self._log("INFO", "NAP connection successful!")

                # Check if PAN interface is up
                if self._pan_active():
                    iface = self._get_pan_interface()
                    self._log("INFO", f"✓ PAN interface active: {iface}")

                    # Wait for interface initialization
                    self._log("INFO", "Waiting for interface initialization...")
                    time.sleep(2)

                    # Setup network with DHCP
                    if self._setup_network_dhcp(iface):
                        self._log("INFO", "✓ Network setup successful")
                    else:
                        self._log("WARNING", "Network setup failed, connection may not work")

                    # Wait a bit for network to stabilize
                    time.sleep(2)

                    # Verify internet connectivity
                    self._log("INFO", "Checking internet connectivity...")
                    with self.lock:
                        self.message = "Verifying internet connection..."
                        self._screen_needs_refresh = True

                    if self._check_internet_connectivity():
                        self._log("INFO", "✓ Internet connectivity verified!")

                        # Get IP address and send Discord notification if configured
                        try:
                            current_ip = self._get_current_ip()
                            if current_ip:
                                self._log("INFO", f"Current IP address: {current_ip}")

                                # Now test DNS resolution after we have confirmed IP
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

                                if self.discord_webhook_url:
                                    self._log(
                                        "INFO",
                                        "Discord webhook configured, starting notification thread...",
                                    )
                                    threading.Thread(
                                        target=self._send_discord_notification,
                                        args=(current_ip,),
                                        daemon=True,
                                    ).start()
                                else:
                                    self._log(
                                        "DEBUG",
                                        "Discord webhook not configured, skipping notification",
                                    )
                            else:
                                self._log(
                                    "WARNING",
                                    "Could not get IP address for Discord notification",
                                )
                        except Exception as e:
                            self._log(
                                "ERROR", f"Failed to send Discord notification: {e}"
                            )

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

                        self._log("DEBUG", "Connection complete, flags cleared")
                        self._force_ui_refresh()

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

                        self._force_ui_refresh()
                else:
                    self._log("WARNING", "NAP connected but no interface detected")
                    # Update cached UI status first
                    self._update_cached_ui_status(mac=mac)

                    with self.lock:
                        self.status = self.STATE_CONNECTED
                        self.message = "Connected but no internet. Enable Bluetooth tethering on phone."
                        self._connection_in_progress = False
                        self._connection_start_time = None
                        self._initializing = False
                        self._screen_needs_refresh = True
            else:
                self._log("WARNING", "NAP connection failed")

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
                self._force_ui_refresh()

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

            self._force_ui_refresh()

    def _strip_ansi_codes(self, text):
        """Remove ANSI color/control codes from text"""
        if not text:
            return text

        # Remove ANSI escape sequences
        ansi_escape = re.compile(r"\x1b\[[0-9;]*[mGKHF]|\x01|\x02")
        text = ansi_escape.sub("", text)

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

    def _check_bluetooth_responsive(self):
        """Quick check if bluetoothctl is responsive"""
        try:
            result = subprocess.run(
                ["bluetoothctl", "show"],
                capture_output=True,
                timeout=10,  # Increased timeout for slow hardware (RPi Zero 2W)
                text=True,
            )
            return result.returncode == 0 and "Powered:" in result.stdout
        except Exception as e:
            logging.debug(f"[bt-tether-helper] Bluetooth responsive check failed: {e}")
            return False

    def _restart_bluetooth_if_needed(self):
        """Restart Bluetooth service if it's unresponsive"""
        if not self._check_bluetooth_responsive():
            logging.warning(
                "[bt-tether-helper] Bluetooth appears hung, restarting service..."
            )
            try:
                subprocess.run(
                    ["pkill", "-9", "bluetoothctl"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=2,
                )
                subprocess.run(
                    ["systemctl", "restart", "bluetooth"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=30,  # Increased timeout for RPi Zero 2W
                )
                time.sleep(5)  # Extra time on slow hardware
                # Power on adapter after restart
                subprocess.run(
                    ["bluetoothctl", "power", "on"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=10,
                )
                time.sleep(1)
                self._log("INFO", "Bluetooth service restarted")
                return True
            except Exception as e:
                self._log("ERROR", f"Failed to restart Bluetooth: {e}")
                return False
        return True

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
        """Setup network for bnep0 interface using dhclient"""
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

            # Use dhclient directly (more reliable for Bluetooth PAN)
            return self._setup_dhclient(iface)

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

    def _setup_dhclient(self, iface):
        """Request DHCP on interface"""
        try:
            self._log("INFO", f"Setting up {iface} for DHCP...")

            # Kill any existing DHCP clients for this interface first
            # This is critical when switching between devices on the same interface
            subprocess.run(
                ["sudo", "pkill", "-f", f"dhcpcd.*{iface}"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=3,
            )
            subprocess.run(
                ["sudo", "pkill", "-f", f"dhclient.*{iface}"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=3,
            )
            time.sleep(1)

            # Reset interfacex - bring down then up to clear any stale state
            self._log("INFO", f"Resetting {iface}...")
            subprocess.run(
                ["sudo", "ip", "link", "set", iface, "down"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=3,
            )
            time.sleep(0.5)
            subprocess.run(
                ["sudo", "ip", "link", "set", iface, "up"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=5,
            )
            time.sleep(1)

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
                # Release any existing lease first
                subprocess.run(
                    ["sudo", "dhcpcd", "-k", iface],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                )
                time.sleep(self.DHCP_RELEASE_WAIT)
                # Request new lease with metric to make it a backup route
                # Lower metric = higher priority, so we use 200 to be backup to most connections
                result = subprocess.run(
                    ["sudo", "dhcpcd", "-4", "-n", "-m", "200", iface],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=self.DHCPCD_TIMEOUT,
                )
                if result.stdout.strip():
                    self._log("INFO", f"dhcpcd: {result.stdout.strip()}")
                if result.returncode == 0:
                    dhcp_success = True
                else:
                    self._log("WARNING", f"dhcpcd failed: {result.stderr.strip()}")

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
                self._set_route_metric(iface, 200)
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

    def _set_route_metric(self, iface, metric=200):
        """Set the metric for default route through interface to make it a backup connection.

        Lower metric = higher priority
        Common metrics:
        - 0-100: Primary connections (Ethernet, USB tethering)
        - 200: Bluetooth (backup connection)
        - 300+: Low priority backup connections
        """
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

            # First try to delete any existing default route for this interface
            del_result = subprocess.run(
                ["sudo", "ip", "route", "del", "default", "dev", iface],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=5,
            )

            # Also try to delete any existing route with this gateway (from previous connections)
            subprocess.run(
                ["sudo", "ip", "route", "del", "default", "via", gateway],
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
                stderr = result.stderr.decode("utf-8").strip()
                # Only log as warning if it's not a "File exists" error (which means route is already set)
                if "File exists" in stderr:
                    self._log(
                        "DEBUG",
                        f"Route already exists for {iface} with metric {metric}",
                    )
                    return True
                else:
                    self._log("WARNING", f"Failed to set route metric: {stderr}")
                    return False

        except Exception as e:
            self._log("DEBUG", f"Error setting route metric: {e}")
            return False

    def _check_internet_connectivity(self):
        """Check if internet is accessible via Bluetooth interface specifically"""
        try:
            # Get the BT interface
            bt_iface = self._get_pan_interface() or "bnep0"

            # First verify bnep0 has an IP - if not, no point testing connectivity
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

            ip_match = re.search(r"inet\s+(\d+\.\d+\.\d+\.\d+)", ip_result.stdout)
            if not ip_match or ip_match.group(1).startswith("169.254."):
                logging.warning(f"[bt-tether-helper] {bt_iface} has no valid IP")
                return False

            bt_ip = ip_match.group(1)
            logging.info(f"[bt-tether-helper] {bt_iface} has IP: {bt_ip}")

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

            # Ping via the Bluetooth interface specifically
            logging.info(
                f"[bt-tether-helper] Testing connectivity to 8.8.8.8 via {bt_iface}..."
            )
            result = subprocess.run(
                ["ping", "-c", "2", "-W", "3", "-I", bt_iface, "8.8.8.8"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10,
            )

            if result.returncode == 0:
                logging.info(f"[bt-tether-helper] ✓ Ping to 8.8.8.8 successful")
                return True
            else:
                logging.warning(f"[bt-tether-helper] Ping to 8.8.8.8 failed via {bt_iface}")
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
                "dns_success": False,
                "bnep0_ip": None,
                "default_route": None,
                "dns_servers": None,
                "dns_error": None,
                "localhost_routes": None,
            }

            # Test ping to 8.8.8.8
            try:
                ping_result = subprocess.run(
                    ["ping", "-c", "2", "-W", "3", "8.8.8.8"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=5,
                )
                result["ping_success"] = ping_result.returncode == 0
                logging.info(
                    f"[bt-tether-helper] Ping test: {'Success' if result['ping_success'] else 'Failed'}"
                )
            except Exception as e:
                logging.warning(f"[bt-tether-helper] Ping test error: {e}")

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
                logging.info(f"[bt-tether-helper] bnep0 IP: {result['bnep0_ip']}")
            except Exception as e:
                logging.warning(f"[bt-tether-helper] Get bnep0 IP error: {e}")

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
                "dns_success": False,
                "bnep0_ip": None,
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

    def _check_nap_service_available(self, mac):
        """Check if the device advertises NAP (Network Access Point) service"""
        try:
            info = self._run_cmd(["bluetoothctl", "info", mac], capture=True)
            if not info:
                return False

            # Look for NAP UUID in the UUIDs list
            # NAP UUID: 00001116-0000-1000-8000-00805f9b34fb
            nap_available = "00001116-0000-1000-8000-00805f9b34fb" in info

            if nap_available:
                logging.info(f"[bt-tether-helper] ✓ NAP service found on device {mac}")
            else:
                logging.warning(
                    f"[bt-tether-helper] ✗ NAP service NOT found on device {mac}"
                )
                logging.warning(f"[bt-tether-helper] Available services:\n{info}")

            return nap_available
        except Exception as e:
            logging.error(f"[bt-tether-helper] Failed to check NAP service: {e}")
            return False

    def _pair_device_interactive(self, mac):
        """Pair device - persistent agent will handle the dialog.
        Starts background scan because bluetoothctl remove clears the device from cache.
        """
        scan_process = None
        try:
            logging.info(f"[bt-tether-helper] Starting pairing with {mac}...")

            with self.lock:
                self.message = "Preparing to pair..."

            # Ensure Bluetooth is powered on and in pairable mode
            self._run_cmd(["bluetoothctl", "power", "on"], capture=True)
            self._run_cmd(["bluetoothctl", "pairable", "on"], capture=True)
            self._run_cmd(["bluetoothctl", "discoverable", "on"], capture=True)
            time.sleep(1)

            # Start background scan to keep device discoverable during pairing
            logging.info(f"[bt-tether-helper] Starting background scan for pairing...")

            env = dict(os.environ)
            env["NO_COLOR"] = "1"
            env["TERM"] = "dumb"

            scan_process = subprocess.Popen(
                ["bluetoothctl"],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
                env=env,
            )
            scan_process.stdin.write("scan on\n")
            scan_process.stdin.flush()

            # Brief wait for scan to start and device to be discovered
            time.sleep(3)

            with self.lock:
                self.message = "Initiating pairing..."

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

                            # Invalidate cache so web UI gets fresh status with passkey
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

                                # Invalidate cache so web UI gets fresh status with passkey

                # Wait for process to complete
                returncode = process.wait(timeout=90)
                output = "".join(output_lines)
                clean_output = self._strip_ansi_codes(output)

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
                logging.error(f"[bt-tether-helper] Pairing timeout (90s)")
                return False

        except Exception as e:
            logging.error(f"[bt-tether-helper] Pairing error: {e}")
            return False
        finally:
            # Stop background scan
            if scan_process:
                try:
                    scan_process.stdin.write("scan off\nexit\n")
                    scan_process.stdin.flush()
                    scan_process.wait(timeout=2)
                except:
                    try:
                        scan_process.kill()
                    except:
                        pass

    def _send_discord_notification(self, ip_address):
        """Send IP address notification to Discord webhook if configured"""
        self._log("INFO", f"Discord notification function called with IP: {ip_address}")

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

            data = {
                "embeds": [
                    {
                        "title": "🔷 Bluetooth Tethering Connected",
                        "description": f"**{pwnagotchi_name}** is now connected via Bluetooth",
                        "color": 3447003,
                        "fields": [
                            {
                                "name": "IP Address",
                                "value": f"`{ip_address}`",
                                "inline": True,
                            },
                            {
                                "name": "Device",
                                "value": pwnagotchi_name,
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

            # Set default socket timeout to prevent DNS resolution hangs
            old_timeout = socket.getdefaulttimeout()
            socket.setdefaulttimeout(5)

            try:
                # Send POST request to Discord webhook with short timeout
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
                # Use shorter timeout (5 seconds) to prevent hanging
                with urllib.request.urlopen(req, timeout=5) as response:
                    status_code = response.status
                    self._log("INFO", f"Discord webhook response status: {status_code}")
                    if status_code == 204 or status_code == 200:
                        self._log("INFO", "✓ Discord notification sent successfully")
                    else:
                        response_body = response.read().decode("utf-8")
                        self._log(
                            "WARNING",
                            f"Discord webhook returned status {status_code}: {response_body}",
                        )
            finally:
                # Restore original timeout
                socket.setdefaulttimeout(old_timeout)

        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8") if e.fp else "No response body"
            self._log("ERROR", f"Discord webhook HTTP error {e.code}: {e.reason}")
            self._log("ERROR", f"Response body: {error_body}")
        except socket.timeout:
            self._log("ERROR", f"Discord webhook timed out after 5 seconds")
        except urllib.error.URLError as e:
            self._log("ERROR", f"Discord webhook failed (network error): {e.reason}")
        except Exception as e:
            self._log("ERROR", f"Discord webhook failed: {type(e).__name__}: {e}")
            self._log("DEBUG", f"Traceback: {traceback.format_exc()}")

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
        """Connect to NAP service using DBus directly"""
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

            # Find the device object path
            logging.info("[bt-tether-helper] Searching for device in BlueZ...")
            objects = manager.GetManagedObjects()
            device_path = None
            for path, interfaces in objects.items():
                if "org.bluez.Device1" in interfaces:
                    props = interfaces["org.bluez.Device1"]
                    if props.get("Address") == mac:
                        device_path = path
                        logging.info(
                            f"[bt-tether-helper] Found device at path: {device_path}"
                        )
                        break

            if not device_path:
                logging.error(
                    f"[bt-tether-helper] Device {mac} not found in BlueZ managed objects"
                )
                return False

            # Connect to NAP service UUID
            NAP_UUID = "00001116-0000-1000-8000-00805f9b34fb"
            logging.info(
                f"[bt-tether-helper] Connecting to NAP profile (UUID: {NAP_UUID})..."
            )
            device = dbus.Interface(
                bus.get_object("org.bluez", device_path), "org.bluez.Device1"
            )

            # Set a timeout for the ConnectProfile call to prevent hanging
            try:
                device.ConnectProfile(NAP_UUID, timeout=30)
                logging.info(
                    f"[bt-tether-helper] ✓ NAP profile connected successfully via DBus"
                )
                return True
            except dbus.exceptions.DBusException as dbus_err:
                error_msg = str(dbus_err)
                logging.error(
                    f"[bt-tether-helper] DBus NAP connection failed: {dbus_err}"
                )

                # Check for authentication/pairing errors - if phone was unpaired, remove pairing on Pwnagotchi side too
                # BUT: Don't remove for tethering-disabled errors (br-connection-create-socket, br-connection-profile-unavailable)
                if (
                    "Authentication Rejected" in error_msg
                    or "Connection refused" in error_msg
                    or "br-connection-page-timeout" in error_msg
                    or "br-connection-unknown" in error_msg
                    or "Host is down" in error_msg
                ):
                    self._log(
                        "WARNING",
                        "⚠️  Device may have been unpaired from phone - removing stale pairing",
                    )
                    # Remove the pairing to prevent repeated failed connection attempts
                    try:
                        self._run_cmd(["bluetoothctl", "remove", mac], timeout=5)
                        self._log(
                            "INFO",
                            "Removed stale pairing - use web UI to re-pair if needed",
                        )
                        # Also clear the phone_mac to force re-scanning
                        with self.lock:
                            self.phone_mac = ""
                    except Exception as e:
                        logging.debug(f"Failed to remove pairing: {e}")

                # Check for common errors and provide helpful hints
                if (
                    "br-connection-create-socket" in error_msg
                    or "br-connection-profile-unavailable" in error_msg
                ):
                    self._log(
                        "ERROR",
                        "⚠️  Bluetooth tethering is NOT enabled on your phone!",
                    )
                    self._log(
                        "ERROR",
                        "Go to Settings → Network & internet → Hotspot & tethering → Enable 'Bluetooth tethering'",
                    )
                elif "NoReply" in error_msg or "Did not receive a reply" in error_msg:
                    self._log(
                        "ERROR",
                        "⚠️  Phone's Bluetooth is not responding to connection requests",
                    )
                    self._log(
                        "ERROR",
                        "📱 On your phone: Forget/unpair this device in Bluetooth settings",
                    )
                    self._log(
                        "ERROR",
                        "🔄 Then toggle Bluetooth tethering OFF and back ON",
                    )
                    self._log(
                        "ERROR",
                        "🔌 Finally, reconnect from the web UI to re-pair",
                    )
                elif "br-connection-busy" in error_msg or "InProgress" in error_msg:
                    self._log(
                        "ERROR",
                        "⚠️  Bluetooth connection is busy, wait a moment and try again",
                    )

                return False

        except ImportError as e:
            logging.error(f"[bt-tether-helper] python3-dbus not installed: {e}")
            logging.error(
                "[bt-tether-helper] Run: sudo apt-get install -y python3-dbus"
            )
            return False
        except Exception as e:
            error_msg = str(e)
            logging.error(
                f"[bt-tether-helper] NAP connection error: {type(e).__name__}: {e}"
            )

            logging.error(f"[bt-tether-helper] Traceback: {traceback.format_exc()}")
            return False

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
