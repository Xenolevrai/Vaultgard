"""fraudes_reelles.py — Jeu d'essai « difficile » : des modes opératoires de fraude réellement documentés.

Il n'existe pas de base publique de vraies factures frauduleuses (les victimes ne les publient pas). Chaque cas
reproduit donc un mode opératoire décrit par une source citée dans SOURCES : décisions de justice, banques,
éditeurs d'audit, DGCCRF. Les sociétés, IBAN et SIREN sont fictifs.

`corpus()` renvoie des cas {family, what, expected, code, source, raw, setup}. `expected` : ok / review / refused /
ignored. `code` : la raison attendue. `setup` : mail de préparation (une facture honnête déjà payée, par exemple),
envoyé mais non compté. Utilisé par scripts/detection-metrics.py et agent/test_fraud.py.
"""
from __future__ import annotations

import zlib

import boite_demo as demo

SOURCES = {
    "supervizor": ("Supervizor, « Les risques cachés de la facturation électronique » : IBAN frauduleux dans le XML, "
                   "compte légitime sur le PDF ; montants HT et TTC intervertis ; les plateformes lisent le XML sans "
                   "le comparer au PDF.", "https://www.supervizor.com/fr/blog/risques-caches-facturation-electronique"),
    "dafmag": ("DAF Magazine / Mata : vraie facture récupérée, compte bancaire modifié, accompagnée d'un avis de "
               "changement de compte ; « toute fraude finit logée dans le fichier de paiement ».",
               "https://www.daf-mag.fr/Thematique/fonction-finance-1242/Breves/Profitez-du-passage-a-la-facture-electronique-pour-securiser-votre-384453.htm"),
    "lbp": ("La Banque Postale, « Les fraudes au RIB version 2025 » : boîte mail du fournisseur piratée, vraie facture "
            "réutilisée, prétexte d'un audit ou d'un changement de banque.",
            "https://www.labanquepostale.fr/entreprises/actualite/2025/fraudes-rib.html"),
    "justice-pt": ("Cour de cassation, 9 septembre 2026, pourvoi n° 25-15.225 : courriel annonçant que le compte du "
                   "constructeur « n'était plus actif », RIB d'une banque portugaise, 189 893,14 € puis 175 404,11 € virés.",
                   "https://www.lemondedudroit.fr/decryptages/379-actualite-juridique/105786-arnaque-au-faux-rib-charge-de-la-preuve.html"),
    "justice-lettre": ("Cour de cassation, 17 juin 2026, pourvoi n° 24-13.306 : adresse d'expéditeur « ne différant que "
                       "d'une lettre », facture de 103 375,64 € et RIB frauduleux, fonds jamais récupérés.",
                       "https://www.lemondedudroit.fr/decryptages/379-actualite-juridique/104799-l-usurpateur-de-creancier-n-est-pas-creancier-apparent.html"),
    "hayot": ("Cabinet Hayot Expertise, 12 contrôles contre le faux RIB : cohérence pays / fournisseur, IBAN inhabituel, "
              "domaines imités.", "https://hayot-expertise.fr/blog/fraude-rib-fournisseur-controles-virement-2026"),
    "dgccrf": ("DGCCRF, « Annuaires professionnels : une arnaque qui perdure » : sociétés souvent situées à l'étranger, "
               "confusion entretenue avec un registre officiel, présentation ambiguë d'une simple offre.",
               "https://www.economie.gouv.fr/dgccrf/actualites/annuaires-professionnels-une-arnaque-qui-perdure"),
    "pdf": ("Analyse de PDF retouchés (helpnetsecurity, arXiv 2507.00827) : mise à jour ajoutée après coup, logiciel de "
            "retouche à la place du logiciel de facturation.", "https://www.helpnetsecurity.com/2025/07/07/detect-pdf-tampering-forgery/"),
    "doublon": ("Supervizor et pratique d'audit : la facture électronique ne garantit pas l'absence de doublons ; la "
                "même facture est représentée avec un numéro légèrement modifié.",
                "https://www.supervizor.com/fr/blog/risques-caches-facturation-electronique"),
    "seuil": ("Pratique d'audit interne : fractionnement d'une dépense en plusieurs factures pour rester sous le seuil "
              "de validation (contrôle classique, sans source publique précise).", ""),
}

# Comptes supplémentaires du carnet pour ce jeu d'essai.
MENUISERIE_LT = demo.make_iban("LT", "3250098765432109")        # carnet empoisonné : société française, compte lituanien
BAUER_DE = demo.make_iban("DE", "100110012620457812")           # vrai fournisseur allemand, compte allemand
ATTACKER_PT = demo.make_iban("PT", "003506519876543210987")
ATTACKER_ES = demo.make_iban("ES", "21000418450200051332")
EXTRA_PAYEES = [("Menuiserie Leroy", MENUISERIE_LT), ("Bauer Logistik", BAUER_DE)]


# ------------------------------------------------------------------ Fabrique de PDF et de Factur-X

def cii(supplier: str, number: str, label: str, quantity: int, unit_ht: str, iban: str, payable: str | None = None) -> str:
    """Facture XML UN/CEFACT CII, celle qu'un Factur-X embarque dans le PDF. TVA 20 %."""
    ht = quantity * float(unit_ht)
    siren = demo.siren_of(supplier)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rsm:CrossIndustryInvoice xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"
    xmlns:ram="urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100">
  <rsm:ExchangedDocument><ram:ID>{number}</ram:ID></rsm:ExchangedDocument>
  <rsm:SupplyChainTradeTransaction>
    <ram:IncludedSupplyChainTradeLineItem>
      <ram:SpecifiedTradeProduct><ram:Name>{label}</ram:Name></ram:SpecifiedTradeProduct>
      <ram:SpecifiedLineTradeAgreement><ram:NetPriceProductTradePrice><ram:ChargeAmount>{unit_ht}</ram:ChargeAmount></ram:NetPriceProductTradePrice></ram:SpecifiedLineTradeAgreement>
      <ram:SpecifiedLineTradeDelivery><ram:BilledQuantity unitCode="C62">{quantity}</ram:BilledQuantity></ram:SpecifiedLineTradeDelivery>
    </ram:IncludedSupplyChainTradeLineItem>
    <ram:ApplicableHeaderTradeAgreement>
      <ram:SellerTradeParty><ram:Name>{supplier}</ram:Name><ram:SpecifiedTaxRegistration><ram:ID schemeID="VA">{demo.vat(siren)}</ram:ID></ram:SpecifiedTaxRegistration></ram:SellerTradeParty>
      <ram:BuyerTradeParty><ram:Name>Transports Martin</ram:Name></ram:BuyerTradeParty>
    </ram:ApplicableHeaderTradeAgreement>
    <ram:ApplicableHeaderTradeSettlement>
      <ram:InvoiceCurrencyCode>EUR</ram:InvoiceCurrencyCode>
      <ram:SpecifiedTradeSettlementPaymentMeans>
        <ram:PayeePartyCreditorFinancialAccount><ram:IBANID>{iban}</ram:IBANID></ram:PayeePartyCreditorFinancialAccount>
      </ram:SpecifiedTradeSettlementPaymentMeans>
      <ram:SpecifiedTradeSettlementHeaderMonetarySummation>
        <ram:TaxTotalAmount currencyID="EUR">{ht * 0.2:.2f}</ram:TaxTotalAmount>
        <ram:GrandTotalAmount>{ht * 1.2:.2f}</ram:GrandTotalAmount>
        <ram:DuePayableAmount>{payable or f"{ht * 1.2:.2f}"}</ram:DuePayableAmount>
      </ram:SpecifiedTradeSettlementHeaderMonetarySummation>
    </ram:ApplicableHeaderTradeSettlement>
  </rsm:SupplyChainTradeTransaction>
</rsm:CrossIndustryInvoice>
"""


def _stream(payload: bytes, extra: bytes = b"") -> bytes:
    data = zlib.compress(payload)
    return b"<< /Length %d /Filter /FlateDecode %s>>\nstream\n" % (len(data), extra) + data + b"\nendstream"


def _page(lines: list[str]) -> bytes:
    ops = [b"BT /F1 10 Tf 50 790 Td 15 TL"]
    for line in lines:
        raw = line.encode("cp1252", "replace").replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")
        ops.append(b"(" + raw + b") Tj T*")
    ops.append(b"ET")
    return b"\n".join(ops)


def pdf(text: str, xml: str = "", producer: str = "Sage 100 Gestion commerciale", edited_with: str = "",
        edited_text: str = "") -> bytes:
    """PDF d'une page. `xml` : facture embarquée (Factur-X). `edited_with` : le fichier est ensuite retouché par ce
    logiciel, comme le fait un éditeur de PDF (mise à jour ajoutée à la fin, page remplacée par `edited_text`)."""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R" + (b" /Names << /EmbeddedFiles << /Names [(factur-x.xml) 7 0 R] >> >> /AF [7 0 R]" if xml else b"") + b" >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        _stream(_page(text.splitlines())),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    if xml:
        objects += [_stream(xml.encode("utf-8"), b"/Type /EmbeddedFile /Subtype /text#2Fxml "),
                    b"<< /Type /Filespec /F (factur-x.xml) /UF (factur-x.xml) /AFRelationship /Alternative /EF << /F 6 0 R >> >>"]
    info = len(objects) + 1
    objects.append(b"<< /Producer (%s) /Creator (%s) /CreationDate (D:20261009101500+02'00') "
                   b"/ModDate (D:20261009101500+02'00') >>" % (producer.encode(), producer.encode()))
    out, offsets = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n", []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R /Info %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, info, xref)
    if edited_with:
        page = len(out)
        out += b"4 0 obj\n" + _stream(_page((edited_text or text).splitlines())) + b"\nendobj\n"
        meta = len(out)
        out += (b"%d 0 obj\n<< /Producer (%s) /Creator (Sage 100 Gestion commerciale) /CreationDate (D:20261009101500+02'00') "
                b"/ModDate (D:20261010074200+02'00') >>\nendobj\n" % (info, edited_with.encode()))
        update = len(out)
        out += (b"xref\n4 1\n%010d 00000 n \n%d 1\n%010d 00000 n \n" % (page, info, meta)
                + b"trailer\n<< /Size %d /Root 1 0 R /Info %d 0 R /Prev %d >>\nstartxref\n%d\n%%%%EOF\n" % (info + 1, info, xref, update))
    return out


# ------------------------------------------------------------------ Démonstration en direct

def build() -> dict[str, bytes]:
    """Sept mails à déposer un par un (ENVOYER-FRAUDES-DEMO.bat), à la suite du parcours de boite_demo.build()."""
    compta, boss = demo.SENDERS
    job = ("Révision complète camion", 1, "195,00")
    text = lambda number, iban=demo.GARAGE, j=job: demo.invoice_text("Garage Dupont SARL", number, [j], iban)  # noqa: E731
    fx = lambda number, **kw: cii("Garage Dupont", number, job[0], 1, "195.00", **kw)  # noqa: E731
    att = lambda name, data: dict(sender=compta, subject="TR: facture électronique",  # noqa: E731
                                  body="Bonjour,\n\nFacture en pièce jointe.\n", attachment=(name, data, "pdf"))
    registry = next(c for c in corpus() if c["code"] == "known_scam")["raw"]
    return {
        "20-facture-electronique-normale.eml": demo.mail("20", **att("GD-2026-3001.pdf", pdf(text("GD-2026-3001"), fx("GD-2026-3001", iban=demo.GARAGE)))),
        "21-xml-autre-compte.eml": demo.mail("21", **att("GD-2026-3002.pdf", pdf(text("GD-2026-3002"), fx("GD-2026-3002", iban=demo.ATTACKER)))),
        "22-xml-autre-montant.eml": demo.mail("22", **att("GD-2026-3003.pdf", pdf(text("GD-2026-3003"), fx("GD-2026-3003", iban=demo.GARAGE, payable="432.00")))),
        "23-pdf-retouche.eml": demo.mail("23", **att("GD-2026-3004.pdf", pdf(text("GD-2026-3004", j=("Révision complète camion", 1, "115,00")),
                                                                               edited_with="iLovePDF", edited_text=text("GD-2026-3004")))),
        "24-fournisseur-sosie.eml": demo.mail("24", boss, "TR: facture", demo.invoice_text("Garage Dupond SARL", "GD-2026-3100", [job], demo.INCONNU)),
        "25-faux-registre.eml": registry,
        "26-doublon-maquille.eml": demo.mail("26", compta, "TR: relance facture", text("GD-2O26-3001")),
    }


EXPECTED = {
    "20-facture-electronique-normale.eml": "ok", "21-xml-autre-compte.eml": "refused", "22-xml-autre-montant.eml": "refused",
    "23-pdf-retouche.eml": "review", "24-fournisseur-sosie.eml": "refused", "25-faux-registre.eml": "refused",
    "26-doublon-maquille.eml": "refused",
}


def payment_file() -> str:
    """Fichier de virements SEPA tel qu'un autre logiciel le produirait, avec un compte remplacé à l'intérieur."""
    lines = [("Garage Dupont", demo.GARAGE, "234.00", "GD-2026-3001"),
             ("Loueur Camions Express", demo.ATTACKER, "2400.00", "LCE-7781"),          # carnet du logiciel modifié
             ("Epicerie Pro", demo.EPICERIE, "126.00", "EP-3310"),
             ("Nettoyage Express 95", demo.INCONNU, "360.00", "NE-0456")]
    rows = "".join(
        f"   <CdtTrfTxInf>\n    <PmtId><EndToEndId>{ref}</EndToEndId></PmtId>\n"
        f'    <Amt><InstdAmt Ccy="EUR">{amount}</InstdAmt></Amt>\n    <Cdtr><Nm>{name}</Nm></Cdtr>\n'
        f"    <CdtrAcct><Id><IBAN>{iban}</IBAN></Id></CdtrAcct>\n    <RmtInf><Ustrd>Facture {ref}</Ustrd></RmtInf>\n   </CdtTrfTxInf>\n"
        for name, iban, amount, ref in lines)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.001.001.03">\n'
            " <CstmrCdtTrfInitn>\n  <GrpHdr><MsgId>COMPTA-2026-10-11</MsgId><CreDtTm>2026-10-11T08:00:00</CreDtTm>"
            "<NbOfTxs>4</NbOfTxs><CtrlSum>3120.00</CtrlSum><InitgPty><Nm>Transports Martin</Nm></InitgPty></GrpHdr>\n"
            "  <PmtInf>\n   <PmtInfId>COMPTA-2026-10-11</PmtInfId><PmtMtd>TRF</PmtMtd>\n"
            f"   <Dbtr><Nm>Transports Martin</Nm></Dbtr><DbtrAcct><Id><IBAN>{demo.COMPANY_IBAN}</IBAN></Id></DbtrAcct>\n"
            f"{rows}  </PmtInf>\n </CstmrCdtTrfInitn>\n</Document>\n")


# ------------------------------------------------------------------ Les cas

def corpus() -> list[dict]:
    compta, boss = demo.SENDERS
    out: list[dict] = []
    n = 0

    def add(family: str, what: str, expected: str, code: str, source: str, setup: bool = False, **kw) -> None:
        nonlocal n
        n += 1
        out.append({"family": family, "what": what, "expected": expected, "code": code, "source": source,
                    "setup": setup, "raw": demo.mail(f"r{n}", **kw)})

    def attach(name: str, data: bytes) -> dict:
        return dict(sender=compta, subject="TR: facture", body="Bonjour,\n\nFacture en pièce jointe.\n",
                    attachment=(name, data, "pdf"))

    garage = lambda number, job, iban=demo.GARAGE, **kw: demo.invoice_text("Garage Dupont SARL", number, [job], iban, **kw)  # noqa: E731
    job = ("Révision complète camion", 1, "195,00")                     # 234,00 € TTC

    # ---- 1. Le PDF et le XML ne disent pas la même chose (facture électronique hybride)
    fam = "PDF et XML différents"
    fx = lambda number, **kw: cii("Garage Dupont", number, job[0], 1, "195.00", **kw)  # noqa: E731
    add(fam, "facture électronique cohérente (PDF = XML)", "ok", "ok", "supervizor",
        **attach("GD-FX1.pdf", pdf(garage("GD-FX1", job), fx("GD-FX1", iban=demo.GARAGE))))
    add(fam, "compte habituel sur le PDF, compte du fraudeur dans le XML", "refused", "layer_mismatch", "supervizor",
        **attach("GD-FX2.pdf", pdf(garage("GD-FX2", job), fx("GD-FX2", iban=demo.ATTACKER))))
    add(fam, "234 € sur le PDF, 432 € dans le XML", "refused", "layer_mismatch", "supervizor",
        **attach("GD-FX3.pdf", pdf(garage("GD-FX3", job), fx("GD-FX3", iban=demo.GARAGE, payable="432.00"))))
    add(fam, "montant hors taxes à la place du TTC dans le XML", "refused", "layer_mismatch", "supervizor",
        **attach("GD-FX4.pdf", pdf(garage("GD-FX4", job), fx("GD-FX4", iban=demo.GARAGE, payable="195.00"))))
    add(fam, "facture déjà payée renvoyée avec un autre numéro dans le XML", "refused", "layer_mismatch", "doublon",
        **attach("GD-FX1-copie.pdf", pdf(garage("GD-FX1", job), fx("GD-FX9", iban=demo.GARAGE))))
    add(fam, "XML au nom d'une autre société que le PDF", "refused", "layer_mismatch", "supervizor",
        **attach("GD-FX5.pdf", pdf(garage("GD-FX5", job), cii("Garage Dupont Holding Ltd", "GD-FX5", job[0], 1, "195.00", demo.GARAGE))))

    # ---- 2. Vraie facture interceptée, compte bancaire remplacé
    fam = "Vraie facture détournée"
    add(fam, "PDF d'une vraie facture, IBAN remplacé", "refused", "iban_changed", "dafmag",
        **attach("GD-V1.pdf", pdf(garage("GD-V1", job, iban=demo.ATTACKER_FR))))
    add(fam, "avis de changement de compte (banque portugaise), sans facture", "refused", "iban_changed", "justice-pt",
        sender=compta, subject="TR: nouvelles coordonnées bancaires",
        body=demo.forward("GARAGE DUPONT SARL\n\nMadame, Monsieur,\n\nSuite à un audit interne, notre ancien compte n'est plus actif. "
                          f"Merci d'enregistrer notre nouveau RIB pour tous vos règlements :\nIBAN : {demo.spaced(ATTACKER_PT)}\n"
                          "BIC : CGDIPTPL\n\nLa comptabilité\n", "compta@garage-dupont.example"))
    add(fam, "expéditeur à une lettre près d'une adresse autorisée", "ignored", "", "justice-lettre",
        sender="compta@transports-martln.example", subject="Facture à régler", body=garage("GD-V3", job, iban=demo.ATTACKER))
    tricky = garage("GD-V4", job, iban=demo.ATTACKER).replace(demo.spaced(demo.ATTACKER), "-".join(demo.spaced(demo.ATTACKER).split()))
    add(fam, "IBAN du fraudeur écrit avec des tirets, compte habituel caché en texte blanc", "refused", "iban_changed", "lbp",
        sender=compta, subject="TR: facture", body=tricky,
        html=demo.html_invoice(tricky, f"IBAN : {demo.spaced(demo.GARAGE)}"))
    dotted = garage("GD-V5", job, iban=demo.ATTACKER).replace(demo.spaced(demo.ATTACKER), ".".join(demo.spaced(demo.ATTACKER).split()))
    add(fam, "IBAN du fraudeur écrit avec des points pour échapper à la lecture", "refused", "iban_changed", "lbp",
        sender=compta, subject="TR: facture", body=dotted)
    add(fam, "PDF retouché après sa création par un éditeur en ligne (montant gonflé)", "review", "pdf_edited", "pdf",
        **attach("GD-V6.pdf", pdf(garage("GD-V6", ("Révision complète camion", 1, "115,00")), producer="Sage 100 Gestion commerciale",
                                  edited_with="iLovePDF", edited_text=garage("GD-V6", job))))

    # ---- 3. Faux fournisseur
    fam = "Faux fournisseur"
    add(fam, "nom presque identique à un fournisseur connu (Dupond pour Dupont)", "refused", "supplier_lookalike", "lbp",
        sender=compta, subject="TR: facture",
        body=demo.invoice_text("Garage Dupond SARL", "GD-2026-3100", [job], demo.INCONNU))
    scam = ("REGISTRE NATIONAL DES SOCIETES ET ENTREPRISES\nService des inscriptions — avis de paiement\n"
            "TVA intracommunautaire " + demo.vat(demo.make_siren(4777)) + "\n"
            "Facture n° RNS-889213 — 10/10/2026\nDestinataire : Transports Martin\n\n"
            "Inscription au registre et publication de vos données       1 x 289,00\n\n"
            "Total HT : 289,00 €\nTVA 20 % : 57,80 €\nTotal à payer : 346,80 €\n\n"
            "Règlement sous 8 jours pour éviter la radiation.\n"
            f"IBAN : {demo.spaced(ATTACKER_ES)}\n\n"
            "Ce document est une offre commerciale et non une facture.\n")
    add(fam, "faux registre officiel : « inscription », compte à l'étranger", "refused", "known_scam", "dgccrf",
        sender=boss, subject="TR: avis de paiement registre", body=scam)
    add(fam, "société française du carnet, payée sur un compte à l'étranger", "review", "iban_foreign", "hayot",
        sender=compta, subject="TR: facture",
        body=demo.invoice_text("Menuiserie Leroy", "ML-0412", [("Pose de rayonnages", 1, "380,00")], MENUISERIE_LT))

    # ---- 4. Faire payer deux fois, ou passer sous le seuil
    fam = "Doublon et seuil"
    add(fam, "", "ok", "ok", "", setup=True, sender=compta, subject="TR: facture",
        body=demo.forward(demo.invoice_text("Loueur Camions Express", "LCE-5501", [("Location utilitaire (semaine)", 1, "260,00")],
                                            demo.LOUEUR), "facturation@loueur-camions.example"))
    add(fam, "même facture, un zéro remplacé par la lettre O dans le numéro", "refused", "duplicate", "doublon",
        sender=compta, subject="TR: facture",
        body=demo.invoice_text("Loueur Camions Express", "LCE-55O1", [("Location utilitaire (semaine)", 1, "260,00")], demo.LOUEUR))
    add(fam, "même facture, numéro suivi de « -BIS »", "refused", "duplicate", "doublon",
        sender=boss, subject="TR: relance",
        body=demo.invoice_text("Loueur Camions Express", "LCE-5501-BIS", [("Location utilitaire (semaine)", 1, "260,00")], demo.LOUEUR))
    add(fam, "", "ok", "ok", "", setup=True, sender=compta, subject="TR: facture",
        body=demo.invoice_text("Épicerie Pro", "EP-7001", [("Buffet séminaire, première partie", 1, "540,00")], demo.EPICERIE))
    add(fam, "dépense coupée en deux factures pour rester sous le seuil de 1 000 €", "review", "split_threshold", "seuil",
        sender=compta, subject="TR: facture",
        body=demo.invoice_text("Épicerie Pro", "EP-7002", [("Buffet séminaire, seconde partie", 1, "540,00")], demo.EPICERIE))

    # ---- 5. Factures honnêtes qui ressemblent à des cas ci-dessus : elles doivent passer
    fam = "Facture légitime (cas piégeux)"
    add(fam, "PDF sorti d'un logiciel de facturation", "ok", "ok", "",
        **attach("GD-H1.pdf", pdf(garage("GD-H1", ("Contrôle technique", 1, "95,00")))))
    add(fam, "facture électronique dont le PDF écrit les montants à la française", "ok", "ok", "",
        **attach("GD-H2.pdf", pdf(garage("GD-H2", ("Pneus avant", 2, "180,00")), cii("Garage Dupont", "GD-H2", "Pneus avant", 2, "180.00", demo.GARAGE))))
    add(fam, "fournisseur allemand payé sur son compte allemand", "ok", "ok", "",
        sender=compta, subject="TR: Rechnung",
        body=demo.invoice_text("Bauer Logistik GmbH", "BL-20261", [("Transport Cergy-Köln", 1, "400,00")], BAUER_DE,
                               legal="Bauer Logistik GmbH — USt-IdNr. DE811907980\nTVA du client : "
                                     + demo.vat(demo.make_siren(4001))))
    add(fam, "abonnement : même montant que le mois dernier, nouveau numéro", "ok", "ok", "",
        sender=compta, subject="TR: facture",
        body=demo.invoice_text("Loueur Camions Express", "LCE-5502", [("Location utilitaire (semaine)", 1, "260,00")], demo.LOUEUR))
    add(fam, "IBAN habituel écrit avec des tirets", "ok", "ok", "",
        sender=boss, subject="TR: facture",
        body=garage("GD-H5", ("Vidange", 1, "110,00")).replace(demo.spaced(demo.GARAGE), "-".join(demo.spaced(demo.GARAGE).split())))
    add(fam, "deux petites factures le même jour", "ok", "ok", "",
        sender=boss, subject="TR: facture", body=garage("GD-H6", ("Ampoules", 4, "12,00")))
    add(fam, "PDF signé par le fournisseur après sa création (mise à jour sans retouche)", "ok", "ok", "",
        **attach("GD-H7.pdf", pdf(garage("GD-H7", ("Balais d'essuie-glace", 2, "22,00")), edited_with="Sage 100 Gestion commerciale")))
    return out


if __name__ == "__main__":
    import sys
    target = demo.HERE / "boite"
    target.mkdir(exist_ok=True)
    for filename, data in build().items():
        (target / filename).write_bytes(data)
    (demo.HERE / "virements").mkdir(exist_ok=True)
    (demo.HERE / "virements" / "virements-autre-logiciel.xml").write_text(payment_file(), encoding="utf-8", newline="\n")
    print(f"{len(build())} mails écrits dans {target}, 1 fichier de virements dans {demo.HERE / 'virements'}", file=sys.stderr)
