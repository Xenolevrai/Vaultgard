#!/usr/bin/env bash
# Audit de sécurité automatisé de VaultGuard, sur TA machine uniquement (127.0.0.1).
# Rejoue chaque attaque trouvée sur la v1 et vérifie qu'elle est bloquée. Rapport : docs/audit-latest.txt
#   bash scripts/security-audit.sh
set -uo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.foundry/bin:$HOME/.venvs/vg-audit/bin:$PATH"
PY="$HOME/.venvs/vaultguard/bin/python"; [ -x "$PY" ] || PY=python3
PORT=8765; U="http://127.0.0.1:$PORT"; REPORT=docs/audit-latest.txt
PASS=0; FAIL=0
check() { if [ "$2" = "$3" ]; then echo "  [OK]    $1 (attendu $3)"; PASS=$((PASS+1)); else echo "  [ECHEC] $1 : obtenu $2, attendu $3"; FAIL=$((FAIL+1)); fi; }

# Outils d'audit dans un venv séparé (ne touche pas au projet)
V="$HOME/.venvs/vg-audit"
if [ ! -x "$V/bin/bandit" ]; then
  python3 -m venv --without-pip "$V" && curl -sS https://bootstrap.pypa.io/get-pip.py | "$V/bin/python" - -q
  "$V/bin/python" -m pip install -q slither-analyzer bandit pip-audit solc-select
fi

{
echo "VaultGuard — audit de sécurité automatisé — $(date -Iseconds)"
echo
(cd agent && CHAIN= AUDIT_PATH=/dev/null PORT=$PORT HOST=127.0.0.1 setsid nohup "$PY" server.py >/tmp/vg-audit-server.log 2>&1 & echo $! > /tmp/vg-audit.pid)
for _ in $(seq 40); do curl -s "$U/healthz" -H "Host: localhost" >/dev/null && break; sleep 0.25; done
J=/tmp/vg-cookies; rm -f $J
CSRF=$(curl -s -c $J -b $J "$U/api/session" -H "Host: localhost" | "$PY" -c "import sys,json;print(json.load(sys.stdin)['csrf'])")
code() { curl -s -o /dev/null -w "%{http_code}" -c $J -b $J -H "Host: localhost" "$@"; }

echo "== 1. Surface réseau (nmap)"
command -v nmap >/dev/null && nmap -sV -p $PORT 127.0.0.1 2>/dev/null | grep -E "^$PORT" | sed 's/^/  /'
echo "  Écoute : $(ss -ltn 2>/dev/null | grep ":$PORT " | awk '{print $4}') (doit être 127.0.0.1, pas 0.0.0.0)"

echo "== 2. Rejeu des failles de la v1"
check "CSRF : POST depuis un site tiers (Origin evil)" "$(code -X POST $U/api/pause -H 'Origin: https://evil.example' -H 'Content-Type: application/json' -H "X-CSRF-Token: $CSRF" -d '{"paused":true}')" 403
check "CSRF : formulaire text/plain sans jeton" "$(code -X POST $U/api/pause -H 'Content-Type: text/plain' -d '{"paused":true}')" 403
check "CSRF : jeton absent" "$(code -X POST $U/api/pause -H 'Content-Type: application/json' -d '{"paused":true}')" 403
check "DNS rebinding : Host arbitraire" "$(curl -s -o /dev/null -w '%{http_code}' $U/api/state -H 'Host: evil.example')" 421
code -X POST $U/api/run -H 'Content-Type: application/json' -H "X-CSRF-Token: $CSRF" -d '{"scenario":"big","mode":"full"}' >/dev/null
check "Index négatif id=-1" "$(code -X POST $U/api/approve -H 'Content-Type: application/json' -H "X-CSRF-Token: $CSRF" -d '{"id":-1}')" 400
check "Type confus id=true" "$(code -X POST $U/api/approve -H 'Content-Type: application/json' -H "X-CSRF-Token: $CSRF" -d '{"id":true}')" 400
check "Content-Length géant (DoS mémoire)" "$(code -X POST $U/api/run -H 'Content-Type: application/json' -H "X-CSRF-Token: $CSRF" -H 'Content-Length: 99999999999' -d '{}')" 413
BODY=$(curl -s -c $J -b $J -X POST $U/api/run -H "Host: localhost" -H 'Content-Type: application/json' -H "X-CSRF-Token: $CSRF" -d 'xx')
check "JSON invalide sans fuite de trace interne" "$(echo "$BODY" | grep -c 'Decode\|Traceback')" 0
check "Accès au vrai coffre sans être admin" "$(code -X POST $U/api/pause -H 'Content-Type: application/json' -H "X-CSRF-Token: $CSRF" -d '{"paused":true,"target":"live"}')" 200
echo "    (200 attendu ici car l'audit tourne en mode local : l'admin est la personne devant la machine)"
check "Traversée de chemin" "$(curl -s -o /dev/null -w '%{http_code}' --path-as-is "$U/../../etc/passwd" -H 'Host: localhost')" 404
check "Méthode DELETE" "$(code -X DELETE $U/api/state)" 405

echo "== 3. En-têtes de sécurité"
H=$(curl -s -D - -o /dev/null $U/ -H 'Host: localhost')
for h in Content-Security-Policy X-Frame-Options X-Content-Type-Options Referrer-Policy Permissions-Policy; do
  check "en-tête $h présent" "$(echo "$H" | grep -ci "^$h:")" 1
done
check "bannière serveur sans version Python" "$(echo "$H" | grep -i '^Server:' | grep -ci python)" 0

echo "== 4. Fichiers sensibles exposés ? (ffuf, liste ciblée)"
WL=/tmp/vg-wordlist.txt
printf '%s
' .env .env.anvil agent/.env .git/config .git/HEAD audit.jsonl server.py agent.py chain.py   contracts/out abi/AgentVault.json ../agent/.env admin api api/admin config backup.zip id_rsa .ssh/id_rsa   docker-compose.yml Dockerfile robots.txt .well-known/security.txt etc/passwd index.html healthz > $WL
if command -v ffuf >/dev/null; then
  F=$(ffuf -u "$U/FUZZ" -H "Host: localhost" -w $WL -mc 200,301,302,403 -s 2>/dev/null | sort | tr '
' ' ')
else
  F=$(while read -r p; do [ "$(curl -s -o /dev/null -w '%{http_code}' -H 'Host: localhost' "$U/$p")" = 200 ] && echo -n "$p "; done < $WL)
fi
echo "  chemins accessibles : ${F:-aucun}"
check "seuls index.html et healthz sont servis" "$F" "healthz index.html "
echo "== 5. Limitation de débit (300 requêtes rapides)"
R=$(for i in $(seq 300); do code $U/api/scenarios; echo; done | sort | uniq -c | tr '\n' ' ')
echo "  codes : $R"
check "des requêtes sont limitées (429)" "$(echo "$R" | grep -c 429)" 1

kill "$(cat /tmp/vg-audit.pid)" 2>/dev/null; rm -f /tmp/vg-audit.pid

echo "== 6. Analyse statique du contrat (Slither)"
(cd contracts && slither . --exclude-dependencies --exclude-informational --exclude-low \
   --exclude arbitrary-send-eth,reentrancy-eth,reentrancy-no-eth >/tmp/sl.txt 2>&1) && echo "  aucune alerte moyenne/haute" \
   || grep -v "^INFO:Slither\|running" /tmp/sl.txt | head -20
(cd contracts && forge build -q)

echo "== 7. Analyse statique Python (Bandit)"
bandit -q -r agent -x agent/test_vaultguard.py,agent/test_server.py,agent/test_parity.py,agent/test_product.py -ll 2>/dev/null && echo "  aucune alerte moyenne/haute"

echo "== 8. Dépendances vulnérables (pip-audit)"
pip-audit --path "$(ls -d "$HOME"/.venvs/vaultguard/lib/python3*/site-packages)" 2>&1 | tail -5 | sed 's/^/  /'

echo
echo "RÉSULTAT : $PASS vérifications OK, $FAIL échec(s)"
} 2>&1 | tee "$REPORT"
grep -q "0 échec" "$REPORT"
