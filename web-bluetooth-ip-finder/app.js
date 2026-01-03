// Pwnagotchi IP Finder - Web Bluetooth App
// This app scans for Pwnagotchi devices and retrieves their IP address from BLE advertising

class PwnagotchiIPFinder {
  constructor() {
    this.device = null;
    this.connected = false;

    // DOM elements
    this.scanBtn = document.getElementById("scanBtn");
    this.scanBtnText = document.getElementById("scanBtnText");
    this.statusMessage = document.getElementById("statusMessage");
    this.ipContainer = document.getElementById("ipContainer");
    this.ipAddress = document.getElementById("ipAddress");
    this.deviceInfo = document.getElementById("deviceInfo");
    this.deviceName = document.getElementById("deviceName");
    this.deviceId = document.getElementById("deviceId");
    this.deviceConnected = document.getElementById("deviceConnected");
    this.copyBtn = document.getElementById("copyBtn");
    this.browserCheck = document.getElementById("browserCheck");
    this.devicesContainer = document.getElementById("devicesContainer");
    this.devicesList = document.getElementById("devicesList");

    this.init();
  }

  init() {
    // Check browser compatibility
    if (!navigator.bluetooth) {
      this.showStatus(
        "error",
        "❌ Web Bluetooth is not supported in this browser. " +
          "Please use Chrome, Edge, or Opera on desktop or Android."
      );
      this.browserCheck.className = "status error";
      this.browserCheck.innerHTML =
        "<strong>❌ Browser not supported</strong><br>Please use Chrome, Edge, or Opera";
      return;
    }

    // Browser is compatible
    this.browserCheck.className = "status success";
    this.browserCheck.innerHTML =
      "<strong>✅ Browser is compatible!</strong><br>Click the button below to scan for devices";
    this.scanBtn.disabled = false;

    // Setup event listeners
    this.scanBtn.addEventListener("click", () => this.scanForDevices());
    this.copyBtn.addEventListener("click", () => this.copyIPAddress());
  }

  showStatus(type, message) {
    this.statusMessage.className = `status ${type}`;
    this.statusMessage.innerHTML = message;
    this.statusMessage.style.display = "block";
  }

  hideStatus() {
    this.statusMessage.style.display = "none";
  }

  async scanForDevices() {
    try {
      this.scanBtn.disabled = true;
      this.scanBtnText.textContent = "Scanning...";
      document.querySelector(".spinner").style.display = "inline-block";
      this.hideStatus();
      this.ipContainer.style.display = "none";
      this.devicesContainer.style.display = "none";

      this.showStatus(
        "info",
        "🔍 Scanning for Bluetooth devices... Please wait."
      );

      // Request Bluetooth device
      // Look for devices with "Pwn-" in the name (our BLE advertisement format)
      const device = await navigator.bluetooth.requestDevice({
        filters: [{ namePrefix: "Pwn-" }],
        optionalServices: ["battery_service", "device_information"], // Add services if needed
      });

      this.device = device;

      // Extract IP from device name
      // Format: Pwn-192-168-1-123
      const deviceName = device.name;
      const ip = this.extractIPFromName(deviceName);

      if (ip) {
        this.displayIPAddress(ip, device);
      } else {
        this.showStatus(
          "warning",
          `⚠️ Found device "${deviceName}" but couldn't extract IP address. ` +
            "Make sure BLE broadcasting is enabled on your Pwnagotchi."
        );
      }
    } catch (error) {
      console.error("Scan error:", error);

      if (error.name === "NotFoundError") {
        this.showStatus(
          "warning",
          "⚠️ No devices found. Make sure your Pwnagotchi is powered on and " +
            "Bluetooth tethering is configured."
        );
      } else if (error.name === "SecurityError") {
        this.showStatus(
          "error",
          "❌ Security error: Bluetooth access was denied. " +
            "Please ensure you're using HTTPS or localhost."
        );
      } else {
        this.showStatus("error", `❌ Error: ${error.message}`);
      }
    } finally {
      this.scanBtn.disabled = false;
      this.scanBtnText.textContent = "Scan Again";
      document.querySelector(".spinner").style.display = "none";
    }
  }

  extractIPFromName(deviceName) {
    // Extract IP from format: Pwn-192-168-1-123
    const match = deviceName.match(/Pwn-(\d+)-(\d+)-(\d+)-(\d+)/);
    if (match) {
      return `${match[1]}.${match[2]}.${match[3]}.${match[4]}`;
    }

    // Alternative format check: just look for the pattern after "Pwn-"
    const parts = deviceName.replace("Pwn-", "").split("-");
    if (
      parts.length === 4 &&
      parts.every((p) => !isNaN(p) && p >= 0 && p <= 255)
    ) {
      return parts.join(".");
    }

    return null;
  }

  displayIPAddress(ip, device) {
    this.ipAddress.textContent = ip;
    this.ipContainer.style.display = "block";

    // Show device info
    this.deviceName.textContent = device.name;
    this.deviceId.textContent = device.id;
    this.deviceConnected.textContent = device.gatt.connected
      ? "Yes ✅"
      : "No ❌";
    this.deviceInfo.style.display = "block";

    this.showStatus(
      "success",
      `✅ Successfully found your Pwnagotchi! IP address: ${ip}`
    );
  }

  async copyIPAddress() {
    const ip = this.ipAddress.textContent;

    try {
      await navigator.clipboard.writeText(ip);

      // Visual feedback
      const originalText = this.copyBtn.textContent;
      this.copyBtn.textContent = "✅ Copied!";
      this.copyBtn.style.background =
        "linear-gradient(135deg, #4caf50 0%, #2e7d32 100%)";

      setTimeout(() => {
        this.copyBtn.textContent = originalText;
        this.copyBtn.style.background =
          "linear-gradient(135deg, #667eea 0%, #764ba2 100%)";
      }, 2000);
    } catch (error) {
      // Fallback for older browsers
      const textArea = document.createElement("textarea");
      textArea.value = ip;
      textArea.style.position = "fixed";
      textArea.style.left = "-999999px";
      document.body.appendChild(textArea);
      textArea.select();

      try {
        document.execCommand("copy");
        this.showStatus("success", "✅ IP address copied to clipboard!");
      } catch (err) {
        this.showStatus(
          "error",
          "❌ Failed to copy IP address. Please copy manually."
        );
      }

      document.body.removeChild(textArea);
    }
  }
}

// Initialize the app when DOM is ready
document.addEventListener("DOMContentLoaded", () => {
  new PwnagotchiIPFinder();
});
