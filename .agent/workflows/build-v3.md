---
description: Construire VaultGuard v3 (plateforme multi-clients) étape par étape à partir de docs/SPEC-V3-PRODUIT.md
---

1. Lis AGENTS.md puis docs/SPEC-V3-PRODUIT.md en entier. Repère l'étape suivante non cochée dans AGENTS.md §6.
2. Réalise UNE seule étape du cahier des charges. Réutilise l'existant (firewall.py, chain.py, server.py : sessions,
   CSRF, limites, en-têtes, scrypt) au lieu de le réécrire ; ne retire aucune protection.
3. Ajoute les tests de l'étape dans agent/test_product.py (dont les tests d'isolation entre clients et de rôles).
4. Lance `wsl -d kali-linux --cd /mnt/c/Users/ozgun/Bureau/SecureHorizons-Prep/vaultguard -- bash scripts/test-all.sh --full`
   et corrige jusqu'au vert, puis `bash scripts/security-audit.sh` (0 échec).
5. Si l'étape touche l'interface : vérifie la page dans le navigateur à 1440 px et 390 px ; aucun texte ne doit dépasser.
6. Coche l'étape dans AGENTS.md §6, résume en 3 lignes ce qui a été fait et propose un message de commit.
