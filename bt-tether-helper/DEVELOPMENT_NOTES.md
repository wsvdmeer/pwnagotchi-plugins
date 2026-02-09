# BT Tether Helper - Development Notes

## Target Platform: Raspberry Pi (Linux)

**NOT Windows.** All code must be tested on actual RPi hardware or Linux environment.

### Critical Platform Differences

#### Bluetooth/bluetoothctl Behavior

- **Interactive Mode**: `bluetoothctl` in interactive mode (stdin/stdout) behaves differently than command-line execution
  - Output may be buffered or delayed
  - Process may not respond immediately to commands
  - `readline()` can hang waiting for newlines that never come
  - Solution: Use `hcitool scan` for device discovery instead!

- **Scanning - SOLUTION: Capture `bluetoothctl scan` output with regex validation**
  - ✅ Start `bluetoothctl scan on` and capture output with line buffering
  - ✅ Use `select()` with timeout to read output without blocking indefinitely
  - ✅ Parse "NEW Device MAC Name" and "CHG Device MAC Name" events from output
  - ❌ **Do NOT** use `bluetoothctl devices` - that only shows cached/known devices, not NEW discoveries
  - **Device Parsing**: Use regex pattern to extract MAC addresses from scan output

    ```python
    mac_pattern = re.compile(
        r"([0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2}:[0-9A-Fa-f]{2})"
    )
    # Parse "NEW Device MAC Name" or "CHG Device MAC Name" format
    if "NEW Device" in line or "CHG Device" in line:
        mac_match = mac_pattern.search(line)
    ```

    - Validates MAC address format (HH:HH:HH:HH:HH:HH)
    - Robust against formatting variations in scan output
    - Prevents invalid MAC addresses from being processed

  - **Output format**: `NEW Device XX:XX:XX:XX:XX:XX Device Name`
  - Device discovery is slow on RPi - expect 10-15 second scan duration per device
  - Line-buffered output with select() prevents blocking while still capturing results

- **Connection Timeouts**:
  - Device responses are often slow under load (>5 seconds)
  - Never use aggressive timeouts (<5s) for `bluetoothctl connect`
  - Some devices take 10-15s to respond

#### Subprocess Issues on Linux

- ⚠️ **Do NOT use `fcntl` + `select` for bluetoothctl stdin/stdout**
  - This approach fails with interactive mode on Linux
  - The process may become unresponsive
  - Text mode with buffering=0 doesn't work as expected

- ✅ **CORRECT Approach**: Use simple subprocess.run() or subprocess.Popen() with timeout

  ```python
  result = subprocess.run(
      ["bluetoothctl", "-c", "power on"],
      capture_output=True,
      text=True,
      timeout=5
  )
  ```

- For scanning, use a separate process that you can kill:
  ```python
  proc = subprocess.Popen(["bluetoothctl", "scan", "on"], ...)
  time.sleep(30)  # Scan duration
  proc.terminate()
  ```

### Known Issues & Solutions

#### Issue: Scan Hangs

**Symptom**: "Starting device scan..." then nothing
**Causes**:

- Interactive stdin/stdout with bluetoothctl (blocking readline)
- Process buffering issues
- Device not responding to scan commands

**Solution**:

- Use separate non-interactive scan process
- Don't try to read output in real-time from interactive session
- Use `bluetoothctl -c "command"` for single commands instead

#### Issue: Device Pairing/Trust Failures

**Symptom**: "Device already paired but not trusted" loop
**Root Cause**: Test connect timeout misinterpreted as broken pairing
**Solution**:

- Don't do test connections to verify pairing
- Check trust status with `bluetoothctl info MAC | grep "Trusted"`
- Remove/re-pair only if explicitly needed, not on timeouts

#### Issue: Double Pairing Attempts

**Symptom**: Device gets removed and re-paired unnecessarily
**Root Cause**: Cached pairing from previous failed attempt
**Solution**:

- Skip device discovery scan if device is already in `bluetoothctl devices`
- Trust existing cache, don't re-scan for known devices

### Testing Checklist

Before making changes, test on actual RPi:

- [ ] Device scan completes in ~30s without hanging
- [ ] Scan finds devices in range
- [ ] Pairing prompt appears on device when pairing starts
- [ ] Device trust is properly confirmed
- [ ] No unnecessary pairing removals
- [ ] Connection succeeds within reasonable time (<2 min)
- [ ] Logs show clear progress (no long silent periods)

### Code Guidelines for This Plugin

1. **Always use timeouts** - No infinite waits
   - Bluetooth operations: 5-30s depending on type
   - Network operations: 10-30s
   - Default: 10s unless specified otherwise

2. **Log progress frequently** - Users need to see it's working
   - Log every major step
   - Log every timeout/retry
   - Use appropriate log levels (INFO for progress, DEBUG for details)

3. **Handle timeouts gracefully** - Don't assume timeout = failure
   - Timeout often just means "device is slow"
   - Retry with longer timeouts or exponential backoff
   - Don't remove pairing due to timeout

4. **Avoid interactive subprocess** - Use command-line mode
   - ❌ `subprocess.Popen(["bluetoothctl"], stdin=PIPE, stdout=PIPE)`
   - ✅ `subprocess.run(["bluetoothctl", "-c", "command"])`
   - ✅ `self._run_cmd(["bluetoothctl", "command"], timeout=X)`

5. **Cache device discovery** - Don't re-scan unnecessarily
   - Check if device is in `bluetoothctl devices` first
   - Skip discovery scan if already known
   - Pre-load cached paired devices for immediate UI display

6. **Test device responsiveness** - Don't assume it's broken
   - Slow response ≠ broken pairing
   - Trust ≠ connection capability
   - Always verify the specific property you're checking

### Linux/RPi Specific Modules

- `fcntl` - File control (use for non-blocking I/O if needed, but avoid with bluetoothctl)
- `select` - I/O multiplexing (works better than fcntl for reading, but still not ideal for bluetoothctl)
- `subprocess` - Process execution (preferred for bluetoothctl)
- `os.O_NONBLOCK` - Non-blocking flag for file descriptors

### Deployment Path

- Files go to: `/usr/local/share/pwnagotchi/custom-plugins/` or `/etc/pwnagotchi/plugins/`
- Logs appear in: Pwnagotchi's main log (check with `pwnagotchi` command or `/tmp/pwnagotchi.log`)
- Config: `/etc/pwnagotchi/config.toml`
- Test in place: No need to reinstall, just reload the plugin

### Development Assumptions

- **Bluetooth Tethering**: Always assume BT tethering is enabled and working on the target phone
  - If "profile-unavailable" errors occur, it's likely a BlueZ discovery timing issue, not missing tethering
  - Do NOT suggest disabling/re-enabling tethering as the first diagnostic step

---

**Remember**: Test on actual RPi hardware. Assumptions about subprocess behavior that work on Windows/WSL may fail on bare metal RPi Linux.
