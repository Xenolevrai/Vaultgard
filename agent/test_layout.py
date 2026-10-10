"""Tests de conformité de la charte graphique et du layout (SPEC-V3-PRODUIT étape 7).

Vérifie :
1. La liste blanche explicite des fichiers statiques dans server.py (protection path traversal).
2. L'absence absolue d'attributs style= et on*= dans toutes les pages HTML (compatibilité CSP nonce).
3. L'absence de classes résiduelles .u-* et la présence des classes sémantiques.
4. L'absence d'emojis et de ressources distantes (Google Fonts, CDN, scripts externes).
5. La présence des règles de non-débordement CSS (overflow-wrap: anywhere, min-width: 0, table-responsive, focus-visible).
"""
import http.client
import os
import re
import sys
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

# Si Python a chargé le dossier agent comme un namespace package au lieu du module agent.py
if "agent" in sys.modules and not hasattr(sys.modules["agent"], "MODE_LABELS"):
    del sys.modules["agent"]

os.environ["AUDIT_PATH"] = os.devnull
os.environ.pop("CHAIN", None)

try:
    import server
except ImportError:
    from agent import server

DASHBOARD_DIR = Path(__file__).resolve().parent.parent / "dashboard"

EMOJI_PATTERN = re.compile(
    "[\U00010000-\U0010ffff"
    "\u2600-\u26ff"
    "\u2700-\u27bf"
    "\u2300-\u23ff"
    "\u2b50-\u2b55"
    "\u200d"
    "\ufe0f"
    "]"
)


class TestLayoutStaticWhitelist(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["HOST"] = "127.0.0.1"
        server.CFG = server.Config()
        server.CFG.local_admin = False
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def _get(self, path: str):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.request("GET", path)
        r = c.getresponse()
        data = r.read()
        headers = {k.lower(): v for k, v in r.getheaders()}
        c.close()
        return r.status, data, headers

    def test_static_assets_whitelist_structure(self):
        """Vérifie que STATIC_ASSETS est un dictionnaire bien configuré pointant vers des fichiers existants."""
        self.assertTrue(hasattr(server, "STATIC_ASSETS"))
        self.assertIsInstance(server.STATIC_ASSETS, dict)

        for route, (filename, content_type, require_admin) in server.STATIC_ASSETS.items():
            self.assertTrue(route.startswith("/"), f"La route {route} doit commencer par /")
            target_path = DASHBOARD_DIR / filename
            self.assertTrue(target_path.is_file(), f"Le fichier {target_path} pour {route} doit exister")
            self.assertTrue(
                content_type.startswith("text/css") or content_type.startswith("application/javascript"),
                f"Type MIME inattendu pour {route}: {content_type}"
            )

    def test_serve_static_whitelisted_assets(self):
        """Les fichiers en liste blanche sont servis avec le bon type MIME."""
        status, data, headers = self._get("/app.css")
        self.assertEqual(status, 200)
        self.assertIn("text/css", headers.get("content-type", ""))
        self.assertIn(b"--font-sans", data)

        status, data, headers = self._get("/app.js")
        self.assertEqual(status, 200)
        self.assertIn("application/javascript", headers.get("content-type", ""))

    def test_admin_js_requires_admin_or_404(self):
        """admin.js ne doit pas être accessible anonymement (doit renvoyer 404 pour stealth)."""
        status, _, _ = self._get("/admin.js")
        self.assertEqual(status, 404)

        status, _, _ = self._get("/dashboard/admin.js")
        self.assertEqual(status, 404)

    def test_path_traversal_and_unknown_static_rejected(self):
        """Aucun chemin arbitraire ni tentative de traversée de répertoire ne doit être servi."""
        probes = [
            "/../server.py",
            "/dashboard/../agent/server.py",
            "/unknown.css",
            "/test.js",
            "/app.css/extra",
            "/secret.txt",
        ]
        for probe in probes:
            status, _, _ = self._get(probe)
            self.assertEqual(status, 404, f"Le chemin {probe} aurait dû renvoyer 404, reçu {status}")


class TestHtmlHygiene(unittest.TestCase):
    def setUp(self):
        self.html_files = list(DASHBOARD_DIR.rglob("*.html"))     # dont dashboard/workspace/index.html
        self.assertGreaterEqual(len(self.html_files), 10, "Moins de 10 fichiers HTML trouvés dans dashboard/")

    def test_no_inline_style_attributes(self):
        """Aucun attribut style= ne doit être présent dans le HTML (bloqué par CSP sans unsafe-inline)."""
        pattern = re.compile(r'\bstyle\s*=', re.IGNORECASE)
        for path in self.html_files:
            content = path.read_text(encoding="utf-8")
            matches = pattern.findall(content)
            self.assertEqual(matches, [], f"Attribut style= trouvé dans {path.name}: {len(matches)} occurrence(s)")

    def test_no_inline_event_handlers(self):
        """Aucun attribut on*= (onclick, onchange...) ne doit être présent (bloqué par CSP)."""
        pattern = re.compile(r'\bon[a-zA-Z]+\s*=', re.IGNORECASE)
        for path in self.html_files:
            content = path.read_text(encoding="utf-8")
            matches = pattern.findall(content)
            self.assertEqual(matches, [], f"Attribut on*= trouvé dans {path.name}: {matches}")

    def test_no_u_classes_in_html(self):
        """Aucune classe .u-1 à .u-43 ne doit subsister dans les fichiers HTML."""
        pattern = re.compile(r'\bu-[0-9]+\b')
        for path in self.html_files:
            content = path.read_text(encoding="utf-8")
            matches = pattern.findall(content)
            self.assertEqual(matches, [], f"Classe utilitaire résiduelle .u-* trouvée dans {path.name}: {matches}")

    def test_no_emojis_in_html(self):
        """Aucun emoji dans les fichiers HTML conformément à la charte §5.7."""
        for path in self.html_files:
            content = path.read_text(encoding="utf-8")
            matches = EMOJI_PATTERN.findall(content)
            self.assertEqual(matches, [], f"Emoji trouvé dans {path.name}: {matches}")

    def test_no_external_resources_in_html(self):
        """Aucun lien externe (fonts, CDN, scripts tiers) dans les balises HTML."""
        pattern = re.compile(r'<(script|link|img)[^>]*(href|src)\s*=\s*["\'](https?://[^"\']+)["\']', re.IGNORECASE)
        for path in self.html_files:
            content = path.read_text(encoding="utf-8")
            matches = pattern.findall(content)
            self.assertEqual(matches, [], f"Ressource externe trouvée dans {path.name}: {matches}")


class TestCssTypographyAndOverflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.css_path = DASHBOARD_DIR / "app.css"
        if not cls.css_path.is_file():  # cls.assertTrue(...) ne vérifierait rien : méthode d'instance
            raise AssertionError("dashboard/app.css est introuvable")
        cls.css = cls.css_path.read_text(encoding="utf-8")

    def test_no_u_classes_in_css(self):
        """Aucune définition de classe .u-1 à .u-43 dans app.css."""
        pattern = re.compile(r'\.u-[0-9]+\b')
        matches = pattern.findall(self.css)
        self.assertEqual(matches, [], f"Classes résiduelles .u-* trouvées dans app.css: {matches}")

    def test_overflow_wrap_on_address_classes(self):
        """Les adresses, hashes et clés doivent avoir overflow-wrap: anywhere et word-break."""
        self.assertIn("overflow-wrap: anywhere", self.css)
        self.assertIn("word-break: break-word", self.css)
        # Vérification des sélecteurs d'adresses et hashes
        self.assertTrue(
            bool(re.search(r'\.(mono|addr|hash|key|break-all)[^{]*{[^}]*overflow-wrap:\s*anywhere', self.css)),
            "overflow-wrap: anywhere doit être appliqué aux sélecteurs d'adresses / hashes"
        )

    def test_responsive_and_accessibility_rules(self):
        """Vérifie la présence des règles critiques : min-width: 0, table-responsive, focus-visible, @media."""
        self.assertIn("min-width: 0", self.css)
        self.assertIn(".table-responsive", self.css)
        self.assertIn("overflow-x: auto", self.css)
        self.assertIn(":focus-visible", self.css)
        self.assertIn("@media (max-width: 768px)", self.css)

    def test_design_system_variables(self):
        """Vérifie que les variables CSS obligatoires de la charte §5.7 sont définies."""
        required_vars = [
            "--font-sans",
            "--font-mono",
            "--bg",
            "--ink",
            "--accent",
            "--border",
        ]
        for var in required_vars:
            self.assertIn(var, self.css, f"Variable CSS {var} manquante dans app.css")

    def test_is_hidden_can_be_overridden_by_js(self):
        """Revue de l'étape 7 : `.is-hidden { display: none !important }` empêchait le JS (el.style.display = 'block')
        d'afficher le champ 2FA de /login, les erreurs et la fenêtre de dégel. La règle ne doit pas être !important."""
        import re
        rules = re.findall(r"[^{}]*\.is-hidden\b[^{}]*\{([^}]*)\}", self.css)
        self.assertTrue(rules, ".is-hidden doit être défini dans app.css")
        for body in rules:
            self.assertNotIn("!important", body)


if __name__ == "__main__":
    unittest.main()
