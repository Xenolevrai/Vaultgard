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
- **Prochaine session = hackathon** : commencer par AGENTS.md §8 (mode hackathon), puis §6. La v3 est terminée,
  revue et poussée (CI verte) ; il reste le déploiement Fuji (faucet), les slides et la vidéo de secours.
- Démo locale : base de démo via `scripts/seed-demo-local.py`, serveur via `LANCER-DASHBOARD.bat` (port 8000).
  Ne jamais lire à voix haute / afficher `agent/data/COMPTES-DEMO.txt` ni `agent/.env` : renvoyer Ozgun au fichier.
- Vérifications de sécurité : passer par `scripts/security-audit.sh` et `scripts/test-all.sh --full` (contrôles
  existants, sur 127.0.0.1) et par la relecture de code, plutôt que d'enchaîner des outils d'attaque ad hoc en
  direct : ces sessions ont été coupées plusieurs fois par un filtre automatique.
- Chrome (Claude in Chrome) : le CAPTCHA des faucets, la création de wallet et l'approbation dans l'extension Core
  sont faits par Ozgun ; Claude peut ouvrir les pages, préremplir l'adresse publique Owner et vérifier GitHub Actions.
- Git : dépôt privé `origin` = github.com/Xenolevrai/SecureHorizon (branche `main`). Avant chaque commit, vérifier
  qu'aucune valeur de `agent/.env` n'est indexée (script de comparaison, sans afficher les valeurs).
