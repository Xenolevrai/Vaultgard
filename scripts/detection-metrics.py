"""Mesure la détection de la boîte de dépôt des factures sur le jeu d'essai étiqueté (examples/boite_demo.py).

Usage (depuis agent/) : python3 ../scripts/detection-metrics.py            affiche le tableau
                        python3 ../scripts/detection-metrics.py --write    met aussi à jour docs/METRIQUES.md
Base temporaire, rien n'est envoyé nulle part. Le jeu d'essai est fabriqué par nous : ces chiffres montrent que
chaque famille de fraude prévue est arrêtée, pas ce que donnerait un trafic réel.
"""
import os
import shutil
import statistics
import sys
import tempfile
import time
from pathlib import Path

os.environ["CHAIN"] = "mock"
os.environ["AUDIT_PATH"] = os.devnull
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "agent"))
sys.path.insert(0, str(ROOT / "examples"))
TMP = tempfile.mkdtemp(prefix="vg_metrics_")
os.environ["DB_PATH"] = os.path.join(TMP, "metrics.db")
os.environ.pop("INBOUND_ADDRESS", None)

import auth  # noqa: E402
import boite_demo as demo  # noqa: E402
import db  # noqa: E402
import inbox  # noqa: E402
import mail_agent  # noqa: E402

LABELS = {"ok": "bon à payer", "stop": "arrêtée (humain ou refus)", "ignored": "écarté sans être lu"}


def run() -> tuple[list[dict], list[float]]:
    db.init_db()
    r = auth.signup("mesure@demo.local", "Mesure-Demo-2026-ok!", org_name="Transports Martin")
    org_id, uid = r["org"]["id"], r["user"]["id"]
    inbox.ensure_inbox(org_id, alias=demo.ALIAS)
    for sender in demo.SENDERS:
        inbox.add_sender(org_id, uid, sender)
    for name, iban in demo.PAYEES:
        inbox.add_payee(org_id, uid, name, iban)
    db.execute("UPDATE payees SET active_after = 0;")
    settings = mail_agent.Settings(authserv_id=demo.AUTHSERV)
    rows, timings = [], []
    for family, what, expected, raw in demo.corpus():
        start = time.perf_counter()
        out = mail_agent.process_message(raw, settings)
        timings.append((time.perf_counter() - start) * 1000)
        got = "ignored" if out["status"] == "ignored" else ("ok" if out["verdict"] == "ok" else "stop")
        detail = out.get("verdict") or out.get("reason")
        rows.append({"family": family, "what": what, "expected": expected, "got": got, "detail": detail})
    return rows, timings


def report(rows: list[dict], timings: list[float]) -> str:
    attacks = [r for r in rows if r["expected"] != "ok"]
    honest = [r for r in rows if r["expected"] == "ok"]
    missed = [r for r in attacks if r["got"] == "ok"]
    alarms = [r for r in honest if r["got"] != "ok"]
    refused = sum(1 for r in attacks if r["detail"] == "refused")
    review = sum(1 for r in attacks if r["detail"] == "review")
    unread = sum(1 for r in attacks if r["got"] == "ignored")
    lines = [
        "# Chiffres de détection — boîte de dépôt des factures",
        "",
        f"Mesure du {time.strftime('%d/%m/%Y')}, reproductible : `cd agent && python3 ../scripts/detection-metrics.py`.",
        f"Jeu d'essai : **{len(rows)} mails** fabriqués par nous (`examples/boite_demo.py`), "
        f"{len(attacks)} à arrêter et {len(honest)} factures honnêtes.",
        "",
        "| Mesure | Résultat |",
        "|---|---|",
        f"| Fraudes et anomalies arrêtées | **{len(attacks) - len(missed)} sur {len(attacks)}** ({100 * (len(attacks) - len(missed)) // len(attacks)} %) |",
        f"| — dont mails écartés sans être lus (expéditeur non autorisé ou imité) | {unread} |",
        f"| — dont factures refusées | {refused} |",
        f"| — dont factures envoyées à une personne | {review} |",
        f"| Fraudes passées en « bon à payer » | **{len(missed)}** |",
        f"| Factures honnêtes passées sans déranger personne | **{len(honest) - len(alarms)} sur {len(honest)}** |",
        f"| Fausses alertes | **{len(alarms)}** |",
        f"| Temps de contrôle d'un mail | médiane {statistics.median(timings):.0f} ms, maximum {max(timings):.0f} ms |",
        "",
        "## Par famille",
        "",
        "| Famille | Cas | Résultat attendu | Obtenu |",
        "|---|---|---|---|",
    ]
    families: dict[str, list[dict]] = {}
    for r in rows:
        families.setdefault(r["family"], []).append(r)
    for family, items in families.items():
        good = sum(1 for r in items if r["got"] == r["expected"])
        lines.append(f"| {family} | {len(items)} | {LABELS[items[0]['expected']]} | {good} sur {len(items)} |")
    lines += ["", "## Détail des cas", "", "| Famille | Cas | Obtenu |", "|---|---|---|"]
    for r in rows:
        mark = "" if r["got"] == r["expected"] else " **(inattendu)**"
        lines.append(f"| {r['family']} | {r['what']} | {LABELS[r['got']]}{mark} |")
    lines += [
        "",
        "## Ce que ces chiffres ne disent pas",
        "",
        "- Le jeu d'essai est le nôtre : il prouve que chaque famille de fraude prévue est arrêtée et qu'une facture",
        "  ordinaire passe. Il ne mesure pas un trafic réel ; un taux de fausses alertes en conditions réelles reste à",
        "  mesurer chez un premier client.",
        "- Les mêmes cas sont rejoués à chaque modification du code (`agent/test_inbox.py`, classe `TestDetectionCorpus`) :",
        "  une fraude qui passerait ferait échouer les tests.",
        "- Non couvert aujourd'hui : facture scannée (image) sans texte, qui part toujours vers une personne ; fraude",
        "  où le vrai fournisseur est complice ; compte de messagerie d'un employé autorisé réellement piraté (limité par",
        "  le contrôle de l'IBAN, le seuil et le délai de sécurité, mais pas empêché).",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        text = report(*run())
    finally:
        db.close_all()
        shutil.rmtree(TMP, ignore_errors=True)
    print(text)
    if "--write" in sys.argv:
        (ROOT / "docs" / "METRIQUES.md").write_text(text, encoding="utf-8", newline="\n")
