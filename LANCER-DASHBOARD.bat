@echo off
title VaultGuard - dashboard
echo Lancement du dashboard VaultGuard...
echo Le navigateur va s'ouvrir sur http://localhost:8000/demo
echo Pour arreter : fermer cette fenetre.
echo.
start "" cmd /c "timeout /t 3 >nul & start http://localhost:8000/demo"
wsl -d kali-linux --cd "%~dp0agent" -- bash -lc "if [ -x ~/.venvs/vaultguard/bin/python ]; then exec ~/.venvs/vaultguard/bin/python server.py; else exec python3 server.py; fi"
pause
