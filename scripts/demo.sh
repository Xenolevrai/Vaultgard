#!/usr/bin/env bash
# Lance le serveur VaultGuard et affiche l'URL de la démonstration interactive.
#   bash scripts/demo.sh
set -euo pipefail
cd "$(dirname "$0")/.."
echo "Lancement de VaultGuard..."
echo "Démonstration interactive accessible sur : http://localhost:8000/demo"
echo "Site public d'accueil sur : http://localhost:8000"
echo "Appuyez sur Ctrl+C pour arrêter."
PY="$HOME/.venvs/vaultguard/bin/python"; [ -x "$PY" ] || PY=python3
cd agent && exec "$PY" server.py
