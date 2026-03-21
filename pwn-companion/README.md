# 📱 Pwn Companion Plugin for Pwnagotchi

Real-time bidirectional communication between your mobile device and Pwnagotchi via WebSocket. Send commands, GPS coordinates, and more directly to your device.

## Features

- 🔌 **WebSocket Server** on port 8888 (configurable)
- 🔐 **Password-based Authentication** for secure connections
- 📍 **GPS Location Support** - share your location with pwnagotchi
- 🎮 **Custom Commands** - extensible command system
- 📊 **Live Status Display** on pwnagotchi screen
- 🔄 **Multiple Concurrent Clients** supported
- 📝 **Message Logging** for debugging

## Installation

### 1. Install Dependencies

```bash
# Update package manager
sudo apt-get update

# Install websockets library
sudo pip3 install websockets
```

### 2. Copy Plugin

```bash
# Copy the plugin file
sudo cp pwn-companion.py /usr/local/share/pwnagotchi/custom-plugins/
```

### 3. Enable in Config

Add this to `/etc/pwnagotchi/config.toml`:

```toml
[main.plugins.pwn-companion]
enabled = true
port = 8888                     # WebSocket port (default: 8888)
show_on_screen = true
show_client_count = true
status_position = [0, 0]        # [x, y] coordinates
```

### 4. Restart Pwnagotchi

```bash
sudo pwnkill
```

## Configuration Options

| Option              | Type | Default  | Description                      |
| ------------------- | ---- | -------- | -------------------------------- |
| `enabled`           | bool | `true`   | Enable/disable plugin            |
| `port`              | int  | `8888`   | WebSocket server port            |
| `show_on_screen`    | bool | `true`   | Display status on screen         |
| `show_client_count` | bool | `true`   | Show connected client count      |
| `status_position`   | list | `[0, 0]` | Status display position `[x, y]` |

## WebSocket Protocol

### 1. Send Custom Command

**Client → Server:**

```json
{
  "type": "command",
  "action": "command_name",
  "params": {
    "key1": "value1",
    "key2": "value2"
  }
}
```

**Server Response:**

```json
{
  "type": "command_received",
  "action": "command_name"
}
```

**Supported Actions (extensible):**

- `scan` - Trigger WiFi scan
- `status` - Request device status
- `message` - Display message on screen
- Custom actions can be added via `execute_command()` method

### 2. Send GPS Coordinates

**Client → Server:**

```json
{
  "type": "gps",
  "latitude": 37.7749,
  "longitude": -122.4194,
  "accuracy": 10.5
}
```

**Server Response:**

```json
{
  "type": "gps_received",
  "lat": 37.7749,
  "lon": -122.4194
}
```

### 3. Request Status

**Client → Server:**

```json
{
  "type": "status_request"
}
```

**Server Response:**

```json
{
  "type": "status",
  "uptime": 3600,
  "clients": 2,
  "last_gps": {
    "latitude": 37.7749,
    "longitude": -122.4194,
    "accuracy": 10.5,
    "timestamp": 1234567890.5
  },
  "last_command": {
    "action": "scan",
    "params": {},
    "timestamp": 1234567890.5
  }
}
```

### 4. Request UI Screenshot

Request a live screenshot image from the pwnagotchi UI. The image is returned as base64-encoded data.

**Client → Server:**

```json
{
  "type": "image_request"
}
```

**Server Response:**

```json
{
  "type": "image",
  "data": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
  "content_type": "image/png",
  "timestamp": 1234567890.5
}
```

**Error Response:**

```json
{
  "type": "error",
  "message": "Failed to fetch image: <error details>"
}
```

## Mobile App Examples

### Using OkHttp (Kotlin/Android)

```kotlin
package com.example.pwncompanion

import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okhttp3.OkHttpClient
import okhttp3.Request
import com.google.gson.JsonObject
import com.google.gson.Gson
import android.util.Log

class PwnCompanionWebSocket(private val host: String, private val password: String) {

    private val gson = Gson()
    private lateinit var webSocket: WebSocket
    private val client = OkHttpClient()

    fun connect(onConnected: () -> Unit, onMessage: (String) -> Unit) {
        val request = Request.Builder()
            .url("ws://$host:8888")
            .build()

        webSocket = client.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: okhttp3.Response) {
                Log.d("PwnCompanion", "Connected")
                authenticate()
                onConnected()
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                Log.d("PwnCompanion", "Message: $text")
                onMessage(text)
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: okhttp3.Response?) {
                Log.e("PwnCompanion", "Error: ${t.message}")
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                Log.d("PwnCompanion", "Closed: $reason")
            }
        })
    }

    private fun authenticate() {
        val auth = JsonObject()
        auth.addProperty("type", "auth")
        auth.addProperty("password", password)
        webSocket.send(auth.toString())
    }

    fun sendCommand(action: String, params: Map<String, String> = emptyMap()) {
        val command = JsonObject()
        command.addProperty("type", "command")
        command.addProperty("action", action)

        val paramsJson = JsonObject()
        params.forEach { (k, v) -> paramsJson.addProperty(k, v) }
        command.add("params", paramsJson)

        webSocket.send(command.toString())
    }

    fun sendGPS(latitude: Double, longitude: Double, accuracy: Float = 0f) {
        val gps = JsonObject()
        gps.addProperty("type", "gps")
        gps.addProperty("latitude", latitude)
        gps.addProperty("longitude", longitude)
        gps.addProperty("accuracy", accuracy.toDouble())

        webSocket.send(gps.toString())
    }

    fun requestStatus() {
        val status = JsonObject()
        status.addProperty("type", "status_request")
        webSocket.send(status.toString())
    }

    fun disconnect() {
        webSocket.close(1000, "Closing")
    }
}
```

### Usage in Android Activity

```kotlin
class MainActivity : AppCompatActivity() {

    private lateinit var companion: PwnCompanionWebSocket

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        // Replace with your pwnagotchi IP
        companion = PwnCompanionWebSocket("192.168.1.100", "your-strong-password-here")

        companion.connect(
            onConnected = {
                Log.d("Main", "Pwn Companion connected!")
            },
            onMessage = { message ->
                Log.d("Main", "Received: $message")
            }
        )

        // Send GPS location
        findViewById<Button>(R.id.sendGpsButton).setOnClickListener {
            companion.sendGPS(37.7749, -122.4194, 15f)
        }

        // Send command
        findViewById<Button>(R.id.scanButton).setOnClickListener {
            companion.sendCommand("scan")
        }

        // Request status
        findViewById<Button>(R.id.statusButton).setOnClickListener {
            companion.requestStatus()
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        companion.disconnect()
    }
}
```

### Using Python (for testing)

```python
import websocket
import json
import time

class PwnCompanionClient:
    def __init__(self, host, password):
        self.host = host
        self.password = password
        self.ws = None

    def connect(self):
        self.ws = websocket.WebSocketApp(
            f"ws://{self.host}:8888",
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close,
        )
        self.ws.on_open = self.on_open
        self.ws.run_forever()

    def on_open(self, ws):
        print("Connected!")
        self.authenticate()

    def on_message(self, ws, message):
        print(f"Received: {message}")

    def on_error(self, ws, error):
        print(f"Error: {error}")

    def on_close(self, ws, close_status_code, close_msg):
        print("Connection closed")

    def authenticate(self):
        auth = {
            "type": "auth",
            "password": self.password
        }
        self.ws.send(json.dumps(auth))

    def send_gps(self, lat, lon, accuracy=0):
        gps = {
            "type": "gps",
            "latitude": lat,
            "longitude": lon,
            "accuracy": accuracy
        }
        self.ws.send(json.dumps(gps))

    def send_command(self, action, params=None):
        cmd = {
            "type": "command",
            "action": action,
            "params": params or {}
        }
        self.ws.send(json.dumps(cmd))

    def request_status(self):
        status = {"type": "status_request"}
        self.ws.send(json.dumps(status))

if __name__ == "__main__":
    client = PwnCompanionClient("192.168.1.100", "your-strong-password-here")
    client.connect()
```

**Run it:**

```bash
# Install websocket-client
pip install websocket-client

# Run
python3 test_client.py
```

## Troubleshooting

### WebSocket Server Won't Start

**Check if port is in use:**

```bash
sudo lsof -i :8888
# Or for netstat
sudo ss -tlnp | grep 8888
```

**Kill process using port:**

```bash
sudo kill -9 <PID>
```

### Can't Connect from Mobile App

1. **Verify IP Address**: Use `hostname -I` on pwnagotchi

   ```bash
   hostname -I
   ```

2. **Check Firewall**: Ensure port 8888 is accessible

   ```bash
   sudo ufw status
   sudo ufw allow 8888/tcp
   ```

3. **Verify Plugin is Running**:
   ```bash
   sudo tail -f /var/log/pwnagotchi/pwnagotchi.log | grep pwn-companion
   ```

### Authentication Failures

- Double-check password in both pwnagotchi config and mobile app
- Password is case-sensitive
- Make sure to update config and restart pwnagotchi after changing password

### Messages Not Being Received

1. Check authentication succeeded first
2. Verify JSON format is correct
3. Check logs: `sudo tail -f /var/log/pwnagotchi/pwnagotchi.log`

## Extending the Plugin

### Adding Custom Commands

Edit the `execute_command()` method in `pwn-companion.py`:

```python
def execute_command(self, action, params):
    try:
        if action == "custom_action":
            # Your code here
            log.info(f"[pwn-companion] Custom action: {params}")
            pass
        else:
            log.warning(f"[pwn-companion] Unknown action: {action}")
    except Exception as e:
        log.error(f"[pwn-companion] Command execution error: {e}")
```

Then call from mobile app:

```json
{
  "type": "command",
  "action": "custom_action",
  "params": { "key": "value" }
}
```

## API Testing

### Using websocat

```bash
# Install
sudo apt-get install websocat

# Test connection
websocat ws://192.168.1.100:8888

# Paste auth message
{"type": "auth", "password": "pwnagotchi"}

# Send GPS
{"type": "gps", "latitude": 37.7749, "longitude": -122.4194}
```

### Using curl

WebSocket connections require special clients, but you can test the HTTP endpoint:

```bash
curl http://192.168.1.100:8080/plugins/pwn-companion/test
```

## Performance Notes

- Plugin runs in background thread
- No impact on pwnagotchi's main scanning
- Thread-safe client handling with locks
- Incoming messages processed asynchronously

## Security Recommendations

1. **Change Default Password**: Update `password` in config.toml immediately
2. **Use Strong Password**: Use 16+ character password with mixed case and numbers
3. **Local Network Only**: Only accessible on local WiFi/network (no internet exposure recommended)
4. **Monitor Connections**: Check logs regularly for suspicious activity
5. **Update Regularly**: Keep pwnagotchi and plugin updated

## License

Part of the Pwnagotchi Plugins collection

## Contributing

Have ideas for improvement? Feel free to contribute!

---

**Need Help?**

- Check plugin logs: `sudo tail -f /var/log/pwnagotchi/pwnagotchi.log | grep pwn-companion`
- Verify connection: Use websocat or Python test script
- Debug mobile app: Check app logs for WebSocket messages
