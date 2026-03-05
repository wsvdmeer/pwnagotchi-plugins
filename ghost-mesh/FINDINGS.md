# Ghost Mesh — Technical Findings & Implementation Log

## Executive Summary

**Status:** ✅ **PEER DETECTION WORKING**

Ghost Mesh successfully detects nearby Pwnagotchi peers via BLE manufacturer-specific advertising using a custom 0xDEAD manufacturer ID with a 0xBE magic byte signature.

**Key Achievement:** Discovered and resolved the BLE format discrepancy between expected and actual btmon output, enabling reliable peer detection.

---

## Problem Statement

When scanning for peers broadcasting Ghost Mesh packets, the scanner was detecting the peer device (MAC visible in btmon output) but not recognizing the broadcast data, resulting in 0 peer detections after 28,000+ log lines.

### Symptoms

- Peer device visible in btmon (`B8:27:EB:DA:48:25` — Raspberry Pi Foundation)
- Device advertising consistently with valid BLE data
- Scanner logging ~1000-5000 lines per minute indefinitely
- **NO peer HMAC extraction occurring**
- Top manufacturer IDs seen: 0x00, 0x3E, 0x01, 0xFCF1 (but NOT 0xDEAD)

---

## Root Cause Analysis

### Expected Format vs. Actual Format

**What We Programmed:**

```
Manufacturer Data (0xDEAD): be ec02 4fe8 60b7 0069 a8ac 5b
                            ^^
                            magic byte indicator
```

**What btmon Actually Shows:**

```
Company: not assigned (57005)
Data[12]: beec024fe860b70069a8ac5b
          ^^
          magic byte (same, but in different structure!)
```

### Discovery Process

1. **Initial Observation:** Peer MAC `B8:27:EB:DA:48:25` appeared 7+ times in logs but no HMAC extracted
2. **Diagnostic Logging Added:** Created `🎯 PEER` markers to capture ALL fields broadcast by target MAC
3. **Pattern Recognition:** Logs revealed:
   - `Company: not assigned (57005)` — This is decimal 0xDEAD!
   - `Data[12]: beec024fe860b70069a8ac5b` — Full payload starting with magic byte `be`
   - **Missing:** Traditional "Manufacturer Data (0xDEAD)" format not appearing

### Why the Format Differs

btmon processes BLE advertisement data differently based on packet structure:

- **Standard format** (what we expected): `Manufacturer Data (0xDEAD): [payload]`
  - Occurs when manufacturer ID is in AD structure header
- **Alternative format** (what we found): `Company: [decimal_id]` + `Data[N]: [hex_payload]`
  - Occurs when manufacturer data is embedded differently in raw advertisement

Both are **valid representations of the same 0xDEAD manufacturer ID** — just parsed/displayed differently.

---

## Technical Deep Dive

### Broadcast Payload Structure (12 bytes)

```
Byte 0:      0xBE        (magic byte — distinguishes Ghost Mesh from other 0xDEAD broadcasts)
Bytes 1-6:   [HMAC]      (6 bytes = 12 hex chars, e.g., "ec024fe860b7")
Byte 7:      [peer_cnt]  (0-255, count of known peers)
Bytes 8-11:  [timestamp] (4 bytes, Unix time LE, for replay detection)
─────────────────────────────────────────────────────────────────────
TOTAL: 12 bytes = 24 hex characters
```

### Example Peer Broadcast

```
Data[12]: beec024fe860b70069a8ac5b
          │ └────┬────┘ │ └─┬──┘
          │      HMAC    │  timestamp
          │      (6B)    │  (4B)
          │             peer_count
          │             (0x00)
          magic byte
          (0xBE)
```

**Extracted HMAC:** `ec024fe860b7` (6 bytes, identifies this peer uniquely)

---

## Solution Implementation

### Parser Updates

Added three new parsing paths to handle the 0xDEAD format variations:

#### 1. **Company ID Recognition** (Lines ~830-850)

```python
# Detect when btmon shows Company ID 57005 (decimal 0xDEAD)
if mfg_id == "57005":
    logging.info(f"[ghost-mesh] ⭐ FOUND MFG 0xDEAD (shown as company 57005)")
    # Flag context: next line should contain Data[12] with BE payload
```

#### 2. **Data[BE] Format Parser** (Lines ~850-875)

```python
# Extract HMAC when Data[N] line starts with BE magic byte
if hex_data.startswith("be"):
    if len(hex_data) >= 14:  # Minimum: be + 12 char HMAC
        rx_hmac = hex_data[2:14]  # Skip "be", take 12 chars
        if re.match(r"[0-9a-f]{12}", rx_hmac):
            logging.info(f"✓✓✓ DETECTED PEER (Data[BE] format): {rx_hmac}")
            self._resolve_and_update(rx_hmac)  # Add to peers dict
```

#### 3. **EIR Format Parser** (Original, Lines ~740-800)

- Handles `Unknown EIR field 0xFF[N]: ffaddabe[HMAC]` format
- Kept for compatibility with other BLE devices/implementations
- Searches for embedded `deadbe`/`addebe` patterns

---

## Current Implementation Status

### ✅ Working Features

| Feature           | Status       | Notes                                      |
| ----------------- | ------------ | ------------------------------------------ |
| Peer Detection    | ✅ WORKING   | Successfully extracts HMAC from broadcasts |
| Broadcast Formats | ✅ 3 PARSERS | PRIMARY, EIR, Data[BE], embedded patterns  |
| HMAC Extraction   | ✅ WORKING   | 12-char hex string from magic byte         |
| Peer Storage      | ✅ WORKING   | Peers added to internal dict with metadata |
| Logging Markers   | ✅ ACTIVE    | Debug emissions for troubleshooting        |
| Device Discovery  | ✅ WORKING   | Tracks unique MAC addresses (📍 markers)   |

### 🔄 In Progress

| Feature             | Status      | Notes                                           |
| ------------------- | ----------- | ----------------------------------------------- |
| Two-Way Detection   | ⏳ TESTING  | Need to confirm OUR device is detected by peer  |
| Grid Sync           | ⏳ PENDING  | Requires pwngrid to be running in AUTO mode     |
| Stealth Mode Toggle | ⏳ TESTING  | Verify broadcasting starts/stops correctly      |
| Identity Resolution | ⏳ BLOCKING | No pwngrid running to map HMAC→fingerprint→name |

### 🟡 Known Limitations

1. **Peer Hardcoded:** MAC address `B8:27:EB:DA:48:25` is hardcoded in scanner for tracking
   - Should be removed or made dynamic for production
2. **Verbose Logging:** Debug markers (`⭐`, `🎯`, `📍`) logged for every broadcast
   - Should be reduced to INFO or DEBUG level for production
3. **Single Peer Focus:** Peer-specific field tracking only captures target MAC
   - Should track all peers generically once debugging is complete

4. **No Known Identities:** Without pwngrid, peers show as `Ghost [ec024fe860b7]`
   - Requires identity cache from disk or network sync

---

## Key Learnings

### BLE Format Variations

- **btmon display is not 1:1 with raw BLE data** — same payload may show differently based on AD structure
- **0xDEAD manufacturer ID appears as both:**
  - `Manufacturer Data (0xDEAD): ...` (when in standard location)
  - `Company: not assigned (57005)` (when embedded in different AD structure)
- **Both formats carry identical data** — just need parsers for both

### Peer Discovery Process

1. Peer MAC becomes visible when first advertisement received
2. Each advertisement repeats the same HMAC payload
3. Multiple timestamps/RSSI values seen = multiple advertisement reports
4. Payload structure consistent: `BE` + `[6B HMAC]` + `[1B count]` + `[4B timestamp]`

### Testing Methodology

- **Diagnostic logging must be surgical** — targeted to specific MAC for clarity
- **Field tracking useful** — counts reveal advertising pattern (Company field appears 7× per peer)
- **Repeated unknowns indicate missing parser** — the mystery hex `4a17...ffe4` appeared 50+ times (not ours, from another device)

---

## Broadcast Format Reference

### Format 1: PRIMARY (Standard Manufacturer Data)

```
Line: Manufacturer Data (0xDEAD): be aa bb cc dd ee ff 00 00 00 00
Parse: Extract "aaabbccddeeff" as 12-char HMAC
```

### Format 2: EIR (Raw 0xFF Manufacturer Marker)

```
Line: Unknown EIR field 0xFF[12]: ffaddabe ec024fe860b7 00 69a8ac5b
Parse: Extract "ec024fe860b7" between "ffaddabe" and timestamp
```

### Format 3: DATA[BE] (Embedded Payload)

```
Line: Data[12]: beec024fe860b70069a8ac5b
Parse: Skip "be", extract next 12 chars "ec024fe860b7" as HMAC
```

All three formats carry the **same 12-byte payload** — just different presentation by btmon.

---

## Next Steps for Production

### Phase 1: Clean Up Debug Code

- [ ] Remove hardcoded `peer_mac = "B8:27:EB:DA:48:25"`
- [ ] Replace `⭐`, `🎯`, `📍` markers with conditional debug logging
- [ ] Remove peer-specific field tracking (`peer_data` dictionary)

### Phase 2: Generalize Detection

- [ ] Make parser work for ANY peer, not just target MAC
- [ ] Test with multiple simultaneous peers
- [ ] Verify broadcast cycling (15s ON + 45s OFF)

### Phase 3: Identity Resolution

- [ ] Start pwngrid in AUTO mode
- [ ] Test grid sync endpoint
- [ ] Verify HMAC→fingerprint→name resolution
- [ ] Confirm UI shows named peers instead of "Ghost" placeholders

### Phase 4: Stealth Mode

- [ ] Toggle stealth ON → broadcasting stops
- [ ] Toggle stealth OFF → broadcasting resumes
- [ ] Verify state persists

### Phase 5: Performance Tuning

- [ ] Reduce logging overhead (30KB+ per minute currently)
- [ ] Profile memory usage (dictionaries growing unbounded?)
- [ ] Evaluate keepalive log frequency (every 1000 lines excessive?)

---

## Files Modified

### Primary Implementation

- **[ghost-mesh/ghost-mesh.py](ghost-mesh/ghost-mesh.py)** (v44.2.0, ~1082 lines)
  - Added Data[BE] format parser (~25 lines)
  - Enhanced Company ID tracking (~15 lines)
  - Device discovery logging (~20 lines)
  - Peer-specific tracking (~40 lines, **DEBUG ONLY**)

### Test Results

- ✅ test-scan endpoint: PRIMARY parser validates
- ✅ test-scan endpoint: EIR parser validates
- ✅ Live scan: Peer HMAC `ec024fe860b7` extracted
- ✅ Peer added to internal peers dict
- 🔄 Two-way detection: **PENDING**
- 🔄 Grid sync: **PENDING**

---

## Debugging Reference

### Marker Reference

- `[ghost-mesh] ⭐ FOUND MFG 0xDEAD` — Company ID 57005 detected
- `[ghost-mesh] ⭐⭐⭐ DETECTED PEER (0xDEAD via Data[BE])` — HMAC extracted
- `[ghost-mesh] ✓✓✓ DETECTED PEER (Data[BE] format)` — Peer updated
- `[ghost-mesh] 📍 NEW DEVICE DETECTED` — New MAC address seen
- `[ghost-mesh] 🎯 PEER ADVERTISEMENT FOR [MAC]` — Target peer broadcast
- `[ghost-mesh] 🎯 PEER FIELD` — Peer field data logged

### Common Log Patterns

```
Normal operation: 1000-5000 lines/min with multiple device detections
WARNING "⚠ Found 0xFF field but no ADDE/DEAD+BE": Non-Ghost-Mesh device
INFO "✓✓✓ DETECTED PEER": Ghost Mesh peer found and queued for processing
```

---

## References

### BLE Specification

- **Manufacturer ID 0xDEAD:** Custom assignment for Ghost Mesh
- **Magic Byte 0xBE:** Distinguishes Ghost Mesh from other 0xDEAD vendors
- **AD Structure:** Advertisement Data structures in BLE GAP layer

### Tools Used

- **btmon:** BlueZ HCI monitor (`btmon -i hci0`)
- **hcitool:** BlueZ CLI tool (`hcitool lescan --passive --duplicates`)
- **bt-tether:** Pwnagotchi plugin providing BLE broadcast API

---

## Conclusion

Ghost Mesh peer detection is now **functional and validated**. The breakthrough came from recognizing that btmon displays the same 0xDEAD manufacturer data in multiple formats (`Company: 57005` vs. `Manufacturer Data (0xDEAD)`), each requiring a dedicated parser. With the Data[BE] format parser in place, peer HMACs are reliably extracted and detected.

**Current milestone:** Peer detected ✅  
**Next milestone:** Two-way detection + identity resolution  
**Final milestone:** Production-ready stealth mesh network
