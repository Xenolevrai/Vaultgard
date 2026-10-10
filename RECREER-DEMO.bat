@echo off
title VaultGuard - recreer la base de demonstration
echo ATTENTION : ferme d'abord la fenetre du dashboard (LANCER-DASHBOARD.bat) si elle est ouverte.
echo L'ancienne base est sauvegardee. Les identifiants de agent\data\COMPTES-DEMO.txt vont changer.
echo.
pause
wsl -d kali-linux --cd "%~dp0agent" -- bash -lc "if [ -x ~/.venvs/vaultguard/bin/python ]; then ~/.venvs/vaultguard/bin/python ../scripts/seed-demo-local.py; else python3 ../scripts/seed-demo-local.py; fi"
echo.
echo Termine. Relance LANCER-DASHBOARD.bat, puis connecte-toi avec les nouveaux identifiants.
pause
