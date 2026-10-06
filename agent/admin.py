"""admin.py — Espace administration de la plateforme VaultGuard v3 (Étape 5).

Exigences de sécurité et d'architecture :
  - Python stdlib uniquement (sqlite3, json, time, urllib.request, etc.)
  - Accès strictement réservé aux super-administrateurs avec 2FA active.
  - Statistiques globales : comptages uniquement, JAMAIS de contenu de paiement (pas de montant, memo, documents).
  - Organisations : suspendre/réactiver. Une suspension coupe immédiatement /v1 (403) et /app.
    Garde-fous : un super-admin ne peut pas suspendre sa propre organisation.
    Changements d'état par UPDATE … WHERE <état attendu> + vérification de rowcount.
    Aucune donnée d'organisation n'est modifiable depuis /admin, sauf le statut de suspension.
  - Utilisateurs : désactiver, déconnecter partout (suppression des sessions en base).
    Garde-fous : un super-admin ne peut ni se désactiver lui-même, et le dernier super-admin ne peut pas être désactivé.
    Changements d'état par UPDATE … WHERE <état attendu> + vérification de rowcount.
  - Événements de sécurité : échecs de connexion (login_events), clés en quarantaine (api_keys), appâts touchés (payments / audit).
  - Journal d'audit : vérification d'intégrité cryptographique complète (chaîne de hash).
  - Santé : état base (SQLite), RPC Avalanche avec délai d'attente court (JSON-RPC), version de l'application.
  - Chaque action admin est tracée dans l'audit avec l'adresse IP.
"""
from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from typing import Any

try:
    import db
    import auth
    import orgs
except ImportError:
    from agent import db
    from agent import auth
    from agent import orgs

PLATFORM_VERSION = "3.0.0"


class AdminError(Exception):
    def __init__(self, message: str, code: int = 400):
        super().__init__(message)
        self.message = message
        self.code = code


# ------------------------------------------------------------------ 1. Statistiques globales
def get_global_stats(db_path: str | None = None) -> dict[str, Any]:
    """Retourne les comptages globaux de la plateforme.

    Règle absolue de confidentialité : comptages uniquement, jamais de contenu de paiement
    (aucun destinataire, montant, memo ou document de facture).
    """
    now = int(time.time())

    # Utilisateurs
    u_total = db.query_one("SELECT COUNT(*) AS c FROM users;", db_path=db_path)["c"]
    u_active = db.query_one("SELECT COUNT(*) AS c FROM users WHERE is_active = 1;", db_path=db_path)["c"]
    u_inactive = db.query_one("SELECT COUNT(*) AS c FROM users WHERE is_active = 0;", db_path=db_path)["c"]
    u_totp = db.query_one("SELECT COUNT(*) AS c FROM users WHERE totp_enabled = 1;", db_path=db_path)["c"]
    u_super = db.query_one("SELECT COUNT(*) AS c FROM users WHERE is_superadmin = 1;", db_path=db_path)["c"]

    # Organisations
    o_total = db.query_one("SELECT COUNT(*) AS c FROM orgs;", db_path=db_path)["c"]
    o_active = db.query_one("SELECT COUNT(*) AS c FROM orgs WHERE is_suspended = 0;", db_path=db_path)["c"]
    o_suspended = db.query_one("SELECT COUNT(*) AS c FROM orgs WHERE is_suspended = 1;", db_path=db_path)["c"]

    # Clés API
    k_total = db.query_one("SELECT COUNT(*) AS c FROM api_keys;", db_path=db_path)["c"]
    k_quarantined = db.query_one(
        "SELECT COUNT(*) AS c FROM api_keys WHERE quarantined_until IS NOT NULL AND quarantined_until > ?;",
        (now,), db_path=db_path
    )["c"]
    k_active = db.query_one(
        "SELECT COUNT(*) AS c FROM api_keys WHERE is_active = 1 AND (quarantined_until IS NULL OR quarantined_until <= ?);",
        (now,), db_path=db_path
    )["c"]

    # Paiements : COMPTAGES UNIQUEMENT (jamais de montants ni de memos)
    p_total = db.query_one("SELECT COUNT(*) AS c FROM payments;", db_path=db_path)["c"]
    p_allowed = db.query_one("SELECT COUNT(*) AS c FROM payments WHERE decision = 'allowed';", db_path=db_path)["c"]
    p_blocked = db.query_one("SELECT COUNT(*) AS c FROM payments WHERE decision = 'blocked';", db_path=db_path)["c"]
    p_pending = db.query_one("SELECT COUNT(*) AS c FROM payments WHERE decision = 'pending_review';", db_path=db_path)["c"]

    # Entrées d'audit
    audit_total = db.query_one("SELECT COUNT(*) AS c FROM audit;", db_path=db_path)["c"]

    return {
        "users": {
            "total": u_total,
            "active": u_active,
            "inactive": u_inactive,
            "totp_enabled": u_totp,
            "superadmins": u_super,
        },
        "orgs": {
            "total": o_total,
            "active": o_active,
            "suspended": o_suspended,
        },
        "api_keys": {
            "total": k_total,
            "active": k_active,
            "quarantined": k_quarantined,
        },
        "payments": {
            "total": p_total,
            "allowed": p_allowed,
            "blocked": p_blocked,
            "pending_review": p_pending,
        },
        "audit_entries_count": audit_total,
    }


# ------------------------------------------------------------------ 2. Organisations
def list_orgs(db_path: str | None = None) -> list[dict[str, Any]]:
    """Liste les organisations de la plateforme avec métriques de rattachement."""
    rows = db.query_all(
        "SELECT o.id, o.name, o.slug, o.network, o.vault_address, o.canary_address, o.is_suspended, "
        "       o.created_at, o.updated_at, "
        "       (SELECT COUNT(*) FROM members WHERE org_id = o.id) AS members_count, "
        "       (SELECT COUNT(*) FROM api_keys WHERE org_id = o.id) AS api_keys_count, "
        "       (SELECT COUNT(*) FROM payments WHERE org_id = o.id) AS payments_count "
        "FROM orgs o ORDER BY o.created_at DESC;",
        db_path=db_path,
    )
    out = []
    for r in rows:
        d = dict(r)
        d["is_suspended"] = bool(d["is_suspended"])
        out.append(d)
    return out


def suspend_org(org_id: str, admin_user_id: str, ip: str | None = None,
                db_path: str | None = None) -> dict[str, Any]:
    """Suspend une organisation.

    Garde-fous :
      - Un super-administrateur ne peut pas suspendre sa propre organisation (dont il est propriétaire).
      - Changement d'état atomique UPDATE … WHERE is_suspended = 0 + vérification rowcount.
      - Coupe immédiatement /v1 (403) et /app (lecture seule).
      - Action tracée dans l'audit avec IP.
    """
    clean_org_id = str(org_id).strip()
    if not clean_org_id:
        raise AdminError("Identifiant d'organisation requis", 400)

    # Vérification : l'admin est-il propriétaire de cette organisation ?
    m = db.query_one(
        "SELECT role FROM members WHERE user_id = ? AND org_id = ?;",
        (admin_user_id, clean_org_id),
        db_path=db_path,
    )
    if m and m["role"] == "owner":
        raise AdminError("Un super-administrateur ne peut pas suspendre sa propre organisation", 400)

    now = int(time.time())
    cur = db.execute(
        "UPDATE orgs SET is_suspended = 1, updated_at = ? WHERE id = ? AND is_suspended = 0;",
        (now, clean_org_id),
        db_path=db_path,
    )
    if cur.rowcount == 0:
        org = db.query_one("SELECT id, is_suspended FROM orgs WHERE id = ?;", (clean_org_id,), db_path=db_path)
        if not org:
            raise AdminError("Organisation introuvable", 404)
        raise AdminError("Organisation déjà suspendue", 400)

    auth.log_audit(
        "admin.org.suspend",
        org_id=clean_org_id,
        user_id=admin_user_id,
        details={"org_id": clean_org_id, "is_suspended": True},
        ip=ip,
        db_path=db_path,
    )
    return {"ok": True, "org_id": clean_org_id, "is_suspended": True}


def reactivate_org(org_id: str, admin_user_id: str, ip: str | None = None,
                   db_path: str | None = None) -> dict[str, Any]:
    """Réactive une organisation suspendue.

    Garde-fous :
      - Changement d'état atomique UPDATE … WHERE is_suspended = 1 + vérification rowcount.
      - Action tracée dans l'audit avec IP.
    """
    clean_org_id = str(org_id).strip()
    if not clean_org_id:
        raise AdminError("Identifiant d'organisation requis", 400)

    now = int(time.time())
    cur = db.execute(
        "UPDATE orgs SET is_suspended = 0, updated_at = ? WHERE id = ? AND is_suspended = 1;",
        (now, clean_org_id),
        db_path=db_path,
    )
    if cur.rowcount == 0:
        org = db.query_one("SELECT id, is_suspended FROM orgs WHERE id = ?;", (clean_org_id,), db_path=db_path)
        if not org:
            raise AdminError("Organisation introuvable", 404)
        raise AdminError("Organisation déjà active", 400)

    auth.log_audit(
        "admin.org.reactivate",
        org_id=clean_org_id,
        user_id=admin_user_id,
        details={"org_id": clean_org_id, "is_suspended": False},
        ip=ip,
        db_path=db_path,
    )
    return {"ok": True, "org_id": clean_org_id, "is_suspended": False}


# ------------------------------------------------------------------ 3. Utilisateurs
def list_users(db_path: str | None = None) -> list[dict[str, Any]]:
    """Liste tous les utilisateurs de la plateforme avec statut et affiliations."""
    rows = db.query_all(
        "SELECT u.id, u.email, u.is_superadmin, u.is_active, u.totp_enabled, "
        "       u.failed_login_attempts, u.locked_until, u.created_at, u.updated_at, "
        "       (SELECT COUNT(*) FROM sessions WHERE user_id = u.id) AS sessions_count "
        "FROM users u ORDER BY u.created_at DESC;",
        db_path=db_path,
    )
    out = []
    for r in rows:
        d = dict(r)
        d["is_superadmin"] = bool(d["is_superadmin"])
        d["is_active"] = bool(d["is_active"])
        d["totp_enabled"] = bool(d["totp_enabled"])

        # Affiliations d'organisation
        m_rows = db.query_all(
            "SELECT o.id, o.name, m.role FROM members m JOIN orgs o ON m.org_id = o.id WHERE m.user_id = ?;",
            (d["id"],),
            db_path=db_path,
        )
        d["orgs"] = [dict(mr) for mr in m_rows]
        out.append(d)
    return out


def deactivate_user(target_user_id: str, admin_user_id: str, ip: str | None = None,
                    db_path: str | None = None) -> dict[str, Any]:
    """Désactive un utilisateur et révoque immédiatement toutes ses sessions en base.

    Garde-fous :
      - Un super-administrateur ne peut ni se désactiver lui-même.
      - Le dernier super-administrateur actif ne peut pas être désactivé.
      - Changement d'état atomique UPDATE … WHERE is_active = 1 + vérification rowcount.
      - Action tracée dans l'audit avec IP.
    """
    clean_target_id = str(target_user_id).strip()
    if not clean_target_id:
        raise AdminError("Identifiant d'utilisateur requis", 400)

    if clean_target_id == admin_user_id:
        raise AdminError("Un super-administrateur ne peut pas se désactiver lui-même", 400)

    target = db.query_one("SELECT id, is_superadmin, is_active FROM users WHERE id = ?;", (clean_target_id,), db_path=db_path)
    if not target:
        raise AdminError("Utilisateur introuvable", 404)

    now = int(time.time())
    # Condition « pas le dernier super-admin » évaluée dans l'UPDATE lui-même : SQLite n'a qu'un écrivain à la fois,
    # donc deux désactivations parallèles ne peuvent pas toutes les deux voir « 2 super-admins actifs ».
    cur = db.execute(
        "UPDATE users SET is_active = 0, updated_at = ? WHERE id = ? AND is_active = 1 AND ("
        "  is_superadmin = 0 OR (SELECT COUNT(*) FROM users WHERE is_superadmin = 1 AND is_active = 1) > 1);",
        (now, clean_target_id),
        db_path=db_path,
    )
    if cur.rowcount == 0:
        if target["is_superadmin"] and target["is_active"]:
            raise AdminError("Le dernier super-administrateur ne peut pas être désactivé", 400)
        raise AdminError("Utilisateur déjà inactif", 400)

    # Révoque immédiatement toutes les sessions en base
    db.execute("DELETE FROM sessions WHERE user_id = ?;", (clean_target_id,), db_path=db_path)

    auth.log_audit(
        "admin.user.deactivate",
        user_id=admin_user_id,
        details={"target_user_id": clean_target_id, "is_active": False},
        ip=ip,
        db_path=db_path,
    )
    return {"ok": True, "user_id": clean_target_id, "is_active": False}


def activate_user(target_user_id: str, admin_user_id: str, ip: str | None = None,
                  db_path: str | None = None) -> dict[str, Any]:
    """Réactive un utilisateur inactif.

    Garde-fous :
      - Changement d'état atomique UPDATE … WHERE is_active = 0 + vérification rowcount.
      - Action tracée dans l'audit avec IP.
    """
    clean_target_id = str(target_user_id).strip()
    if not clean_target_id:
        raise AdminError("Identifiant d'utilisateur requis", 400)

    now = int(time.time())
    cur = db.execute(
        "UPDATE users SET is_active = 1, updated_at = ? WHERE id = ? AND is_active = 0;",
        (now, clean_target_id),
        db_path=db_path,
    )
    if cur.rowcount == 0:
        target = db.query_one("SELECT id FROM users WHERE id = ?;", (clean_target_id,), db_path=db_path)
        if not target:
            raise AdminError("Utilisateur introuvable", 404)
        raise AdminError("Utilisateur déjà actif", 400)

    auth.log_audit(
        "admin.user.activate",
        user_id=admin_user_id,
        details={"target_user_id": clean_target_id, "is_active": True},
        ip=ip,
        db_path=db_path,
    )
    return {"ok": True, "user_id": clean_target_id, "is_active": True}


def disconnect_all_sessions(target_user_id: str, admin_user_id: str, ip: str | None = None,
                            db_path: str | None = None) -> dict[str, Any]:
    """Déconnecte un utilisateur de tous ses appareils en supprimant ses sessions en base.

    Garde-fous :
      - Suppression atomique dans la table sessions.
      - Action tracée dans l'audit avec IP.
    """
    clean_target_id = str(target_user_id).strip()
    if not clean_target_id:
        raise AdminError("Identifiant d'utilisateur requis", 400)

    target = db.query_one("SELECT id FROM users WHERE id = ?;", (clean_target_id,), db_path=db_path)
    if not target:
        raise AdminError("Utilisateur introuvable", 404)

    cur = db.execute("DELETE FROM sessions WHERE user_id = ?;", (clean_target_id,), db_path=db_path)
    deleted_count = cur.rowcount

    auth.log_audit(
        "admin.user.disconnect_all",
        user_id=admin_user_id,
        details={"target_user_id": clean_target_id, "deleted_sessions": deleted_count},
        ip=ip,
        db_path=db_path,
    )
    return {"ok": True, "user_id": clean_target_id, "deleted_sessions": deleted_count}


# ------------------------------------------------------------------ 4. Événements de sécurité
def get_security_events(db_path: str | None = None) -> dict[str, Any]:
    """Retourne les alertes et événements de sécurité récents :

    - Échecs de connexion (login_events)
    - Clés agents mises en quarantaine (api_keys)
    - Déclenchements d'adresses appâts (honeytokens)
    """
    now = int(time.time())

    # 1. Échecs de connexion récents (50 derniers)
    failed_logins_rows = db.query_all(
        "SELECT id, user_id, email, ip, user_agent, reason, created_at "
        "FROM login_events WHERE success = 0 ORDER BY created_at DESC LIMIT 50;",
        db_path=db_path,
    )
    failed_logins = [dict(r) for r in failed_logins_rows]

    # 2. Clés en quarantaine
    quarantine_rows = db.query_all(
        "SELECT k.id, k.org_id, o.name AS org_name, k.name, k.key_prefix, "
        "       k.quarantined_until, k.quarantine_reason, k.created_at "
        "FROM api_keys k JOIN orgs o ON k.org_id = o.id "
        "WHERE k.quarantined_until IS NOT NULL AND k.quarantined_until > ? "
        "ORDER BY k.quarantined_until DESC LIMIT 50;",
        (now,), db_path=db_path,
    )
    quarantined_keys = [dict(r) for r in quarantine_rows]

    # 3. Événements appâts (honeytokens touchés)
    # Détectés soit par blocage de paiement contenant "canary", soit par trace d'audit
    canary_payment_rows = db.query_all(
        "SELECT p.id, p.org_id, o.name AS org_name, p.recipient, p.amount_gwei, p.created_at, p.reasons_json "
        "FROM payments p JOIN orgs o ON p.org_id = o.id "
        "WHERE p.reasons_json LIKE '%canary%' OR p.chain_status LIKE '%Canary%' "
        "ORDER BY p.created_at DESC LIMIT 50;",
        db_path=db_path,
    )
    canary_events = []
    for cp in canary_payment_rows:
        d = dict(cp)
        d["event_type"] = "payment_canary_hit"
        canary_events.append(d)

    canary_audit_rows = db.query_all(
        "SELECT a.id, a.org_id, o.name AS org_name, a.user_id, a.api_key_id, a.action, "
        "       a.details_json, a.ip, a.created_at "
        "FROM audit a LEFT JOIN orgs o ON a.org_id = o.id "
        "WHERE a.details_json LIKE '%appât%' OR a.details_json LIKE '%honeytoken%' OR a.details_json LIKE '%canary%' "
        "ORDER BY a.id DESC LIMIT 50;",
        db_path=db_path,
    )
    for ca in canary_audit_rows:
        d = dict(ca)
        try:
            d["details"] = json.loads(d.get("details_json") or "{}")
        except Exception:
            d["details"] = {}
        d["event_type"] = "audit_canary_alert"
        canary_events.append(d)

    return {
        "failed_logins": failed_logins,
        "quarantined_keys": quarantined_keys,
        "canary_events": canary_events[:50],
        "summary": {
            "failed_logins_count": len(failed_logins),
            "quarantined_keys_count": len(quarantined_keys),
            "canary_events_count": len(canary_events),
        },
    }


# ------------------------------------------------------------------ 5. Journal d'audit de la plateforme
def get_platform_audit(limit: int = 100, db_path: str | None = None) -> list[dict[str, Any]]:
    """Retourne les entrées du journal d'audit de l'ensemble de la plateforme."""
    clean_limit = max(1, min(limit, 500))
    rows = db.query_all(
        "SELECT a.id, a.org_id, o.name AS org_name, a.user_id, u.email AS user_email, "
        "       a.api_key_id, a.action, a.details_json, a.ip, a.prev_hash, a.entry_hash, a.created_at "
        "FROM audit a "
        "LEFT JOIN users u ON a.user_id = u.id "
        "LEFT JOIN orgs o ON a.org_id = o.id "
        "ORDER BY a.id DESC LIMIT ?;",
        (clean_limit,),
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


def verify_platform_audit(admin_user_id: str, ip: str | None = None,
                          db_path: str | None = None) -> dict[str, Any]:
    """Vérifie l'intégrité cryptographique complète de la chaîne d'audit de la plateforme."""
    res = orgs.verify_audit_chain(db_path=db_path)
    auth.log_audit(
        "admin.audit.verify",
        user_id=admin_user_id,
        details={"valid": res.get("valid", False), "count": res.get("count", 0)},
        ip=ip,
        db_path=db_path,
    )
    return res


# ------------------------------------------------------------------ 6. Santé de la plateforme
def _redact_url(url: str) -> str:
    """Ne garde que schéma://hôte : le chemin ou la requête d'une URL RPC contient souvent une clé d'API."""
    parts = urllib.parse.urlsplit(url)
    return f"{parts.scheme}://{parts.hostname or ''}" if parts.scheme else "(invalide)"


def get_health(db_path: str | None = None) -> dict[str, Any]:
    """Contrôle la santé globale de la plateforme :

    - Base de données SQLite (connexion + latence)
    - RPC Avalanche avec court délai d'attente (JSON-RPC eth_blockNumber, timeout 1.5 s)
    - Version de l'application
    """
    # 1. Base de données
    db_status = "ok"
    db_latency_ms: float | None = None
    t0_db = time.perf_counter()
    try:
        db.query_one("SELECT 1;", db_path=db_path)
        db_latency_ms = round((time.perf_counter() - t0_db) * 1000, 2)
    except Exception as e:
        db_status = f"error: {type(e).__name__}"
        db_latency_ms = round((time.perf_counter() - t0_db) * 1000, 2)

    # 2. RPC Avalanche
    rpc_url = os.environ.get("RPC_URL", "https://api.avax-test.network/ext/bc/C/rpc")
    rpc_status = "unknown"
    rpc_latency_ms: float | None = None
    block_number: int | None = None

    t0_rpc = time.perf_counter()
    try:
        payload = json.dumps({
            "jsonrpc": "2.0",
            "method": "eth_blockNumber",
            "params": [],
            "id": 1
        }).encode("utf-8")
        req = urllib.request.Request(
            rpc_url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "VaultGuard-Health/3.0",
            },
        )
        with urllib.request.urlopen(req, timeout=1.5) as resp:  # nosec B310
            if resp.status == 200:
                raw = resp.read().decode("utf-8")
                data = json.loads(raw)
                hex_block = data.get("result", "0x0")
                if isinstance(hex_block, str) and hex_block.startswith("0x"):
                    block_number = int(hex_block, 16)
                elif isinstance(hex_block, int):
                    block_number = hex_block
                rpc_status = "ok"
                rpc_latency_ms = round((time.perf_counter() - t0_rpc) * 1000, 2)
            else:
                rpc_status = f"http_{resp.status}"
                rpc_latency_ms = round((time.perf_counter() - t0_rpc) * 1000, 2)
    except Exception:
        rpc_status = "unreachable"
        rpc_latency_ms = round((time.perf_counter() - t0_rpc) * 1000, 2)

    overall_status = "ok" if db_status == "ok" else "error"

    return {
        "status": overall_status,
        "version": PLATFORM_VERSION,
        "database": {
            "status": db_status,
            "latency_ms": db_latency_ms,
        },
        "avalanche_rpc": {
            "status": rpc_status,
            "url": _redact_url(rpc_url),
            "latency_ms": rpc_latency_ms,
            "block_number": block_number,
        },
    }
