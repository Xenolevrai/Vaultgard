@echo off
title VaultGuard - audit de securite
echo Audit de securite automatise (attaques rejouees sur 127.0.0.1, Slither, Bandit, pip-audit).
echo Rapport : docs\audit-latest.txt
echo.
wsl -d kali-linux --cd "%~dp0.." -- bash scripts/security-audit.sh
echo.
pause
