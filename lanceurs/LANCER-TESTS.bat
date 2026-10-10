@echo off
title VaultGuard - tests complets
echo Tests complets : contrat (unitaires, fuzz, invariants), agent, API, parite blockchain locale, analyse statique.
echo.
wsl -d kali-linux --cd "%~dp0.." -- bash scripts/test-all.sh --full
echo.
pause
