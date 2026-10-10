@echo off
title VaultGuard - agent de facturation
echo L'agent IA va lire les factures de examples\factures et demander a VaultGuard de les payer.
echo Le dashboard doit etre lance (LANCER-DASHBOARD.bat). Resultats visibles sur http://localhost:8000/app
echo.
wsl -d kali-linux --cd "%~dp0." -- python3 examples/agent_factures.py --pause
echo.
pause
