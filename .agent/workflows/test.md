---
description: Lancer tous les tests (contrat + agent + API + parité + analyse statique) et corriger les échecs
---

1. Rapide : `wsl -d kali-linux --cd /mnt/c/Users/ozgun/Bureau/SecureHorizons-Prep/vaultguard -- bash scripts/test-all.sh`
2. Complet (avant commit) : même commande avec `--full` (blockchain locale + Slither + Bandit).
3. Si un test échoue, lis le message, corrige la cause (pas le test, sauf s'il est faux) et relance.
4. Résume en 2 lignes : nombre de tests, ce qui a été corrigé.
