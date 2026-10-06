"""orgs.py — Espaces clients (organisations) et permissions pour VaultGuard v3.

Exigences de sécurité et d'architecture :
  - Python stdlib uniquement
  - Rôles stricts : owner > admin > approver > viewer
  - Fonction unique require_role(user_id, org_id, min_role) appelée par CHAQUE route /api/app/*
  - Anti-IDOR : chaque requête SQL filtre par org_id = organisation active de la session.
    Un identifiant appartenant à une autre organisation renvoie 404 (jamais 403, pour ne pas révéler son existence).
  - Organisation suspendue = lecture seule (toute mutation bloquée avec 403).
  - Équipe : seul l'owner peut nommer un owner ; impossible de retirer ou rétrograder le dernier owner.
  - Fournisseurs : ajout payable seulement après activation_delay (comme on-chain).
  - Politique : montants en wei entiers (jamais de flottants).
  - Journal d'audit : tracé via auth.log_audit uniquement, vérification cryptographique de la chaîne,
    export CSV protégé contre CWE-1236.
"""
from __future__ import annotations

import csv
import io
import json
import re
import secrets
import sqlite3
import time
from typing import Any

try:
    import db
    import auth
except ImportError:
    from agent import db
    from agent import auth


# ------------------------------------------------------------------ Hiérarchie des rôles

ROLE_LEVELS: dict[str, int] = {
    "viewer": 1,
    "approver": 2,
    "admin": 3,
    "owner": 4,
}

VALID_ROLES = frozenset(ROLE_LEVELS.keys())
CSV_DANGEROUS = ("=", "+", "-", "@", "\t", "\r")


class OrgError(Exception):
    def __init__(self, message: str, code: int = 400):
        super().__init__(message)
        self.message = message
        self.code = code


def csv_cell(v: Any) -> str:
    """Neutralise l'injection de formule dans Excel/LibreOffice (CWE-1236)."""
    s = "" if v is None else str(v)
    return "'" + s if s.startswith(CSV_DANGEROUS) else s


# ------------------------------------------------------------------ Contrôle d'accès strict

def require_role(user_id: str, org_id: str, min_role: str, db_path: str | None = None) -> dict[str, Any]:
    """Vérifie l'appartenance à l'organisation et le niveau de rôle minimal requis.

    Rôles : owner > admin > approver > viewer.
    - Si l'utilisateur n'est pas membre de l'organisation : renvoie 404 (anti-énumération / anti-IDOR).
    - Si le rôle est insuffisant : renvoie 403.
    """
    if min_role not in ROLE_LEVELS:
        raise OrgError("Rôle requis invalide", 400)

    member = db.query_one(
        "SELECT * FROM members WHERE user_id = ? AND org_id = ?;",
        (user_id, org_id),
        db_path=db_path,
    )
    if not member:
        # 404 strict : ne révèle pas si l'organisation existe ou non à un non-membre
        raise OrgError("Organisation introuvable", 404)

    member_role = member["role"]
    if ROLE_LEVELS.get(member_role, 0) < ROLE_LEVELS[min_role]:
        raise OrgError("Droits insuffisants pour cette action", 403)

    return dict(member)


def get_org(org_id: str, db_path: str | None = None) -> dict[str, Any]:
    """Récupère l'organisation active en base ou lève 404."""
    org = db.query_one("SELECT * FROM orgs WHERE id = ?;", (org_id,), db_path=db_path)
    if not org:
        raise OrgError("Organisation introuvable", 404)
    return dict(org)


def check_org_writable(org_id: str, db_path: str | None = None) -> dict[str, Any]:
    """Vérifie que l'organisation n'est pas suspendue (lecture seule si suspendue)."""
    org = get_org(org_id, db_path=db_path)
    if org.get("is_suspended"):
        raise OrgError("Organisation suspendue : lecture seule", 403)
    return org


# ------------------------------------------------------------------ Changement d'organisation active

def switch_org(user_id: str, new_org_id: str, session_id: str,
               ip: str | None = None, db_path: str | None = None) -> dict[str, Any]:
    """Bascule l'organisation active de la session vers une autre organisation dont l'utilisateur est membre."""
    # require_role renvoie 404 si l'utilisateur n'en est pas membre
    require_role(user_id, new_org_id, "viewer", db_path=db_path)

    now = int(time.time())
    db.execute(
        "UPDATE sessions SET active_org_id = ?, last_seen_at = ? WHERE id = ? AND user_id = ?;",
        (new_org_id, now, session_id, user_id),
        db_path=db_path,
    )
    auth.log_audit("org.switch", org_id=new_org_id, user_id=user_id,
                   details={"new_org_id": new_org_id}, ip=ip, db_path=db_path)
    return {"ok": True, "active_org_id": new_org_id}


def list_user_orgs(user_id: str, active_org_id: str | None = None,
                   db_path: str | None = None) -> list[dict[str, Any]]:
    """Retourne la liste des organisations auxquelles l'utilisateur appartient."""
    rows = db.query_all(
        "SELECT o.id, o.name, o.slug, o.network, o.is_suspended, m.role, m.created_at AS joined_at "
        "FROM members m JOIN orgs o ON m.org_id = o.id "
        "WHERE m.user_id = ? ORDER BY o.name ASC;",
        (user_id,),
        db_path=db_path,
    )
    out = []
    for r in rows:
        d = dict(r)
        d["is_active"] = (d["id"] == active_org_id)
        out.append(d)
    return out


# ------------------------------------------------------------------ 1. Vue d'ensemble

def get_overview(org_id: str, db_path: str | None = None) -> dict[str, Any]:
    """Retourne les statistiques de l'organisation : paiements du jour, bloqués, en attente, montant protégé."""
    org = get_org(org_id, db_path=db_path)
    now = int(time.time())
    start_today = now - (now % 86400)

    # Paiements du jour (depuis minuit UTC)
    today_stats = db.query_one(
        "SELECT COUNT(*) AS total_count, COALESCE(SUM(amount_gwei), 0) AS total_gwei "
        "FROM payments WHERE org_id = ? AND created_at >= ?;",
        (org_id, start_today),
        db_path=db_path,
    )

    # Compteurs par statut global
    counts = db.query_one(
        "SELECT "
        "  COALESCE(SUM(CASE WHEN decision = 'blocked' THEN 1 ELSE 0 END), 0) AS blocked_count, "
        "  COALESCE(SUM(CASE WHEN decision = 'pending_review' THEN 1 ELSE 0 END), 0) AS pending_count, "
        "  COALESCE(SUM(CASE WHEN decision = 'allowed' THEN 1 ELSE 0 END), 0) AS allowed_count, "
        "  COALESCE(SUM(CASE WHEN decision = 'blocked' THEN amount_gwei ELSE 0 END), 0) AS protected_gwei "
        "FROM payments WHERE org_id = ?;",
        (org_id,),
        db_path=db_path,
    )

    # État du coffre (org_vault_states)
    vrow = db.query_one("SELECT is_paused, balance_gwei FROM org_vault_states WHERE org_id = ?;", (org_id,), db_path=db_path)
    vault_is_paused = bool(vrow["is_paused"]) if vrow else False

    # Alertes récentes (quarantaines ou disjoncteurs ou gel)
    quarantined = db.query_all(
        "SELECT id, name, key_prefix, quarantine_reason, quarantined_until "
        "FROM api_keys WHERE org_id = ? AND quarantined_until > ?;",
        (org_id, now),
        db_path=db_path,
    )

    alerts = []
    if org.get("is_suspended"):
        alerts.append({"type": "suspended", "message": "Organisation suspendue par l'administrateur de la plateforme."})
    if vault_is_paused:
        alerts.append({"type": "vault_paused", "message": "Coffre gelé : un appât ou le disjoncteur a été touché. Dégel réservé au propriétaire avec 2FA."})
    for q in quarantined:
        alerts.append({
            "type": "quarantine",
            "message": f"Clé agent '{q['name']}' ({q['key_prefix']}...) en quarantaine : {q['quarantine_reason'] or 'activité suspecte'}"
        })

    return {
        "org": {
            "id": org["id"],
            "name": org["name"],
            "slug": org.get("slug"),
            "network": org.get("network", "mock"),
            "vault_address": org.get("vault_address"),
            "canary_address": org.get("canary_address"),
            "is_suspended": bool(org.get("is_suspended")),
            "vault_paused": vault_is_paused,
            "status": "suspended" if org.get("is_suspended") else ("paused" if vault_is_paused else "active"),
        },
        "vault": {
            "is_paused": vault_is_paused,
            "balance_gwei": vrow["balance_gwei"] if vrow else 10_000_000_000,
        },
        "stats": {
            "today_count": today_stats["total_count"] if today_stats else 0,
            "today_gwei": today_stats["total_gwei"] if today_stats else 0,
            "blocked_count": counts["blocked_count"] if counts else 0,
            "pending_count": counts["pending_count"] if counts else 0,
            "allowed_count": counts["allowed_count"] if counts else 0,
            "protected_gwei": counts["protected_gwei"] if counts else 0,
        },
        "alerts": alerts,
    }


def unpause_vault(org_id: str, user_id: str, totp_code: str,
                  ip: str | None = None, db_path: str | None = None) -> dict[str, Any]:
    """Dégèle le coffre de l'organisation après déclenchement d'un appât ou du disjoncteur.

    Garde-fous :
      - Réservé strictement au rôle owner.
      - Refusé si l'organisation est suspendue (lecture seule).
      - Ré-authentification 2FA TOTP obligatoire.
      - Mise à jour atomique UPDATE … WHERE is_paused = 1 + vérification rowcount.
      - Action tracée dans le journal d'audit avec IP.
    """
    require_role(user_id, org_id, "owner", db_path=db_path)
    check_org_writable(org_id, db_path=db_path)

    user_row = db.query_one("SELECT * FROM users WHERE id = ?;", (user_id,), db_path=db_path)
    if not user_row:
        raise OrgError("Utilisateur introuvable", 404)
    user = dict(user_row)
    if not user.get("totp_enabled") or not user.get("totp_secret"):
        raise OrgError("La double authentification (2FA) est obligatoire pour dégeler le coffre", 400)

    clean_code = str(totp_code).strip()
    if not auth.verify_totp(user["totp_secret"], clean_code, user_id=user["id"], db_path=db_path):
        raise OrgError("Code 2FA invalide ou déjà utilisé", 401)

    try:
        import api_v1
    except ImportError:
        from agent import api_v1
    now_int = int(time.time())
    with api_v1._org_lock(org_id):
        cur = db.execute(
            "UPDATE org_vault_states SET is_paused = 0, updated_at = ? WHERE org_id = ? AND is_paused = 1;",
            (now_int, org_id),
            db_path=db_path,
        )
    if cur.rowcount == 0:
        raise OrgError("Le coffre n'est pas gelé ou état inchangé", 400)

    auth.log_audit(
        "vault.unpause",
        org_id=org_id,
        user_id=user_id,
        details={"action": "unpause_vault", "previous_state": "paused"},
        ip=ip,
        db_path=db_path,
    )
    return {"ok": True, "message": "Coffre dégelé avec succès", "is_paused": False}


# ------------------------------------------------------------------ 2. Paiements

def list_payments(org_id: str, status: str | None = None, limit: int = 50,
                  db_path: str | None = None) -> list[dict[str, Any]]:
    """Liste les paiements de l'organisation active (anti-IDOR par org_id)."""
    clean_limit = max(1, min(limit, 200))
    if status and status in ("allowed", "pending_review", "blocked"):
        rows = db.query_all(
            "SELECT * FROM payments WHERE org_id = ? AND decision = ? ORDER BY created_at DESC LIMIT ?;",
            (org_id, status, clean_limit),
            db_path=db_path,
        )
    else:
        rows = db.query_all(
            "SELECT * FROM payments WHERE org_id = ? ORDER BY created_at DESC LIMIT ?;",
            (org_id, clean_limit),
            db_path=db_path,
        )

    out = []
    for r in rows:
        d = dict(r)
        try:
            d["reasons"] = json.loads(d.get("reasons_json") or "[]")
        except Exception:
            d["reasons"] = []
        try:
            d["documents"] = json.loads(d.get("documents_json") or "[]")
        except Exception:
            d["documents"] = []
        out.append(d)
    return out


def get_payment(org_id: str, payment_id: str, db_path: str | None = None) -> dict[str, Any]:
    """Récupère le détail d'un paiement en filtrant strictement par org_id (anti-IDOR -> 404)."""
    row = db.query_one(
        "SELECT * FROM payments WHERE id = ? AND org_id = ?;",
        (payment_id, org_id),
        db_path=db_path,
    )
    if not row:
        raise OrgError("Paiement introuvable", 404)

    d = dict(row)
    try:
        d["reasons"] = json.loads(d.get("reasons_json") or "[]")
    except Exception:
        d["reasons"] = []
    try:
        d["documents"] = json.loads(d.get("documents_json") or "[]")
    except Exception:
        d["documents"] = []
    return d


def approve_payment(org_id: str, user_id: str, payment_id: str,
                    ip: str | None = None, db_path: str | None = None) -> dict[str, Any]:
    """Valide un paiement en attente (réservé aux approver+)."""
    check_org_writable(org_id, db_path=db_path)
    payment = get_payment(org_id, payment_id, db_path=db_path)

    if payment["decision"] != "pending_review":
        raise OrgError("Ce paiement n'est pas en attente de validation", 400)

    now = int(time.time())
    cur = db.execute(
        "UPDATE payments SET decision = 'allowed', review_action = 'approved', reviewed_by = ?, "
        "reviewed_at = ?, chain_status = 'approved', updated_at = ? WHERE id = ? AND org_id = ? AND decision = 'pending_review';",
        (user_id, now, now, payment_id, org_id),
        db_path=db_path,
    )
    if cur.rowcount != 1:  # une autre requête simultanée a déjà tranché
        raise OrgError("Ce paiement n'est pas en attente de validation", 409)
    auth.log_audit("payment.approve", org_id=org_id, user_id=user_id,
                   details={"payment_id": payment_id, "amount_gwei": payment["amount_gwei"],
                            "recipient": payment["recipient"]},
                   ip=ip, db_path=db_path)
    return get_payment(org_id, payment_id, db_path=db_path)


def reject_payment(org_id: str, user_id: str, payment_id: str,
                   ip: str | None = None, db_path: str | None = None) -> dict[str, Any]:
    """Rejette un paiement en attente (réservé aux approver+)."""
    check_org_writable(org_id, db_path=db_path)
    payment = get_payment(org_id, payment_id, db_path=db_path)

    if payment["decision"] != "pending_review":
        raise OrgError("Ce paiement n'est pas en attente de validation", 400)

    now = int(time.time())
    cur = db.execute(
        "UPDATE payments SET decision = 'blocked', review_action = 'rejected', reviewed_by = ?, "
        "reviewed_at = ?, chain_status = 'rejected', updated_at = ? WHERE id = ? AND org_id = ? AND decision = 'pending_review';",
        (user_id, now, now, payment_id, org_id),
        db_path=db_path,
    )
    if cur.rowcount != 1:  # une autre requête simultanée a déjà tranché
        raise OrgError("Ce paiement n'est pas en attente de validation", 409)
    auth.log_audit("payment.reject", org_id=org_id, user_id=user_id,
                   details={"payment_id": payment_id, "amount_gwei": payment["amount_gwei"],
                            "recipient": payment["recipient"]},
                   ip=ip, db_path=db_path)
    return get_payment(org_id, payment_id, db_path=db_path)


# ------------------------------------------------------------------ 3. Clés API Agents

def list_api_keys(org_id: str, db_path: str | None = None) -> list[dict[str, Any]]:
    """Liste les clés API agents pour l'organisation active."""
    rows = db.query_all(
        "SELECT id, name, key_prefix, is_active, quarantined_until, quarantine_reason, last_used_at, created_at "
        "FROM api_keys WHERE org_id = ? ORDER BY created_at DESC;",
        (org_id,),
        db_path=db_path,
    )
    return [dict(r) for r in rows]


def create_api_key(org_id: str, user_id: str, name: str,
                   ip: str | None = None, db_path: str | None = None) -> dict[str, Any]:
    """Crée une nouvelle clé API agent (affichée une seule fois)."""
    check_org_writable(org_id, db_path=db_path)
    clean_name = (name or "").strip()[:80]
    if not clean_name:
        raise OrgError("Nom de la clé requis", 400)

    raw_token = f"vg_live_{secrets.token_urlsafe(32)}"
    key_prefix = raw_token[:12]
    key_hash = db.hash_token(raw_token)
    key_id = "k_" + secrets.token_hex(12)
    now = int(time.time())

    db.execute(
        "INSERT INTO api_keys (id, org_id, name, key_prefix, key_hash, is_active, created_by, created_at) "
        "VALUES (?, ?, ?, ?, ?, 1, ?, ?);",
        (key_id, org_id, clean_name, key_prefix, key_hash, user_id, now),
        db_path=db_path,
    )
    auth.log_audit("api_key.create", org_id=org_id, user_id=user_id,
                   details={"key_id": key_id, "name": clean_name, "key_prefix": key_prefix},
                   ip=ip, db_path=db_path)
    return {
        "id": key_id,
        "name": clean_name,
        "raw_key": raw_token,
        "key_prefix": key_prefix,
        "created_at": now,
    }


def revoke_api_key(org_id: str, user_id: str, key_id: str,
                   ip: str | None = None, db_path: str | None = None) -> dict[str, Any]:
    """Révoque une clé API agent (anti-IDOR -> 404 si clé appartenant à une autre org)."""
    check_org_writable(org_id, db_path=db_path)
    row = db.query_one("SELECT * FROM api_keys WHERE id = ? AND org_id = ?;", (key_id, org_id), db_path=db_path)
    if not row:
        raise OrgError("Clé API introuvable", 404)

    db.execute("UPDATE api_keys SET is_active = 0 WHERE id = ? AND org_id = ?;", (key_id, org_id), db_path=db_path)
    auth.log_audit("api_key.revoke", org_id=org_id, user_id=user_id,
                   details={"key_id": key_id, "name": row["name"]},
                   ip=ip, db_path=db_path)
    return {"ok": True, "id": key_id}


# ------------------------------------------------------------------ 4. Fournisseurs (Carnet d'adresses)

_HEX_ADDR_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")


def validate_evm_address(address: str) -> str:
    """Valide et normalise une adresse Avalanche / EVM (0x + 40 hex)."""
    if not isinstance(address, str):
        raise OrgError("L'adresse doit être une chaîne", 400)
    clean = address.strip()
    if not _HEX_ADDR_RE.match(clean):
        raise OrgError("Adresse Avalanche invalide (format 0x... attendu)", 400)
    # Minuscules : sinon la même adresse en MAJUSCULES contourne l'unicité et le délai d'activation.
    return clean.lower()


def list_suppliers(org_id: str, db_path: str | None = None) -> list[dict[str, Any]]:
    """Liste les fournisseurs avec statut d'activation (payable seulement après délai)."""
    rows = db.query_all(
        "SELECT * FROM suppliers WHERE org_id = ? ORDER BY created_at DESC;",
        (org_id,),
        db_path=db_path,
    )
    now = int(time.time())
    out = []
    for r in rows:
        d = dict(r)
        d["is_payable"] = bool(d["is_active"] and now >= d["active_after"])
        d["remaining_seconds"] = max(0, d["active_after"] - now)
        out.append(d)
    return out


def add_supplier(org_id: str, user_id: str, name: str, address: str,
                 ip: str | None = None, db_path: str | None = None) -> dict[str, Any]:
    """Ajoute un fournisseur au carnet d'adresses. Payable uniquement après activation_delay."""
    check_org_writable(org_id, db_path=db_path)
    clean_name = (name or "").strip()[:80]
    if not clean_name:
        raise OrgError("Nom du fournisseur requis", 400)
    clean_address = validate_evm_address(address)

    org = get_org(org_id, db_path=db_path)
    delay = org.get("activation_delay", 86400)
    now = int(time.time())
    active_after = now + delay
    sup_id = "sup_" + secrets.token_hex(12)

    try:
        db.execute(
            "INSERT INTO suppliers (id, org_id, name, address, active_after, is_active, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, 1, ?, ?);",
            (sup_id, org_id, clean_name, clean_address, active_after, now, now),
            db_path=db_path,
        )
    except sqlite3.IntegrityError:
        raise OrgError("Cette adresse est déjà enregistrée pour cette organisation", 409)

    auth.log_audit("supplier.create", org_id=org_id, user_id=user_id,
                   details={"supplier_id": sup_id, "name": clean_name, "address": clean_address,
                            "active_after": active_after, "delay": delay},
                   ip=ip, db_path=db_path)
    return {
        "id": sup_id,
        "name": clean_name,
        "address": clean_address,
        "active_after": active_after,
        "is_payable": False,
        "remaining_seconds": delay,
        "created_at": now,
    }


def remove_supplier(org_id: str, user_id: str, supplier_id: str,
                    ip: str | None = None, db_path: str | None = None) -> dict[str, Any]:
    """Supprime un fournisseur du carnet d'adresses (anti-IDOR -> 404)."""
    check_org_writable(org_id, db_path=db_path)
    row = db.query_one("SELECT * FROM suppliers WHERE id = ? AND org_id = ?;", (supplier_id, org_id), db_path=db_path)
    if not row:
        raise OrgError("Fournisseur introuvable", 404)

    db.execute("DELETE FROM suppliers WHERE id = ? AND org_id = ?;", (supplier_id, org_id), db_path=db_path)
    auth.log_audit("supplier.remove", org_id=org_id, user_id=user_id,
                   details={"supplier_id": supplier_id, "name": row["name"], "address": row["address"]},
                   ip=ip, db_path=db_path)
    return {"ok": True, "id": supplier_id}


# ------------------------------------------------------------------ 5. Politique (montants en gwei)

# Bornes : un compte admin volé ne doit pas pouvoir désactiver une défense (délai 0, disjoncteur 0)
# ni provoquer un dépassement d'entier (montant > 2^63). 10^15 gwei = 1 million d'AVAX.
POLICY_BOUNDS: dict[str, tuple[int, int]] = {
    "max_tx_gwei": (0, 10**15),
    "max_daily_gwei": (0, 10**15),
    "human_threshold_gwei": (0, 10**15),
    "activation_delay": (3600, 30 * 86400),
    "circuit_breaker_limit": (1, 100),
}

def get_policy(org_id: str, db_path: str | None = None) -> dict[str, Any]:
    """Retourne la politique de l'organisation (tous les montants en wei entiers)."""
    org = get_org(org_id, db_path=db_path)
    return {
        "max_tx_gwei": org["max_tx_gwei"],
        "max_daily_gwei": org["max_daily_gwei"],
        "human_threshold_gwei": org["human_threshold_gwei"],
        "activation_delay": org["activation_delay"],
        "circuit_breaker_limit": org["circuit_breaker_limit"],
        "network": org.get("network", "mock"),
        "vault_address": org.get("vault_address"),
    }


def update_policy(org_id: str, user_id: str,
                  max_tx_gwei: int | None = None,
                  max_daily_gwei: int | None = None,
                  human_threshold_gwei: int | None = None,
                  activation_delay: int | None = None,
                  circuit_breaker_limit: int | None = None,
                  ip: str | None = None, db_path: str | None = None) -> dict[str, Any]:
    """Met à jour les seuils de la politique. Refuse strictement les flottants."""
    check_org_writable(org_id, db_path=db_path)

    # Validation stricte des types et bornes : montants entiers en wei >= 0
    checks = [
        ("max_tx_gwei", max_tx_gwei),
        ("max_daily_gwei", max_daily_gwei),
        ("human_threshold_gwei", human_threshold_gwei),
        ("activation_delay", activation_delay),
        ("circuit_breaker_limit", circuit_breaker_limit),
    ]
    updates = []
    params = []
    log_details = {}

    for name, val in checks:
        if val is not None:
            if not isinstance(val, int) or isinstance(val, bool):
                raise OrgError(f"Valeur invalide pour {name} : entier requis", 400)
            lo, hi = POLICY_BOUNDS[name]
            if not lo <= val <= hi:
                raise OrgError(f"Valeur hors limites pour {name} : entre {lo} et {hi}", 400)
            log_details[name] = val

    if not log_details:
        return get_policy(org_id, db_path=db_path)

    # Cohérence avec les valeurs déjà en place : seuil humain <= plafond par paiement <= plafond journalier.
    cur = get_policy(org_id, db_path=db_path)
    tx = max_tx_gwei if max_tx_gwei is not None else cur["max_tx_gwei"]
    daily = max_daily_gwei if max_daily_gwei is not None else cur["max_daily_gwei"]
    human = human_threshold_gwei if human_threshold_gwei is not None else cur["human_threshold_gwei"]
    if not human <= tx <= daily:
        raise OrgError("Incohérent : il faut seuil de validation <= plafond par paiement <= plafond journalier", 400)

    now = int(time.time())
    db.execute(
        "UPDATE orgs SET "
        "  max_tx_gwei = COALESCE(?, max_tx_gwei), "
        "  max_daily_gwei = COALESCE(?, max_daily_gwei), "
        "  human_threshold_gwei = COALESCE(?, human_threshold_gwei), "
        "  activation_delay = COALESCE(?, activation_delay), "
        "  circuit_breaker_limit = COALESCE(?, circuit_breaker_limit), "
        "  updated_at = ? "
        "WHERE id = ?;",
        (max_tx_gwei, max_daily_gwei, human_threshold_gwei, activation_delay, circuit_breaker_limit, now, org_id),
        db_path=db_path,
    )
    auth.log_audit("policy.update", org_id=org_id, user_id=user_id,
                   details=log_details, ip=ip, db_path=db_path)
    return get_policy(org_id, db_path=db_path)


# ------------------------------------------------------------------ 6. Journal d'audit chaîné

def get_audit_trail(org_id: str, limit: int = 100, db_path: str | None = None) -> list[dict[str, Any]]:
    """Retourne les entrées d'audit de l'organisation active (anti-IDOR par org_id)."""
    clean_limit = max(1, min(limit, 500))
    rows = db.query_all(
        "SELECT a.id, a.org_id, a.user_id, a.api_key_id, a.action, a.details_json, a.ip, "
        "       a.prev_hash, a.entry_hash, a.created_at, u.email AS user_email "
        "FROM audit a LEFT JOIN users u ON a.user_id = u.id "
        "WHERE a.org_id = ? ORDER BY a.id DESC LIMIT ?;",
        (org_id, clean_limit),
        db_path=db_path,
    )
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["details"] = json.loads(d.get("details_json") or "{}")
        except Exception:
            d["details"] = {}
        out.append(d)
    return out


def verify_audit_chain_for_org(org_id: str, db_path: str | None = None) -> dict[str, Any]:
    """Vérifie toute la chaîne (elle est commune à la plateforme) mais ne révèle à un client que ses propres
    chiffres : ni le volume d'activité des autres organisations, ni l'identifiant d'un maillon qui n'est pas à lui."""
    res = verify_audit_chain(db_path=db_path)
    own = db.query_one("SELECT COUNT(*) AS c FROM audit WHERE org_id = ?;", (org_id,), db_path=db_path)["c"]
    if res["valid"]:
        return {"valid": True, "count": own,
                "message": f"Chaîne d'audit intègre ({own} entrées de votre organisation vérifiées)"}
    row = db.query_one("SELECT org_id FROM audit WHERE id = ?;", (res.get("tampered_id"),), db_path=db_path)
    out = {"valid": False, "count": own,
           "message": "Altération détectée dans le journal de la plateforme : contactez le support VaultGuard."}
    if row and row["org_id"] == org_id:
        out["tampered_id"] = res["tampered_id"]
    return out


def verify_audit_chain(db_path: str | None = None) -> dict[str, Any]:
    """Vérifie l'intégrité cryptographique complète de la chaîne du journal d'audit (usage plateforme)."""
    rows = db.query_all(
        "SELECT id, org_id, user_id, api_key_id, action, details_json, ip, prev_hash, entry_hash, created_at "
        "FROM audit ORDER BY id ASC;",
        db_path=db_path,
    )
    if not rows:
        return {"valid": True, "message": "Journal d'audit vide (intègre)", "count": 0}

    prev_hash = db.GENESIS_HASH
    for r in rows:
        # 1. Vérification du maillon précédent
        if r["prev_hash"] != prev_hash:
            return {
                "valid": False,
                "message": f"Rupture de chaîne détectée au maillon #{r['id']} : "
                           f"prev_hash attendu {prev_hash[:12]}..., trouvé {r['prev_hash'][:12]}...",
                "tampered_id": r["id"],
                "count": len(rows),
            }

        # 2. Re-calcul de l'empreinte de l'entrée
        computed = db.compute_audit_hash(
            prev_hash,
            r["created_at"],
            r["org_id"],
            r["user_id"],
            r["action"],
            r["details_json"],
            api_key_id=r["api_key_id"],
            ip=r["ip"],
        )
        if computed != r["entry_hash"]:
            return {
                "valid": False,
                "message": f"Altération détectée au maillon #{r['id']} : "
                           f"l'empreinte calculée ne correspond pas au contenu",
                "tampered_id": r["id"],
                "count": len(rows),
            }

        prev_hash = r["entry_hash"]

    return {
        "valid": True,
        "message": f"Chaîne d'audit intègre ({len(rows)} entrées vérifiées sans altération)",
        "count": len(rows),
    }


def export_audit_csv(org_id: str, db_path: str | None = None) -> str:
    """Exporte le journal d'audit de l'organisation au format CSV protégé (CWE-1236)."""
    rows = db.query_all(
        "SELECT a.id, a.created_at, a.action, u.email AS user_email, a.ip, a.details_json, a.prev_hash, a.entry_hash "
        "FROM audit a LEFT JOIN users u ON a.user_id = u.id "
        "WHERE a.org_id = ? ORDER BY a.id ASC;",
        (org_id,),
        db_path=db_path,
    )
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["id", "date_utc", "action", "user", "ip", "details", "prev_hash", "entry_hash"])
    for r in rows:
        writer.writerow([
            csv_cell(r["id"]),
            csv_cell(time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(r["created_at"]))),
            csv_cell(r["action"]),
            csv_cell(r["user_email"] or ""),
            csv_cell(r["ip"] or ""),
            csv_cell(r["details_json"]),
            csv_cell(r["prev_hash"]),
            csv_cell(r["entry_hash"]),
        ])
    return buf.getvalue()


# ------------------------------------------------------------------ 7. Équipe et Rôles

def list_members(org_id: str, db_path: str | None = None) -> list[dict[str, Any]]:
    """Liste tous les membres d'une organisation avec leur rôle et email."""
    rows = db.query_all(
        "SELECT m.id, m.org_id, m.user_id, m.role, m.created_at, u.email "
        "FROM members m JOIN users u ON m.user_id = u.id "
        "WHERE m.org_id = ? ORDER BY m.created_at ASC;",
        (org_id,),
        db_path=db_path,
    )
    return [dict(r) for r in rows]


def change_member_role(org_id: str, actor_user_id: str, member_id: str, new_role: str,
                       ip: str | None = None, db_path: str | None = None) -> dict[str, Any]:
    """Modifie le rôle d'un membre.

    Règles strictes :
      - L'acteur doit être au minimum admin.
      - Seul un owner peut nommer un nouveau owner.
      - Seul un owner peut modifier le rôle d'un owner.
      - Impossible de rétrograder le dernier owner de l'organisation.
      - Anti-IDOR : 404 si le membre n'appartient pas à l'organisation active.
    """
    check_org_writable(org_id, db_path=db_path)
    actor_member = require_role(actor_user_id, org_id, "admin", db_path=db_path)

    if new_role not in VALID_ROLES:
        raise OrgError("Rôle invalide", 400)

    target_member = db.query_one(
        "SELECT * FROM members WHERE id = ? AND org_id = ?;",
        (member_id, org_id),
        db_path=db_path,
    )
    if not target_member:
        raise OrgError("Membre introuvable", 404)

    # Seul l'owner peut nommer un owner
    if new_role == "owner" and actor_member["role"] != "owner":
        raise OrgError("Seul le propriétaire peut nommer un propriétaire", 403)

    # Modification d'un owner existant
    if target_member["role"] == "owner":
        if actor_member["role"] != "owner":
            raise OrgError("Seul le propriétaire peut modifier le rôle d'un propriétaire", 403)

        if new_role != "owner":
            # On ne peut pas retirer le dernier owner
            owners = db.query_one(
                "SELECT COUNT(*) AS c FROM members WHERE org_id = ? AND role = 'owner';",
                (org_id,),
                db_path=db_path,
            )
            if owners and owners["c"] <= 1:
                raise OrgError("Impossible de modifier le rôle du dernier propriétaire", 400)

    now = int(time.time())
    db.execute(
        "UPDATE members SET role = ?, updated_at = ? WHERE id = ? AND org_id = ?;",
        (new_role, now, member_id, org_id),
        db_path=db_path,
    )
    auth.log_audit("team.role_change", org_id=org_id, user_id=actor_user_id,
                   details={"target_member_id": member_id, "target_user_id": target_member["user_id"],
                            "old_role": target_member["role"], "new_role": new_role},
                   ip=ip, db_path=db_path)
    return {"ok": True, "id": member_id, "role": new_role}


def remove_member(org_id: str, actor_user_id: str, member_id: str,
                  ip: str | None = None, db_path: str | None = None) -> dict[str, Any]:
    """Retire un membre de l'organisation.

    Règles strictes :
      - L'acteur doit être au minimum admin.
      - Seul un owner peut retirer un owner.
      - Impossible de retirer le dernier owner de l'organisation.
      - Anti-IDOR : 404 si le membre n'appartient pas à l'organisation active.
    """
    check_org_writable(org_id, db_path=db_path)
    actor_member = require_role(actor_user_id, org_id, "admin", db_path=db_path)

    target_member = db.query_one(
        "SELECT * FROM members WHERE id = ? AND org_id = ?;",
        (member_id, org_id),
        db_path=db_path,
    )
    if not target_member:
        raise OrgError("Membre introuvable", 404)

    if target_member["role"] == "owner":
        if actor_member["role"] != "owner":
            raise OrgError("Seul le propriétaire peut retirer un propriétaire", 403)

        owners = db.query_one(
            "SELECT COUNT(*) AS c FROM members WHERE org_id = ? AND role = 'owner';",
            (org_id,),
            db_path=db_path,
        )
        if owners and owners["c"] <= 1:
            raise OrgError("Impossible de retirer le dernier propriétaire", 400)

    db.execute("DELETE FROM members WHERE id = ? AND org_id = ?;", (member_id, org_id), db_path=db_path)
    auth.log_audit("team.member_remove", org_id=org_id, user_id=actor_user_id,
                   details={"target_member_id": member_id, "target_user_id": target_member["user_id"],
                            "role": target_member["role"]},
                   ip=ip, db_path=db_path)
    return {"ok": True, "id": member_id}


def invite_member(org_id: str, actor_user_id: str, email: str, role: str,
                  ip: str | None = None, db_path: str | None = None) -> dict[str, Any]:
    """Crée une invitation d'équipe par lien à usage unique (auth.create_invite).

    Règles strictes :
      - Acteur au moins admin.
      - Seul l'owner peut inviter avec le rôle owner.
    """
    check_org_writable(org_id, db_path=db_path)
    actor_member = require_role(actor_user_id, org_id, "admin", db_path=db_path)

    if role not in VALID_ROLES:
        raise OrgError("Rôle invalide", 400)

    if role == "owner" and actor_member["role"] != "owner":
        raise OrgError("Seul le propriétaire peut inviter un propriétaire", 403)

    raw_token, inv = auth.create_invite(
        org_id, email, role, invited_by=actor_user_id, ip=ip, db_path=db_path
    )
    return {"token": raw_token, **inv}


def list_invites(org_id: str, db_path: str | None = None) -> list[dict[str, Any]]:
    """Liste les invitations en attente pour l'organisation active."""
    now = int(time.time())
    rows = db.query_all(
        "SELECT id, org_id, email, role, invited_by, expires_at, created_at "
        "FROM invites WHERE org_id = ? AND used_at IS NULL AND expires_at > ? "
        "ORDER BY created_at DESC;",
        (org_id, now),
        db_path=db_path,
    )
    return [dict(r) for r in rows]


def revoke_invite(org_id: str, actor_user_id: str, invite_id: str,
                  ip: str | None = None, db_path: str | None = None) -> dict[str, Any]:
    """Révoque une invitation en attente (anti-IDOR -> 404)."""
    check_org_writable(org_id, db_path=db_path)
    require_role(actor_user_id, org_id, "admin", db_path=db_path)

    inv = db.query_one("SELECT * FROM invites WHERE id = ? AND org_id = ?;", (invite_id, org_id), db_path=db_path)
    if not inv:
        raise OrgError("Invitation introuvable", 404)

    db.execute("DELETE FROM invites WHERE id = ? AND org_id = ?;", (invite_id, org_id), db_path=db_path)
    auth.log_audit("team.invite_revoke", org_id=org_id, user_id=actor_user_id,
                   details={"invite_id": invite_id, "email": inv["email"]},
                   ip=ip, db_path=db_path)
    return {"ok": True, "id": invite_id}


# ------------------------------------------------------------------ 9. Paramètres d'organisation

def get_settings(org_id: str, db_path: str | None = None) -> dict[str, Any]:
    """Récupère les paramètres de l'organisation."""
    org = get_org(org_id, db_path=db_path)
    return {
        "id": org["id"],
        "name": org["name"],
        "slug": org.get("slug"),
        "network": org.get("network", "mock"),
        "vault_address": org.get("vault_address"),
        "canary_address": org.get("canary_address"),
        "is_suspended": bool(org.get("is_suspended")),
    }


def update_settings(org_id: str, user_id: str,
                    name: str | None = None,
                    network: str | None = None,
                    vault_address: str | None = None,
                    canary_address: str | None = None,
                    ip: str | None = None, db_path: str | None = None) -> dict[str, Any]:
    """Met à jour les paramètres de l'organisation (réservé aux admins+)."""
    check_org_writable(org_id, db_path=db_path)
    require_role(user_id, org_id, "admin", db_path=db_path)

    log_details: dict[str, Any] = {}
    clean_name = None
    if name is not None:
        clean_name = str(name).strip()[:80]
        if not clean_name:
            raise OrgError("Nom d'organisation invalide", 400)
        log_details["name"] = clean_name

    if network is not None:
        if network not in ("mock", "avalanche", "fuji"):
            raise OrgError("Réseau invalide ('mock', 'avalanche' ou 'fuji')", 400)
        log_details["network"] = network

    clean_vault = None
    if vault_address is not None:
        clean_vault = validate_evm_address(vault_address) if vault_address.strip() else ""
        log_details["vault_address"] = clean_vault

    clean_canary = None
    if canary_address is not None:
        clean_canary = validate_evm_address(canary_address) if canary_address.strip() else ""
        log_details["canary_address"] = clean_canary

    if log_details:
        now = int(time.time())
        db.execute(
            "UPDATE orgs SET "
            "  name = COALESCE(?, name), "
            "  network = COALESCE(?, network), "
            "  vault_address = COALESCE(?, vault_address), "
            "  canary_address = COALESCE(?, canary_address), "
            "  updated_at = ? "
            "WHERE id = ?;",
            (clean_name, network, clean_vault, clean_canary, now, org_id),
            db_path=db_path,
        )
        auth.log_audit("org.settings_update", org_id=org_id, user_id=user_id,
                       details=log_details, ip=ip, db_path=db_path)

    return get_settings(org_id, db_path=db_path)
