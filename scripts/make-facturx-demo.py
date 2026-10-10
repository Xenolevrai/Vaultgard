"""Fabrique examples/factures/08-garage-dupont-facturx.pdf : un PDF lisible par un humain qui embarque la même
facture en XML (UN/CEFACT CII), comme un Factur-X. Sans dépendance.

Usage (depuis vaultguard/) : python3 scripts/make-facturx-demo.py
"""
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "examples" / "factures" / "08-garage-dupont-facturx.pdf"

XML = """<?xml version="1.0" encoding="UTF-8"?>
<rsm:CrossIndustryInvoice xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"
    xmlns:ram="urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100">
  <rsm:ExchangedDocument><ram:ID>GD-2026-1008</ram:ID></rsm:ExchangedDocument>
  <rsm:SupplyChainTradeTransaction>
    <ram:IncludedSupplyChainTradeLineItem>
      <ram:SpecifiedTradeProduct><ram:Name>Vidange camion</ram:Name></ram:SpecifiedTradeProduct>
      <ram:SpecifiedLineTradeAgreement><ram:NetPriceProductTradePrice><ram:ChargeAmount>25.00</ram:ChargeAmount></ram:NetPriceProductTradePrice></ram:SpecifiedLineTradeAgreement>
      <ram:SpecifiedLineTradeDelivery><ram:BilledQuantity unitCode="C62">2</ram:BilledQuantity></ram:SpecifiedLineTradeDelivery>
    </ram:IncludedSupplyChainTradeLineItem>
    <ram:ApplicableHeaderTradeAgreement>
      <ram:SellerTradeParty><ram:Name>Garage Dupont</ram:Name></ram:SellerTradeParty>
      <ram:BuyerTradeParty><ram:Name>Transports Martin</ram:Name></ram:BuyerTradeParty>
    </ram:ApplicableHeaderTradeAgreement>
    <ram:ApplicableHeaderTradeSettlement>
      <ram:InvoiceCurrencyCode>EUR</ram:InvoiceCurrencyCode>
      <ram:SpecifiedTradeSettlementPaymentMeans>
        <ram:PayeePartyCreditorFinancialAccount><ram:ProprietaryID>0xd92b1525628baa7ab228796fd49304ef1435a234</ram:ProprietaryID></ram:PayeePartyCreditorFinancialAccount>
      </ram:SpecifiedTradeSettlementPaymentMeans>
      <ram:SpecifiedTradeSettlementHeaderMonetarySummation>
        <ram:TaxTotalAmount currencyID="EUR">0.00</ram:TaxTotalAmount>
        <ram:GrandTotalAmount>50.00</ram:GrandTotalAmount>
        <ram:DuePayableAmount>50.00</ram:DuePayableAmount>
      </ram:SpecifiedTradeSettlementHeaderMonetarySummation>
    </ram:ApplicableHeaderTradeSettlement>
  </rsm:SupplyChainTradeTransaction>
</rsm:CrossIndustryInvoice>
"""

LINES = ["GARAGE DUPONT SARL - 12 rue des Ateliers, 95000 Cergy", "Facture n° GD-2026-1008 - 10/10/2026",
         "Client : Transports Martin", "", "Vidange camion        2 x 25.00", "", "TVA : 0.00",
         "Total facture : 50.00 EUR", "À régler à : 0xd92b1525628baa7ab228796fd49304ef1435a234"]


def text_ops() -> bytes:
    ops = [b"BT /F1 11 Tf 50 780 Td 16 TL"]
    for line in LINES:
        raw = line.encode("cp1252").replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")
        ops.append(b"(" + raw + b") Tj T*")
    ops.append(b"ET")
    return b"\n".join(ops)


def stream(payload: bytes, extra: bytes = b"") -> bytes:
    data = zlib.compress(payload)
    return b"<< /Length %d /Filter /FlateDecode %s>>\nstream\n" % (len(data), extra) + data + b"\nendstream"


objects = [
    b"<< /Type /Catalog /Pages 2 0 R /Names << /EmbeddedFiles << /Names [(factur-x.xml) 7 0 R] >> >> /AF [7 0 R] >>",
    b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
    stream(text_ops()),
    b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    stream(XML.encode("utf-8"), b"/Type /EmbeddedFile /Subtype /text#2Fxml "),
    b"<< /Type /Filespec /F (factur-x.xml) /UF (factur-x.xml) /AFRelationship /Alternative /EF << /F 6 0 R >> >>",
]

pdf, offsets = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n", []
for number, body in enumerate(objects, 1):
    offsets.append(len(pdf))
    pdf += b"%d 0 obj\n" % number + body + b"\nendobj\n"
xref = len(pdf)
pdf += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
pdf += b"".join(b"%010d 00000 n \n" % o for o in offsets)
pdf += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
OUT.write_bytes(pdf)
print("écrit :", OUT.name, len(pdf), "octets")
