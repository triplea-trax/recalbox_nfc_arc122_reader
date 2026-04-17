#!/usr/bin/env python3
"""
clean_associations.py
=====================
Fixes associations.json corrupted by the APPEND bug (v1.x).

In v1.x of the daemon, repeated card associations concatenated the new
value to the old one instead of replacing it, because EmulationStation
writes to the sysfs-like file in O_APPEND mode. This script repairs
existing associations.json files by keeping only the last valid entry
per card.

Run ONCE after updating to v2.x:
    /etc/init.d/S32nfc-acr stop
    python3 clean_associations.py
    /etc/init.d/S32nfc-acr start
"""
import json
import re
import sys
import os
import shutil

CANDIDATES = [
    "/recalbox/share/system/nfc-daemon/associations.json",
    "/recalbox/share/system/nfc-acr-system/associations.json",
]

UUID_RE = re.compile(
    r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\|\|'
)


def clean_value(value):
    matches = list(UUID_RE.finditer(value))
    if len(matches) <= 1:
        return value
    return value[matches[-1].start():]


def main():
    found_any = False
    for path in CANDIDATES:
        if not os.path.isfile(path):
            continue
        found_any = True
        print(f"Processing {path}")

        backup = path + ".corrupted.bak"
        shutil.copy(path, backup)
        print(f"  Backup saved to {backup}")

        with open(path, 'r') as f:
            assocs = json.load(f)

        cleaned = {}
        changes = 0
        for uid, value in assocs.items():
            new_value = clean_value(value)
            if new_value != value:
                changes += 1
                print(f"  UID {uid}:")
                print(f"    BEFORE: {value[:80]}...")
                print(f"    AFTER:  {new_value}")
            cleaned[uid] = new_value

        with open(path, 'w') as f:
            json.dump(cleaned, f, indent=2)

        print(f"  {changes}/{len(cleaned)} associations cleaned")

    if not found_any:
        print("No associations.json found. Nothing to do.")
        sys.exit(1)

    print("\nDone. Restart the daemon: /etc/init.d/S32nfc-acr restart")


if __name__ == "__main__":
    main()
