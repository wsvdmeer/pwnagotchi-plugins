# Mobile App Project Template

This directory contains example mobile app code structure for connecting to the Pwn Companion WebSocket plugin.

## Quick Setup

1. **Create new Android Project** in Android Studio
2. **Add Dependencies** to `build.gradle` (Module: app)
3. **Implement WebSocket Connection**
4. **Build UI for commands**

## Dependencies (build.gradle)

```gradle
dependencies {
    // OkHttp for WebSocket
    implementation 'com.squareup.okhttp3:okhttp:4.11.0'

    // Gson for JSON
    implementation 'com.google.code.gson:gson:2.10.1'

    // Location Services (for GPS)
    implementation 'com.google.android.gms:play-services-location:21.0.1'

    // Material Design
    implementation 'androidx.material:material:1.9.0'
}
```

## Project Structure

```
mobile-app/
├── src/main/
│   ├── java/com/example/pwncompanion/
│   │   ├── MainActivity.kt
│   │   ├── PwnCompanionWebSocket.kt
│   │   ├── LocationHelper.kt
│   │   └── ConnectionManager.kt
│   ├── res/
│   │   ├── layout/
│   │   │   ├── activity_main.xml
│   │   │   └── fragment_commands.xml
│   │   └── values/
│   │       ├── strings.xml
│   │       └── dimens.xml
│   └── AndroidManifest.xml
└── build.gradle
```

## Required Permissions (AndroidManifest.xml)

```xml
<manifest ...>
    <uses-permission android:name="android.permission.INTERNET" />
    <uses-permission android:name="android.permission.ACCESS_FINE_LOCATION" />
    <uses-permission android:name="android.permission.ACCESS_COARSE_LOCATION" />

    <application ...>
        <activity android:name=".MainActivity" />
    </application>
</manifest>
```

## Key Files to Implement

### 1. PwnCompanionWebSocket.kt

Main WebSocket connection handler

### 2. MainActivity.kt

Main UI and connection management

### 3. LocationHelper.kt

GPS location tracking

### 4. ConnectionManager.kt

Connection state and lifecycle management

## Quick Start Code

See examples in parent README.md for complete implementations.

## Testing the Connection

Before building full app:

```bash
# Test with Python client
python3 test_client.py

# Or use websocat
websocat ws://pwnagotchi-ip:8888
```

## Common Issues

**Issue**: App crashes on connection

- **Fix**: Ensure pwnagotchi IP is correct and port 8888 is accessible

**Issue**: JSON parsing errors

- **Fix**: Verify response format matches expected protocol

**Issue**: Location permission denied

- **Fix**: Request runtime permissions for Android 6.0+

```kotlin
// Example permission request
ActivityCompat.requestPermissions(
    this,
    arrayOf(Manifest.permission.ACCESS_FINE_LOCATION),
    LOCATION_PERMISSION_CODE
)
```

## Next Steps

1. Create MainActivity with connection UI
2. Implement PwnCompanionWebSocket class
3. Add LocationHelper for GPS
4. Create command buttons in layout
5. Test with Python client first
6. Build and deploy to device
