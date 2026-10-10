"""mail_agent.py — L'agent qui relève la boîte de dépôt des factures et demande un verdict à VaultGuard.

Chaque entreprise a son adresse (inbox.address_for). L'agent tourne dans le serveur (un fil d'exécution) :
  1. il ne télécharge d'abord que les EN-TÊTES du mail ;
  2. il retrouve l'entreprise d'après l'adresse de destination ;
  3. il écarte, sans lire le contenu, tout mail dont l'expéditeur n'est pas dans la liste de confiance de cette
     entreprise, ou dont l'expéditeur n'est pas prouvé par le serveur de réception (SPF / DKIM / DMARC) ;
  4. il lit alors la facture en mémoire, appelle inbox.judge, répond à l'expéditeur, puis efface le mail.

Configuration (variables d'environnement, à mettre dans agent/.env) :
  INBOUND_ADDRESS        modèle d'adresse, ex. vaultguard.factures+{alias}@gmail.com
  INBOUND_IMAP_HOST / _PORT / _USER / _PASSWORD / _FOLDER    la boîte à relever
  INBOUND_AUTHSERV_ID    nom du serveur de réception dans l'en-tête Authentication-Results (Gmail : mx.google.com)
  INBOUND_SMTP_HOST / _PORT   pour répondre à l'expéditeur (mêmes identifiants que l'IMAP)
  INBOUND_POLL           secondes entre deux relevés (10 par défaut, 3 pour le dossier de démonstration)
  PUBLIC_URL             adresse du site, citée dans la réponse
Sans INBOUND_IMAP_HOST, sur une machine locale, l'agent relève un dossier (data/boite-entrante/*.eml) : c'est la
boîte de démonstration. Les mails de démonstration portent l'en-tête que poserait un vrai serveur de réception.
"""
from __future__ import annotations

import email
import email.policy
import email.utils
import hashlib
import imaplib
import logging
import os
import re
import smtplib
import sys
import threading
import time
from dataclasses import dataclass
from email.message import EmailMessage, Message
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import db  # noqa: E402
import inbox  # noqa: E402
from sdk.invoice_reader import MAX_BYTES, UnreadableInvoice, read_bytes  # noqa: E402

log = logging.getLogger("vaultguard.mail")

DEMO_AUTHSERV_ID = "demo.vaultguard.local"
VERDICT_LABELS = {"ok": "BON À PAYER", "review": "À VÉRIFIER PAR VOUS", "refused": "REFUSÉE"}
RECIPIENT_HEADERS = ("Delivered-To", "X-Original-To", "Envelope-To", "To", "Cc")


@dataclass
class Settings:
    imap_host: str = ""
    imap_port: int = 993
    imap_user: str = ""
    imap_password: str = ""
    imap_folder: str = "INBOX"
    authserv_id: str = DEMO_AUTHSERV_ID
    drop_dir: Path | None = None
    smtp_host: str = ""
    smtp_port: int = 465
    public_url: str = ""
    poll: int = 10

    @classmethod
    def from_env(cls, local: bool) -> "Settings":
        env = os.environ.get
        host = env("INBOUND_IMAP_HOST", "").strip()
        default_id = "mx.google.com" if host.endswith(("gmail.com", "googlemail.com")) else ""
        drop = None
        if not host and local:
            drop = Path(db.get_db_path()).resolve().parent / "boite-entrante"
        return cls(
            imap_host=host, imap_port=int(env("INBOUND_IMAP_PORT", "993") or 993),
            imap_user=env("INBOUND_IMAP_USER", "").strip(), imap_password=env("INBOUND_IMAP_PASSWORD", ""),
            imap_folder=env("INBOUND_IMAP_FOLDER", "INBOX") or "INBOX",
            authserv_id=env("INBOUND_AUTHSERV_ID", "").strip() or (default_id if host else DEMO_AUTHSERV_ID),
            drop_dir=drop, smtp_host=env("INBOUND_SMTP_HOST", "").strip(),
            smtp_port=int(env("INBOUND_SMTP_PORT", "465") or 465),
            public_url=env("PUBLIC_URL", "").strip().rstrip("/"),
            poll=max(3, int(env("INBOUND_POLL", "") or (3 if drop else 10))))

    @property
    def enabled(self) -> bool:
        return bool(self.drop_dir or (self.imap_host and self.imap_user and self.imap_password and self.authserv_id))


# ------------------------------------------------------------------ Qui a envoyé ce mail, et est-ce prouvé ?

def authenticated(headers: Message, sender: str, authserv_id: str) -> bool:
    """L'adresse d'expéditeur se falsifie en une ligne. On ne la croit que si NOTRE serveur de réception a vérifié
    le mail : DMARC, DKIM ou SPF valide, pour le domaine de l'expéditeur.

    Seul le premier en-tête Authentication-Results compte : le serveur de réception l'ajoute tout en haut, un
    en-tête fabriqué par l'expéditeur se trouve forcément plus bas. Il doit porter le nom de notre serveur."""
    results = headers.get_all("Authentication-Results", [])
    if not results or not authserv_id or "@" not in sender:
        return False
    value = re.sub(r"\s+", " ", str(results[0]))
    for _ in range(5):
        value = re.sub(r"\([^()]*\)", " ", value)   # commentaires
    parts = [p.strip() for p in value.split(";")]
    if parts[0].split(" ")[0].lower() != authserv_id.lower():
        return False
    domain = sender.rsplit("@", 1)[1].lower()

    def aligned(candidate: str) -> bool:
        d = candidate.lower().rsplit("@", 1)[-1].strip(".")
        return "." in d and (d == domain or domain.endswith("." + d) or d.endswith("." + domain))

    for part in parts[1:]:
        m = re.match(r"(\w+)\s*=\s*(\w+)(.*)", part)
        if not m or m.group(2).lower() != "pass":
            continue
        props = {k.lower(): v for k, v in re.findall(r"([\w.]+)=(\S+)", m.group(3))}
        method = m.group(1).lower()
        if method == "dmarc" and aligned(props.get("header.from", "")):
            return True
        if method == "dkim" and aligned(props.get("header.d") or props.get("header.i", "")):
            return True
        if method == "spf" and aligned(props.get("smtp.mailfrom", "")):
            return True
    return False


def gate(headers: Message, settings: Settings, db_path: str | None = None) -> tuple[dict[str, Any], dict[str, Any]] | str:
    """Décide, sur les seuls en-têtes, si le mail sera lu. Renvoie (entreprise, expéditeur) ou la raison du refus."""
    try:
        auto = str(headers.get("Auto-Submitted", "no")).strip().lower()
        senders = email.utils.getaddresses([str(v) for v in headers.get_all("From", [])])
        recipients = [addr for _, addr in email.utils.getaddresses(
            [str(v) for name in RECIPIENT_HEADERS for v in headers.get_all(name, [])])]
    except (ValueError, IndexError, AttributeError):
        return "malformed"
    if auto != "no":
        return "auto"       # réponse automatique : ne jamais y répondre (boucles de mails)
    if len(senders) != 1 or "@" not in senders[0][1]:
        return "sender"
    sender = senders[0][1].strip().lower()
    outcome = "alias"
    for alias in inbox.aliases_in(recipients)[:3]:
        org = inbox.org_for_alias(alias, db_path=db_path)
        if not org:
            continue
        if org["is_suspended"]:
            outcome = "suspended"
            continue
        row = inbox.trusted_sender(org["id"], sender, db_path=db_path)
        if not row:
            inbox.note_ignored(org["id"], "sender", db_path=db_path)
            outcome = "sender"
            continue
        if not authenticated(headers, sender, settings.authserv_id):
            inbox.note_ignored(org["id"], "auth", db_path=db_path)
            outcome = "auth"
            continue
        if inbox.checks_last_hour(org["id"], db_path=db_path) >= inbox.MAX_CHECKS_PER_HOUR:
            inbox.note_ignored(org["id"], "rate", db_path=db_path)
            outcome = "rate"
            continue
        return org, row
    return outcome


def _headers(raw: bytes) -> Message:
    return email.message_from_bytes(raw.split(b"\r\n\r\n", 1)[0].split(b"\n\n", 1)[0] + b"\n\n", policy=email.policy.default)


def handle(raw: bytes, org: dict[str, Any], sender: dict[str, Any], settings: Settings,
           db_path: str | None = None) -> dict[str, Any]:
    """Lit la facture d'un mail accepté et demande le verdict. Rien du mail n'est conservé ni journalisé."""
    try:
        invoice = read_bytes(raw, "mail.eml")
    except UnreadableInvoice:
        result = inbox.judge(org, None, sender_id=sender["id"], db_path=db_path, unreadable=True,
                             file_sha256=hashlib.sha256(raw).hexdigest())
    else:
        result = inbox.judge(org, invoice, sender_id=sender["id"], db_path=db_path)
    log.info("boîte factures : %s -> %s (%s)", org["name"], VERDICT_LABELS[result["verdict"]], result["id"])
    try:
        reply(raw, sender["email"], org, result, settings)
    except (OSError, smtplib.SMTPException, ValueError) as e:
        log.warning("boîte factures : réponse non envoyée (%s)", type(e).__name__)
    return result


def process_message(raw: bytes, settings: Settings, db_path: str | None = None) -> dict[str, Any]:
    """Un mail complet (boîte de démonstration, tests) : filtre sur les en-têtes, puis lecture si accepté."""
    if len(raw) > MAX_BYTES:
        return {"status": "ignored", "reason": "size"}
    decision = gate(_headers(raw), settings, db_path=db_path)
    if isinstance(decision, str):
        return {"status": "ignored", "reason": decision}
    return {"status": "checked", **handle(raw, decision[0], decision[1], settings, db_path=db_path)}


# ------------------------------------------------------------------ Réponse à l'expéditeur

def build_reply(raw: bytes, to: str, org: dict[str, Any], result: dict[str, Any], settings: Settings) -> EmailMessage:
    """La réponse ne recopie rien du mail reçu : uniquement nos phrases, le numéro et le montant lus."""
    original = _headers(raw)
    label = VERDICT_LABELS[result["verdict"]]
    what = "Facture" + (f" {result['invoice_number']}" if result["invoice_number"] else "")
    if result["payee_name"]:
        what += f" de {result['payee_name']}"
    if result["amount_cents"] is not None and result["currency"] == "EUR":
        what += f", {inbox.euros(result['amount_cents'])}"
    lines = [f"{what} : {label}", ""]
    for reason in result["reasons"]:
        lines.append("- " + reason["title"])
        if reason["detail"]:
            lines.append("  " + reason["detail"])
    lines.append("")
    if result["verdict"] == "review":
        lines.append("Rien n'est payé. Ouvrez votre espace VaultGuard pour accepter ou refuser"
                     + (f" : {settings.public_url}/app#inbox" if settings.public_url else "."))
    elif result["verdict"] == "refused":
        lines.append("Rien n'est payé.")
    lines += ["", "VaultGuard n'a pas conservé votre mail ni la facture : seule une empreinte est gardée comme preuve.",
              f"Référence de cette vérification : {result['id']}"]
    msg = EmailMessage()
    msg["From"] = inbox.address_for(org["alias"])
    msg["To"] = to
    msg["Subject"] = f"[VaultGuard] {label}" + (f" - facture {result['invoice_number']}" if result["invoice_number"] else "")
    msg["Auto-Submitted"] = "auto-replied"
    message_id = re.sub(r"[\r\n]", "", str(original.get("Message-ID", "")))[:200]
    if re.fullmatch(r"<[^<>\s]+>", message_id):
        msg["In-Reply-To"] = message_id
        msg["References"] = message_id
    msg.set_content("\n".join(lines))
    return msg


def reply(raw: bytes, to: str, org: dict[str, Any], result: dict[str, Any], settings: Settings) -> bool:
    if not (settings.smtp_host and settings.imap_user and settings.imap_password):
        return False
    msg = build_reply(raw, to, org, result, settings)
    with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
        smtp.login(settings.imap_user, settings.imap_password)
        smtp.send_message(msg, from_addr=settings.imap_user, to_addrs=[to])
    return True


# ------------------------------------------------------------------ Relève : dossier de démonstration et IMAP

def poll_folder(settings: Settings, db_path: str | None = None) -> int:
    folder = settings.drop_dir
    if folder is None:
        return 0
    folder.mkdir(parents=True, exist_ok=True)
    done = 0
    for path in sorted(folder.glob("*.eml"))[:50]:
        try:
            if time.time() - path.stat().st_mtime < 1:      # copie peut-être encore en cours
                continue
            if path.is_symlink() or path.stat().st_size > MAX_BYTES:
                raw = b""
            else:
                raw = path.read_bytes()
            path.unlink()                      # zéro conservation : le mail disparaît dès qu'il est pris en charge
        except OSError:
            continue
        if raw:
            out = process_message(raw, settings, db_path=db_path)
            if out["status"] == "ignored":
                log.info("boîte factures : mail écarté sans être lu (%s)", out["reason"])
        done += 1
    return done


def _discard(box: imaplib.IMAP4_SSL, uid: str, gmail: bool) -> None:
    if gmail:                                   # sur Gmail, \Deleted archive seulement : il faut la corbeille
        box.uid("store", uid, "+X-GM-LABELS", "(\\Trash)")
    box.uid("store", uid, "+FLAGS", "(\\Seen \\Deleted)")


def poll_imap(settings: Settings, db_path: str | None = None) -> int:
    if not settings.imap_host:
        return 0
    gmail = settings.imap_host.endswith(("gmail.com", "googlemail.com"))
    box = imaplib.IMAP4_SSL(settings.imap_host, settings.imap_port, timeout=30)
    done = 0
    try:
        box.login(settings.imap_user, settings.imap_password)
        box.select(settings.imap_folder)
        _, data = box.uid("search", None, "UNSEEN")
        for uid in (data[0] or b"").split()[:50]:
            uid_s = uid.decode()
            _, fetched = box.uid("fetch", uid_s, "(RFC822.SIZE BODY.PEEK[HEADER])")
            if not fetched or not isinstance(fetched[0], tuple):
                continue
            size = re.search(rb"RFC822\.SIZE (\d+)", fetched[0][0])
            decision = gate(email.message_from_bytes(fetched[0][1], policy=email.policy.default), settings, db_path=db_path)
            if isinstance(decision, str):
                log.info("boîte factures : mail écarté sans être lu (%s)", decision)
            elif size and int(size.group(1)) > MAX_BYTES:
                inbox.note_ignored(decision[0]["id"], "size", db_path=db_path)
            else:
                _, body = box.uid("fetch", uid_s, "(BODY.PEEK[])")
                if body and isinstance(body[0], tuple):
                    handle(body[0][1], decision[0], decision[1], settings, db_path=db_path)
            _discard(box, uid_s, gmail)
            done += 1
        if done:
            box.expunge()
    finally:
        try:
            box.logout()
        except (imaplib.IMAP4.error, OSError):
            pass
    return done


def run_forever(settings: Settings, stop: threading.Event) -> None:
    where = f"dossier {settings.drop_dir}" if settings.drop_dir else f"{settings.imap_user} sur {settings.imap_host}"
    log.info("boîte factures : relève toutes les %s s (%s)", settings.poll, where)
    while not stop.is_set():
        try:
            poll_folder(settings)
            poll_imap(settings)
        except (imaplib.IMAP4.error, OSError) as e:
            log.warning("boîte factures : relève impossible (%s)", type(e).__name__)
        except Exception:                       # l'agent ne doit jamais s'arrêter sur un mail piégé
            log.exception("boîte factures : erreur inattendue")
        stop.wait(settings.poll)


def start(local: bool) -> threading.Event | None:
    """Lance la relève en arrière-plan. `local` : le serveur n'écoute que sur cette machine."""
    settings = Settings.from_env(local)
    if not settings.enabled:
        return None
    stop = threading.Event()
    threading.Thread(target=run_forever, args=(settings, stop), name="mail-agent", daemon=True).start()
    return stop
