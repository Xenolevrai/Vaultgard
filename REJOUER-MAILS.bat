@echo off
title VaultGuard - mails de demonstration
echo L'agent va lire deux mails enregistres (un normal, un piege) sans se connecter a une boite mail.
echo Le dashboard doit etre lance (LANCER-DASHBOARD.bat). Resultats visibles sur http://localhost:8000/app
echo.
wsl -d kali-linux --cd "%~dp0." -- python3 examples/agent_mail.py --eml examples/mails/facture-normale.eml
echo.
pause
wsl -d kali-linux --cd "%~dp0." -- python3 examples/agent_mail.py --eml examples/mails/facture-piegee.eml
echo.
pause
