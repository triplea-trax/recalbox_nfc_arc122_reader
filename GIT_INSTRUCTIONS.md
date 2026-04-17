# Comment pousser la mise à jour sur GitHub

## Sur ton PC (où tu as le clone du repo)

```bash
cd ~/chemin/vers/recalbox_nfc_arc122_reader

# Mettre à jour le clone local
git pull origin main

# Copier les fichiers mis à jour
cp /chemin/vers/github_update/nfc_acr_daemon.py .
cp /chemin/vers/github_update/clean_associations.py .
cp /chemin/vers/github_update/CHANGELOG.md .

# Vérifier les changements
git status
git diff nfc_acr_daemon.py

# Stager + commit
git add nfc_acr_daemon.py clean_associations.py CHANGELOG.md
git commit -m "v2.0: Fix association concatenation bug

- Fix critical bug where re-associating a card corrupted associations.json
  (ES uses O_APPEND on the sysfs 'association' file, daemon now handles it)
- Add clean_associations.py to repair JSONs corrupted by the v1.x bug"

# Tag de version (optionnel)
git tag -a v2.0 -m "Version 2.0 - Association bug fix"

# Pousser
git push origin main
git push origin v2.0
```

## Mettre à jour le README

Dans la section "Troubleshooting" ou "Migration", ajouter :

> **Associations corrompues (v1.x)** : si tu viens d'une version
> antérieure et que tes associations semblent cassées (message
> "carte non associée" même pour des cartes associées), lance une
> fois après la mise à jour :
>
> ```bash
> /etc/init.d/S32nfc-acr stop
> python3 clean_associations.py
> /etc/init.d/S32nfc-acr start
> ```
