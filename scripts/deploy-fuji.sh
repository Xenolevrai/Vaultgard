#!/usr/bin/env bash
# Déploie AgentVault sur Avalanche Fuji avec les wallets de agent/.env, puis donne du gas à l'agent et au guardian.
# Pré-requis : bash scripts/create-wallets.sh, puis ~1 AVAX de test sur l'adresse Owner (faucet).
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.foundry/bin:$PATH"
ENV="${ENV_FILE:-agent/.env}"
set -a; source "$ENV"; set +a; unset CHAIN  # CHAIN est aussi lu par Foundry
RPC="${RPC_URL:-https://api.avax-test.network/ext/bc/C/rpc}"
FUND_WEI="${FUND_WEI:-300000000000000000}"   # 0.3 AVAX déposés dans le coffre
GAS_WEI="${GAS_WEI:-50000000000000000}"      # 0.05 AVAX pour les frais de l'agent
GUARD_WEI="${GUARD_WEI:-20000000000000000}"  # 0.02 AVAX pour les frais du guardian

[ -n "${GUARDIAN_PRIVATE_KEY:-}" ] && [ -n "${CANARY_ADDRESS:-}" ] || { echo "Lance d'abord : bash scripts/create-wallets.sh"; exit 1; }
CID=$(cast chain-id --rpc-url "$RPC")
OWNER=$(cast wallet address "$OWNER_PRIVATE_KEY")
AGENT=$(cast wallet address "$AGENT_PRIVATE_KEY")
GUARDIAN=$(cast wallet address "$GUARDIAN_PRIVATE_KEY")
BAL=$(cast balance "$OWNER" --rpc-url "$RPC")
echo "Réseau : $RPC (chainId $CID)"
[ "$CID" = 43114 ] && { echo "ATTENTION : MAINNET (vrais fonds). Ctrl+C dans 10 s pour annuler."; sleep 10; }
echo "Owner  : $OWNER  ($(cast from-wei "$BAL") AVAX)"
NEED=$(python3 -c "print($FUND_WEI + $GAS_WEI + $GUARD_WEI + 50000000000000000)")
if ! python3 -c "import sys; sys.exit(0 if $BAL >= $NEED else 1)"; then
  echo "ERREUR : il faut au moins $(cast from-wei "$NEED") AVAX sur Owner. Passe par le faucet Fuji avec l'adresse $OWNER."
  exit 1
fi

cd contracts
forge build -q
OUT=$(PRIVATE_KEY=$OWNER_PRIVATE_KEY AGENT_ADDRESS=$AGENT SUPPLIER_ADDRESS=$SUPPLIER_ADDRESS FUND_WEI=$FUND_WEI \
      NEW_SUPPLIER_ADDRESS=$NEW_SUPPLIER_ADDRESS CANARY_ADDRESS=$CANARY_ADDRESS GUARDIAN_ADDRESS=$GUARDIAN \
      forge script script/Deploy.s.sol --rpc-url "$RPC" --broadcast 2>&1) || { echo "$OUT"; exit 1; }
VAULT=$(echo "$OUT" | grep -oE 'AgentVault deployed at: 0x[0-9a-fA-F]{40}' | grep -oE '0x[0-9a-fA-F]{40}')
BLOCK=$(echo "$OUT" | grep -oE 'Deploy block: [0-9]+' | grep -oE '[0-9]+$' || echo 0)
cd ..
put() { if grep -qE "^$1=" "$ENV"; then sed -i "s|^$1=.*|$1=$2|" "$ENV"; else echo "$1=$2" >> "$ENV"; fi; }
put VAULT_ADDRESS "$VAULT"; put DEPLOY_BLOCK "$BLOCK"

echo "Envoi de gas à l'agent et au guardian..."
cast send "$AGENT" --value "$GAS_WEI" --private-key "$OWNER_PRIVATE_KEY" --rpc-url "$RPC" >/dev/null
cast send "$GUARDIAN" --value "$GUARD_WEI" --private-key "$OWNER_PRIVATE_KEY" --rpc-url "$RPC" >/dev/null

EXP=https://testnet.snowtrace.io; [ "$CID" = 43114 ] && EXP=https://snowtrace.io
echo
echo "AgentVault déployé : $VAULT (bloc $BLOCK)"
echo "Explorateur        : $EXP/address/$VAULT"
echo "Étape suivante     : mettre CHAIN=web3 dans $ENV, puis bash scripts/doctor.sh, puis le dashboard."
