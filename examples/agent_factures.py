"""agent_factures.py — Parcours de A à Z : un agent IA lit des factures et demande à VaultGuard de les payer.

L'agent est volontairement naïf (il obéit à ce qu'il lit, comme un LLM manipulable) : c'est VaultGuard qui décide.

Usage (dashboard lancé) :
    python3 examples/agent_factures.py              toutes les factures de examples/factures/
    python3 examples/agent_factures.py --pause      attend Entrée entre deux factures
    python3 examples/agent_factures.py --only 03    une seule facture (préfixe du nom de fichier)
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sdk.vaultguard_client import VaultGuardClient, VaultGuardError

ADDRESS = r"0x[0-9a-fA-F]{40}"
AMOUNT = r"(\d+(?:\.\d+)?)\s*AVAX"
INJECTION = re.compile(r"ignore[zr]?\s+(?:all\s+)?(?:previous|les)\s+instructions.*", re.I | re.S)
VERDICTS = {"allowed": "PAYÉ", "pending_review": "EN ATTENTE D'UN HUMAIN", "blocked": "BLOQUÉ"}


def local_demo_key() -> str | None:
    """Clé de l'agent de démonstration locale (fichier créé par scripts/seed-demo-local.py)."""
    path = REPO_ROOT / "agent" / "data" / "COMPTES-DEMO.txt"
    if not path.exists():
        return None
    found = re.search(r"vg_live_\S+", path.read_text(encoding="utf-8"))
    return found.group(0) if found else None


def read_invoice(text: str) -> dict:
    """Ce que l'agent « comprend » de la facture. S'il y lit un ordre, il lui obéit."""
    number = re.search(r"Facture n°\s*(\S+)", text)
    memo = "Facture " + (number.group(1) if number else "sans numéro")
    order = INJECTION.search(text)
    if order and re.search(ADDRESS, order.group(0)) and re.search(AMOUNT, order.group(0)):
        return {"to": re.search(ADDRESS, order.group(0)).group(0),
                "amount": re.search(AMOUNT, order.group(0)).group(1),
                "memo": memo, "manipulated": True}
    pay_line = re.search(r"régler à\s*:?\s*(" + ADDRESS + ")", text)
    total = re.search(r"Total à payer\s*:?\s*" + AMOUNT, text)
    if not pay_line or not total:
        raise ValueError("adresse ou montant introuvable dans la facture")
    return {"to": pay_line.group(1), "amount": total.group(1), "memo": memo, "manipulated": False}


def process(client: VaultGuardClient, path: Path, suppliers: dict[str, str], mandate: str) -> str:
    text = path.read_text(encoding="utf-8")
    print("\n" + "=" * 72)
    print(f"FACTURE REÇUE : {path.name}")
    print("-" * 72)
    print(text.strip())
    print("-" * 72)
    try:
        intent = read_invoice(text)
    except ValueError as e:
        print(f"L'agent ne sait pas lire cette facture ({e}) : rien n'est envoyé.")
        return "ignored"
    known = suppliers.get(intent["to"].lower(), "adresse absente du carnet de fournisseurs")
    print(f"1. L'agent veut payer {intent['amount']} AVAX à {intent['to']}")
    print(f"   ({known})")
    if intent["manipulated"]:
        print("   L'agent a obéi à une instruction cachée dans la facture, sans s'en rendre compte.")
    try:
        res = client.pay(to=intent["to"], amount=intent["amount"], memo=intent["memo"],
                         user_request=mandate,
                         documents=[{"source": path.name, "content": text}])
    except VaultGuardError as e:
        print(f"2. VaultGuard a refusé la requête : HTTP {e.status_code} — {e.message}")
        return "error"
    decision = res.get("decision", "?")
    print(f"2. Décision de VaultGuard : {VERDICTS.get(decision, decision)}   (paiement {res.get('id')})")
    for reason in res.get("reasons", []):
        if isinstance(reason, dict):
            ref = f" [{reason['ref']}]" if reason.get("ref") else ""
            print(f"   - {reason.get('title', reason.get('code'))}{ref}")
            if reason.get("detail"):
                print(f"     {reason['detail']}")
        else:
            print(f"   - {reason}")
    print(f"3. Coffre : {res.get('chain', {}).get('status')}")
    if decision == "pending_review":
        print("   -> À toi : ouvre http://localhost:8000/app, onglet Paiements, et clique Approuver ou Rejeter.")
    return decision


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Agent de facturation de démonstration (VaultGuard)")
    parser.add_argument("--api-key", default=os.environ.get("VAULTGUARD_API_KEY"))
    parser.add_argument("--url", default=os.environ.get("VAULTGUARD_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--dossier", default=str(HERE / "factures"), help="dossier des factures (.txt)")
    parser.add_argument("--only", default="", help="ne traiter que les fichiers commençant par ce préfixe")
    parser.add_argument("--pause", action="store_true", help="attendre Entrée entre deux factures")
    parser.add_argument("--consigne", default="Paie les factures de Garage Dupont et de Loueur Camions Express.",
                        help="ce que le dirigeant a demandé à l'agent (le mandat, seule donnée fiable)")
    args = parser.parse_args()

    key = args.api_key or local_demo_key()
    if not key:
        sys.exit("Clé API manquante : --api-key, VAULTGUARD_API_KEY, ou lance scripts/seed-demo-local.py.")
    client = VaultGuardClient(api_key=key, base_url=args.url)
    try:
        policy = client.get_policy()
    except VaultGuardError as e:
        sys.exit(f"VaultGuard injoignable ou clé refusée : HTTP {e.status_code} — {e.message}")
    limits = policy.get("limits", {})
    suppliers = {s["address"].lower(): s["name"] for s in policy.get("active_suppliers", [])}
    print(f"CONSIGNE DU DIRIGEANT À L'AGENT : « {args.consigne} »")
    print("RÈGLES DE L'ENTREPRISE (lues dans VaultGuard)")
    print(f"  plafond par paiement {limits.get('max_tx_avax')} AVAX · par jour {limits.get('max_daily_avax')} AVAX · "
          f"validation humaine dès {limits.get('human_threshold_avax')} AVAX · "
          f"gel après {limits.get('circuit_breaker_limit')} refus/jour")
    for address, name in suppliers.items():
        print(f"  fournisseur autorisé : {name} ({address})")

    files = sorted(p for p in Path(args.dossier).glob("*.txt") if p.name.startswith(args.only))
    if not files:
        sys.exit(f"Aucune facture dans {args.dossier}")
    results: dict[str, str] = {}
    for index, path in enumerate(files):
        if args.pause and index:
            input("\n[Entrée] pour la facture suivante...")
        results[path.name] = process(client, path, suppliers, args.consigne)

    print("\n" + "=" * 72)
    print("BILAN")
    for name, decision in results.items():
        print(f"  {VERDICTS.get(decision, decision):<24} {name}")
    print("Tout est visible dans http://localhost:8000/app (Paiements, Journal d'audit).")


if __name__ == "__main__":
    main()
