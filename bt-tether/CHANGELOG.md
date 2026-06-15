# Changelog

All notable changes to the **bt-tether** plugin are documented here.

## [1.3.0] - 2026-06-15

Reliability, speed and interface overhaul. No new dependencies (standard library
plus the already-present `dbus`/`flask`). Verified end-to-end on a Raspberry Pi
Zero 2 W: full connect, real internet, and `bt_tether_connected` events consumed
by pwn-companion and bt-tether-discord.

### Performance (measured on a Pi Zero 2 W)

- **Connect time ~14 s → ~4 s** (NAP-connected → internet-verified), ~3.5× faster:
  - dhcpcd ARP duplicate-address probe **~6 s → 0 s** (`noarp`; pointless on a
    point-to-point PAN link).
  - Pre-DHCP settle **2 s → 0.5 s**.
  - Post-DHCP stabilize **fixed 2 s → poll** for the lease.
  - Reconnect PAN-interface wait **fixed 2 s → poll**.
- **Time-to-ready ~10 s faster**: wait for a late `on_ready()` cut **15 s → 5 s**
  (the remaining "Initializing" time is pwnagotchi's own boot).
- **Status reads no longer spawn `bluetoothctl`** per device — a single BlueZ
  D-Bus call instead; the web status endpoint is cached ~2 s to coalesce polls.

### Added

- Web **status banner**: colour-coded at-a-glance state with device name,
  interface and IP, plus a live auto-reconnect cooldown countdown.
- **"Enable tethering on phone" indicator**: when the phone refuses the NAP
  service (`br-connection-profile-unavailable`), the web banner says so and the
  e-ink mini status shows `!` (`BT:Tether off?`).
- **"Pair another device"**: the scanner is reachable even when a device is
  already trusted.
- **Log level filtering** (All / Info / Warn / Err) in the web Output panel.
- **Self-healing**: after repeated `br-connection-busy` errors the plugin
  restarts Bluetooth to clear a stuck BlueZ "connecting" state.
- Config options **`nap_connect_timeout`** (default 20) and **`fast_dhcp`**
  (default true).

### Changed

- **On-screen glyphs** use a case-based scheme: lowercase = action in progress
  (`i/s/p/t/u/>/r/d`), UPPERCASE = settled (`C/N/P/X`). Dropped the overloaded `T`.
- **NAP connect is bounded and interruptible** (20 s cap) so an off/out-of-range
  phone can no longer freeze the loop for the full ~30 s BlueZ timeout; the
  half-open link is torn down on abandon.
- **Bluetooth restart waits for adapter readiness** (polls systemd + power state)
  instead of a fixed sleep that raced the pairing agent on slow hardware.
- **Dynamic PAN interface** everywhere (no hardcoded `bnep0`; handles
  `bt-pan`/`bnep1`).
- The **connected event** now carries the real device name instead of the MAC.
- Monitor sleeps are interruptible (prompt shutdown); failure/cooldown state
  fully resets on a manual connect.

### Fixed

- **PAN interface detection race**: NAP would connect but a single immediate
  check missed the not-yet-created `bnep0` ("no interface detected"); now polls.
- **Spurious "restart timed out" warning** every boot (5 s `systemctl restart
  bluetooth` cap was too short on a Pi Zero → 25 s, treated as informational).
- **False-positive disconnect events** from a single transient status read (now
  re-checks before declaring a drop).
- **Resource cleanup**: orphaned `dhclient`/`bluetoothctl` reaped and in-flight
  connects aborted on unload/disconnect.
