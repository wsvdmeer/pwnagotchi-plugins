"""
Bluetooth Tether Helper Plugin for Pwnagotchi

Required System Packages:
    sudo apt-get update
    sudo apt-get install -y bluez network-manager python3-dbus python3-toml

Features:
- Bluetooth tethering to mobile phones
- Device name updates with IP address (visible in Bluetooth settings)
- Auto-reconnect functionality
- Web UI for easy management

Setup:
1. Install packages: sudo apt-get install -y bluez network-manager python3-dbus python3-toml
2. Enable services:
   sudo systemctl enable bluetooth && sudo systemctl start bluetooth
   sudo systemctl enable NetworkManager && sudo systemctl start NetworkManager
3. Configure plugin in config.toml with phone MAC address
4. Access web UI at http://<pwnagotchi-ip>:8080/plugins/bt-tether-helper

Configuration options:
- main.plugins.bt-tether-helper.mac = "XX:XX:XX:XX:XX:XX"  # Phone MAC address
- main.plugins.bt-tether-helper.advertise_ip = false  # Show IP in device name (default: false, enable for headless)
- main.plugins.bt-tether-helper.auto_reconnect = true  # Auto reconnect on disconnect
- main.plugins.bt-tether-helper.show_on_screen = true  # Show status on display

Device Name with IP (for headless use):
Set advertise_ip = true to automatically update the Bluetooth device name with your IP address.
Format: "{pwnagotchi_name} | {ip_address}"
View this in your phone's Bluetooth settings - perfect for headless setups where you can't see the screen.
Updates occur once after internet connectivity is verified, and again on each reconnection.
When disabled (default), only the pwnagotchi name is shown.
"""

import subprocess
import threading
import time
import logging
import os
import re
import traceback
from pwnagotchi.plugins import Plugin
from flask import render_template_string, request, jsonify
import pwnagotchi.ui.fonts as fonts
from pwnagotchi.ui.components import LabeledValue
from pwnagotchi.ui.view import BLACK

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
    <style>
      body { font-family: sans-serif; padding: 20px; max-width: 600px; margin: 0 auto; background: #f5f5f5; }
      .card { background: white; padding: 20px; border-radius: 8px; margin-bottom: 16px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
      h2 { margin: 0 0 20px 0; color: #333; }
      input { padding: 10px; font-size: 14px; border: 1px solid #ddd; border-radius: 4px; text-transform: uppercase; }
      button { padding: 10px 20px; background: #0066cc; color: white; border: none; cursor: pointer; font-size: 14px; border-radius: 4px; margin-right: 8px; min-height: 42px; display: inline-flex; align-items: center; justify-content: center; }
      button:hover { background: #0052a3; }
      button.danger { background: #dc3545; }
      button.danger:hover { background: #c82333; }
      button.success { background: #28a745; }
      button.success:hover { background: #218838; }
      button:disabled { background: #ccc; cursor: not-allowed; }
      .status-item { padding: 8px; margin: 4px 0; border-radius: 4px; background: #f8f9fa; }
      .status-good { background: #d4edda; color: #155724; }
      .status-bad { background: #f8d7da; color: #721c24; }
      .device-item { padding: 12px; margin: 8px 0; border: 1px solid #ddd; border-radius: 4px; cursor: pointer; display: flex; justify-content: space-between; align-items: center; }
      .device-item:hover { background: #f0f8ff; border-color: #0066cc; }
      .message-box { padding: 12px; border-radius: 4px; margin: 12px 0; }
      .message-info { background: #d1ecf1; color: #0c5460; border: 1px solid #bee5eb; }
      .message-success { background: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
      .message-warning { background: #fff3cd; color: #856404; border: 1px solid #ffeeba; }
      .message-error { background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
      .spinner { display: inline-block; width: 14px; height: 14px; border: 2px solid #f3f3f3; 
                 border-top: 2px solid #0066cc; border-radius: 50%; animation: spin 1s linear infinite; margin-right: 8px; vertical-align: middle; }
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
    <div class="card" id="phoneConnectionCard" style="display: none;">
      <h3 style="margin: 0 0 12px 0;">📱 Phone Connection</h3>
      <div style="background: #1e1e1e; color: #d4d4d4; padding: 12px; border-radius: 4px; margin-bottom: 12px; font-family: 'Courier New', monospace; font-size: 12px; line-height: 1.5;">
        <div style="color: #888; margin-bottom: 4px;">Configured MAC address:</div>
        <div style="color: #4ec9b0; font-size: 14px;">{{ mac if mac else 'Not configured' }}</div>
      </div>
      
      <!-- Status in output style -->
      <div style="background: #1e1e1e; color: #d4d4d4; padding: 12px; border-radius: 4px; margin-bottom: 12px; font-family: 'Courier New', monospace; font-size: 12px; line-height: 1.5;">
        <div style="color: #888; margin-bottom: 8px;">Connection Status:</div>
        <div id="statusActiveConnection" style="display: none; margin: 4px 0; padding: 8px; background: rgba(78, 201, 176, 0.1); border-left: 3px solid #4ec9b0; margin-bottom: 8px;"></div>
        <div id="statusPaired" style="margin: 4px 0;">📱 Paired: <span>Checking...</span></div>
        <div id="statusTrusted" style="margin: 4px 0;">🔐 Trusted: <span>Checking...</span></div>
        <div id="statusConnected" style="margin: 4px 0;">🔵 Connected: <span>Checking...</span></div>
        <div id="statusInternet" style="margin: 4px 0;">🌐 Internet: <span>Checking...</span></div>
        <div id="statusIP" style="display: none; margin: 4px 0;">🔢 IP Address: <span></span></div>
      </div>
      
      <!-- Hidden input for JavaScript to access MAC value -->
      <input type="hidden" id="macInput" value="{{ mac }}" />
      
      <!-- Output Section (shown above connect button) -->
      <div style="margin-bottom: 12px;">
        <h4 style="margin: 0 0 8px 0; color: #666; font-size: 14px;">📋 Output</h4>
        <div id="logViewer">
          <div style="background: #1e1e1e; color: #d4d4d4; padding: 12px; border-radius: 4px; font-family: 'Courier New', monospace; font-size: 12px; max-height: 300px; overflow-y: auto; line-height: 1.5;" id="logContent">
            <div style="color: #888;">Fetching logs...</div>
          </div>
        </div>
      </div>
      
      <!-- Connect/Disconnect Actions -->
      <div id="connectActions">
        <button class="success" onclick="quickConnect()" id="quickConnectBtn" style="width: 100%; margin: 0 0 8px 0;">
          ⚡ Connect to Phone
        </button>
      </div>
      
      <!-- Disconnect Section -->
      <div id="disconnectSection" style="display: none;">
        <label style="display: flex; align-items: center; gap: 12px; padding: 12px; background: #fff3cd; border-radius: 4px; cursor: pointer; margin-bottom: 8px;">
          <input type="checkbox" id="unpairCheckbox" style="width: 20px; height: 20px; margin: 0; cursor: pointer;" />
          <span style="color: #856404; font-size: 14px; font-weight: 500;">Also unpair device (requires passkey on next connection)</span>
        </label>
        <button class="danger" onclick="disconnectDevice()" id="disconnectBtn" style="width: 100%; margin: 0 0 8px 0;">
          🔌 Disconnect
        </button>
      </div>
      
      <small style="color: #666; display: block; margin-bottom: 12px;">Click Connect for first-time pairing. Pairing dialog will appear on your phone. Disconnect blocks device to prevent auto-reconnect.</small>
    </div>
    
    <!-- Test Internet Connectivity -->
    <div class="card" id="testInternetCard" style="display: none;">
      <h3 style="margin: 0 0 12px 0;">🔍 Test Internet Connectivity</h3>
      <button onclick="testInternet()" id="testInternetBtn" style="width: 100%; margin: 0 0 12px 0;">
        🔍 Run Test
      </button>
      
      <!-- Test Results -->
      <div id="testResults" style="display: none;">
        <div id="testResultsMessage" class="message-box message-info"></div>
      </div>
    </div>
    
    <!-- Scan for Devices -->
    <div class="card" id="scanCard">
      <h3 style="margin: 0 0 12px 0;">🔍 Scan for Devices</h3>
      <div id="setupInstructions" style="background: #e7f3ff; padding: 12px; border-radius: 4px; margin-bottom: 12px; border-left: 4px solid #0066cc;">
        <p style="margin: 0 0 8px 0; font-weight: bold;">First-time setup:</p>
        <ol style="margin: 0; padding-left: 20px; line-height: 1.6;">
          <li>Make sure your phone's Bluetooth is ON</li>
          <li>Click "Scan" below to discover devices</li>
          <li>Find your phone in the list and click 📋 Copy MAC</li>
          <li>Open <code style="background: white; padding: 2px 6px; border-radius: 3px;">/etc/pwnagotchi/config.toml</code></li>
          <li>Add: <code style="background: white; padding: 2px 6px; border-radius: 3px;">main.plugins.bt-tether-helper.mac = "XX:XX:XX:XX:XX:XX"</code></li>
          <li>Restart Pwnagotchi to apply changes</li>
        </ol>
      </div>
      <button class="success" onclick="scanDevices()" id="scanBtn" style="width: 100%; margin: 0;">
        🔍 Scan
      </button>
      
      <!-- Discovered Devices List -->
      <div id="scanResults" style="margin-top: 16px; display: none;">
        <h4 style="margin: 0 0 8px 0;">Discovered Devices:</h4>
        <div id="scanStatus" style="color: #666; margin: 8px 0;">Scanning...</div>
        <div id="deviceList"></div>
      </div>
    </div>
    

    
    <script>
      const macInput = document.getElementById("macInput");
      let statusInterval = null;
      let logInterval = null;

      // Update card visibility and status on page load
      updateCardVisibility();
      if (macInput.value && /^([0-9A-F]{2}:){5}[0-9A-F]{2}$/i.test(macInput.value)) {
        checkConnectionStatus();
      }
      
      // Start log polling immediately
      refreshLogs();
      startLogPolling();
      
      function updateCardVisibility() {
        const hasMac = macInput.value && /^([0-9A-F]{2}:){5}[0-9A-F]{2}$/i.test(macInput.value);
        // Always show scan card, just toggle which instructions to show
        const setupInstructions = document.getElementById('setupInstructions');
        if (setupInstructions) {
          setupInstructions.style.display = hasMac ? 'none' : 'block';
        }
        document.getElementById('phoneConnectionCard').style.display = hasMac ? 'block' : 'none';
        document.getElementById('testInternetCard').style.display = hasMac ? 'block' : 'none';
      }

      async function checkConnectionStatus() {
        const mac = macInput.value.trim();
        if (!/^([0-9A-F]{2}:){5}[0-9A-F]{2}$/i.test(mac)) return;
        
        try {
          // First check the plugin's internal status
          const statusResponse = await fetch(`/plugins/bt-tether-helper/status`);
          const statusData = await statusResponse.json();
          
          const response = await fetch(`/plugins/bt-tether-helper/connection-status?mac=${encodeURIComponent(mac)}`);
          const data = await response.json();
          
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
            
            statusActiveConnection.style.display = 'block';
            statusActiveConnection.innerHTML = `${connEmoji} <span style="color: #4ec9b0; font-weight: bold;">${connType}</span> <span style="color: #888;">(${data.default_route_interface})</span>${connDetails}`;
          } else {
            statusActiveConnection.style.display = 'none';
          }
          
          // Manage polling based on connection state
          if (statusData.status === 'CONNECTING' || statusData.status === 'PAIRING' || statusData.status === 'RECONNECTING') {
            // Actively connecting - poll faster (every 2 seconds)
            if (!statusInterval || statusInterval._interval !== 2000) {
              console.log('Connection in progress - fast polling (2s)');
              stopStatusPolling();
              statusInterval = setInterval(checkConnectionStatus, 2000);
              statusInterval._interval = 2000;
            }
          } else {
            // Otherwise poll slower (every 5 seconds) to keep status updated
            if (!statusInterval || statusInterval._interval !== 5000) {
              console.log('Idle/connected - slow polling (5s)');
              stopStatusPolling();
              statusInterval = setInterval(checkConnectionStatus, 5000);
              statusInterval._interval = 5000;
            }
          }
          
          // Update button states
          // Show/hide connect/disconnect buttons based on connection status
          const connectBtn = document.getElementById('quickConnectBtn');
          const disconnectSection = document.getElementById('disconnectSection');
          
          // Set button state based on current status
          if (statusData.status === 'PAIRING' || statusData.status === 'CONNECTING' || statusData.status === 'RECONNECTING') {
            // Show spinner during connection operations
            connectBtn.disabled = true;
            connectBtn.innerHTML = '<span class="spinner"></span> Connecting...';
          } else if (!data.connected) {
            // Enable button when disconnected and not connecting
            connectBtn.disabled = false;
            connectBtn.innerHTML = '⚡ Connect to Phone';
          }
          
          // Show connect button only when paired/trusted but not connected
          // Show disconnect section when connected or paired
          if (data.connected) {
            connectBtn.style.display = 'none';
            disconnectSection.style.display = 'block';
          } else if (data.paired && data.trusted) {
            connectBtn.style.display = 'block';
            disconnectSection.style.display = 'block';
          } else if (data.paired) {
            connectBtn.style.display = 'none';
            disconnectSection.style.display = 'block';
          } else {
            connectBtn.style.display = 'block';
            disconnectSection.style.display = 'none';
          }
          
        } catch (error) {
          console.error('Status check failed:', error);
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

      async function quickConnect() {
        const mac = macInput.value.trim();
        if (!mac || !/^([0-9A-F]{2}:){5}[0-9A-F]{2}$/i.test(mac)) {
          showFeedback("Please enter your phone's MAC address first!", "warning");
          return;
        }

        const quickConnectBtn = document.getElementById('quickConnectBtn');
        quickConnectBtn.disabled = true;
        quickConnectBtn.innerHTML = '<span class="spinner"></span> Connecting...';
        
        showFeedback("Connecting to phone... Watch for pairing dialog!", "info");
        
        try {
          const response = await fetch(`/plugins/bt-tether-helper/connect?mac=${encodeURIComponent(mac)}`, { method: 'GET' });
          const data = await response.json();
          
          if (data.success) {
            showFeedback("Connection started! Check your phone for the pairing dialog.", "success");
            startStatusPolling();
          } else {
            showFeedback("Connection failed: " + data.message, "error");
          }
        } catch (error) {
          showFeedback("Connection failed: " + error.message, "error");
        } finally {
          quickConnectBtn.disabled = false;
          quickConnectBtn.innerHTML = '⚡ Connect to Phone';
        }
      }

      async function scanDevices() {
        const scanBtn = document.getElementById('scanBtn');
        const scanResults = document.getElementById('scanResults');
        const scanStatus = document.getElementById('scanStatus');
        const deviceList = document.getElementById('deviceList');
        
        scanBtn.disabled = true;
        scanBtn.innerHTML = '<span class="spinner"></span> Scanning...';
        scanResults.style.display = 'block';
        deviceList.innerHTML = '';
        scanStatus.innerHTML = '<span class="spinner"></span> Scanning for devices... (30 seconds)';
        
        showFeedback("Scanning for devices... Keep phone Bluetooth settings open!", "info");
        
        try {
          const response = await fetch('/plugins/bt-tether-helper/scan', { method: 'GET' });
          const data = await response.json();
          
          if (data.devices && data.devices.length > 0) {
            // Show all discovered devices with copy buttons
            scanStatus.textContent = `Found ${data.devices.length} device(s):`;
            deviceList.innerHTML = '';
            data.devices.forEach(device => {
              const div = document.createElement('div');
              div.className = 'device-item';
              div.innerHTML = `
                <div>
                  <b>${device.name}</b><br>
                  <small style="color: #666;">${device.mac}</small>
                </div>
                <button onclick="copyMacToClipboard('${device.mac}'); return false;" style="margin: 0;">📋 Copy MAC</button>
              `;
              deviceList.appendChild(div);
            });
            showFeedback(`Found ${data.devices.length} device(s). Copy MAC to add to config.toml`, "success");
          } else {
            scanStatus.textContent = 'No devices found';
            showFeedback("No devices found. Make sure phone Bluetooth is ON.", "warning");
          }
        } catch (error) {
          scanStatus.textContent = 'Scan failed';
          showFeedback("Scan failed: " + error.message, "error");
        } finally {
          scanBtn.disabled = false;
          scanBtn.innerHTML = '🔍 Scan';
        }
      }

      function copyMacToClipboard(mac) {
        navigator.clipboard.writeText(mac).then(() => {
          showFeedback(`MAC address copied: ${mac}\n\nAdd this to your config.toml:\nmain.plugins.bt-tether-helper.mac = "${mac}"`, "success");
        }).catch(err => {
          // Fallback for older browsers
          const textArea = document.createElement('textarea');
          textArea.value = mac;
          document.body.appendChild(textArea);
          textArea.select();
          try {
            document.execCommand('copy');
            showFeedback(`MAC address copied: ${mac}\n\nAdd this to your config.toml:\nmain.plugins.bt-tether-helper.mac = "${mac}"`, "success");
          } catch (err) {
            showFeedback(`Failed to copy. MAC: ${mac}`, "error");
          }
          document.body.removeChild(textArea);
        });
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

      async function disconnectDevice() {
        const mac = macInput.value.trim();
        if (!/^([0-9A-F]{2}:){5}[0-9A-F]{2}$/i.test(mac)) {
          showFeedback("Enter a valid MAC address first", "warning");
          return;
        }
        
        const unpairCheckbox = document.getElementById('unpairCheckbox');
        const shouldUnpair = unpairCheckbox.checked;
        const disconnectBtn = document.getElementById('disconnectBtn');
        
        disconnectBtn.disabled = true;
        disconnectBtn.innerHTML = '<span class="spinner"></span> Disconnecting...';
        
        showFeedback(shouldUnpair ? "Disconnecting and unpairing device..." : "Disconnecting from device...", "info");
        
        try {
          const response = await fetch(`/plugins/bt-tether-helper/disconnect?mac=${encodeURIComponent(mac)}`, { method: 'GET' });
          const data = await response.json();
          
          if (data.success) {
            // Disconnect already removes the device, so no need to call unpair separately
            if (shouldUnpair) {
              showFeedback("Device disconnected and unpaired. Passkey required for next connection.", "success");
            } else {
              showFeedback("Device disconnected and blocked. Phone will see connection drop automatically.", "success");
            }
            
            // Reset the unpair checkbox after successful disconnect
            unpairCheckbox.checked = false;
            
            stopStatusPolling();
            // Wait a moment for backend to complete all operations
            await new Promise(resolve => setTimeout(resolve, 2000));
            // Force fresh status check after disconnect to update UI
            await checkConnectionStatus();
            // Don't restart polling - we're disconnected
          } else {
            showFeedback(data.message || "Disconnect failed", "error");
          }
        } catch (error) {
          showFeedback("Disconnect failed: " + error.message, "error");
        } finally {
          disconnectBtn.disabled = false;
          disconnectBtn.innerHTML = '🔌 Disconnect';
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
            
            // Auto-scroll to bottom
            logContent.scrollTop = logContent.scrollHeight;
          } else {
            logContent.innerHTML = '<div style=\"color: #888;\">No logs available</div>';
          }
        } catch (error) {
          console.error('Failed to fetch logs:', error);
        }
      }
      
      function startLogPolling() {
        if (logInterval) clearInterval(logInterval);
        logInterval = setInterval(refreshLogs, 3000);
      }
      
      function stopLogPolling() {
        if (logInterval) {
          clearInterval(logInterval);
          logInterval = null;
        }
      }
    </script>
  </body>
</html>
"""


class BTTetherHelper(Plugin):
    __author__ = "wsvdmeer"
    __version__ = "0.9.9-beta"
    __license__ = "GPL3"
    __description__ = "Guided Bluetooth tethering with user instructions"

    # Timing constants
    BLUETOOTH_SERVICE_STARTUP_DELAY = 3
    MONITOR_INITIAL_DELAY = 5
    SCAN_DURATION = 30
    DEVICE_OPERATION_DELAY = 1
    DEVICE_OPERATION_LONGER_DELAY = 2
    SCAN_STOP_DELAY = 0.5
    NAP_DISCONNECT_RETRY_DELAY = 1
    PROCESS_CLEANUP_DELAY = 0.2
    DBUS_OPERATION_RETRY_DELAY = 0.1
    NAME_UPDATE_INTERVAL = 30

    def on_loaded(self):
        """Initialize plugin configuration and data structures only - no heavy operations"""
        from collections import deque

        self.phone_mac = self.options.get("mac", "")
        self._status = "IDLE"
        self._message = "Ready"
        self.lock = threading.Lock()
        self.options["csrf_exempt"] = True  # Disable CSRF for this plugin
        self.agent_process = None  # Track agent process
        self.agent_log_fd = None  # File descriptor for agent log
        self.agent_log_path = None  # Path to agent log file
        self.current_passkey = None  # Store passkey for display in UI

        # UI Log buffer - store last 100 log messages
        self._ui_logs = deque(maxlen=100)
        self._ui_log_lock = threading.Lock()
        self.ui_position = self.options.get(
            "position", None
        )  # Screen position for status (None = auto top-right)
        self.show_on_screen = self.options.get(
            "show_on_screen", True
        )  # Enable/disable screen display

        # Detailed status line configuration
        self.show_detailed_status = self.options.get(
            "show_detailed_status", True
        )  # Show detailed status line with IP
        self.detailed_status_position = self.options.get(
            "detailed_status_position", [0, 82]
        )  # Position for detailed status line

        # Auto-reconnect configuration
        self.auto_reconnect = self.options.get(
            "auto_reconnect", True
        )  # Enable automatic reconnection when connection drops
        self.reconnect_interval = self.options.get(
            "reconnect_interval", 60
        )  # Check connection every N seconds (increased for RPi Zero W2)

        # Cache for status to avoid excessive bluetoothctl polling
        self._status_cache = None
        self._status_cache_time = 0
        self._status_cache_ttl = (
            5  # Cache status for 5s to reduce polling while keeping display responsive
        )

        # Lock to prevent multiple bluetoothctl commands from running simultaneously
        self._bluetoothctl_lock = threading.Lock()

        # Flag to indicate when connection/pairing is in progress
        self._connection_in_progress = False
        # Flag to indicate when disconnecting is in progress
        self._disconnecting = False

        # Monitoring thread for automatic reconnection
        self._monitor_thread = None
        self._monitor_stop = threading.Event()
        self._last_known_connected = False  # Track if we were previously connected
        self._reconnect_failure_count = 0  # Track consecutive reconnect failures
        self._max_reconnect_failures = 3  # Stop auto-reconnect after this many failures
        self._user_requested_disconnect = False  # Track if user manually disconnected

        # Device name update configuration
        self.advertise_ip = self.options.get(
            "advertise_ip", False
        )  # Show IP in device name (disabled by default, enable for headless use)
        self._name_update_thread = None
        self._name_update_stop = threading.Event()
        self._connectivity_verified = (
            threading.Event()
        )  # Signal when internet is verified

        # Track if initialization has been done (to prevent double-init from fallback)
        self._initialization_done = threading.Event()

        # Track fallback thread for cleanup
        self._fallback_thread = None

        self._log("INFO", "Plugin configuration loaded")

        # Start fallback initialization thread in case on_ready() is never called
        self._fallback_thread = threading.Thread(
            target=self._fallback_initialization, daemon=True
        )
        self._fallback_thread.start()

    def _fallback_initialization(self):
        """Fallback initialization if on_ready() is not called within timeout"""
        # Wait 15 seconds for on_ready() to be called
        if not self._initialization_done.wait(timeout=15):
            self._log(
                "WARNING", "on_ready() was not called, using fallback initialization"
            )
            self._initialize_bluetooth_services()

    def on_ready(self, agent):
        """Called when everything is ready and the main loop is about to start"""
        self._log("INFO", "on_ready() called, initializing Bluetooth services...")
        # Signal that on_ready was called (prevents fallback from running)
        if not self._initialization_done.is_set():
            self._initialization_done.set()
            self._initialize_bluetooth_services()

    def _initialize_bluetooth_services(self):
        """Initialize Bluetooth services - called by either on_ready() or fallback"""
        try:
            # Kill any lingering bluetoothctl processes to prevent deadlocks
            try:
                subprocess.run(
                    ["pkill", "-9", "bluetoothctl"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                self._log("INFO", "Cleaned up lingering bluetoothctl processes")
            except Exception as e:
                self._log("DEBUG", f"Process cleanup: {e}")

            # Restart bluetooth service to ensure clean state
            try:
                self._log("INFO", "Restarting Bluetooth service...")
                subprocess.run(
                    ["systemctl", "restart", "bluetooth"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                )
                time.sleep(self.BLUETOOTH_SERVICE_STARTUP_DELAY)
                self._log("INFO", "Bluetooth service restarted")
            except Exception as e:
                self._log("WARNING", f"Failed to restart Bluetooth service: {e}")

            # Verify localhost routing is intact (critical for bettercap API)
            try:
                self._verify_localhost_route()
            except Exception as e:
                self._log("WARNING", f"Initial localhost check failed: {e}")

            # Start persistent pairing agent in background
            self._start_pairing_agent()

            # Start connection monitoring thread if auto-reconnect is enabled
            if self.auto_reconnect and self.phone_mac:
                self._start_monitoring_thread()

            # Set initial device name immediately (without IP)
            if DBUS_AVAILABLE:
                try:
                    pwn_name = self._get_pwnagotchi_name()
                    self._log("INFO", f"Setting initial device name: {pwn_name}")
                    self._update_device_name(pwn_name, None)
                except Exception as e:
                    self._log("WARNING", f"Failed to set initial device name: {e}")

            # Start device name update thread
            if self.advertise_ip:
                if not DBUS_AVAILABLE:
                    self._log(
                        "ERROR", "Device name updates disabled - dbus not available"
                    )
                    self._log(
                        "ERROR", "Install with: sudo apt-get install -y python3-dbus"
                    )
                else:
                    self._log("INFO", "Starting device name update thread...")
                    self._start_ble_advertising()
            else:
                self._log("INFO", "Device name IP advertising disabled in config")

            self._log("INFO", "Bluetooth services initialized")
        except Exception as e:
            self._log("ERROR", f"Failed to initialize Bluetooth services: {e}")

            self._log("ERROR", f"Traceback: {traceback.format_exc()}")

    def on_unload(self, ui):
        """Cleanup when plugin is unloaded"""
        try:
            self._log("INFO", "Unloading plugin, cleaning up resources...")

            # Stop monitoring thread
            if self._monitor_thread and self._monitor_thread.is_alive():
                self._monitor_stop.set()
                self._monitor_thread.join(timeout=5)

            # Stop name update thread
            if self._name_update_thread and self._name_update_thread.is_alive():
                self._name_update_stop.set()
                self._name_update_thread.join(timeout=5)

            # Cleanup agent process
            if self.agent_process and self.agent_process.poll() is None:
                try:
                    self.agent_process.terminate()
                    self.agent_process.wait(timeout=3)
                except:
                    try:
                        self.agent_process.kill()
                    except:
                        pass

            # Close agent log file
            if self.agent_log_fd:
                try:
                    self.agent_log_fd.close()
                except:
                    pass

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
        else:  # INFO
            logging.info(full_message)

        # Add to UI log buffer
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
        if self.show_on_screen:
            # If position not specified, place in top-right of screen
            pos = self.ui_position if self.ui_position else (ui.width() / 2 + 50, 0)
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

        # Add detailed status line
        if self.show_detailed_status:
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
        """Update Bluetooth status on screen"""
        if not self.show_on_screen or not self.phone_mac:
            return

        try:
            # Show connecting indicator when connection is in progress
            # > = Connecting/Pairing in progress
            with self.lock:
                connection_in_progress = self._connection_in_progress

            if connection_in_progress:
                ui.set("bt-status", ">")
                # Still update detailed status even during connection/disconnection
                if self.show_detailed_status:
                    try:
                        # Get current status for detailed display
                        status = self._get_full_connection_status(self.phone_mac)
                        detailed = self._format_detailed_status(status)
                        ui.set("bt-detail", detailed)
                    except Exception as detail_error:
                        logging.debug(
                            f"[bt-tether-helper] Detailed status error: {detail_error}"
                        )
                return

            # Invalidate cache to force fresh check on screen updates
            self._invalidate_status_cache()

            # Get current connection status
            status = self._get_full_connection_status(self.phone_mac)

            # Determine display value based on status
            # C = Connected (internet), T = Connected+Trusted (no internet), N = Connected+Untrusted, P = Paired only, D = Disconnected
            if status.get("pan_active", False):
                display = "C"  # Connected with internet
            elif status.get("connected", False) and status.get("trusted", False):
                display = "T"  # Connected and trusted but no internet yet
            elif status.get("connected", False):
                display = "N"  # Connected but not trusted
            elif status.get("paired", False):
                display = "P"  # Paired but not connected
            else:
                display = "D"  # Disconnected

            ui.set("bt-status", display)

            # Update detailed status line
            if self.show_detailed_status:
                try:
                    detailed = self._format_detailed_status(status)
                    ui.set("bt-detail", detailed)
                except Exception as detail_error:
                    logging.debug(
                        f"[bt-tether-helper] Detailed status error: {detail_error}"
                    )

        except Exception as e:
            # Log error but don't crash
            logging.debug(f"[bt-tether-helper] UI update error: {e}")
            # Set to unknown state if error occurs
            try:
                ui.set("bt-status", "?")
                if self.show_detailed_status:
                    ui.set("bt-detail", "BT:Error")
            except:
                pass

    def _format_detailed_status(self, status):
        """Format detailed status line for screen display"""
        # Check if we're disconnecting
        with self.lock:
            disconnecting = self._disconnecting
            connection_in_progress = self._connection_in_progress

        # Get connection state
        connected = status.get("connected", False)
        paired = status.get("paired", False)
        trusted = status.get("trusted", False)
        pan_active = status.get("pan_active", False)
        ip_address = status.get("ip_address")

        # Build status string
        if disconnecting:
            return "BT:Disconnecting..."
        elif connection_in_progress:
            return "BT:Connecting..."
        elif pan_active and ip_address:
            # Connected with IP: just show the IP
            return f"BT:{ip_address}"
        elif connected and trusted:
            # Connected and trusted but no IP yet
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
        logging.info("[bt-tether-helper] Connection monitor started")

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

                # Check current connection status
                status = self._get_full_connection_status(self.phone_mac)

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
                        "[bt-tether-helper] Connection dropped! Attempting to reconnect..."
                    )
                    with self.lock:
                        self.status = "RECONNECTING"
                        self.message = "Connection lost, reconnecting..."

                    # Attempt to reconnect
                    self._reconnect_device()

                # Invalidate cache when connection state changes
                if status["connected"] != self._last_known_connected:
                    self._invalidate_status_cache()

                # Update last known state
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
                        "[bt-tether-helper] Device is paired/trusted but not connected. Attempting connection..."
                    )
                    with self.lock:
                        self.status = "CONNECTING"
                        self.message = "Reconnecting to device..."

                    success = self._reconnect_device()

                    if success:
                        # Reset failure counter on successful connection
                        self._reconnect_failure_count = 0
                    else:
                        # Increment failure counter
                        self._reconnect_failure_count += 1
                        if (
                            self._reconnect_failure_count
                            >= self._max_reconnect_failures
                        ):
                            self._log(
                                "WARNING",
                                f"⚠️  Auto-reconnect stopped after {self._max_reconnect_failures} failed attempts",
                            )
                            self._log(
                                "INFO",
                                "📱 Please check your phone and use the web UI to reconnect manually",
                            )
                            with self.lock:
                                self.status = "DISCONNECTED"
                                self.message = "Auto-reconnect disabled - manual reconnect required"
                elif self._reconnect_failure_count >= self._max_reconnect_failures:
                    # Already exceeded max failures, don't log every time
                    pass
                elif not status["paired"] or not status["trusted"]:
                    # Device not paired/trusted (or blocked), don't attempt auto-reconnect
                    # Reset failure counter since this is intentional
                    self._reconnect_failure_count = 0
                    logging.debug(
                        f"[bt-tether-helper] Device not ready for auto-reconnect (paired={status['paired']}, trusted={status['trusted']})"
                    )

            except Exception as e:
                logging.error(f"[bt-tether-helper] Monitor loop error: {e}")

            # Wait for next check
            time.sleep(self.reconnect_interval)

        logging.info("[bt-tether-helper] Connection monitor stopped")

    def _reconnect_device(self):
        """Attempt to reconnect to a previously paired device"""
        try:
            mac = self.phone_mac
            if not mac:
                self._log("ERROR", "No MAC address configured for reconnection")
                return False

            # Set flag to prevent concurrent operations
            with self.lock:
                self._connection_in_progress = True
            self._invalidate_status_cache()

            self._log("INFO", f"Reconnecting to {mac}...")

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

            # Try NAP connection (this will also establish Bluetooth connection if needed)
            self._log("INFO", f"Attempting NAP connection...")
            nap_connected = self._connect_nap_dbus(mac)

            if nap_connected:
                self._log("INFO", f"✓ Reconnection successful")

                # Wait for PAN interface
                time.sleep(2)

                # Check if PAN interface is up
                if self._pan_active():
                    iface = self._get_pan_interface()
                    self._log("INFO", f"✓ PAN interface active: {iface}")

                    # Setup network with DHCP
                    if self._setup_network_dhcp(iface):
                        self._log("INFO", f"✓ Network setup successful")

                    # Verify internet connectivity
                    time.sleep(2)
                    if self._check_internet_connectivity():
                        self._log("INFO", f"✓ Internet connectivity verified!")
                        self._connectivity_verified.set()  # Signal BLE thread
                        # Update device name with new IP if advertise_ip is enabled
                        if self.advertise_ip and DBUS_AVAILABLE:
                            try:
                                pwn_name = self._get_pwnagotchi_name()
                                current_ip = self._get_current_ip()
                                if current_ip:
                                    self._log(
                                        "INFO",
                                        f"Updating device name to: {pwn_name} | {current_ip}",
                                    )
                                    self._update_device_name(pwn_name, current_ip)
                            except Exception as e:
                                self._log(
                                    "WARNING", f"Failed to update device name: {e}"
                                )
                        # Invalidate cache so screen gets fresh IP
                        self._invalidate_status_cache()
                        with self.lock:
                            self.status = "CONNECTED"
                            self.message = f"✓ Reconnected! Internet via {iface}"
                        return True
                    else:
                        logging.warning(
                            f"[bt-tether-helper] Reconnected but no internet detected"
                        )
                        with self.lock:
                            self.status = "CONNECTED"
                            self.message = f"Reconnected via {iface} but no internet"
                        return True
                else:
                    logging.warning(
                        f"[bt-tether-helper] NAP connected but no interface detected"
                    )
                    with self.lock:
                        self.status = "CONNECTED"
                        self.message = "Reconnected but no PAN interface"
                    return True
            else:
                logging.warning(f"[bt-tether-helper] Reconnection failed")
                with self.lock:
                    self.status = "ERROR"
                    self.message = "Reconnection failed. Will retry later."
                return False

        except Exception as e:
            logging.error(f"[bt-tether-helper] Reconnection error: {e}")
            with self.lock:
                self.status = "ERROR"
                self.message = f"Reconnection error: {str(e)[:50]}"
            return False
        finally:
            with self.lock:
                self._connection_in_progress = False
            self._invalidate_status_cache()

    def _monitor_agent_log_for_passkey(self, passkey_found_event):
        """Monitor agent log file for passkey display in real-time and auto-confirm"""
        try:
            import time

            logging.info("[bt-tether-helper] Monitoring agent log for passkey...")

            # Tail the agent log file
            with open(self.agent_log_path, "r") as f:
                # Seek to end of file
                f.seek(0, 2)

                # Monitor for up to 90 seconds
                start_time = time.time()
                last_prompt = None
                while time.time() - start_time < 90:
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
                                        self.status = "PAIRING"
                                        self.message = f"🔑 PASSKEY: {self.current_passkey}\n\nVerify this matches on your phone, then tap PAIR!"

                                    # Invalidate cache so web UI gets fresh status with passkey
                                    self._invalidate_status_cache()

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

            self._log("INFO", "Agent log monitoring timeout (90s)")
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

            if clean_path == "connect":
                mac = request.args.get("mac", "").strip().upper()
                if mac and self._validate_mac(mac):
                    with self.lock:
                        self.phone_mac = mac
                        self.options["mac"] = self.phone_mac
                    self.start_connection()
                    return jsonify({"success": True, "message": "Connection started"})
                else:
                    return jsonify({"success": False, "message": "Invalid MAC"})

            if clean_path == "status":
                with self.lock:
                    return jsonify(
                        {
                            "status": self.status,
                            "message": self.message,
                            "mac": self.phone_mac,
                        }
                    )

            if clean_path == "disconnect":
                mac = request.args.get("mac", "").strip().upper()
                if mac and self._validate_mac(mac):
                    result = self._disconnect_device(mac)
                    return jsonify(result)
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
                devices = self._scan_devices()
                return jsonify({"devices": devices})

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
                        }
                    )

            if clean_path == "test-internet":
                result = self._test_internet_connectivity()
                return jsonify(result)

            if clean_path == "logs":
                with self._ui_log_lock:
                    logs = list(self._ui_logs)
                return jsonify({"logs": logs})

            return "Not Found", 404
        except Exception as e:
            logging.error(f"[bt-tether-helper] Webhook error: {e}")
            return "Error", 500

    def _validate_mac(self, mac):
        """Validate MAC address format"""

        return bool(re.match(r"^([0-9A-F]{2}:){5}[0-9A-F]{2}$", mac))

    def _disconnect_device(self, mac):
        """Disconnect from a Bluetooth device and remove trust to prevent auto-reconnect"""
        try:
            # FIRST: Set flag to stop auto-reconnect immediately
            with self.lock:
                self._user_requested_disconnect = True

            # Wait briefly for any ongoing reconnect to complete
            with self.lock:
                connection_in_progress = self._connection_in_progress

            if connection_in_progress:
                self._log("INFO", "Waiting for ongoing operation to complete...")
                # Wait up to 5 seconds for current operation to finish
                for _ in range(10):
                    with self.lock:
                        if not self._connection_in_progress:
                            break
                    time.sleep(0.5)

            # Now set flag to prevent monitor from interfering with disconnect
            with self.lock:
                self._connection_in_progress = True
                self._disconnecting = True  # Set disconnecting flag for UI

            self._log("INFO", f"Disconnecting from device {mac}...")

            # FIRST: Disconnect NAP profile via DBus if connected
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
            except Exception as e:
                logging.debug(f"[bt-tether-helper] DBus operation: {e}")

            # Disconnect the Bluetooth connection
            self._log("INFO", "Disconnecting Bluetooth...")
            result = self._run_cmd(["bluetoothctl", "disconnect", mac], capture=True)
            self._log("INFO", f"Disconnect result: {result}")
            time.sleep(self.DEVICE_OPERATION_LONGER_DELAY)

            # Remove trust to prevent automatic reconnection
            self._log("INFO", "Removing trust to prevent auto-reconnect...")
            trust_result = self._run_cmd(["bluetoothctl", "untrust", mac], capture=True)
            self._log("INFO", f"Untrust result: {trust_result}")
            time.sleep(self.DEVICE_OPERATION_DELAY)

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

            # Update internal state
            with self.lock:
                self.status = "DISCONNECTED"
                self.message = "Device disconnected and blocked"
                self._last_known_connected = False
                # Clear passkey after disconnect
                self.current_passkey = None

            # Invalidate status cache again to ensure fresh status on next poll
            self._invalidate_status_cache()

            # Force immediate cache update with disconnected status
            self._status_cache = {
                "paired": False,
                "trusted": False,
                "connected": False,
                "pan_active": False,
                "interface": None,
                "ip_address": None,
                "passkey": None,
                "default_route_interface": None,
            }
            self._status_cache_time = time.time()

            # Return success
            return {
                "success": True,
                "message": f"Device {mac} disconnected, unpaired, and blocked",
            }
        except Exception as e:
            self._log("ERROR", f"Disconnect error: {e}")
            return {"success": False, "message": f"Disconnect failed: {str(e)}"}
        finally:
            # Always clear the flags, even if disconnect fails
            with self.lock:
                self._connection_in_progress = False
                self._disconnecting = False

    def _unpair_device(self, mac):
        """Unpair a Bluetooth device"""
        try:
            # Invalidate status cache before unpair
            self._invalidate_status_cache()

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
                    self.status = "DISCONNECTED"
                    self.message = "Device unpaired"
                    self._last_known_connected = False
                    # Clear passkey after unpair
                    self.current_passkey = None

                # Invalidate status cache again after unpair
                self._invalidate_status_cache()

                # Force immediate cache update with disconnected status
                self._status_cache = {
                    "paired": False,
                    "trusted": False,
                    "connected": False,
                    "pan_active": False,
                    "interface": None,
                    "ip_address": None,
                    "passkey": None,
                    "default_route_interface": None,
                }
                self._status_cache_time = time.time()

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
                return {"paired": False, "connected": False}

            paired = "Paired: yes" in info
            connected = "Connected: yes" in info

            logging.debug(
                f"[bt-tether-helper] Device {mac} - Paired: {paired}, Connected: {connected}"
            )
            return {"paired": paired, "connected": connected}
        except Exception as e:
            self._log("ERROR", f"Pair status check error: {e}")
            return {"paired": False, "connected": False}

    def _invalidate_status_cache(self):
        """Invalidate the status cache to force fresh status check"""
        self._status_cache = None
        self._status_cache_time = 0

    def _get_full_connection_status(self, mac):
        """Get complete connection status including trusted and PAN interface (with caching)"""
        try:
            # If connection/pairing is in progress, return cached status to avoid blocking
            with self.lock:
                connection_in_progress = self._connection_in_progress

            if connection_in_progress:
                if self._status_cache:
                    return self._status_cache
                # Return default "connecting" status if no cache yet
                return {
                    "paired": False,
                    "trusted": False,
                    "connected": False,
                    "pan_active": False,
                    "interface": None,
                }

            # Use cached status if still fresh (< 30 seconds old)
            current_time = time.time()
            if (
                self._status_cache
                and (current_time - self._status_cache_time) < self._status_cache_ttl
            ):
                return self._status_cache

            # First check if device is blocked (bluetoothctl info hangs on blocked devices)
            # Use shorter timeout (5s) for this check since it sometimes hangs
            devices_output = self._run_cmd(
                ["bluetoothctl", "devices", "Blocked"], capture=True, timeout=5
            )

            # If blocked check times out or returns timeout, skip it and try info directly
            if devices_output and devices_output != "Timeout" and mac in devices_output:
                logging.debug(
                    f"[bt-tether-helper] Device {mac} is blocked, returning disconnected status"
                )
                status = {
                    "paired": False,
                    "trusted": False,
                    "connected": False,
                    "pan_active": False,
                    "interface": None,
                    "ip_address": None,
                    "default_route_interface": None,
                }
                # Cache the result
                self._status_cache = status
                self._status_cache_time = current_time
                return status

            # Try to get device info (with 10s timeout)
            info = self._run_cmd(
                ["bluetoothctl", "info", mac], capture=True, timeout=10
            )

            # If info command timed out, return disconnected status
            if info == "Timeout":
                logging.warning(
                    f"[bt-tether-helper] Device info query timed out, returning disconnected status"
                )
                status = {
                    "paired": False,
                    "trusted": False,
                    "connected": False,
                    "pan_active": False,
                    "interface": None,
                    "ip_address": None,
                    "default_route_interface": None,
                }
                # Cache the result
                self._status_cache = status
                self._status_cache_time = current_time
                return status

            if not info or "Device" not in info:
                status = {
                    "paired": False,
                    "trusted": False,
                    "connected": False,
                    "pan_active": False,
                    "interface": None,
                    "ip_address": None,
                    "default_route_interface": None,
                }
                # Cache the result
                self._status_cache = status
                self._status_cache_time = current_time
                return status

            paired = "Paired: yes" in info
            trusted = "Trusted: yes" in info
            connected = "Connected: yes" in info
            pan_active = self._pan_active()
            interface = self._get_pan_interface() if pan_active else None
            ip_address = self._get_interface_ip(interface) if interface else None

            # Get default route interface
            default_route_interface = self._get_default_route_interface()

            # Only log at debug level to reduce spam
            logging.debug(
                f"[bt-tether-helper] Full status - Paired: {paired}, Trusted: {trusted}, Connected: {connected}, PAN: {pan_active}, Interface: {interface}, IP: {ip_address}, Default Route: {default_route_interface}"
            )
            status = {
                "paired": paired,
                "trusted": trusted,
                "connected": connected,
                "pan_active": pan_active,
                "interface": interface,
                "ip_address": ip_address,
                "default_route_interface": default_route_interface,
            }

            # Cache the result
            self._status_cache = status
            self._status_cache_time = current_time
            return status

        except Exception as e:
            self._log("ERROR", f"Connection status check error: {e}")
            status = {
                "paired": False,
                "trusted": False,
                "connected": False,
                "pan_active": False,
                "interface": None,
                "ip_address": None,
                "default_route_interface": None,
            }
            # Cache error result too to avoid rapid retries
            self._status_cache = status
            self._status_cache_time = current_time
            return status

    def _scan_devices(self):
        """Scan for Bluetooth devices and return list with MACs and names"""
        try:
            logging.info("[bt-tether-helper] Starting device scan...")

            # Power on bluetooth
            self._run_cmd(["bluetoothctl", "power", "on"], capture=True)
            time.sleep(1)

            # Start scanning
            self._log("INFO", "Starting scan...")
            # Use subprocess directly to prevent [CHG] messages in logs
            try:
                subprocess.Popen(
                    ["bluetoothctl", "scan", "on"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception as e:
                self._log("DEBUG", f"Failed to start scan: {e}")

            # Scan for configured duration
            time.sleep(self.SCAN_DURATION)

            # Get devices
            devices_output = self._run_cmd(["bluetoothctl", "devices"], capture=True)

            # Stop scanning
            try:
                subprocess.Popen(
                    ["bluetoothctl", "scan", "off"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                time.sleep(self.SCAN_STOP_DELAY)
            except Exception as e:
                self._log("DEBUG", f"Failed to stop scan: {e}")

            devices = []
            if devices_output:
                for line in devices_output.split("\n"):
                    if line.strip() and line.startswith("Device"):
                        parts = line.strip().split(" ", 2)
                        if len(parts) >= 2:
                            mac = parts[1]
                            name = parts[2] if len(parts) > 2 else "Unknown Device"
                            devices.append({"mac": mac, "name": name})
                            self._log("INFO", f"Scan found: {name} ({mac})")

            logging.info(
                f"[bt-tether-helper] Scan complete. Found {len(devices)} devices"
            )
            return devices

        except Exception as e:
            self._log("ERROR", f"Scan error: {e}")
            return []

    def start_connection(self):
        with self.lock:
            if not self.phone_mac:
                self.status = "ERROR"
                self.message = "No MAC address set"
                return

            # Check if connection is already in progress (prevents multiple threads)
            if self._connection_in_progress:
                self._log(
                    "WARNING",
                    "Connection already in progress, ignoring duplicate request",
                )
                self.message = "Connection already in progress"
                return

            if self.status in ["PAIRING", "CONNECTING"]:
                self._log(
                    "WARNING", "Already pairing/connecting, ignoring duplicate request"
                )
                self.message = "Connection already in progress"
                return

            # Set flag INSIDE the lock to prevent race condition
            self._connection_in_progress = True
            self._user_requested_disconnect = False  # Re-enable auto-reconnect

        # Reset failure counter on manual reconnect
        self._reconnect_failure_count = 0

        # Invalidate status cache to get fresh status during connection
        self._invalidate_status_cache()

        threading.Thread(target=self._connect_thread, daemon=True).start()

    def _connect_thread(self):
        """Full automatic connection thread with pairing and connection logic"""
        try:
            mac = self.phone_mac
            self._log("INFO", f"Starting connection to {mac}...")

            # Check if Bluetooth is responsive, restart if needed
            if not self._restart_bluetooth_if_needed():
                self._log(
                    "ERROR",
                    "Bluetooth service is unresponsive and couldn't be restarted",
                )
                with self.lock:
                    self.status = "ERROR"
                    self.message = "Bluetooth service unresponsive. Try: sudo systemctl restart bluetooth"
                return

            # Make Pwnagotchi discoverable and pairable
            self._log("INFO", f"Making Pwnagotchi discoverable...")
            with self.lock:
                self.message = "Making Pwnagotchi discoverable..."
            self._run_cmd(["bluetoothctl", "discoverable", "on"], capture=True)
            self._run_cmd(["bluetoothctl", "pairable", "on"], capture=True)
            time.sleep(self.DEVICE_OPERATION_LONGER_DELAY)

            # Remove device completely to ensure fresh pairing
            self._log("INFO", "Removing device for fresh pairing...")
            with self.lock:
                self.message = "Removing old pairing..."
            self._run_cmd(["bluetoothctl", "remove", mac], capture=True)
            time.sleep(self.DEVICE_OPERATION_DELAY)

            self._log("INFO", "Unblocking device in case it was blocked...")
            with self.lock:
                self.message = "Unblocking device..."
            self._run_cmd(["bluetoothctl", "unblock", mac], capture=True)
            time.sleep(self.DEVICE_OPERATION_DELAY)

            # Check if already paired
            with self.lock:
                self.message = "Checking pairing status..."
            pair_status = self._check_pair_status(mac)

            if not pair_status["paired"]:
                self._log("INFO", "Device not paired. Starting pairing process...")
                with self.lock:
                    self.status = "PAIRING"
                    self.message = "Device not paired. Starting pairing process..."

                # Attempt pairing - this will show dialog on phone
                if not self._pair_device_interactive(mac):
                    self._log("ERROR", "Pairing failed!")
                    with self.lock:
                        self.status = "ERROR"
                        self.message = (
                            "Pairing failed. Did you accept the dialog on your phone?"
                        )
                    return

                self._log("INFO", "Pairing successful!")
            else:
                self._log("INFO", "Device already paired")
                with self.lock:
                    self.message = "Device already paired ✓"

            # Trust the device
            logging.info(f"[bt-tether-helper] Trusting device...")
            with self.lock:
                self.message = "Setting device as trusted..."
            self._run_cmd(["bluetoothctl", "trust", mac])

            # Wait longer after pairing/trust for phone to be ready
            logging.info(f"[bt-tether-helper] Waiting for phone to be ready...")
            with self.lock:
                self.message = "Waiting for phone to be ready..."
            time.sleep(5)  # Give phone time after pairing

            # Skip bluetoothctl connect - pairing already establishes connection
            # Go directly to NAP profile connection
            with self.lock:
                self.status = "CONNECTING"
                self.message = "Waiting for Bluetooth connection..."

            # Wait for Bluetooth connection to be established automatically after pairing
            self._log("INFO", "Waiting for Bluetooth connection to establish...")
            connection_established = False
            for check in range(10):
                time.sleep(2)
                status = self._check_pair_status(mac)
                if status["connected"]:
                    connection_established = True
                    self._log("INFO", "✓ Bluetooth connection established!")
                    break
                self._log("INFO", f"Waiting for connection... ({(check+1)*2}s)")

            if not connection_established:
                self._log(
                    "WARNING",
                    "Bluetooth connection did not establish automatically after pairing",
                )
                self._log(
                    "INFO", "This might be normal - will try NAP connection anyway"
                )

            self._log("INFO", "Proceeding to NAP connection...")
            with self.lock:
                self.message = "Connecting to NAP profile for internet..."

            # Additional wait to ensure phone is ready for NAP connection
            self._log(
                "INFO", "Waiting 5 seconds for phone to be ready for tethering..."
            )
            time.sleep(5)

            # Try to establish PAN connection
            self._log("INFO", "Establishing PAN connection...")
            with self.lock:
                self.status = "CONNECTING"
                self.message = "Connecting to NAP profile for internet..."

            # Try DBus connection to NAP profile (with retry for br-connection-busy)
            nap_connected = False
            for retry in range(3):
                if retry > 0:
                    self._log(
                        "info", f"Retrying NAP connection (attempt {retry + 1}/3)..."
                    )
                    with self.lock:
                        self.message = f"NAP retry {retry + 1}/3..."
                    time.sleep(3)  # Wait for previous connection attempt to settle

                nap_connected = self._connect_nap_dbus(mac)
                if nap_connected:
                    break
                else:
                    self._log("WARNING", f"NAP attempt {retry + 1} failed")
                    with self.lock:
                        self.message = f"NAP attempt {retry + 1}/3 failed..."

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
                        self._log(
                            "warning",
                            "Network setup failed, connection may not work",
                        )

                    # Wait a bit for network to stabilize
                    time.sleep(2)

                    # Verify internet connectivity
                    self._log("INFO", "Checking internet connectivity...")
                    with self.lock:
                        self.message = "Verifying internet connection..."

                    if self._check_internet_connectivity():
                        self._log("INFO", "✓ Internet connectivity verified!")
                        self._connectivity_verified.set()  # Signal BLE thread
                        self._invalidate_status_cache()  # Invalidate before clearing flag
                        with self.lock:
                            self.status = "CONNECTED"
                            self.message = f"✓ Connected! Internet via {iface}"
                        # Update device name with new IP if advertise_ip is enabled (after clearing connection flag)
                        if self.advertise_ip and DBUS_AVAILABLE:
                            try:
                                pwn_name = self._get_pwnagotchi_name()
                                current_ip = self._get_current_ip()
                                if current_ip:
                                    self._log(
                                        "INFO",
                                        f"Updating device name to: {pwn_name} | {current_ip}",
                                    )
                                    self._update_device_name(pwn_name, current_ip)
                            except Exception as e:
                                self._log(
                                    "WARNING", f"Failed to update device name: {e}"
                                )
                    else:
                        self._log("WARNING", "No internet connectivity detected")
                        self._invalidate_status_cache()  # Invalidate before clearing flag
                        with self.lock:
                            self.status = "CONNECTED"
                            self.message = (
                                f"Connected via {iface} but no internet access"
                            )
                else:
                    self._log("WARNING", "NAP connected but no interface detected")
                    self._invalidate_status_cache()  # Invalidate before clearing flag
                    with self.lock:
                        self.status = "CONNECTED"
                        self.message = "Connected but no internet. Enable Bluetooth tethering on phone."
            else:
                self._log("WARNING", "NAP connection failed")
                self._invalidate_status_cache()  # Invalidate before clearing flag
                with self.lock:
                    self.status = "CONNECTED"
                    self.message = "Bluetooth connected but tethering failed. Enable tethering on phone."

        except Exception as e:
            self._log("ERROR", f"Connection thread error: {e}")

            self._log("ERROR", f"Traceback: {traceback.format_exc()}")
            self._invalidate_status_cache()  # Invalidate before clearing flag
            with self.lock:
                self.status = "ERROR"
                self.message = f"Connection error: {str(e)}"
                self._connection_in_progress = False
        finally:
            # Clear the flag if not already cleared (error cases)
            # Invalidate cache first to ensure fresh status on next UI update
            self._invalidate_status_cache()
            with self.lock:
                if self._connection_in_progress:
                    self._connection_in_progress = False

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
                timeout=3,  # Short timeout for health check
                text=True,
            )
            return result.returncode == 0
        except:
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
                    timeout=5,  # Reduced timeout for RPi Zero W2
                )
                time.sleep(3)  # Extra time on slow hardware
                self._log("INFO", "Bluetooth service restarted")
                return True
            except Exception as e:
                self._log("ERROR", f"Failed to restart Bluetooth: {e}")
                return False
        return True

    def _run_cmd(self, cmd, capture=False, timeout=10):
        """Run shell command with error handling and deadlock prevention"""
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
                time.sleep(1)
                # Request new lease
                result = subprocess.run(
                    ["sudo", "dhcpcd", "-4", "-n", iface],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=20,
                )
                if result.stdout.strip():
                    self._log("INFO", f"dhcpcd: {result.stdout.strip()}")
                if result.returncode == 0:
                    dhcp_success = True
                else:
                    self._log("WARNING", f"dhcpcd failed: {result.stderr.strip()}")

            elif has_dhclient:
                self._log("INFO", "Using dhclient...")
                # Kill any existing dhclient for this interface
                subprocess.run(
                    ["sudo", "pkill", "-f", f"dhclient.*{iface}"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=3,
                )
                time.sleep(0.5)

                # Request new lease with better error handling
                try:
                    result = subprocess.run(
                        ["sudo", "dhclient", "-4", "-v", iface],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        timeout=30,
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
                    elif combined:
                        # Truncate long output
                        self._log("INFO", f"dhclient: {combined[:200]}")

                    if result.returncode == 0:
                        dhcp_success = True
                    else:
                        self._log("WARNING", f"dhclient returned {result.returncode}")

                except subprocess.TimeoutExpired:
                    self._log("WARNING", "dhclient timed out after 30s")
                    # Kill hung dhclient
                    subprocess.run(
                        ["sudo", "pkill", "-9", "-f", f"dhclient.*{iface}"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=3,
                    )

            else:
                self._log(
                    "ERROR",
                    "No DHCP client found! Install dhclient: sudo apt install isc-dhcp-client",
                )
                return False

            # Check for IP with extended wait time (tethering may take time to fully start)
            ip_addr = None
            max_checks = 8  # Increased from 5 to give more time

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
            return False

    def _is_monitor_mode_active(self):
        """Check if monitor mode (mon0) is currently active"""
        try:
            result = subprocess.run(
                ["ip", "link", "show", "mon0"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=3,
            )
            # If mon0 exists and returncode is 0, monitor mode is active
            return result.returncode == 0 and "mon0" in result.stdout
        except Exception:
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

    def _protect_existing_routes(self, bt_iface):
        """Ensure existing interfaces (usb0, eth0) still have valid routes after DHCP on Bluetooth"""
        try:
            # Check if usb0 exists and should have a route (common for USB gadget mode)
            for iface in ["usb0", "eth0"]:
                try:
                    # Check if interface exists and has IP
                    result = subprocess.run(
                        ["ip", "addr", "show", iface],
                        capture_output=True,
                        text=True,
                        timeout=3,
                    )
                    if result.returncode != 0:
                        continue  # Interface doesn't exist

                    # Check if it has an IP
                    ip_match = re.search(
                        r"inet\s+(\d+\.\d+\.\d+)\.(\d+)", result.stdout
                    )
                    if not ip_match:
                        continue  # No IP assigned

                    subnet = ip_match.group(1)
                    gateway = f"{subnet}.1"

                    # Check if route exists for this interface
                    route_check = subprocess.run(
                        ["ip", "route", "show", "dev", iface],
                        capture_output=True,
                        text=True,
                        timeout=3,
                    )

                    if route_check.returncode == 0 and route_check.stdout.strip():
                        logging.debug(f"[bt-tether-helper] Route for {iface} OK")
                    else:
                        # Route may have been removed by DHCP, restore it
                        logging.warning(
                            f"[bt-tether-helper] Restoring route for {iface}..."
                        )
                        subprocess.run(
                            [
                                "sudo",
                                "ip",
                                "route",
                                "add",
                                f"{subnet}.0/24",
                                "dev",
                                iface,
                            ],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            timeout=3,
                        )
                        # Add default route with higher metric so it doesn't override BT
                        subprocess.run(
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
                                "50",
                            ],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            timeout=3,
                        )
                        logging.info(f"[bt-tether-helper] ✓ Route for {iface} restored")

                except Exception as e:
                    logging.debug(f"[bt-tether-helper] Route check for {iface}: {e}")

        except Exception as e:
            logging.warning(f"[bt-tether-helper] Route protection check failed: {e}")

    def _log_network_config(self, iface):
        """Log current network configuration for debugging - optimized for RPi Zero W2"""
        try:
            # Check IP address
            ip_result = subprocess.run(
                ["ip", "addr", "show", iface],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=5,
            )
            logging.debug(  # Use debug level to reduce log spam on limited storage
                f"[bt-tether-helper] Interface {iface} config:\n{ip_result.stdout}"
            )

            # Check routing table
            route_result = subprocess.run(
                ["ip", "route"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=5,
            )
            logging.debug(f"[bt-tether-helper] Routing table:\n{route_result.stdout}")

            # Check DNS
            try:
                with open("/etc/resolv.conf", "r") as f:
                    dns_config = f.read()
                    logging.debug(f"[bt-tether-helper] DNS config:\n{dns_config}")
            except:
                pass

        except Exception as e:
            logging.error(f"[bt-tether-helper] Failed to log network config: {e}")

    def _setup_routing(self, iface):
        """Setup default route and DNS for internet access"""
        try:
            logging.info(f"[bt-tether-helper] Setting up routing for {iface}...")

            # DHCP is handled by _setup_dhclient, just ensure interface is up
            logging.info(f"[bt-tether-helper] Ensuring {iface} is up for routing...")
            try:
                subprocess.run(
                    ["sudo", "ip", "link", "set", iface, "up"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=5,
                )
            except Exception as e:
                logging.warning(f"[bt-tether-helper] Failed to bring up {iface}: {e}")

            # Wait for IP to be assigned
            time.sleep(2)

            # Get the gateway from the interface
            ip_result = subprocess.run(
                ["ip", "addr", "show", iface],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=5,
            )

            # Extract IP and calculate gateway (usually .1 on the subnet)

            ip_match = re.search(r"inet (\d+\.\d+\.\d+)\.(\d+)/", ip_result.stdout)
            if ip_match:
                subnet = ip_match.group(1)
                my_ip_last = ip_match.group(2)
                gateway = f"{subnet}.1"
                my_ip = f"{subnet}.{my_ip_last}"
                logging.info(
                    f"[bt-tether-helper] ✓ IP assigned: {my_ip}, gateway: {gateway}"
                )

                # Check if default route exists
                route_check = subprocess.run(
                    ["ip", "route", "show", "default"],
                    stdout=subprocess.PIPE,
                    text=True,
                    timeout=5,
                )

                if iface not in route_check.stdout:
                    logging.info(
                        f"[bt-tether-helper] Adding default route via {gateway} on {iface}"
                    )
                    subprocess.run(
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
                            "100",  # Higher metric to avoid overriding local routes (bettercap API protection)
                        ],
                        timeout=5,
                        check=False,
                    )
                else:
                    logging.info(
                        f"[bt-tether-helper] Default route via {iface} already exists"
                    )

            else:
                logging.warning(
                    f"[bt-tether-helper] ⚠️  No IPv4 address assigned to {iface}!"
                )
                logging.warning(
                    f"[bt-tether-helper] ⚠️  Make sure Bluetooth tethering is enabled on your phone"
                )

        except Exception as e:
            logging.error(f"[bt-tether-helper] Routing setup error: {e}")

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
                logging.warning(f"[bt-tether-helper] Ping to 8.8.8.8 failed")
                logging.warning(f"[bt-tether-helper] Ping stderr: {result.stderr}")
                logging.warning(f"[bt-tether-helper] Ping stdout: {result.stdout}")

                # Try to ping the gateway to see if that works
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

    def _get_bluetooth_adapter(self):
        """Get the Bluetooth adapter interface name (e.g., hci0)"""
        try:
            result = self._run_cmd(["hciconfig"], capture=True)
            if result:
                # Parse hciconfig output: "hci0:  Type: Primary  Bus: USB"
                for line in result.split("\n"):
                    if line and not line.startswith(" ") and "hci" in line:
                        adapter = line.split(":")[0].strip()
                        logging.info(
                            f"[bt-tether-helper] Found Bluetooth adapter: {adapter}"
                        )
                        return adapter
            # Fallback: assume hci0
            logging.warning(
                "[bt-tether-helper] Could not detect adapter, using default: hci0"
            )
            return "hci0"
        except Exception as e:
            logging.error(f"[bt-tether-helper] Failed to get Bluetooth adapter: {e}")
            return "hci0"  # Default fallback

    def _check_interface_has_ip(self, iface):
        """Check if network interface has an IP address assigned"""
        try:
            result = subprocess.check_output(
                ["ip", "addr", "show", iface], text=True, timeout=5
            )
            # Look for "inet " followed by an IP address (not 169.254.x.x which is link-local)

            ip_match = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", result)
            if ip_match:
                ip_addr = ip_match.group(1)
                # Exclude link-local addresses (169.254.x.x)
                if not ip_addr.startswith("169.254."):
                    logging.info(
                        f"[bt-tether-helper] Interface {iface} has IP: {ip_addr}"
                    )
                    return True
                else:
                    logging.warning(
                        f"[bt-tether-helper] Interface {iface} has only link-local IP: {ip_addr}"
                    )
                    return False
            else:
                logging.info(f"[bt-tether-helper] No IP address on {iface}")
                return False
        except Exception as e:
            logging.error(f"[bt-tether-helper] Failed to check IP on {iface}: {e}")
            return False

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
        """Pair device - persistent agent will handle the dialog"""
        try:
            logging.info(f"[bt-tether-helper] Starting pairing with {mac}...")

            with self.lock:
                self.message = "Scanning for phone..."

            # First ensure Bluetooth is powered on and in pairable mode
            self._run_cmd(["bluetoothctl", "power", "on"], capture=True)
            time.sleep(1)
            self._run_cmd(["bluetoothctl", "pairable", "on"], capture=True)
            self._run_cmd(["bluetoothctl", "discoverable", "on"], capture=True)
            time.sleep(1)

            # Scan for device first so bluetoothctl knows about it
            logging.info(f"[bt-tether-helper] Scanning for device {mac}...")
            try:
                subprocess.Popen(
                    ["bluetoothctl", "scan", "on"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except:
                pass

            # Wait up to 60 seconds for device to be discovered
            device_found = False
            for i in range(60):
                time.sleep(1)
                devices = self._run_cmd(["bluetoothctl", "devices"], capture=True)
                if devices and devices != "Timeout" and mac.upper() in devices.upper():
                    device_found = True
                    logging.info(f"[bt-tether-helper] ✓ Device {mac} found!")
                    break
                if i % 5 == 0 and i > 0:
                    logging.info(f"[bt-tether-helper] Still scanning... ({i}s)")

            # Stop scan
            try:
                subprocess.Popen(
                    ["bluetoothctl", "scan", "off"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                time.sleep(0.5)
            except:
                pass

            if not device_found:
                logging.error(f"[bt-tether-helper] Device {mac} not found after scan!")
                with self.lock:
                    self.message = "Phone not found. Is Bluetooth ON?"
                return False

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
                                self.status = "PAIRING"
                                self.message = f"🔑 PASSKEY: {self.current_passkey}\n\nVerify this matches on your phone, then tap PAIR!"

                            # Invalidate cache so web UI gets fresh status with passkey
                            self._invalidate_status_cache()
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
                                    self.status = "PAIRING"
                                    self.message = f"🔑 PASSKEY: {self.current_passkey}\n\nVerify this matches on your phone, then tap PAIR!"

                                # Invalidate cache so web UI gets fresh status with passkey
                                self._invalidate_status_cache()

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

    def _start_ble_advertising(self):
        """Start device name update thread"""
        try:
            if self._name_update_thread and self._name_update_thread.is_alive():
                self._log("INFO", "Device name update thread already running")
                return

            self._name_update_stop.clear()
            self._name_update_thread = threading.Thread(
                target=self._name_update_loop, daemon=True
            )
            self._name_update_thread.start()
            self._log("INFO", "Started device name update thread")
        except Exception as e:
            self._log("ERROR", f"Failed to start device name updates: {e}")

    def _stop_ble_advertising(self):
        """Stop the device name update thread"""
        try:
            if self._name_update_thread and self._name_update_thread.is_alive():
                self._log("INFO", "Stopping device name updates...")
                self._name_update_stop.set()
                self._name_update_thread.join(timeout=5)
                self._log("INFO", "Device name updates stopped")
        except Exception as e:
            self._log("ERROR", f"Error stopping device name updates: {e}")

    def _name_update_loop(self):
        """Update device name with IP once after connectivity is verified"""
        try:
            self._log("INFO", "Waiting for internet connectivity to be verified...")
            self._connectivity_verified.wait()  # Block until connectivity is verified

            # Get pwnagotchi name from config
            pwn_name = self._get_pwnagotchi_name()

            # Get current IP address if enabled
            current_ip = self._get_current_ip() if self.advertise_ip else None

            if current_ip:
                self._log("INFO", f"Updating device name with IP: {current_ip}")
                self._update_device_name(pwn_name, current_ip)
                self._log(
                    "INFO", "Device name updated. IP will refresh on reconnection."
                )
            else:
                self._log("WARNING", "No IP found after connectivity verification")

        except Exception as e:
            self._log("ERROR", f"Device name update error: {e}")

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

    def _update_device_name(self, name, ip):
        """Update Bluetooth device alias with current name and optionally IP"""
        try:
            import dbus

            # Create device name - with or without IP based on config
            adv_data = f"{name} | {ip}" if ip else name
            self._log("INFO", f"Updating device name to: {adv_data}")

            # Use D-Bus to set the adapter alias (device name)
            bus = dbus.SystemBus()
            adapter_path = "/org/bluez/hci0"

            try:
                adapter = dbus.Interface(
                    bus.get_object("org.bluez", adapter_path),
                    "org.freedesktop.DBus.Properties",
                )

                # Set the Alias property - this is the device name shown in Bluetooth settings
                # Safe to change even when connected, as pairing is based on MAC address
                adapter.Set("org.bluez.Adapter1", "Alias", dbus.String(adv_data))
                self._log("INFO", f"Successfully updated device name")

            except dbus.exceptions.DBusException as e:
                self._log("ERROR", f"D-Bus error: {e}")
                # Fallback to bluetoothctl
                self._log("INFO", "Trying bluetoothctl as fallback...")
                result = self._run_bluetoothctl_command(f"system-alias '{adv_data}'")
                if result:
                    self._log("INFO", f"bluetoothctl fallback succeeded")

        except ImportError as e:
            self._log("ERROR", f"Missing dependencies: {e}")
            self._log(
                "ERROR",
                "Install with: sudo apt-get install -y python3-dbus",
            )
        except Exception as e:
            self._log("ERROR", f"Failed to update device name: {e}")

            self._log("ERROR", f"Traceback: {traceback.format_exc()}")

    def _run_bluetoothctl_command(self, command):
        """Run a single bluetoothctl command"""
        try:
            process = subprocess.Popen(
                ["bluetoothctl"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            stdout, stderr = process.communicate(input=f"{command}\nexit\n", timeout=5)
            return stdout
        except Exception as e:
            self._log("DEBUG", f"bluetoothctl command failed: {e}")
            return None

    def _connect_nap_dbus(self, mac):
        """Connect to NAP service using DBus directly"""
        try:
            logging.info("[bt-tether-helper] Importing dbus module...")
            import dbus

            logging.info("[bt-tether-helper] dbus module imported successfully")

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
                if (
                    "br-connection-page-timeout" in error_msg
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
