#!/usr/bin/env bash
# Lance les tests. À exécuter avant chaque commit/push.
#   bash scripts/test-all.sh           rapide : contrat (unitaires + fuzz + invariants) + Python (unitaires + API)
#   bash scripts/test-all.sh --full    + parité/bout en bout sur blockchain locale + analyse statique (Slither, Bandit)
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.foundry/bin:$PATH"
PY="$HOME/.venvs/vaultguard/bin/python"; [ -x "$PY" ] || PY=python3
AUDIT="$HOME/.venvs/vg-audit/bin"
FULL=0; [ "${1:-}" = "--full" ] && FULL=1
ok() { echo "   OK  $1"; }

echo "== 1. Contrat : tests unitaires, fuzzing, invariants (forge test)"
(cd contracts && forge test -q) || { echo "   ECHEC : voir ci-dessus"; exit 1; }; ok "contrat"
bash scripts/export-abi.sh >/dev/null; ok "ABI exportée"

echo "== 2. Agent : tests unitaires + fonctionnels + sécurité de l'API"
(cd agent && AUDIT_PATH=/dev/null CHAIN= "$PY" -m unittest -q test_vaultguard test_server test_product test_layout 2>&1 | grep -vE '^\{"event"' ) || { echo "   ECHEC : voir ci-dessus"; exit 1; }; ok "python"

if [ $FULL = 1 ]; then
  echo "== 3. Parité simulation <-> contrat + bout en bout (anvil)"
  export ANVIL_PORT=8599 OUT_ENV=/tmp/vg-parity.env
  pkill -f "anvil --silent --port 8599" 2>/dev/null || true
  bash scripts/local-chain.sh >/dev/null
  (cd agent && PARITY_ENV=/tmp/vg-parity.env AUDIT_PATH=/dev/null "$PY" -m unittest -q test_parity) || { echo "   ECHEC : voir ci-dessus"; exit 1; }; ok "parité + e2e"
  pkill -f "anvil --silent --port 8599" 2>/dev/null || true; rm -f /tmp/vg-parity.env

  echo "== 4. Analyse statique"
  if [ -x "$AUDIT/slither" ]; then
    # arbitrary-send-eth / reentrancy : faux positifs documentés (destinataires en liste blanche, verrou nonReentrant).
    if (cd contracts && "$AUDIT/slither" . --exclude-dependencies --exclude-informational --exclude-low \
          --exclude arbitrary-send-eth,reentrancy-eth,reentrancy-no-eth >/tmp/slither.txt 2>&1); then
      ok "slither (aucune alerte moyenne/haute)"
    else
      echo "   ALERTE slither :"; grep -vE '^INFO:Slither|running' /tmp/slither.txt | head -20; exit 1
    fi
    (cd contracts && forge build -q)  # slither nettoie out/ : on recompile
  else echo "   (Slither absent : bash scripts/security-audit.sh l'installe)"; fi
  if [ -x "$AUDIT/bandit" ]; then
    "$AUDIT/bandit" -q -r agent -x agent/test_vaultguard.py,agent/test_server.py,agent/test_parity.py,agent/test_product.py,agent/test_layout.py -ll || { echo "   ALERTE bandit"; exit 1; }; ok "bandit (aucune alerte moyenne/haute)"
  fi
fi
echo "== Tout est vert"
