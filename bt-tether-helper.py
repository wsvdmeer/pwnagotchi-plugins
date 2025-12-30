"""
Bluetooth Tether Helper Plugin for Pwnagotchi

Required System Packages:
    sudo apt-get update
    sudo apt-get install -y bluez network-manager

Setup:
1. Install packages: sudo apt-get install -y bluez network-manager
2. Enable services:
   sudo systemctl enable bluetooth && sudo systemctl start bluetooth
   sudo systemctl enable NetworkManager && sudo systemctl start NetworkManager
3. Configure plugin in config.toml with phone MAC address
4. Access web UI at http://<pwnagotchi-ip>:8080/plugins/bt-tether-helper
"""

import subprocess
import threading
import time
import logging
import os
from pwnagotchi.plugins import Plugin
from flask import render_template_string, request, jsonify
import pwnagotchi.ui.fonts as fonts
from pwnagotchi.ui.components import LabeledValue
from pwnagotchi.ui.view import BLACK


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
      <div style="background: #f5f5f5; padding: 12px; border-radius: 4px; margin-bottom: 12px; border: 1px solid #ddd;">
        <div style="color: #666; font-size: 12px; margin-bottom: 4px;">Configured MAC address:</div>
        <div style="font-family: monospace; font-size: 14px; color: #333;">{{ mac if mac else 'Not configured' }}</div>
        <small style="color: #666; display: block; margin-top: 4px;">Set in config.toml: <code style="background: white; padding: 2px 6px; border-radius: 3px;">main.plugins.bt-tether-helper.mac</code></small>
      </div>
      
      <!-- Hidden input for JavaScript to access MAC value -->
      <input type="hidden" id="macInput" value="{{ mac }}" />
      
      <div id="connectActions">
        <button class="success" onclick="quickConnect()" id="quickConnectBtn" style="width: 100%; margin: 0 0 8px 0;">
          ⚡ Connect to Phone
        </button>
        <div id="disconnectSection" style="display: none;">
          <label style="display: flex; align-items: center; gap: 8px; padding: 8px; background: #fff3cd; border-radius: 4px; cursor: pointer; margin-bottom: 8px;">
            <input type="checkbox" id="unpairCheckbox" style="width: auto; margin: 0;" />
            <span style="color: #856404; font-size: 13px;">Also unpair device (requires passkey on next connection)</span>
          </label>
          <button class="danger" onclick="disconnectDevice()" id="disconnectBtn" style="width: 100%; margin: 0 0 12px 0;">
            🔌 Disconnect
          </button>
        </div>
      </div>
      <small style="color: #666; display: block; margin-bottom: 12px;">Click Connect for first-time pairing. Pairing dialog will appear on your phone. Disconnect blocks device to prevent auto-reconnect.</small>
      
      <!-- Pairing Feedback -->
      <div id="pairingFeedback" style="display: none; margin-bottom: 12px;">
        <div id="pairingMessage" class="message-box message-info">
          <div id="pairingText">Ready to pair</div>
        </div>
      </div>
      
      <!-- USB Priority Warning -->
      <div id="usbWarning" style="display: none; margin-bottom: 12px;">
        <div class="message-box message-warning">
          ⚠️ <b>USB Connected</b><br>
          <small>Internet traffic is using USB (higher priority). Bluetooth tethering is standby.</small>
        </div>
      </div>
      
      <!-- Active Route Status -->
      <div id="activeRouteBox" style="display: none; margin-bottom: 12px;">
        <div style="background: #f5f5f5; padding: 10px; border-radius: 4px; border: 1px solid #ddd;">
          <div style="color: #666; font-size: 12px; margin-bottom: 4px;">🚦 Active Internet Route:</div>
          <div id="statusRoute" style="font-weight: bold; font-size: 14px;">Checking...</div>
        </div>
      </div>
      
      <!-- Connection Status -->
      <div style="border-top: 1px solid #ddd; padding-top: 12px;">
        <h4 style="margin: 0 0 8px 0; color: #666; font-size: 14px;">📊 Status</h4>
        <div id="connectionStatus">
          <div class="status-item" id="statusPaired">📱 Paired: <span>Checking...</span></div>
          <div class="status-item" id="statusTrusted">🔐 Trusted: <span>Checking...</span></div>
          <div class="status-item" id="statusConnected">🔵 Connected: <span>Checking...</span></div>
          <div class="status-item" id="statusInternet">🌐 Internet: <span>Checking...</span></div>
          <div class="status-item" id="statusIP" style="display: none;">🔢 IP Address: <span></span></div>
        </div>
        
        <!-- Test Internet Connectivity -->
        <div style="margin-top: 12px;">
          <button onclick="testInternet()" id="testInternetBtn" style="width: 100%; margin: 0;">
            🔍 Test Internet Connectivity
          </button>
        </div>
        
        <!-- Test Results -->
        <div id="testResults" style="display: none; margin-top: 12px;">
          <div id="testResultsMessage" class="message-box message-info"></div>
        </div>
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

      // Update card visibility and status on page load
      updateCardVisibility();
      if (macInput.value && /^([0-9A-F]{2}:){5}[0-9A-F]{2}$/i.test(macInput.value)) {
        checkConnectionStatus();
      }
      
      function updateCardVisibility() {
        const hasMac = macInput.value && /^([0-9A-F]{2}:){5}[0-9A-F]{2}$/i.test(macInput.value);
        // Always show scan card, just toggle which instructions to show
        const setupInstructions = document.getElementById('setupInstructions');
        if (setupInstructions) {
          setupInstructions.style.display = hasMac ? 'none' : 'block';
        }
        document.getElementById('phoneConnectionCard').style.display = hasMac ? 'block' : 'none';
      }

      async function checkConnectionStatus() {
        const mac = macInput.value.trim();
        if (!/^([0-9A-F]{2}:){5}[0-9A-F]{2}$/i.test(mac)) return;
        
        try {
          // First check the plugin's internal status
          const statusResponse = await fetch(`/plugins/bt-tether-helper/status`);
          const statusData = await statusResponse.json();
          
          // Show connecting indicator if pairing or connecting
          if (statusData.status === 'PAIRING' || statusData.status === 'CONNECTING') {
            showFeedback(`<span class="spinner"></span> ${statusData.message}`, "info");
            
            // Disable quick connect button during connection
            const connectBtn = document.getElementById('quickConnectBtn');
            connectBtn.disabled = true;
            connectBtn.innerHTML = '<span class="spinner"></span> Connecting...';
          }
          
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
            `📱 <b style="color: ${data.paired ? '#28a745' : '#6c757d'};">[P]</b> Paired: <b style="color: ${data.paired ? '#28a745' : '#dc3545'};">${data.paired ? '✓ Yes' : '✗ No'}</b>`;
          document.getElementById("statusPaired").className = data.paired ? 'status-item status-good' : 'status-item status-bad';
          
          document.getElementById("statusTrusted").innerHTML = 
            `🔐 <b style="color: ${data.trusted ? '#28a745' : '#6c757d'};">[T]</b> Trusted: <b style="color: ${data.trusted ? '#28a745' : '#dc3545'};">${data.trusted ? '✓ Yes' : '✗ No'}</b>`;
          document.getElementById("statusTrusted").className = data.trusted ? 'status-item status-good' : 'status-item status-bad';
          
          document.getElementById("statusConnected").innerHTML = 
            `🔵 <b style="color: ${data.connected ? '#28a745' : '#6c757d'};">[C]</b> Connected: <b style="color: ${data.connected ? '#28a745' : '#dc3545'};">${data.connected ? '✓ Yes' : '✗ No'}</b>`;
          document.getElementById("statusConnected").className = data.connected ? 'status-item status-good' : 'status-item status-bad';
          
          document.getElementById("statusInternet").innerHTML = 
            `🌐 <b style="color: ${data.pan_active ? '#28a745' : '#6c757d'};">[I]</b> Internet: <b style="color: ${data.pan_active ? '#28a745' : '#dc3545'};">${data.pan_active ? '✓ Active' : '✗ Not Active'}</b>${data.interface ? ` (${data.interface})` : ''}`;
          document.getElementById("statusInternet").className = data.pan_active ? 'status-item status-good' : 'status-item status-bad';
          
          // Show IP address if available
          const statusIPElement = document.getElementById('statusIP');
          if (data.ip_address && data.pan_active) {
            statusIPElement.style.display = 'block';
            statusIPElement.innerHTML = `🔢 IP Address: <b style="color: #28a745;">${data.ip_address}</b>`;
            statusIPElement.className = 'status-item status-good';
          } else {
            statusIPElement.style.display = 'none';
          }
          
          // Show active route and USB warning
          const statusRoute = document.getElementById('statusRoute');
          const activeRouteBox = document.getElementById('activeRouteBox');
          const usbWarning = document.getElementById('usbWarning');
          
          if (data.default_route_interface) {
            activeRouteBox.style.display = 'block';
            const isUsingBluetooth = data.default_route_interface === data.interface;
            const routeColor = isUsingBluetooth ? '#28a745' : '#856404';
            statusRoute.innerHTML = `<b style="color: ${routeColor};">${data.default_route_interface}</b>`;
            statusRoute.style.color = routeColor;
            
            // Show USB warning if BT is connected but USB has priority
            if (data.pan_active && data.default_route_interface !== data.interface && data.default_route_interface.startsWith('usb')) {
              usbWarning.style.display = 'block';
            } else {
              usbWarning.style.display = 'none';
            }
          } else {
            activeRouteBox.style.display = 'none';
            usbWarning.style.display = 'none';
          }
          
          // Show/hide connect/disconnect buttons based on connection status
          const connectBtn = document.getElementById('quickConnectBtn');
          const disconnectSection = document.getElementById('disconnectSection');
          
          // Re-enable connect button if not currently connecting
          if (statusData.status !== 'PAIRING' && statusData.status !== 'CONNECTING') {
            connectBtn.disabled = false;
            connectBtn.innerHTML = '⚡ Connect to Phone';
          }
          
          if (data.connected) {
            connectBtn.style.display = 'none';
            disconnectSection.style.display = 'block';
          } else {
            connectBtn.style.display = 'block';
            disconnectSection.style.display = 'none';
          }
          
          // Display passkey prominently if available (only during pairing)
          if (data.passkey && !data.paired) {
            showFeedback(
              'PASSKEY: ' + data.passkey + '\\n\\nVerify this matches on your phone, then tap PAIR!',
              "warning"
            );
          } else if (data.paired && data.connected) {
            // Hide passkey message once fully connected
            const pairingFeedback = document.getElementById('pairingFeedback');
            const pairingText = document.getElementById('pairingText');
            if (pairingText.innerHTML.includes('PASSKEY:')) {
              pairingFeedback.style.display = 'none';
            }
            
            // Hide status feedback when PAN is active (fully connected)
            if (data.pan_active) {
              pairingFeedback.style.display = 'none';
              console.log('Fully connected - stopping status polling');
              stopStatusPolling();
            }
          }
          
          // Uncheck unpair checkbox when disconnected
          if (!data.connected) {
            const unpairCheckbox = document.getElementById('unpairCheckbox');
            if (unpairCheckbox) {
              unpairCheckbox.checked = false;
            }
          }
          
        } catch (error) {
          console.error('Status check failed:', error);
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
            // If unpair checkbox is checked, also unpair
            if (shouldUnpair) {
              const unpairResponse = await fetch(`/plugins/bt-tether-helper/unpair?mac=${encodeURIComponent(mac)}`, { method: 'GET' });
              const unpairData = await unpairResponse.json();
              if (unpairData.success) {
                showFeedback("Device disconnected and unpaired. Passkey required for next connection.", "success");
              } else {
                showFeedback("Disconnected but unpair failed: " + unpairData.message, "warning");
              }
            } else {
              showFeedback("Device disconnected and blocked. Phone will see connection drop automatically.", "success");
            }
            stopStatusPolling();
            checkConnectionStatus();
            // Restart polling after disconnect to update status
            startStatusPolling();
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
        const pairingFeedback = document.getElementById('pairingFeedback');
        const pairingMessage = document.getElementById('pairingMessage');
        const pairingText = document.getElementById('pairingText');
        
        pairingFeedback.style.display = 'block';
        pairingMessage.className = 'message-box message-' + type;
        
        // For passkey messages, make them stand out with larger font
        if (message.includes('PASSKEY:')) {
          pairingText.innerHTML = message.replace(/PASSKEY: (\d{6})/, 
            '<b style="font-size: 24px; display: block; margin: 10px 0;">🔑 PASSKEY: $1</b>');
        } else if (message.includes('<span class="spinner">')) {
          // Allow HTML for spinner and other HTML elements
          pairingText.innerHTML = message;
        } else {
          pairingText.textContent = message;
        }
        
        // Auto-hide success messages after 5 seconds
        if (type === 'success') {
          setTimeout(() => {
            if (pairingText.textContent === message || pairingText.innerHTML.includes(message)) {
              pairingFeedback.style.display = 'none';
            }
          }, 5000);
        }
      }
    </script>
  </body>
</html>
"""


class BTTetherHelper(Plugin):
    __author__ = "wsvdmeer"
    __version__ = "0.9.0-beta"
    __license__ = "GPL3"
    __description__ = "Guided Bluetooth tethering with user instructions"

    def on_loaded(self):
        self.phone_mac = self.options.get("mac", "")
        self._status = "IDLE"
        self._message = "Ready"
        self.lock = threading.Lock()
        self.options["csrf_exempt"] = True  # Disable CSRF for this plugin
        self.agent_process = None  # Track agent process
        self.agent_log_fd = None  # File descriptor for agent log
        self.agent_log_path = None  # Path to agent log file
        self.current_passkey = None  # Store passkey for display in UI
        self.ui_position = self.options.get(
            "position", None
        )  # Screen position for status (None = auto top-right)
        self.show_on_screen = self.options.get(
            "show_on_screen", True
        )  # Enable/disable screen display

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
        self._status_cache_ttl = 15  # Cache status for 15s (RPi Zero W2 optimization)

        # Lock to prevent multiple bluetoothctl commands from running simultaneously
        self._bluetoothctl_lock = threading.Lock()

        # Flag to indicate when connection/pairing is in progress
        self._connection_in_progress = False

        # Monitoring thread for automatic reconnection
        self._monitor_thread = None
        self._monitor_stop = threading.Event()
        self._last_known_connected = False  # Track if we were previously connected

        # Agent tracking for persistent pairing agent
        self.agent_process = None  # Track agent process
        self.agent_log_fd = None  # File descriptor for agent log
        self.agent_log_path = None  # Path to agent log file
        self.current_passkey = None  # Store passkey for display in UI

        # Kill any lingering bluetoothctl processes to prevent deadlocks
        try:
            subprocess.run(
                ["pkill", "-9", "bluetoothctl"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            logging.info(
                "[bt-tether-helper] Cleaned up lingering bluetoothctl processes"
            )
        except:
            pass

        # Restart bluetooth service to ensure clean state
        try:
            logging.info("[bt-tether-helper] Restarting Bluetooth service...")
            subprocess.run(
                ["systemctl", "restart", "bluetooth"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,  # Reduced timeout for RPi Zero W2
            )
            time.sleep(3)  # Give service extra time to start on slow hardware
            logging.info("[bt-tether-helper] Bluetooth service restarted")
        except Exception as e:
            logging.warning(
                f"[bt-tether-helper] Failed to restart Bluetooth service: {e}"
            )

        # Verify localhost routing is intact (critical for bettercap API)
        try:
            self._verify_localhost_route()
        except Exception as e:
            logging.warning(f"[bt-tether-helper] Initial localhost check failed: {e}")

        # Start persistent pairing agent in background
        self._start_pairing_agent()

        # Start connection monitoring thread if auto-reconnect is enabled
        if self.auto_reconnect and self.phone_mac:
            self._start_monitoring_thread()

        logging.info("[bt-tether-helper] Loaded")

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

    def on_ui_update(self, ui):
        """Update Bluetooth status on screen"""
        if not self.show_on_screen or not self.phone_mac:
            return

        try:
            # Show connecting indicator when connection is in progress
            # > = Connecting/Pairing in progress
            if self._connection_in_progress:
                ui.set("bt-status", ">")
                return

            # Get current connection status
            status = self._get_full_connection_status(self.phone_mac)

            # Determine display value based on status
            # C = Connected (internet), N = No internet, P = Paired, D = Disconnected
            if status.get("pan_active", False):
                display = "C"  # Connected with internet
            elif status.get("connected", False):
                display = "N"  # Connected but no internet
            elif status.get("paired", False):
                display = "P"  # Paired but not connected
            else:
                display = "D"  # Disconnected

            ui.set("bt-status", display)
        except Exception as e:
            # Log error but don't crash
            logging.debug(f"[bt-tether-helper] UI update error: {e}")
            # Set to unknown state if error occurs
            try:
                ui.set("bt-status", "?")
            except:
                pass

    def _start_pairing_agent(self):
        """Start a persistent bluetoothctl agent to handle pairing requests"""
        try:
            if self.agent_process and self.agent_process.poll() is None:
                logging.info("[bt-tether-helper] Pairing agent already running")
                return

            logging.info("[bt-tether-helper] Starting persistent pairing agent...")

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
            self.agent_process.stdin.close()  # Close stdin after sending (prevent stdin deadlock)

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
                logging.info("[bt-tether-helper] Monitoring thread already running")
                return

            self._monitor_stop.clear()
            self._monitor_thread = threading.Thread(
                target=self._connection_monitor_loop, daemon=True
            )
            self._monitor_thread.start()
            logging.info(
                f"[bt-tether-helper] Started connection monitoring (interval: {self.reconnect_interval}s)"
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

        # Wait a bit before starting to monitor to let initial connection settle
        time.sleep(30)

        while not self._monitor_stop.is_set():
            try:
                # Skip monitoring if connection/pairing is already in progress
                if self._connection_in_progress:
                    time.sleep(self.reconnect_interval)
                    continue

                # Check current connection status
                status = self._get_full_connection_status(self.phone_mac)

                # Detect if connection was dropped (was connected, now not)
                if self._last_known_connected and not status["connected"]:
                    logging.warning(
                        "[bt-tether-helper] Connection dropped! Attempting to reconnect..."
                    )
                    with self.lock:
                        self.status = "RECONNECTING"
                        self.message = "Connection lost, reconnecting..."

                    # Attempt to reconnect
                    self._reconnect_device()

                # Update last known state
                self._last_known_connected = status["connected"]

                # If paired but not connected, try to reconnect (device may have been disconnected manually)
                if (
                    status["paired"]
                    and status["trusted"]
                    and not status["connected"]
                    and not self._last_known_connected
                ):
                    logging.info(
                        "[bt-tether-helper] Device is paired/trusted but not connected. Attempting connection..."
                    )
                    with self.lock:
                        self.status = "CONNECTING"
                        self.message = "Reconnecting to device..."

                    self._reconnect_device()

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
                logging.error(
                    "[bt-tether-helper] No MAC address configured for reconnection"
                )
                return

            # Set flag to prevent concurrent operations
            self._connection_in_progress = True
            self._invalidate_status_cache()

            logging.info(f"[bt-tether-helper] Reconnecting to {mac}...")

            # Check if device is blocked
            devices_output = self._run_cmd(
                ["bluetoothctl", "devices", "Blocked"], capture=True, timeout=5
            )
            if devices_output and devices_output != "Timeout" and mac in devices_output:
                logging.info(f"[bt-tether-helper] Unblocking device {mac}...")
                self._run_cmd(["bluetoothctl", "unblock", mac], capture=True)
                time.sleep(1)

            # Trust the device
            logging.info(f"[bt-tether-helper] Ensuring device is trusted...")
            self._run_cmd(["bluetoothctl", "trust", mac], capture=True)
            time.sleep(1)

            # Try NAP connection (this will also establish Bluetooth connection if needed)
            logging.info(f"[bt-tether-helper] Attempting NAP connection...")
            nap_connected = self._connect_nap_dbus(mac)

            if nap_connected:
                logging.info(f"[bt-tether-helper] ✓ Reconnection successful")

                # Wait for PAN interface
                time.sleep(2)

                # Check if PAN interface is up
                if self._pan_active():
                    iface = self._get_pan_interface()
                    logging.info(f"[bt-tether-helper] ✓ PAN interface active: {iface}")

                    # Setup NetworkManager connection
                    if self._setup_network_manager(mac, iface):
                        logging.info(
                            f"[bt-tether-helper] ✓ NetworkManager setup successful"
                        )

                    # Verify internet connectivity
                    time.sleep(2)
                    if self._check_internet_connectivity():
                        logging.info(
                            f"[bt-tether-helper] ✓ Internet connectivity verified!"
                        )
                        with self.lock:
                            self.status = "CONNECTED"
                            self.message = f"✓ Reconnected! Internet via {iface}"
                    else:
                        logging.warning(
                            f"[bt-tether-helper] Reconnected but no internet detected"
                        )
                        with self.lock:
                            self.status = "CONNECTED"
                            self.message = f"Reconnected via {iface} but no internet"
                else:
                    logging.warning(
                        f"[bt-tether-helper] NAP connected but no interface detected"
                    )
                    with self.lock:
                        self.status = "CONNECTED"
                        self.message = "Reconnected but no PAN interface"
            else:
                logging.warning(f"[bt-tether-helper] Reconnection failed")
                with self.lock:
                    self.status = "ERROR"
                    self.message = "Reconnection failed. Will retry later."

        except Exception as e:
            logging.error(f"[bt-tether-helper] Reconnection error: {e}")
            with self.lock:
                self.status = "ERROR"
                self.message = f"Reconnection error: {str(e)[:50]}"
        finally:
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
                                import re

                                passkey_match = re.search(
                                    r"passkey\s+(\d{6})", clean_line, re.IGNORECASE
                                )
                                if passkey_match:
                                    self.current_passkey = passkey_match.group(1)
                                    logging.warning(
                                        f"[bt-tether-helper] 🔑 PASSKEY: {self.current_passkey} - Confirm on phone!"
                                    )

                                    # Auto-confirm passkey on Pwnagotchi side
                                    if (
                                        self.agent_process
                                        and self.agent_process.poll() is None
                                    ):
                                        try:
                                            logging.info(
                                                "[bt-tether-helper] ✅ Auto-confirming on Pwnagotchi & waiting for phone..."
                                            )
                                            if self.agent_process.stdin and not self.agent_process.stdin.closed:
                                                self.agent_process.stdin.write(b"yes\n")
                                                self.agent_process.stdin.flush()
                                        except Exception as confirm_err:
                                            logging.error(
                                                f"[bt-tether-helper] Failed to auto-confirm: {confirm_err}"
                                            )

                                passkey_found_event.set()
                            elif "request confirmation" in clean_line.lower():
                                logging.info(f"[bt-tether-helper] 📱 {clean_line}")
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
                        time.sleep(0.1)

            logging.info("[bt-tether-helper] Agent log monitoring timeout (90s)")
        except Exception as e:
            logging.error(f"[bt-tether-helper] Error monitoring agent log: {e}")

    def _strip_ansi_codes(self, text):
        """Remove ANSI color/control codes from text"""
        if not text:
            return text
        import re

        # Remove ANSI escape sequences
        ansi_escape = re.compile(r"\x1b\[[0-9;]*[mGKHF]|\x01|\x02")
        return ansi_escape.sub("", text)

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

            return "Not Found", 404
        except Exception as e:
            logging.error(f"[bt-tether-helper] Webhook error: {e}")
            return "Error", 500

    def _validate_mac(self, mac):
        """Validate MAC address format"""
        import re

        return bool(re.match(r"^([0-9A-F]{2}:){5}[0-9A-F]{2}$", mac))

    def _disconnect_device(self, mac):
        """Disconnect from a Bluetooth device and remove trust to prevent auto-reconnect"""
        try:
            # Invalidate status cache to get fresh status after disconnect
            self._invalidate_status_cache()

            logging.info(f"[bt-tether-helper] Disconnecting from device {mac}...")

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
                        logging.info(f"[bt-tether-helper] Disconnecting NAP profile...")
                        device.DisconnectProfile(NAP_UUID)
                        time.sleep(1)
                        logging.info(f"[bt-tether-helper] NAP profile disconnected")
                    except Exception as e:
                        logging.debug(f"[bt-tether-helper] NAP disconnect: {e}")
            except Exception as e:
                logging.debug(f"[bt-tether-helper] DBus operation: {e}")

            # Disconnect the Bluetooth connection
            logging.info(f"[bt-tether-helper] Disconnecting Bluetooth...")
            result = self._run_cmd(["bluetoothctl", "disconnect", mac], capture=True)
            logging.info(f"[bt-tether-helper] Disconnect result: {result}")
            time.sleep(2)

            # Remove trust to prevent automatic reconnection
            logging.info(
                f"[bt-tether-helper] Removing trust to prevent auto-reconnect..."
            )
            trust_result = self._run_cmd(["bluetoothctl", "untrust", mac], capture=True)
            logging.info(f"[bt-tether-helper] Untrust result: {trust_result}")
            time.sleep(1)

            # Unpair (remove) the device completely
            logging.info(f"[bt-tether-helper] Removing device to unpair...")
            remove_result = self._run_cmd(["bluetoothctl", "remove", mac], capture=True)
            logging.info(f"[bt-tether-helper] Remove result: {remove_result}")
            time.sleep(1)

            # Block the device to prevent reconnection attempts
            logging.info(
                f"[bt-tether-helper] Blocking device to prevent reconnection..."
            )
            block_result = self._run_cmd(["bluetoothctl", "block", mac], capture=True)
            logging.info(f"[bt-tether-helper] Block result: {block_result}")
            time.sleep(1)

            logging.info(
                f"[bt-tether-helper] Device {mac} disconnected, unpaired, and blocked successfully"
            )

            # Return success
            final_status = {"connected": False, "paired": False}
            logging.info(
                f"[bt-tether-helper] Final status - Connected: {final_status['connected']}, Paired: {final_status['paired']}"
            )

            return {
                "success": True,
                "message": f"Device {mac} disconnected, unpaired, and blocked",
            }
        except Exception as e:
            logging.error(f"[bt-tether-helper] Disconnect error: {e}")
            return {"success": False, "message": f"Disconnect failed: {str(e)}"}

    def _unpair_device(self, mac):
        """Unpair a Bluetooth device"""
        try:
            logging.info(f"[bt-tether-helper] Unpairing device {mac}...")
            result = self._run_cmd(["bluetoothctl", "remove", mac], capture=True)
            if result and "Device has been removed" in result:
                logging.info(f"[bt-tether-helper] Device {mac} unpaired successfully")
                return {
                    "success": True,
                    "message": f"Device {mac} unpaired successfully",
                }
            elif result and "not available" in result:
                return {"success": True, "message": f"Device {mac} was not paired"}
            else:
                logging.warning(f"[bt-tether-helper] Unpair result: {result}")
                return {"success": True, "message": f"Unpair command sent: {result}"}
        except Exception as e:
            logging.error(f"[bt-tether-helper] Unpair error: {e}")
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
            logging.error(f"[bt-tether-helper] Pair status check error: {e}")
            return {"paired": False, "connected": False}

    def _invalidate_status_cache(self):
        """Invalidate the status cache to force fresh status check"""
        self._status_cache = None
        self._status_cache_time = 0

    def _get_full_connection_status(self, mac):
        """Get complete connection status including trusted and PAN interface (with caching)"""
        try:
            # If connection/pairing is in progress, return cached status to avoid blocking
            if self._connection_in_progress:
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
                "passkey": self.current_passkey,
                "default_route_interface": default_route_interface,
            }

            # Cache the result
            self._status_cache = status
            self._status_cache_time = current_time
            return status

        except Exception as e:
            logging.error(f"[bt-tether-helper] Connection status check error: {e}")
            status = {
                "paired": False,
                "trusted": False,
                "connected": False,
                "pan_active": False,
                "interface": None,
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
            logging.info("[bt-tether-helper] Starting scan...")
            # Use subprocess directly to prevent [CHG] messages in logs
            try:
                subprocess.Popen(
                    ["bluetoothctl", "scan", "on"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except:
                pass

            # Scan for 30 seconds
            time.sleep(30)

            # Get devices
            devices_output = self._run_cmd(["bluetoothctl", "devices"], capture=True)

            # Stop scanning
            try:
                subprocess.Popen(
                    ["bluetoothctl", "scan", "off"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                time.sleep(0.5)
            except:
                pass

            devices = []
            if devices_output:
                for line in devices_output.split("\n"):
                    if line.strip() and line.startswith("Device"):
                        parts = line.strip().split(" ", 2)
                        if len(parts) >= 2:
                            mac = parts[1]
                            name = parts[2] if len(parts) > 2 else "Unknown Device"
                            devices.append({"mac": mac, "name": name})
                            logging.info(
                                f"[bt-tether-helper] Scan found: {name} ({mac})"
                            )

            logging.info(
                f"[bt-tether-helper] Scan complete. Found {len(devices)} devices"
            )
            return devices

        except Exception as e:
            logging.error(f"[bt-tether-helper] Scan error: {e}")
            return []

    def start_connection(self):
        with self.lock:
            if not self.phone_mac:
                self.status = "ERROR"
                self.message = "No MAC address set"
                return

            if self.status in ["PAIRING", "CONNECTING"]:
                self.message = "Connection already in progress"
                return

        # Invalidate status cache to get fresh status during connection
        self._invalidate_status_cache()
        self._connection_in_progress = True
        threading.Thread(target=self._connect_thread, daemon=True).start()

    def _connect_thread(self):
        """Full automatic connection thread with pairing and connection logic"""
        try:
            mac = self.phone_mac
            logging.info(f"[bt-tether-helper] Starting connection to {mac}...")

            # Check if Bluetooth is responsive, restart if needed
            if not self._restart_bluetooth_if_needed():
                logging.error(
                    "[bt-tether-helper] Bluetooth service is unresponsive and couldn't be restarted"
                )
                with self.lock:
                    self.status = "ERROR"
                    self.message = "Bluetooth service unresponsive. Try: sudo systemctl restart bluetooth"
                return

            # Make Pwnagotchi discoverable and pairable
            logging.info(f"[bt-tether-helper] Making Pwnagotchi discoverable...")
            with self.lock:
                self.message = "Making Pwnagotchi discoverable..."
            self._run_cmd(["bluetoothctl", "discoverable", "on"], capture=True)
            self._run_cmd(["bluetoothctl", "pairable", "on"], capture=True)
            time.sleep(2)

            # Remove device completely to ensure fresh pairing
            logging.info(f"[bt-tether-helper] Removing device for fresh pairing...")
            with self.lock:
                self.message = "Removing old pairing..."
            self._run_cmd(["bluetoothctl", "remove", mac], capture=True)
            time.sleep(1)

            logging.info(
                f"[bt-tether-helper] Unblocking device in case it was blocked..."
            )
            with self.lock:
                self.message = "Unblocking device..."
            self._run_cmd(["bluetoothctl", "unblock", mac], capture=True)
            time.sleep(1)

            # Check if already paired
            with self.lock:
                self.message = "Checking pairing status..."
            pair_status = self._check_pair_status(mac)

            if not pair_status["paired"]:
                logging.info(
                    f"[bt-tether-helper] Device not paired. Starting pairing process..."
                )
                with self.lock:
                    self.status = "PAIRING"
                    self.message = "Device not paired. Starting pairing process..."

                # Attempt pairing - this will show dialog on phone
                if not self._pair_device_interactive(mac):
                    logging.error(f"[bt-tether-helper] Pairing failed!")
                    with self.lock:
                        self.status = "ERROR"
                        self.message = (
                            "Pairing failed. Did you accept the dialog on your phone?"
                        )
                    return

                logging.info(f"[bt-tether-helper] Pairing successful!")
            else:
                logging.info(f"[bt-tether-helper] Device already paired")
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
            logging.info(
                f"[bt-tether-helper] Waiting for Bluetooth connection to establish..."
            )
            connection_established = False
            for check in range(10):
                time.sleep(2)
                status = self._check_pair_status(mac)
                if status["connected"]:
                    connection_established = True
                    logging.info(
                        f"[bt-tether-helper] ✓ Bluetooth connection established!"
                    )
                    break
                logging.info(
                    f"[bt-tether-helper] Waiting for connection... ({(check+1)*2}s)"
                )

            if not connection_established:
                logging.warning(
                    f"[bt-tether-helper] Bluetooth connection did not establish automatically after pairing"
                )
                logging.info(
                    f"[bt-tether-helper] This might be normal - will try NAP connection anyway"
                )

            logging.info(f"[bt-tether-helper] Proceeding to NAP connection...")
            with self.lock:
                self.message = "Connecting to NAP profile for internet..."

            # Additional wait to ensure phone is ready for NAP connection
            logging.info(
                f"[bt-tether-helper] Waiting 5 seconds for phone to be ready for tethering..."
            )
            time.sleep(5)

            # Try to establish PAN connection
            logging.info(f"[bt-tether-helper] Establishing PAN connection...")
            with self.lock:
                self.status = "CONNECTING"
                self.message = "Connecting to NAP profile for internet..."

            # Try DBus connection to NAP profile (with retry for br-connection-busy)
            nap_connected = False
            for retry in range(3):
                if retry > 0:
                    logging.info(
                        f"[bt-tether-helper] Retrying NAP connection (attempt {retry + 1}/3)..."
                    )
                    with self.lock:
                        self.message = f"NAP retry {retry + 1}/3..."
                    time.sleep(3)  # Wait for previous connection attempt to settle

                nap_connected = self._connect_nap_dbus(mac)
                if nap_connected:
                    break
                else:
                    logging.warning(
                        f"[bt-tether-helper] NAP attempt {retry + 1} failed"
                    )
                    with self.lock:
                        self.message = f"NAP attempt {retry + 1}/3 failed..."

            if nap_connected:
                logging.info(f"[bt-tether-helper] NAP connection successful!")

                # Check if PAN interface is up
                if self._pan_active():
                    iface = self._get_pan_interface()
                    logging.info(f"[bt-tether-helper] ✓ PAN interface active: {iface}")

                    # Wait for interface initialization
                    logging.info(
                        f"[bt-tether-helper] Waiting for interface initialization..."
                    )
                    time.sleep(2)

                    # Setup NetworkManager connection
                    if self._setup_network_manager(mac, iface):
                        logging.info(
                            f"[bt-tether-helper] ✓ NetworkManager setup successful"
                        )
                    else:
                        logging.warning(
                            f"[bt-tether-helper] NetworkManager setup failed, connection may not work"
                        )

                    # Wait a bit for network to stabilize
                    time.sleep(2)

                    # Verify internet connectivity
                    logging.info(
                        f"[bt-tether-helper] Checking internet connectivity..."
                    )
                    with self.lock:
                        self.message = "Verifying internet connection..."

                    if self._check_internet_connectivity():
                        logging.info(
                            f"[bt-tether-helper] ✓ Internet connectivity verified!"
                        )
                        with self.lock:
                            self.status = "CONNECTED"
                            self.message = f"✓ Connected! Internet via {iface}"
                            self._connection_in_progress = False
                        self._invalidate_status_cache()
                    else:
                        logging.warning(
                            f"[bt-tether-helper] No internet connectivity detected"
                        )
                        with self.lock:
                            self.status = "CONNECTED"
                            self.message = (
                                f"Connected via {iface} but no internet access"
                            )
                            self._connection_in_progress = False
                        self._invalidate_status_cache()
                else:
                    logging.warning(
                        f"[bt-tether-helper] NAP connected but no interface detected"
                    )
                    with self.lock:
                        self.status = "CONNECTED"
                        self.message = "Connected but no internet. Enable Bluetooth tethering on phone."
                        self._connection_in_progress = False
                    self._invalidate_status_cache()
            else:
                logging.warning(f"[bt-tether-helper] NAP connection failed")
                with self.lock:
                    self.status = "CONNECTED"
                    self.message = "Bluetooth connected but tethering failed. Enable tethering on phone."
                    self._connection_in_progress = False
                self._invalidate_status_cache()

        except Exception as e:
            logging.error(f"[bt-tether-helper] Connection thread error: {e}")
            import traceback

            logging.error(f"[bt-tether-helper] Traceback: {traceback.format_exc()}")
            with self.lock:
                self.status = "ERROR"
                self.message = f"Connection error: {str(e)}"
                self._connection_in_progress = False
            self._invalidate_status_cache()
        finally:
            # Clear the flag if not already cleared (error cases)
            with self.lock:
                if self._connection_in_progress:
                    self._connection_in_progress = False
            self._invalidate_status_cache()  # Force fresh status after connection

    def _strip_ansi_codes(self, text):
        """Remove ANSI color/control codes from text"""
        if not text:
            return text
        import re

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
                logging.info("[bt-tether-helper] Bluetooth service restarted")
                return True
            except Exception as e:
                logging.error(f"[bt-tether-helper] Failed to restart Bluetooth: {e}")
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
                        time.sleep(0.2)  # Brief pause to let process die
                    except:
                        pass
                return "Timeout"
            except Exception as e:
                logging.error(f"[bt-tether-helper] Command failed: {' '.join(cmd)}")
                logging.error(f"[bt-tether-helper] Exception: {e}")
                return f"Error: {e}"

    def _setup_network_manager(self, mac, iface):
        """Setup NetworkManager connection for existing bnep0 interface"""
        try:
            conn_name = f"BT-Tether-{mac.replace(':', '')}"
            logging.info(f"[bt-tether-helper] Setting up NetworkManager for {iface}...")

            # Delete ALL existing connections for this interface to avoid conflicts
            logging.info(f"[bt-tether-helper] Cleaning up old connections for {iface}...")
            
            # First, delete connection by name if it exists
            subprocess.run(
                ["sudo", "nmcli", "connection", "delete", conn_name],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=5,
            )
            
            # Get all connections on this interface and delete them
            result = subprocess.run(
                ["nmcli", "-t", "-f", "NAME,DEVICE", "connection", "show", "--active"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=5,
            )
            
            if result.returncode == 0:
                for line in result.stdout.strip().split('\n'):
                    if line and ':' in line:
                        parts = line.split(':')
                        if len(parts) >= 2 and parts[1] == iface:
                            old_conn = parts[0]
                            logging.info(f"[bt-tether-helper] Removing old connection '{old_conn}' from {iface}")
                            subprocess.run(
                                ["sudo", "nmcli", "connection", "delete", old_conn],
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                timeout=5,
                            )
            
            # Also check for any BT-Tether connections regardless of interface
            result = subprocess.run(
                ["nmcli", "-t", "-f", "NAME", "connection", "show"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=5,
            )
            
            if result.returncode == 0:
                for line in result.stdout.strip().split('\n'):
                    if line and 'BT-Tether' in line:
                        logging.info(f"[bt-tether-helper] Removing old BT-Tether connection '{line}'")
                        subprocess.run(
                            ["sudo", "nmcli", "connection", "delete", line],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            timeout=5,
                        )

            # Create ethernet connection on the existing bnep0 interface
            # Note: Using 'ethernet' type with explicit interface name binding
            logging.info(f"[bt-tether-helper] Creating connection profile...")
            result = subprocess.run(
                [
                    "sudo",
                    "nmcli",
                    "connection",
                    "add",
                    "type",
                    "ethernet",
                    "con-name",
                    conn_name,
                    "ifname",
                    iface,
                    "autoconnect",
                    "no",
                    "connection.interface-name",
                    iface,  # Explicitly set interface name
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10,
            )

            if result.returncode != 0:
                logging.error(
                    f"[bt-tether-helper] Failed to create connection: {result.stderr}"
                )
                return False

            # Configure for DHCP with safeguards to avoid interfering with local services
            logging.info(f"[bt-tether-helper] Configuring DHCP settings...")
            subprocess.run(
                [
                    "sudo",
                    "nmcli",
                    "connection",
                    "modify",
                    conn_name,
                    "ipv4.method",
                    "auto",
                    "ipv4.dns",
                    "8.8.8.8 1.1.1.1",
                    "ipv4.ignore-auto-dns",
                    "yes",
                    "ipv4.route-metric",
                    "100",  # Higher metric to avoid overriding local routes (bettercap API protection)
                    "ipv4.never-default",
                    "no",  # Allow as default route but with high metric
                    "connection.autoconnect-slaves",
                    "no",  # Don't interfere with other interfaces
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=10,
                check=True,
            )

            # Activate the connection
            logging.info(f"[bt-tether-helper] Activating connection with DHCP...")
            result = subprocess.run(
                ["sudo", "nmcli", "connection", "up", conn_name, "ifname", iface],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=20,
            )

            if result.returncode == 0:
                logging.info(
                    f"[bt-tether-helper] ✓ NetworkManager connection activated"
                )
                
                # Get and display IP address
                time.sleep(1)  # Brief wait for IP assignment
                ip_result = subprocess.run(
                    ["ip", "-4", "addr", "show", iface],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=5,
                )
                
                if ip_result.returncode == 0:
                    import re
                    ip_match = re.search(r'inet\s+(\d+\.\d+\.\d+\.\d+)', ip_result.stdout)
                    if ip_match:
                        ip_addr = ip_match.group(1)
                        logging.info(f"[bt-tether-helper] ✓ {iface} IP address: {ip_addr}")
                    else:
                        logging.warning(f"[bt-tether-helper] Could not determine IP address for {iface}")
                
                # Verify localhost routing is intact (critical for bettercap API)
                self._verify_localhost_route()
                
                return True
            else:
                logging.error(f"[bt-tether-helper] Failed to activate: {result.stderr}")
                return False

        except subprocess.TimeoutExpired:
            logging.error(f"[bt-tether-helper] NetworkManager setup timed out")
            return False
        except Exception as e:
            logging.error(f"[bt-tether-helper] NetworkManager error: {e}")
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
                logging.warning(
                    "[bt-tether-helper] Could not verify localhost routing"
                )
                
        except Exception as e:
            logging.error(f"[bt-tether-helper] Localhost route verification failed: {e}")

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

            # First, request IP via DHCP
            logging.info(f"[bt-tether-helper] Requesting IP via DHCP on {iface}...")
            try:
                # Try dhcpcd first (common on Raspberry Pi)
                result = subprocess.run(
                    ["sudo", "dhcpcd", "-n", iface],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=15,
                )
                if result.returncode == 0:
                    logging.info(
                        f"[bt-tether-helper] DHCP request via dhcpcd successful"
                    )
                else:
                    # Try dhclient as fallback
                    logging.info(
                        f"[bt-tether-helper] dhcpcd failed, trying dhclient..."
                    )
                    result = subprocess.run(
                        ["sudo", "dhclient", "-v", iface],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        timeout=15,
                    )
                    if result.returncode == 0:
                        logging.info(
                            f"[bt-tether-helper] DHCP request via dhclient successful"
                        )
            except subprocess.TimeoutExpired:
                logging.warning(f"[bt-tether-helper] DHCP request timed out")
            except Exception as dhcp_err:
                logging.warning(f"[bt-tether-helper] DHCP request failed: {dhcp_err}")

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
            import re

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
        """Check if internet is accessible by pinging and DNS resolution"""
        try:
            # First try ping to Google's DNS (8.8.8.8)
            logging.info(f"[bt-tether-helper] Testing connectivity to 8.8.8.8...")
            result = subprocess.run(
                ["ping", "-c", "2", "-W", "3", "8.8.8.8"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
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
            import re

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
                    import re

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
            import re
            result = subprocess.check_output(
                ["ip", "-4", "addr", "show", iface],
                text=True,
                timeout=5
            )
            # Look for inet address (e.g., "inet 192.168.44.123/24")
            match = re.search(r'inet\s+(\d+\.\d+\.\d+\.\d+)', result)
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
            import re

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
                # Use subprocess.run with timeout for pairing command
                env = dict(os.environ)
                env["NO_COLOR"] = "1"
                env["TERM"] = "dumb"

                result = subprocess.run(
                    ["bluetoothctl", "pair", mac],
                    capture_output=True,
                    text=True,
                    timeout=90,
                    env=env,
                )

                output = result.stdout + result.stderr
                clean_output = self._strip_ansi_codes(output)

                # Check if pairing succeeded
                if (
                    "Pairing successful" in clean_output
                    or "AlreadyExists" in clean_output
                ):
                    logging.info(f"[bt-tether-helper] ✓ Pairing successful!")
                    return True
                elif result.returncode == 0:
                    # Command succeeded but output unclear - check status
                    time.sleep(2)
                    pair_status = self._check_pair_status(mac)
                    if pair_status["paired"]:
                        logging.info(f"[bt-tether-helper] ✓ Pairing successful!")
                        return True

                logging.error(f"[bt-tether-helper] Pairing failed: {clean_output}")
                return False

            except subprocess.TimeoutExpired:
                logging.error(f"[bt-tether-helper] Pairing timeout (90s)")
                return False

        except Exception as e:
            logging.error(f"[bt-tether-helper] Pairing error: {e}")
            return False

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

                # Check for common errors and provide helpful hints
                if (
                    "br-connection-create-socket" in error_msg
                    or "br-connection-profile-unavailable" in error_msg
                ):
                    logging.error(
                        "[bt-tether-helper] ⚠️  Bluetooth tethering is NOT enabled on your phone!"
                    )
                    logging.error(
                        "[bt-tether-helper] ⚠️  Go to Settings → Network & internet → Hotspot & tethering → Enable 'Bluetooth tethering'"
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

            import traceback

            logging.error(f"[bt-tether-helper] Traceback: {traceback.format_exc()}")
            return False
