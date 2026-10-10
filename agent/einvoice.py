"""einvoice.py — Plateforme de facturation électronique : émettre, remettre, recevoir, suivre.

Une entreprise déclare son identité (SIREN), crée une facture en saisissant le destinataire (par son SIREN) et les
lignes. La plateforme produit la facture hybride (page PDF + données XML UN/CEFACT CII, le principe du Factur-X),
la remet à l'entreprise destinataire si elle est sur la plateforme, et la fait contrôler par inbox.judge avant que
le destinataire ne la voie. L'émetteur suit le statut : remise, à vérifier, acceptée, refusée, virement préparé.

Ce que la conception interdit, par rapport à une facture reçue par mail :
  - la page et les données sortent de la même saisie : elles ne peuvent pas se contredire ;
  - le compte bancaire n'est jamais saisi sur la facture : c'est celui que l'entreprise émettrice a enregistré ;
  - le numéro est attribué par la plateforme, à la suite, sans trou ni doublon ;
  - le fichier se régénère à l'identique et son empreinte est gardée : une altération en base se voit.

Limites assumées : VaultGuard n'est pas une plateforme agréée (immatriculation DGFiP à demander). Le SIREN est
déclaré par l'entreprise, pas encore vérifié ; le PDF n'est pas un PDF/A-3 certifié ; rien n'est transmis à
l'administration ; l'échange avec les autres plateformes n'existe pas.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import sqlite3
import sys
import time
import zlib
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import auth
    import db
    import inbox
    import registry
    import transfers
    from orgs import OrgError, check_org_writable
except ImportError:
    from agent import auth, db, inbox, registry, transfers
    from agent.orgs import OrgError, check_org_writable

from sdk.invoice_reader import UnreadableInvoice, read_bytes  # noqa: E402

MAX_LINES = 50
MAX_PER_DAY = 100
VAT_PERCENT = 20
PRODUCER = "VaultGuard Facturation"


# ------------------------------------------------------------------ Identité de l'entreprise (annuaire)

def get_profile(org_id: str, db_path: str | None = None) -> dict[str, Any] | None:
    row = db.query_one("SELECT siren, address FROM company_profiles WHERE org_id = ?;", (org_id,), db_path=db_path)
    return dict(row) if row else None


def set_profile(org_id: str, user_id: str, siren: str, address: str = "", ip: str | None = None,
                db_path: str | None = None) -> dict[str, Any]:
    check_org_writable(org_id, db_path=db_path)
    digits = re.sub(r"[\s.]", "", siren) if isinstance(siren, str) else ""
    if not registry.siren_valid(digits):
        raise OrgError("SIREN invalide : 9 chiffres, tels qu'ils figurent sur votre extrait Kbis")
    clean = re.sub(r"\s+", " ", address).strip() if isinstance(address, str) else ""
    if len(clean) > 120 or any(ord(c) < 32 for c in clean):
        raise OrgError("Adresse : 120 caractères au plus")
    try:
        db.execute("INSERT INTO company_profiles (org_id, siren, address, updated_at) VALUES (?, ?, ?, ?) "
                   "ON CONFLICT(org_id) DO UPDATE SET siren = excluded.siren, address = excluded.address, "
                   "updated_at = excluded.updated_at;", (org_id, digits, clean, int(time.time())), db_path=db_path)
    except sqlite3.IntegrityError:
        raise OrgError("Ce SIREN est déjà utilisé par une autre entreprise de la plateforme", 409) from None
    auth.log_audit("company.profile", org_id=org_id, user_id=user_id, details={"siren": digits}, ip=ip, db_path=db_path)
    return {"siren": digits, "address": clean}


def find_company(siren: str, db_path: str | None = None) -> dict[str, Any] | None:
    """Annuaire : l'entreprise qui porte ce SIREN sur la plateforme, si elle y est."""
    digits = re.sub(r"[\s.]", "", siren) if isinstance(siren, str) else ""
    if not registry.siren_valid(digits):
        raise OrgError("SIREN invalide : 9 chiffres")
    row = db.query_one("SELECT o.id AS org_id, o.name, o.is_suspended, p.siren FROM company_profiles p "
                       "JOIN orgs o ON o.id = p.org_id WHERE p.siren = ?;", (digits,), db_path=db_path)
    return dict(row) if row else None


# ------------------------------------------------------------------ Fabrication du fichier (page + données)

def _money(cents: int) -> str:
    return f"{cents // 100},{cents % 100:02d}"


def _dot(cents: int) -> str:
    return f"{cents // 100}.{cents % 100:02d}"


def _spaced(iban: str) -> str:
    return " ".join(iban[i:i + 4] for i in range(0, len(iban), 4))


def _page_text(inv: dict[str, Any], lines: list[dict[str, Any]]) -> list[str]:
    day = time.strftime("%d/%m/%Y", time.gmtime(inv["created_at"]))
    due = time.strftime("%d/%m/%Y", time.gmtime(inv["created_at"] + 30 * 86400))
    siren = inv["seller_siren"]
    out = [f"{inv['seller_name'].upper()}" + (f" - {inv['seller_address']}" if inv["seller_address"] else ""),
           f"SIREN {siren[:3]} {siren[3:6]} {siren[6:]} - TVA intracommunautaire FR{registry.vat_key(siren)}{siren}",
           f"Facture n° {inv['number']} - {day}",
           f"Client : {inv['buyer_name']} (SIREN {inv['buyer_siren']})", "",
           "Désignation                               Quantité x prix HT"]
    out += [f"{line['label'][:40]:<40}  {line['quantity']} x {_money(line['unit_cents'])}" for line in lines]
    out += ["", f"Total HT : {_money(inv['total_ht_cents'])} EUR", f"TVA {VAT_PERCENT} % : {_money(inv['tax_cents'])} EUR",
            f"Total à payer : {_money(inv['total_cents'])} EUR", "",
            "Règlement par virement", f"IBAN : {_spaced(inv['seller_iban'])}", f"Échéance : {due}",
            "Pénalités de retard : trois fois le taux d'intérêt légal. Indemnité forfaitaire de recouvrement : 40 EUR.",
            "", "Facture émise sur la plateforme VaultGuard : la page et les données sont produites ensemble."]
    return out


def _xml(inv: dict[str, Any], lines: list[dict[str, Any]]) -> str:
    siren = inv["seller_siren"]
    items = "".join(
        "<ram:IncludedSupplyChainTradeLineItem>"
        f"<ram:AssociatedDocumentLineDocument><ram:LineID>{i}</ram:LineID></ram:AssociatedDocumentLineDocument>"
        f"<ram:SpecifiedTradeProduct><ram:Name>{escape(line['label'])}</ram:Name></ram:SpecifiedTradeProduct>"
        "<ram:SpecifiedLineTradeAgreement><ram:NetPriceProductTradePrice>"
        f"<ram:ChargeAmount>{_dot(line['unit_cents'])}</ram:ChargeAmount></ram:NetPriceProductTradePrice></ram:SpecifiedLineTradeAgreement>"
        f'<ram:SpecifiedLineTradeDelivery><ram:BilledQuantity unitCode="C62">{line["quantity"]}</ram:BilledQuantity></ram:SpecifiedLineTradeDelivery>'
        "</ram:IncludedSupplyChainTradeLineItem>" for i, line in enumerate(lines, 1))
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rsm:CrossIndustryInvoice xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100" '
        'xmlns:ram="urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100" '
        'xmlns:udt="urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100">'
        f"<rsm:ExchangedDocument><ram:ID>{escape(inv['number'])}</ram:ID><ram:TypeCode>380</ram:TypeCode>"
        f'<ram:IssueDateTime><udt:DateTimeString format="102">{time.strftime("%Y%m%d", time.gmtime(inv["created_at"]))}'
        "</udt:DateTimeString></ram:IssueDateTime></rsm:ExchangedDocument>"
        f"<rsm:SupplyChainTradeTransaction>{items}"
        "<ram:ApplicableHeaderTradeAgreement>"
        f"<ram:SellerTradeParty><ram:Name>{escape(inv['seller_name'])}</ram:Name>"
        f'<ram:SpecifiedLegalOrganization><ram:ID schemeID="0002">{siren}</ram:ID></ram:SpecifiedLegalOrganization>'
        f'<ram:SpecifiedTaxRegistration><ram:ID schemeID="VA">FR{registry.vat_key(siren)}{siren}</ram:ID></ram:SpecifiedTaxRegistration>'
        "</ram:SellerTradeParty>"
        f"<ram:BuyerTradeParty><ram:Name>{escape(inv['buyer_name'])}</ram:Name>"
        f'<ram:SpecifiedLegalOrganization><ram:ID schemeID="0002">{inv["buyer_siren"]}</ram:ID></ram:SpecifiedLegalOrganization>'
        "</ram:BuyerTradeParty></ram:ApplicableHeaderTradeAgreement>"
        "<ram:ApplicableHeaderTradeSettlement><ram:InvoiceCurrencyCode>EUR</ram:InvoiceCurrencyCode>"
        "<ram:SpecifiedTradeSettlementPaymentMeans><ram:TypeCode>30</ram:TypeCode>"
        f"<ram:PayeePartyCreditorFinancialAccount><ram:IBANID>{inv['seller_iban']}</ram:IBANID></ram:PayeePartyCreditorFinancialAccount>"
        "</ram:SpecifiedTradeSettlementPaymentMeans>"
        "<ram:SpecifiedTradeSettlementHeaderMonetarySummation>"
        f"<ram:LineTotalAmount>{_dot(inv['total_ht_cents'])}</ram:LineTotalAmount>"
        f"<ram:TaxBasisTotalAmount>{_dot(inv['total_ht_cents'])}</ram:TaxBasisTotalAmount>"
        f'<ram:TaxTotalAmount currencyID="EUR">{_dot(inv["tax_cents"])}</ram:TaxTotalAmount>'
        f"<ram:GrandTotalAmount>{_dot(inv['total_cents'])}</ram:GrandTotalAmount>"
        f"<ram:DuePayableAmount>{_dot(inv['total_cents'])}</ram:DuePayableAmount>"
        "</ram:SpecifiedTradeSettlementHeaderMonetarySummation></ram:ApplicableHeaderTradeSettlement>"
        "</rsm:SupplyChainTradeTransaction></rsm:CrossIndustryInvoice>\n")


def _stream(payload: bytes, extra: bytes = b"") -> bytes:
    data = zlib.compress(payload, 9)
    return b"<< /Length %d /Filter /FlateDecode %s>>\nstream\n" % (len(data), extra) + data + b"\nendstream"


def render(inv: dict[str, Any]) -> bytes:
    """Le fichier de la facture. Ne dépend que de la ligne enregistrée : même facture, mêmes octets."""
    lines = json.loads(inv["lines_json"])
    ops = [b"BT /F1 10 Tf 50 790 Td 15 TL"]
    for text in _page_text(inv, lines):
        raw = text.encode("cp1252", "replace").replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")
        ops.append(b"(" + raw + b") Tj T*")
    ops.append(b"ET")
    stamp = time.strftime("D:%Y%m%d%H%M%SZ", time.gmtime(inv["created_at"])).encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R /Names << /EmbeddedFiles << /Names [(factur-x.xml) 7 0 R] >> >> /AF [7 0 R] >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        _stream(b"\n".join(ops)),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        _stream(_xml(inv, lines).encode("utf-8"), b"/Type /EmbeddedFile /Subtype /text#2Fxml "),
        b"<< /Type /Filespec /F (factur-x.xml) /UF (factur-x.xml) /AFRelationship /Alternative /EF << /F 6 0 R >> >>",
        b"<< /Producer (%s) /Creator (%s) /CreationDate (%s) /ModDate (%s) >>" % (PRODUCER.encode(), PRODUCER.encode(), stamp, stamp),
    ]
    out, offsets = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n", []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R /Info 8 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return out


# ------------------------------------------------------------------ Émettre et remettre

def _clean_lines(lines: Any) -> list[dict[str, Any]]:
    if not isinstance(lines, list) or not 1 <= len(lines) <= MAX_LINES:
        raise OrgError(f"Entre 1 et {MAX_LINES} lignes de facture")
    out = []
    for line in lines:
        if not isinstance(line, dict):
            raise OrgError("Ligne de facture invalide")
        label = re.sub(r"\s+", " ", line.get("label", "")).strip() if isinstance(line.get("label"), str) else ""
        quantity = line.get("quantity")
        price = line.get("unit_price")
        if not 2 <= len(label) <= 120 or any(ord(c) < 32 for c in label):
            raise OrgError("Désignation : entre 2 et 120 caractères")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or not 1 <= quantity <= 9999:
            raise OrgError("Quantité : un nombre entier entre 1 et 9 999")
        # Le prix arrive en texte (« 150,00 ») : converti en centimes sans passer par un nombre flottant.
        m = re.fullmatch(r"(\d{1,7})(?:[.,](\d{1,2}))?", price.strip()) if isinstance(price, str) else None
        if not m:
            raise OrgError("Prix unitaire hors taxes : un montant en euros, par exemple 150,00")
        unit_cents = int(m.group(1)) * 100 + int((m.group(2) or "0").ljust(2, "0"))
        if unit_cents <= 0:
            raise OrgError("Prix unitaire : supérieur à zéro")
        out.append({"label": label, "quantity": quantity, "unit_cents": unit_cents})
    return out


def _judge_context(org_id: str, db_path: str | None) -> dict[str, Any] | None:
    box = inbox.ensure_inbox(org_id, db_path=db_path)
    return inbox.org_for_alias(box["alias"], db_path=db_path)


def create_invoice(org_id: str, user_id: str, buyer_siren: str, lines: Any, buyer_name: str = "",
                   ip: str | None = None, db_path: str | None = None) -> dict[str, Any]:
    """Crée la facture, la numérote, la remet au destinataire s'il est sur la plateforme et la fait contrôler."""
    org = check_org_writable(org_id, db_path=db_path)
    profile = get_profile(org_id, db_path=db_path)
    if not profile:
        raise OrgError("Renseignez d'abord le SIREN de votre entreprise")
    bank = transfers.get_bank(org_id, db_path=db_path)
    if not bank:
        raise OrgError("Renseignez d'abord le compte bancaire de votre entreprise (menu « Factures reçues »)")
    clean = _clean_lines(lines)
    buyer = find_company(buyer_siren, db_path=db_path)
    digits = re.sub(r"[\s.]", "", buyer_siren)
    if digits == profile["siren"]:
        raise OrgError("Le destinataire ne peut pas être votre propre entreprise")
    name = buyer["name"] if buyer else (re.sub(r"\s+", " ", buyer_name).strip() if isinstance(buyer_name, str) else "")
    if not 2 <= len(name) <= 80 or any(ord(c) < 32 for c in name):
        raise OrgError("Ce SIREN n'est pas sur la plateforme : indiquez le nom du destinataire (2 à 80 caractères)")
    total_ht = sum(line["quantity"] * line["unit_cents"] for line in clean)
    if total_ht > 10 ** 11:
        raise OrgError("Montant total trop élevé")
    tax = (total_ht * VAT_PERCENT + 50) // 100
    now = int(time.time())
    invoice_id = "inv_" + secrets.token_hex(10)
    year = time.strftime("%Y", time.gmtime(now))
    with inbox._org_lock(org_id):
        today = db.query_one("SELECT COUNT(*) AS c FROM issued_invoices WHERE org_id = ? AND created_at >= ?;",
                             (org_id, now - 86400), db_path=db_path)
        if today and today["c"] >= MAX_PER_DAY:
            raise OrgError(f"Limite de {MAX_PER_DAY} factures par jour atteinte", 429)
        # Numérotation à la suite, sans trou : attribuée ici, sous verrou, jamais saisie.
        count = db.query_one("SELECT COUNT(*) AS c FROM issued_invoices WHERE org_id = ? AND number LIKE ?;",
                             (org_id, f"F-{year}-%"), db_path=db_path)
        inv = {"id": invoice_id, "org_id": org_id, "number": f"F-{year}-{(count['c'] if count else 0) + 1:04d}",
               "seller_name": org["name"], "seller_siren": profile["siren"], "seller_address": profile["address"],
               "seller_iban": bank["iban"], "buyer_name": name, "buyer_siren": digits,
               "buyer_org_id": buyer["org_id"] if buyer and not buyer["is_suspended"] else None,
               "lines_json": json.dumps(clean, ensure_ascii=False), "total_ht_cents": total_ht, "tax_cents": tax,
               "total_cents": total_ht + tax, "created_by": user_id, "created_at": now}
        data = render(inv)
        inv["file_sha256"] = hashlib.sha256(data).hexdigest()
        db.execute("INSERT INTO issued_invoices (id, org_id, number, seller_name, seller_siren, seller_address, seller_iban, "
                   "buyer_name, buyer_siren, buyer_org_id, lines_json, total_ht_cents, tax_cents, total_cents, file_sha256, "
                   "created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);",
                   tuple(inv[k] for k in ("id", "org_id", "number", "seller_name", "seller_siren", "seller_address",
                                          "seller_iban", "buyer_name", "buyer_siren", "buyer_org_id", "lines_json",
                                          "total_ht_cents", "tax_cents", "total_cents", "file_sha256", "created_by",
                                          "created_at")), db_path=db_path)
    auth.log_audit("einvoice.issue", org_id=org_id, user_id=user_id,
                   details={"invoice_id": invoice_id, "number": inv["number"], "file_sha256": inv["file_sha256"],
                            "total_cents": inv["total_cents"], "delivered": bool(inv["buyer_org_id"])}, ip=ip, db_path=db_path)
    if inv["buyer_org_id"]:
        _deliver(inv, data, db_path)
    return get_issued(org_id, invoice_id, db_path=db_path)


def _deliver(inv: dict[str, Any], data: bytes, db_path: str | None) -> None:
    """Remise au destinataire : la facture passe par le même contrôle qu'une facture reçue par mail."""
    context = _judge_context(inv["buyer_org_id"], db_path)
    if not context:
        return
    try:
        result = inbox.judge(context, read_bytes(data, inv["number"] + ".pdf"), db_path=db_path)
    except UnreadableInvoice:
        result = inbox.judge(context, None, db_path=db_path, unreadable=True, file_sha256=inv["file_sha256"])
    db.execute("UPDATE issued_invoices SET check_id = ? WHERE id = ? AND check_id IS NULL;", (result["id"], inv["id"]),
               db_path=db_path)
    auth.log_audit("einvoice.receive", org_id=inv["buyer_org_id"],
                   details={"invoice_id": inv["id"], "check_id": result["id"], "file_sha256": inv["file_sha256"],
                            "seller_siren": inv["seller_siren"]}, db_path=db_path)


# ------------------------------------------------------------------ Suivre

STATUS = {
    "undelivered": "Non remise : le destinataire n'est pas sur la plateforme. Téléchargez-la pour la lui transmettre.",
    "review": "Remise. En attente d'une vérification chez le destinataire.",
    "ok": "Acceptée : bonne à payer chez le destinataire.",
    "refused": "Refusée par le destinataire.",
    "paid": "Virement préparé par le destinataire.",
}


def _with_status(row: Any, db_path: str | None) -> dict[str, Any]:
    d = dict(row)
    d["lines"] = json.loads(d.pop("lines_json"))
    status = "undelivered"
    if d["check_id"]:
        check = db.query_one("SELECT verdict FROM invoice_checks WHERE id = ?;", (d["check_id"],), db_path=db_path)
        status = check["verdict"] if check else "review"
        if status == "ok" and db.query_one("SELECT 1 FROM transfer_items WHERE check_id = ?;", (d["check_id"],), db_path=db_path):
            status = "paid"
    d["status"], d["status_text"] = status, STATUS[status]
    d.pop("buyer_org_id", None)                     # l'émetteur n'a pas à connaître l'identifiant interne du client
    d.pop("check_id", None)
    return d


def list_issued(org_id: str, db_path: str | None = None) -> list[dict[str, Any]]:
    rows = db.query_all("SELECT * FROM issued_invoices WHERE org_id = ? ORDER BY created_at DESC, rowid DESC LIMIT 200;",
                        (org_id,), db_path=db_path)
    return [_with_status(r, db_path) for r in rows]


def get_issued(org_id: str, invoice_id: str, db_path: str | None = None) -> dict[str, Any]:
    row = db.query_one("SELECT * FROM issued_invoices WHERE id = ? AND org_id = ?;", (invoice_id, org_id), db_path=db_path)
    if not row:
        raise OrgError("Facture introuvable", 404)
    return _with_status(row, db_path)


def _file(row: Any) -> tuple[str, bytes]:
    data = render(dict(row))
    if hashlib.sha256(data).hexdigest() != row["file_sha256"]:
        raise OrgError("Cette facture ne correspond plus à son empreinte : elle a été altérée en base.", 409)
    return re.sub(r"[^A-Za-z0-9-]", "", row["number"]) + ".pdf", data


def issued_file(org_id: str, invoice_id: str, db_path: str | None = None) -> tuple[str, bytes]:
    """Le fichier d'une facture que cette entreprise a émise."""
    row = db.query_one("SELECT * FROM issued_invoices WHERE id = ? AND org_id = ?;", (invoice_id, org_id), db_path=db_path)
    if not row:
        raise OrgError("Facture introuvable", 404)
    return _file(row)


def received_file(org_id: str, check_id: str, db_path: str | None = None) -> tuple[str, bytes]:
    """Le fichier d'une facture que cette entreprise a reçue par la plateforme."""
    row = db.query_one("SELECT * FROM issued_invoices WHERE check_id = ? AND buyer_org_id = ?;", (check_id, org_id),
                       db_path=db_path)
    if not row:
        raise OrgError("Facture introuvable", 404)
    return _file(row)


def received_index(org_id: str, db_path: str | None = None) -> dict[str, dict[str, str]]:
    """Factures reçues par la plateforme : contrôle -> émetteur. Sert à l'écran « Factures reçues »."""
    return {r["check_id"]: {"seller_name": r["seller_name"], "seller_siren": r["seller_siren"]} for r in db.query_all(
        "SELECT check_id, seller_name, seller_siren FROM issued_invoices WHERE buyer_org_id = ? AND check_id IS NOT NULL "
        "ORDER BY created_at DESC LIMIT 200;", (org_id,), db_path=db_path)}


def overview(org_id: str, db_path: str | None = None) -> dict[str, Any]:
    return {"profile": get_profile(org_id, db_path=db_path), "bank": transfers.get_bank(org_id, db_path=db_path),
            "issued": list_issued(org_id, db_path=db_path), "vat_percent": VAT_PERCENT}
