"""invoice_reader.py — lit une facture dans les formats courants, sur la machine de l'entreprise.

Aucun service tiers, aucune dépendance : la facture ne sort pas de chez le client. Seul le texte extrait part
vers VaultGuard, qui l'analyse en mémoire et n'en garde que l'empreinte SHA-256.

Formats :
  - texte (.txt, corps de mail), HTML
  - XML structuré de la facturation électronique : UBL 2.1 et UN/CEFACT CII
  - PDF : texte des pages, et XML embarqué d'un Factur-X (PDF + CII)
  - mail (.eml) avec ses pièces jointes
  - Word (.docx) et OpenDocument (.odt)
  - image ou PDF scanné : seulement si l'outil « tesseract » est installé (OCR local)
Un format illisible lève UnreadableInvoice : la facture va alors à un humain, jamais en paiement automatique.

Le champ `text` contient tout ce qu'un agent IA lirait, texte invisible et commentaires compris : c'est lui que
le pare-feu doit voir. Rien n'est tronqué (un ordre caché après la coupure passerait inaperçu) : `documents()`
découpe le texte en morceaux qui se recouvrent.
"""
from __future__ import annotations

import bisect
import email
import email.policy
import hashlib
import html
import io
import re
import shutil
import subprocess  # nosec B404
import tempfile
import xml.etree.ElementTree as ET  # nosec B405
import zipfile
import zlib
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

# Bandit : subprocess ne sert qu'à l'OCR local optionnel (arguments fixes) ; pour le XML, DOCTYPE et entités
# sont refusés avant l'analyse (voir _xml), ce qui écarte XXE et entités explosives sans dépendance.

MAX_BYTES = 10_000_000       # taille maximale d'un fichier
MAX_INFLATED = 20_000_000    # taille maximale après décompression (anti « bombe » zip / zlib)
DOC_CHARS = 30_000           # l'API accepte 32 000 caractères par document
DOC_OVERLAP = 500
MAX_DOCS = 20

ADDRESS = r"0x[0-9a-fA-F]{40}"
CURRENCY = r"(EUR|€|USD|\$|AVAX|EURC|USDC)"
NUMBER = r"(\d[\d .,  ]*)"


class UnreadableInvoice(ValueError):
    """Format non reconnu, fichier trop gros ou sans texte exploitable."""


def num(value) -> str:
    """Nombre écrit à la française ou à l'anglaise -> « 1234.50 » ; chaîne vide si illisible."""
    s = re.sub(r"[\s  ]", "", str(value or ""))
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    else:
        s = s.replace(",", ".")
    try:
        d = Decimal(s)
    except InvalidOperation:
        return ""
    if not d.is_finite() or d < 0 or d >= Decimal("1e12"):
        return ""
    return f"{d.quantize(Decimal('0.000001')).normalize():f}" if d != d.to_integral() else f"{d.to_integral():f}"


@dataclass
class Invoice:
    fmt: str
    name: str = ""
    text: str = ""
    number: str = ""
    supplier: str = ""
    currency: str = ""
    total: str = ""
    tax: str = ""
    pay_to: str = ""
    lines: list[dict[str, str]] = field(default_factory=list)
    file_sha256: str = ""
    attachments: list[dict[str, str]] = field(default_factory=list)  # mail : [{sha256, total}] par pièce jointe
    # Facture hybride (PDF + XML embarqué) : ce que la PAGE montre à un humain. Les autres champs viennent du XML,
    # que lisent les logiciels. Rien n'oblige les deux à dire la même chose : c'est à l'appelant de les comparer.
    shown: str = ""
    seen: dict[str, str] = field(default_factory=dict)               # {number, total, currency} lus sur la page
    # PDF retouché : texte des versions remplacées, encore présentes dans le fichier, et indices de retouche.
    previous: str = ""
    traces: list[str] = field(default_factory=list)

    def documents(self) -> list[dict[str, str]]:
        """Le texte complet, découpé pour l'API : [{source, content, file_sha256}]."""
        step = DOC_CHARS - DOC_OVERLAP
        chunks = [self.text[i:i + DOC_CHARS] for i in range(0, max(len(self.text), 1), step)]
        if len(chunks) > MAX_DOCS:
            raise UnreadableInvoice("facture trop volumineuse pour un traitement automatique")
        return [{"source": f"{self.name[:200]} ({i}/{len(chunks)})", "content": c, "file_sha256": self.file_sha256}
                for i, c in enumerate(chunks, 1)]

    def structured(self, references: list[dict[str, str]] | None = None, factor: str = "") -> dict | None:
        """La facture sous la forme attendue par le contrôle de cohérence de VaultGuard (None si pas de total)."""
        if not self.total or not self.currency:
            return None
        out = {"currency": self.currency, "total": self.total, "lines": self.lines[:200],
               "references": references or []}
        if self.tax:
            out["tax"] = self.tax
        if factor:
            out["factor"] = factor
        return out


# ------------------------------------------------------------------ Texte libre

def readable(markup: str) -> str:
    """Version sans balises d'un HTML, pour y retrouver montant et adresse."""
    text = re.sub(r"<(br|/p|/div|/tr|/li|/h\d)[^>]*>", "\n", markup, flags=re.I)
    text = re.sub(r"<!--|-->", " ", text)
    return html.unescape(re.sub(r"<[^>]+>", "", text)).replace("\xa0", " ")


def _currency(symbol: str) -> str:
    return {"€": "EUR", "$": "USD"}.get(symbol, symbol.upper())


def _from_text(inv: Invoice, text: str) -> Invoice:
    """Complète les champs absents à partir du texte (factures non structurées)."""
    if not inv.number:
        m = re.search(r"(?:Facture|Invoice)\s*(?:n°|no\.?|#|numéro)\s*:?\s*([A-Za-z0-9][\w/-]*)", text, re.I)
        inv.number = m.group(1) if m else ""
    if not inv.pay_to:
        m = re.search(r"(?:régler à|payer à|pay to)\s*:?\s*(" + ADDRESS + ")", text, re.I)
        inv.pay_to = m.group(1) if m else ""
    if not inv.total:
        for label in (r"Total\s+(?:facture|TTC|général|due)", r"Total à payer", r"Net à payer", r"Amount due"):
            m = re.search(label + r"\s*:?\s*" + NUMBER + r"\s*" + CURRENCY, text, re.I)
            if m and num(m.group(1)):
                inv.total, inv.currency = num(m.group(1)), _currency(m.group(2))
                break
    if not inv.tax:
        m = re.search(r"(?:TVA|VAT)[^:\n]*:\s*" + NUMBER, text, re.I)
        inv.tax = num(m.group(1)) if m else ""
    if not inv.lines:
        # « Désignation      quantité x prix unitaire »
        for m in re.finditer(r"^[ \t]*(\S.*?)[ \t]{2,}(\d+(?:[.,]\d+)?)[ \t]*[x×][ \t]*(\d+(?:[.,]\d+)?)", text, re.M):
            if num(m.group(2)) and num(m.group(3)):
                inv.lines.append({"label": m.group(1).strip()[:200], "quantity": num(m.group(2)),
                                  "unit_price": num(m.group(3))})
    return inv


# ------------------------------------------------------------------ XML (UBL, CII)

def _local(tag) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _first(node, *path: str) -> str:
    """Texte du premier descendant suivant le chemin de noms locaux (espaces de noms ignorés)."""
    for name in path:
        node = next((e for e in node.iter() if e is not node and _local(e.tag) == name), None)
        if node is None:
            return ""
    return (node.text or "").strip()


def _child(node, name: str) -> str:
    for e in node:
        if _local(e.tag) == name:
            return (e.text or "").strip()
    return ""


def _xml(raw: str, name: str) -> Invoice:
    # Un DOCTYPE permet des entités externes (lecture de fichiers locaux) ou explosives : refusé d'emblée.
    if re.search(r"<!\s*(DOCTYPE|ENTITY)", raw, re.I):
        raise UnreadableInvoice("XML avec DOCTYPE ou entités : refusé")
    try:
        root = ET.fromstring(raw.encode("utf-8"))  # nosec B314
    except ET.ParseError as e:
        raise UnreadableInvoice(f"XML invalide ({e})") from e
    kind = _local(root.tag)
    inv = Invoice(fmt="xml", name=name, text=raw)
    if kind == "CrossIndustryInvoice":
        inv.fmt = "cii"
        inv.number = _first(root, "ExchangedDocument", "ID")
        inv.supplier = _first(root, "SellerTradeParty", "Name")
        inv.currency = _first(root, "InvoiceCurrencyCode").upper()
        summary = "SpecifiedTradeSettlementHeaderMonetarySummation"
        inv.total = num(_first(root, summary, "DuePayableAmount") or _first(root, summary, "GrandTotalAmount"))
        inv.tax = num(_first(root, summary, "TaxTotalAmount"))
        inv.pay_to = (_first(root, "PayeePartyCreditorFinancialAccount", "IBANID")
                      or _first(root, "PayeePartyCreditorFinancialAccount", "ProprietaryID"))
        items = [e for e in root.iter() if _local(e.tag) == "IncludedSupplyChainTradeLineItem"]
        fields = (("SpecifiedTradeProduct", "Name"), ("BilledQuantity",), ("NetPriceProductTradePrice", "ChargeAmount"))
    elif kind in ("Invoice", "CreditNote"):
        inv.fmt = "ubl"
        inv.number = _child(root, "ID")
        inv.supplier = (_first(root, "AccountingSupplierParty", "RegistrationName")
                        or _first(root, "AccountingSupplierParty", "PartyName", "Name"))
        inv.currency = _child(root, "DocumentCurrencyCode").upper()
        inv.total = num(_first(root, "LegalMonetaryTotal", "PayableAmount"))
        tax = next((e for e in root if _local(e.tag) == "TaxTotal"), None)
        inv.tax = num(_child(tax, "TaxAmount")) if tax is not None else ""
        inv.pay_to = _first(root, "PaymentMeans", "PayeeFinancialAccount", "ID")
        items = [e for e in root if _local(e.tag) in ("InvoiceLine", "CreditNoteLine")]
        fields = (("Item", "Name"), ("InvoicedQuantity",), ("Price", "PriceAmount"))
    else:
        raise UnreadableInvoice(f"XML de type « {kind} » : ni UBL ni CII")
    for item in items:
        label, quantity, unit = (_first(item, *path) for path in fields)
        if num(quantity) and num(unit):
            inv.lines.append({"label": label[:200], "quantity": num(quantity), "unit_price": num(unit)})
    return inv


# ------------------------------------------------------------------ PDF

def _inflate(raw: bytes, budget: int) -> bytes:
    try:
        return zlib.decompressobj().decompress(raw, budget)
    except zlib.error:
        return raw


def _pdf_string(raw: bytes) -> str:
    def unescape(m):
        c = m.group(1)
        if c[:1].isdigit():
            return bytes([int(c, 8) & 0xFF])
        return {b"n": b"\n", b"r": b"\r", b"t": b"\t", b"b": b"\b", b"f": b"\f"}.get(c, c)
    data = re.sub(rb"\\([0-7]{1,3}|.)", unescape, raw, flags=re.S)
    return data[2:].decode("utf-16-be", "replace") if data.startswith(b"\xfe\xff") else data.decode("cp1252", "replace")


def _pdf_hex(raw: bytes) -> str:
    digits = re.sub(rb"\s", b"", raw)
    try:
        data = bytes.fromhex((digits + b"0" * (len(digits) % 2)).decode("ascii"))
    except ValueError:
        return ""
    return data[2:].decode("utf-16-be", "replace") if data.startswith(b"\xfe\xff") else data.decode("cp1252", "replace")


_PDF_OPS = re.compile(
    rb"\[((?:\\.|[^\]\\])*)\]\s*TJ"                 # tableau de morceaux de texte
    rb"|\(((?:\\.|[^\\()])*)\)\s*(?:Tj|'|\")"       # chaîne simple
    rb"|<([0-9A-Fa-f\s]+)>\s*Tj"                    # chaîne hexadécimale
    rb"|(T\*|T[dD]\b|ET\b)", re.S)                  # fin de ligne ou de bloc


def _pdf_page_text(stream: bytes) -> str:
    out = []
    for m in _PDF_OPS.finditer(stream):
        if m.group(1) is not None:
            for part in re.finditer(rb"\(((?:\\.|[^\\()])*)\)|<([0-9A-Fa-f\s]+)>", m.group(1), re.S):
                out.append(_pdf_string(part.group(1)) if part.group(1) is not None else _pdf_hex(part.group(2)))
        elif m.group(2) is not None:
            out.append(_pdf_string(m.group(2)))
        elif m.group(3) is not None:
            out.append(_pdf_hex(m.group(3)))
        else:
            out.append("\n")
    return "".join(out)


def _pdf(data: bytes, name: str) -> Invoice:
    """Texte des pages (visible ou non) et XML embarqué d'un Factur-X. Extraction simple : les PDF chiffrés ou
    à polices exotiques ne donnent rien et partent à un humain."""
    embedded, budget = "", MAX_INFLATED
    # Un éditeur de PDF ne réécrit pas le fichier : il ajoute à la fin une nouvelle version des objets modifiés.
    # La dernière définition d'un objet est celle qui s'affiche ; les précédentes restent lisibles dans le fichier.
    starts = [(m.start(), int(m.group(1))) for m in re.finditer(rb"(?<![0-9])(\d{1,7})[ \t]+\d{1,5}[ \t]+obj\b", data)]
    positions = [s for s, _ in starts]
    pages: list[tuple[int, str]] = []                                # (numéro d'objet, texte), dans l'ordre du fichier
    for m in re.finditer(rb"(?<!end)stream\r?\n", data):
        end = data.find(b"endstream", m.end())
        if end < 0 or budget <= 0:
            break
        stream = _inflate(data[m.end():end], budget)
        budget -= len(stream)
        if b"CrossIndustryInvoice" in stream or (b"Invoice" in stream and b"urn:oasis:names:specification:ubl" in stream):
            embedded = stream[stream.find(b"<"):].decode("utf-8", "replace").lstrip("﻿")
        elif b"BT" in stream and (b"Tj" in stream or b"TJ" in stream):
            owner = bisect.bisect_right(positions, m.start()) - 1
            pages.append((starts[owner][1] if owner >= 0 else -len(pages) - 1, _pdf_page_text(stream)))
    last = {number: i for i, (number, _) in enumerate(pages)}
    text = "\n".join(t for i, (n, t) in enumerate(pages) if last[n] == i and t.strip())
    previous = "\n".join(t for i, (n, t) in enumerate(pages) if last[n] != i and t.strip())
    traces = _pdf_traces(data)
    if previous and re.sub(r"\s+", " ", previous).strip() != re.sub(r"\s+", " ", text).strip():
        traces.append("rewritten")
    if embedded:
        inv = _xml(embedded, name)
        inv.fmt, inv.text, inv.shown = "facturx", "\n".join([embedded, text, previous]), text
        page = _from_text(Invoice(fmt="pdf"), text)
        inv.seen = {"number": page.number, "total": page.total, "currency": page.currency}
    elif sum(c.isalnum() for c in text) < 20:
        return _ocr(data, name, ".pdf")
    else:
        inv = _from_text(Invoice(fmt="pdf", name=name, text=text + ("\n" + previous if previous else "")), text)
    inv.previous, inv.traces = previous, traces
    return inv


# Logiciels qui servent à retoucher un PDF existant, pas à produire une facture.
_PDF_EDITORS = re.compile(rb"ilovepdf|sejda|smallpdf|pdfescape|pdf-?xchange|foxit|phantompdf|nitro|pdfelement|"
                          rb"wondershare|soda ?pdf|pdffiller|dochub|pdf24|inkscape|illustrator|photoshop|gimp|"
                          rb"libreoffice draw|master pdf|xodo|pdf ?candy|canva", re.I)


def _pdf_traces(data: bytes) -> list[str]:
    """Indices de retouche lisibles sans dépendance : mise à jour ajoutée après coup, logiciel de retouche,
    logiciel de fin différent du logiciel d'origine. Aucun n'est une preuve seul ; ils appuient les autres contrôles."""
    traces = []
    producers = [re.sub(rb"\s+", b" ", p).strip().lower() for p in re.findall(rb"/Producer\s*\(((?:\\.|[^\\()]){0,200})\)", data)]
    if data.count(b"%%EOF") > 1:
        traces.append("updated")
        if len(set(producers)) > 1:
            traces.append("other_tool")
    if any(_PDF_EDITORS.search(p) for p in producers):
        traces.append("editor")
    return traces


# ------------------------------------------------------------------ Bureautique, images, mails

def _office(data: bytes, name: str) -> Invoice:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            member = next((n for n in ("word/document.xml", "content.xml") if n in z.namelist()), None)
            if member is None:
                raise UnreadableInvoice("archive sans document Word ni OpenDocument")
            if z.getinfo(member).file_size > MAX_INFLATED:
                raise UnreadableInvoice("document trop volumineux une fois décompressé")
            raw = z.read(member).decode("utf-8", "replace")
    except zipfile.BadZipFile as e:
        raise UnreadableInvoice("archive illisible") from e
    text = html.unescape(re.sub(r"<[^>]+>", "", re.sub(r"</(w:p|text:p|text:h)>", "\n", raw)))
    return _from_text(Invoice(fmt="docx" if member.startswith("word") else "odt", name=name, text=text), text)


def _ocr(data: bytes, name: str, suffix: str) -> Invoice:
    """Reconnaissance de caractères locale, si tesseract est installé. Sinon : à traiter par un humain."""
    tool = shutil.which("tesseract")
    if not tool or suffix == ".pdf":
        raise UnreadableInvoice("document scanné ou image : pas de texte lisible sans OCR")
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(data)
    try:
        done = subprocess.run([tool, tmp.name, "stdout", "-l", "fra+eng"],  # nosec B603
                              capture_output=True, timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise UnreadableInvoice(f"OCR en échec ({e})") from e
    finally:
        Path(tmp.name).unlink(missing_ok=True)
    text = done.stdout.decode("utf-8", "replace")
    if sum(c.isalnum() for c in text) < 20:
        raise UnreadableInvoice("image sans texte lisible")
    return _from_text(Invoice(fmt="image", name=name, text=text), text)


def _mail(data: bytes, name: str) -> Invoice:
    """Corps du mail (texte et HTML bruts) et pièces jointes lisibles. Les champs structurés d'une pièce
    jointe (XML, Factur-X) priment sur ceux devinés dans le corps."""
    msg = email.message_from_bytes(data, policy=email.policy.default)
    parts, attached, shown = [], [], {"text/plain": [], "text/html": []}
    for part in msg.walk():
        if part.is_multipart():
            continue
        filename = part.get_filename() or ""
        payload = part.get_payload(decode=True) or b""
        if not filename and part.get_content_type() in ("text/plain", "text/html"):
            try:
                parts.append(str(part.get_content()))
            except (LookupError, UnicodeDecodeError):
                parts.append(payload.decode("utf-8", "replace"))
            shown[part.get_content_type()].append(parts[-1])
        elif filename:
            try:
                attached.append(read_bytes(payload, filename, _depth=1))
            except UnreadableInvoice as e:
                # Logo ou image de signature : presque tous les mails en portent. Si la facture elle-même est
                # une image illisible, aucun montant ne sera trouvé et un humain sera sollicité.
                if part.get_content_maintype() == "image":
                    continue
                raise UnreadableInvoice(f"pièce jointe « {filename[:60]} » illisible : {e}") from e
    body = "\n".join(parts)
    inv = Invoice(fmt="mail", name=name, text="\n".join([body, *(a.text for a in attached)]),
                  attachments=[{"sha256": a.file_sha256, "total": a.total} for a in attached])
    best = next((a for a in attached if a.total), None)
    if best:
        for attr in ("number", "supplier", "currency", "total", "tax", "pay_to", "lines", "shown", "seen"):
            setattr(inv, attr, getattr(best, attr))
        inv.fmt = f"mail+{best.fmt}"
    inv.previous = "\n".join(a.previous for a in attached if a.previous)
    inv.traces = sorted({t for a in attached for t in a.traces})
    # Un mail porte souvent le même contenu deux fois (texte et HTML) : les champs sont lus dans une seule
    # version, celle qu'affiche une messagerie, sinon chaque ligne compterait double. `inv.text` garde tout.
    visible = shown["text/html"] or shown["text/plain"]
    return _from_text(inv, readable("\n".join([*visible, *(a.text for a in attached)])))


# ------------------------------------------------------------------ Entrées

def read_bytes(data: bytes, name: str = "facture", _depth: int = 0) -> Invoice:
    if len(data) > MAX_BYTES:
        raise UnreadableInvoice("fichier trop volumineux")
    suffix = Path(name).suffix.lower()
    if data.startswith(b"%PDF"):
        inv = _pdf(data, name)
    elif data.startswith(b"PK\x03\x04"):
        inv = _office(data, name)
    elif data.startswith((b"\x89PNG", b"\xff\xd8\xff", b"GIF8", b"II*\x00", b"MM\x00*")):
        inv = _ocr(data, name, suffix or ".png")
    elif suffix == ".eml" and _depth == 0:
        inv = _mail(data, name)
    else:
        if b"\x00" in data[:4096]:
            raise UnreadableInvoice("format binaire non reconnu")
        try:
            raw = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            raw = data.decode("cp1252", "replace")
        head = raw.lstrip()[:2000].lower()
        if head.startswith("<") and ("<html" in head or "<!doctype html" in head):
            inv = _from_text(Invoice(fmt="html", name=name, text=raw), readable(raw))
        elif head.startswith("<"):
            inv = _xml(raw, name)
        else:
            inv = _from_text(Invoice(fmt="texte", name=name, text=raw), raw)
    if not inv.text.strip():
        raise UnreadableInvoice("document vide")
    inv.file_sha256 = hashlib.sha256(data).hexdigest()
    return inv


def read_file(path: str | Path) -> Invoice:
    path = Path(path)
    if path.stat().st_size > MAX_BYTES:
        raise UnreadableInvoice("fichier trop volumineux")
    return read_bytes(path.read_bytes(), path.name)
