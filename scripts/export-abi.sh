#!/usr/bin/env bash
# Compile le contrat et copie son ABI dans agent/abi/ (le serveur de production n'a pas besoin de Foundry).
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.foundry/bin:$PATH"
(cd contracts && forge build -q)
python3 -c "import json;d=json.load(open('contracts/out/AgentVault.sol/AgentVault.json'));json.dump(d['abi'],open('agent/abi/AgentVault.json','w'),indent=1)"
echo "ABI exportée -> agent/abi/AgentVault.json"
