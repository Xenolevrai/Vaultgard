---
description: Lancer le dashboard de démo VaultGuard (simulation, anvil local ou Fuji)
---

1. Le plus simple : double-clic sur `LANCER-DASHBOARD.bat` (ouvre http://localhost:8000).
2. Si quelque chose cloche : `DIAGNOSTIC.bat` (ou `bash scripts/doctor.sh`).
3. Blockchain locale : `bash scripts/local-chain.sh` puis `cd agent && ENV_FILE=.env.anvil ~/.venvs/vaultguard/bin/python server.py`
4. Fuji : `CHAIN=web3` dans `agent/.env` (après `deploy-fuji.sh`), puis `LANCER-DASHBOARD.bat`.
5. Dérouler le script de `docs/PITCH.md` (bouton « Mode présentation » pour le projecteur).
