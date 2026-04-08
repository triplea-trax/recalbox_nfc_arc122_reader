# NFC ACR122U Card Reader pour Recalbox

## Qu'est-ce que c'est ?
Ce système permet d'utiliser un **lecteur NFC USB ACR122U** standard avec la
fonction Card Reader d'EmulationStation sur Recalbox. Vous pouvez utiliser
n'importe quelle carte NFC (NTAG, Mifare, etc.) au lieu des Recalcards officielles.

## Comment ça marche
```
Lecteur ACR122U USB
       ↓ (libusb)
Daemon Python lit les cartes NFC
       ↓ (écrit des fichiers)
/tmp/fake-card-reader/plugged, uuid, etc.
       ↓ (mount --bind)
/sys/kernel/recalbox-card-reader/
       ↓ (lit les fichiers)
EmulationStation → détecte la carte → lance le jeu
```

La commande `mount --bind` superpose nos fichiers sur le chemin sysfs
qu'EmulationStation lit. ES ne voit aucune différence avec le Card Reader officiel.

## Prérequis
- Raspberry Pi 5 avec Recalbox
- Lecteur NFC USB ACR122U
- Cartes NFC (NTAG213/215/216, Mifare Classic, etc.)

## Installation
```bash
# Copier les fichiers sur le Pi (depuis votre PC)
scp -r nfc-acr-final/ root@<ip-du-pi>:/recalbox/share/system/

# Se connecter en SSH
ssh root@<ip-du-pi>

# Installer
mount -o remount,rw /
cd /recalbox/share/system/nfc-acr-final
sh install.sh

# Redémarrer
reboot
```

## Utilisation
1. Brancher l'ACR122U sur un port USB du Pi
2. Le daemon démarre automatiquement au boot
3. **LED rouge** = lecteur prêt, en attente de carte
4. Poser une carte NFC → **LED verte** = carte détectée
5. Dans ES, naviguer vers un jeu et choisir "Associer cette carte au jeu"
6. La prochaine fois, poser la carte = le jeu se lance automatiquement !

## Commandes
```bash
/etc/init.d/S32nfc-acr start    # Démarrer le daemon + mount bind
/etc/init.d/S32nfc-acr stop     # Arrêter le daemon + retirer mount bind
/etc/init.d/S32nfc-acr restart  # Redémarrer
/etc/init.d/S32nfc-acr status   # Vérifier le statut
```

## Configuration du buzzer
Éditer `/recalbox/share/system/nfc-daemon/config.json` :

```json
{"buzzer": false}   ← silencieux (défaut)
{"buzzer": true}    ← bip à chaque détection de carte
```

Puis redémarrer : `/etc/init.d/S32nfc-acr restart`

## LED du lecteur
| État | LED | Buzzer |
|------|-----|--------|
| En attente | Rouge | - |
| Carte détectée | Verte | Bip (si activé) |
| Carte retirée | Rouge | - |

## Après une mise à jour Recalbox
Les mises à jour de Recalbox **écrasent la partition système**, ce qui supprime
le script de démarrage `/etc/init.d/S32nfc-acr`. Les fichiers du daemon dans
`/recalbox/share/system/nfc-daemon/` ne sont **pas affectés** car ils sont sur
la partition données.

Pour restaurer après une mise à jour :
```bash
ssh root@<ip-du-pi>
mount -o remount,rw /
cd /recalbox/share/system/nfc-acr-final
sh install.sh
reboot
```

C'est tout ! Le script `install.sh` recrée le service init.d et désactive
automatiquement l'ancien daemon NFC s'il est présent.

## Fichiers installés

### Partition données (survivent aux mises à jour)
- `/recalbox/share/system/nfc-daemon/nfc_acr_daemon.py` — Daemon principal
- `/recalbox/share/system/nfc-daemon/config.json` — Configuration (buzzer)
- `/recalbox/share/system/nfc-daemon/associations.json` — Correspondances carte↔jeu

### Partition système (écrasés par les mises à jour)
- `/etc/init.d/S32nfc-acr` — Script de démarrage automatique

### Fichiers temporaires
- `/tmp/fake-card-reader/` — Fichiers sysfs virtuels
- `/tmp/nfc-acr.log` — Log du daemon

## Dépannage
| Problème | Solution |
|----------|----------|
| ACR122U non détecté | Vérifier `lsusb \| grep ACR` |
| LIBUSB_ERROR_BUSY | Ancien daemon NFC actif : `pkill -f nfc_daemon` |
| ES dit "not installed" | Module kernel absent : `modprobe recalbox_card_reader` |
| Carte non détectée | Essayer un autre type de carte NFC |
| LED ne s'allume pas | Vérifier les logs : `cat /tmp/nfc-acr.log` |
| Ne fonctionne plus après MAJ | Réinstaller : `cd /recalbox/share/system/nfc-acr-final && sh install.sh && reboot` |

## Détails techniques

### Pourquoi mount --bind et pas LD_PRELOAD ?
EmulationStation utilise `std::ifstream` (C++) pour lire les fichiers sysfs.
La chaîne d'appels interne passe par des symboles glibc cachés
(`__open_nocancel`) qui ne sont pas interposables par LD_PRELOAD.

`mount --bind` résout le problème au niveau du système de fichiers : **tous**
les accès sont redirigés, quel que soit le mécanisme utilisé par ES.

### Pourquoi le script init.d est nécessaire
Le module kernel `recalbox-card-reader.ko` crée le dossier
`/sys/kernel/recalbox-card-reader/` au chargement. Sans ce dossier,
EmulationStation ne détecte pas le Card Reader. Le `.ko` doit être chargé
**avant** le `mount --bind`, ce que le script init.d gère automatiquement.

### Fichiers sysfs du Card Reader
| Fichier | Permissions | Description |
|---------|:-----------:|-------------|
| available | 0444 | "true" si le lecteur est présent |
| plugged | 0444 | "true" si une carte est posée |
| uuid | 0444 | UID numérique de la carte (décimal) |
| association | 0644 | Chemin système/ROM associé à la carte |
| reset_card | 0644 | Écriture pour dissocier une carte |
| firmware_version | 0444 | Version firmware (80 = "À JOUR") |
| module_version | 0444 | Version du module kernel |

### UID des cartes NFC
Les cartes NTAG ont un UID de 7 bytes. L'ACR122U lit les 4 premiers bytes
en little-endian pour générer un UID 32-bit.
