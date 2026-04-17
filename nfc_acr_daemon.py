#!/usr/bin/env python3
"""
NFC ACR122U Card Reader Daemon for Recalbox
============================================
Reads NFC cards from ACR122U USB reader and writes card state
to /tmp/fake-card-reader/ files. Combined with mount --bind,
EmulationStation sees these as the real sysfs card-reader files.

Architecture:
  ACR122U USB -> daemon Python -> /tmp/fake-card-reader/ -> mount --bind -> ES

BUGFIX (v2): EmulationStation writes to the 'association' file in APPEND
mode (O_APPEND). Each new association made by the user was concatenated
to the previous value instead of replacing it, corrupting the file and
associations.json. The daemon now tracks what it wrote itself and
extracts only the NEW part that ES appended, even if ES appended
multiple entries in rapid succession.
"""

import os
import re
import time
import json
import signal
import usb1

FAKE_DIR = "/tmp/fake-card-reader"
ASSOC_FILE = "/recalbox/share/system/nfc-daemon/associations.json"
CONFIG_FILE = "/recalbox/share/system/nfc-daemon/config.json"
ACR_VID = 0x072f
ACR_PID = 0x2200

# Regex pour détecter un UUID format 8-4-4-4-12 hex suivi de ||
UUID_HEADER_RE = re.compile(
    r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\|\|'
)


class ACRDaemon:
    def __init__(self):
        self.running = True
        self.plugged = False
        self.uuid = 0
        self.associations = {}
        self.handle = None
        self.ctx = None
        self.buzzer = False

        # BUGFIX: mémoire de la dernière valeur écrite dans "association".
        # Sert à distinguer ce que le daemon a écrit lui-même de ce que ES
        # a appendé derrière en mode O_APPEND.
        self._last_written_assoc = ""

        os.makedirs(FAKE_DIR, exist_ok=True)
        self.load_associations()
        self.load_config()
        self.init_files()

        signal.signal(signal.SIGTERM, self._sig)
        signal.signal(signal.SIGINT, self._sig)

    def _sig(self, sig, frame):
        print(f"[ACR] Signal {sig}, stopping...")
        self.running = False

    def load_associations(self):
        try:
            with open(ASSOC_FILE, 'r') as f:
                self.associations = json.load(f)
            print(f"[ACR] Loaded {len(self.associations)} associations")
        except:
            self.associations = {}

    def save_associations(self):
        try:
            with open(ASSOC_FILE, 'w') as f:
                json.dump(self.associations, f, indent=2)
        except Exception as e:
            print(f"[ACR] Save error: {e}")

    def load_config(self):
        try:
            with open(CONFIG_FILE, 'r') as f:
                cfg = json.load(f)
            self.buzzer = cfg.get("buzzer", False)
            print(f"[ACR] Config: buzzer={self.buzzer}")
        except:
            self.buzzer = False

    def init_files(self):
        """Create all sysfs-like files with initial values"""
        files = {
            "available": "true",
            "plugged": "false",
            "uuid": "0",
            "firmware_version": "80",
            "module_version": "80",
            "reversed": "false",
            "specific": "false",
            "season": "0",
            "id": "0",
            "association": "",
            "reset_card": "",
        }
        for name, value in files.items():
            with open(os.path.join(FAKE_DIR, name), 'w') as f:
                f.write(value)

    def write_state(self):
        uid_str = str(self.uuid)
        assoc = self.associations.get(uid_str, "")
        writes = {
            "plugged": "true" if self.plugged else "false",
            "uuid": uid_str if self.plugged else "0",
            "id": uid_str if self.plugged else "0",
            "association": assoc,
        }
        for name, value in writes.items():
            with open(os.path.join(FAKE_DIR, name), 'w') as f:
                f.write(value)
        # BUGFIX: mémoriser ce qu'on vient d'écrire dans "association"
        self._last_written_assoc = assoc

    @staticmethod
    def _extract_last_assoc(text):
        """Si text contient plusieurs entrées 'UUID||path' concaténées,
        retourne la dernière. Sinon retourne text tel quel."""
        matches = list(UUID_HEADER_RE.finditer(text))
        if len(matches) > 1:
            return text[matches[-1].start():]
        return text

    def check_association_write(self):
        """Check if ES wrote a new association.

        ES ouvre le fichier 'association' en mode O_APPEND, donc chaque
        écriture est AJOUTÉE au contenu existant au lieu de le remplacer.
        On compare ce qu'on lit à ce qu'on a écrit soi-même pour isoler
        uniquement la partie ajoutée par ES.
        """
        try:
            path = os.path.join(FAKE_DIR, "association")
            with open(path, 'r') as f:
                raw = f.read()

            if not self.plugged:
                return

            # Déterminer ce qu'ES a ajouté par-dessus ce que le daemon a écrit
            prefix = self._last_written_assoc
            if raw.startswith(prefix) and len(raw) > len(prefix):
                new_part = raw[len(prefix):].strip()
            elif raw == prefix:
                # Rien de nouveau, juste ce qu'on a écrit
                return
            else:
                # Contenu inattendu (race ou état incohérent)
                # → fallback : extraire la dernière entrée UUID du tout
                new_part = self._extract_last_assoc(raw).strip()

            if not new_part:
                return

            # Si la nouvelle partie contient elle-même plusieurs entrées
            # (ES a fait plusieurs append rapidement), garder la dernière
            new_assoc = self._extract_last_assoc(new_part).strip()
            if not new_assoc:
                return

            uid_str = str(self.uuid)
            if self.associations.get(uid_str) != new_assoc:
                self.associations[uid_str] = new_assoc
                self.save_associations()
                print(f"[ACR] Association: UID={uid_str} -> {new_assoc}")

                # Nettoyer le fichier : garder uniquement la nouvelle assoc
                # → empêche toute concaténation future de s'amplifier
                with open(path, 'w') as f:
                    f.write(new_assoc)
                self._last_written_assoc = new_assoc
        except Exception as e:
            print(f"[ACR] assoc check error: {e}")

        # === Reset card (inchangé) ===
        try:
            path = os.path.join(FAKE_DIR, "reset_card")
            with open(path, 'r') as f:
                content = f.read().strip()
            if content and content not in ("0", ""):
                uid_str = str(self.uuid)
                if uid_str in self.associations:
                    del self.associations[uid_str]
                    self.save_associations()
                    print(f"[ACR] Reset association for UID={uid_str}")
                with open(path, 'w') as f:
                    f.write("")
                # Après reset, invalider le prefix mémorisé
                self._last_written_assoc = ""
        except:
            pass

    def led_command(self, state, buzz=False):
        """LED/buzzer: 'green' = card detected, 'red' = no card/idle"""
        try:
            if state == 'green':
                self.send_apdu([0xFF, 0x00, 0x40, 0x0E, 0x04,
                                0x02, 0x01, 0x01, 0x01 if buzz else 0x00])
            elif state == 'red':
                self.send_apdu([0xFF, 0x00, 0x40, 0x0D, 0x04,
                                0x00, 0x00, 0x00, 0x00])
        except:
            pass

    def connect_acr(self):
        try:
            if self.ctx:
                try:
                    self.ctx.close()
                except:
                    pass
            self.ctx = usb1.USBContext()
            for dev in self.ctx.getDeviceList():
                if dev.getVendorID() == ACR_VID and dev.getProductID() == ACR_PID:
                    self.handle = dev.open()
                    try:
                        if self.handle.kernelDriverActive(0):
                            self.handle.detachKernelDriver(0)
                    except:
                        pass
                    self.handle.claimInterface(0)
                    print("[ACR] ACR122U connected!")
                    self.led_command('red')
                    return True
        except Exception as e:
            print(f"[ACR] Connect error: {e}")
            self.handle = None
        return False

    def send_apdu(self, apdu):
        ccid = bytes([0x6F, len(apdu) & 0xFF, (len(apdu) >> 8) & 0xFF,
                      0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00]) + bytes(apdu)
        self.handle.bulkWrite(0x02, ccid, timeout=2000)
        return list(self.handle.bulkRead(0x82, 256, timeout=2000))

    def poll_card(self):
        """Poll for NFC card, return UID or 0, -1 on error"""
        try:
            resp = self.send_apdu([0xFF, 0x00, 0x00, 0x00, 0x04,
                                   0xD4, 0x4A, 0x01, 0x00])
            if len(resp) > 10:
                payload = resp[10:]
                if (len(payload) >= 3 and payload[0] == 0xD5
                        and payload[1] == 0x4B and payload[2] >= 1):
                    nfcid_len = payload[7] if len(payload) > 7 else 0
                    if nfcid_len > 0 and len(payload) > 8 + nfcid_len:
                        uid_bytes = payload[8:8 + nfcid_len]
                        uid = 0
                        for i in range(min(4, len(uid_bytes))):
                            uid |= uid_bytes[i] << (i * 8)
                        self.send_apdu([0xFF, 0x00, 0x00, 0x00, 0x03,
                                        0xD4, 0x52, 0x00])
                        return uid
            try:
                self.send_apdu([0xFF, 0x00, 0x00, 0x00, 0x03,
                                0xD4, 0x52, 0x00])
            except:
                pass
            return 0
        except usb1.USBErrorTimeout:
            return 0
        except Exception:
            return -1

    def run(self):
        print("[ACR] NFC ACR122U Daemon started")
        print(f"[ACR] Fake dir: {FAKE_DIR}")
        print(f"[ACR] Buzzer: {'ON' if self.buzzer else 'OFF'}")

        if not self.connect_acr():
            print("[ACR] ACR122U not found, retrying...")

        miss_count = 0

        while self.running:
            if not self.handle:
                time.sleep(5)
                self.connect_acr()
                continue

            uid = self.poll_card()

            if uid == -1:
                print("[ACR] USB error, reconnecting...")
                self.handle = None
                time.sleep(2)
                continue

            if uid > 0:
                miss_count = 0
                if not self.plugged or self.uuid != uid:
                    self.plugged = True
                    self.uuid = uid
                    self.write_state()
                    print(f"[ACR] Card detected: UID={uid} (0x{uid:08X})")
                    self.led_command('green', buzz=self.buzzer)
            else:
                miss_count += 1
                if miss_count >= 3 and self.plugged:
                    self.plugged = False
                    self.uuid = 0
                    self.write_state()
                    print("[ACR] Card removed")
                    self.led_command('red')

            if self.plugged:
                self.check_association_write()

            time.sleep(0.3)

        # Cleanup
        self.plugged = False
        self.uuid = 0
        self.write_state()
        print("[ACR] Daemon stopped")


if __name__ == "__main__":
    ACRDaemon().run()
