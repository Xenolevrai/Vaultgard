"""db.py — Persistance SQLite pour VaultGuard v3.

Exigences de sécurité et d'architecture :
  - Python stdlib uniquement (sqlite3, hashlib, hmac)
  - Une connexion par thread (threading.local)
  - Mode WAL + clés étrangères activées (PRAGMA foreign_keys = ON)
  - Requêtes paramétrées avec '?' (aucune concaténation de texte utilisateur)
  - Stockage exclusif d'empreintes pour les secrets :
      * mot de passe : scrypt (réutilise hash_password / verify_password de server.py)
      * jetons de session, clés API, invitations : SHA-256
  - DB_PATH configurable (défaut : data/vaultguard.db), dossier créé automatiquement
  - Création du schéma idempotente (CREATE TABLE/INDEX IF NOT EXISTS)
  - Fonctions utilitaires : connect, execute, query_one, query_all, transaction
"""
from __future__ import annotations

import base64
import contextlib
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sqlite3
import threading
from typing import Any, Generator, Sequence

DEFAULT_DB_PATH = "data/vaultguard.db"

_local = threading.local()

# ------------------------------------------------------------------ Schéma SQL v3

SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- 1. Utilisateurs
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT UNIQUE NOT NULL COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    is_superadmin INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1,
    totp_secret TEXT,
    totp_enabled INTEGER NOT NULL DEFAULT 0,
    failed_login_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until INTEGER,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

-- 2. Organisations (espaces clients)
CREATE TABLE IF NOT EXISTS orgs (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    slug TEXT UNIQUE,
    network TEXT NOT NULL DEFAULT 'mock',
    vault_address TEXT,
    canary_address TEXT,
    is_suspended INTEGER NOT NULL DEFAULT 0,
    -- Montants en gwei entiers (1 AVAX = 10^9 gwei ; x 10^9 = wei on-chain) : jamais de flottants,
    -- et un entier SQLite (2^63) en wei plafonnerait à 9,2 AVAX.
    max_tx_gwei INTEGER NOT NULL DEFAULT 100000000 CHECK (max_tx_gwei >= 0),
    max_daily_gwei INTEGER NOT NULL DEFAULT 300000000 CHECK (max_daily_gwei >= 0),
    human_threshold_gwei INTEGER NOT NULL DEFAULT 50000000 CHECK (human_threshold_gwei >= 0),
    activation_delay INTEGER NOT NULL DEFAULT 86400,
    circuit_breaker_limit INTEGER NOT NULL DEFAULT 5,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

-- 3. Membres d'organisations avec rôle strict
CREATE TABLE IF NOT EXISTS members (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('owner', 'admin', 'approver', 'viewer')),
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    UNIQUE(org_id, user_id)
);

-- 4. Invitations par lien unique (7 jours)
CREATE TABLE IF NOT EXISTS invites (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
    email TEXT NOT NULL COLLATE NOCASE,
    role TEXT NOT NULL CHECK (role IN ('owner', 'admin', 'approver', 'viewer')),
    token_hash TEXT UNIQUE NOT NULL,
    invited_by TEXT REFERENCES users(id) ON DELETE SET NULL,
    expires_at INTEGER NOT NULL,
    used_at INTEGER,
    created_at INTEGER NOT NULL
);

-- 5. Sessions côté serveur
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    token_hash TEXT UNIQUE NOT NULL,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    active_org_id TEXT REFERENCES orgs(id) ON DELETE SET NULL,
    ip TEXT,
    user_agent TEXT,
    expires_at INTEGER NOT NULL,
    last_seen_at INTEGER NOT NULL,
    created_at INTEGER NOT NULL
);

-- 6. Clés API agents IA
CREATE TABLE IF NOT EXISTS api_keys (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    key_prefix TEXT NOT NULL,
    key_hash TEXT UNIQUE NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    quarantined_until INTEGER,
    quarantine_reason TEXT,
    last_used_at INTEGER,
    created_by TEXT REFERENCES users(id) ON DELETE SET NULL,
    created_at INTEGER NOT NULL
);

-- 7. Fournisseurs autorisés (carnet d'adresses)
CREATE TABLE IF NOT EXISTS suppliers (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    address TEXT NOT NULL,
    active_after INTEGER NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    UNIQUE(org_id, address)
);

-- 8. Demandes de paiement (historique et arbitrage)
CREATE TABLE IF NOT EXISTS payments (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
    api_key_id TEXT REFERENCES api_keys(id) ON DELETE SET NULL,
    requested_by TEXT REFERENCES users(id) ON DELETE SET NULL,
    recipient TEXT NOT NULL,
    amount_gwei INTEGER NOT NULL CHECK (amount_gwei >= 0),
    memo TEXT NOT NULL DEFAULT '',
    user_request TEXT NOT NULL DEFAULT '',
    documents_json TEXT NOT NULL DEFAULT '[]',
    decision TEXT NOT NULL CHECK (decision IN ('allowed', 'pending_review', 'blocked')),
    reasons_json TEXT NOT NULL DEFAULT '[]',
    chain_status TEXT NOT NULL DEFAULT 'none',
    tx_hash TEXT,
    reviewed_by TEXT REFERENCES users(id) ON DELETE SET NULL,
    reviewed_at INTEGER,
    review_action TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

-- 9. Journal d'audit chaîné par hash, en ajout seul.
-- Pas de clés étrangères : supprimer un utilisateur ou une organisation ne doit ni effacer ni modifier
-- le journal (sinon la chaîne d'empreintes casse et les preuves disparaissent).
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id TEXT,
    user_id TEXT,
    api_key_id TEXT,
    action TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}',
    ip TEXT,
    prev_hash TEXT NOT NULL,
    entry_hash TEXT NOT NULL,
    created_at INTEGER NOT NULL
);

-- 10. Événements de connexion (anti-bruteforce)
CREATE TABLE IF NOT EXISTS login_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
    email TEXT NOT NULL COLLATE NOCASE,
    ip TEXT,
    user_agent TEXT,
    success INTEGER NOT NULL,
    reason TEXT,
    created_at INTEGER NOT NULL
);

-- Index d'optimisation
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_members_user ON members(user_id);
CREATE INDEX IF NOT EXISTS idx_members_org ON members(org_id);
CREATE INDEX IF NOT EXISTS idx_invites_org ON invites(org_id);
CREATE INDEX IF NOT EXISTS idx_invites_hash ON invites(token_hash);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_hash ON sessions(token_hash);
CREATE INDEX IF NOT EXISTS idx_api_keys_org ON api_keys(org_id);
CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON api_keys(key_hash);
CREATE INDEX IF NOT EXISTS idx_suppliers_org ON suppliers(org_id);
CREATE INDEX IF NOT EXISTS idx_payments_org ON payments(org_id);
CREATE INDEX IF NOT EXISTS idx_payments_created ON payments(created_at);
CREATE INDEX IF NOT EXISTS idx_audit_org ON audit(org_id);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit(created_at);
CREATE INDEX IF NOT EXISTS idx_login_events_email ON login_events(email);
-- 11. Codes TOTP utilisés (anti-rejeu RFC 6238)
CREATE TABLE IF NOT EXISTS totp_used_codes (
    user_id TEXT NOT NULL,
    code TEXT NOT NULL,
    used_at INTEGER NOT NULL,
    PRIMARY KEY (user_id, code)
);
CREATE INDEX IF NOT EXISTS idx_totp_used_user ON totp_used_codes(user_id);

-- 12. Coffre simulé par organisation (état persistant, isolé)
CREATE TABLE IF NOT EXISTS org_vault_states (
    org_id TEXT PRIMARY KEY REFERENCES orgs(id) ON DELETE CASCADE,
    balance_gwei INTEGER NOT NULL DEFAULT 10000000000 CHECK (balance_gwei >= 0),
    spent_today_gwei INTEGER NOT NULL DEFAULT 0 CHECK (spent_today_gwei >= 0),
    spent_day INTEGER NOT NULL DEFAULT -1,
    blocked_today INTEGER NOT NULL DEFAULT 0,
    blocked_day INTEGER NOT NULL DEFAULT -1,
    is_paused INTEGER NOT NULL DEFAULT 0,
    updated_at INTEGER NOT NULL
);

-- 13. Boîte de dépôt des factures : une adresse par organisation (inbox.py)
CREATE TABLE IF NOT EXISTS inboxes (
    org_id TEXT PRIMARY KEY REFERENCES orgs(id) ON DELETE CASCADE,
    alias TEXT UNIQUE NOT NULL,
    review_threshold_cents INTEGER NOT NULL DEFAULT 100000 CHECK (review_threshold_cents >= 0),
    created_at INTEGER NOT NULL
);

-- 14. Expéditeurs de confiance : seuls leurs mails sont lus
CREATE TABLE IF NOT EXISTS inbox_senders (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
    email TEXT NOT NULL COLLATE NOCASE,
    created_by TEXT REFERENCES users(id) ON DELETE SET NULL,
    created_at INTEGER NOT NULL,
    UNIQUE(org_id, email)
);

-- 15. Fournisseurs payés par virement : nom + IBAN de référence
CREATE TABLE IF NOT EXISTS payees (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    iban TEXT NOT NULL,
    active_after INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    UNIQUE(org_id, iban)
);

-- 16. Factures vérifiées. Aucun texte de facture : montant, numéro, empreintes, fin de l'IBAN.
CREATE TABLE IF NOT EXISTS invoice_checks (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
    sender_id TEXT,
    payee_id TEXT,
    payee_name TEXT NOT NULL DEFAULT '',
    invoice_number TEXT NOT NULL DEFAULT '',
    amount_cents INTEGER,
    currency TEXT NOT NULL DEFAULT '',
    iban_tail TEXT NOT NULL DEFAULT '',
    iban_sha256 TEXT NOT NULL DEFAULT '',
    file_sha256 TEXT NOT NULL DEFAULT '',
    fmt TEXT NOT NULL DEFAULT '',
    verdict TEXT NOT NULL CHECK (verdict IN ('ok', 'review', 'refused')),
    reasons_json TEXT NOT NULL DEFAULT '[]',
    reviewed_by TEXT REFERENCES users(id) ON DELETE SET NULL,
    reviewed_at INTEGER,
    review_action TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
-- 17. Compte bancaire de l'entreprise (celui qui paie les fournisseurs)
CREATE TABLE IF NOT EXISTS org_bank_accounts (
    org_id TEXT PRIMARY KEY REFERENCES orgs(id) ON DELETE CASCADE,
    holder TEXT NOT NULL,
    iban TEXT NOT NULL,
    updated_at INTEGER NOT NULL
);

-- 18. Fichiers de virements SEPA préparés. Le fichier n'est pas stocké : il se régénère à l'identique
-- à partir de ces lignes, et son empreinte est scellée (journal chaîné, puis Avalanche).
CREATE TABLE IF NOT EXISTS transfer_batches (
    id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
    created_by TEXT REFERENCES users(id) ON DELETE SET NULL,
    debtor_name TEXT NOT NULL,
    debtor_iban TEXT NOT NULL,
    tx_count INTEGER NOT NULL,
    total_cents INTEGER NOT NULL,
    file_sha256 TEXT NOT NULL,
    seal_status TEXT NOT NULL DEFAULT '',
    seal_tx TEXT NOT NULL DEFAULT '',
    seal_url TEXT NOT NULL DEFAULT '',
    sealed_at INTEGER,
    created_at INTEGER NOT NULL
);

-- Une facture ne peut figurer que dans un seul fichier : pas de double virement.
CREATE TABLE IF NOT EXISTS transfer_items (
    check_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL REFERENCES transfer_batches(id) ON DELETE CASCADE,
    org_id TEXT NOT NULL,
    position INTEGER NOT NULL,
    payee_name TEXT NOT NULL,
    iban TEXT NOT NULL,
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    reference TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_transfer_batches_org ON transfer_batches(org_id, created_at);
CREATE INDEX IF NOT EXISTS idx_transfer_items_batch ON transfer_items(batch_id);
CREATE INDEX IF NOT EXISTS idx_inbox_senders_org ON inbox_senders(org_id);
CREATE INDEX IF NOT EXISTS idx_payees_org ON payees(org_id);
CREATE INDEX IF NOT EXISTS idx_invoice_checks_org ON invoice_checks(org_id, created_at);

-- Un maillon ne peut avoir qu'un seul successeur : la chaîne ne peut pas bifurquer.
CREATE UNIQUE INDEX IF NOT EXISTS idx_audit_prev_unique ON audit(prev_hash);

-- Le journal d'audit est immuable, même pour le code applicatif.
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit
BEGIN SELECT RAISE(ABORT, 'audit is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit
BEGIN SELECT RAISE(ABORT, 'audit is append-only'); END;
"""


# ------------------------------------------------------------------ Hachage des secrets

# Source unique du hachage des mots de passe : server.py l'importe d'ici (importer server depuis db créerait
# un import circulaire dès que server utilisera la base).
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(dk).decode()


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, salt_b64, dk_b64 = stored.split("$")
        if algo != "scrypt":
            return False
        dk = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt_b64), n=2**14, r=8, p=1, dklen=32)
        return hmac.compare_digest(dk, base64.b64decode(dk_b64))
    except (ValueError, TypeError):
        return False


def hash_token(token: str) -> str:
    """Empreinte SHA-256 pour jetons de session, clés API et jetons d'invitation."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_token(token: str, stored_hash: str) -> bool:
    """Vérification en temps constant d'un jeton par rapport à son empreinte SHA-256."""
    calculated = hash_token(token)
    return hmac.compare_digest(calculated, stored_hash)


GENESIS_HASH = "0" * 64


def compute_audit_hash(prev_hash: str, created_at: int, org_id: str | None, user_id: str | None, action: str,
                       details_json: str, api_key_id: str | None = None, ip: str | None = None) -> str:
    """Calcule l'empreinte chaînée d'une entrée d'audit.

    Encodage JSON d'une liste : sans ambiguïté, contrairement à un séparateur « | » qu'un champ pourrait contenir.
    """
    payload = json.dumps([prev_hash, created_at, org_id, user_id, api_key_id, ip, action, details_json],
                         ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------ Chemins et connexions

def get_db_path() -> str:
    """Retourne le chemin configuré pour la base de données."""
    return os.environ.get("DB_PATH", DEFAULT_DB_PATH)


def _normalize_path(path: str | Path | None) -> str:
    if path is None:
        path = get_db_path()
    path_str = str(path)
    if path_str == ":memory:" or path_str.startswith("file:"):
        return path_str
    return str(Path(path_str).expanduser().resolve())


def _ensure_dir(path_key: str) -> None:
    if path_key != ":memory:" and not path_key.startswith("file:"):
        p = Path(path_key)
        p.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        # La base contient emails et empreintes : lisible par le seul compte du serveur.
        if not p.exists():
            p.touch(mode=0o600)


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Retourne une connexion SQLite active pour le thread courant.

    Active le mode WAL et le respect des contraintes de clés étrangères.
    """
    path_key = _normalize_path(db_path)
    _ensure_dir(path_key)

    conns = getattr(_local, "connections", None)
    if conns is None:
        conns = {}
        _local.connections = conns

    conn = conns.get(path_key)
    if conn is not None:
        try:
            conn.execute("SELECT 1;")
        except (sqlite3.ProgrammingError, sqlite3.OperationalError):
            conn = None

    if conn is None:
        conn = sqlite3.connect(path_key, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA foreign_keys = ON;")
        conns[path_key] = conn

    return conn


def close_connection(db_path: str | Path | None = None) -> None:
    """Ferme la connexion SQLite du thread courant pour le chemin donné."""
    path_key = _normalize_path(db_path)
    conns = getattr(_local, "connections", None)
    if conns and path_key in conns:
        try:
            conns[path_key].close()
        except Exception:
            pass
        del conns[path_key]


def close_all() -> None:
    """Ferme toutes les connexions du thread courant."""
    conns = getattr(_local, "connections", None)
    if conns:
        for c in list(conns.values()):
            try:
                c.close()
            except Exception:
                pass
        conns.clear()


# ------------------------------------------------------------------ Initialisation du schéma

def init_db(db_path: str | Path | None = None) -> None:
    """Crée le schéma de manière idempotente (tables, contraintes, index)."""
    conn = connect(db_path)
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    purge_stored_content(db_path)


def purge_stored_content(db_path: str | Path | None = None) -> int:
    """Zéro conservation : remplace par des empreintes SHA-256 les textes de factures et de consignes
    enregistrés par les versions précédentes. Renvoie le nombre de paiements nettoyés."""
    conn = connect(db_path)
    rows = conn.execute(
        "SELECT id, user_request, documents_json FROM payments "
        "WHERE documents_json LIKE '%\"content\"%' OR (user_request != '' AND user_request NOT LIKE 'sha256:%');"
    ).fetchall()
    for row in rows:
        try:
            docs = json.loads(row["documents_json"] or "[]")
        except ValueError:
            docs = []
        prints = []
        for index, d in enumerate(docs if isinstance(docs, list) else [], 1):
            if isinstance(d, dict) and "content" in d:
                content = str(d["content"])
                d = {"n": index, "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(), "chars": len(content)}
            prints.append(d)
        mandate = row["user_request"]
        if mandate and not mandate.startswith("sha256:"):
            mandate = "sha256:" + hashlib.sha256(mandate.encode("utf-8")).hexdigest()
        conn.execute("UPDATE payments SET user_request = ?, documents_json = ? WHERE id = ?;",
                     (mandate, json.dumps(prints), row["id"]))
    conn.commit()
    return len(rows)


# ------------------------------------------------------------------ Transactions et requêtes

@contextlib.contextmanager
def transaction(db_path: str | Path | None = None) -> Generator[sqlite3.Connection, None, None]:
    """Gestionnaire de contexte de transaction atomique.

    Valide (commit) automatiquement en sortie de bloc ou annule (rollback) en cas d'exception.
    Prend en charge l'imbrication dans le même thread.
    """
    conn = connect(db_path)
    depth = getattr(_local, "tx_depth", 0)
    _local.tx_depth = depth + 1
    try:
        if depth == 0:
            with conn:
                yield conn
        else:
            yield conn
    finally:
        _local.tx_depth = depth


def execute(
    sql: str,
    params: Sequence[Any] | dict[str, Any] = (),
    db_path: str | Path | None = None,
) -> sqlite3.Cursor:
    """Exécute une requête paramétrée.

    Valide immédiatement si appelée hors d'un bloc `transaction`.
    """
    conn = connect(db_path)
    try:
        cur = conn.execute(sql, params)
    except sqlite3.Error:
        # Une écriture refusée (contrainte d'unicité...) laisse sinon une transaction ouverte sur la connexion
        # de ce fil : elle garde le verrou d'écriture et toutes les autres requêtes échouent (« database is locked »).
        if getattr(_local, "tx_depth", 0) == 0:
            conn.rollback()
        raise
    if getattr(_local, "tx_depth", 0) == 0:
        conn.commit()
    return cur


def query_one(
    sql: str,
    params: Sequence[Any] | dict[str, Any] = (),
    db_path: str | Path | None = None,
) -> sqlite3.Row | None:
    """Exécute une requête de lecture et retourne le premier résultat ou None."""
    conn = connect(db_path)
    cur = conn.execute(sql, params)
    return cur.fetchone()


def query_all(
    sql: str,
    params: Sequence[Any] | dict[str, Any] = (),
    db_path: str | Path | None = None,
) -> list[sqlite3.Row]:
    """Exécute une requête de lecture et retourne tous les résultats."""
    conn = connect(db_path)
    cur = conn.execute(sql, params)
    return cur.fetchall()
