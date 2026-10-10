@echo off
title VaultGuard - agent branche sur la boite mail
echo L'agent surveille la boite configuree dans examples\.env.mail (lecture seule, objet contenant "facture").
echo Le dashboard doit etre lance. Resultats sur http://localhost:8000/app   -   Ctrl+C pour arreter.
echo.
wsl -d kali-linux --cd "%~dp0." -- python3 examples/agent_mail.py --watch 15
echo.
pause
