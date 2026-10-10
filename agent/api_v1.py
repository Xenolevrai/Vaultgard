"""api_v1.py — API REST v1 pour les agents IA (VaultGuard v3).

Exigences :
  - Authentification Bearer <clé> : empreinte SHA-256 en base, comparaison en temps constant.
  - Clé révoquée, inactive ou en quarantaine = 401 avec exactement le même message.
  - Org suspendue = 403 sur /v1.
  - Pas de cookie donc pas de CSRF, mais Host, taille du corps et en-têtes de sécurité préservés.
  - Limitation de débit PAR CLÉ (en plus de la limitation par IP).
  - Mise à jour de last_used_at à chaque appel réussi.
  - POST /v1/payments : montant en AVAX chaîne converti en gwei entier sans flottant (max 9 décimales, borné).
  - Réutilisation stricte de firewall.py (carnet = fournisseurs actifs après délai, appât, historique, anomalie, doubles paiements).
  - Simulation isolée et persistante par organisation (org_vault_states).
  - Quarantaine automatique de la clé : circuit breaker (N blocages en 1 h) ou premier appât touché.
  - GET /v1/payments/{id} (404 si autre org), GET /v1/policy (fournisseurs actifs, limites en AVAX texte).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import secrets
import threading
import time
from typing import Any

try:
    import db
    import auth
    import firewall
    import chain
except ImportError:
    from agent import db, auth, firewall, chain

log = logging.getLogger("vaultguard.api_v1")

MAX_AVAX_GWEI = 10**15  # 1 000 000 AVAX en gwei (10^15 gwei = 10^24 wei)
# Une clé en quarantaine ne redevient jamais valide toute seule : un agent compromis ne doit pas revenir
# après un délai. Levée = décision humaine (révoquer la clé, en créer une nouvelle).
QUARANTINE_SECONDS = 100 * 365 * 86400
AUTH_ERROR_MSG = "Clé API invalide ou inactive"
DUMMY_KEY_HASH = db.hash_token("vaultguard-dummy-api-key-timing-protection-2026")
EVM_ADDRESS_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")


class ApiV1Error(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class KeyRateLimiter:
    """Limitation de débit par clé API (seau à jetons thread-safe)."""

    def __init__(self, capacity: int = 60, refill_per_sec: float = 1.0):
        self.capacity = capacity
        self.refill_per_sec = refill_per_sec
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def allow(self, key_id: str) -> bool:
        now = time.time()
        with self._lock:
            if len(self._buckets) > 10_000:
                self._buckets.clear()
            tokens, last_time = self._buckets.get(key_id, (float(self.capacity), now))
            tokens = min(float(self.capacity), tokens + (now - last_time) * self.refill_per_sec)
            if tokens < 1.0:
                self._buckets[key_id] = (tokens, now)
                return False
            self._buckets[key_id] = (tokens - 1.0, now)
            return True


KEY_RATE_LIMITER = KeyRateLimiter(capacity=60, refill_per_sec=1.0)

_ORG_LOCKS: dict[str, threading.Lock] = {}
_ORG_LOCKS_GUARD = threading.Lock()


def _org_lock(org_id: str) -> threading.Lock:
    """Verrou propre à une organisation (serveur mono-processus ; en multi-processus il faudrait BEGIN IMMEDIATE)."""
    with _ORG_LOCKS_GUARD:
        return _ORG_LOCKS.setdefault(org_id, threading.Lock())


# ------------------------------------------------------------------ Validation des montants

def parse_avax_to_gwei(amount_str: Any) -> int:
    """Convertit une chaîne en AVAX ("0.05") en gwei entier (50000000) sans aucun flottant.

    Règles strictes :
      - Rejette tout type non chaîne
      - Rejette la notation scientifique ("1e18"), négatifs ("-1"), espaces ou signes
      - Maximum 9 décimales (1 gwei = 10^-9 AVAX)
      - Bornes : strictement positif et <= 1 000 000 AVAX (10^15 gwei)
    """
    if not isinstance(amount_str, str):
        raise ApiV1Error(400, "Le montant doit être une chaîne de caractères en AVAX (ex. \"0.05\")")

    clean = amount_str.strip()
    if not clean:
        raise ApiV1Error(400, "Le montant ne peut pas être vide")

    if any(c in clean for c in ("e", "E", "-", "+", " ", "\t", "\n")):
        raise ApiV1Error(400, "Format de montant invalide (notation scientifique et signes interdits)")

    if not re.fullmatch(r"[0-9]+(\.[0-9]+)?", clean):
        raise ApiV1Error(400, "Format de montant invalide (chiffres positifs attendus)")

    if "." in clean:
        int_part, frac_part = clean.split(".", 1)
        if len(frac_part) > 9:
            raise ApiV1Error(400, "Le montant ne peut pas dépasser 9 décimales (précision gwei)")
        if len(frac_part) == 0:
            raise ApiV1Error(400, "Partie décimale vide")
        padded_frac = frac_part.ljust(9, "0")
        try:
            gwei = int(int_part) * (10**9) + int(padded_frac)
        except (ValueError, OverflowError):
            raise ApiV1Error(400, "Montant trop grand")
    else:
        try:
            gwei = int(clean) * (10**9)
        except (ValueError, OverflowError):
            raise ApiV1Error(400, "Montant trop grand")

    if gwei <= 0:
        raise ApiV1Error(400, "Le montant doit être strictement supérieur à zéro")

    if gwei > MAX_AVAX_GWEI:
        raise ApiV1Error(400, f"Le montant dépasse le plafond maximal ({MAX_AVAX_GWEI // 10**9} AVAX)")

    return gwei


def gwei_to_avax_str(gwei: int) -> str:
    """Convertit un montant gwei entier en chaîne AVAX exacte sans flottant."""
    ip = gwei // 10**9
    fp = gwei % 10**9
    if fp == 0:
        return str(ip)
    return f"{ip}.{fp:09d}".rstrip("0")


# ------------------------------------------------------------------ Authentification Bearer

def authenticate_key(auth_header: str | None, ip: str | None = None,
                     db_path: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Vérifie la clé API fournie dans Authorization: Bearer <clé>.

    Sécurité :
      - Recherche par empreinte SHA-256
      - Comparaison en temps constant (hmac.compare_digest)
      - Clé révoquée, inactive ou en quarantaine = 401 avec EXACTEMENT le même message
      - Organisation suspendue = 403
      - Limitation de débit par clé (en plus de par IP)
      - Mise à jour de last_used_at
    """
    if not auth_header or not isinstance(auth_header, str):
        db.verify_token("dummy", DUMMY_KEY_HASH)
        raise ApiV1Error(401, AUTH_ERROR_MSG)

    parts = auth_header.strip().split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        db.verify_token("dummy", DUMMY_KEY_HASH)
        raise ApiV1Error(401, AUTH_ERROR_MSG)

    raw_key = parts[1].strip()
    key_hash = db.hash_token(raw_key)

    row = db.query_one("SELECT * FROM api_keys WHERE key_hash = ?;", (key_hash,), db_path=db_path)
    stored_hash = row["key_hash"] if row else DUMMY_KEY_HASH
    is_valid = hmac.compare_digest(key_hash, stored_hash)

    now = int(time.time())
    if not is_valid or not row:
        raise ApiV1Error(401, AUTH_ERROR_MSG)

    if not row["is_active"]:
        raise ApiV1Error(401, AUTH_ERROR_MSG)

    quarantined_until = row["quarantined_until"]
    if quarantined_until and quarantined_until > now:
        raise ApiV1Error(401, AUTH_ERROR_MSG)

    org = db.query_one("SELECT * FROM orgs WHERE id = ?;", (row["org_id"],), db_path=db_path)
    if not org:
        raise ApiV1Error(401, AUTH_ERROR_MSG)

    if org["is_suspended"]:
        raise ApiV1Error(403, "Organisation suspendue : accès API désactivé")

    # Mise à jour atomique de last_used_at
    db.execute("UPDATE api_keys SET last_used_at = ? WHERE id = ?;", (now, row["id"]), db_path=db_path)

    # Limitation de débit propre à la clé
    if not KEY_RATE_LIMITER.allow(row["id"]):
        raise ApiV1Error(429, "Trop de requêtes pour cette clé API, patientez un instant")

    return dict(row), dict(org)


def quarantine_key(api_key_id: str, org_id: str, reason: str, duration: int = QUARANTINE_SECONDS,
                   ip: str | None = None, db_path: str | None = None) -> None:
    """Met une clé API en quarantaine automatique et trace l'alerte d'audit."""
    now = int(time.time())
    until = now + duration
    db.execute(
        "UPDATE api_keys SET quarantined_until = ?, quarantine_reason = ? WHERE id = ?;",
        (until, reason, api_key_id),
        db_path=db_path,
    )
    auth.log_audit(
        "api_key.quarantine",
        org_id=org_id,
        api_key_id=api_key_id,
        details={"key_id": api_key_id, "reason": reason, "quarantined_until": until},
        ip=ip,
        db_path=db_path,
    )


# ------------------------------------------------------------------ Coffre simulé par organisation

def _ensure_org_vault_table(db_path: str | None = None) -> None:
    db.execute(
        "CREATE TABLE IF NOT EXISTS org_vault_states ("
        "  org_id TEXT PRIMARY KEY REFERENCES orgs(id) ON DELETE CASCADE,"
        "  balance_gwei INTEGER NOT NULL DEFAULT 10000000000 CHECK (balance_gwei >= 0),"
        "  spent_today_gwei INTEGER NOT NULL DEFAULT 0 CHECK (spent_today_gwei >= 0),"
        "  spent_day INTEGER NOT NULL DEFAULT -1,"
        "  blocked_today INTEGER NOT NULL DEFAULT 0,"
        "  blocked_day INTEGER NOT NULL DEFAULT -1,"
        "  is_paused INTEGER NOT NULL DEFAULT 0,"
        "  updated_at INTEGER NOT NULL"
        ");",
        db_path=db_path,
    )


def load_org_mock_chain(org_id: str, now_fn=None, db_path: str | None = None) -> chain.MockChain:
    """Charge le coffre simulé persistant pour l'organisation donnée (jamais partagé)."""
    _ensure_org_vault_table(db_path=db_path)
    org_row = db.query_one("SELECT * FROM orgs WHERE id = ?;", (org_id,), db_path=db_path)
    if not org_row:
        raise ApiV1Error(404, "Organisation introuvable")
    org = dict(org_row)

    suppliers = db.query_all(
        "SELECT address, active_after FROM suppliers WHERE org_id = ? AND is_active = 1;",
        (org_id,),
        db_path=db_path,
    )
    allowed = {s["address"].lower() for s in suppliers}
    active_from = {s["address"].lower(): s["active_after"] for s in suppliers}

    canary = org.get("canary_address")
    canaries = {canary.lower()} if canary else set()

    vrow = db.query_one("SELECT * FROM org_vault_states WHERE org_id = ?;", (org_id,), db_path=db_path)
    now_int = int(time.time() if now_fn is None else now_fn())
    if not vrow:
        init_balance_gwei = 10_000_000_000  # 10 AVAX
        db.execute(
            "INSERT OR IGNORE INTO org_vault_states (org_id, balance_gwei, spent_today_gwei, spent_day, blocked_today, blocked_day, is_paused, updated_at) "
            "VALUES (?, ?, 0, -1, 0, -1, 0, ?);",
            (org_id, init_balance_gwei, now_int),
            db_path=db_path,
        )
        vrow = db.query_one("SELECT * FROM org_vault_states WHERE org_id = ?;", (org_id,), db_path=db_path)

    vdict = dict(vrow) if vrow else {}
    balance = (vdict.get("balance_gwei", 10_000_000_000) / 1e9)
    spent_today = (vdict.get("spent_today_gwei", 0) / 1e9)

    return chain.MockChain(
        allowed=allowed,
        balance=balance,
        max_per_tx=org["max_tx_gwei"] / 1e9,
        daily_limit=org["max_daily_gwei"] / 1e9,
        threshold=org["human_threshold_gwei"] / 1e9,
        enforce_policy=True,
        paused=bool(vdict.get("is_paused", 0)),
        canaries=canaries,
        active_from=active_from,
        recipient_delay=org["activation_delay"],
        max_blocked_per_day=org["circuit_breaker_limit"],
        spent_today=spent_today,
        day=vdict.get("spent_day", -1),
        blocked_today=vdict.get("blocked_today", 0),
        blocked_day=vdict.get("blocked_day", -1),
        now=now_fn or time.time,
    )


def save_org_mock_chain(org_id: str, mc: chain.MockChain, db_path: str | None = None) -> None:
    """Enregistre l'état du coffre simulé dans org_vault_states."""
    _ensure_org_vault_table(db_path=db_path)
    now_int = int(mc.now())
    bal_gwei = max(0, int(round(mc.balance * 1e9)))
    spent_gwei = max(0, int(round(mc.spent_today * 1e9)))
    db.execute(
        "UPDATE org_vault_states SET balance_gwei = ?, spent_today_gwei = ?, spent_day = ?, "
        "  blocked_today = ?, blocked_day = ?, is_paused = ?, updated_at = ? WHERE org_id = ?;",
        (bal_gwei, spent_gwei, mc.day, mc.blocked_today, mc.blocked_day,
         1 if mc.paused else 0, now_int, org_id),
        db_path=db_path,
    )


# ------------------------------------------------------------------ Traitement des paiements

def handle_post_payment(body: dict[str, Any], api_key: dict[str, Any], org: dict[str, Any],
                        ip: str | None = None, db_path: str | None = None) -> tuple[int, dict[str, Any]]:
    """Gère un paiement soumis par un agent IA (POST /v1/payments)."""
    to_addr = body.get("to")
    if not isinstance(to_addr, str) or not EVM_ADDRESS_RE.match(to_addr.strip()):
        raise ApiV1Error(400, "Adresse destinataire EVM invalide (format 0x... attendu)")
    to_clean = to_addr.strip().lower()

    amount_raw = body.get("amount")
    amount_gwei = parse_avax_to_gwei(amount_raw)

    memo_raw = body.get("memo", "")
    if not isinstance(memo_raw, str):
        raise ApiV1Error(400, "Le memo doit être une chaîne de caractères")
    if len(memo_raw.encode("utf-8")) > 140:
        raise ApiV1Error(400, "Memo trop long (140 octets maximum comme le contrat)")

    user_req = body.get("user_request", "")
    if not isinstance(user_req, str):
        raise ApiV1Error(400, "user_request doit être une chaîne de caractères")
    if len(user_req) > 10_000:
        raise ApiV1Error(400, "user_request trop volumineux (10000 caractères max)")

    docs_raw = body.get("documents", [])
    if not isinstance(docs_raw, list):
        raise ApiV1Error(400, "documents doit être une liste d'objets [{source, content}]")
    if len(docs_raw) > 50:
        raise ApiV1Error(400, "Trop de documents fournis (max 50)")

    clean_docs = []
    for d in docs_raw:
        if not isinstance(d, dict):
            raise ApiV1Error(400, "Chaque élément de documents doit être un objet JSON")
        src = d.get("source", "")
        cnt = d.get("content", "")
        if not isinstance(src, str) or not isinstance(cnt, str):
            raise ApiV1Error(400, "Les champs source et content d'un document doivent être des chaînes")
        if len(src) > 256 or len(cnt) > 32_000:
            raise ApiV1Error(400, "Taille d'un document trop importante")
        file_hash = d.get("file_sha256", "")
        if not isinstance(file_hash, str) or (file_hash and not SHA256_RE.match(file_hash)):
            raise ApiV1Error(400, "file_sha256 doit être une empreinte SHA-256 (64 caractères hexadécimaux)")
        clean_docs.append({"source": src, "content": cnt, "file_sha256": file_hash.lower()})

    invoice = _clean_invoice(body.get("invoice"))

    with _org_lock(org["id"]):
        # La clé a pu être mise en quarantaine ou révoquée par une requête parallèle depuis l'authentification.
        k = db.query_one("SELECT is_active, quarantined_until FROM api_keys WHERE id = ?;", (api_key["id"],), db_path=db_path)
        if not k or not k["is_active"] or (k["quarantined_until"] or 0) > int(time.time()):
            raise ApiV1Error(401, AUTH_ERROR_MSG)
        return _decide_payment(to_clean, amount_gwei, memo_raw, user_req, clean_docs, api_key, org, ip, db_path,
                               invoice=invoice)


SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_NUMBER_RE = re.compile(r"^[0-9]{1,12}(\.[0-9]{1,6})?$")


def _clean_invoice(raw: Any) -> dict[str, Any] | None:
    """Valide la facture structurée (optionnelle) : types, bornes, nombres en chaînes ASCII sans flottant."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ApiV1Error(400, "invoice doit être un objet JSON")

    def number(value: Any, name: str, required: bool = True) -> str:
        if value in (None, "") and not required:
            return ""
        if not isinstance(value, str) or not _NUMBER_RE.match(value):
            raise ApiV1Error(400, f"invoice.{name} doit être un nombre positif en chaîne (ex. \"18.00\")")
        return value

    def rows(key: str, maximum: int, fields: tuple[str, ...]) -> list[dict[str, str]]:
        items = raw.get(key, [])
        if not isinstance(items, list) or len(items) > maximum:
            raise ApiV1Error(400, f"invoice.{key} doit être une liste d'au plus {maximum} éléments")
        out = []
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("label"), str) or len(item["label"]) > 200:
                raise ApiV1Error(400, f"invoice.{key} : chaque élément a un label (200 caractères max)")
            out.append({"label": item["label"], **{f: number(item.get(f), f"{key}.{f}") for f in fields}})
        return out

    currency = raw.get("currency", "")
    if not isinstance(currency, str) or not re.match(r"^[A-Za-z]{3,5}$", currency):
        raise ApiV1Error(400, "invoice.currency doit être un code de devise (ex. \"EUR\")")
    return {
        "currency": currency.upper(),
        "total": number(raw.get("total"), "total"),
        "tax": number(raw.get("tax"), "tax", required=False),
        "factor": number(raw.get("factor"), "factor", required=False),
        "lines": rows("lines", 200, ("quantity", "unit_price")),
        "references": rows("references", 500, ("unit_price",)),
    }


def fingerprint(text: str) -> str:
    """Empreinte SHA-256 : identifie un contenu sans permettre de le retrouver."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _decide_payment(to_clean: str, amount_gwei: int, memo_raw: str, user_req: str, clean_docs: list,
                    api_key: dict[str, Any], org: dict[str, Any], ip: str | None,
                    db_path: str | None, invoice: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
    """Section critique (verrou de l'organisation tenu) : pare-feu, coffre simulé, enregistrement, quarantaine."""
    amount_avax = amount_gwei / 1e9
    # Données propres à l'organisation
    now = int(time.time())
    suppliers = db.query_all(
        "SELECT name, address, active_after, is_active FROM suppliers WHERE org_id = ? AND is_active = 1;",
        (org["id"],),
        db_path=db_path,
    )
    # Carnet = fournisseurs dont l'adresse est active (délai d'activation écoulé)
    book = {s["name"]: s["address"].lower() for s in suppliers if s["active_after"] <= now}

    canary = org.get("canary_address")
    canaries = {canary.lower()} if canary else set()

    # Historique de l'organisation pour anomalie de montant et doubles paiements
    past_rows = db.query_all(
        "SELECT recipient, amount_gwei, memo, decision FROM payments WHERE org_id = ?;",
        (org["id"],),
        db_path=db_path,
    )
    history: dict[str, list[float]] = {}
    past_invoices: set[tuple[str, str]] = set()
    for p in past_rows:
        if p["decision"] == "allowed":
            history.setdefault(p["recipient"].lower(), []).append(p["amount_gwei"] / 1e9)
        if p["decision"] in ("allowed", "pending_review"):
            for inv in firewall.INVOICE_RE.findall(p["memo"] or ""):
                past_invoices.add((p["recipient"].lower(), inv.upper()))

    # Coffre simulé ou configuration
    mock_chain = load_org_mock_chain(org["id"], db_path=db_path)

    # Initialisation du pare-feu
    fw = firewall.TxFirewall(
        address_book=book,
        chain=mock_chain,
        history=history,
        canaries=canaries,
        audit_path=None,  # tracé via auth.log_audit et la table payments
    )

    sess = firewall.FirewallSession()
    sess.paid = past_invoices
    if user_req:
        sess.add_trusted(user_req)
    # Zéro conservation : les documents sont analysés en mémoire puis oubliés. Leur nom (fichier, expéditeur)
    # ne doit pas se retrouver dans les raisons enregistrées : le pare-feu ne voit que « document N ».
    for index, d in enumerate(clean_docs, 1):
        sess.add_untrusted(f"document {index}", d["content"])
    prints = [{"n": index, "sha256": fingerprint(d["content"]), "chars": len(d["content"]),
               **({"file_sha256": d["file_sha256"]} if d.get("file_sha256") else {})}
              for index, d in enumerate(clean_docs, 1)]
    mandate_print = "sha256:" + fingerprint(user_req) if user_req else ""

    # Vérification par le pare-feu
    verdict = fw.check(sess, to_clean, amount_avax, memo_raw, invoice=invoice)

    is_canary = (to_clean in canaries) or ("canary" in verdict.codes)

    # Détermination de la décision
    if is_canary:
        decision = "blocked"
        chain_status = "blocked"
        chain_info = {"status": "Blocked", "reason": "CanaryTriggered"}
        mock_chain.set_paused(True)
        save_org_mock_chain(org["id"], mock_chain, db_path=db_path)
        quarantine_key(api_key["id"], org["id"], reason="Adresse appât touchée (honeytoken)", ip=ip, db_path=db_path)
    elif verdict.action == firewall.Action.BLOCK:
        decision = "blocked"
        chain_status = "blocked"
        chain_info = {"status": "Blocked", "reason": verdict.reasons[0]["code"] if verdict.reasons else "blocked"}
        save_org_mock_chain(org["id"], mock_chain, db_path=db_path)
    elif (verdict.action == firewall.Action.CONFIRM
          or amount_gwei >= org["human_threshold_gwei"]
          or verdict.onchain_preview.startswith("Queued")):
        decision = "pending_review"
        if org.get("network") == "mock":
            tx_res = mock_chain.request_payment(to_clean, amount_avax, verdict.memo)
            chain_status = "queued"
            chain_info = {"status": "Queued", "pending_id": tx_res.pending_id}
            save_org_mock_chain(org["id"], mock_chain, db_path=db_path)
        else:
            chain_status = "pending_review"
            chain_info = {"status": "Queued"}
    else:
        decision = "allowed"
        if org.get("network") == "mock":
            tx_res = mock_chain.request_payment(to_clean, amount_avax, verdict.memo)
            chain_status = "executed"
            chain_info = {"status": "Executed"}
            save_org_mock_chain(org["id"], mock_chain, db_path=db_path)
        else:
            # Mode Avalanche : la plateforme ne détient aucune clé, l'agent signe lui-même
            chain_status = "ready_for_signature"
            chain_info = {
                "status": "allowed",
                "action": "agent_must_sign",
                "vault_address": org.get("vault_address") or "",
            }

    # Zéro conservation : l'agent reçoit le détail complet (il cite la facture), la base n'en garde qu'une
    # version qui ne recopie rien du document.
    public_reasons = [{k: v for k, v in r.items() if k != "detail_stored"} for r in verdict.reasons]
    stored_reasons = [dict(r, detail=verdict.reasons[i].get("detail_stored", r["detail"]))
                      for i, r in enumerate(public_reasons)]

    # Persistance de la demande en base
    payment_id = "pay_" + secrets.token_hex(12)
    db.execute(
        "INSERT INTO payments (id, org_id, api_key_id, recipient, amount_gwei, memo, "
        "                      user_request, documents_json, decision, reasons_json, "
        "                      chain_status, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);",
        (payment_id, org["id"], api_key["id"], to_clean, amount_gwei, verdict.memo,
         mandate_print, json.dumps(prints), decision,
         json.dumps(stored_reasons, ensure_ascii=False), chain_status, now, now),
        db_path=db_path,
    )

    auth.log_audit(
        "payment.request",
        org_id=org["id"],
        api_key_id=api_key["id"],
        # Les empreintes entrent dans le journal chaîné : on peut prouver quel document a été jugé, sans le détenir.
        details={"payment_id": payment_id, "to": to_clean, "amount_gwei": amount_gwei, "decision": decision,
                 "documents_sha256": [p["sha256"] for p in prints], "mandate": mandate_print},
        ip=ip,
        db_path=db_path,
    )

    # Disjoncteur automatique : N blocages dans la dernière heure
    if decision == "blocked" and not is_canary:
        one_hour_ago = now - 3600
        row_cnt = db.query_one(
            "SELECT COUNT(*) AS c FROM payments WHERE api_key_id = ? AND decision = 'blocked' AND created_at >= ?;",
            (api_key["id"], one_hour_ago),
            db_path=db_path,
        )
        cnt = row_cnt["c"] if row_cnt else 0
        limit = org.get("circuit_breaker_limit", 5)
        if cnt >= limit:
            quarantine_key(
                api_key["id"],
                org["id"],
                reason=f"Disjoncteur déclenché : {cnt} paiements bloqués en 1 h (limite {limit})",
                ip=ip,
                db_path=db_path,
            )

    return 200, {
        "id": payment_id,
        "decision": decision,
        "reasons": public_reasons,
        "chain": chain_info,
        "memo": verdict.memo,
        "documents": prints,
    }


def handle_get_payment(payment_id: str, api_key: dict[str, Any], org: dict[str, Any],
                       db_path: str | None = None) -> tuple[int, dict[str, Any]]:
    """Récupère l'état d'un paiement (GET /v1/payments/{id}). Anti-IDOR : 404 si autre organisation."""
    row = db.query_one(
        "SELECT * FROM payments WHERE id = ? AND org_id = ?;",
        (payment_id, org["id"]),
        db_path=db_path,
    )
    if not row:
        raise ApiV1Error(404, "Paiement introuvable")

    try:
        reasons = json.loads(row["reasons_json"] or "[]")
    except Exception:
        reasons = []

    try:
        documents = json.loads(row["documents_json"] or "[]")
    except Exception:
        documents = []

    return 200, {
        "id": row["id"],
        "org_id": row["org_id"],
        "recipient": row["recipient"],
        "amount_gwei": row["amount_gwei"],
        "amount_avax": gwei_to_avax_str(row["amount_gwei"]),
        "memo": row["memo"],
        "user_request": row["user_request"],
        "documents": documents,
        "decision": row["decision"],
        "reasons": reasons,
        "chain_status": row["chain_status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def handle_get_policy(api_key: dict[str, Any], org: dict[str, Any],
                      db_path: str | None = None) -> tuple[int, dict[str, Any]]:
    """Récupère la politique de l'organisation et ses fournisseurs actifs (GET /v1/policy)."""
    now = int(time.time())
    suppliers = db.query_all(
        "SELECT name, address, active_after, is_active FROM suppliers WHERE org_id = ? AND is_active = 1;",
        (org["id"],),
        db_path=db_path,
    )
    active_suppliers = [
        {"name": s["name"], "address": s["address"]}
        for s in suppliers
        if s["active_after"] <= now
    ]

    max_tx = gwei_to_avax_str(org["max_tx_gwei"])
    max_daily = gwei_to_avax_str(org["max_daily_gwei"])
    human_threshold = gwei_to_avax_str(org["human_threshold_gwei"])

    return 200, {
        "network": org.get("network", "mock"),
        "vault_address": org.get("vault_address") or "",
        "limits": {
            "max_tx": max_tx,
            "max_daily": max_daily,
            "human_threshold": human_threshold,
            "max_tx_avax": max_tx,
            "max_daily_avax": max_daily,
            "human_threshold_avax": human_threshold,
            "activation_delay": org["activation_delay"],
            "circuit_breaker_limit": org["circuit_breaker_limit"],
        },
        "active_suppliers": active_suppliers,
    }


# ------------------------------------------------------------------ Dispatcher HTTP

def dispatch_v1(method: str, path: str, headers: Any, body: dict[str, Any] | None = None,
                ip: str | None = None, db_path: str | None = None) -> tuple[int, dict[str, Any]]:
    """Point d'entrée pour toutes les requêtes /v1/*."""
    try:
        auth_header = None
        if hasattr(headers, "get"):
            auth_header = headers.get("Authorization") or headers.get("authorization")
        elif isinstance(headers, dict):
            auth_header = headers.get("Authorization") or headers.get("authorization")

        api_key, org = authenticate_key(auth_header, ip=ip, db_path=db_path)

        clean_path = path.split("?", 1)[0]

        if method == "POST" and clean_path == "/v1/payments":
            if body is None:
                raise ApiV1Error(400, "Corps JSON manquant")
            return handle_post_payment(body, api_key, org, ip=ip, db_path=db_path)

        if method == "GET" and clean_path.startswith("/v1/payments/"):
            pid = clean_path[len("/v1/payments/"):].strip()
            if not pid:
                raise ApiV1Error(400, "Identifiant de paiement requis")
            return handle_get_payment(pid, api_key, org, db_path=db_path)

        if method == "GET" and clean_path == "/v1/policy":
            return handle_get_policy(api_key, org, db_path=db_path)

        raise ApiV1Error(404, "Route introuvable")

    except ApiV1Error as e:
        return e.code, {"error": e.message}
    except Exception:
        log.exception("Erreur interne api_v1")
        return 500, {"error": "Erreur interne du serveur"}
