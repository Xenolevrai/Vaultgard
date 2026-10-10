"""registry.py — L'entreprise qui facture existe-t-elle ? Numéros légaux et annuaire public de l'État.

Hors ligne (toujours) : validité d'un SIREN (clé de Luhn) et cohérence du numéro de TVA français avec ce SIREN.
En ligne (si REGISTRY_CHECK=1) : l'API publique « Recherche d'entreprises » (recherche-entreprises.api.gouv.fr,
gratuite, sans clé) dit si le SIREN existe, si l'entreprise est en activité et sous quel nom.
Seul le SIREN, un identifiant public, est envoyé : jamais la facture.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.error
import urllib.request

API = "https://recherche-entreprises.api.gouv.fr/search?per_page=1&q="
CACHE_SECONDS = 6 * 3600
_cache: dict[str, tuple[float, dict | None]] = {}
_lock = threading.Lock()

_VAT = re.compile(r"(?<![A-Z0-9])FR[ ]?([0-9A-Z]{2})[ ]?(\d{3})[ ]?(\d{3})[ ]?(\d{3})(?![0-9])")
_LABELLED = re.compile(r"SIRET[^0-9A-Z]{0,8}((?:\d[ . ]?){13}\d)|SIRE[NT][^0-9A-Z]{0,8}((?:\d[ . ]?){8}\d)(?![ . ]?\d)")
_XML_ID = re.compile(r"<[^<>]*(?:COMPANYID|GLOBALID)[^<>]*>\s*(\d{9}|\d{14})\s*<")


def luhn(digits: str) -> bool:
    total = 0
    for i, c in enumerate(reversed(digits)):
        n = int(c) * (2 if i % 2 else 1)
        total += n - 9 if n > 9 else n
    return total % 10 == 0


def siren_valid(siren: str) -> bool:
    return bool(re.fullmatch(r"\d{9}", siren)) and siren != "000000000" and luhn(siren)


def vat_key(siren: str) -> str:
    """Clé du numéro de TVA intracommunautaire français : FR + clé + SIREN."""
    return f"{(12 + 3 * (int(siren) % 97)) % 97:02d}"


def find_ids(text: str) -> tuple[list[str], bool]:
    """(SIREN valides cités dans le document ; True si un numéro annoncé est faux : clé invalide ou TVA incohérente)."""
    upper = text.upper()
    found: list[str] = []
    wrong = False

    def add(siren: str) -> None:
        if siren not in found:
            found.append(siren)

    for m in _VAT.finditer(upper):
        key, siren = m.group(1), m.group(2) + m.group(3) + m.group(4)
        if not siren_valid(siren) or (key.isdigit() and key != vat_key(siren)):
            wrong = True
        else:
            add(siren)
    for m in list(_LABELLED.finditer(upper)) + list(_XML_ID.finditer(upper)):
        digits = re.sub(r"\D", "", next(g for g in m.groups() if g))
        if len(digits) in (9, 14) and siren_valid(digits[:9]) and (len(digits) == 9 or luhn(digits)):
            add(digits[:9])
        else:
            wrong = True
    return found, wrong


def enabled() -> bool:
    return os.environ.get("REGISTRY_CHECK", "").strip().lower() in {"1", "true", "yes", "oui"}


def lookup(siren: str, timeout: float = 4.0) -> dict | None:
    """{"found", "active", "names"} d'après l'annuaire public, ou None si l'annuaire ne répond pas.
    Une panne de l'annuaire ne doit ni bloquer ni valider une facture : l'appelant ignore None."""
    if not siren_valid(siren):
        return {"found": False, "active": False, "names": []}
    now = time.time()
    with _lock:
        hit = _cache.get(siren)
        if hit and now - hit[0] < CACHE_SECONDS:
            return hit[1]
    try:
        req = urllib.request.Request(API + siren, headers={"Accept": "application/json", "User-Agent": "VaultGuard/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310
            data = json.loads(resp.read(200_000).decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None
    result = {"found": False, "active": False, "names": []}
    for row in data.get("results", []) if isinstance(data, dict) else []:
        if isinstance(row, dict) and row.get("siren") == siren:
            names = [str(row.get(k)) for k in ("nom_complet", "nom_raison_sociale", "sigle") if row.get(k)]
            result = {"found": True, "active": row.get("etat_administratif") == "A", "names": names}
    with _lock:
        if len(_cache) > 2000:
            _cache.clear()
        _cache[siren] = (now, result)
    return result
