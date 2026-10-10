@echo off
chcp 65001 >nul
title VaultGuard - preparer la plateforme de facturation de demonstration
echo Cette fenetre inscrit deux entreprises sur la plateforme de facturation, sans rien effacer :
echo   - Transports Martin (ton client de demonstration)
echo   - Garage Dupont (son fournisseur), rattache au meme compte
echo.
echo IMPORTANT : ferme d'abord la fenetre de LANCER-DASHBOARD.bat (le site doit etre arrete).
pause
wsl -d kali-linux --cd "%~dp0..\agent" -- bash -lc "if [ -x ~/.venvs/vaultguard/bin/python ]; then ~/.venvs/vaultguard/bin/python ../scripts/seed_inbox_demo.py; else python3 ../scripts/seed_inbox_demo.py; fi"
echo.
echo Ensuite :
echo   1. Relance LANCER-DASHBOARD.bat et ouvre http://localhost:8000/app
echo   2. En haut a droite, liste des entreprises : choisis Garage Dupont
echo   3. Menu "Factures emises" : SIREN du client = 000040014 , une ligne, "Creer et envoyer"
echo   4. Reviens sur Transports Martin, menu "Factures recues" :
echo      la facture est la, deja controlee, "Bon a payer".
pause
