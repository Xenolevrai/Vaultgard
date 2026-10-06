#!/usr/bin/env bash
# Affiche les soldes (AVAX) des wallets et du coffre sur le réseau configuré (Fuji par défaut).
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.foundry/bin:$PATH"
set -a; source "${ENV_FILE:-agent/.env}"; set +a; unset CHAIN
RPC="${RPC_URL:-https://api.avax-test.network/ext/bc/C/rpc}"

show() { [ -n "$2" ] && printf "  %-9s %s  %s AVAX\n" "$1" "$2" "$(cast balance "$2" --ether --rpc-url "$RPC")"; return 0; }
echo "Réseau : $RPC (chainId $(cast chain-id --rpc-url "$RPC"))"
show Owner "$(cast wallet address "$OWNER_PRIVATE_KEY")"
show Agent "$(cast wallet address "$AGENT_PRIVATE_KEY")"
[ -n "${GUARDIAN_PRIVATE_KEY:-}" ] && show Guardian "$(cast wallet address "$GUARDIAN_PRIVATE_KEY")"
show Supplier "${SUPPLIER_ADDRESS:-}"
show Coffre "${VAULT_ADDRESS:-}"
