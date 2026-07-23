# ⚠️ Plugin Renamed: bt-tether-helper → bt-tether

This folder has been kept for backwards compatibility with old links and references.

## 📍 New Location

The plugin has been renamed to **`bt-tether`** for consistency with the default Pwnagotchi plugin naming conventions.

### Migration Guide

**If you have old references to `bt-tether-helper`:**

1. **Update your file paths:**
   - Old: `/usr/local/share/pwnagotchi/custom-plugins/bt-tether-helper.py`
   - New: `/usr/local/share/pwnagotchi/custom-plugins/bt-tether.py`

2. **Update your configuration (`config.toml`):**

   ```toml
   # Old
   [main.plugins.bt-tether-helper]

   # New
   [main.plugins.bt-tether]
   ```

3. **Update web UI links:**
   - Old: `http://<pwnagotchi-ip>:8080/plugins/bt-tether-helper`
   - New: `http://<pwnagotchi-ip>:8080/plugins/bt-tether`

### Quick Migration Steps

```bash
# Remove old plugin file
sudo rm /usr/local/share/pwnagotchi/custom-plugins/bt-tether-helper.py

# Copy new plugin file
sudo cp bt-tether/bt-tether.py /usr/local/share/pwnagotchi/custom-plugins/

# Update your config.toml with the new plugin name [main.plugins.bt-tether]

# Restart Pwnagotchi
pwnkill
```

## 📖 Full Documentation

See the **[📖 Full Documentation](../bt-tether/README.md)** for complete plugin documentation and installation instructions.

---

**Version History:**

- **v1.2.3+**: Renamed to `bt-tether` (current)
- **v1.2.3 and earlier**: Named `bt-tether-helper`

All functionality remains the same—only the name has changed.
