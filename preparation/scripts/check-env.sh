#!/usr/bin/env bash
# Vérifie les outils nécessaires au hackathon (à lancer dans Kali).
export PATH="$HOME/.foundry/bin:$HOME/.local/bin:$PATH"
for c in git node npm python3 pip3 forge anvil cast curl slither; do
  printf "%-8s: " "$c"
  if command -v "$c" >/dev/null 2>&1; then "$c" --version 2>/dev/null | head -1; else echo "MANQUANT"; fi
done
