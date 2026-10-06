@echo off
title VaultGuard - diagnostic
wsl -d kali-linux --cd "%~dp0" -- bash scripts/doctor.sh
echo.
pause
