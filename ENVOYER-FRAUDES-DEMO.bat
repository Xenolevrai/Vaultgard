@echo off
chcp 65001 >nul
title VaultGuard - fraudes a la facture electronique
echo Cette fenetre depose 7 mails, un par un : les fraudes que la facture electronique rend possibles.
echo Avant de commencer :
echo   1. LANCER-DASHBOARD.bat doit tourner.
echo   2. Ouvre http://localhost:8000/app , onglet "2. Factures recues" (la page se met a jour seule).
echo   3. Clique sur "Detail" a chaque facture pour lire l'explication.
echo.
if not exist "%~dp0agent\data\boite-entrante" mkdir "%~dp0agent\data\boite-entrante"
pause

call :send 20-facture-electronique-normale "Facture electronique du garage (PDF + donnees XML identiques), 234 EUR" "BON A PAYER"
call :send 21-xml-autre-compte             "Le PDF montre le compte habituel, les donnees XML un compte en Lituanie" "REFUSEE (la page et les donnees ne disent pas la meme chose)"
call :send 22-xml-autre-montant            "Le PDF montre 234 EUR, les donnees XML 432 EUR"                          "REFUSEE (meme raison, sur le montant)"
call :send 23-pdf-retouche                 "PDF retouche avec un editeur en ligne : 138 EUR devenus 234 EUR"         "A VERIFIER (PDF retouche apres sa creation)"
call :send 24-fournisseur-sosie            "Garage DuponD au lieu de DuponT, avec un autre compte"                   "REFUSEE (nom qui imite un fournisseur)"
call :send 25-faux-registre                "Faux registre officiel : inscription, compte en Espagne"                 "REFUSEE (fausse facture de registre)"
call :send 26-doublon-maquille             "La facture 20 renvoyee, un zero remplace par la lettre O dans le numero" "REFUSEE (deja recue)"

echo.
echo Termine. Dernier essai : dans la meme page, bloc "Dernier controle avant la banque", depose le fichier
echo   examples\virements\virements-autre-logiciel.xml
echo Resultat attendu : "N'envoyez pas ce fichier" (le compte du loueur a ete remplace par un compte en Lituanie).
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
