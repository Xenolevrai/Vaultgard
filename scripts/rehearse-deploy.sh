#!/usr/bin/env bash
# Répétition générale du déploiement Fuji, mais sur une blockchain locale (anvil) : ne touche pas à agent/.env.
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.foundry/bin:$PATH"
PY="$HOME/.venvs/vaultguard/bin/python"
export ENV_FILE=agent/.env.rehearsal
RPC=http://127.0.0.1:8545

cast chain-id --rpc-url $RPC >/dev/null 2>&1 || { setsid nohup anvil --silent >/tmp/anvil.log 2>&1 </dev/null & sleep 2; }
cp .env.example "$ENV_FILE"
sed -i "s|^RPC_URL=.*|RPC_URL=$RPC|" "$ENV_FILE"
trap 'rm -f "$ENV_FILE"' EXIT

echo "== 1. Création des wallets";  bash scripts/create-wallets.sh >/dev/null && echo "   6 wallets/adresses créés"
OWNER=$(cast wallet address "$(grep ^OWNER_PRIVATE_KEY= $ENV_FILE | cut -d= -f2)")
echo "== 2. 'Faucet' local : 1 AVAX pour Owner"
cast send "$OWNER" --value 1ether --private-key 0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80 --rpc-url $RPC >/dev/null
echo "== 3. Déploiement";            bash scripts/deploy-fuji.sh
sed -i "s|^CHAIN=.*|CHAIN=web3|" "$ENV_FILE"
echo "== 4. Diagnostic";             { bash scripts/doctor.sh || true; } | grep -E "contrat|coffre|agent a du gas|Bilan"
echo "== 5. Paiement légitime via l'agent (vraie transaction)"
(cd agent && ENV_FILE=.env.rehearsal AUDIT_PATH=/dev/null "$PY" agent.py --scenario legit | grep -E "^  chain|bilan")
echo "== 6. Attaque par adresse appât (le guardian doit geler le coffre on-chain)"
(cd agent && ENV_FILE=.env.rehearsal AUDIT_PATH=/dev/null "$PY" agent.py --scenario canary | grep -E "guardian|bilan")
echo "== Répétition réussie : le même enchaînement fonctionnera sur Fuji."
