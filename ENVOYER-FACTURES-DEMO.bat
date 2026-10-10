@echo off
chcp 65001 >nul
title VaultGuard - envoyer les factures de demonstration
echo Cette fenetre depose 9 mails, un par un, dans la boite de depot du client de demonstration.
echo Avant de commencer :
echo   1. LANCER-DASHBOARD.bat doit tourner.
echo   2. Ouvre http://localhost:8000/app , onglet "2. Factures recues" (la page se met a jour seule).
echo.
if not exist "%~dp0agent\data\boite-entrante" mkdir "%~dp0agent\data\boite-entrante"
pause

call :send 01-facture-normale       "Facture normale du Garage Dupont, 480 EUR"                  "BON A PAYER"
call :send 02-montant-eleve         "Location de 2 400 EUR, au-dessus du seuil de 1 000 EUR"     "A VERIFIER (ton accord est demande)"
call :send 03-changement-de-rib     "Le garage annonce un nouveau RIB"                           "REFUSEE (fraude au changement de RIB)"
call :send 04-instructions-cachees  "Texte blanc invisible qui donne des ordres a l'assistant"   "REFUSEE (instructions cachees)"
call :send 05-fournisseur-inconnu   "Une societe de nettoyage jamais vue"                        "A VERIFIER (fournisseur inconnu)"
call :send 06-expediteur-inconnu    "Mail d'une adresse qui n'est pas dans la liste autorisee"   "ECARTE SANS ETRE LU (rien n'apparait dans la liste)"
call :send 07-expediteur-imite      "Quelqu'un imite l'adresse du dirigeant"                     "ECARTE SANS ETRE LU (adresse non prouvee)"
call :send 08-doublon               "La facture 01 renvoyee une seconde fois"                    "REFUSEE (deja recue)"
call :send 09-facture-electronique  "Facture electronique (fichier XML) de l'epicerie, 126 EUR"  "BON A PAYER"

echo Termine. En haut de la page, le compteur indique les 2 mails ecartes sans etre lus.
pause
exit /b

:send
echo.
echo ------------------------------------------------------------------------
echo Mail %~1
echo   Contenu          : %~2
echo   Resultat attendu : %~3
copy /y "%~dp0examples\boite\%~1.eml" "%~dp0agent\data\boite-entrante\" >nul
echo   Mail depose. Regarde la page (quelques secondes), puis :
pause
exit /b
