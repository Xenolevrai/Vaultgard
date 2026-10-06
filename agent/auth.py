"""auth.py — Gestion des comptes, authentification, 2FA et sessions pour VaultGuard v3.

Exigences de sécurité et d'architecture :
  - Python stdlib uniquement (sqlite3, hashlib, hmac, secrets, base64, struct, time, json)
  - Utilise agent/db.py pour toute persistance (requêtes paramétrées, transactions)
  - Inscription (désactivable via SIGNUP_OPEN=0) : utilisateur + organisation (rôle owner) dans db.transaction()
  - Mots de passe >= 12 caractères, refus d'une liste de mots de passe courants
  - Connexion : verrouillage 15 min après 5 échecs, temps de réponse similaire (hash factice)
    et même message que l'email existe ou non. Chaque tentative dans login_events.
  - TOTP RFC 6238 : HMAC-SHA1, 6 chiffres, 30 s, fenêtre +-1, hmac.compare_digest,
    refus de réutiliser un code déjà accepté, clé base32 + lien otpauth://
  - Sessions en base : jeton secrets.token_urlsafe(32), seule l'empreinte SHA-256 stockée,
    inactivité 2 h, déconnexion globale
  - Changement de mot de passe : ancien requis, invalide les autres sessions
  - Invitations : jeton unique, validité 7 jours, usage unique
  - Chaque action sensible écrit une ligne d'audit chaînée par hash
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import struct
import threading
import time
from typing import Any
from urllib.parse import quote

try:
    import db
except ImportError:
    from agent import db


# ------------------------------------------------------------------ Erreurs et constantes

class AuthError(Exception):
    def __init__(self, message: str, code: int = 400):
        super().__init__(message)
        self.message = message
        self.code = code


# Durée de validité de session (2 heures d'inactivité)
SESSION_TTL = 2 * 3600

# Durée de validité des invitations (7 jours)
INVITE_TTL = 7 * 86400

# Durée de verrouillage après 5 échecs (15 minutes)
LOCKOUT_DURATION = 15 * 60
MAX_LOGIN_ATTEMPTS = 5

_AUDIT_LOCK = threading.RLock()

# Mot de passe factice pour égaliser le temps de calcul scrypt lors de tentatives sur emails inexistants
# Précalculé à l'import pour garantir des performances stables
DUMMY_PASSWORD_HASH = db.hash_password("vaultguard-dummy-timing-protection-2026")

# Liste de mots de passe courants ou trop prévisibles (>= 12 caractères)
COMMON_PASSWORDS = frozenset({
    "password1234",
    "password12345",
    "123456789012",
    "1234567890123",
    "qwerty123456",
    "azerty123456",
    "admin1234567",
    "administrator",
    "welcome12345",
    "motdepasse123",
    "motdepasse1234",
    "iloveyou1234",
    "monkey123456",
    "dragon123456",
    "sunshine1234",
    "princess1234",
    "football1234",
    "baseball1234",
    "master123456",
    "shadow123456",
    "charlie12345",
    "trustnoone123",
    "starwars1234",
    "superman1234",
    "batman123456",
    "letmein12345",
    "changeme1234",
    "passphrase123",
    "111111111111",
    "000000000000",
    "123123123123",
    "abcabcabcabc",
    "qwertyuiopas",
    "asdfghjkl123",
    "123456123456",
    "passwordpassword",
})


# ------------------------------------------------------------------ Validation des entrées

def validate_password(password: str) -> None:
    """Valide les critères de sécurité du mot de passe (>= 12 caractères, non courant)."""
    if not isinstance(password, str):
        raise AuthError("Le mot de passe doit être une chaîne de caractères", 400)
    if len(password) < 12:
        raise AuthError("Le mot de passe doit contenir au moins 12 caractères", 400)
    if len(password) > 256:
        raise AuthError("Le mot de passe ne peut pas dépasser 256 caractères", 400)

    clean = password.strip().lower()
    if clean in COMMON_PASSWORDS:
        raise AuthError("Mot de passe trop courant ou prévisible", 400)

    # Répétitions triviales (ex: 12 fois le même caractère)
    if len(set(password)) < 3:
        raise AuthError("Mot de passe trop simple ou répétitif", 400)


def validate_email(email: str) -> str:
    """Normalise et valide le format basique d'une adresse email."""
    if not isinstance(email, str):
        raise AuthError("L'adresse email doit être une chaîne de caractères", 400)
    normalized = email.strip().lower()
    if not normalized or "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
        raise AuthError("Adresse email invalide", 400)
    local, _, domain = normalized.partition("@")
    if not local or not domain or "." not in domain or len(normalized) > 254:
        raise AuthError("Adresse email invalide", 400)
    return normalized


# ------------------------------------------------------------------ Journal d'audit chaîné

def log_audit(action: str, org_id: str | None = None, user_id: str | None = None,
              api_key_id: str | None = None, details: dict[str, Any] | None = None,
              ip: str | None = None, db_path: str | None = None) -> dict[str, Any]:
    """Écrit une ligne d'audit chaînée par hash en respectant db.compute_audit_hash."""
    now = int(time.time())
    details_str = json.dumps(details or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    # Lire le dernier maillon puis écrire le suivant doit être indivisible, sinon deux requêtes simultanées
    # s'accrochent au même maillon et la chaîne bifurque (l'index unique sur prev_hash l'interdit aussi en base).
    with _AUDIT_LOCK:
        last_row = db.query_one("SELECT entry_hash FROM audit ORDER BY id DESC LIMIT 1;", db_path=db_path)
        prev_hash = last_row["entry_hash"] if last_row else db.GENESIS_HASH
        entry_hash = db.compute_audit_hash(
            prev_hash, now, org_id, user_id, action, details_str,
            api_key_id=api_key_id, ip=ip
        )
        db.execute(
            "INSERT INTO audit (org_id, user_id, api_key_id, action, details_json, ip, prev_hash, entry_hash, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
            (org_id, user_id, api_key_id, action, details_str, ip, prev_hash, entry_hash, now),
            db_path=db_path,
        )
    return {
        "action": action,
        "org_id": org_id,
        "user_id": user_id,
        "prev_hash": prev_hash,
        "entry_hash": entry_hash,
        "created_at": now,
    }


# ------------------------------------------------------------------ TOTP (RFC 6238 en stdlib)

def _ensure_totp_table(db_path: str | None = None) -> None:
    db.execute(
        "CREATE TABLE IF NOT EXISTS totp_used_codes ("
        "user_id TEXT NOT NULL, "
        "code TEXT NOT NULL, "
        "used_at INTEGER NOT NULL, "
        "PRIMARY KEY (user_id, code));",
        db_path=db_path,
    )


def generate_totp_secret() -> str:
    """Génère une clé secrète TOTP aléatoire (160 bits) encodée en base32."""
    raw = secrets.token_bytes(20)
    return base64.b32encode(raw).decode("ascii").rstrip("=")


def get_totp_uri(secret_b32: str, email: str, issuer: str = "VaultGuard") -> str:
    """Génère le lien otpauth:// standard compatible Google Authenticator / 1Password."""
    label = f"{quote(issuer)}:{quote(email)}"
    return (f"otpauth://totp/{label}?secret={secret_b32}&issuer={quote(issuer)}"
            f"&algorithm=SHA1&digits=6&period=30")


def hotp(secret_b32: str, counter: int) -> str:
    """Calcule le code HOTP (RFC 4226) à 6 chiffres via HMAC-SHA1."""
    pad_len = (8 - len(secret_b32) % 8) % 8
    padded = secret_b32 + "=" * pad_len
    key = base64.b32decode(padded, casefold=True)
    msg = struct.pack(">Q", counter)
    # RFC 6238 requiert spécifiquement HMAC-SHA1
    digest = hmac.new(key, msg, hashlib.sha1).digest()  # nosec B303
    offset = digest[-1] & 0x0F
    binary = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    code = binary % 1_000_000
    return f"{code:06d}"


def is_totp_code_used(user_id: str, code: str, db_path: str | None = None) -> bool:
    """Vérifie si un code TOTP a déjà été validé pour cet utilisateur."""
    _ensure_totp_table(db_path)
    row = db.query_one(
        "SELECT 1 FROM totp_used_codes WHERE user_id = ? AND code = ?;",
        (user_id, code),
        db_path=db_path,
    )
    return row is not None


def mark_totp_code_used(user_id: str, code: str, now: int, db_path: str | None = None) -> None:
    """Enregistre un code TOTP comme consommé (anti-rejeu)."""
    _ensure_totp_table(db_path)
    # Nettoyage des codes de plus de 5 minutes
    db.execute("DELETE FROM totp_used_codes WHERE used_at < ?;", (now - 300,), db_path=db_path)
    db.execute(
        "INSERT INTO totp_used_codes (user_id, code, used_at) VALUES (?, ?, ?);",
        (user_id, code, now),
        db_path=db_path,
    )


def verify_totp(secret_b32: str, code: str, user_id: str | None = None,
                now: int | None = None, window: int = 1, db_path: str | None = None) -> bool:
    """Vérifie un code TOTP selon RFC 6238 (fenêtre +-1, comparaison en temps constant, anti-rejeu)."""
    if not secret_b32 or not code:
        return False
    code_clean = str(code).strip()
    if len(code_clean) != 6 or not code_clean.isdigit():
        return False

    if now is None:
        now = int(time.time())
    current_counter = now // 30

    # Fenêtre +-1 pas de 30 s
    for step in range(-window, window + 1):
        expected = hotp(secret_b32, current_counter + step)
        if hmac.compare_digest(code_clean, expected):
            if user_id:
                # Insertion atomique (clé primaire) : deux requêtes simultanées avec le même code
                # ne peuvent pas réussir toutes les deux.
                try:
                    mark_totp_code_used(user_id, code_clean, now, db_path=db_path)
                except sqlite3.IntegrityError:
                    return False
            return True

    return False


def setup_2fa(user_id: str, ip: str | None = None, db_path: str | None = None) -> dict[str, str]:
    """Génère une clé secrète TOTP et le lien otpauth:// sans activer le 2FA immédiatement."""
    user = db.query_one("SELECT * FROM users WHERE id = ?;", (user_id,), db_path=db_path)
    if not user:
        raise AuthError("Utilisateur introuvable", 404)
    # Sinon une session volée suffirait à rattacher la 2FA au téléphone de l'attaquant.
    if user["totp_enabled"]:
        raise AuthError("La double authentification est déjà active", 409)

    secret = generate_totp_secret()
    now = int(time.time())
    db.execute(
        "UPDATE users SET totp_secret = ?, updated_at = ? WHERE id = ?;",
        (secret, now, user_id),
        db_path=db_path,
    )
    uri = get_totp_uri(secret, user["email"])
    log_audit("auth.2fa_setup", user_id=user_id, ip=ip, db_path=db_path)
    return {"secret": secret, "otpauth_url": uri}


def enable_2fa(user_id: str, code: str, ip: str | None = None, db_path: str | None = None) -> dict[str, bool]:
    """Active le 2FA après vérification d'un premier code valide."""
    user = db.query_one("SELECT * FROM users WHERE id = ?;", (user_id,), db_path=db_path)
    if not user or not user["totp_secret"]:
        raise AuthError("Configuration 2FA non initiée", 400)

    now = int(time.time())
    if not verify_totp(user["totp_secret"], code, user_id=user_id, now=now, db_path=db_path):
        raise AuthError("Code TOTP invalide ou expiré", 400)

    db.execute(
        "UPDATE users SET totp_enabled = 1, updated_at = ? WHERE id = ?;",
        (now, user_id),
        db_path=db_path,
    )
    log_audit("auth.2fa_enable", user_id=user_id, ip=ip, db_path=db_path)
    return {"ok": True}


# ------------------------------------------------------------------ Sessions en base SQLite

def create_session(user_id: str, active_org_id: str | None = None, ip: str | None = None,
                   user_agent: str | None = None, db_path: str | None = None) -> tuple[str, dict[str, Any]]:
    """Crée une nouvelle session en base (jeton token_urlsafe(32), seule l'empreinte SHA-256 est stockée)."""
    raw_token = secrets.token_urlsafe(32)
    token_hash = db.hash_token(raw_token)
    session_id = "s_" + secrets.token_hex(12)
    now = int(time.time())
    expires_at = now + SESSION_TTL

    db.execute(
        "INSERT INTO sessions (id, token_hash, user_id, active_org_id, ip, user_agent, expires_at, last_seen_at, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
        (session_id, token_hash, user_id, active_org_id, ip, user_agent, expires_at, now, now),
        db_path=db_path,
    )
    session_dict = {
        "id": session_id,
        "user_id": user_id,
        "active_org_id": active_org_id,
        "expires_at": expires_at,
        "last_seen_at": now,
        "created_at": now,
    }
    return raw_token, session_dict


def get_session_by_token(raw_token: str | None, db_path: str | None = None) -> dict[str, Any] | None:
    """Récupère une session active depuis son jeton brut, et renouvelle la fenêtre d'inactivité (2 h)."""
    if not raw_token:
        return None
    token_hash = db.hash_token(raw_token)
    now = int(time.time())

    row = db.query_one("SELECT * FROM sessions WHERE token_hash = ?;", (token_hash,), db_path=db_path)
    if not row:
        return None

    if now > row["expires_at"]:
        db.execute("DELETE FROM sessions WHERE id = ?;", (row["id"],), db_path=db_path)
        return None

    new_expires_at = now + SESSION_TTL
    db.execute(
        "UPDATE sessions SET expires_at = ?, last_seen_at = ? WHERE id = ?;",
        (new_expires_at, now, row["id"]),
        db_path=db_path,
    )
    sess = dict(row)
    sess["expires_at"] = new_expires_at
    sess["last_seen_at"] = now
    return sess


def get_user_from_token(raw_token: str | None, db_path: str | None = None) -> tuple[dict, dict | None, dict] | None:
    """Retourne (user, active_org, session) pour un jeton de session valide, ou None."""
    sess = get_session_by_token(raw_token, db_path=db_path)
    if not sess:
        return None

    user = db.query_one(
        "SELECT id, email, is_superadmin, is_active, totp_enabled, created_at FROM users WHERE id = ?;",
        (sess["user_id"],),
        db_path=db_path,
    )
    if not user or not user["is_active"]:
        return None

    org = None
    if sess["active_org_id"]:
        org = db.query_one(
            "SELECT id, name, slug, network, is_suspended FROM orgs WHERE id = ?;",
            (sess["active_org_id"],),
            db_path=db_path,
        )

    return dict(user), dict(org) if org else None, sess


def delete_session(raw_token: str | None, ip: str | None = None, db_path: str | None = None) -> None:
    """Supprime la session courante."""
    if not raw_token:
        return
    token_hash = db.hash_token(raw_token)
    sess = db.query_one("SELECT * FROM sessions WHERE token_hash = ?;", (token_hash,), db_path=db_path)
    if sess:
        db.execute("DELETE FROM sessions WHERE id = ?;", (sess["id"],), db_path=db_path)
        log_audit("auth.logout", org_id=sess["active_org_id"], user_id=sess["user_id"], ip=ip, db_path=db_path)


def delete_all_sessions(user_id: str, ip: str | None = None, db_path: str | None = None) -> None:
    """Déconnecte toutes les sessions d'un utilisateur (« déconnecter toutes mes sessions »)."""
    db.execute("DELETE FROM sessions WHERE user_id = ?;", (user_id,), db_path=db_path)
    log_audit("auth.logout_all", user_id=user_id, ip=ip, db_path=db_path)


# ------------------------------------------------------------------ Inscription et Connexion

def is_signup_open() -> bool:
    """Vérifie si les inscriptions libres sont autorisées (SIGNUP_OPEN != 0)."""
    val = os.environ.get("SIGNUP_OPEN", "1").strip().lower()
    return val not in {"0", "false", "no", "off"}


def signup(email: str, password: str, org_name: str | None = None,
           invite_token: str | None = None, ip: str | None = None,
           user_agent: str | None = None, db_path: str | None = None) -> dict[str, Any]:
    """Crée un nouvel utilisateur et son organisation (rôle owner) de manière atomique dans db.transaction().

    Si SIGNUP_OPEN=0, l'inscription requiert obligatoirement un invite_token valide.
    """
    clean_email = validate_email(email)
    validate_password(password)

    if not is_signup_open() and not invite_token:
        raise AuthError("Inscriptions fermées : invitation requise", 403)

    existing = db.query_one(
        "SELECT id FROM users WHERE email = ? COLLATE NOCASE;",
        (clean_email,),
        db_path=db_path,
    )
    if existing:
        raise AuthError("Cette adresse email est déjà utilisée", 409)

    user_id = "u_" + secrets.token_hex(12)
    pwd_hash = db.hash_password(password)
    now = int(time.time())

    with db.transaction(db_path):
        if invite_token:
            token_hash = db.hash_token(invite_token)
            inv = db.query_one("SELECT * FROM invites WHERE token_hash = ?;", (token_hash,), db_path=db_path)
            if not inv:
                raise AuthError("Invitation introuvable", 404)
            if inv["used_at"] is not None:
                raise AuthError("Invitation déjà utilisée", 400)
            if now > inv["expires_at"]:
                raise AuthError("Invitation expirée", 400)
            if inv["email"].lower() != clean_email.lower():
                raise AuthError("Cette invitation est destinée à une autre adresse email", 400)

            # Création utilisateur
            db.execute(
                "INSERT INTO users (id, email, password_hash, is_superadmin, is_active, created_at, updated_at) "
                "VALUES (?, ?, ?, 0, 1, ?, ?);",
                (user_id, clean_email, pwd_hash, now, now),
                db_path=db_path,
            )
            # Rejoint l'organisation de l'invitation avec le rôle prévu (consommation atomique du lien)
            cur = db.execute("UPDATE invites SET used_at = ? WHERE id = ? AND used_at IS NULL;",
                             (now, inv["id"]), db_path=db_path)
            if cur.rowcount != 1:
                raise AuthError("Invitation déjà utilisée", 400)
            member_id = "m_" + secrets.token_hex(12)
            db.execute(
                "INSERT INTO members (id, org_id, user_id, role, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?);",
                (member_id, inv["org_id"], user_id, inv["role"], now, now),
                db_path=db_path,
            )
            org_id = inv["org_id"]
            org_row = db.query_one("SELECT name FROM orgs WHERE id = ?;", (org_id,), db_path=db_path)
            final_org_name = org_row["name"] if org_row else "Organisation"

            log_audit("auth.signup_invite", org_id=org_id, user_id=user_id,
                      details={"email": clean_email, "invite_id": inv["id"], "role": inv["role"]},
                      ip=ip, db_path=db_path)
        else:
            # Inscription standard : utilisateur + organisation propre (owner)
            org_id = "o_" + secrets.token_hex(12)
            if org_name is not None and not isinstance(org_name, str):
                raise AuthError("Nom d'organisation invalide", 400)
            final_org_name = "".join(c for c in (org_name or f"Organisation {clean_email.split('@')[0]}")
                                     if c.isprintable()).strip()[:80]
            if not final_org_name:
                raise AuthError("Nom d'organisation invalide", 400)
            slug = "org-" + secrets.token_hex(6)

            db.execute(
                "INSERT INTO users (id, email, password_hash, is_superadmin, is_active, created_at, updated_at) "
                "VALUES (?, ?, ?, 0, 1, ?, ?);",
                (user_id, clean_email, pwd_hash, now, now),
                db_path=db_path,
            )
            db.execute(
                "INSERT INTO orgs (id, name, slug, created_at, updated_at) VALUES (?, ?, ?, ?, ?);",
                (org_id, final_org_name, slug, now, now),
                db_path=db_path,
            )
            member_id = "m_" + secrets.token_hex(12)
            db.execute(
                "INSERT INTO members (id, org_id, user_id, role, created_at, updated_at) VALUES (?, ?, ?, 'owner', ?, ?);",
                (member_id, org_id, user_id, now, now),
                db_path=db_path,
            )
            log_audit("auth.signup", org_id=org_id, user_id=user_id,
                      details={"email": clean_email, "org_id": org_id, "org_name": final_org_name},
                      ip=ip, db_path=db_path)

        # Nouvelle session pour le nouvel inscrit
        raw_token, sess = create_session(user_id, active_org_id=org_id, ip=ip, user_agent=user_agent, db_path=db_path)

    return {
        "token": raw_token,
        "session": sess,
        "user": {"id": user_id, "email": clean_email, "is_superadmin": 0, "totp_enabled": 0},
        "org": {"id": org_id, "name": final_org_name},
    }


def _record_failure(user_id: str, now: int, db_path: str | None) -> bool:
    """Compte un échec en une seule requête SQL (atomique face aux rafales parallèles). Retourne True si verrouillé."""
    db.execute(
        "UPDATE users SET failed_login_attempts = failed_login_attempts + 1, "
        "locked_until = CASE WHEN failed_login_attempts + 1 >= ? THEN ? ELSE locked_until END, "
        "updated_at = ? WHERE id = ?;",
        (MAX_LOGIN_ATTEMPTS, now + LOCKOUT_DURATION, now, user_id),
        db_path=db_path,
    )
    row = db.query_one("SELECT locked_until FROM users WHERE id = ?;", (user_id,), db_path=db_path)
    return bool(row and row["locked_until"] and row["locked_until"] > now)


def login(email: str, password: str, totp_code: str | None = None,
          ip: str | None = None, user_agent: str | None = None,
          db_path: str | None = None) -> dict[str, Any]:
    """Authentifie un utilisateur avec protection anti-énumération, anti-bruteforce (verrou 15 min) et 2FA.

    - Même message et temps de réponse identique (scrypt factice) si l'email n'existe pas.
    - Chaque tentative est enregistrée dans login_events.
    """
    clean_email = email.strip().lower() if isinstance(email, str) else ""
    now = int(time.time())

    user = db.query_one(
        "SELECT * FROM users WHERE email = ? COLLATE NOCASE;",
        (clean_email,),
        db_path=db_path,
    ) if clean_email else None

    # 1. Email inexistant -> vérification d'un hash scrypt factice (temps identique, anti-énumération)
    if not user:
        if isinstance(password, str):
            db.verify_password(password, DUMMY_PASSWORD_HASH)
        db.execute(
            "INSERT INTO login_events (user_id, email, ip, user_agent, success, reason, created_at) "
            "VALUES (NULL, ?, ?, ?, 0, 'user_not_found', ?);",
            (clean_email, ip, user_agent, now),
            db_path=db_path,
        )
        raise AuthError("Identifiants invalides", 401)

    # 2. Compte désactivé -> même temps de calcul et message générique
    if not user["is_active"]:
        db.verify_password(password, DUMMY_PASSWORD_HASH)
        db.execute(
            "INSERT INTO login_events (user_id, email, ip, user_agent, success, reason, created_at) "
            "VALUES (?, ?, ?, ?, 0, 'inactive', ?);",
            (user["id"], clean_email, ip, user_agent, now),
            db_path=db_path,
        )
        raise AuthError("Identifiants invalides", 401)

    # 3. Compte verrouillé temporairement (15 min après 5 échecs)
    if user["locked_until"] and user["locked_until"] > now:
        db.verify_password(password, DUMMY_PASSWORD_HASH)
        db.execute(
            "INSERT INTO login_events (user_id, email, ip, user_agent, success, reason, created_at) "
            "VALUES (?, ?, ?, ?, 0, 'locked', ?);",
            (user["id"], clean_email, ip, user_agent, now),
            db_path=db_path,
        )
        raise AuthError("Identifiants invalides", 401)

    # 4. Vérification du mot de passe réel
    pwd_matches = db.verify_password(password, user["password_hash"]) if isinstance(password, str) else False
    if not pwd_matches:
        locked = _record_failure(user["id"], now, db_path)
        reason = "locked_triggered" if locked else "bad_password"
        db.execute(
            "INSERT INTO login_events (user_id, email, ip, user_agent, success, reason, created_at) "
            "VALUES (?, ?, ?, ?, 0, ?, ?);",
            (user["id"], clean_email, ip, user_agent, reason, now),
            db_path=db_path,
        )
        raise AuthError("Identifiants invalides", 401)

    # 5. Double authentification (TOTP) si activée sur le compte
    if user["totp_enabled"]:
        if not totp_code:
            db.execute(
                "INSERT INTO login_events (user_id, email, ip, user_agent, success, reason, created_at) "
                "VALUES (?, ?, ?, ?, 0, 'totp_required', ?);",
                (user["id"], clean_email, ip, user_agent, now),
                db_path=db_path,
            )
            return {"totp_required": True, "email": clean_email}

        totp_ok = verify_totp(user["totp_secret"], totp_code, user_id=user["id"], now=now, db_path=db_path)
        if not totp_ok:
            _record_failure(user["id"], now, db_path)
            db.execute(
                "INSERT INTO login_events (user_id, email, ip, user_agent, success, reason, created_at) "
                "VALUES (?, ?, ?, ?, 0, 'totp_invalid', ?);",
                (user["id"], clean_email, ip, user_agent, now),
                db_path=db_path,
            )
            raise AuthError("Identifiants invalides", 401)

    # 6. Connexion réussie : réinitialisation des échecs et création de session
    db.execute(
        "UPDATE users SET failed_login_attempts = 0, locked_until = NULL, updated_at = ? WHERE id = ?;",
        (now, user["id"]),
        db_path=db_path,
    )
    db.execute(
        "INSERT INTO login_events (user_id, email, ip, user_agent, success, reason, created_at) "
        "VALUES (?, ?, ?, ?, 1, 'success', ?);",
        (user["id"], clean_email, ip, user_agent, now),
        db_path=db_path,
    )

    # Organisation active principale
    membership = db.query_one(
        "SELECT org_id FROM members WHERE user_id = ? ORDER BY created_at ASC LIMIT 1;",
        (user["id"],),
        db_path=db_path,
    )
    active_org_id = membership["org_id"] if membership else None

    raw_token, sess = create_session(user["id"], active_org_id=active_org_id, ip=ip,
                                     user_agent=user_agent, db_path=db_path)
    log_audit("auth.login", org_id=active_org_id, user_id=user["id"],
              details={"email": clean_email}, ip=ip, db_path=db_path)

    return {
        "token": raw_token,
        "session": sess,
        "user": {
            "id": user["id"],
            "email": user["email"],
            "is_superadmin": user["is_superadmin"],
            "totp_enabled": user["totp_enabled"],
        },
        "org_id": active_org_id,
    }


# ------------------------------------------------------------------ Changement de mot de passe

def change_password(user_id: str, old_password: str, new_password: str,
                    current_token: str | None = None, ip: str | None = None,
                    db_path: str | None = None) -> dict[str, bool]:
    """Change le mot de passe de l'utilisateur, vérifie l'ancien, et révoque toutes les autres sessions."""
    user = db.query_one("SELECT * FROM users WHERE id = ?;", (user_id,), db_path=db_path)
    if not user:
        raise AuthError("Utilisateur introuvable", 404)

    if not db.verify_password(old_password, user["password_hash"]):
        raise AuthError("Ancien mot de passe incorrect", 400)

    validate_password(new_password)
    new_hash = db.hash_password(new_password)
    now = int(time.time())

    with db.transaction(db_path):
        db.execute(
            "UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?;",
            (new_hash, now, user_id),
            db_path=db_path,
        )
        # Invalidation des autres sessions
        if current_token:
            curr_hash = db.hash_token(current_token)
            db.execute(
                "DELETE FROM sessions WHERE user_id = ? AND token_hash != ?;",
                (user_id, curr_hash),
                db_path=db_path,
            )
        else:
            db.execute("DELETE FROM sessions WHERE user_id = ?;", (user_id,), db_path=db_path)

        log_audit("auth.password_change", user_id=user_id, ip=ip, db_path=db_path)

    return {"ok": True}


# ------------------------------------------------------------------ Invitations (usage unique 7 jours)

def create_invite(org_id: str, email: str, role: str, invited_by: str | None = None,
                  ip: str | None = None, db_path: str | None = None) -> tuple[str, dict[str, Any]]:
    """Crée une invitation à usage unique valable 7 jours."""
    clean_email = validate_email(email)
    if role not in ("owner", "admin", "approver", "viewer"):
        raise AuthError("Rôle invalide", 400)

    # Respect de la clé étrangère : invited_by doit exister dans users, sinon NULL
    valid_inviter = None
    if invited_by:
        user_row = db.query_one("SELECT id FROM users WHERE id = ?;", (invited_by,), db_path=db_path)
        if user_row:
            valid_inviter = user_row["id"]

    raw_token = secrets.token_urlsafe(32)
    token_hash = db.hash_token(raw_token)
    now = int(time.time())
    expires_at = now + INVITE_TTL
    invite_id = "inv_" + secrets.token_hex(12)

    db.execute(
        "INSERT INTO invites (id, org_id, email, role, token_hash, invited_by, expires_at, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?);",
        (invite_id, org_id, clean_email, role, token_hash, valid_inviter, expires_at, now),
        db_path=db_path,
    )
    log_audit("auth.invite_create", org_id=org_id, user_id=valid_inviter,
              details={"email": clean_email, "role": role}, ip=ip, db_path=db_path)

    return raw_token, {
        "id": invite_id,
        "org_id": org_id,
        "email": clean_email,
        "role": role,
        "expires_at": expires_at,
    }


def accept_invite(token: str, password: str | None = None, user_id: str | None = None,
                  ip: str | None = None, user_agent: str | None = None,
                  db_path: str | None = None) -> dict[str, Any]:
    """Valide et consomme une invitation à usage unique."""
    if not token:
        raise AuthError("Jeton d'invitation manquant", 400)
    token_hash = db.hash_token(token)
    now = int(time.time())

    inv = db.query_one("SELECT * FROM invites WHERE token_hash = ?;", (token_hash,), db_path=db_path)
    if not inv:
        raise AuthError("Invitation introuvable", 404)
    if inv["used_at"] is not None:
        raise AuthError("Invitation déjà utilisée", 400)
    if now > inv["expires_at"]:
        raise AuthError("Invitation expirée", 400)

    with db.transaction(db_path):
        # Consommation atomique : deux requêtes simultanées ne peuvent pas utiliser le même lien.
        cur = db.execute("UPDATE invites SET used_at = ? WHERE id = ? AND used_at IS NULL;",
                         (now, inv["id"]), db_path=db_path)
        if cur.rowcount != 1:
            raise AuthError("Invitation déjà utilisée", 400)

        final_user_id = user_id
        if final_user_id:
            user = db.query_one("SELECT * FROM users WHERE id = ?;", (final_user_id,), db_path=db_path)
            if not user:
                raise AuthError("Utilisateur introuvable", 404)
            # Le lien ne vaut que pour le compte invité : un autre compte connecté ne peut pas l'utiliser.
            if user["email"].lower() != inv["email"].lower():
                raise AuthError("Cette invitation est destinée à une autre adresse email", 403)
        else:
            if not password:
                raise AuthError("Mot de passe requis pour créer votre compte", 400)
            validate_password(password)
            existing = db.query_one("SELECT id FROM users WHERE email = ? COLLATE NOCASE;", (inv["email"],), db_path=db_path)
            if existing:
                # Jamais de session sur un compte existant à partir d'un simple lien (prise de compte) :
                # le titulaire doit se connecter (mot de passe + 2FA) puis accepter l'invitation.
                raise AuthError("Un compte existe déjà pour cette adresse : connectez-vous puis acceptez l'invitation", 409)
            else:
                final_user_id = "u_" + secrets.token_hex(12)
                pwd_hash = db.hash_password(password)
                db.execute(
                    "INSERT INTO users (id, email, password_hash, is_superadmin, is_active, created_at, updated_at) "
                    "VALUES (?, ?, ?, 0, 1, ?, ?);",
                    (final_user_id, inv["email"], pwd_hash, now, now),
                    db_path=db_path,
                )

        # Ajout comme membre de l'organisation
        member = db.query_one("SELECT id FROM members WHERE org_id = ? AND user_id = ?;", (inv["org_id"], final_user_id), db_path=db_path)
        if not member:
            member_id = "m_" + secrets.token_hex(12)
            db.execute(
                "INSERT INTO members (id, org_id, user_id, role, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?);",
                (member_id, inv["org_id"], final_user_id, inv["role"], now, now),
                db_path=db_path,
            )

        log_audit("auth.invite_accept", org_id=inv["org_id"], user_id=final_user_id,
                  details={"email": inv["email"], "role": inv["role"]}, ip=ip, db_path=db_path)

        raw_token, sess = create_session(final_user_id, active_org_id=inv["org_id"],
                                         ip=ip, user_agent=user_agent, db_path=db_path)

    return {
        "token": raw_token,
        "session": sess,
        "user_id": final_user_id,
        "org_id": inv["org_id"],
        "role": inv["role"],
    }


# ------------------------------------------------------------------ Super-administrateur

def create_superadmin(email: str, password: str, db_path: str | None = None) -> dict[str, Any]:
    """Crée ou met à jour le super-administrateur de la plateforme."""
    clean_email = validate_email(email)
    validate_password(password)
    db.init_db(db_path)
    now = int(time.time())
    pwd_hash = db.hash_password(password)

    with db.transaction(db_path):
        existing = db.query_one("SELECT * FROM users WHERE email = ? COLLATE NOCASE;", (clean_email,), db_path=db_path)
        if existing:
            user_id = existing["id"]
            db.execute(
                "UPDATE users SET password_hash = ?, is_superadmin = 1, is_active = 1, updated_at = ? WHERE id = ?;",
                (pwd_hash, now, user_id),
                db_path=db_path,
            )
        else:
            user_id = "u_" + secrets.token_hex(12)
            db.execute(
                "INSERT INTO users (id, email, password_hash, is_superadmin, is_active, created_at, updated_at) "
                "VALUES (?, ?, ?, 1, 1, ?, ?);",
                (user_id, clean_email, pwd_hash, now, now),
                db_path=db_path,
            )

        # Organisation système de la plateforme
        admin_org = db.query_one("SELECT id FROM orgs WHERE slug = 'platform-admin';", db_path=db_path)
        if not admin_org:
            org_id = "o_" + secrets.token_hex(12)
            db.execute(
                "INSERT INTO orgs (id, name, slug, created_at, updated_at) VALUES (?, 'VaultGuard Platform', 'platform-admin', ?, ?);",
                (org_id, now, now),
                db_path=db_path,
            )
        else:
            org_id = admin_org["id"]

        member = db.query_one("SELECT id FROM members WHERE org_id = ? AND user_id = ?;", (org_id, user_id), db_path=db_path)
        if not member:
            member_id = "m_" + secrets.token_hex(12)
            db.execute(
                "INSERT INTO members (id, org_id, user_id, role, created_at, updated_at) VALUES (?, ?, ?, 'owner', ?, ?);",
                (member_id, org_id, user_id, now, now),
                db_path=db_path,
            )

        log_audit("auth.create_admin", org_id=org_id, user_id=user_id,
                  details={"email": clean_email}, db_path=db_path)

    return {"id": user_id, "email": clean_email, "is_superadmin": 1}
