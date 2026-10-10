"""agent_mail.py — L'agent de l'entreprise lit SA boîte mail et demande à VaultGuard de payer les factures.

Ce programme tourne chez l'entreprise cliente, pas chez VaultGuard : VaultGuard ne voit que la demande de
paiement et le texte du mail joint comme pièce. La boîte est ouverte en lecture seule (rien n'est marqué lu,
déplacé ni supprimé) et seuls les mails non lus dont l'objet contient « facture » sont regardés.

Configuration : copier examples/mail.env.example vers examples/.env.mail et le remplir.

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
import html
import imaplib
import json
import os
import re
import sys
import time
from email.message import EmailMessage
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

from agent_factures import VERDICTS, local_demo_key, read_invoice
from sdk.vaultguard_client import VaultGuardClient, VaultGuardError

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
    return conf


def mail_text(msg: EmailMessage) -> str:
    """Tout ce qu'un agent lirait : texte brut, HTML (commentaires et texte invisible compris), pièces .txt."""
    parts = []
    for part in msg.walk():
        kind = part.get_content_type()
        if kind in ("text/plain", "text/html") or (part.get_filename() or "").lower().endswith(".txt"):
            try:
                parts.append(part.get_content())
            except (LookupError, UnicodeDecodeError):
                parts.append(part.get_payload(decode=True).decode("utf-8", "replace"))
    return "\n".join(str(p) for p in parts)


def readable(markup: str) -> str:
    """Version sans balises, pour que l'agent retrouve le montant et l'adresse dans un mail HTML."""
    text = re.sub(r"<(br|/p|/div|/tr)[^>]*>", "\n", markup, flags=re.I)
    text = re.sub(r"<!--|-->", " ", text)
    return html.unescape(re.sub(r"<[^>]+>", "", text)).replace("\xa0", " ")


def handle(msg: EmailMessage, client: VaultGuardClient | None, mandate: str) -> str:
    sender, subject = str(msg.get("From", "?")), str(msg.get("Subject", "(sans objet)"))
    raw = mail_text(msg)
    print("\n" + "=" * 72)
    print(f"MAIL REÇU de {sender}\nObjet : {subject}")
    print("-" * 72)
    print(readable(msg.get_body(preferencelist=("plain", "html")).get_content()).strip()[:1500]
          if msg.get_body(preferencelist=("plain", "html")) else "(mail sans texte)")
    print("-" * 72)
    try:
        intent = read_invoice(readable(raw))
    except ValueError as e:
        print(f"L'agent ne reconnaît pas une facture ({e}) : rien n'est envoyé à VaultGuard.")
        return "ignored"
    print(f"1. L'agent veut payer {intent['amount']} AVAX à {intent['to']}")
    if intent["manipulated"]:
        print("   L'agent a obéi à une instruction lue dans le mail, sans s'en rendre compte.")
    if client is None:
        print("2. (--dry-run) rien n'est envoyé à VaultGuard.")
        return "dry-run"
    try:
        res = client.pay(to=intent["to"], amount=intent["amount"], memo=intent["memo"], user_request=mandate,
                         documents=[{"source": f"mail de {sender}"[:120], "content": raw[:4000]}])
    except VaultGuardError as e:
        print(f"2. VaultGuard a refusé la requête : HTTP {e.status_code} — {e.message}")
        return "error"
    decision = res.get("decision", "?")
    print(f"2. Décision de VaultGuard : {VERDICTS.get(decision, decision)}   (paiement {res.get('id')})")
    for reason in res.get("reasons", []):
        ref = f" [{reason['ref']}]" if reason.get("ref") else ""
        print(f"   - {reason.get('title', reason.get('code'))}{ref}")
        if reason.get("detail"):
            print(f"     {reason['detail']}")
    print(f"3. Coffre : {res.get('chain', {}).get('status')}  — à voir dans http://localhost:8000/app")
    return decision


def fetch_new(conf: dict[str, str], done: set[str]) -> list[EmailMessage]:
    today = datetime.date.today()
    since = f"{today.day:02d}-{MONTHS[today.month - 1]}-{today.year}"
    box = imaplib.IMAP4_SSL(conf["IMAP_HOST"], int(conf.get("IMAP_PORT", "993")))
    try:
        box.login(conf["IMAP_USER"], conf["IMAP_PASSWORD"])
        box.select(conf.get("IMAP_FOLDER", "INBOX"), readonly=True)
        _, data = box.search(None, "UNSEEN", "SINCE", since, "SUBJECT", '"facture"')
        messages = []
        for num in data[0].split():
            _, fetched = box.fetch(num, "(BODY.PEEK[])")
            msg = email.message_from_bytes(fetched[0][1], policy=email.policy.default)
            if str(msg.get("Message-ID", num)) not in done:
                messages.append(msg)
        return messages
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
    parser.add_argument("--consigne", default="Paie les factures de Garage Dupont et de Loueur Camions Express.")
    args = parser.parse_args()

    client = None
    if not args.dry_run:
        key = args.api_key or local_demo_key()
        if not key:
            sys.exit("Clé API manquante : --api-key ou VAULTGUARD_API_KEY (créée dans /app, onglet Clés d'API).")
        client = VaultGuardClient(api_key=key, base_url=args.url)
    print(f"CONSIGNE DU DIRIGEANT À L'AGENT : « {args.consigne} »")

    if args.eml:
        handle(email.message_from_bytes(Path(args.eml).read_bytes(), policy=email.policy.default), client, args.consigne)
        return

    conf = load_config()
    done = set(json.loads(SEEN.read_text(encoding="utf-8"))) if SEEN.exists() else set()
    print(f"Boîte surveillée : {conf['IMAP_USER']} (lecture seule, mails non lus dont l'objet contient « facture »)")
    while True:
        try:
            messages = fetch_new(conf, done)
        except (imaplib.IMAP4.error, OSError) as e:
            sys.exit(f"Connexion à la boîte impossible : {e}")
        if not messages and not args.watch:
            print("Aucun nouveau mail de facture.")
        for msg in messages:
            handle(msg, client, args.consigne)
            done.add(str(msg.get("Message-ID")))
            if not args.dry_run:
                SEEN.write_text(json.dumps(sorted(done)), encoding="utf-8")
        if not args.watch:
            return
        time.sleep(max(5, args.watch))


if __name__ == "__main__":
    main()
