#!/usr/bin/env bash
# Lance une blockchain locale (anvil), déploie AgentVault et écrit agent/.env.anvil (ou $OUT_ENV).
# Usage (Kali) : bash scripts/local-chain.sh   puis   cd agent && ENV_FILE=.env.anvil ~/.venvs/vaultguard/bin/python server.py
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.foundry/bin:$PATH"
RPC=http://127.0.0.1:${ANVIL_PORT:-8545}
OUT_ENV="${OUT_ENV:-agent/.env.anvil}"

if ! cast chain-id --rpc-url "$RPC" >/dev/null 2>&1; then
  setsid nohup anvil --silent --port "${ANVIL_PORT:-8545}" >/tmp/anvil.log 2>&1 < /dev/null &
  for _ in $(seq 40); do cast chain-id --rpc-url "$RPC" >/dev/null 2>&1 && break; sleep 0.25; done
fi

# Clés de test PUBLIQUES d'anvil (comptes 0,1,3) — connues de tous, à n'utiliser QU'EN LOCAL.
OWNER_PK=0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80
AGENT_PK=0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d
GUARDIAN_PK=0x7c852118294e51e653712a81e05800f419141751be58f605c371e15141b007a6
AGENT=$(cast wallet address "$AGENT_PK")
GUARDIAN=$(cast wallet address "$GUARDIAN_PK")
SUPPLIER=0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC
NEW_SUPPLIER=0x15d34AAf54267DB7D7c367839AAf71A00a2C6A65
CANARY=0xc0ffee00000000000000000000000000ca4a7700

cd contracts
OUT=$(PRIVATE_KEY=$OWNER_PK AGENT_ADDRESS=$AGENT SUPPLIER_ADDRESS=$SUPPLIER NEW_SUPPLIER_ADDRESS=$NEW_SUPPLIER \
      CANARY_ADDRESS=$CANARY GUARDIAN_ADDRESS=$GUARDIAN \
      forge script script/Deploy.s.sol --rpc-url "$RPC" --broadcast 2>&1) || { echo "$OUT"; exit 1; }
VAULT=$(echo "$OUT" | grep -oE 'AgentVault deployed at: 0x[0-9a-fA-F]{40}' | grep -oE '0x[0-9a-fA-F]{40}')
BLOCK=$(echo "$OUT" | grep -oE 'Deploy block: [0-9]+' | grep -oE '[0-9]+$' || echo 0)
cd ..

cat > "$OUT_ENV" <<ENV
CHAIN=web3
RPC_URL=$RPC
VAULT_ADDRESS=$VAULT
DEPLOY_BLOCK=$BLOCK
AGENT_PRIVATE_KEY=$AGENT_PK
OWNER_PRIVATE_KEY=$OWNER_PK
GUARDIAN_PRIVATE_KEY=$GUARDIAN_PK
SUPPLIER_ADDRESS=$SUPPLIER
NEW_SUPPLIER_ADDRESS=$NEW_SUPPLIER
CANARY_ADDRESS=$CANARY
ENV
echo "AgentVault local : $VAULT  -> $OUT_ENV écrit"
