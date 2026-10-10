"""Tests : boîte de dépôt des factures (adresse par entreprise, expéditeurs de confiance, verdict en euros).

    cd agent && python3 -m unittest -q test_inbox
"""
import http.client
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from email.message import EmailMessage
from pathlib import Path

os.environ["CHAIN"] = "mock"            # avant tout import : agent/.env ne doit pas brancher les tests sur Fuji

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "examples"))

import auth
import boite_demo as demo
import db
import inbox
import mail_agent
import orgs

SETTINGS = mail_agent.Settings(authserv_id=demo.AUTHSERV)
PASSWORD = "PassphraseSecure123!"


def clean_env():
    """agent/.env (rechargé par `import server`) peut configurer une vraie boîte : les tests n'en veulent pas."""
    for key in [k for k in os.environ if k.startswith("INBOUND_")] + ["PUBLIC_URL"]:
        os.environ.pop(key, None)


def make_org(db_path, email="owner@martin.local", name="Transports Martin", alias=demo.ALIAS, delay_passed=True):
    r = auth.signup(email, PASSWORD, org_name=name, db_path=db_path)
    org_id, uid = r["org"]["id"], r["user"]["id"]
    inbox.ensure_inbox(org_id, db_path=db_path, alias=alias)
    for sender in demo.SENDERS:
        inbox.add_sender(org_id, uid, sender, db_path=db_path)
    for payee, iban in demo.PAYEES:
        inbox.add_payee(org_id, uid, payee, iban, db_path=db_path)
    if delay_passed:
        db.execute("UPDATE payees SET active_after = ? WHERE org_id = ?;", (int(time.time()) - 60, org_id), db_path=db_path)
    return org_id, uid


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="vg_inbox_test_")
        self.db_path = os.path.join(self.tmp, "test.db")
        self.old_env = {k: os.environ.get(k) for k in ("DB_PATH", "INBOUND_ADDRESS")}
        os.environ["DB_PATH"] = self.db_path
        clean_env()
        db.init_db(self.db_path)
        self.org_id, self.uid = make_org(self.db_path)

    def tearDown(self):
        db.close_all()
        for key, value in self.old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        shutil.rmtree(self.tmp, ignore_errors=True)

    def send(self, raw):
        return mail_agent.process_message(raw, SETTINGS, db_path=self.db_path)

    def codes(self, result):
        return [r["code"] for r in result["reasons"]]


class TestIban(unittest.TestCase):
    def test_checksum_and_length(self):
        self.assertTrue(inbox.iban_valid(demo.GARAGE))
        self.assertTrue(inbox.iban_valid("GB82WEST12345698765432"))          # exemple du registre SWIFT
        self.assertTrue(inbox.iban_valid("DE89370400440532013000"))
        self.assertFalse(inbox.iban_valid(demo.GARAGE[:-1] + "0"))
        self.assertFalse(inbox.iban_valid("DE8937040044053201300"))           # un caractère en moins
        self.assertFalse(inbox.iban_valid("ZZ89370400440532013000"))          # pays inconnu

    def test_found_in_text_whatever_the_spacing(self):
        text = f"IBAN : {demo.spaced(demo.GARAGE)}\nBIC : DEMOFRPP\nautre {demo.LOUEUR.lower()} fin"
        self.assertEqual(inbox.find_ibans(text), ([demo.GARAGE, demo.LOUEUR], False))
        self.assertEqual(inbox.find_ibans("TVA FR40123456789, facture FR2026-10, SIRET 123 456 789 00012"), ([], False))
        self.assertEqual(inbox.find_ibans("IBAN : FR76 3000 6000 0112 3456 7890 180"), ([], True))

    def test_human_input_is_cleaned(self):
        self.assertEqual(inbox.clean_iban(" " + demo.spaced(demo.GARAGE).lower() + " "), demo.GARAGE)
        with self.assertRaises(orgs.OrgError):
            inbox.clean_iban("FR76 1234")


class TestSenderProof(unittest.TestCase):
    def headers(self, *results, sender="compta@transports-martin.example"):
        msg = EmailMessage()
        for value in results:
            msg["Authentication-Results"] = value
        msg["From"] = sender
        return msg

    def ok(self, *results, sender="compta@transports-martin.example", server="mx.vg.example"):
        return mail_agent.authenticated(self.headers(*results, sender=sender), sender, server)

    def test_pass_must_be_for_the_sender_domain(self):
        self.assertTrue(self.ok("mx.vg.example; dmarc=pass (p=REJECT) header.from=transports-martin.example"))
        self.assertTrue(self.ok("mx.vg.example; dkim=pass header.i=@transports-martin.example header.s=k1"))
        self.assertTrue(self.ok("mx.vg.example; spf=pass (ok) smtp.mailfrom=bounce@mail.transports-martin.example"))
        self.assertFalse(self.ok("mx.vg.example; dkim=pass header.d=attaquant.example; spf=pass smtp.mailfrom=x@attaquant.example"))
        self.assertFalse(self.ok("mx.vg.example; dkim=fail header.d=transports-martin.example; spf=softfail"))
        self.assertFalse(self.ok("mx.vg.example; dkim=pass header.d=example"))       # un suffixe public n'aligne rien
        self.assertFalse(self.ok())

    def test_only_our_server_and_only_its_topmost_header_count(self):
        good = "dmarc=pass header.from=transports-martin.example"
        self.assertFalse(self.ok("mx.attaquant.example; " + good))
        self.assertFalse(self.ok("mx.vg.example; dmarc=fail header.from=transports-martin.example", "mx.vg.example; " + good))
        self.assertFalse(self.ok("mx.vg.example; dmarc=fail (dmarc=pass header.from=transports-martin.example)"))


class TestMailbox(Base):
    def test_demo_walkthrough(self):
        seen = {}
        for name, raw in demo.build().items():
            out = self.send(raw)
            seen[name] = out["verdict"] if out["status"] == "checked" else "ignored"
        self.assertEqual(seen, demo.EXPECTED)
        checks = {c["invoice_number"]: c for c in inbox.list_checks(self.org_id, db_path=self.db_path)}
        self.assertEqual(len(checks), 6)                 # 08 porte le même numéro que 01 ; 06 et 07 n'ont jamais été lus
        self.assertEqual((checks["LCE-7781"]["amount_cents"], checks["LCE-7781"]["payee_name"]), (240000, "Loueur Camions Express"))
        self.assertEqual(checks["EP-3310"]["amount_cents"], 12600)
        self.assertEqual(checks["GD-2026-2002"]["reasons"][0]["code"], "iban_changed")
        self.assertIn(demo.GARAGE[-4:], checks["GD-2026-2002"]["reasons"][0]["detail"])
        self.assertIn("injection", [r["code"] for r in checks["GD-2026-2003"]["reasons"]])
        box = inbox.get_inbox(self.org_id, db_path=self.db_path)
        self.assertEqual(box["ignored_7d"], {"sender": 1, "auth": 1})
        self.assertEqual(box["address"], demo.ADDRESS)

    def test_untrusted_mail_is_never_opened(self):
        raw = demo.build()["06-expediteur-inconnu.eml"]
        calls = []
        original = mail_agent.read_bytes
        mail_agent.read_bytes = lambda *a, **k: calls.append(a) or original(*a, **k)
        try:
            self.assertEqual(self.send(raw), {"status": "ignored", "reason": "sender"})
            self.assertEqual(self.send(demo.build()["07-expediteur-imite.eml"]), {"status": "ignored", "reason": "auth"})
        finally:
            mail_agent.read_bytes = original
        self.assertEqual(calls, [])
        self.assertEqual(inbox.list_checks(self.org_id, db_path=self.db_path), [])

    def test_sender_tricks(self):
        fake = demo.invoice_text("Garage Dupont SARL", "X-1", [("Divers", 1, "10,00")], demo.GARAGE)
        compta = demo.SENDERS[0]
        cases = {
            "two From addresses": demo.mail("t1", compta, "f", fake).replace(b"From: " + compta.encode(), b"From: x@evil.example, " + compta.encode()),
            "display name": demo.mail("t2", "x@evil.example", "f", fake, display=compta),
            "auto reply": demo.mail("t3", compta, "f", fake).replace(b"Subject:", b"Auto-Submitted: auto-replied\nSubject:"),
            "unknown alias": demo.mail("t4", compta, "f", fake, to="factures+nexiste-pas-abc123@demo.vaultguard.local"),
            "no alias": demo.mail("t5", compta, "f", fake, to="quelquun@demo.vaultguard.local"),
        }
        for label, raw in cases.items():
            self.assertEqual(self.send(raw)["status"], "ignored", label)
        self.assertEqual(self.send(b"\xff\xfe\x00 pas un mail")["status"], "ignored")
        self.assertEqual(self.send(b"x" * 11_000_000), {"status": "ignored", "reason": "size"})

    def test_one_company_cannot_use_another_company_address(self):
        other_org, _ = make_org(self.db_path, email="owner@beta.local", name="Beta", alias="beta-societe")
        db.execute("DELETE FROM inbox_senders WHERE org_id = ?;", (other_org,), db_path=self.db_path)
        raw = demo.mail("iso", demo.SENDERS[0], "f", demo.invoice_text("Garage Dupont SARL", "ISO-1", [("Divers", 1, "10,00")], demo.GARAGE),
                        to="factures+beta-societe@demo.vaultguard.local")
        self.assertEqual(self.send(raw), {"status": "ignored", "reason": "sender"})
        self.assertEqual(inbox.list_checks(other_org, db_path=self.db_path), [])
        self.assertEqual(inbox.list_checks(self.org_id, db_path=self.db_path), [])

    def test_no_invoice_text_reaches_the_database(self):
        secret = "REMISE-CONFIDENTIELLE-ZX42"
        text = demo.invoice_text("Garage Dupont SARL", "GD-9", [(f"Prestation {secret}", 1, "100,00")], demo.ATTACKER,
                                 note=f"Note interne {secret}")
        out = self.send(demo.mail("z1", demo.SENDERS[0], f"Objet {secret}", text))
        self.assertEqual(out["verdict"], "refused")
        db.close_all()
        con = sqlite3.connect(self.db_path)
        dump = "\n".join(con.iterdump())
        con.close()
        self.assertNotIn(secret, dump)
        self.assertNotIn(demo.ATTACKER, dump)             # l'IBAN inconnu : seulement sa fin et son empreinte
        self.assertIn(demo.ATTACKER[-4:], dump)

    def test_new_supplier_and_unusual_amount_need_a_human(self):
        db.execute("UPDATE payees SET active_after = ? WHERE org_id = ? AND iban = ?;",
                   (int(time.time()) + 3600, self.org_id, demo.EPICERIE), db_path=self.db_path)
        out = self.send(demo.mail("n1", demo.SENDERS[0], "f", demo.invoice_text("Épicerie Pro", "EP-1", [("Café", 1, "50,00")], demo.EPICERIE)))
        self.assertEqual((out["verdict"], self.codes(out)), ("review", ["payee_recent"]))
        for i in range(3):
            out = self.send(demo.mail(f"h{i}", demo.SENDERS[0], "f",
                                      demo.invoice_text("Garage Dupont SARL", f"GD-H{i}", [("Vidange", 1, "100,00")], demo.GARAGE)))
            self.assertEqual(out["verdict"], "ok")
        out = self.send(demo.mail("h9", demo.SENDERS[0], "f",
                                  demo.invoice_text("Garage Dupont SARL", "GD-H9", [("Moteur", 1, "700,00")], demo.GARAGE)))
        self.assertEqual((out["verdict"], self.codes(out)), ("review", ["amount_anomaly"]))

    def test_logo_does_not_block_and_two_invoices_do(self):
        text = demo.invoice_text("Garage Dupont SARL", "GD-L1", [("Vidange", 1, "100,00")], demo.GARAGE)
        msg = EmailMessage()
        msg["Authentication-Results"] = demo.auth_header(demo.SENDERS[0])
        msg["From"], msg["To"], msg["Subject"] = demo.SENDERS[0], demo.ADDRESS, "f"
        msg.set_content(text)
        msg.add_attachment(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64, maintype="image", subtype="png", filename="logo.png")
        self.assertEqual(self.send(msg.as_bytes())["verdict"], "ok")
        for n in ("A", "B"):
            msg.add_attachment(demo.ubl("Garage Dupont", f"GD-M{n}", "Pneu", 1, "50.00", demo.GARAGE),
                               maintype="application", subtype="xml", filename=f"{n}.xml")
        out = self.send(msg.as_bytes())
        self.assertEqual(out["verdict"], "review")
        self.assertIn("several_invoices", self.codes(out))

    def test_human_decides_once_and_it_is_chained(self):
        out = self.send(demo.build()["02-montant-eleve.eml"])
        done = inbox.review_check(self.org_id, self.uid, out["id"], approve=True, db_path=self.db_path)
        self.assertEqual((done["verdict"], done["review_action"]), ("ok", "approved"))
        self.assertEqual([p["action"] for p in done["proof"]], ["invoice.check", "invoice.approve"])
        with self.assertRaises(orgs.OrgError) as ctx:
            inbox.review_check(self.org_id, self.uid, out["id"], approve=False, db_path=self.db_path)
        self.assertEqual(ctx.exception.code, 409)
        with self.assertRaises(orgs.OrgError) as ctx:
            inbox.review_check("org_autre", self.uid, out["id"], approve=True, db_path=self.db_path)
        self.assertIn(ctx.exception.code, (403, 404))
        self.assertTrue(orgs.verify_audit_chain(db_path=self.db_path)["valid"])

    def test_flood_is_bounded(self):
        raw = demo.build()["06-expediteur-inconnu.eml"]
        for _ in range(inbox.MAX_IGNORED_LOGGED_PER_HOUR + 15):
            self.send(raw)
        row = db.query_one("SELECT COUNT(*) AS c FROM audit WHERE action = 'inbox.ignored';", db_path=self.db_path)
        self.assertEqual(row["c"], inbox.MAX_IGNORED_LOGGED_PER_HOUR)
        old = inbox.MAX_CHECKS_PER_HOUR
        inbox.MAX_CHECKS_PER_HOUR = 2
        try:
            results = [self.send(demo.mail(f"f{i}", demo.SENDERS[0], "f", demo.invoice_text(
                "Garage Dupont SARL", f"GD-F{i}", [("Vidange", 1, "100,00")], demo.GARAGE)))["status"] for i in range(4)]
        finally:
            inbox.MAX_CHECKS_PER_HOUR = old
        self.assertEqual(results, ["checked", "checked", "ignored", "ignored"])

    def test_reply_quotes_nothing_from_the_mail(self):
        raw = demo.build()["04-instructions-cachees.eml"]
        org = inbox.org_for_alias(demo.ALIAS, db_path=self.db_path)
        result = self.send(raw)
        msg = mail_agent.build_reply(raw, demo.SENDERS[0], org, result, mail_agent.Settings(public_url="https://vg.example"))
        body = msg.get_content()
        self.assertIn("REFUSÉE", msg["Subject"])
        self.assertEqual(msg["Auto-Submitted"], "auto-replied")
        self.assertEqual(msg["In-Reply-To"], "<04@demo.example>")
        self.assertNotIn("ignore previous", body)
        self.assertNotIn(demo.ATTACKER[:12], body.replace(" ", ""))
        evil = raw.replace(b"<04@demo.example>", b"<a@b>\r\n Bcc: victime@x.example")
        self.assertNotIn("Bcc", str(mail_agent.build_reply(evil, demo.SENDERS[0], org, result, SETTINGS)))

    def test_demo_folder_is_emptied(self):
        folder = Path(self.tmp) / "boite-entrante"
        folder.mkdir()
        for name in ("01-facture-normale.eml", "06-expediteur-inconnu.eml"):
            path = folder / name
            path.write_bytes(demo.build()[name])
            os.utime(path, (time.time() - 5, time.time() - 5))
        settings = mail_agent.Settings(authserv_id=demo.AUTHSERV, drop_dir=folder)
        self.assertEqual(mail_agent.poll_folder(settings, db_path=self.db_path), 2)
        self.assertEqual(list(folder.iterdir()), [])
        self.assertEqual(len(inbox.list_checks(self.org_id, db_path=self.db_path)), 1)

    def test_settings(self):
        local = mail_agent.Settings.from_env(local=True)
        self.assertTrue(local.enabled and local.drop_dir and local.authserv_id == demo.AUTHSERV)
        self.assertFalse(mail_agent.Settings.from_env(local=False).enabled)       # en ligne : pas de dossier de démo
        os.environ["INBOUND_ADDRESS"] = "vg.factures+{alias}@gmail.com"
        try:
            self.assertEqual(inbox.address_for("abc-123"), "vg.factures+abc-123@gmail.com")
            self.assertEqual(inbox.aliases_in(["VG.Factures+ABC-123@gmail.com", "vg.factures@gmail.com", "x+abc-123@gmail.com"]), ["abc-123"])
        finally:
            os.environ.pop("INBOUND_ADDRESS")

    def test_inputs_are_validated(self):
        for bad in ("pas-un-mail", "a@b", "x@y.fr\nBcc: z@z.fr", "<a@b.fr>", ""):
            with self.assertRaises(orgs.OrgError, msg=bad):
                inbox.add_sender(self.org_id, self.uid, bad, db_path=self.db_path)
        with self.assertRaises(orgs.OrgError) as ctx:
            inbox.add_sender(self.org_id, self.uid, demo.SENDERS[0].upper(), db_path=self.db_path)
        self.assertEqual(ctx.exception.code, 409)
        # Un doublon refusé ne doit pas laisser la base verrouillée pour les autres requêtes (autres fils).
        errors = []

        def other_request():
            try:
                inbox.add_sender(self.org_id, self.uid, "autre@transports-martin.example", db_path=self.db_path)
            except Exception as e:  # noqa: BLE001
                errors.append(e)
            finally:
                db.close_all()
        worker = threading.Thread(target=other_request)
        worker.start()
        worker.join(20)
        self.assertEqual(errors, [])
        with self.assertRaises(orgs.OrgError):
            inbox.add_payee(self.org_id, self.uid, "X", demo.INCONNU, db_path=self.db_path)
        with self.assertRaises(orgs.OrgError) as ctx:
            inbox.add_payee(self.org_id, self.uid, "Doublon", demo.GARAGE, db_path=self.db_path)
        self.assertEqual(ctx.exception.code, 409)
        for bad in (-1, 1.5, "100", True, None, 10**15):
            with self.assertRaises(orgs.OrgError, msg=repr(bad)):
                inbox.set_threshold(self.org_id, self.uid, bad, db_path=self.db_path)
        added = inbox.add_payee(self.org_id, self.uid, "Nouveau", demo.INCONNU, db_path=self.db_path)
        self.assertGreater(added["active_after"], time.time() + 3600)             # délai d'activation de l'organisation
        alias = inbox.ensure_inbox(make_org(self.db_path, "o@gamma.local", "Gamma & Fils", alias=None)[0], db_path=self.db_path)["alias"]
        self.assertRegex(alias, r"^gamma-fils-[a-z0-9]{6}$")


class TestDetectionCorpus(Base):
    def test_no_attack_is_paid_and_no_honest_invoice_is_stopped(self):
        missed, false_alarms = [], []
        for family, what, expected, raw in demo.corpus():
            out = self.send(raw)
            got = "ignored" if out["status"] == "ignored" else ("ok" if out["verdict"] == "ok" else "stop")
            if expected != "ok" and got == "ok":
                missed.append((family, what))
            elif got != expected:
                false_alarms.append((family, what, got))
        self.assertEqual(missed, [])
        self.assertEqual(false_alarms, [])


class TestInboxHTTP(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import server
        cls.server = server
        cls.tmp = tempfile.mkdtemp(prefix="vg_inbox_http_")
        cls.db_path = os.path.join(cls.tmp, "test.db")
        cls.old_env = os.environ.get("DB_PATH")
        os.environ["DB_PATH"] = cls.db_path
        clean_env()
        db.init_db(cls.db_path)
        server.CFG = server.Config()
        server.CFG.local_admin = False
        cls.srv = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        db.close_all()
        if cls.old_env is None:
            os.environ.pop("DB_PATH", None)
        else:
            os.environ["DB_PATH"] = cls.old_env
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def req(self, method, path, body=None, cookie="", csrf=""):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Host": "localhost"}
        if cookie:
            h["Cookie"] = cookie
        if csrf:
            h["X-CSRF-Token"] = csrf
        data = None
        if body is not None:
            h["Content-Type"] = "application/json"
            data = json.dumps(body).encode()
        c.request(method, path, body=data, headers=h)
        r = c.getresponse()
        payload = r.read()
        sc = r.getheader("Set-Cookie")
        c.close()
        try:
            parsed = json.loads(payload)
        except ValueError:
            parsed = payload
        return r.status, parsed, (sc.split(";")[0] if sc else cookie)

    def account(self, email, org_name=None, invite=None):
        _, data, cookie = self.req("GET", "/api/session")
        body = {"email": email, "password": PASSWORD}
        body.update({"org_name": org_name} if org_name else {"invite_token": invite})
        status, data, cookie = self.req("POST", "/api/auth/signup", body, cookie=cookie, csrf=data["csrf"])
        self.assertEqual(status, 201, data)
        return cookie, data["csrf"]

    def test_roles_csrf_and_isolation(self):
        self.server.LIMITER._b.clear()
        owner, owner_csrf = self.account("owner@alpha.local", org_name="Alpha Transports")
        status, invite, _ = self.req("POST", "/api/app/team/invites", {"email": "viewer@alpha.local", "role": "viewer"},
                                     cookie=owner, csrf=owner_csrf)
        self.assertEqual(status, 201)
        viewer, viewer_csrf = self.account("viewer@alpha.local", invite=invite["token"])
        other, other_csrf = self.account("owner@beta.local", org_name="Beta Logistique")

        self.assertEqual(self.req("GET", "/api/app/inbox")[0], 401)
        status, box, _ = self.req("GET", "/api/app/inbox", cookie=owner)
        self.assertEqual(status, 200)
        self.assertRegex(box["address"], r"^factures\+alpha-transports-[a-z0-9]{6}@demo\.vaultguard\.local$")
        self.assertEqual((box["senders"], box["payees"], box["checks"]), ([], [], []))

        sender = {"email": "compta@alpha.example"}
        self.assertEqual(self.req("POST", "/api/app/inbox/senders", sender, cookie=owner)[0], 403)              # sans CSRF
        self.assertEqual(self.req("POST", "/api/app/inbox/senders", sender, cookie=viewer, csrf=viewer_csrf)[0], 403)
        status, added, _ = self.req("POST", "/api/app/inbox/senders", sender, cookie=owner, csrf=owner_csrf)
        self.assertEqual(status, 201)
        self.assertEqual(self.req("POST", "/api/app/payees", {"name": "Garage", "iban": "FR76 0000"}, cookie=owner, csrf=owner_csrf)[0], 400)
        status, payee, _ = self.req("POST", "/api/app/payees", {"name": "Garage Dupont", "iban": demo.spaced(demo.GARAGE)},
                                    cookie=owner, csrf=owner_csrf)
        self.assertEqual((status, payee["iban"]), (201, demo.GARAGE))
        self.assertEqual(self.req("POST", "/api/app/inbox/threshold", {"cents": 50000}, cookie=owner, csrf=owner_csrf)[0], 200)
        self.assertEqual(self.req("POST", "/api/app/inbox/threshold", {"cents": "50000"}, cookie=owner, csrf=owner_csrf)[0], 400)

        # Une facture arrive : au-dessus du seuil de 500 €, elle attend une décision.
        alias = box["address"].split("+")[1].split("@")[0]
        db.execute("UPDATE payees SET active_after = 0;", db_path=self.db_path)
        raw = demo.mail("h1", "compta@alpha.example", "f", demo.invoice_text("Garage Dupont SARL", "GD-77", [("Boîte de vitesses", 1, "900,00")], demo.GARAGE),
                        to=f"factures+{alias}@demo.vaultguard.local")
        out = mail_agent.process_message(raw, SETTINGS, db_path=self.db_path)
        self.assertEqual((out["status"], out["verdict"]), ("checked", "review"))
        decide = {"id": out["id"]}
        self.assertEqual(self.req("POST", "/api/app/inbox/checks/approve", decide, cookie=viewer, csrf=viewer_csrf)[0], 403)
        self.assertEqual(self.req("POST", "/api/app/inbox/checks/approve", decide, cookie=other, csrf=other_csrf)[0], 404)
        self.assertEqual(self.req("GET", "/api/app/inbox", cookie=other)[1]["checks"], [])
        status, done, _ = self.req("POST", "/api/app/inbox/checks/approve", decide, cookie=owner, csrf=owner_csrf)
        self.assertEqual((status, done["verdict"], done["amount_cents"]), (200, "ok", 108000))
        self.assertEqual(self.req("POST", "/api/app/inbox/checks/reject", decide, cookie=owner, csrf=owner_csrf)[0], 409)

        # Les identifiants d'une autre entreprise ne donnent rien (404, pas 403).
        for path, body in (("/api/app/inbox/senders/remove", {"id": added["id"]}), ("/api/app/payees/remove", {"id": payee["id"]})):
            self.assertEqual(self.req("POST", path, body, cookie=other, csrf=other_csrf)[0], 404, path)
            self.assertEqual(self.req("POST", path, body, cookie=owner, csrf=owner_csrf)[0], 200, path)
        self.assertEqual(self.req("POST", "/api/app/inbox/nimporte", {}, cookie=owner, csrf=owner_csrf)[0], 404)


if __name__ == "__main__":
    unittest.main()
