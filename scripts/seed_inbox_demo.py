"""Prépare la boîte de dépôt des factures du client de démonstration « Transports Martin ».

Usage (depuis agent/, site arrêté) : python3 ../scripts/seed_inbox_demo.py
N'efface rien et ne change aucun identifiant : ajoute l'adresse de dépôt, deux personnes autorisées, trois
fournisseurs avec leur IBAN de test et trois factures déjà réglées la veille (pour que « montant inhabituel »
ait un point de comparaison). Peut être relancé sans risque.
"""
import hashlib
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "agent"))
sys.path.insert(0, str(ROOT / "examples"))

import boite_demo as demo  # noqa: E402
import db  # noqa: E402
import inbox  # noqa: E402
import mail_agent  # noqa: E402
import transfers  # noqa: E402
from orgs import OrgError  # noqa: E402


def seed(org_id: str, user_id: str) -> str:
    box = inbox.ensure_inbox(org_id, alias=demo.ALIAS)
    for sender in demo.SENDERS:
        try:
            inbox.add_sender(org_id, user_id, sender)
        except OrgError:
            pass                                    # déjà présent
    for name, iban in demo.PAYEES:
        try:
            inbox.add_payee(org_id, user_id, name, iban)
        except OrgError:
            pass
    db.execute("UPDATE payees SET active_after = ? WHERE org_id = ?;", (int(time.time()) - 60, org_id))
    if box["alias"] == demo.ALIAS and not inbox.list_checks(org_id, limit=1):
        settings = mail_agent.Settings(authserv_id=demo.AUTHSERV)
        for i, price in enumerate(("350,00", "400,00", "450,00")):
            text = demo.invoice_text("Garage Dupont SARL", f"GD-2026-190{i}", [("Entretien mensuel de la flotte", 1, price)], demo.GARAGE)
            mail_agent.process_message(demo.mail(f"hist{i}", demo.SENDERS[0], "TR: facture", text), settings)
        db.execute("UPDATE invoice_checks SET created_at = created_at - 86400, updated_at = updated_at - 86400 WHERE org_id = ?;",
                   (org_id,))
    if not transfers.get_bank(org_id):
        transfers.set_bank(org_id, user_id, "Transports Martin", demo.COMPANY_IBAN)
    if box["alias"] == demo.ALIAS and not transfers.list_batches(org_id):
        try:        # les factures de la veille ont deja ete reglees : elles forment un premier fichier, date d'hier
            batch = transfers.create_batch(org_id, user_id, before=int(time.time()) - 12 * 3600)
        except OrgError:
            batch = None
        if batch:
            batch["created_at"] -= 86400
            digest = hashlib.sha256(transfers.build_xml(batch, batch["items"]).encode("utf-8")).hexdigest()
            db.execute("UPDATE transfer_batches SET created_at = ?, file_sha256 = ?, seal_status = 'simulated', sealed_at = ? "
                       "WHERE id = ?;", (batch["created_at"], digest, batch["created_at"], batch["id"]))
    seed_platform(org_id, user_id)
    return inbox.address_for(box["alias"])


def seed_platform(org_id: str, user_id: str) -> None:
    """Plateforme de facturation : Transports Martin y est inscrit, ainsi qu'un fournisseur, « Garage Dupont »,
    rattaché au même compte de démonstration. On passe de l'un à l'autre par le menu « Organisation » en haut de
    /app : émettre côté garage, recevoir côté transporteur."""
    import secrets

    import einvoice

    if not einvoice.get_profile(org_id):
        einvoice.set_profile(org_id, user_id, demo.make_siren(4001), "8 avenue du Fret, 95000 Cergy")
    row = db.query_one("SELECT o.id FROM orgs o JOIN members m ON m.org_id = o.id WHERE o.name = 'Garage Dupont' "
                       "AND m.user_id = ?;", (user_id,))
    garage = row["id"] if row else "org_" + secrets.token_hex(12)
    if not row:
        now = int(time.time())
        db.execute("INSERT INTO orgs (id, name, slug, created_at, updated_at) VALUES (?, 'Garage Dupont', ?, ?, ?);",
                   (garage, "org-" + secrets.token_hex(6), now, now))
        db.execute("INSERT INTO members (id, org_id, user_id, role, created_at, updated_at) VALUES (?, ?, ?, 'owner', ?, ?);",
                   ("m_" + secrets.token_hex(12), garage, user_id, now, now))
    if not einvoice.get_profile(garage):
        einvoice.set_profile(garage, user_id, demo.SIRENS["garage dupont"], "12 rue des Ateliers, 95000 Cergy")
    if not transfers.get_bank(garage):
        transfers.set_bank(garage, user_id, "Garage Dupont", demo.GARAGE)


if __name__ == "__main__":
    db.init_db()
    row = db.query_one("SELECT o.id AS org_id, m.user_id FROM orgs o JOIN members m ON m.org_id = o.id "
                       "WHERE o.name = 'Transports Martin' AND m.role = 'owner' ORDER BY o.created_at LIMIT 1;")
    if not row:
        sys.exit("Client de démonstration introuvable : lance d'abord lanceurs/RECREER-DEMO.bat.")
    print("Boîte de dépôt prête :", seed(row["org_id"], row["user_id"]))
