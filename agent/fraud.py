"""fraud.py — Contrôles propres à la fraude à la facture, au-delà de « l'IBAN est-il dans le carnet ? ».

Chaque fonction répond à un mode opératoire documenté (docs/DETECTION-FRAUDE.md) et ne fait que du calcul :
aucune base, aucun réseau. inbox.judge décide du verdict.
    layers        la page du PDF et le XML embarqué disent-ils la même chose ? (facture électronique hybride)
    lookalike     ce nom ressemble-t-il, à une lettre près, à un fournisseur du carnet ?
    scam          fausse facture d'annuaire ou de registre « officiel »
    same_invoice  même facture qu'une autre, numéro maquillé (O pour 0, suffixe -BIS)
    bank_hint     où est tenu ce compte, en clair
"""
from __future__ import annotations

import difflib
import re
from decimal import Decimal, InvalidOperation

COUNTRIES = {
    "FR": "en France", "MC": "à Monaco", "DE": "en Allemagne", "ES": "en Espagne", "PT": "au Portugal", "IT": "en Italie",
    "BE": "en Belgique", "NL": "aux Pays-Bas", "LU": "au Luxembourg", "LT": "en Lituanie", "LV": "en Lettonie",
    "EE": "en Estonie", "PL": "en Pologne", "RO": "en Roumanie", "BG": "en Bulgarie", "HU": "en Hongrie",
    "CZ": "en Tchéquie", "IE": "en Irlande", "GB": "au Royaume-Uni", "CH": "en Suisse", "MT": "à Malte",
    "CY": "à Chypre", "GR": "en Grèce", "AT": "en Autriche", "TR": "en Turquie", "AE": "aux Émirats arabes unis",
}

# Établissements où un compte s'ouvre en ligne en quelques minutes : préfixe du numéro de compte -> nom.
# Ce n'est pas un signe de fraude (beaucoup d'entreprises honnêtes y sont) ; c'est une précision donnée à la
# personne qui doit trancher quand le compte est déjà inconnu ou différent de l'habituel.
ONLINE_BANKS = {
    "FR": {"16958": "Qonto", "28233": "Revolut", "16598": "Nickel", "16798": "Treezor (Shine et autres)", "17598": "Swan"},
    "LT": {"32500": "Revolut", "35000": "Paysera"},
    "DE": {"10011001": "N26"},
    "BE": {"967": "Wise"},
    "NL": {"BUNQ": "bunq"},
}


def country_of(iban: str) -> str:
    return COUNTRIES.get(iban[:2], f"à l'étranger ({iban[:2]})")


def bank_hint(iban: str) -> str:
    """« tenu en Lituanie, dans une banque en ligne (Revolut) » — pour l'explication donnée à l'utilisateur."""
    bban = iban[4:]
    bank = next((name for prefix, name in ONLINE_BANKS.get(iban[:2], {}).items() if bban.startswith(prefix)), "")
    return f"tenu {country_of(iban)}" + (f", dans une banque en ligne ({bank}) où un compte s'ouvre en quelques minutes" if bank else "")


# ------------------------------------------------------------------ Numéros de facture

def canonical(number: str) -> str:
    """Numéro tel qu'un œil pressé le lit : sans ponctuation, O = 0, I et L = 1."""
    return re.sub(r"[^A-Z0-9]", "", str(number).upper()).translate(str.maketrans("OIL", "011"))


def same_invoice(number: str, other: str, same_amount: bool) -> bool:
    """Deux numéros différents désignent-ils la même facture ? Égaux une fois « lus à l'œil », ou, à montant égal,
    l'un est l'autre suivi d'un court suffixe (-BIS, -2, A...)."""
    a, b = canonical(number), canonical(other)
    if len(a) < 4 or len(b) < 4:
        return False
    if a == b:
        return True
    short, long = sorted((a, b), key=len)
    tail = long[len(short):]
    # Un suffixe qui commence par un chiffre prolonge un numéro (FAC-10 / FAC-100) : ce n'est pas un doublon.
    return same_amount and long.startswith(short) and len(tail) <= 4 and not tail[0].isdigit()


# ------------------------------------------------------------------ Nom du vendeur

def lookalike(header: str, names: list[str]) -> str:
    """Nom du carnet auquel l'en-tête de la facture ressemble sans être identique (Dupond / Dupont, rn / m).
    `header` et `names` sont déjà en minuscules sans accents. Renvoie "" si aucun."""
    words = re.findall(r"[a-z0-9]+", header)[:80]
    for name in names:
        parts = re.findall(r"[a-z0-9]+", name)
        target = " ".join(parts)
        if len(target) < 6:
            continue
        for i in range(len(words) - len(parts) + 1):
            window = " ".join(words[i:i + len(parts)])
            if window == target or abs(len(window) - len(target)) > 2 or window[0] != target[0]:
                continue
            if difflib.SequenceMatcher(None, window, target).ratio() >= 0.86:
                return name
    return ""


# ------------------------------------------------------------------ Fausses factures d'annuaire ou de registre

_SCAM = {
    "official": r"registre (national|europ[ée]en|central|du commerce|des soci[ée]t[ée]s|des entreprises)|institut national|"
                r"office (europ[ée]en|national)|\binpi\b|\beuipo\b|greffe|bulletin officiel|journal officiel|"
                r"mise en conformit[ée]|\brgpd\b|accessibilit[ée] des [ée]tablissements",
    "listing": r"inscription|insertion|r[ée]f[ée]rencement|publication de vos donn[ée]es|annuaire|renouvellement de (la |votre )?marque|"
               r"enregistrement de (la |votre )?marque",
    # « pénalités de retard » est une mention obligatoire des vraies factures : elle n'y figure pas.
    "threat": r"radiation|suppression de votre|sous peine|[ée]viter (la|une|toute)|dernier (avis|rappel)|mise en demeure",
    "disclaimer": r"offre commerciale|n'est pas une facture|non une facture|proposition (commerciale|de contrat)|"
                  r"sans (aucun )?caract[èe]re obligatoire|facultati(f|ve)",
}


def scam(text: str) -> bool:
    """Fausse facture d'annuaire ou de registre « officiel » (pratique signalée par la DGCCRF) ? Texte en minuscules.
    Il faut deux familles d'indices, dont le faux air officiel ou la petite mention « ceci est une offre »."""
    hits = {name for name, pattern in _SCAM.items() if re.search(pattern, text)}
    return len(hits) >= 2 and bool(hits & {"official", "disclaimer"})


# ------------------------------------------------------------------ PDF et XML d'une même facture

def _amount(value: str) -> Decimal | None:
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None


def layers(invoice, xml_iban: str, page_ibans: list[str], page_plain: str, supplier_plain: str) -> list[str]:
    """Différences entre le XML (lu par les logiciels) et la page (lue par l'humain) d'une facture hybride.
    Renvoie la liste, en clair, de ce qui diffère ; vide si tout concorde ou si la facture n'est pas hybride."""
    seen = getattr(invoice, "seen", None) or {}
    if not getattr(invoice, "shown", ""):
        return []
    out = []
    if xml_iban and page_ibans and xml_iban not in page_ibans:
        out.append("le compte bancaire")
    a, b = _amount(invoice.total), _amount(seen.get("total", ""))
    if a is not None and b is not None and (a != b or (seen.get("currency") or invoice.currency) != invoice.currency):
        out.append("le montant à payer")
    if invoice.number and seen.get("number") and canonical(invoice.number) != canonical(seen["number"]):
        out.append("le numéro de facture")
    if len(supplier_plain) >= 3 and supplier_plain not in page_plain:
        out.append("le nom du vendeur")
    return out
