"""agent_mail.py — L'agent de l'entreprise lit une boîte mail et demande à VaultGuard de payer les factures.

Ce programme tourne chez l'entreprise cliente, pas chez VaultGuard : VaultGuard ne voit que la demande de
paiement et le texte du mail, qu'il analyse en mémoire sans le conserver (empreinte SHA-256 seulement).

Deux façons de choisir ce que l'agent a le droit de lire (MODE dans examples/.env.mail) :
  - MODE=filtre (défaut) : la boîte existante, en lecture seule, mails non lus dont l'objet contient « facture ».
  - MODE=dediee : une adresse créée pour cela (ex. factures-a-payer@entreprise.fr). L'entreprise y TRANSFÈRE
    les factures qu'elle veut faire payer : l'agent ne voit rien d'autre. Seuls les expéditeurs listés dans
    EXPEDITEURS_AUTORISES sont acceptés. Avec SUPPRIMER_APRES=1 le mail est effacé de la boîte une fois traité.
Pièces jointes lues : PDF, Factur-X, XML UBL/CII, Word, texte (voir sdk/invoice_reader.py).

    python3 examples/agent_mail.py                 un passage sur la boîte
    python3 examples/agent_mail.py --watch 15      surveille la boîte toutes les 15 s
    python3 examples/agent_mail.py --dry-run       montre ce que l'agent ferait, sans rien envoyer à VaultGuard
    python3 examples/agent_mail.py --eml mail.eml  traite un mail enregistré (sans connexion à la boîte)
"""
from __future__ import annotations

import argparse
import datetime
import email
import email.policy
import email.utils
import hashlib
import imaplib
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

from agent_factures import CONSIGNE, DEMO_RATE, decide, local_demo_key, submit
from sdk.invoice_reader import UnreadableInvoice, read_bytes, readable
from sdk.vaultguard_client import VaultGuardClient

CONFIG = HERE / ".env.mail"
SEEN = HERE / ".mail-traites.json"
MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()


def load_config() -> dict[str, str]:
    if not CONFIG.exists():
        sys.exit(f"Configuration absente : copie examples/mail.env.example vers {CONFIG.name} et remplis-le.")
    conf = {}
    for line in CONFIG.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            conf[key.strip()] = value.strip()
    for required in ("IMAP_HOST", "IMAP_USER", "IMAP_PASSWORD"):
        if not conf.get(required):
            sys.exit(f"{required} manquant dans {CONFIG.name}")
    if conf.get("MODE", "filtre") == "dediee" and not allowed_senders(conf):
        sys.exit("MODE=dediee : EXPEDITEURS_AUTORISES est obligatoire (adresses de l'entreprise, séparées par des virgules).")
    return conf


def allowed_senders(conf: dict[str, str]) -> set[str]:
    return {a.strip().lower() for a in conf.get("EXPEDITEURS_AUTORISES", "").split(",") if a.strip()}


def sender_refused(raw: bytes, conf: dict[str, str]) -> str:
    """Boîte dédiée : raison du refus d'un mail, ou chaîne vide s'il est accepté.

    L'adresse d'expéditeur se falsifie : si le serveur de réception a vérifié le mail (en-tête
    Authentication-Results), on exige que SPF ou DKIM soit valide."""
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    sender = email.utils.parseaddr(str(msg.get("From", "")))[1].lower()
    if sender not in allowed_senders(conf):
        return "expéditeur hors de la liste autorisée"
    checks = " ".join(str(v) for v in msg.get_all("Authentication-Results", [])).lower()
    if checks and "spf=pass" not in checks and "dkim=pass" not in checks:
        return "expéditeur non authentifié (SPF et DKIM en échec)"
    return ""


def handle(raw: bytes, client: VaultGuardClient | None, mandate: str, rate: str = DEMO_RATE) -> str:
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    print("\n" + "=" * 72)
    print(f"MAIL REÇU de {msg.get('From', '?')}\nObjet : {msg.get('Subject', '(sans objet)')}")
    print("-" * 72)
    try:
        inv = read_bytes(raw, "mail.eml")
    except UnreadableInvoice as e:
        print(f"Mail illisible ({e}) : rien n'est envoyé à VaultGuard, un humain doit le traiter.")
        return "ignored"
    print(f"[format {inv.fmt}, {len(inv.lines)} ligne(s) de détail]")
    print(readable(inv.text).strip()[:1500])
    print("-" * 72)
    if client is None:
        try:
            intent = decide(inv, rate)
            print(f"1. L'agent voudrait payer {intent['amount']} AVAX à {intent['to']}")
        except ValueError as e:
            print(f"L'agent ne reconnaît pas une facture ({e}).")
        print("2. (--dry-run) rien n'est envoyé à VaultGuard.")
        return "dry-run"
    return submit(client, inv, mandate, rate)


def mark(message_id: str) -> str:
    """Les mails déjà traités sont mémorisés par empreinte, pas par identifiant lisible."""
    return hashlib.sha256(message_id.encode("utf-8", "replace")).hexdigest()


def fetch_new(conf: dict[str, str], done: set[str]) -> list[tuple[bytes, bytes]]:
    """Renvoie [(UID IMAP, mail brut)] pour les mails à traiter."""
    dedicated = conf.get("MODE", "filtre") == "dediee"
    today = datetime.date.today()
    since = f"{today.day:02d}-{MONTHS[today.month - 1]}-{today.year}"
    box = imaplib.IMAP4_SSL(conf["IMAP_HOST"], int(conf.get("IMAP_PORT", "993")))
    try:
        box.login(conf["IMAP_USER"], conf["IMAP_PASSWORD"])
        box.select(conf.get("IMAP_FOLDER", "INBOX"), readonly=True)
        criteria = ("UNSEEN", "SINCE", since) if dedicated else ("UNSEEN", "SINCE", since, "SUBJECT", '"facture"')
        # UID et non numéro de séquence : le numéro change dès qu'un autre mail est effacé.
        _, data = box.uid("search", *criteria)
        messages = []
        for num in data[0].split():
            _, fetched = box.uid("fetch", num.decode(), "(BODY.PEEK[])")
            raw = fetched[0][1]
            msg = email.message_from_bytes(raw, policy=email.policy.default)
            if mark(str(msg.get("Message-ID", num))) in done:
                continue
            refusal = sender_refused(raw, conf) if dedicated else ""
            if refusal:
                print(f"Mail ignoré ({refusal}) : rien n'est lu ni envoyé.")
                done.add(mark(str(msg.get("Message-ID", num))))
                continue
            messages.append((num, raw))
        return messages
    finally:
        try:
            box.logout()
        except imaplib.IMAP4.error:
            pass


def delete_processed(conf: dict[str, str], numbers: list[bytes]) -> None:
    """Boîte dédiée avec SUPPRIMER_APRES=1 : efface les mails traités, pour que rien ne reste en attente."""
    box = imaplib.IMAP4_SSL(conf["IMAP_HOST"], int(conf.get("IMAP_PORT", "993")))
    try:
        box.login(conf["IMAP_USER"], conf["IMAP_PASSWORD"])
        box.select(conf.get("IMAP_FOLDER", "INBOX"))
        for num in numbers:
            box.uid("store", num.decode(), "+FLAGS", "\\Deleted")
        box.expunge()
    finally:
        try:
            box.logout()
        except imaplib.IMAP4.error:
            pass


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Agent de facturation branché sur une boîte mail (VaultGuard)")
    parser.add_argument("--api-key", default=os.environ.get("VAULTGUARD_API_KEY"))
    parser.add_argument("--url", default=os.environ.get("VAULTGUARD_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--watch", type=int, default=0, metavar="SECONDES", help="surveiller la boîte en continu")
    parser.add_argument("--dry-run", action="store_true", help="ne rien envoyer à VaultGuard")
    parser.add_argument("--eml", help="traiter un fichier .eml au lieu de la boîte")
    parser.add_argument("--taux", default=DEMO_RATE, help="euros fictifs pour 1 AVAX de test (démo)")
    parser.add_argument("--consigne", default=CONSIGNE)
    args = parser.parse_args()

    client = None
    if not args.dry_run:
        key = args.api_key or local_demo_key()
        if not key:
            sys.exit("Clé API manquante : --api-key ou VAULTGUARD_API_KEY (créée dans /app, onglet Clés d'API).")
        client = VaultGuardClient(api_key=key, base_url=args.url)
    print(f"CONSIGNE DU DIRIGEANT À L'AGENT : « {args.consigne} »")

    if args.eml:
        handle(Path(args.eml).read_bytes(), client, args.consigne, args.taux)
        return

    conf = load_config()
    dedicated = conf.get("MODE", "filtre") == "dediee"
    done = set(json.loads(SEEN.read_text(encoding="utf-8"))) if SEEN.exists() else set()
    print(f"Boîte surveillée : {conf['IMAP_USER']} — "
          + ("boîte dédiée, expéditeurs autorisés seulement" if dedicated
             else "lecture seule, mails non lus dont l'objet contient « facture »"))
    while True:
        try:
            messages = fetch_new(conf, done)
        except (imaplib.IMAP4.error, OSError) as e:
            sys.exit(f"Connexion à la boîte impossible : {e}")
        if not messages and not args.watch:
            print("Aucun nouveau mail de facture.")
        for _, raw in messages:
            handle(raw, client, args.consigne, args.taux)
            msg = email.message_from_bytes(raw, policy=email.policy.default)
            done.add(mark(str(msg.get("Message-ID"))))
        if not args.dry_run:
            SEEN.write_text(json.dumps(sorted(done)), encoding="utf-8")
            if dedicated and conf.get("SUPPRIMER_APRES") == "1" and messages:
                delete_processed(conf, [num for num, _ in messages])
                print(f"{len(messages)} mail(s) traité(s) puis effacé(s) de la boîte dédiée.")
        if not args.watch:
            return
        time.sleep(max(5, args.watch))


if __name__ == "__main__":
    main()
