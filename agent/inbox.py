"""inbox.py — Boîte de dépôt des factures : une adresse mail par entreprise, vérification avant paiement.

L'entreprise transfère ses factures à l'adresse que VaultGuard lui fournit. Seuls les expéditeurs qu'elle a
déclarés sont lus (mail_agent.py). Pour chaque facture, `judge` rend un verdict :
    ok       bon à payer : fournisseur connu, IBAN habituel, montant cohérent
    review   une personne de l'entreprise doit trancher
    refused  signes de fraude : rien ne doit être payé
Aucun paiement n'est déclenché ici. Règlement visé : virement en euros vers l'IBAN du fournisseur.

Zéro conservation : la facture est lue en mémoire. La base garde le verdict, le montant, le numéro, les quatre
derniers caractères de l'IBAN et des empreintes SHA-256. Aucune raison enregistrée ne recopie le document.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import secrets
import sqlite3
import statistics
import threading
import time
import unicodedata
from decimal import Decimal, InvalidOperation
from typing import Any

try:
    import auth
    import db
    import firewall
    import fraud
    import registry
    from orgs import OrgError, check_org_writable
except ImportError:
    from agent import auth, db, firewall, fraud, registry
    from agent.orgs import OrgError, check_org_writable

DEFAULT_ADDRESS = "factures+{alias}@demo.vaultguard.local"
ALIAS_RE = r"[a-z0-9](?:[a-z0-9-]{1,38}[a-z0-9])"
EMAIL_RE = re.compile(r"^[a-z0-9._%+-]{1,64}@[a-z0-9](?:[a-z0-9.-]{0,180}[a-z0-9])?\.[a-z]{2,24}$")
MAX_SENDERS = 50
MAX_PAYEES = 500
MAX_CHECKS_PER_HOUR = 60
MAX_IGNORED_LOGGED_PER_HOUR = 20
MAX_THRESHOLD_CENTS = 100_000_000_00

# Longueur des IBAN par pays (registre SWIFT).
IBAN_LENGTHS = {
    "AD": 24, "AE": 23, "AL": 28, "AT": 20, "AZ": 28, "BA": 20, "BE": 16, "BG": 22, "BH": 22, "BR": 29, "BY": 28,
    "CH": 21, "CR": 22, "CY": 28, "CZ": 24, "DE": 22, "DK": 18, "DO": 28, "EE": 20, "EG": 29, "ES": 24, "FI": 18,
    "FO": 18, "FR": 27, "GB": 22, "GE": 22, "GI": 23, "GL": 18, "GR": 27, "GT": 28, "HR": 21, "HU": 28, "IE": 22,
    "IL": 23, "IQ": 23, "IS": 26, "IT": 27, "JO": 30, "KW": 30, "KZ": 20, "LB": 28, "LC": 32, "LI": 21, "LT": 20,
    "LU": 20, "LV": 21, "MC": 27, "MD": 24, "ME": 22, "MK": 19, "MR": 27, "MT": 31, "MU": 30, "NL": 18, "NO": 15,
    "PK": 24, "PL": 28, "PS": 29, "PT": 25, "QA": 29, "RO": 24, "RS": 22, "SA": 24, "SC": 31, "SE": 24, "SI": 19,
    "SK": 24, "SM": 27, "ST": 25, "SV": 28, "TL": 23, "TN": 24, "TR": 26, "UA": 29, "VA": 22, "VG": 24, "XK": 20,
}
_IBAN_START = re.compile(r"(?<![A-Z0-9])[A-Z]{2}\d{2}(?=[   \-./]?[A-Z0-9])")
# « FR76-3000-... » ou « FR76.3000... » reste un IBAN : ces séparateurs servent parfois à échapper à la lecture.
_IBAN_SEPARATORS = "-./"
_IBAN_SPACES = _IBAN_SEPARATORS +"   "

# Familles d'injection (firewall.INJECTION_PATTERNS) qui n'ont aucune raison d'être dans une vraie facture.
ATTACK_FAMILIES = {"override", "fake_system", "role_hijack", "secrecy", "secret_exfil", "encoded_payload"}
PRESSURE_FAMILIES = {"urgency", "new_payee", "drain", "split"}

LEVEL_RANK = {"ok": 0, "review": 1, "refused": 2}

# code -> (niveau, phrase pour tous, référence)
CATALOG = {
    "ok": ("ok", "Rien d'anormal : fournisseur connu, compte bancaire habituel, montant cohérent.", ""),
    "unreadable": ("review", "Le document n'a pas pu être lu automatiquement.", "Contrôle de format"),
    "several_invoices": ("review", "Le mail contient plusieurs factures : envoyez-les une par une.", "Contrôle de format"),
    "no_iban": ("review", "Aucun compte bancaire (IBAN) lisible sur la facture.", "Contrôle de cohérence"),
    "iban_invalid": ("review", "Le compte bancaire indiqué est mal formé (IBAN invalide).", "Contrôle de cohérence"),
    "unknown_supplier": ("review", "Ce fournisseur n'est pas dans votre liste.", "OWASP ASI02"),
    "iban_changed": ("refused", "Le compte bancaire n'est pas celui que vous avez enregistré pour ce fournisseur.",
                     "Fraude au changement de RIB"),
    "several_accounts": ("review", "Le document contient plusieurs comptes bancaires différents.", "Fraude au changement de RIB"),
    "name_mismatch": ("review", "Le compte bancaire est connu, mais la facture ne porte pas le nom de ce fournisseur.",
                      "Fraude au faux fournisseur"),
    "payee_recent": ("review", "Ce fournisseur vient d'être ajouté à votre liste : un contrôle humain est demandé.",
                     "Délai d'activation"),
    "layer_mismatch": ("refused", "La page que vous voyez et les données lues par les logiciels ne disent pas la même chose.",
                       "Fraude à la facture électronique (PDF / XML)"),
    "pdf_edited": ("review", "Ce PDF a été retouché après sa création.", "Document falsifié"),
    "supplier_lookalike": ("refused", "Le nom du vendeur imite celui d'un de vos fournisseurs, avec un autre compte bancaire.",
                           "Fraude au faux fournisseur"),
    "known_scam": ("refused", "Ce document a la forme d'une fausse facture d'annuaire ou de registre officiel.",
                   "Arnaque signalée par la DGCCRF"),
    "account_reported": ("review", "Ce compte bancaire a déjà été refusé pour fraude par une autre entreprise.",
                         "Alerte partagée entre entreprises"),
    "iban_foreign": ("review", "Société française, mais compte bancaire tenu à l'étranger.", "Cohérence pays / fournisseur"),
    "split_threshold": ("review", "Plusieurs factures du même fournisseur en 24 h dépassent ensemble votre seuil.",
                        "Fractionnement sous le seuil"),
    "company_id_missing": ("review", "La facture ne porte pas le numéro d'entreprise du vendeur (SIREN ou TVA), mention obligatoire.",
                           "Mentions légales"),
    "company_id_invalid": ("review", "Un numéro d'entreprise indiqué sur la facture (SIREN ou TVA) est faux.", "Mentions légales"),
    "company_unknown": ("review", "Le numéro d'entreprise de la facture n'existe pas dans l'annuaire public des entreprises.",
                        "Annuaire des entreprises"),
    "company_closed": ("review", "D'après l'annuaire public, une entreprise citée sur la facture a cessé son activité.",
                       "Annuaire des entreprises"),
    "company_name_mismatch": ("review", "Le numéro d'entreprise de la facture appartient à une société d'un autre nom.",
                              "Fraude au faux fournisseur"),
    "no_amount": ("review", "Le montant à payer n'a pas pu être lu.", "Contrôle de cohérence"),
    "currency": ("review", "La facture n'est pas en euros.", "Contrôle de cohérence"),
    "above_threshold": ("review", "Montant au-dessus de votre seuil : votre accord est demandé.", "Human-in-the-loop"),
    "amount_anomaly": ("review", "Le montant est inhabituel pour ce fournisseur.", "Détection d'anomalie"),
    "invoice_arithmetic": ("review", "Le total de la facture ne correspond pas à la somme de ses lignes.", "Contrôle de cohérence"),
    "duplicate": ("refused", "Cette facture a déjà été reçue.", "Fraude au double paiement"),
    "injection": ("refused", "Le document contient des instructions cachées destinées à tromper un assistant automatique.",
                  "OWASP LLM01"),
    "obfuscation": ("review", "Le document contient du texte camouflé (caractères invisibles ou lettres imitées).", "OWASP LLM01"),
    "pressure": ("review", "Le message insiste sur l'urgence ou annonce un changement de coordonnées bancaires.",
                 "Ingénierie sociale"),
}

_ORG_LOCKS: dict[str, threading.Lock] = {}
_ORG_LOCKS_GUARD = threading.Lock()


def _org_lock(org_id: str) -> threading.Lock:
    with _ORG_LOCKS_GUARD:
        return _ORG_LOCKS.setdefault(org_id, threading.Lock())


# ------------------------------------------------------------------ IBAN

def iban_valid(iban: str) -> bool:
    """Longueur du pays et clé de contrôle (modulo 97, ISO 13616)."""
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", iban) or IBAN_LENGTHS.get(iban[:2]) != len(iban):
        return False
    return int("".join(str(int(c, 36)) for c in iban[4:] + iban[:4])) % 97 == 1


def clean_iban(value: str) -> str:
    """IBAN saisi par un humain -> forme compacte en majuscules ; OrgError s'il est invalide."""
    if not isinstance(value, str):
        raise OrgError("IBAN requis")
    compact = re.sub(r"[\s  .-]", "", value).upper()
    if not iban_valid(compact):
        raise OrgError("IBAN invalide : vérifiez les chiffres (ex. FR76 3000 6000 0112 3456 7890 189)")
    return compact


def find_ibans(text: str) -> tuple[list[str], bool]:
    """(IBAN valides trouvés, sans doublon ; True si un texte annoncé comme IBAN est mal formé)."""
    upper = text.upper()
    found: list[str] = []
    malformed = False
    for m in _IBAN_START.finditer(upper):
        need = IBAN_LENGTHS.get(m.group(0)[:2])
        if not need:
            continue
        chars, i, spaced = [], m.start(), False
        while len(chars) < need and i < len(upper):
            c = upper[i]
            if c.isascii() and c.isalnum():
                chars.append(c)
                spaced = False
            elif c in _IBAN_SPACES and not spaced:
                spaced = True
            else:
                break
            i += 1
        candidate = "".join(chars)
        if iban_valid(candidate):
            if candidate not in found:
                found.append(candidate)
        elif "IBAN" in upper[max(0, m.start() - 40):m.start()]:
            malformed = True
    return found, malformed


def _plain(text: str) -> str:
    text = firewall.normalize(str(text)).lower().replace("œ", "oe").replace("æ", "ae")
    text = "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", text)


def _tail(iban: str) -> str:
    return iban[-4:]


def euros(cents: int) -> str:
    whole, part = divmod(abs(int(cents)), 100)
    return f"{whole:,}".replace(",", " ") + f",{part:02d} €"


def _readable(markup: str) -> str:
    text = re.sub(r"<(br|/p|/div|/tr|/li|/td|/h\d)[^>]*>", "\n", markup, flags=re.I)
    return html.unescape(re.sub(r"<[^>]{0,2000}>", " ", text)).replace("\xa0", " ")


# ------------------------------------------------------------------ Adresse de dépôt

def address_template() -> str:
    template = os.environ.get("INBOUND_ADDRESS", "").strip() or DEFAULT_ADDRESS
    return template if template.count("{alias}") == 1 and "@" in template else DEFAULT_ADDRESS


def address_for(alias: str) -> str:
    return address_template().replace("{alias}", alias)


def aliases_in(addresses: list[str]) -> list[str]:
    """Alias d'entreprise présents dans une liste d'adresses de destination."""
    head, tail = address_template().lower().split("{alias}")
    pattern = re.compile(re.escape(head) + "(" + ALIAS_RE + ")" + re.escape(tail))
    out: list[str] = []
    for address in addresses:
        m = pattern.fullmatch(address.strip().lower())
        if m and m.group(1) not in out:
            out.append(m.group(1))
    return out


def _new_alias(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", _plain(name)).strip("-")[:20].strip("-") or "entreprise"
    return base + "-" + "".join(secrets.choice("abcdefghjkmnpqrstuvwxyz23456789") for _ in range(6))


def ensure_inbox(org_id: str, db_path: str | None = None, alias: str | None = None) -> dict[str, Any]:
    """Boîte de l'organisation, créée au premier accès. L'alias contient une part aléatoire : il ne se devine pas."""
    row = db.query_one("SELECT * FROM inboxes WHERE org_id = ?;", (org_id,), db_path=db_path)
    if row:
        return dict(row)
    org = db.query_one("SELECT name FROM orgs WHERE id = ?;", (org_id,), db_path=db_path)
    if not org:
        raise OrgError("Organisation introuvable", 404)
    if alias is not None and not re.fullmatch(ALIAS_RE, alias):
        raise OrgError("Alias invalide")
    for _ in range(5):
        # OR IGNORE : une requête parallèle a pu créer la boîte, ou l'alias tiré est déjà pris (on en tire un autre).
        db.execute("INSERT OR IGNORE INTO inboxes (org_id, alias, created_at) VALUES (?, ?, ?);",
                   (org_id, alias or _new_alias(org["name"]), int(time.time())), db_path=db_path)
        row = db.query_one("SELECT * FROM inboxes WHERE org_id = ?;", (org_id,), db_path=db_path)
        if row:
            return dict(row)
        if alias:
            raise OrgError("Alias déjà utilisé", 409)
    raise OrgError("Création de la boîte impossible", 500)


def org_for_alias(alias: str, db_path: str | None = None) -> dict[str, Any] | None:
    row = db.query_one(
        "SELECT o.id, o.name, o.is_suspended, o.activation_delay, i.alias, i.review_threshold_cents "
        "FROM inboxes i JOIN orgs o ON o.id = i.org_id WHERE i.alias = ?;", (alias,), db_path=db_path)
    return dict(row) if row else None


def trusted_sender(org_id: str, email_address: str, db_path: str | None = None) -> dict[str, Any] | None:
    row = db.query_one("SELECT id, email FROM inbox_senders WHERE org_id = ? AND email = ?;",
                       (org_id, email_address.strip().lower()), db_path=db_path)
    return dict(row) if row else None


# ------------------------------------------------------------------ Réglages (routes /api/app/inbox*)

def get_inbox(org_id: str, db_path: str | None = None) -> dict[str, Any]:
    box = ensure_inbox(org_id, db_path=db_path)
    now = int(time.time())
    senders = db.query_all("SELECT id, email, created_at FROM inbox_senders WHERE org_id = ? ORDER BY email;",
                           (org_id,), db_path=db_path)
    ignored: dict[str, int] = {}
    for row in db.query_all("SELECT details_json FROM audit WHERE org_id = ? AND action = 'inbox.ignored' "
                            "AND created_at >= ?;", (org_id, now - 7 * 86400), db_path=db_path):
        try:
            reason = json.loads(row["details_json"] or "{}").get("reason", "")
        except ValueError:
            continue
        ignored[reason] = ignored.get(reason, 0) + 1
    try:
        import transfers
    except ImportError:
        from agent import transfers
    to_pay = transfers.payable(org_id, db_path=db_path)
    return {
        "bank": transfers.get_bank(org_id, db_path=db_path),
        "payable": {k: to_pay[k] for k in ("count", "total_cents", "skipped")},
        "batches": transfers.list_batches(org_id, db_path=db_path),
        "address": address_for(box["alias"]),
        "review_threshold_cents": box["review_threshold_cents"],
        "senders": [dict(s) for s in senders],
        "payees": list_payees(org_id, db_path=db_path),
        "ignored_7d": ignored,
        "checks": list_checks(org_id, db_path=db_path),
    }


def add_sender(org_id: str, user_id: str, email_address: str, ip: str | None = None,
               db_path: str | None = None) -> dict[str, Any]:
    check_org_writable(org_id, db_path=db_path)
    clean = email_address.strip().lower() if isinstance(email_address, str) else ""
    if not EMAIL_RE.fullmatch(clean):
        raise OrgError("Adresse mail invalide")
    sender_id = "snd_" + secrets.token_hex(8)
    with _org_lock(org_id):
        count = db.query_one("SELECT COUNT(*) AS c FROM inbox_senders WHERE org_id = ?;", (org_id,), db_path=db_path)
        if count and count["c"] >= MAX_SENDERS:
            raise OrgError(f"Limite de {MAX_SENDERS} expéditeurs atteinte")
        try:
            db.execute("INSERT INTO inbox_senders (id, org_id, email, created_by, created_at) VALUES (?, ?, ?, ?, ?);",
                       (sender_id, org_id, clean, user_id, int(time.time())), db_path=db_path)
        except sqlite3.IntegrityError:
            raise OrgError("Cette adresse est déjà autorisée", 409) from None
    auth.log_audit("inbox.sender_add", org_id=org_id, user_id=user_id, details={"sender_id": sender_id, "email": clean},
                   ip=ip, db_path=db_path)
    return {"id": sender_id, "email": clean}


def remove_sender(org_id: str, user_id: str, sender_id: str, ip: str | None = None,
                  db_path: str | None = None) -> dict[str, Any]:
    check_org_writable(org_id, db_path=db_path)
    row = db.query_one("SELECT email FROM inbox_senders WHERE id = ? AND org_id = ?;", (sender_id, org_id), db_path=db_path)
    if not row:
        raise OrgError("Expéditeur introuvable", 404)
    db.execute("DELETE FROM inbox_senders WHERE id = ? AND org_id = ?;", (sender_id, org_id), db_path=db_path)
    auth.log_audit("inbox.sender_remove", org_id=org_id, user_id=user_id,
                   details={"sender_id": sender_id, "email": row["email"]}, ip=ip, db_path=db_path)
    return {"ok": True}


def list_payees(org_id: str, db_path: str | None = None) -> list[dict[str, Any]]:
    now = int(time.time())
    out = []
    for row in db.query_all("SELECT * FROM payees WHERE org_id = ? ORDER BY name COLLATE NOCASE;", (org_id,), db_path=db_path):
        d = dict(row)
        d["is_active"] = d["active_after"] <= now
        d["remaining_seconds"] = max(0, d["active_after"] - now)
        out.append(d)
    return out


def add_payee(org_id: str, user_id: str, name: str, iban: str, ip: str | None = None,
              db_path: str | None = None) -> dict[str, Any]:
    """Ajoute un fournisseur. Comme pour le coffre, il n'est « habituel » qu'après le délai d'activation."""
    org = check_org_writable(org_id, db_path=db_path)
    clean_name = re.sub(r"\s+", " ", name).strip() if isinstance(name, str) else ""
    if not 2 <= len(clean_name) <= 80 or any(ord(c) < 32 for c in clean_name):
        raise OrgError("Nom du fournisseur : entre 2 et 80 caractères")
    compact = clean_iban(iban)
    payee_id = "pye_" + secrets.token_hex(8)
    now = int(time.time())
    with _org_lock(org_id):
        count = db.query_one("SELECT COUNT(*) AS c FROM payees WHERE org_id = ?;", (org_id,), db_path=db_path)
        if count and count["c"] >= MAX_PAYEES:
            raise OrgError(f"Limite de {MAX_PAYEES} fournisseurs atteinte")
        try:
            db.execute("INSERT INTO payees (id, org_id, name, iban, active_after, created_at) VALUES (?, ?, ?, ?, ?, ?);",
                       (payee_id, org_id, clean_name, compact, now + int(org["activation_delay"]), now), db_path=db_path)
        except sqlite3.IntegrityError:
            raise OrgError("Ce compte bancaire est déjà enregistré", 409) from None
        # L'entreprise adopte ce compte : son ancien refus n'est plus une alerte pour les autres.
        db.execute("DELETE FROM reported_accounts WHERE org_id = ? AND iban_sha256 = ?;", (org_id, _sha(compact)), db_path=db_path)
    auth.log_audit("payee.add", org_id=org_id, user_id=user_id,
                   details={"payee_id": payee_id, "name": clean_name, "iban_sha256": _sha(compact), "iban_tail": _tail(compact)},
                   ip=ip, db_path=db_path)
    return {"id": payee_id, "name": clean_name, "iban": compact, "active_after": now + int(org["activation_delay"])}


def remove_payee(org_id: str, user_id: str, payee_id: str, ip: str | None = None,
                 db_path: str | None = None) -> dict[str, Any]:
    check_org_writable(org_id, db_path=db_path)
    row = db.query_one("SELECT name, iban FROM payees WHERE id = ? AND org_id = ?;", (payee_id, org_id), db_path=db_path)
    if not row:
        raise OrgError("Fournisseur introuvable", 404)
    db.execute("DELETE FROM payees WHERE id = ? AND org_id = ?;", (payee_id, org_id), db_path=db_path)
    auth.log_audit("payee.remove", org_id=org_id, user_id=user_id,
                   details={"payee_id": payee_id, "name": row["name"], "iban_tail": _tail(row["iban"])},
                   ip=ip, db_path=db_path)
    return {"ok": True}


def set_threshold(org_id: str, user_id: str, cents: Any, ip: str | None = None,
                  db_path: str | None = None) -> dict[str, Any]:
    check_org_writable(org_id, db_path=db_path)
    if isinstance(cents, bool) or not isinstance(cents, int) or not 0 <= cents <= MAX_THRESHOLD_CENTS:
        raise OrgError("Seuil invalide : un montant en centimes, positif")
    ensure_inbox(org_id, db_path=db_path)
    db.execute("UPDATE inboxes SET review_threshold_cents = ? WHERE org_id = ?;", (cents, org_id), db_path=db_path)
    auth.log_audit("inbox.threshold", org_id=org_id, user_id=user_id, details={"review_threshold_cents": cents},
                   ip=ip, db_path=db_path)
    return {"review_threshold_cents": cents}


# ------------------------------------------------------------------ Factures vérifiées

def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def list_checks(org_id: str, limit: int = 100, db_path: str | None = None) -> list[dict[str, Any]]:
    rows = db.query_all("SELECT * FROM invoice_checks WHERE org_id = ? ORDER BY created_at DESC, rowid DESC LIMIT ?;",
                        (org_id, max(1, min(limit, 200))), db_path=db_path)
    trail: dict[str, list[dict[str, Any]]] = {}
    for a in db.query_all("SELECT action, details_json, entry_hash, created_at FROM audit WHERE org_id = ? AND action IN "
                          "('invoice.check', 'invoice.approve', 'invoice.reject') ORDER BY id;", (org_id,), db_path=db_path):
        try:
            check_id = json.loads(a["details_json"] or "{}").get("check_id")
        except ValueError:
            continue
        trail.setdefault(check_id, []).append(
            {"action": a["action"], "entry_hash": a["entry_hash"], "created_at": a["created_at"]})
    batched = {r["check_id"]: r["batch_id"] for r in db.query_all(
        "SELECT check_id, batch_id FROM transfer_items WHERE org_id = ?;", (org_id,), db_path=db_path)}
    out = []
    for row in rows:
        d = dict(row)
        try:
            d["reasons"] = json.loads(d.pop("reasons_json") or "[]")
        except ValueError:
            d["reasons"] = []
        d["batch_id"] = batched.get(d["id"], "")
        d["proof"] = trail.get(d["id"], [])
        out.append(d)
    return out


def checks_last_hour(org_id: str, db_path: str | None = None) -> int:
    row = db.query_one("SELECT COUNT(*) AS c FROM invoice_checks WHERE org_id = ? AND created_at >= ?;",
                       (org_id, int(time.time()) - 3600), db_path=db_path)
    return row["c"] if row else 0


def note_ignored(org_id: str, reason: str, db_path: str | None = None) -> None:
    """Trace un mail écarté sans être lu (expéditeur inconnu, non authentifié...). Borné : une rafale de mails
    indésirables ne doit pas remplir le journal."""
    row = db.query_one("SELECT COUNT(*) AS c FROM audit WHERE org_id = ? AND action = 'inbox.ignored' AND created_at >= ?;",
                       (org_id, int(time.time()) - 3600), db_path=db_path)
    if row and row["c"] >= MAX_IGNORED_LOGGED_PER_HOUR:
        return
    auth.log_audit("inbox.ignored", org_id=org_id, details={"reason": reason}, db_path=db_path)


# Refus qui désignent un compte de fraudeur : son empreinte est partagée avec les autres entreprises.
SHARED_CODES = ("iban_changed", "supplier_lookalike", "known_scam")


def reported_elsewhere(org_id: str, ibans: list[str], db_path: str | None = None) -> int:
    """Nombre d'autres entreprises qui ont refusé l'un de ces comptes pour fraude. Seules des empreintes sont
    comparées : aucune entreprise ne voit les factures ni les fournisseurs d'une autre."""
    if not ibans:
        return 0
    orgs_seen = set()
    for iban in ibans[:10]:
        orgs_seen.update(r["org_id"] for r in db.query_all(
            "SELECT org_id FROM reported_accounts WHERE org_id != ? AND iban_sha256 = ?;", (org_id, _sha(iban)), db_path=db_path))
    return len(orgs_seen)


def _cents(total: str) -> int | None:
    try:
        d = Decimal(str(total))
    except InvalidOperation:
        return None
    if not d.is_finite() or d <= 0 or d > Decimal("1e9") or d != d.quantize(Decimal("0.01")):
        return None
    return int(d * 100)


def judge(org: dict[str, Any], invoice: Any, sender_id: str | None = None, db_path: str | None = None,
          unreadable: bool = False, file_sha256: str = "") -> dict[str, Any]:
    """Vérifie une facture pour une organisation et enregistre le verdict.

    `org` vient de org_for_alias ; `invoice` est un sdk.invoice_reader.Invoice (ou None si `unreadable`).
    Tout ce que contient la facture est une donnée non fiable : rien n'y est obéi, tout y est contrôlé.
    """
    org_id = org["id"]
    reasons: list[dict[str, str]] = []

    def flag(code: str, detail: str = "") -> None:
        level, title, ref = CATALOG[code]
        if not any(r["code"] == code for r in reasons):
            reasons.append({"code": code, "level": level, "title": title, "detail": detail, "ref": ref})

    now = int(time.time())
    payee: dict[str, Any] | None = None
    number, cents, currency, fmt, iban_seen = "", None, "", "", ""

    with _org_lock(org_id):
        if unreadable or invoice is None:
            flag("unreadable", "Ouvrez le mail d'origine dans votre messagerie pour le traiter à la main.")
        else:
            fmt = str(invoice.fmt)[:20]
            file_sha256 = file_sha256 or invoice.file_sha256
            priced = [a for a in getattr(invoice, "attachments", []) if a.get("total")]
            if len(priced) > 1:
                flag("several_invoices")
            elif len(priced) == 1:
                file_sha256 = priced[0]["sha256"]
            raw = invoice.text
            visible = _readable(raw)

            # 1. Instructions cachées et texte camouflé (sur le texte brut : balises, commentaires, texte invisible)
            families = set(firewall.scan_injection(raw)) | set(firewall.scan_injection(visible))
            if families & ATTACK_FAMILIES:
                flag("injection", "Ce type de texte n'a rien à faire dans une facture. Ne payez pas et prévenez votre fournisseur "
                                  "par un autre moyen que ce mail.")
            if "obfuscation" in families:
                flag("obfuscation")

            # 2. Compte bancaire : comparé au carnet de l'entreprise, jamais repris de la facture sans contrôle
            payees = db.query_all("SELECT * FROM payees WHERE org_id = ?;", (org_id,), db_path=db_path)
            by_iban = {p["iban"]: dict(p) for p in payees}
            ibans, malformed = find_ibans(firewall.normalize(raw) + "\n" + firewall.normalize(visible))
            structured = re.sub(r"[\s  ]", "", str(invoice.pay_to or "")).upper()
            if iban_valid(structured) and structured not in ibans:
                ibans.insert(0, structured)
            plain = _plain(visible + "\n" + str(invoice.supplier or ""))
            named = [dict(p) for p in payees if len(_plain(p["name"])) >= 3 and _plain(p["name"]) in plain]
            known = [by_iban[i] for i in ibans if i in by_iban]
            unknown = [i for i in ibans if i not in by_iban]
            if not ibans:
                flag("iban_invalid" if malformed else "no_iban")
            elif unknown:
                iban_seen = unknown[0]
                target = (known or named or [None])[0]
                where = fraud.bank_hint(unknown[0])
                names = {_plain(p["name"]): p["name"] for p in payees}
                twin = "" if target else fraud.lookalike(_plain(visible[:3000] + "\n" + str(invoice.supplier or "")), list(names))
                if target:
                    payee = target
                    flag("iban_changed", f"Facture : compte finissant par {_tail(unknown[0])}, {where}. Compte enregistré pour "
                                         f"{target['name']} : finissant par {_tail(target['iban'])}. C'est la fraude la plus "
                                         "courante : appelez le fournisseur à son numéro habituel avant tout paiement.")
                elif twin:
                    flag("supplier_lookalike", f"Le nom ressemble à « {names[twin]} » sans être le même, et le compte (finissant par "
                                               f"{_tail(unknown[0])}, {where}) n'est pas celui de ce fournisseur. Ne l'ajoutez pas à "
                                               "votre liste : appelez votre fournisseur à son numéro habituel.")
                else:
                    flag("unknown_supplier", f"Compte finissant par {_tail(unknown[0])}, {where}. Si vous connaissez ce fournisseur, "
                                             "ajoutez-le à votre liste après avoir vérifié son IBAN, puis renvoyez la facture.")
            else:
                owners = {p["id"]: p for p in known}
                payee = known[0]
                iban_seen = payee["iban"]
                if len(owners) > 1:
                    flag("several_accounts")
                elif payee["id"] not in {p["id"] for p in named}:
                    flag("name_mismatch", f"Le compte est celui de {payee['name']}.")
                if payee["active_after"] > now:
                    flag("payee_recent", f"{payee['name']} sera considéré comme habituel dans "
                                         f"{max(1, (payee['active_after'] - now + 3599) // 3600)} h.")
            elsewhere = reported_elsewhere(org_id, unknown, db_path=db_path)
            if elsewhere:
                flag("account_reported", f"Refusé chez {elsewhere} autre{'s' if elsewhere > 1 else ''} entreprise"
                                         f"{'s' if elsewhere > 1 else ''} qui utilise{'nt' if elsewhere > 1 else ''} VaultGuard. "
                                         "Ne l'ajoutez pas à votre liste sans avoir appelé le fournisseur.")
            if malformed and ibans:
                flag("iban_invalid")
            if len(ibans) > 1 and not any(r["code"] in ("iban_changed", "several_accounts") for r in reasons):
                flag("several_accounts")

            # 2 ter. Facture électronique hybride : la page (lue par l'humain) contre le XML (lu par les logiciels)
            shown = str(getattr(invoice, "shown", "") or "")
            if shown:
                page_ibans, _ = find_ibans(firewall.normalize(shown))
                diffs = fraud.layers(invoice, structured if iban_valid(structured) else "", page_ibans, _plain(shown),
                                     _plain(invoice.supplier or ""))
                if diffs:
                    flag("layer_mismatch", "Différence sur " + ", ".join(diffs) + ". Un logiciel de paiement suivrait les données "
                                           "cachées, pas la page que vous avez sous les yeux. Ne payez pas : demandez une facture "
                                           "corrigée au fournisseur, par téléphone.")
            traces = set(getattr(invoice, "traces", []) or [])
            if "rewritten" in traces:
                flag("pdf_edited", "Le fichier contient encore l'ancienne version de la page, et elle est différente de celle "
                                   "qui s'affiche. Demandez l'original au fournisseur.")
            elif "other_tool" in traces or {"editor", "updated"} <= traces:
                flag("pdf_edited", "Il a été modifié par un autre logiciel que celui qui l'a produit. Demandez l'original au fournisseur.")

            # 2 quater. Fausse facture d'annuaire ou de registre « officiel », envoyée par un inconnu
            if payee is None and fraud.scam(_plain(visible)):
                flag("known_scam", "Vendeur inconnu, air officiel, « inscription » ou « offre » en petits caractères : aucun organisme "
                                   "public ne réclame un paiement de cette façon. Ne payez pas.")

            # 2 bis. Mentions légales du vendeur (facture française) : SIREN / numéro de TVA, puis annuaire public
            identity = firewall.normalize(raw) + "\n" + firewall.normalize(visible)
            abroad = [i for i in ibans if i[:2] not in ("FR", "MC")]
            # Un numéro de TVA du pays du compte indique un vendeur réellement étranger : rien d'anormal.
            local_vat = abroad and any(not iban_valid(re.sub(r"\s", "", m.group(0))) for m in re.finditer(
                r"(?<![A-Z0-9])" + abroad[0][:2] + r" ?[A-Z]{0,2}\d{7,11}[A-Z0-9]{0,3}(?![A-Z0-9])", identity.upper()))
            if abroad and not local_vat and registry.find_ids(identity)[0]:
                flag("iban_foreign", f"La facture porte un numéro d'entreprise français, mais le compte est {fraud.bank_hint(abroad[0])}. "
                                     "Les comptes ouverts à l'étranger servent souvent à faire disparaître l'argent : vérifiez par téléphone.")
            if any(i[:2] in ("FR", "MC") for i in ibans):
                sirens, wrong = registry.find_ids(identity)
                if wrong:
                    flag("company_id_invalid")
                elif not sirens:
                    flag("company_id_missing")
                elif registry.enabled():
                    answers = [a for a in (registry.lookup(s) for s in sirens[:3]) if a is not None]
                    known_names = " ".join(_plain(n) for a in answers for n in a["names"])
                    if answers and not any(a["found"] for a in answers):
                        flag("company_unknown")
                    elif any(a["found"] and not a["active"] for a in answers):
                        flag("company_closed")
                    elif answers and payee and not any(
                            len(word) >= 4 and word in known_names for word in _plain(payee["name"]).split()):
                        flag("company_name_mismatch", f"Fournisseur attendu : {payee['name']}.")

            # 3. Montant
            currency = str(invoice.currency or "").upper()[:5]
            cents = _cents(invoice.total) if invoice.total else None
            if cents is None:
                flag("no_amount")
            elif currency != "EUR":
                flag("currency", f"Devise lue : {currency or 'inconnue'}.")
            else:
                if cents >= org["review_threshold_cents"]:
                    flag("above_threshold", f"{euros(cents)} ; votre seuil est de {euros(org['review_threshold_cents'])}.")
                if payee:
                    past = [r["amount_cents"] for r in db.query_all(
                        "SELECT amount_cents FROM invoice_checks WHERE org_id = ? AND payee_id = ? AND verdict = 'ok' "
                        "AND amount_cents IS NOT NULL;", (org_id, payee["id"]), db_path=db_path)]
                    if len(past) >= 3 and cents > 3 * statistics.median(past):
                        flag("amount_anomaly", f"{euros(cents)}, soit {cents / statistics.median(past):.1f} fois le montant "
                                               f"habituel ({euros(int(statistics.median(past)))}).")
                # Fractionnement : plusieurs factures « moyennes » du même fournisseur en 24 h qui, ensemble, passent le seuil
                threshold = org["review_threshold_cents"]
                if payee and cents < threshold <= cents * 4:
                    parts = [r["amount_cents"] for r in db.query_all(
                        "SELECT amount_cents FROM invoice_checks WHERE org_id = ? AND payee_id = ? AND verdict != 'refused' "
                        "AND created_at >= ? AND amount_cents < ? AND amount_cents * 4 >= ?;",
                        (org_id, payee["id"], now - 86400, threshold, threshold), db_path=db_path)]
                    if parts and sum(parts) + cents >= threshold:
                        flag("split_threshold", f"{len(parts) + 1} factures de {payee['name']} en 24 h, {euros(sum(parts) + cents)} au "
                                                f"total ; votre seuil est de {euros(threshold)}.")
                structured_invoice = invoice.structured()
                if structured_invoice and any(a[2] == "invoice_arithmetic" for a in firewall.check_invoice(
                        structured_invoice, float(invoice.total), currency)):
                    flag("invoice_arithmetic")

            # 4. Déjà reçue ? Même fichier, ou même numéro chez le même fournisseur.
            number = re.sub(r"[^A-Za-z0-9/_.-]", "", str(invoice.number or ""))[:40]
            previous = None
            if file_sha256:
                previous = db.query_one(
                    "SELECT created_at FROM invoice_checks WHERE org_id = ? AND file_sha256 = ? AND verdict != 'refused' "
                    "ORDER BY created_at LIMIT 1;", (org_id, file_sha256), db_path=db_path)
            if not previous and number and payee:
                previous = db.query_one(
                    "SELECT created_at FROM invoice_checks WHERE org_id = ? AND payee_id = ? AND invoice_number = ? "
                    "COLLATE NOCASE AND verdict != 'refused' ORDER BY created_at LIMIT 1;",
                    (org_id, payee["id"], number), db_path=db_path)
            if previous:
                flag("duplicate", "Première réception le " + time.strftime("%d/%m/%Y à %H:%M", time.localtime(previous["created_at"]))
                     + ". La payer deux fois serait une erreur.")
            elif number and payee:
                # Numéro maquillé : la lettre O pour un zéro, ou le même numéro suivi de « -BIS »
                for old in db.query_all(
                        "SELECT invoice_number, amount_cents, created_at FROM invoice_checks WHERE org_id = ? AND payee_id = ? "
                        "AND verdict != 'refused' AND invoice_number != '' ORDER BY created_at DESC LIMIT 500;",
                        (org_id, payee["id"]), db_path=db_path):
                    if fraud.same_invoice(number, old["invoice_number"], cents is not None and old["amount_cents"] == cents):
                        flag("duplicate", f"Elle porte presque le même numéro que la facture {old['invoice_number']}, reçue le "
                             + time.strftime("%d/%m/%Y à %H:%M", time.localtime(old["created_at"]))
                             + ". Un numéro légèrement modifié sert à faire payer deux fois.")
                        break

            # La pression seule ne prouve rien ; elle appuie un autre signal.
            if reasons and families & PRESSURE_FAMILIES:
                flag("pressure")

        if not reasons:
            flag("ok")
        verdict = max((r["level"] for r in reasons), key=LEVEL_RANK.__getitem__)
        # La raison la plus grave d'abord ; à gravité égale, la contradiction page / données, qui explique les autres.
        reasons.sort(key=lambda r: (-LEVEL_RANK[r["level"]], r["code"] != "layer_mismatch"))
        check_id = "chk_" + secrets.token_hex(12)
        db.execute(
            "INSERT INTO invoice_checks (id, org_id, sender_id, payee_id, payee_name, invoice_number, amount_cents, "
            "currency, iban_tail, iban_sha256, file_sha256, fmt, verdict, reasons_json, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);",
            (check_id, org_id, sender_id, payee["id"] if payee else None, payee["name"] if payee else "", number, cents,
             currency, _tail(iban_seen) if iban_seen else "", _sha(iban_seen) if iban_seen else "", file_sha256, fmt,
             verdict, json.dumps(reasons, ensure_ascii=False), now, now), db_path=db_path)
        shared = next((r["code"] for r in reasons if r["code"] in SHARED_CODES), "")
        if verdict == "refused" and shared and iban_seen and (not payee or iban_seen != payee["iban"]):
            db.execute("INSERT OR IGNORE INTO reported_accounts (iban_sha256, org_id, code, created_at) VALUES (?, ?, ?, ?);",
                       (_sha(iban_seen), org_id, shared, now), db_path=db_path)
    auth.log_audit("invoice.check", org_id=org_id,
                   details={"check_id": check_id, "verdict": verdict, "codes": [r["code"] for r in reasons],
                            "file_sha256": file_sha256, "amount_cents": cents, "payee_id": payee["id"] if payee else None},
                   db_path=db_path)
    return {"id": check_id, "verdict": verdict, "reasons": reasons, "payee_name": payee["name"] if payee else "",
            "invoice_number": number, "amount_cents": cents, "currency": currency, "file_sha256": file_sha256}


def review_check(org_id: str, user_id: str, check_id: str, approve: bool, ip: str | None = None,
                 db_path: str | None = None) -> dict[str, Any]:
    """Décision humaine sur une facture « à vérifier » (approver+). Une seule décision possible."""
    check_org_writable(org_id, db_path=db_path)
    now = int(time.time())
    cur = db.execute(
        "UPDATE invoice_checks SET verdict = ?, review_action = ?, reviewed_by = ?, reviewed_at = ?, updated_at = ? "
        "WHERE id = ? AND org_id = ? AND verdict = 'review';",
        ("ok" if approve else "refused", "approved" if approve else "rejected", user_id, now, now, check_id, org_id),
        db_path=db_path)
    if cur.rowcount != 1:
        exists = db.query_one("SELECT 1 FROM invoice_checks WHERE id = ? AND org_id = ?;", (check_id, org_id), db_path=db_path)
        raise OrgError("Cette facture n'attend pas de décision", 409) if exists else OrgError("Facture introuvable", 404)
    auth.log_audit("invoice.approve" if approve else "invoice.reject", org_id=org_id, user_id=user_id,
                   details={"check_id": check_id}, ip=ip, db_path=db_path)
    return next(c for c in list_checks(org_id, limit=200, db_path=db_path) if c["id"] == check_id)
