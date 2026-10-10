"""Mesure la détection de la boîte de dépôt des factures sur deux jeux d'essai étiquetés :
  - examples/boite_demo.py       les familles de base (45 mails) ;
  - examples/fraudes_reelles.py  les modes opératoires réels documentés, plus difficiles (sources citées).

Usage (depuis agent/) : python3 ../scripts/detection-metrics.py            affiche le tableau
                        python3 ../scripts/detection-metrics.py --write    met aussi à jour docs/METRIQUES.md
Base temporaire, rien n'est envoyé nulle part. Les jeux d'essai sont fabriqués par nous à partir de cas publiés :
ces chiffres montrent que chaque mode opératoire prévu est arrêté, pas ce que donnerait un trafic réel.
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
os.environ.pop("INBOUND_ADDRESS", None)

import auth  # noqa: E402
import boite_demo as demo  # noqa: E402
import db  # noqa: E402
import fraudes_reelles as real  # noqa: E402
import inbox  # noqa: E402
import mail_agent  # noqa: E402

LABELS = {"ok": "bon à payer", "stop": "arrêtée (humain ou refus)", "ignored": "écarté sans être lu",
          "review": "envoyée à une personne", "refused": "refusée"}
# Même jeu d'essai, passé sur le code d'avant le renforcement (commit 1c08384 et suivants, mesuré le 10/10/2026 dans
# une copie de travail du dernier commit) : voir docs/DETECTION-FRAUDE.md.
BEFORE = {"missed": 7, "frauds": 17, "false_alarms": 2, "honest": 8}


def run(cases: list[dict], extra_payees: list[tuple[str, str]], name: str) -> tuple[list[dict], list[float]]:
    path = os.path.join(TMP, name + ".db")
    os.environ["DB_PATH"] = path
    db.init_db(path)
    r = auth.signup("mesure@demo.local", "Mesure-Demo-2026-ok!", org_name="Transports Martin", db_path=path)
    org_id, uid = r["org"]["id"], r["user"]["id"]
    inbox.ensure_inbox(org_id, alias=demo.ALIAS, db_path=path)
    for sender in demo.SENDERS:
        inbox.add_sender(org_id, uid, sender, db_path=path)
    for payee, iban in demo.PAYEES + extra_payees:
        inbox.add_payee(org_id, uid, payee, iban, db_path=path)
    db.execute("UPDATE payees SET active_after = 0;", db_path=path)
    settings = mail_agent.Settings(authserv_id=demo.AUTHSERV)
    rows, timings = [], []
    for case in cases:
        start = time.perf_counter()
        out = mail_agent.process_message(case["raw"], settings, db_path=path)
        elapsed = (time.perf_counter() - start) * 1000
        if case.get("setup"):
            continue
        timings.append(elapsed)
        got = "ignored" if out["status"] == "ignored" else out["verdict"]
        codes = [r["code"] for r in out.get("reasons", [])]
        rows.append({**case, "got": got, "codes": codes})
    db.close_all()
    return rows, timings


def paid(row: dict) -> bool:
    return row["got"] == "ok"


def good(row: dict) -> bool:
    """Le résultat est-il celui attendu ? « stop » et « review » acceptent un refus (plus sévère)."""
    want, got = row["expected"], row["got"]
    return got == want or (want == "stop" and got in ("review", "refused")) or (want == "review" and got == "refused")


def families(rows: list[dict]) -> list[str]:
    out = ["| Famille | Cas | Obtenu comme attendu |", "|---|---|---|"]
    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(r["family"], []).append(r)
    for family, items in groups.items():
        out.append(f"| {family} | {len(items)} | {sum(map(good, items))} sur {len(items)} |")
    return out


def report(base: list[dict], base_t: list[float], hard: list[dict], hard_t: list[float]) -> str:
    rows, timings = base + hard, base_t + hard_t
    attacks = [r for r in rows if r["expected"] != "ok"]
    honest = [r for r in rows if r["expected"] == "ok"]
    missed = [r for r in attacks if paid(r)]
    alarms = [r for r in honest if not paid(r)]
    hard_attacks = [r for r in hard if r["expected"] != "ok"]
    hard_honest = [r for r in hard if r["expected"] == "ok"]
    hard_missed = [r for r in hard_attacks if paid(r)]
    hard_alarms = [r for r in hard_honest if not paid(r)]
    explained = [r for r in hard_attacks if r["code"] and r["code"] in r["codes"]]
    with_code = [r for r in hard_attacks if r["code"]]
    lines = [
        "# Chiffres de détection — boîte de dépôt des factures",
        "",
        f"Mesure du {time.strftime('%d/%m/%Y')}, reproductible : `cd agent && python3 ../scripts/detection-metrics.py`.",
        f"**{len(rows)} mails** : {len(attacks)} fraudes ou anomalies à arrêter, {len(honest)} factures honnêtes.",
        "",
        "| Mesure | Résultat |",
        "|---|---|",
        f"| Fraudes et anomalies arrêtées | **{len(attacks) - len(missed)} sur {len(attacks)}** |",
        f"| Fraudes passées en « bon à payer » | **{len(missed)}** |",
        f"| Factures honnêtes passées sans déranger personne | **{len(honest) - len(alarms)} sur {len(honest)}** |",
        f"| Fausses alertes | **{len(alarms)}** |",
        f"| Temps de contrôle d'un mail | médiane {statistics.median(timings):.0f} ms, maximum {max(timings):.0f} ms |",
        "",
        "## Jeu d'essai 2 — modes opératoires réels (le plus difficile)",
        "",
        f"`examples/fraudes_reelles.py` : {len(hard)} mails qui reproduisent des fraudes décrites par des tribunaux, des",
        "banques, la DGCCRF et des cabinets d'audit (sources dans `docs/DETECTION-FRAUDE.md`), plus 8 factures",
        "honnêtes qui leur ressemblent. La plupart de ces fraudes ne se voient pas en regardant la facture.",
        "",
        "| Mesure | Avant (notre version précédente) | Maintenant |",
        "|---|---|---|",
        f"| Fraudes payées sans alerte | {BEFORE['missed']} sur {BEFORE['frauds']} | **{len(hard_missed)} sur {len(hard_attacks)}** |",
        f"| Fausses alertes sur les factures honnêtes piégeuses | {BEFORE['false_alarms']} sur {BEFORE['honest']} | **{len(hard_alarms)} sur {len(hard_honest)}** |",
        f"| Fraudes arrêtées avec la bonne explication | — | **{len(explained)} sur {len(with_code)}** |",
        "",
        *families(hard),
        "",
        "| Famille | Cas | Attendu | Obtenu | Raison donnée |",
        "|---|---|---|---|---|",
    ]
    for r in hard:
        mark = "" if good(r) else " **(inattendu)**"
        why = inbox.CATALOG[r["code"]][1] if r["code"] in r["codes"] and r["code"] != "ok" else ""
        lines.append(f"| {r['family']} | {r['what']} | {LABELS[r['expected']]} | {LABELS[r['got']]}{mark} | {why} |")
    lines += ["", "## Jeu d'essai 1 — familles de base", "", f"`examples/boite_demo.py` : {len(base)} mails.", "", *families(base),
              "", "| Famille | Cas | Obtenu |", "|---|---|---|"]
    for r in base:
        mark = "" if good(r) else " **(inattendu)**"
        lines.append(f"| {r['family']} | {r['what']} | {LABELS[r['got']]}{mark} |")
    lines += [
        "",
        "## Ce que ces chiffres ne disent pas",
        "",
        "- Il n'existe pas de base publique de vraies factures frauduleuses : les victimes ne les publient pas. Les cas",
        "  sont donc fabriqués par nous, à partir de modes opératoires publiés. Ils prouvent que chaque mode opératoire",
        "  prévu est arrêté et qu'une facture ordinaire passe ; ils ne mesurent pas un trafic réel. Le taux de fausses",
        "  alertes en conditions réelles reste à mesurer chez un premier client.",
        "- Les mêmes cas sont rejoués à chaque modification du code (`agent/test_inbox.py` et `agent/test_fraud.py`) :",
        "  une fraude qui passerait ferait échouer les tests.",
        "- Non couvert : facture scannée (image) sans texte, qui part toujours vers une personne ; fraude où le vrai",
        "  fournisseur est complice ; faux fournisseur entièrement nouveau et crédible (il part vers une personne, qui",
        "  peut se tromper) ; compte de messagerie d'un employé autorisé piraté (limité par le carnet d'IBAN, le seuil",
        "  et le délai de sécurité, pas empêché).",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    try:
        base_cases = [{"family": f, "what": w, "expected": e, "code": "", "raw": raw} for f, w, e, raw in demo.corpus()]
        base = run(base_cases, [], "base")
        hard = run(real.corpus(), real.EXTRA_PAYEES, "reel")
        text = report(*base, *hard)
    finally:
        db.close_all()
        shutil.rmtree(TMP, ignore_errors=True)
    print(text)
    if "--write" in sys.argv:
        (ROOT / "docs" / "METRIQUES.md").write_text(text, encoding="utf-8", newline="\n")
