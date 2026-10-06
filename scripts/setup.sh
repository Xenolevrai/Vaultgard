#!/usr/bin/env bash
# Installation complète (Kali/Ubuntu/macOS). Idempotent : relançable sans risque.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -x "$HOME/.foundry/bin/forge" ]; then
  curl -sSL https://foundry.paradigm.xyz | bash
  "$HOME/.foundry/bin/foundryup"
fi
export PATH="$HOME/.foundry/bin:$PATH"

[ -d contracts/lib/forge-std ] || (cd contracts && forge install foundry-rs/forge-std --no-git)

VENV="$HOME/.venvs/vaultguard"
if [ ! -x "$VENV/bin/python" ]; then
  python3 -m venv "$VENV" 2>/dev/null || { python3 -m venv --without-pip "$VENV"; curl -sS https://bootstrap.pypa.io/get-pip.py | "$VENV/bin/python" - -q; }
fi
"$VENV/bin/python" -m pip install -q -r agent/requirements.txt

[ -f agent/.env ] || cp .env.example agent/.env
echo "OK. Lance : bash scripts/test-all.sh"
