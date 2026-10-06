---
trigger: always_on
---

# Règles VaultGuard (Antigravity)

Lis **AGENTS.md** à la racine du projet avant toute tâche : contexte du hackathon, architecture, commandes, règles.
Résumé non négociable :

- Réponds en **français**, de façon concise. Ozgun débute en cybersécurité : explique chaque nouveau concept en 1-2 phrases.
- Les commandes se lancent dans **WSL Kali** : `wsl -d kali-linux --cd /mnt/c/Users/ozgun/Bureau/SecureHorizons-Prep/vaultguard -- bash <script>`.
- Après chaque modification : `bash scripts/test-all.sh` doit être vert (`--full` avant un commit). Un test pour chaque nouvelle règle.
- Toute règle ajoutée dans `contracts/src/AgentVault.sol` doit être reproduite dans `MockChain` (`agent/chain.py`) ; `test_parity.py` le vérifie.
- Sécurité de l'API (`agent/server.py`) : ne jamais retirer le jeton CSRF, la vérification Host/Origin, les limites de taille et de débit,
  ni les en-têtes de sécurité. Toute nouvelle route POST : valider chaque champ (type + bornes) et la tester dans `test_server.py`.
- Après toute modification de `server.py` ou du dashboard : `bash scripts/security-audit.sh` doit finir par « 0 échec(s) ».
- Jamais de clé privée ou d'API dans le code ni dans un commit : uniquement `agent/.env` (gitignoré), clés de testnet seulement.
  Ne jamais afficher le contenu de `agent/.env`.
- Dashboard : HTML unique, pas de build, pas de CDN, insertion via `textContent` uniquement, aucun attribut `style=` ni `onclick=`
  (la CSP à nonce les bloque) ; design sobre et clair, aucun emoji.
- Fichiers `.sh` en fins de ligne LF.
- Avant de terminer une tâche : mets à jour la section « État d'avancement » d'AGENTS.md.
