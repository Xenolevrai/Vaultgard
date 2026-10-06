@AGENTS.md

## Spécifique à Claude Code
- Exécuter les commandes du projet dans Kali via PowerShell : `wsl -d kali-linux --cd /mnt/c/Users/ozgun/Bureau/SecureHorizons-Prep/vaultguard -- bash -lc "<cmd>"`.
  Attention : dans `bash -lc "..."` lancé depuis PowerShell, éviter `$var` (PowerShell l'interpole) et `#` (commentaire bash) — préférer un script `.sh`.
  Ne pas passer de chemins `/mnt/...` via l'outil Bash (Git Bash les réécrit) — ou préfixer `MSYS_NO_PATHCONV=1`.
  Fichiers écrits depuis Python Windows : `newline="\n"` (sinon CRLF, et les `.sh` cassent). Les gros heredocs dans
  l'outil Bash échouent parfois sur les guillemets : préférer l'outil Write.
- Après une modif : `bash scripts/test-all.sh --full`, et `bash scripts/security-audit.sh` si l'API ou le dashboard changent.
- Python avec web3 : `~/.venvs/vaultguard/bin/python` ; Foundry : `~/.foundry/bin/forge`.
- Le dashboard tourne sur http://localhost:8000 et peut être vérifié avec Claude in Chrome.
- Ozgun utilise aussi **Antigravity** sur ce projet : relire `git log` / l'état dans AGENTS.md §6 en début de session, et mettre §6 à jour en fin de tâche.
- Économie de tokens : lire seulement les parties utiles, pas de sous-agents sauf demande.
