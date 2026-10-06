---
description: Déployer AgentVault sur Avalanche Fuji (testnet) et brancher le dashboard
---

1. `bash scripts/create-wallets.sh` (ne remplace jamais un wallet existant), puis faucet Fuji sur l'adresse Owner affichée.
2. `wsl -d kali-linux --cd /mnt/c/Users/ozgun/Bureau/SecureHorizons-Prep/vaultguard -- bash scripts/deploy-fuji.sh` : déploie, configure liste blanche/délai/appât/guardian/disjoncteur, finance le coffre, donne du gas à l'agent et au guardian.
3. Mets `CHAIN=web3` dans `agent/.env`, puis `bash scripts/doctor.sh` doit finir sans erreur.
4. Lance le dashboard, onglet Coffre → « Vrai coffre » ; joue « Paiement normal » : le lien Snowtrace doit s'ouvrir.
5. Note l'adresse du contrat dans AGENTS.md §6 et dans le README.
