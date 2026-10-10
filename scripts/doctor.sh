#!/usr/bin/env bash
# Diagnostic complet : outils, configuration, sécurité du .env, réseau, soldes, cohérence du contrat déployé.
#   bash scripts/doctor.sh            (utilise agent/.env)
set -uo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.foundry/bin:$PATH"
ENV="${ENV_FILE:-agent/.env}"
PY="$HOME/.venvs/vaultguard/bin/python"
OK=0; WARN=0; KO=0
ok()   { echo "  [OK]    $*"; OK=$((OK+1)); }
warn() { echo "  [ATTN]  $*"; WARN=$((WARN+1)); }
ko()   { echo "  [ERREUR] $*"; KO=$((KO+1)); }

echo "== Outils"
command -v forge >/dev/null && ok "Foundry $(forge --version 2>/dev/null | head -1 | awk '{print $3}')" || ko "Foundry absent -> bash scripts/setup.sh"
[ -x "$PY" ] && ok "venv Python ($("$PY" --version 2>&1))" || ko "venv absent -> bash scripts/setup.sh"
[ -x "$PY" ] && "$PY" -c "import web3, dotenv" 2>/dev/null && ok "web3 + python-dotenv installés" || ko "dépendances Python manquantes -> bash scripts/setup.sh"
[ -d contracts/lib/forge-std ] && ok "forge-std présent" || ko "forge-std absent -> bash scripts/setup.sh"
[ -f agent/abi/AgentVault.json ] && ok "ABI exportée" || warn "ABI absente -> bash scripts/export-abi.sh"

echo "== Configuration ($ENV)"
if [ ! -f "$ENV" ]; then ko "$ENV absent -> bash scripts/create-wallets.sh"; else
  set -a; source "$ENV"; set +a
  PERM=$(stat -c %a "$ENV" 2>/dev/null)
  case "$PERM" in 600|400) ok "droits du .env : $PERM";; *) warn "droits du .env : $PERM (sur Windows /mnt/c c'est normal ; sur un serveur : chmod 600)";; esac
  git check-ignore -q "$ENV" 2>/dev/null && ok ".env ignoré par git" || warn ".env non ignoré par git (ou pas de dépôt git)"
  for v in OWNER_PRIVATE_KEY AGENT_PRIVATE_KEY GUARDIAN_PRIVATE_KEY SUPPLIER_ADDRESS NEW_SUPPLIER_ADDRESS CANARY_ADDRESS; do
    [ -n "${!v:-}" ] && ok "$v défini" || warn "$v vide -> bash scripts/create-wallets.sh"
  done
  if [ -n "${OWNER_PRIVATE_KEY:-}" ] && [ -n "${AGENT_PRIVATE_KEY:-}" ]; then
    [ "$OWNER_PRIVATE_KEY" != "$AGENT_PRIVATE_KEY" ] && ok "owner et agent sont des clés différentes" || ko "owner = agent : l'agent pourrait changer les règles !"
  fi
  if grep -qE '^ANTHROPIC_API_KEY=sk-' "$ENV"; then ok "clé LLM présente (mode --llm possible)"; else echo "  [info]  pas de clé LLM : agent scripté (suffisant pour la démo)"; fi
  [ -n "${ADMIN_PASSWORD_HASH:-}" ] && ok "mot de passe admin configuré (production)" || echo "  [info]  pas de mot de passe admin : mode local (admin = cette machine)"
  [ "${HOST:-127.0.0.1}" = "0.0.0.0" ] && [ -z "${ADMIN_PASSWORD_HASH:-}" ] && ko "HOST=0.0.0.0 sans mot de passe : actions admin désactivées"
fi

echo "== Réseau et contrat"
RPC="${RPC_URL:-https://api.avax-test.network/ext/bc/C/rpc}"
CID=$(env -u CHAIN cast chain-id --rpc-url "$RPC" 2>/dev/null)
if [ -z "$CID" ]; then ko "RPC injoignable : $RPC (Wi-Fi ? -> la démo hors-ligne marche quand même)"; else
  ok "RPC joignable : chainId $CID"
  [ "$CID" = 43114 ] && warn "MAINNET : vrais fonds !"
  if [ -n "${OWNER_PRIVATE_KEY:-}" ]; then
    O=$(cast wallet address "$OWNER_PRIVATE_KEY"); B=$(env -u CHAIN cast balance "$O" --ether --rpc-url "$RPC")
    echo "  [info]  Owner $O : $B AVAX"
  fi
  if [ -n "${AGENT_PRIVATE_KEY:-}" ]; then
    A=$(cast wallet address "$AGENT_PRIVATE_KEY"); BA=$(env -u CHAIN cast balance "$A" --rpc-url "$RPC")
    [ "$BA" != "0" ] && ok "l'agent a du gas ($(cast from-wei "$BA") AVAX)" || warn "l'agent n'a pas de gas pour payer ses transactions"
  fi
  if [ -n "${VAULT_ADDRESS:-}" ]; then
    CODE=$(env -u CHAIN cast code "$VAULT_ADDRESS" --rpc-url "$RPC" 2>/dev/null)
    if [ "${#CODE}" -gt 4 ]; then
      ok "contrat présent à $VAULT_ADDRESS"
      C() { env -u CHAIN cast call "$VAULT_ADDRESS" "$1" --rpc-url "$RPC" 2>/dev/null | tr 'A-F' 'a-f'; }
      lc() { echo "$1" | tr 'A-F' 'a-f'; }
      [ "$(C 'agent()(address)')" = "$(lc "$A")" ] && ok "le contrat reconnaît la clé de l'agent" || ko "agent du contrat != AGENT_PRIVATE_KEY"
      [ "$(C 'owner()(address)')" = "$(lc "$O")" ] && ok "owner du contrat = OWNER_PRIVATE_KEY" || warn "owner du contrat différent (multisig ?)"
      [ "$(C 'paused()(bool)')" = "false" ] && ok "coffre actif (non gelé)" || warn "coffre GELÉ (dégeler depuis le dashboard, onglet Coffre)"
      echo "  [info]  solde du coffre : $(env -u CHAIN cast balance "$VAULT_ADDRESS" --ether --rpc-url "$RPC") AVAX"
      [ "${CHAIN:-mock}" = web3 ] && ok "CHAIN=web3 : le dashboard utilise le vrai contrat" || warn "CHAIN=$CHAIN : mettre CHAIN=web3 pour utiliser le contrat déployé"
    else ko "aucun contrat à VAULT_ADDRESS sur ce réseau"; fi
  else warn "pas encore déployé -> faucet puis bash scripts/deploy-fuji.sh"; fi
fi

echo "== Dashboard"
if curl -s -m 2 http://localhost:8000/healthz -H "Host: localhost" | grep -q ok; then ok "dashboard en ligne sur http://localhost:8000"
else echo "  [info]  dashboard arrêté (lanceurs/LANCER-DASHBOARD.bat pour le démarrer)"; fi

echo
echo "Bilan : $OK OK, $WARN à surveiller, $KO erreur(s)"
[ $KO = 0 ]
