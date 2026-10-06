"""Tests de sécurité de l'API (serveur réel sur un port local) : python3 -m unittest test_server -v

Chaque test correspond à une faille trouvée lors de l'audit de la v1 (docs/SECURITE.md) et prouve qu'elle est corrigée.
"""
import http.client
import json
import os
import threading
import unittest
from http.server import ThreadingHTTPServer

os.environ["AUDIT_PATH"] = os.devnull
os.environ.pop("CHAIN", None)

import server  # noqa: E402


class Client:
    def __init__(self, port, host_header="localhost"):
        self.port, self.host, self.cookie, self.csrf = port, host_header, "", ""

    def req(self, method, path, body=None, headers=None, raw=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Host": self.host, **({"Cookie": self.cookie} if self.cookie else {})}
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        if body is not None and raw is None:
            h.update({"Content-Type": "application/json", "X-CSRF-Token": self.csrf})
        h.update(headers or {})
        c.request(method, path, body=data, headers=h)
        r = c.getresponse()
        payload = r.read()
        sc = r.getheader("Set-Cookie")
        if sc and sc.startswith("vg_sid="):
            self.cookie = sc.split(";")[0]
        c.close()
        try:
            return r.status, json.loads(payload), r
        except ValueError:
            return r.status, payload, r

    def login(self):
        _, d, _ = self.req("GET", "/api/session")
        self.csrf = d["csrf"]
        return d


class ServerSecurity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["ADMIN_PASSWORD_HASH"] = server.hash_password("correct horse battery staple")
        os.environ["HOST"] = "127.0.0.1"
        server.CFG = server.Config()
        server.CFG.local_admin = False  # on teste le mode production (mot de passe)
        server.LIMITER.LIMITS = dict(server.LIMITER.LIMITS)
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        server.LIMITER._b.clear()
        self.c = Client(self.port)
        self.c.login()

    def test_dashboard_security_headers(self):
        st, body, r = self.c.req("GET", "/")
        self.assertEqual(st, 200)
        csp = r.getheader("Content-Security-Policy")
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertIn("script-src 'nonce-", csp)
        self.assertNotIn(b"__NONCE__", body)
        self.assertEqual(r.getheader("X-Frame-Options"), "DENY")
        self.assertEqual(r.getheader("X-Content-Type-Options"), "nosniff")
        self.assertNotIn("Python", r.getheader("Server"))

    def test_session_cookie_flags(self):
        c = Client(self.port)
        _, _, r = c.req("GET", "/api/session")
        sc = r.getheader("Set-Cookie")
        self.assertIn("HttpOnly", sc)
        self.assertIn("SameSite=Strict", sc)

    def test_dns_rebinding_host_rejected(self):
        c = Client(self.port, host_header="evil.example")
        self.assertEqual(c.req("GET", "/api/state")[0], 421)

    def test_csrf_token_required(self):
        st, _, _ = self.c.req("POST", "/api/run", {"scenario": "legit", "mode": "full"},
                              headers={"X-CSRF-Token": "faux"})
        self.assertEqual(st, 403)

    def test_cross_origin_rejected(self):
        st, _, _ = self.c.req("POST", "/api/run", {"scenario": "legit", "mode": "full"},
                              headers={"Origin": "https://evil.example"})
        self.assertEqual(st, 403)

    def test_simple_form_content_type_rejected(self):
        st, _, _ = self.c.req("POST", "/api/run", raw=b'{"scenario":"legit","mode":"full"}',
                              headers={"Content-Type": "text/plain", "X-CSRF-Token": self.c.csrf})
        self.assertEqual(st, 415)

    def test_body_size_limits(self):
        st, _, _ = self.c.req("POST", "/api/run", raw=b"{}", headers={
            "Content-Type": "application/json", "X-CSRF-Token": self.c.csrf, "Content-Length": "99999999999"})
        self.assertEqual(st, 413)

    def test_invalid_json_no_leak(self):
        st, d, _ = self.c.req("POST", "/api/run", raw=b"xx", headers={
            "Content-Type": "application/json", "X-CSRF-Token": self.c.csrf})
        self.assertEqual(st, 400)
        self.assertNotIn("JSONDecodeError", json.dumps(d))

    def test_input_validation(self):
        self.c.req("POST", "/api/run", {"scenario": "big", "mode": "full"})
        for bad in [-1, True, "0", 1.5, 2**70, None]:
            st, _, _ = self.c.req("POST", "/api/approve", {"id": bad})
            self.assertEqual(st, 400, bad)
        self.assertEqual(self.c.req("POST", "/api/run", {"scenario": "../etc", "mode": "full"})[0], 400)
        self.assertEqual(self.c.req("POST", "/api/run", {"scenario": "legit", "mode": "god"})[0], 400)
        self.assertEqual(self.c.req("POST", "/api/pause", {"paused": "yes"})[0], 400)

    def test_live_and_llm_require_admin(self):
        self.assertEqual(self.c.req("GET", "/api/state?target=live")[0], 403)
        self.assertEqual(self.c.req("POST", "/api/pause", {"paused": True, "target": "live"})[0], 403)
        self.assertEqual(self.c.req("POST", "/api/run", {"scenario": "legit", "mode": "full", "llm": True})[0], 403)

    def test_login_flow_and_session_rotation(self):
        old = self.c.cookie
        self.assertEqual(self.c.req("POST", "/api/login", {"password": "mauvais"})[0], 401)
        st, d, _ = self.c.req("POST", "/api/login", {"password": "correct horse battery staple"})
        self.assertEqual(st, 200)
        self.assertNotEqual(self.c.cookie, old)  # anti fixation de session
        self.c.csrf = d["csrf"]
        self.assertEqual(self.c.req("GET", "/api/state?target=live")[0], 200)

    def test_login_bruteforce_limited(self):
        codes = [self.c.req("POST", "/api/login", {"password": f"x{i}"})[0] for i in range(8)]
        self.assertIn(429, codes)

    def test_sandboxes_are_isolated(self):
        other = Client(self.port); other.login()
        self.c.req("POST", "/api/run", {"scenario": "canary", "mode": "contract"})
        self.assertTrue(self.c.req("GET", "/api/state")[1]["paused"])
        self.assertFalse(other.req("GET", "/api/state")[1]["paused"])

    def test_csv_formula_injection_neutralized(self):
        self.assertEqual(server.csv_cell("=HYPERLINK(\"http://x\")"), "'=HYPERLINK(\"http://x\")")
        self.assertEqual(server.csv_cell("Facture"), "Facture")

    def test_audit_report_hash_stable(self):
        a = server.audit_report({"events": [{"x": 1}], "network": "n"})
        self.assertEqual(len(a["sha256"]), 64)

    def test_methods_and_404(self):
        self.assertEqual(self.c.req("DELETE", "/api/state")[0], 405)
        self.assertEqual(self.c.req("GET", "/../../etc/passwd")[0], 404)
        self.assertEqual(self.c.req("GET", "/healthz")[0], 200)

    def test_password_hashing(self):
        h = server.hash_password("abc")
        self.assertTrue(server.verify_password("abc", h))
        self.assertFalse(server.verify_password("abd", h))
        self.assertFalse(server.verify_password("abc", "garbage"))


if __name__ == "__main__":
    unittest.main()
