---
description: Auditer la sécurité de VaultGuard (attaques rejouées en local + analyses statiques)
---

1. `wsl -d kali-linux --cd /mnt/c/Users/ozgun/Bureau/SecureHorizons-Prep/vaultguard -- bash scripts/security-audit.sh`
2. Lis `docs/audit-latest.txt`. Chaque ligne `[ECHEC]` est une régression : corrige `agent/server.py` et ajoute un test dans `agent/test_server.py`.
3. Pour une nouvelle attaque : ajoute un `check` dans `scripts/security-audit.sh` et une ligne dans le tableau de `docs/SECURITE.md`.
4. Relance jusqu'à « 0 échec(s) ».
