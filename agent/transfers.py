"""transfers.py — Des factures « bonnes à payer » au virement en euros.

VaultGuard prépare un fichier de virements SEPA (norme ISO 20022, message pain.001) : l'entreprise l'importe dans le
site de sa banque et valide une fois pour tout le lot. Le fournisseur reçoit un virement ordinaire en euros.
VaultGuard ne détient jamais l'argent et n'a aucun accès au compte bancaire.

Garanties :
  - l'IBAN du bénéficiaire vient du carnet de l'entreprise, jamais de la facture ;
  - une facture ne peut entrer que dans un seul fichier (clé primaire sur transfer_items.check_id) ;
  - le fichier n'est pas stocké : il se régénère à l'identique, et son empreinte SHA-256 est inscrite au journal
    chaîné puis scellée sur Avalanche (server.py), ce qui prouve quel lot a été préparé, par qui et quand.
"""
from __future__ import annotations

import hashlib
import re
import secrets
import time
import unicodedata
from typing import Any
from xml.sax.saxutils import escape

try:
    import auth
    import db
    import inbox
    from orgs import OrgError, check_org_writable
except ImportError:
    from agent import auth, db, inbox
    from agent.orgs import OrgError, check_org_writable

MAX_PER_BATCH = 200
_SEPA_ALLOWED = re.compile(r"[^A-Za-z0-9/?:().,'+ -]")


def sepa_text(value: str, limit: int) -> str:
    """Jeu de caractères accepté par toutes les banques SEPA : latin sans accent, ponctuation restreinte."""
    text = unicodedata.normalize("NFKD", str(value).replace("œ", "oe").replace("Œ", "OE").replace("æ", "ae"))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", _SEPA_ALLOWED.sub(" ", text)).strip()[:limit].strip() or "NC"


def _amount(cents: int) -> str:
    return f"{cents // 100}.{cents % 100:02d}"


# ------------------------------------------------------------------ Compte bancaire de l'entreprise

def get_bank(org_id: str, db_path: str | None = None) -> dict[str, Any] | None:
    row = db.query_one("SELECT holder, iban FROM org_bank_accounts WHERE org_id = ?;", (org_id,), db_path=db_path)
    return dict(row) if row else None


def set_bank(org_id: str, user_id: str, holder: str, iban: str, ip: str | None = None,
             db_path: str | None = None) -> dict[str, Any]:
    check_org_writable(org_id, db_path=db_path)
    clean_holder = re.sub(r"\s+", " ", holder).strip() if isinstance(holder, str) else ""
    if not 2 <= len(clean_holder) <= 70 or any(ord(c) < 32 for c in clean_holder):
        raise OrgError("Titulaire du compte : entre 2 et 70 caractères")
    compact = inbox.clean_iban(iban)
    db.execute("INSERT INTO org_bank_accounts (org_id, holder, iban, updated_at) VALUES (?, ?, ?, ?) "
               "ON CONFLICT(org_id) DO UPDATE SET holder = excluded.holder, iban = excluded.iban, updated_at = excluded.updated_at;",
               (org_id, clean_holder, compact, int(time.time())), db_path=db_path)
    auth.log_audit("bank.set", org_id=org_id, user_id=user_id,
                   details={"iban_sha256": hashlib.sha256(compact.encode()).hexdigest(), "iban_tail": compact[-4:]},
                   ip=ip, db_path=db_path)
    return {"holder": clean_holder, "iban": compact}


# ------------------------------------------------------------------ Ce qui peut être payé

def payable(org_id: str, db_path: str | None = None) -> dict[str, Any]:
    """Factures bonnes à payer qui ne sont dans aucun fichier. L'IBAN est celui du carnet, relu maintenant."""
    rows = db.query_all(
        "SELECT c.id, c.invoice_number, c.amount_cents, c.currency, c.payee_id, c.created_at, p.name AS payee_name, p.iban "
        "FROM invoice_checks c LEFT JOIN payees p ON p.id = c.payee_id AND p.org_id = c.org_id "
        "WHERE c.org_id = ? AND c.verdict = 'ok' AND c.id NOT IN (SELECT check_id FROM transfer_items WHERE org_id = ?) "
        "ORDER BY c.created_at, c.rowid;", (org_id, org_id), db_path=db_path)
    items, skipped = [], 0
    for r in rows:
        if r["iban"] and r["currency"] == "EUR" and (r["amount_cents"] or 0) > 0 and inbox.iban_valid(r["iban"]):
            items.append(dict(r))
        else:
            skipped += 1     # acceptée à la main sans fournisseur enregistré, ou fournisseur retiré depuis
    return {"items": items, "count": len(items), "total_cents": sum(i["amount_cents"] for i in items), "skipped": skipped}


# ------------------------------------------------------------------ Fichier pain.001

def build_xml(batch: dict[str, Any], items: list[dict[str, Any]]) -> str:
    """Message pain.001.001.03 (virement SEPA). Ne dépend que du lot enregistré : même lot, même fichier."""
    created = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(batch["created_at"]))
    execution = time.strftime("%Y-%m-%d", time.gmtime(batch["created_at"] + 86400))
    message_id = sepa_text("VG-" + batch["id"], 35)
    debtor = escape(sepa_text(batch["debtor_name"], 70))
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.001.001.03">',
        " <CstmrCdtTrfInitn>",
        "  <GrpHdr>",
        f"   <MsgId>{message_id}</MsgId>",
        f"   <CreDtTm>{created}</CreDtTm>",
        f"   <NbOfTxs>{len(items)}</NbOfTxs>",
        f"   <CtrlSum>{_amount(batch['total_cents'])}</CtrlSum>",
        f"   <InitgPty><Nm>{debtor}</Nm></InitgPty>",
        "  </GrpHdr>",
        "  <PmtInf>",
        f"   <PmtInfId>{message_id}</PmtInfId>",
        "   <PmtMtd>TRF</PmtMtd>",
        f"   <NbOfTxs>{len(items)}</NbOfTxs>",
        f"   <CtrlSum>{_amount(batch['total_cents'])}</CtrlSum>",
        "   <PmtTpInf><SvcLvl><Cd>SEPA</Cd></SvcLvl></PmtTpInf>",
        f"   <ReqdExctnDt>{execution}</ReqdExctnDt>",
        f"   <Dbtr><Nm>{debtor}</Nm></Dbtr>",
        f"   <DbtrAcct><Id><IBAN>{batch['debtor_iban']}</IBAN></Id></DbtrAcct>",
        "   <DbtrAgt><FinInstnId><Othr><Id>NOTPROVIDED</Id></Othr></FinInstnId></DbtrAgt>",
        "   <ChrgBr>SLEV</ChrgBr>",
    ]
    for item in items:
        out += [
            "   <CdtTrfTxInf>",
            f"    <PmtId><EndToEndId>{sepa_text(item['check_id'], 35)}</EndToEndId></PmtId>",
            f'    <Amt><InstdAmt Ccy="EUR">{_amount(item["amount_cents"])}</InstdAmt></Amt>',
            f"    <Cdtr><Nm>{escape(sepa_text(item['payee_name'], 70))}</Nm></Cdtr>",
            f"    <CdtrAcct><Id><IBAN>{item['iban']}</IBAN></Id></CdtrAcct>",
            f"    <RmtInf><Ustrd>{escape(sepa_text(item['reference'], 140))}</Ustrd></RmtInf>",
            "   </CdtTrfTxInf>",
        ]
    out += ["  </PmtInf>", " </CstmrCdtTrfInitn>", "</Document>", ""]
    return "\n".join(out)


def _items(batch_id: str, org_id: str, db_path: str | None) -> list[dict[str, Any]]:
    return [dict(r) for r in db.query_all(
        "SELECT check_id, payee_name, iban, amount_cents, reference FROM transfer_items WHERE batch_id = ? AND org_id = ? "
        "ORDER BY position;", (batch_id, org_id), db_path=db_path)]


def create_batch(org_id: str, user_id: str, ip: str | None = None, db_path: str | None = None,
                 before: int | None = None) -> dict[str, Any]:
    """Regroupe toutes les factures bonnes à payer dans un fichier de virements. Réservé aux approver+."""
    check_org_writable(org_id, db_path=db_path)
    bank = get_bank(org_id, db_path=db_path)
    if not bank:
        raise OrgError("Renseignez d'abord le compte bancaire de votre entreprise (celui qui paie).")
    with inbox._org_lock(org_id):
        todo = [i for i in payable(org_id, db_path=db_path)["items"] if before is None or i["created_at"] < before][:MAX_PER_BATCH]
        if not todo:
            raise OrgError("Aucune facture bonne à payer n'attend de virement.")
        now = int(time.time())
        batch = {"id": "vir_" + secrets.token_hex(10), "org_id": org_id, "created_at": now,
                 "debtor_name": bank["holder"], "debtor_iban": bank["iban"], "tx_count": len(todo),
                 "total_cents": sum(i["amount_cents"] for i in todo)}
        items = [{"check_id": i["id"], "payee_name": i["payee_name"], "iban": i["iban"], "amount_cents": i["amount_cents"],
                  "reference": "Facture " + (i["invoice_number"] or i["id"])} for i in todo]
        batch["file_sha256"] = hashlib.sha256(build_xml(batch, items).encode("utf-8")).hexdigest()
        with db.transaction(db_path) as conn:        # tout le lot ou rien
            conn.execute(
                "INSERT INTO transfer_batches (id, org_id, created_by, debtor_name, debtor_iban, tx_count, total_cents, "
                "file_sha256, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",
                (batch["id"], org_id, user_id, batch["debtor_name"], batch["debtor_iban"], batch["tx_count"],
                 batch["total_cents"], batch["file_sha256"], now))
            conn.executemany(
                "INSERT INTO transfer_items (check_id, batch_id, org_id, position, payee_name, iban, amount_cents, reference) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?);",
                [(it["check_id"], batch["id"], org_id, n, it["payee_name"], it["iban"], it["amount_cents"], it["reference"])
                 for n, it in enumerate(items)])
    auth.log_audit("transfer.batch", org_id=org_id, user_id=user_id,
                   details={"batch_id": batch["id"], "file_sha256": batch["file_sha256"], "tx_count": batch["tx_count"],
                            "total_cents": batch["total_cents"], "check_ids": [it["check_id"] for it in items]},
                   ip=ip, db_path=db_path)
    return get_batch(org_id, batch["id"], db_path=db_path)


def get_batch(org_id: str, batch_id: str, db_path: str | None = None) -> dict[str, Any]:
    row = db.query_one("SELECT * FROM transfer_batches WHERE id = ? AND org_id = ?;", (batch_id, org_id), db_path=db_path)
    if not row:
        raise OrgError("Fichier de virements introuvable", 404)
    batch = dict(row)
    batch["items"] = _items(batch_id, org_id, db_path)
    return batch


def list_batches(org_id: str, db_path: str | None = None) -> list[dict[str, Any]]:
    return [dict(r) for r in db.query_all(
        "SELECT id, tx_count, total_cents, file_sha256, seal_status, seal_tx, seal_url, sealed_at, created_at "
        "FROM transfer_batches WHERE org_id = ? ORDER BY created_at DESC, rowid DESC LIMIT 50;", (org_id,), db_path=db_path)]


def batch_file(org_id: str, batch_id: str, db_path: str | None = None) -> tuple[str, str]:
    """(nom du fichier, contenu). Refuse de servir un fichier qui ne correspond plus à l'empreinte scellée."""
    batch = get_batch(org_id, batch_id, db_path=db_path)
    xml = build_xml(batch, batch["items"])
    if hashlib.sha256(xml.encode("utf-8")).hexdigest() != batch["file_sha256"]:
        raise OrgError("Ce fichier ne correspond plus à son empreinte : il a été altéré en base.", 409)
    return f"virements-{time.strftime('%Y%m%d', time.gmtime(batch['created_at']))}-{batch_id[-6:]}.xml", xml


def record_seal(org_id: str, user_id: str | None, batch_id: str, tx_hash: str, url: str, ip: str | None = None,
                db_path: str | None = None) -> dict[str, Any]:
    """Note que l'empreinte du fichier a été inscrite sur la blockchain (ou, hors ligne, sur le coffre simulé)."""
    status = "anchored" if tx_hash else "simulated"
    cur = db.execute("UPDATE transfer_batches SET seal_status = ?, seal_tx = ?, seal_url = ?, sealed_at = ? "
                     "WHERE id = ? AND org_id = ? AND seal_status != 'anchored';",
                     (status, tx_hash or "", url or "", int(time.time()), batch_id, org_id), db_path=db_path)
    if cur.rowcount == 1:
        auth.log_audit("transfer.seal", org_id=org_id, user_id=user_id,
                       details={"batch_id": batch_id, "status": status, "tx_hash": tx_hash or ""}, ip=ip, db_path=db_path)
    return get_batch(org_id, batch_id, db_path=db_path)
