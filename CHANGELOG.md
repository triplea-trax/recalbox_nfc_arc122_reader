# Changelog

## v2.0 — Association bug fix

### Fixed
- **Critical bug in association persistence**: previously, associating a
  card that was already associated with another game would concatenate
  the new entry to the old one in `associations.json`, corrupting the
  file and breaking all subsequent scans. Root cause: EmulationStation
  opens the `association` sysfs-like file in `O_APPEND` mode, so each
  write was added to the existing content instead of replacing it. The
  daemon now tracks its own writes and extracts only the new portion
  appended by ES, then rewrites the file clean to prevent future
  accumulation.

### Added
- `clean_associations.py` — one-shot script to repair `associations.json`
  files corrupted by the v1.x bug. Creates a `.corrupted.bak` backup
  before modifying. Run once after upgrading to v2.x.

### Migration from v1.x
If you were using a previous version:
```bash
git pull
./install_nfc.sh --update
/etc/init.d/S32nfc-acr stop
python3 clean_associations.py
/etc/init.d/S32nfc-acr start
```
