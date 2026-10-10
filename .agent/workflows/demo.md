---
description: Lancer le dashboard de démo VaultGuard (simulation, anvil local ou Fuji)
---

1. Le plus simple : double-clic sur `lanceurs/LANCER-DASHBOARD.bat` (ouvre http://localhost:8000/demo).
2. Si quelque chose cloche : `lanceurs/DIAGNOSTIC.bat` (ou `bash scripts/doctor.sh`).
3. Blockchain locale : `bash scripts/local-chain.sh` puis `cd agent && ENV_FILE=.env.anvil ~/.venvs/vaultguard/bin/python server.py`
4. Fuji : `CHAIN=web3` dans `agent/.env` (après `deploy-fuji.sh`), puis `lanceurs/LANCER-DASHBOARD.bat`.
5. Dérouler le script de `docs/PITCH.md` (bouton « Mode présentation » pour le projecteur).
