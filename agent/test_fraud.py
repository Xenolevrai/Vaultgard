"""Tests : détection de fraude renforcée (PDF contre XML, PDF retouché, faux fournisseur, doublon maquillé,
fractionnement, alerte partagée, contrôle du fichier de virements).

    cd agent && CHAIN=mock python3 -m unittest -q test_fraud
"""
import os
import sqlite3
import sys
import time
import unittest
from pathlib import Path

os.environ["CHAIN"] = "mock"

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "examples"))

import boite_demo as demo
import db
import fraud
import fraudes_reelles as real
import inbox
import orgs
import transfers
from sdk.invoice_reader import read_bytes
from test_inbox import Base, make_org

JOB = ("Révision complète camion", 1, "195,00")


def garage(number, iban=demo.GARAGE, job=JOB):
    return demo.invoice_text("Garage Dupont SARL", number, [job], iban)


class TestHelpers(unittest.TestCase):
    def test_disguised_invoice_numbers(self):
        self.assertTrue(fraud.same_invoice("LCE-55O1", "LCE-5501", False))        # lettre O pour zéro
        self.assertTrue(fraud.same_invoice("lce 5501", "LCE-5501", False))
        self.assertTrue(fraud.same_invoice("LCE-5501-BIS", "LCE-5501", True))
        self.assertFalse(fraud.same_invoice("LCE-5501-BIS", "LCE-5501", False))   # autre montant : autre facture
        self.assertFalse(fraud.same_invoice("LCE-5502", "LCE-5501", True))        # abonnement mensuel
        self.assertFalse(fraud.same_invoice("FAC-100", "FAC-10", True))           # numéro prolongé par un chiffre
        self.assertFalse(fraud.same_invoice("A1", "A1", True))                    # trop court pour conclure

    def test_lookalike_names(self):
        names = ["garage dupont", "loueur camions express", "epicerie pro"]
        self.assertEqual(fraud.lookalike("garage dupond sarl 12 rue des ateliers", names), "garage dupont")
        self.assertEqual(fraud.lookalike("facture loueur carnions express", names), "loueur camions express")
        self.assertEqual(fraud.lookalike("garage dupont sarl", names), "")        # le vrai nom n'est pas un sosie
        self.assertEqual(fraud.lookalike("garage martin et fils", names), "")
        self.assertEqual(fraud.lookalike("nettoyage express 95", names), "")

    def test_fake_registry_invoices(self):
        self.assertTrue(fraud.scam("registre national des societes inscription au registre pour eviter la radiation"))
        self.assertTrue(fraud.scam("annuaire pro insertion ceci est une offre commerciale et non une facture"))
        self.assertFalse(fraud.scam("facture vidange penalites de retard exigibles inscription a la formation"))
        self.assertFalse(fraud.scam("cabinet conseil mise en conformite rgpd, 3 jours"))

    def test_where_an_account_is_held(self):
        self.assertIn("Lituanie", fraud.bank_hint(demo.ATTACKER))
        self.assertIn("Revolut", fraud.bank_hint(demo.ATTACKER))
        self.assertEqual(fraud.bank_hint(demo.GARAGE), "tenu en France")

    def test_iban_written_to_escape_reading(self):
        for separator in ("-", ".", "/", " "):
            text = "IBAN : " + separator.join(demo.spaced(demo.ATTACKER).split())
            self.assertEqual(inbox.find_ibans(text), ([demo.ATTACKER], False), separator)


class TestReader(unittest.TestCase):
    def test_hybrid_invoice_keeps_page_and_xml_apart(self):
        data = real.pdf(garage("GD-1"), real.cii("Garage Dupont", "GD-9", JOB[0], 1, "195.00", demo.ATTACKER, payable="432.00"))
        inv = read_bytes(data, "f.pdf")
        self.assertEqual((inv.fmt, inv.number, inv.total, inv.pay_to), ("facturx", "GD-9", "432", demo.ATTACKER))
        self.assertEqual(inv.seen, {"number": "GD-1", "total": "234", "currency": "EUR"})
        self.assertIn(demo.spaced(demo.GARAGE), inv.shown)
        self.assertNotIn(demo.ATTACKER, inv.shown)

    def test_edited_pdf_shows_the_last_version_and_keeps_the_old_one(self):
        before, after = garage("GD-2", job=("Révision", 1, "115,00")), garage("GD-2")
        inv = read_bytes(real.pdf(before, edited_with="iLovePDF", edited_text=after), "f.pdf")
        self.assertEqual(inv.total, "234")                               # ce qui s'affiche
        self.assertIn("138,00", inv.previous)                            # ce qui était écrit avant
        self.assertEqual(set(inv.traces), {"updated", "other_tool", "editor", "rewritten"})
        signed = read_bytes(real.pdf(after, edited_with="Sage 100 Gestion commerciale"), "f.pdf")
        self.assertEqual((signed.total, signed.traces), ("234", ["updated"]))
        self.assertEqual(read_bytes(real.pdf(after), "f.pdf").traces, [])


class TestRealFrauds(Base):
    def setUp(self):
        super().setUp()
        for name, iban in real.EXTRA_PAYEES:
            inbox.add_payee(self.org_id, self.uid, name, iban, db_path=self.db_path)
        db.execute("UPDATE payees SET active_after = 0 WHERE org_id = ?;", (self.org_id,), db_path=self.db_path)

    def test_documented_frauds_are_stopped_for_the_right_reason(self):
        wrong = []
        for case in real.corpus():
            out = self.send(case["raw"])
            got = "ignored" if out["status"] == "ignored" else out["verdict"]
            codes = self.codes(out) if out["status"] != "ignored" else []
            accepted = {case["expected"]} | ({"refused"} if case["expected"] == "review" else set())
            if got not in accepted or (case["code"] and case["code"] not in codes):
                wrong.append((case["what"] or "préparation", got, codes))
        self.assertEqual(wrong, [])

    def test_live_demo_after_the_first_walkthrough(self):
        for raw in demo.build().values():
            self.send(raw)
        seen = {}
        for name, raw in real.build().items():
            out = self.send(raw)
            seen[name] = out["verdict"] if out["status"] == "checked" else "ignored"
        self.assertEqual(seen, real.EXPECTED)
        out = transfers.audit_file(self.org_id, self.uid, real.payment_file(), db_path=self.db_path)
        self.assertEqual([line["level"] for line in out["lines"]], ["ok", "refused", "ok", "review"])
        self.assertTrue(out["lines"][0]["invoice_checked"])

    def test_every_case_names_its_source(self):
        for case in real.corpus():
            if case["expected"] != "ok":
                self.assertIn(case["source"], real.SOURCES, case["what"])

    def test_nothing_from_the_invoice_is_stored(self):
        secret = "MENTION-CONFIDENTIELLE-QK71"
        text = garage("GD-7").replace("Client :", f"{secret}\nClient :")
        xml = real.cii("Garage Dupont", "GD-7", f"Prestation {secret}", 1, "195.00", demo.ATTACKER)
        out = self.send(demo.mail("s1", demo.SENDERS[0], "f", "Voir pièce jointe.\n", attachment=("f.pdf", real.pdf(text, xml), "pdf")))
        self.assertEqual(out["verdict"], "refused")
        self.assertIn("layer_mismatch", self.codes(out))
        db.close_all()
        con = sqlite3.connect(self.db_path)
        dump = "\n".join(con.iterdump())
        con.close()
        self.assertNotIn(secret, dump)
        self.assertNotIn(demo.ATTACKER, dump)

    def test_small_invoices_do_not_look_like_a_split(self):
        for i in range(4):
            out = self.send(demo.mail(f"p{i}", demo.SENDERS[0], "f", garage(f"GD-P{i}", job=("Petite pièce", 1, "150,00"))))
            self.assertEqual(out["verdict"], "ok", i)                    # 180 € : moins du quart du seuil de 1 000 €


class TestSharedAlert(Base):
    def test_an_account_refused_by_one_company_warns_the_others(self):
        other, _ = make_org(self.db_path, email="owner@autre.local", name="Autre Société", alias="autre-societe")
        other_org = inbox.org_for_alias("autre-societe", db_path=self.db_path)
        stranger = demo.invoice_text("Plomberie Inconnue", "PI-1", [("Dépannage", 1, "200,00")], demo.ATTACKER,
                                     legal="TVA LT123456789")
        first = inbox.judge(other_org, read_bytes(stranger.encode(), "f.txt"), db_path=self.db_path)
        self.assertNotIn("account_reported", [r["code"] for r in first["reasons"]])      # personne ne l'a encore signalé
        out = self.send(demo.mail("a1", demo.SENDERS[0], "f", garage("GD-S1", iban=demo.ATTACKER)))
        self.assertEqual(out["verdict"], "refused")
        again = inbox.judge(other_org, read_bytes(stranger.replace("PI-1", "PI-2").encode(), "f.txt"), db_path=self.db_path)
        self.assertIn("account_reported", [r["code"] for r in again["reasons"]])
        # l'entreprise qui a signalé ne se voit pas elle-même comme « autre entreprise »
        self.assertEqual(inbox.reported_elsewhere(self.org_id, [demo.ATTACKER], db_path=self.db_path), 0)
        rows = db.query_all("SELECT * FROM reported_accounts;", db_path=self.db_path)
        self.assertEqual([(r["org_id"], r["code"]) for r in rows], [(self.org_id, "iban_changed")])
        self.assertNotIn(demo.ATTACKER, rows[0]["iban_sha256"])
        # si elle adopte finalement ce compte, son signalement disparaît
        inbox.add_payee(self.org_id, self.uid, "Nouveau Compte", demo.ATTACKER, db_path=self.db_path)
        self.assertEqual(inbox.reported_elsewhere(other, [demo.ATTACKER], db_path=self.db_path), 0)

    def test_a_refused_duplicate_reports_nobody(self):
        self.send(demo.mail("d1", demo.SENDERS[0], "f", garage("GD-D1")))
        self.assertEqual(self.send(demo.mail("d2", demo.SENDERS[0], "f", garage("GD-D1")))["verdict"], "refused")
        self.assertEqual(db.query_all("SELECT * FROM reported_accounts;", db_path=self.db_path), [])


class TestPaymentFileAudit(Base):
    def file(self, lines):
        batch = {"id": "ext_1", "created_at": int(time.time()), "debtor_name": "Transports Martin",
                 "debtor_iban": demo.COMPANY_IBAN, "total_cents": sum(c for _, _, c, _ in lines)}
        return transfers.build_xml(batch, [{"check_id": f"E{i}", "payee_name": n, "iban": iban, "amount_cents": c, "reference": ref}
                                           for i, (n, iban, c, ref) in enumerate(lines)])

    def audit(self, lines):
        return transfers.audit_file(self.org_id, self.uid, self.file(lines), db_path=self.db_path)

    def test_a_swapped_account_is_caught_whatever_software_wrote_the_file(self):
        out = self.audit([
            ("Garage Dupont", demo.GARAGE, 23400, "GD-1"),
            ("GARAGE DUPONT SARL", demo.ATTACKER, 23400, "GD-2"),              # carnet du logiciel modifié
            ("Garage Dupond", demo.ATTACKER_FR, 9000, "GD-3"),                 # nom presque identique
            ("Plomberie Inconnue", demo.INCONNU, 5000, "PI-1"),
            ("Loueur Camions Express", demo.EPICERIE, 31200, "LCE-1"),         # compte d'un autre fournisseur
            ("Épicerie Pro", demo.EPICERIE, 6400, "EP-1"),
            ("Épicerie Pro", demo.EPICERIE, 6400, "EP-1"),                     # deux fois la même ligne
        ])
        self.assertEqual([line["level"] for line in out["lines"]],
                         ["ok", "refused", "refused", "review", "review", "ok", "review"])
        self.assertEqual((out["verdict"], out["counts"]), ("refused", {"ok": 2, "review": 3, "refused": 2}))
        self.assertIn("Lituanie", out["lines"][1]["why"])
        self.assertNotIn(demo.ATTACKER, str(out))                              # seulement la fin du compte

    def test_a_clean_file_passes_and_leaves_only_a_fingerprint(self):
        out = self.audit([("Garage Dupont", demo.GARAGE, 23400, "GD-1"), ("Épicerie Pro", demo.EPICERIE, 6400, "EP-1")])
        self.assertEqual((out["verdict"], out["total_cents"]), ("ok", 29800))
        db.close_all()
        con = sqlite3.connect(self.db_path)
        last = con.execute("SELECT action, details_json FROM audit ORDER BY id DESC LIMIT 1;").fetchone()
        con.close()
        self.assertEqual(last[0], "transfer.audit")
        self.assertIn(out["file_sha256"], last[1])
        self.assertNotIn("GD-1", last[1])
        self.assertTrue(orgs.verify_audit_chain(db_path=self.db_path)["valid"])

    def test_an_account_reported_elsewhere_is_pointed_out(self):
        make_org(self.db_path, email="owner@autre.local", name="Autre Société", alias="autre-societe")
        inbox.judge(inbox.org_for_alias("autre-societe", db_path=self.db_path),
                    read_bytes(garage("GD-X", iban=demo.ATTACKER).encode(), "f.txt"), db_path=self.db_path)
        line = self.audit([("Société Nouvelle", demo.ATTACKER, 5000, "SN-1")])["lines"][0]
        self.assertEqual(line["level"], "review")           # un signalement seul ne vaut jamais refus
        self.assertIn("autre entreprise", line["why"])

    def test_bad_files_are_refused(self):
        for content in ("", "pas du xml", "<Document/>", '<!DOCTYPE a [<!ENTITY x "y">]><Document/>',
                        "<a>" + "x" * (transfers.MAX_AUDIT_BYTES + 1) + "</a>"):
            with self.assertRaises(orgs.OrgError):
                transfers.audit_file(self.org_id, self.uid, content, db_path=self.db_path)


if __name__ == "__main__":
    unittest.main()
