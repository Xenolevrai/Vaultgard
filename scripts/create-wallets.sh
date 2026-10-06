#!/usr/bin/env bash
# Crée les wallets de TEST (Owner, Agent, Guardian, Supplier, nouveau fournisseur, appât) dans agent/.env.
# Les clés privées ne sont jamais affichées. Relançable : un wallet déjà présent n'est jamais remplacé.
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.foundry/bin:$PATH"
ENV="${ENV_FILE:-agent/.env}"
[ -f "$ENV" ] || cp .env.example "$ENV"
chmod 600 "$ENV" 2>/dev/null || true

get() { grep -E "^$1=" "$ENV" | head -1 | cut -d= -f2-; }
put() { if grep -qE "^$1=" "$ENV"; then sed -i "s|^$1=.*|$1=$2|" "$ENV"; else echo "$1=$2" >> "$ENV"; fi; }
new_wallet() {
  local out; out=$(cast wallet new 2>&1)
  WADDR=$(echo "$out" | grep -i '^Address' | grep -oE '0x[0-9a-fA-F]{40}')
  WKEY=$(echo "$out" | grep -i '^Private key' | grep -oE '0x[0-9a-fA-F]{64}')
}

for role in OWNER AGENT GUARDIAN; do
  if [ -z "$(get ${role}_PRIVATE_KEY)" ]; then new_wallet; put "${role}_PRIVATE_KEY" "$WKEY"; echo "Wallet $role créé."
  else echo "Wallet $role déjà présent, conservé."; fi
done
if [ -z "$(get SUPPLIER_ADDRESS)" ]; then
  new_wallet; put SUPPLIER_ADDRESS "$WADDR"; put SUPPLIER_PRIVATE_KEY "$WKEY"; echo "Wallet SUPPLIER créé."
else echo "Wallet SUPPLIER déjà présent, conservé."; fi
# Nouveau fournisseur et appât : seule l'adresse compte (la clé de l'appât est jetée : personne ne peut la dépenser).
for role in NEW_SUPPLIER CANARY; do
  if [ -z "$(get ${role}_ADDRESS)" ]; then new_wallet; put "${role}_ADDRESS" "$WADDR"; echo "Adresse $role créée."
  else echo "Adresse $role déjà présente, conservée."; fi
done

echo
echo "Adresses publiques (partageables, PAS les clés) :"
echo "  Owner    : $(cast wallet address "$(get OWNER_PRIVATE_KEY)")   <- à remplir au faucet"
echo "  Agent    : $(cast wallet address "$(get AGENT_PRIVATE_KEY)")"
echo "  Guardian : $(cast wallet address "$(get GUARDIAN_PRIVATE_KEY)")"
echo "  Supplier : $(get SUPPLIER_ADDRESS)"
echo "  Nouveau  : $(get NEW_SUPPLIER_ADDRESS)"
echo "  Appât    : $(get CANARY_ADDRESS)"
echo
echo "Clés privées enregistrées dans $ENV (ignoré par git, droits 600). Ne les copie nulle part ailleurs."
