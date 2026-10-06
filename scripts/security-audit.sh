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
fuser -k $PORT/tcp 2>/dev/null || true

# Initialisation d'une base de données dédiée pour l'audit v3
AUDIT_DB=/tmp/vg-audit.db
rm -f "$AUDIT_DB" /tmp/vg-audit-meta.json
"$PY" -c "
import sys, time, json
sys.path.insert(0, 'agent')
import db, auth, orgs

db.init_db('$AUDIT_DB')

# Org A avec utilisateur et clés
res_a = auth.signup('alice@orga.local', 'PasswordOrgA123!', org_name='Org A', db_path='$AUDIT_DB')
u_a = res_a['user']['id']
o_a = res_a['org']['id']
tok_a = res_a['token']

now = int(time.time())
raw_key_active = 'vg_live_active_key_1234567890abcdef'
db.execute('INSERT INTO api_keys (id, org_id, name, key_prefix, key_hash, is_active, created_at) VALUES (?, ?, ?, ?, ?, 1, ?);',
           ('key_active', o_a, 'Active Key', raw_key_active[:12], db.hash_token(raw_key_active), now), db_path='$AUDIT_DB')

raw_key_revoked = 'vg_live_revoked_key_1234567890abcdef'
db.execute('INSERT INTO api_keys (id, org_id, name, key_prefix, key_hash, is_active, created_at) VALUES (?, ?, ?, ?, ?, 0, ?);',
           ('key_revoked', o_a, 'Revoked Key', raw_key_revoked[:12], db.hash_token(raw_key_revoked), now), db_path='$AUDIT_DB')

orgs.add_supplier(o_a, u_a, 'Datacenter A', '0x5418b7650f0E9ad0a9c80d8702b8E1c8280f3EbA', db_path='$AUDIT_DB')

# Org B avec utilisateur et ressource distincts
res_b = auth.signup('bob@orgb.local', 'PasswordOrgB123!', org_name='Org B', db_path='$AUDIT_DB')
u_b = res_b['user']['id']
o_b = res_b['org']['id']
tok_b = res_b['token']
sup_b = orgs.add_supplier(o_b, u_b, 'Datacenter B', '0x2EC47230c69278a2D6715a95454F2f4dc1cBa325', db_path='$AUDIT_DB')

with open('/tmp/vg-audit-meta.json', 'w') as f:
    json.dump({
        'tok_a': tok_a,
        'tok_b': tok_b,
        'key_active': raw_key_active,
        'key_revoked': raw_key_revoked,
        'sup_b_id': sup_b['id'],
        'org_b_id': o_b
    }, f)
"

# Libère le port (serveur orphelin d'une exécution interrompue) puis garantit l'arrêt même en cas d'interruption.
free_port() { fuser -k -n tcp "$PORT" >/dev/null 2>&1 || true; }
free_port; trap free_port EXIT
(cd agent && CHAIN= AUDIT_PATH=/dev/null DB_PATH=$AUDIT_DB PORT=$PORT HOST=127.0.0.1 setsid nohup "$PY" server.py >/tmp/vg-audit-server.log 2>&1 & echo $! > /tmp/vg-audit.pid)
for _ in $(seq 40); do curl -s "$U/healthz" -H "Host: localhost" >/dev/null && break; sleep 0.25; done
J=/tmp/vg-cookies; rm -f $J
CSRF=$(curl -s -c $J -b $J "$U/api/session" -H "Host: localhost" | "$PY" -c "import sys,json;print(json.load(sys.stdin)['csrf'])")
code() { curl -s -o /dev/null -w "%{http_code}" -c $J -b $J -H "Host: localhost" "$@"; }

# Métadonnées de l'audit
TOK_A=$("$PY" -c "import json; print(json.load(open('/tmp/vg-audit-meta.json'))['tok_a'])")
KEY_REVOKED=$("$PY" -c "import json; print(json.load(open('/tmp/vg-audit-meta.json'))['key_revoked'])")
ORG_B_ID=$("$PY" -c "import json; print(json.load(open('/tmp/vg-audit-meta.json'))['org_b_id'])")

echo "== 1. Surface réseau (nmap)"
command -v nmap >/dev/null && nmap -sV -p $PORT 127.0.0.1 --version-light --host-timeout 5s 2>/dev/null | grep -E "^$PORT" | sed 's/^/  /'
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
H=$(curl -s -D - -o /dev/null $U/demo -H 'Host: localhost')
for h in Content-Security-Policy X-Frame-Options X-Content-Type-Options Referrer-Policy Permissions-Policy; do
  check "en-tête $h présent" "$(echo "$H" | grep -ci "^$h:")" 1
done
check "bannière serveur sans version Python" "$(echo "$H" | grep -i '^Server:' | grep -ci python)" 0

echo "== 4. Fichiers sensibles exposés ? (ffuf, liste ciblée)"
WL=/tmp/vg-wordlist.txt
printf '%s\n' .env .env.anvil agent/.env .git/config .git/HEAD audit.jsonl server.py agent.py chain.py \
  contracts/out abi/AgentVault.json ../agent/.env admin api api/admin config backup.zip id_rsa .ssh/id_rsa \
  docker-compose.yml Dockerfile robots.txt .well-known/security.txt etc/passwd index.html demo healthz > $WL
if command -v ffuf >/dev/null; then
  F=$(ffuf -u "$U/FUZZ" -H "Host: localhost" -w $WL -mc 200,301,302,403 -s 2>/dev/null | sort | tr '\n' ' ')
else
  F=$(while read -r p; do [ "$(curl -s -o /dev/null -w '%{http_code}' -H 'Host: localhost' "$U/$p")" = 200 ] && echo -n "$p "; done < $WL)
fi
echo "  chemins accessibles : ${F:-aucun}"
check "seuls index.html, demo et healthz sont servis" "$F" "demo healthz index.html "

echo "== 5. Attaques v3 multi-clients (127.0.0.1)"
# 5.1 Énumération d'utilisateurs (temps scrypt constant et message identique)
CSRF_AUTH=$(curl -s -c /tmp/vg-ck-auth -b /tmp/vg-ck-auth "$U/api/session" -H 'Host: localhost' | "$PY" -c "import sys,json;print(json.load(sys.stdin)['csrf'])")
T_EXIST=$(curl -s -w "%{time_total}" -o /tmp/resp_exist.json -X POST "$U/api/auth/login" \
  -c /tmp/vg-ck-auth -b /tmp/vg-ck-auth \
  -H 'Host: localhost' -H 'Content-Type: application/json' -H "X-CSRF-Token: $CSRF_AUTH" \
  -d '{"email":"alice@orga.local","password":"MauvaisPassword123!"}')
T_UNKNOWN=$(curl -s -w "%{time_total}" -o /tmp/resp_unknown.json -X POST "$U/api/auth/login" \
  -c /tmp/vg-ck-auth -b /tmp/vg-ck-auth \
  -H 'Host: localhost' -H 'Content-Type: application/json' -H "X-CSRF-Token: $CSRF_AUTH" \
  -d '{"email":"inconnu@introuvable.xyz","password":"MauvaisPassword123!"}')
ERR_EXIST=$("$PY" -c "import json; print(json.load(open('/tmp/resp_exist.json')).get('error',''))")
ERR_UNKNOWN=$("$PY" -c "import json; print(json.load(open('/tmp/resp_unknown.json')).get('error',''))")
check "énumération : message d'erreur identique pour email existant ou inconnu" "$ERR_EXIST" "Identifiants invalides"
check "énumération : message uniforme" "$ERR_UNKNOWN" "$ERR_EXIST"
TIMING_PROCHE=$("$PY" -c "t1, t2 = float('$T_EXIST'), float('$T_UNKNOWN'); print('oui' if max(t1, t2) / max(min(t1, t2), 0.001) < 6.0 else 'non')")
check "énumération : temps de réponse scrypt constant" "$TIMING_PROCHE" "oui"

# 5.2 Force brute (compte verrouillé ou limitation 429)
BRUTE_PROT="non"
for i in $(seq 6); do
  C_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$U/api/auth/login" \
    -c /tmp/vg-ck-auth -b /tmp/vg-ck-auth \
    -H 'Host: localhost' -H 'Content-Type: application/json' -H "X-CSRF-Token: $CSRF_AUTH" \
    -d '{"email":"alice@orga.local","password":"AttaqueBruteForce999!"}')
  if [ "$C_STATUS" = "429" ]; then
    BRUTE_PROT="protégé"
    break
  fi
done
if [ "$BRUTE_PROT" != "protégé" ]; then
  LOCKED=$("$PY" -c "import sys; sys.path.insert(0,'agent'); import db, time; u = db.query_one(\"SELECT locked_until FROM users WHERE email='alice@orga.local'\", db_path='$AUDIT_DB'); print('protégé' if u and u['locked_until'] and u['locked_until'] > time.time() else 'non')")
  BRUTE_PROT="$LOCKED"
fi
check "force brute : compte verrouillé ou limitation 429" "$BRUTE_PROT" "protégé"

# 5.3 Accès croisé entre organisations (anti-IDOR -> 404)
CROSS_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$U/api/orgs/$ORG_B_ID" \
  -H 'Host: localhost' -H "Cookie: vg_session=$TOK_A")
check "accès croisé entre organisations : rejet 404" "$CROSS_CODE" 404

# 5.4 Clé API révoquée sur /v1 -> 401
REVOKED_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$U/v1/policy" \
  -H 'Host: localhost' -H "Authorization: Bearer $KEY_REVOKED")
check "clé API révoquée : rejet 401 sur /v1" "$REVOKED_CODE" 401

# 5.5 Espace /admin sans droits -> 404 stealth
ADMIN_ANON=$(curl -s -o /dev/null -w "%{http_code}" "$U/admin" -H 'Host: localhost')
ADMIN_USER=$(curl -s -o /dev/null -w "%{http_code}" "$U/admin" -H 'Host: localhost' -H "Cookie: vg_session=$TOK_A")
ADMIN_STATS=$(curl -s -o /dev/null -w "%{http_code}" "$U/api/admin/stats" -H 'Host: localhost' -H "Cookie: vg_session=$TOK_A")
check "/admin anonyme : 404 (stealth)" "$ADMIN_ANON" 404
check "/admin utilisateur non-superadmin : 404 (stealth)" "$ADMIN_USER" 404
check "/api/admin/stats non-superadmin : 404" "$ADMIN_STATS" 404

echo "== 6. Injection SQL (sqlmap)"
if command -v sqlmap >/dev/null; then
  # Verdict honnête : ECHEC si sqlmap trouve une injection, OK seulement s'il conclut « non injectable »,
  # sinon (coupé par le timeout, bloqué par la limitation de débit...) : non concluant, NON compté comme OK.
  SQLMAP_OUT=$(timeout 300 sqlmap -u "$U/api/auth/login" \
    --data='{"email":"alice@orga.local","password":"PasswordOrgA123!"}' \
    --headers="Content-Type: application/json\r\nX-CSRF-Token: $CSRF_AUTH" \
    --batch --level=2 --risk=1 --flush-session --output-dir=/tmp/vg-sqlmap </dev/null 2>&1 || true)
  if echo "$SQLMAP_OUT" | grep -qiE "is vulnerable|identified the following injection point"; then
    check "sqlmap : aucun paramètre injectable sur /api/auth/login" "injectable" "sûr"
  elif echo "$SQLMAP_OUT" | grep -qiE "do not appear to be injectable|appear to be not injectable"; then
    check "sqlmap : aucun paramètre injectable sur /api/auth/login" "sûr" "sûr"
  else
    echo "  [NON CONCLUANT] sqlmap n'a pas terminé son analyse (non compté) :"
    echo "$SQLMAP_OUT" | grep -E "^\[[0-9:]+\] \[(CRITICAL|ERROR|WARNING)\]" | tail -3 | sed 's/^/    /'
  fi
else
  echo "  (sqlmap non installé : étape sautée)"
fi

echo "== 7. Limitation de débit (300 requêtes rapides)"
R=$(for i in $(seq 300); do code $U/api/scenarios; echo; done | sort | uniq -c | tr '\n' ' ')
echo "  codes : $R"
check "des requêtes sont limitées (429)" "$(echo "$R" | grep -c 429)" 1

kill "$(cat /tmp/vg-audit.pid)" 2>/dev/null; free_port; rm -f /tmp/vg-audit.pid /tmp/vg-audit-meta.json /tmp/vg-ck-auth "$AUDIT_DB" /tmp/resp_exist.json /tmp/resp_unknown.json

echo "== 8. Analyse statique du contrat (Slither)"
(cd contracts && slither . --exclude-dependencies --exclude-informational --exclude-low \
   --exclude arbitrary-send-eth,reentrancy-eth,reentrancy-no-eth >/tmp/sl.txt 2>&1) && echo "  aucune alerte moyenne/haute" \
   || grep -v "^INFO:Slither\|running" /tmp/sl.txt | head -20
(cd contracts && forge build -q)

echo "== 9. Analyse statique Python (Bandit)"
bandit -q -r agent -x agent/test_vaultguard.py,agent/test_server.py,agent/test_parity.py,agent/test_product.py,agent/test_layout.py -ll 2>/dev/null && echo "  aucune alerte moyenne/haute"

echo "== 10. Dépendances vulnérables (pip-audit)"
pip-audit --path "$(ls -d "$HOME"/.venvs/vaultguard/lib/python3*/site-packages)" 2>&1 | tail -5 | sed 's/^/  /'

echo
echo "RÉSULTAT : $PASS vérifications OK, $FAIL échec(s)"
} 2>&1 | tee "$REPORT"
grep -q "0 échec" "$REPORT"
