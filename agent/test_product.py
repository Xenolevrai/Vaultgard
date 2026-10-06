"""test_product.py — Tests de l'étape 1 (persistance SQLite) de VaultGuard v3.

Vérifications :
  - Création du schéma et présence des 10 tables requises
  - Idempotence de l'initialisation (relances multiples)
  - Contraintes d'unicité (emails, slugs, clés, adresses, adhésions)
  - Clés étrangères actives et intégrité référentielle (cascade & refus)
  - Rôles stricts (owner, admin, approver, viewer)
  - Protection contre les injections SQL via requêtes paramétrées avec '?'
  - Hachage sécurisé des secrets (scrypt pour mots de passe, SHA-256 pour jetons)
  - Gestion des transactions (atomicité et rollback)
  - Une connexion par thread (threading.local)
  - Création automatique du répertoire cible de la base
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import threading
import time
import unittest

try:
    import db
except ImportError:
    from agent import db


class TestSQLitePersistence(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="vg_test_")
        self.db_path = os.path.join(self.tmp_dir, "test.db")
        db.init_db(self.db_path)

    def tearDown(self):
        db.close_all()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_schema_tables_and_columns(self):
        """Vérifie la création des 10 tables et de leurs colonnes principales."""
        expected_tables = {
            "users",
            "orgs",
            "members",
            "invites",
            "sessions",
            "api_keys",
            "suppliers",
            "payments",
            "audit",
            "login_events",
        }
        rows = db.query_all(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';",
            db_path=self.db_path,
        )
        found_tables = {r["name"] for r in rows}
        self.assertTrue(expected_tables.issubset(found_tables), f"Tables manquantes : {expected_tables - found_tables}")

        # Vérification colonnes users
        user_cols = {r["name"] for r in db.query_all("PRAGMA table_info(users);", db_path=self.db_path)}
        for col in ["id", "email", "password_hash", "is_superadmin", "is_active", "totp_secret", "totp_enabled", "failed_login_attempts", "locked_until"]:
            self.assertIn(col, user_cols)

        # Vérification colonnes orgs
        org_cols = {r["name"] for r in db.query_all("PRAGMA table_info(orgs);", db_path=self.db_path)}
        for col in ["id", "name", "slug", "network", "vault_address", "canary_address", "is_suspended", "max_tx_gwei", "max_daily_gwei", "human_threshold_gwei", "activation_delay", "circuit_breaker_limit"]:
            self.assertIn(col, org_cols)

        # Vérification colonnes members
        member_cols = {r["name"] for r in db.query_all("PRAGMA table_info(members);", db_path=self.db_path)}
        for col in ["id", "org_id", "user_id", "role"]:
            self.assertIn(col, member_cols)

        # Vérification colonnes audit
        audit_cols = {r["name"] for r in db.query_all("PRAGMA table_info(audit);", db_path=self.db_path)}
        for col in ["id", "org_id", "user_id", "api_key_id", "action", "details_json", "prev_hash", "entry_hash"]:
            self.assertIn(col, audit_cols)

    def test_schema_idempotence(self):
        """Vérifie que réexécuter init_db() ne lève aucune erreur et préserve les données."""
        now = int(time.time())
        db.execute(
            "INSERT INTO users (id, email, password_hash, created_at, updated_at) VALUES (?, ?, ?, ?, ?);",
            ("u1", "alice@example.com", db.hash_password("secret1234567"), now, now),
            db_path=self.db_path,
        )

        # Re-exécute l'initialisation du schéma à plusieurs reprises
        db.init_db(self.db_path)
        db.init_db(self.db_path)

        user = db.query_one("SELECT * FROM users WHERE id = ?;", ("u1",), db_path=self.db_path)
        self.assertIsNotNone(user)
        self.assertEqual(user["email"], "alice@example.com")

    def test_uniqueness_constraints(self):
        """Vérifie le respect des contraintes d'unicité."""
        now = int(time.time())
        pwd = db.hash_password("PassphraseValide123!")
        db.execute(
            "INSERT INTO users (id, email, password_hash, created_at, updated_at) VALUES (?, ?, ?, ?, ?);",
            ("u1", "alice@example.com", pwd, now, now),
            db_path=self.db_path,
        )

        # Doublon d'email (sensible et insensible à la casse grâce à COLLATE NOCASE)
        with self.assertRaises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO users (id, email, password_hash, created_at, updated_at) VALUES (?, ?, ?, ?, ?);",
                ("u2", "alice@example.com", pwd, now, now),
                db_path=self.db_path,
            )
        with self.assertRaises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO users (id, email, password_hash, created_at, updated_at) VALUES (?, ?, ?, ?, ?);",
                ("u3", "ALICE@EXAMPLE.COM", pwd, now, now),
                db_path=self.db_path,
            )

        # Organisation & adhésion unique (org_id, user_id)
        db.execute(
            "INSERT INTO orgs (id, name, slug, created_at, updated_at) VALUES (?, ?, ?, ?, ?);",
            ("o1", "Acme Corp", "acme", now, now),
            db_path=self.db_path,
        )
        db.execute(
            "INSERT INTO members (id, org_id, user_id, role, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?);",
            ("m1", "o1", "u1", "owner", now, now),
            db_path=self.db_path,
        )

        with self.assertRaises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO members (id, org_id, user_id, role, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?);",
                ("m2", "o1", "u1", "viewer", now, now),
                db_path=self.db_path,
            )

        # Clé API : empreinte unique
        token_hash = db.hash_token("vg_live_secret_key_1")
        db.execute(
            "INSERT INTO api_keys (id, org_id, name, key_prefix, key_hash, created_at) VALUES (?, ?, ?, ?, ?, ?);",
            ("k1", "o1", "Agent 1", "vg_live_sec", token_hash, now),
            db_path=self.db_path,
        )
        with self.assertRaises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO api_keys (id, org_id, name, key_prefix, key_hash, created_at) VALUES (?, ?, ?, ?, ?, ?);",
                ("k2", "o1", "Agent 2", "vg_live_sec", token_hash, now),
                db_path=self.db_path,
            )

        # Fournisseurs : adresse unique par organisation
        db.execute(
            "INSERT INTO suppliers (id, org_id, name, address, active_after, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?);",
            ("s1", "o1", "AWS", "0x1111111111111111111111111111111111111111", now, now, now),
            db_path=self.db_path,
        )
        with self.assertRaises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO suppliers (id, org_id, name, address, active_after, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?);",
                ("s2", "o1", "AWS Doublon", "0x1111111111111111111111111111111111111111", now, now, now),
                db_path=self.db_path,
            )

    def test_foreign_key_constraints(self):
        """Vérifie l'activation des clés étrangères et la suppression en cascade."""
        now = int(time.time())
        # Vérification du pragma
        row = db.query_one("PRAGMA foreign_keys;", db_path=self.db_path)
        self.assertEqual(row[0], 1)

        # Insertion d'un membre avec org inexistante -> refus
        with self.assertRaises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO members (id, org_id, user_id, role, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?);",
                ("m_bad", "org_inconnue", "u_inconnu", "viewer", now, now),
                db_path=self.db_path,
            )

        # Création org + user + member
        db.execute("INSERT INTO users (id, email, password_hash, created_at, updated_at) VALUES (?, ?, ?, ?, ?);",
                   ("u10", "bob@example.com", "hash", now, now), db_path=self.db_path)
        db.execute("INSERT INTO orgs (id, name, created_at, updated_at) VALUES (?, ?, ?, ?);",
                   ("o10", "Org Test", now, now), db_path=self.db_path)
        db.execute("INSERT INTO members (id, org_id, user_id, role, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?);",
                   ("m10", "o10", "u10", "admin", now, now), db_path=self.db_path)

        # Suppression de l'org -> cascade sur members
        db.execute("DELETE FROM orgs WHERE id = ?;", ("o10",), db_path=self.db_path)
        self.assertIsNone(db.query_one("SELECT * FROM members WHERE id = ?;", ("m10",), db_path=self.db_path))

    def test_role_check_constraint(self):
        """Vérifie le contrôle strict des rôles (owner, admin, approver, viewer)."""
        now = int(time.time())
        db.execute("INSERT INTO users (id, email, password_hash, created_at, updated_at) VALUES (?, ?, ?, ?, ?);",
                   ("u20", "charlie@example.com", "hash", now, now), db_path=self.db_path)
        db.execute("INSERT INTO orgs (id, name, created_at, updated_at) VALUES (?, ?, ?, ?);",
                   ("o20", "Org Roles", now, now), db_path=self.db_path)

        for valid_role in ["owner", "admin", "approver", "viewer"]:
            db.execute(
                "INSERT INTO members (id, org_id, user_id, role, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?);",
                (f"m_{valid_role}", "o20", "u20", valid_role, now, now),
                db_path=self.db_path,
            )
            db.execute("DELETE FROM members WHERE id = ?;", (f"m_{valid_role}",), db_path=self.db_path)

        for invalid_role in ["root", "superuser", "hacker", "guest", ""]:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute(
                    "INSERT INTO members (id, org_id, user_id, role, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?);",
                    ("m_bad_role", "o20", "u20", invalid_role, now, now),
                    db_path=self.db_path,
                )

    def test_sql_injection_impossible(self):
        """Vérifie que les chaînes malveillantes avec guillemets sont traitées comme de simples valeurs."""
        now = int(time.time())
        malicious_email = "victim@example.com' OR '1'='1"
        drop_table_email = "hacker@example.com'); DROP TABLE users; --"

        db.execute(
            "INSERT INTO users (id, email, password_hash, created_at, updated_at) VALUES (?, ?, ?, ?, ?);",
            ("u_inj1", malicious_email, "hash1", now, now),
            db_path=self.db_path,
        )
        db.execute(
            "INSERT INTO users (id, email, password_hash, created_at, updated_at) VALUES (?, ?, ?, ?, ?);",
            ("u_inj2", drop_table_email, "hash2", now, now),
            db_path=self.db_path,
        )

        # Recherche de l'injection : doit retourner uniquement la ligne spécifique, sans bypass
        res = db.query_one("SELECT * FROM users WHERE email = ?;", (malicious_email,), db_path=self.db_path)
        self.assertIsNotNone(res)
        self.assertEqual(res["id"], "u_inj1")

        # Une tentative d'injection non présente retourne None et non tous les utilisateurs
        empty_res = db.query_one("SELECT * FROM users WHERE email = ?;", ("autre' OR '1'='1",), db_path=self.db_path)
        self.assertIsNone(empty_res)

        # La table users existe toujours et contient bien nos 2 enregistrements
        all_users = db.query_all("SELECT * FROM users WHERE email LIKE '%@example.com%';", db_path=self.db_path)
        self.assertEqual(len(all_users), 2)

    def test_secret_hashing(self):
        """Vérifie le hachage scrypt pour mots de passe et SHA-256 pour jetons."""
        pwd = "MonMotDePasseTrèsSécurisé!2026"
        hashed = db.hash_password(pwd)
        self.assertTrue(hashed.startswith("scrypt$"), f"Format scrypt attendu, reçu : {hashed[:15]}")
        self.assertTrue(db.verify_password(pwd, hashed))
        self.assertFalse(db.verify_password("MauvaisMotDePasse", hashed))
        self.assertFalse(db.verify_password(pwd, "scrypt$invalid$format"))

        token = "vg_tok_abc123xyz"
        token_hash = db.hash_token(token)
        self.assertEqual(len(token_hash), 64)
        self.assertTrue(db.verify_token(token, token_hash))
        self.assertFalse(db.verify_token("autre_jeton", token_hash))

    def test_transaction_atomicity_and_rollback(self):
        """Vérifie le commit automatique et le rollback complet en cas d'erreur dans une transaction."""
        now = int(time.time())
        db.execute("INSERT INTO orgs (id, name, created_at, updated_at) VALUES (?, ?, ?, ?);",
                   ("o_tx", "Org Tx", now, now), db_path=self.db_path)

        # Transaction réussie
        with db.transaction(self.db_path):
            db.execute("INSERT INTO users (id, email, password_hash, created_at, updated_at) VALUES (?, ?, ?, ?, ?);",
                       ("u_tx1", "tx1@example.com", "h", now, now), db_path=self.db_path)
            db.execute("INSERT INTO users (id, email, password_hash, created_at, updated_at) VALUES (?, ?, ?, ?, ?);",
                       ("u_tx2", "tx2@example.com", "h", now, now), db_path=self.db_path)

        self.assertIsNotNone(db.query_one("SELECT * FROM users WHERE id = ?;", ("u_tx1",), db_path=self.db_path))
        self.assertIsNotNone(db.query_one("SELECT * FROM users WHERE id = ?;", ("u_tx2",), db_path=self.db_path))

        # Transaction qui échoue : rollback de toutes les opérations de ce bloc
        with self.assertRaises(ValueError):
            with db.transaction(self.db_path):
                db.execute("INSERT INTO users (id, email, password_hash, created_at, updated_at) VALUES (?, ?, ?, ?, ?);",
                           ("u_tx3", "tx3@example.com", "h", now, now), db_path=self.db_path)
                raise ValueError("Erreur volontaire pour forcer le rollback")

        self.assertIsNone(db.query_one("SELECT * FROM users WHERE id = ?;", ("u_tx3",), db_path=self.db_path))

    def test_thread_local_connections(self):
        """Vérifie qu'une connexion distincte est instanciée par thread."""
        conn_main = db.connect(self.db_path)
        conns_other: list[sqlite3.Connection] = []

        def worker():
            c = db.connect(self.db_path)
            conns_other.append(c)

        t = threading.Thread(target=worker)
        t.start()
        t.join()

        self.assertEqual(len(conns_other), 1)
        self.assertIsNot(conn_main, conns_other[0])

    def test_db_path_and_auto_mkdir(self):
        """Vérifie que le répertoire parent est automatiquement créé si absent."""
        nested_dir = os.path.join(self.tmp_dir, "deep", "nested", "storage")
        nested_db = os.path.join(nested_dir, "vault.db")
        self.assertFalse(os.path.exists(nested_dir))

        db.init_db(nested_db)
        self.assertTrue(os.path.exists(nested_dir))
        self.assertTrue(os.path.exists(nested_db))
        db.close_connection(nested_db)

    # ---- Non-régression : failles trouvées lors de la revue de l'étape 1

    def _audit_row(self, org_id="o1", user_id="u1", action="login"):
        now = int(time.time())
        h = db.compute_audit_hash(db.GENESIS_HASH, now, org_id, user_id, action, "{}")
        db.execute("INSERT INTO audit (org_id, user_id, action, details_json, prev_hash, entry_hash, created_at) "
                   "VALUES (?, ?, ?, '{}', ?, ?, ?)", (org_id, user_id, action, db.GENESIS_HASH, h, now),
                   db_path=self.db_path)

    def _seed_user_org(self):
        now = int(time.time())
        db.execute("INSERT INTO users (id, email, password_hash, created_at, updated_at) VALUES ('u1', 'a@x.fr', 'h', ?, ?)",
                   (now, now), db_path=self.db_path)
        db.execute("INSERT INTO orgs (id, name, created_at, updated_at) VALUES ('o1', 'Acme', ?, ?)",
                   (now, now), db_path=self.db_path)

    def test_audit_survives_user_and_org_deletion(self):
        """Supprimer un utilisateur ou une organisation n'efface ni ne modifie le journal (chaîne intacte)."""
        self._seed_user_org()
        self._audit_row()
        db.execute("DELETE FROM users WHERE id = 'u1'", db_path=self.db_path)
        db.execute("DELETE FROM orgs WHERE id = 'o1'", db_path=self.db_path)
        r = db.query_one("SELECT * FROM audit", db_path=self.db_path)
        self.assertIsNotNone(r)
        self.assertEqual(r["entry_hash"], db.compute_audit_hash(r["prev_hash"], r["created_at"], r["org_id"],
                                                                r["user_id"], r["action"], r["details_json"]))

    def test_audit_is_append_only(self):
        """UPDATE et DELETE sur le journal sont refusés par la base elle-même."""
        self._audit_row()
        with self.assertRaises(sqlite3.DatabaseError):
            db.execute("UPDATE audit SET action = 'rien'", db_path=self.db_path)
        with self.assertRaises(sqlite3.DatabaseError):
            db.execute("DELETE FROM audit", db_path=self.db_path)

    def test_audit_hash_unambiguous(self):
        """Déplacer un « | » d'un champ à l'autre change l'empreinte (pas de collision par séparateur)."""
        a = db.compute_audit_hash("0", 1, "o1", "u1", "pay|x", "{}")
        b = db.compute_audit_hash("0", 1, "o1", "u1", "pay", "x|{}")
        self.assertNotEqual(a, b)
        self.assertNotEqual(db.compute_audit_hash("0", 1, None, "u1", "a", "{}"),
                            db.compute_audit_hash("0", 1, "", "u1", "a", "{}"))

    def test_amounts_are_integer_gwei(self):
        """Montants stockés en wei entiers ; montant négatif et décision inconnue refusés."""
        self._seed_user_org()
        now = int(time.time())
        sql = ("INSERT INTO payments (id, org_id, recipient, amount_gwei, decision, created_at, updated_at) "
               "VALUES (?, 'o1', '0xabc', ?, ?, ?, ?)")
        db.execute(sql, ("p1", 10**8 + 2 * 10**8, "allowed", now, now), db_path=self.db_path)
        v = db.query_one("SELECT amount_gwei FROM payments WHERE id = 'p1'", db_path=self.db_path)["amount_gwei"]
        self.assertEqual(v, 3 * 10**8)
        for pid, amount, decision in (("p2", -1, "allowed"), ("p3", 1, "approved_by_magic")):
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute(sql, (pid, amount, decision, now, now), db_path=self.db_path)

    @unittest.skipIf(os.name == "nt", "permissions POSIX")
    def test_db_file_private(self):
        """La base n'est lisible que par le compte du serveur (0600, dossier 0700)."""
        nested = os.path.join(self.tmp_dir, "priv", "vault.db")
        db.init_db(nested)
        self.assertEqual(os.stat(nested).st_mode & 0o777, 0o600)
        self.assertEqual(os.stat(os.path.dirname(nested)).st_mode & 0o777, 0o700)
        db.close_connection(nested)

    def test_server_uses_db_password_hashing(self):
        """Une seule implémentation du hachage : server.py réutilise celle de db.py."""
        import server
        self.assertIs(server.hash_password, db.hash_password)
        self.assertTrue(server.verify_password("motdepasse-long", db.hash_password("motdepasse-long")))


try:
    import auth
    import orgs
except ImportError:
    from agent import auth
    from agent import orgs
import http.client
import json


class TestProductAuth(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="vg_auth_test_")
        self.db_path = os.path.join(self.tmp_dir, "test.db")
        db.init_db(self.db_path)

    def tearDown(self):
        db.close_all()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    # 1. Validation du mot de passe
    def test_password_policy(self):
        """Vérifie le rejet des mots de passe trop courts, courants ou trop simples."""
        # Trop court (< 12 caractères)
        for short_pwd in ["", "12345678901", "password123", "court"]:
            with self.assertRaises(auth.AuthError):
                auth.validate_password(short_pwd)

        # Mots de passe courants >= 12 caractères
        for common in ["password1234", "qwerty123456", "123456789012", "azerty123456", "admin1234567"]:
            with self.assertRaises(auth.AuthError):
                auth.validate_password(common)

        # Répétitions triviales
        with self.assertRaises(auth.AuthError):
            auth.validate_password("aaaaaaaaaaaa")
        with self.assertRaises(auth.AuthError):
            auth.validate_password("111111111111")

        # Mot de passe valide
        try:
            auth.validate_password("Passphrase-Tres-Solide-2026!")
        except auth.AuthError:
            self.fail("Mot de passe valide rejeté à tort")

    # 2. Inscription et transactions atomiques
    def test_signup_open_and_transaction(self):
        """Inscription libre : crée utilisateur + organisation (owner) de manière atomique."""
        res = auth.signup("alice@example.com", "PassphraseValide123!", org_name="Alice Corp", db_path=self.db_path)
        self.assertIn("token", res)
        self.assertEqual(res["user"]["email"], "alice@example.com")
        self.assertEqual(res["org"]["name"], "Alice Corp")

        # Vérification en base
        user = db.query_one("SELECT * FROM users WHERE email = 'alice@example.com';", db_path=self.db_path)
        self.assertIsNotNone(user)
        member = db.query_one("SELECT * FROM members WHERE user_id = ?;", (user["id"],), db_path=self.db_path)
        self.assertIsNotNone(member)
        self.assertEqual(member["role"], "owner")

        # Doublon d'email refusé
        with self.assertRaises(auth.AuthError) as ctx:
            auth.signup("alice@example.com", "AutreMotDePasse123!", db_path=self.db_path)
        self.assertEqual(ctx.exception.code, 409)

    def test_signup_closed_without_invite(self):
        """Si SIGNUP_OPEN=0, l'inscription libre est bloquée sauf avec une invitation."""
        old_env = os.environ.get("SIGNUP_OPEN")
        try:
            os.environ["SIGNUP_OPEN"] = "0"
            with self.assertRaises(auth.AuthError) as ctx:
                auth.signup("bob@example.com", "PassphraseValide123!", db_path=self.db_path)
            self.assertEqual(ctx.exception.code, 403)

            # Avec invitation valide
            # Création préalable d'une organisation
            now = int(time.time())
            db.execute("INSERT INTO orgs (id, name, slug, created_at, updated_at) VALUES ('o_inv', 'Org Inv', 'inv', ?, ?);",
                       (now, now), db_path=self.db_path)
            token, inv = auth.create_invite("o_inv", "bob@example.com", "viewer", "system", db_path=self.db_path)

            res = auth.signup("bob@example.com", "PassphraseValide123!", invite_token=token, db_path=self.db_path)
            self.assertEqual(res["user"]["email"], "bob@example.com")
            member = db.query_one("SELECT * FROM members WHERE user_id = ?;", (res["user"]["id"],), db_path=self.db_path)
            self.assertEqual(member["role"], "viewer")
        finally:
            if old_env is not None:
                os.environ["SIGNUP_OPEN"] = old_env
            else:
                os.environ.pop("SIGNUP_OPEN", None)

    # 3. Connexion, protection anti-énumération et verrouillage
    def test_login_anti_enumeration(self):
        """Énumération impossible : même message d'erreur et calcul factice pour email existant ou non."""
        auth.signup("carol@example.com", "PassphraseValide123!", db_path=self.db_path)

        # Mauvais mot de passe pour utilisateur existant
        with self.assertRaises(auth.AuthError) as ctx1:
            auth.login("carol@example.com", "MauvaisMotDePasse123!", db_path=self.db_path)
        self.assertEqual(ctx1.exception.code, 401)
        self.assertEqual(ctx1.exception.message, "Identifiants invalides")

        # Utilisateur inexistant
        with self.assertRaises(auth.AuthError) as ctx2:
            auth.login("inconnu@example.com", "MauvaisMotDePasse123!", db_path=self.db_path)
        self.assertEqual(ctx2.exception.code, 401)
        self.assertEqual(ctx2.exception.message, "Identifiants invalides")

        # Vérification des événements de connexion enregistrés
        events = db.query_all("SELECT * FROM login_events ORDER BY id ASC;", db_path=self.db_path)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["reason"], "bad_password")
        self.assertEqual(events[1]["reason"], "user_not_found")
        self.assertIsNone(events[1]["user_id"])

    def test_login_lockout_after_five_failures(self):
        """Verrouillage du compte pendant 15 minutes après 5 échecs consécutifs."""
        auth.signup("david@example.com", "PassphraseValide123!", db_path=self.db_path)

        # 4 échecs consécutifs
        for _ in range(4):
            with self.assertRaises(auth.AuthError):
                auth.login("david@example.com", "FauxPassword123!", db_path=self.db_path)

        user = db.query_one("SELECT failed_login_attempts, locked_until FROM users WHERE email = 'david@example.com';", db_path=self.db_path)
        self.assertEqual(user["failed_login_attempts"], 4)
        self.assertIsNone(user["locked_until"])

        # 5e échec -> déclenche le verrouillage (15 minutes)
        with self.assertRaises(auth.AuthError):
            auth.login("david@example.com", "FauxPassword123!", db_path=self.db_path)

        now = int(time.time())
        user = db.query_one("SELECT failed_login_attempts, locked_until FROM users WHERE email = 'david@example.com';", db_path=self.db_path)
        self.assertEqual(user["failed_login_attempts"], 5)
        self.assertIsNotNone(user["locked_until"])
        self.assertGreater(user["locked_until"], now + 800)

        # 6e tentative (même avec le BON mot de passe) -> refusée car verrouillé
        with self.assertRaises(auth.AuthError) as ctx_locked:
            auth.login("david@example.com", "PassphraseValide123!", db_path=self.db_path)
        self.assertEqual(ctx_locked.exception.message, "Identifiants invalides")

        last_event = db.query_one("SELECT * FROM login_events ORDER BY id DESC LIMIT 1;", db_path=self.db_path)
        self.assertEqual(last_event["reason"], "locked")

        # Expiration du verrou (simulation du passage de 15 minutes)
        db.execute("UPDATE users SET locked_until = ? WHERE email = 'david@example.com';", (now - 1,), db_path=self.db_path)
        res = auth.login("david@example.com", "PassphraseValide123!", db_path=self.db_path)
        self.assertIn("token", res)
        # Compteur réinitialisé
        user_after = db.query_one("SELECT failed_login_attempts, locked_until FROM users WHERE email = 'david@example.com';", db_path=self.db_path)
        self.assertEqual(user_after["failed_login_attempts"], 0)
        self.assertIsNone(user_after["locked_until"])

    # 4. Double authentification TOTP RFC 6238
    def test_totp_rfc6238_and_replay_rejection(self):
        """Vérifie la génération TOTP, la conformité RFC 6238 et le refus de rejeu d'un code déjà accepté."""
        secret = auth.generate_totp_secret()
        uri = auth.get_totp_uri(secret, "eva@example.com")
        self.assertTrue(uri.startswith("otpauth://totp/VaultGuard:eva%40example.com?secret="))
        self.assertIn("digits=6", uri)

        now = 1700000000
        code = auth.hotp(secret, now // 30)
        self.assertEqual(len(code), 6)
        self.assertTrue(code.isdigit())

        # Validation dans la fenêtre +-1
        self.assertTrue(auth.verify_totp(secret, code, now=now, db_path=self.db_path))
        # Fenêtre -1 pas de 30 s
        code_prev = auth.hotp(secret, (now // 30) - 1)
        self.assertTrue(auth.verify_totp(secret, code_prev, now=now, db_path=self.db_path))
        # Fenêtre +1 pas de 30 s
        code_next = auth.hotp(secret, (now // 30) + 1)
        self.assertTrue(auth.verify_totp(secret, code_next, now=now, db_path=self.db_path))
        # Hors fenêtre (+3 pas de 30 s)
        code_far = auth.hotp(secret, (now // 30) + 3)
        self.assertFalse(auth.verify_totp(secret, code_far, now=now, db_path=self.db_path))

        # Anti-rejeu : un code validé une première fois doit être refusé à la seconde tentative
        uid = "u_test_replay"
        self.assertTrue(auth.verify_totp(secret, code, user_id=uid, now=now, db_path=self.db_path))
        self.assertFalse(auth.verify_totp(secret, code, user_id=uid, now=now, db_path=self.db_path),
                         "Le code TOTP rejoué doit être strictement refusé")

    def test_totp_2fa_full_flow(self):
        """Cycle complet 2FA : activation avec code de vérification, puis connexion sécurisée."""
        signup_res = auth.signup("frank@example.com", "PassphraseValide123!", db_path=self.db_path)
        uid = signup_res["user"]["id"]

        setup_res = auth.setup_2fa(uid, db_path=self.db_path)
        self.assertIn("secret", setup_res)
        self.assertIn("otpauth_url", setup_res)

        now = int(time.time())
        good_code = auth.hotp(setup_res["secret"], now // 30)

        # Mauvais code -> échec
        with self.assertRaises(auth.AuthError):
            auth.enable_2fa(uid, "000000", db_path=self.db_path)

        # Bon code -> activation
        enable_res = auth.enable_2fa(uid, good_code, db_path=self.db_path)
        self.assertTrue(enable_res["ok"])

        # Connexion avec 2FA activé
        # Sans code TOTP -> demande le code
        res_no_totp = auth.login("frank@example.com", "PassphraseValide123!", db_path=self.db_path)
        self.assertTrue(res_no_totp.get("totp_required"))

        # Avec code rejoué (déjà utilisé à l'activation) -> échec
        with self.assertRaises(auth.AuthError):
            auth.login("frank@example.com", "PassphraseValide123!", totp_code=good_code, db_path=self.db_path)

        # Avec nouveau code pour le pas suivant (+1 pas)
        future_now = now + 31
        fresh_code = auth.hotp(setup_res["secret"], future_now // 30)
        res_with_totp = auth.login("frank@example.com", "PassphraseValide123!", totp_code=fresh_code, db_path=self.db_path)
        self.assertIn("token", res_with_totp)

    # 5. Sessions en base et déconnexions
    def test_sessions_inactivity_and_revocation(self):
        """Sessions en base : expiration après 2 h d'inactivité, révocation unitaire et globale."""
        signup_res = auth.signup("grace@example.com", "PassphraseValide123!", db_path=self.db_path)
        token1 = signup_res["token"]
        uid = signup_res["user"]["id"]

        # Seule l'empreinte SHA-256 est en base
        token_hash = db.hash_token(token1)
        db_sess = db.query_one("SELECT * FROM sessions WHERE token_hash = ?;", (token_hash,), db_path=self.db_path)
        self.assertIsNotNone(db_sess)
        self.assertNotIn(token1, [db_sess["id"], db_sess["token_hash"]])

        # Session valide
        auth_info = auth.get_user_from_token(token1, db_path=self.db_path)
        self.assertIsNotNone(auth_info)
        self.assertEqual(auth_info[0]["email"], "grace@example.com")

        # Expiration après 2 heures d'inactivité
        now = int(time.time())
        db.execute("UPDATE sessions SET expires_at = ? WHERE token_hash = ?;", (now - 10, token_hash), db_path=self.db_path)
        self.assertIsNone(auth.get_user_from_token(token1, db_path=self.db_path))

        # Nouvelle connexion -> nouvelle session
        login_res = auth.login("grace@example.com", "PassphraseValide123!", db_path=self.db_path)
        token2 = login_res["token"]
        self.assertNotEqual(token1, token2)

        # Déconnexion unitaire (logout)
        auth.delete_session(token2, db_path=self.db_path)
        self.assertIsNone(auth.get_user_from_token(token2, db_path=self.db_path))

        # Déconnexion de toutes les sessions
        token_a, _ = auth.create_session(uid, db_path=self.db_path)
        token_b, _ = auth.create_session(uid, db_path=self.db_path)
        self.assertIsNotNone(auth.get_user_from_token(token_a, db_path=self.db_path))
        self.assertIsNotNone(auth.get_user_from_token(token_b, db_path=self.db_path))

        auth.delete_all_sessions(uid, db_path=self.db_path)
        self.assertIsNone(auth.get_user_from_token(token_a, db_path=self.db_path))
        self.assertIsNone(auth.get_user_from_token(token_b, db_path=self.db_path))

    def test_password_change_invalidates_other_sessions(self):
        """Changer le mot de passe exige l'ancien et invalide toutes les AUTRES sessions."""
        signup_res = auth.signup("heidi@example.com", "AncienMotDePasse123!", db_path=self.db_path)
        uid = signup_res["user"]["id"]
        token_active = signup_res["token"]
        token_other, _ = auth.create_session(uid, db_path=self.db_path)

        # Échec si l'ancien mot de passe est faux
        with self.assertRaises(auth.AuthError):
            auth.change_password(uid, "MauvaisAncien123!", "NouveauSuperPasse123!", current_token=token_active, db_path=self.db_path)

        # Succès : token_active reste valide, token_other est révoqué
        auth.change_password(uid, "AncienMotDePasse123!", "NouveauSuperPasse123!", current_token=token_active, db_path=self.db_path)
        self.assertIsNotNone(auth.get_user_from_token(token_active, db_path=self.db_path))
        self.assertIsNone(auth.get_user_from_token(token_other, db_path=self.db_path))

        # Connexion avec le nouveau mot de passe
        new_login = auth.login("heidi@example.com", "NouveauSuperPasse123!", db_path=self.db_path)
        self.assertIn("token", new_login)

    # 6. Invitations à usage unique 7 jours
    def test_invitations_lifecycle(self):
        """Invitations : expiration à 7 jours, usage unique, refus de réutilisation."""
        now = int(time.time())
        db.execute("INSERT INTO orgs (id, name, slug, created_at, updated_at) VALUES ('o_test', 'Test Org', 'test', ?, ?);",
                   (now, now), db_path=self.db_path)

        token, inv = auth.create_invite("o_test", "invitee@example.com", "approver", "u_admin", db_path=self.db_path)
        self.assertEqual(inv["role"], "approver")
        self.assertGreater(inv["expires_at"], now + 6 * 86400)

        # Acceptation initiale -> succès
        acc_res = auth.accept_invite(token, password="PassphraseValide123!", db_path=self.db_path)
        self.assertEqual(acc_res["org_id"], "o_test")
        self.assertEqual(acc_res["role"], "approver")

        # Seconde acceptation avec le MÊME jeton -> refusée (usage unique)
        with self.assertRaises(auth.AuthError) as ctx_reused:
            auth.accept_invite(token, password="PassphraseValide123!", db_path=self.db_path)
        self.assertEqual(ctx_reused.exception.message, "Invitation déjà utilisée")

        # Jeton expiré (> 7 jours)
        token_exp, inv_exp = auth.create_invite("o_test", "expired@example.com", "viewer", "u_admin", db_path=self.db_path)
        db.execute("UPDATE invites SET expires_at = ? WHERE id = ?;", (now - 10, inv_exp["id"]), db_path=self.db_path)
        with self.assertRaises(auth.AuthError) as ctx_exp:
            auth.accept_invite(token_exp, password="PassphraseValide123!", db_path=self.db_path)
        self.assertEqual(ctx_exp.exception.message, "Invitation expirée")

    # 7. Intégrité de la piste d'audit chaînée
    def test_chained_audit_trail_integrity(self):
        """Vérifie que chaque action sensible produit une ligne d'audit strictement chaînée."""
        # 1. Inscription
        res = auth.signup("audit_user@example.com", "PassphraseValide123!", db_path=self.db_path)
        uid = res["user"]["id"]
        # 2. 2FA setup & enable
        s2 = auth.setup_2fa(uid, db_path=self.db_path)
        now = int(time.time())
        code = auth.hotp(s2["secret"], now // 30)
        auth.enable_2fa(uid, code, db_path=self.db_path)
        # 3. Changement de mot de passe
        auth.change_password(uid, "PassphraseValide123!", "NouveauPassphrase123!", current_token=res["token"], db_path=self.db_path)
        # 4. Déconnexion globale
        auth.delete_all_sessions(uid, db_path=self.db_path)

        rows = db.query_all("SELECT * FROM audit ORDER BY id ASC;", db_path=self.db_path)
        self.assertGreaterEqual(len(rows), 5)

        prev = db.GENESIS_HASH
        for row in rows:
            self.assertEqual(row["prev_hash"], prev, f"Rupture de chaîne sur l'audit id={row['id']}")
            computed = db.compute_audit_hash(
                row["prev_hash"],
                row["created_at"],
                row["org_id"],
                row["user_id"],
                row["action"],
                row["details_json"],
                api_key_id=row["api_key_id"],
                ip=row["ip"],
            )
            self.assertEqual(row["entry_hash"], computed, f"Empreinte altérée sur l'audit id={row['id']}")
            prev = row["entry_hash"]

    # 8. Création du superadmin
    def test_create_superadmin(self):
        """Vérifie la création d'un superadmin avec organisation plateforme dédiée."""
        adm = auth.create_superadmin("root@vaultguard.local", "SuperAdminSecretPassphrase2026!", db_path=self.db_path)
        self.assertEqual(adm["email"], "root@vaultguard.local")
        self.assertEqual(adm["is_superadmin"], 1)

        user = db.query_one("SELECT * FROM users WHERE email = 'root@vaultguard.local';", db_path=self.db_path)
        self.assertEqual(user["is_superadmin"], 1)
        self.assertEqual(user["is_active"], 1)

    # ---- Non-régression : failles trouvées lors de la revue de l'étape 2

    def test_invite_cannot_take_over_existing_account(self):
        """Un lien d'invitation ne donne jamais de session sur un compte existant (prise de compte)."""
        p = self.db_path
        victim = auth.signup("victime@banque.fr", "MotDePasseVictime-2026", org_name="Banque", db_path=p)
        att = auth.signup("pirate@evil.fr", "MotDePassePirate-2026", org_name="Evil", db_path=p)
        tok, _ = auth.create_invite(att["org"]["id"], "victime@banque.fr", "viewer",
                                    invited_by=att["user"]["id"], db_path=p)
        # Sans être connecté, avec un mot de passe quelconque -> refusé.
        with self.assertRaises(auth.AuthError) as ctx:
            auth.accept_invite(tok, password="NimporteQuoi-123456", db_path=p)
        self.assertEqual(ctx.exception.code, 409)
        # Connecté avec un autre compte -> refusé.
        with self.assertRaises(auth.AuthError):
            auth.accept_invite(tok, user_id=att["user"]["id"], db_path=p)
        # Le refus n'a pas consommé le lien : la vraie destinataire, connectée, peut l'accepter.
        res = auth.accept_invite(tok, user_id=victim["user"]["id"], db_path=p)
        self.assertEqual(res["user_id"], victim["user"]["id"])
        self.assertEqual(res["org_id"], att["org"]["id"])

    def test_totp_cannot_be_reset_once_enabled(self):
        """Une session volée ne peut pas rattacher la 2FA à un autre téléphone."""
        uid = auth.signup("deuxfa@example.com", "PassphraseValide123!", db_path=self.db_path)["user"]["id"]
        s = auth.setup_2fa(uid, db_path=self.db_path)
        auth.enable_2fa(uid, auth.hotp(s["secret"], int(time.time()) // 30), db_path=self.db_path)
        with self.assertRaises(auth.AuthError):
            auth.setup_2fa(uid, db_path=self.db_path)
        row = db.query_one("SELECT totp_secret FROM users WHERE id = ?;", (uid,), db_path=self.db_path)
        self.assertEqual(row["totp_secret"], s["secret"])

    def test_totp_code_single_use_under_concurrency(self):
        """Le même code TOTP envoyé 10 fois en parallèle n'est accepté qu'une fois."""
        secret = auth.generate_totp_secret()
        now = int(time.time())
        code = auth.hotp(secret, now // 30)
        auth.verify_totp(secret, "000000", user_id="init", now=now, db_path=self.db_path)  # crée la table
        results = []

        def w():
            results.append(auth.verify_totp(secret, code, user_id="u-race", now=now, db_path=self.db_path))
            db.close_all()
        ts = [threading.Thread(target=w) for _ in range(10)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(results.count(True), 1)

    def test_audit_chain_never_forks_under_concurrency(self):
        """30 écritures d'audit simultanées produisent une chaîne linéaire, sans bifurcation."""
        def w(i):
            auth.log_audit("test.parallel", details={"i": i}, db_path=self.db_path)
            db.close_all()
        ts = [threading.Thread(target=w, args=(i,)) for i in range(30)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        rows = db.query_all("SELECT prev_hash, entry_hash FROM audit ORDER BY id;", db_path=self.db_path)
        self.assertEqual(len(rows), 30)
        prev = db.GENESIS_HASH
        for r in rows:
            self.assertEqual(r["prev_hash"], prev)
            prev = r["entry_hash"]

    def test_lockout_counter_atomic(self):
        """10 mauvais mots de passe en parallèle : le compteur les compte tous et le compte est verrouillé."""
        auth.signup("rafale@example.com", "PassphraseValide123!", db_path=self.db_path)

        def w():
            try:
                auth.login("rafale@example.com", "mauvais-mot-de-passe", db_path=self.db_path)
            except auth.AuthError:
                pass
            db.close_all()
        ts = [threading.Thread(target=w) for _ in range(10)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        row = db.query_one("SELECT failed_login_attempts, locked_until FROM users WHERE email = 'rafale@example.com';",
                           db_path=self.db_path)
        self.assertGreaterEqual(row["failed_login_attempts"], 5)
        self.assertIsNotNone(row["locked_until"])
        with self.assertRaises(auth.AuthError):
            auth.login("rafale@example.com", "PassphraseValide123!", db_path=self.db_path)

    def test_org_name_sanitized(self):
        """Nom d'organisation : caractères de contrôle retirés, longueur bornée."""
        res = auth.signup("nom@example.com", "PassphraseValide123!", org_name="A\x00B\x1b" + "x" * 500,
                          db_path=self.db_path)
        self.assertTrue(res["org"]["name"].startswith("AB"))
        self.assertLessEqual(len(res["org"]["name"]), 80)


class TestProductServerAuth(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import server
        cls.server = server
        cls.tmp_dir = tempfile.mkdtemp(prefix="vg_srv_test_")
        cls.db_path = os.path.join(cls.tmp_dir, "server_test.db")
        os.environ["DB_PATH"] = cls.db_path
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
        shutil.rmtree(cls.tmp_dir, ignore_errors=True)

    def _req(self, method, path, body=None, cookie="", csrf="", headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Host": "localhost"}
        if cookie:
            h["Cookie"] = cookie
        if csrf:
            h["X-CSRF-Token"] = csrf
        if body is not None:
            h["Content-Type"] = "application/json"
            data = json.dumps(body).encode()
        else:
            data = None
        if headers:
            h.update(headers)
        c.request(method, path, body=data, headers=h)
        r = c.getresponse()
        payload = r.read()
        sc = r.getheader("Set-Cookie")
        cookie_out = sc.split(";")[0] if sc else cookie
        c.close()
        try:
            parsed = json.loads(payload)
        except Exception:
            parsed = payload
        return r.status, parsed, cookie_out, r

    def _get_csrf(self, cookie=""):
        status, data, new_cookie, _ = self._req("GET", "/api/session", cookie=cookie)
        return data["csrf"], new_cookie

    def test_http_auth_full_lifecycle(self):
        """Cycle complet via les routes HTTP : signup, me, 2fa, password, logout, login."""
        self.server.LIMITER._b.clear()
        csrf, cookie = self._get_csrf()

        # 1. Signup
        signup_body = {"email": "user_api@example.com", "password": "PasswordApi12345!", "org_name": "API Org"}
        st, res, cookie, _ = self._req("POST", "/api/auth/signup", signup_body, cookie=cookie, csrf=csrf)
        self.assertEqual(st, 201)
        self.assertTrue(res["ok"])
        csrf = res["csrf"]

        # 2. GET /api/auth/me
        st, me_res, _, _ = self._req("GET", "/api/auth/me", cookie=cookie)
        self.assertEqual(st, 200)
        self.assertTrue(me_res["authenticated"])
        self.assertEqual(me_res["user"]["email"], "user_api@example.com")
        self.assertEqual(me_res["org"]["name"], "API Org")

        # 3. 2FA setup & enable
        st, setup_res, _, _ = self._req("POST", "/api/auth/2fa/setup", {}, cookie=cookie, csrf=csrf)
        self.assertEqual(st, 200)
        secret = setup_res["secret"]

        # Code dans la fenêtre -1 pour laisser le pas courant pour le login
        current_counter = int(time.time() // 30)
        code_enable = auth.hotp(secret, current_counter - 1)
        st, enable_res, _, _ = self._req("POST", "/api/auth/2fa/enable", {"code": code_enable}, cookie=cookie, csrf=csrf)
        self.assertEqual(st, 200)
        self.assertTrue(enable_res["ok"])

        # 4. Changement de mot de passe
        pw_body = {"old_password": "PasswordApi12345!", "new_password": "NewPasswordApi12345!"}
        st, pw_res, _, _ = self._req("POST", "/api/auth/password", pw_body, cookie=cookie, csrf=csrf)
        self.assertEqual(st, 200)
        self.assertTrue(pw_res["ok"])

        # 5. Déconnexion (logout)
        st, lo_res, cookie, _ = self._req("POST", "/api/auth/logout", {}, cookie=cookie, csrf=csrf)
        self.assertEqual(st, 200)
        self.assertTrue(lo_res["ok"])

        # Après logout : /api/auth/me retourne 401
        st, _, _, _ = self._req("GET", "/api/auth/me", cookie=cookie)
        self.assertEqual(st, 401)

        # 6. Reconnexion (login) avec 2FA
        csrf, cookie = self._get_csrf()
        # Premier appel sans code TOTP -> retourne totp_required
        login_body = {"email": "user_api@example.com", "password": "NewPasswordApi12345!"}
        st, req_res, _, _ = self._req("POST", "/api/auth/login", login_body, cookie=cookie, csrf=csrf)
        self.assertEqual(st, 200)
        self.assertTrue(req_res.get("totp_required"))

        # Reconnexion avec le code du pas courant (frais et non consommé)
        code_login = auth.hotp(secret, int(time.time() // 30))
        login_body["totp_code"] = code_login
        st, ok_res, cookie, _ = self._req("POST", "/api/auth/login", login_body, cookie=cookie, csrf=csrf)
        self.assertEqual(st, 200)
        self.assertTrue(ok_res["ok"])
        csrf = ok_res["csrf"]

        # 7. Logout-all
        st, loa_res, _, _ = self._req("POST", "/api/auth/logout-all", {}, cookie=cookie, csrf=csrf)
        self.assertEqual(st, 200)
        self.assertTrue(loa_res["ok"])

    def test_http_protections_enforced(self):
        """Vérifie que CSRF, Origin et Host restent vérifiés sur les routes auth."""
        self.server.LIMITER._b.clear()
        csrf, cookie = self._get_csrf()

        # Origin tiers -> 403
        st, _, _, _ = self._req("POST", "/api/auth/login", {"email": "a@x.com", "password": "p"},
                                cookie=cookie, csrf=csrf, headers={"Origin": "https://evil.com"})
        self.assertEqual(st, 403)

        # CSRF manquant -> 403
        st, _, _, _ = self._req("POST", "/api/auth/login", {"email": "a@x.com", "password": "p"},
                                cookie=cookie, csrf="mauvais")
        self.assertEqual(st, 403)

        # Host malveillant -> 421
        st, _, _, _ = self._req("GET", "/api/auth/me", cookie=cookie, headers={"Host": "evil.com"})
        self.assertEqual(st, 421)

    def test_http_logout_all_kills_other_sessions_in_memory(self):
        """Après « déconnecter toutes mes sessions », une session volée ne garde ni CSRF ni état en mémoire."""
        self.server.LIMITER._b.clear()
        csrf, cookie = self._get_csrf()
        body = {"email": "vol@example.com", "password": "PasswordVol12345!"}
        st, res, stolen_cookie, _ = self._req("POST", "/api/auth/signup", body, cookie=cookie, csrf=csrf)
        self.assertEqual(st, 201)
        stolen_csrf = res["csrf"]
        # La victime se connecte ailleurs puis coupe toutes ses sessions.
        csrf2, cookie2 = self._get_csrf()
        st, res2, cookie2, _ = self._req("POST", "/api/auth/login", body, cookie=cookie2, csrf=csrf2)
        self.assertEqual(st, 200)
        st, _, _, _ = self._req("POST", "/api/auth/logout-all", {}, cookie=cookie2, csrf=res2["csrf"])
        self.assertEqual(st, 200)
        # La session volée ne passe plus, même sur une route qui n'appelle pas auth directement.
        st, _, _, _ = self._req("POST", "/api/reset", {}, cookie=stolen_cookie, csrf=stolen_csrf)
        self.assertIn(st, (401, 403))
        st, _, _, _ = self._req("GET", "/api/auth/me", cookie=stolen_cookie)
        self.assertEqual(st, 401)

    def test_superadmin_without_2fa_has_no_vault_control(self):
        """Un super-admin sans 2FA n'obtient pas le contrôle du coffre réel."""
        self.server.LIMITER._b.clear()
        auth.create_superadmin("root2@vaultguard.local", "SuperAdminSecretPassphrase2026!")
        csrf, cookie = self._get_csrf()
        body = {"email": "root2@vaultguard.local", "password": "SuperAdminSecretPassphrase2026!"}
        st, res, cookie, _ = self._req("POST", "/api/auth/login", body, cookie=cookie, csrf=csrf)
        self.assertEqual(st, 200)
        st, _, _, _ = self._req("GET", "/api/state?target=live", cookie=cookie)
        self.assertEqual(st, 403)


# ==============================================================================
# ÉTAPE 3 — Espaces clients (organisations), rôles, anti-IDOR, audit chaîné
# ==============================================================================

class TestOrgsAndPermissions(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="vg_orgs_test_")
        self.db_path = os.path.join(self.tmp_dir, "test.db")
        db.init_db(self.db_path)
        self.now = int(time.time())

        # Création de deux organisations de test avec utilisateurs
        self.u_owner = "u_alice"
        self.u_admin = "u_bob"
        self.u_approver = "u_charlie"
        self.u_viewer = "u_david"
        self.u_stranger = "u_eve"
        self.org1_id = "o_alpha"
        self.org2_id = "o_beta"

        pwd = db.hash_password("PassphraseValide12345!")
        for uid, email in [
            (self.u_owner, "alice@alpha.com"),
            (self.u_admin, "bob@alpha.com"),
            (self.u_approver, "charlie@alpha.com"),
            (self.u_viewer, "david@alpha.com"),
            (self.u_stranger, "eve@beta.com"),
        ]:
            db.execute("INSERT INTO users (id, email, password_hash, created_at, updated_at) VALUES (?, ?, ?, ?, ?);",
                       (uid, email, pwd, self.now, self.now), db_path=self.db_path)

        db.execute("INSERT INTO orgs (id, name, slug, max_tx_gwei, max_daily_gwei, human_threshold_gwei, activation_delay, circuit_breaker_limit, created_at, updated_at) "
                   "VALUES (?, 'Alpha Corp', 'alpha', 100000000, 300000000, 50000000, 86400, 5, ?, ?);",
                   (self.org1_id, self.now, self.now), db_path=self.db_path)
        db.execute("INSERT INTO orgs (id, name, slug, created_at, updated_at) VALUES (?, 'Beta Corp', 'beta', ?, ?);",
                   (self.org2_id, self.now, self.now), db_path=self.db_path)

        # Adhésions Alpha
        db.execute("INSERT INTO members (id, org_id, user_id, role, created_at, updated_at) VALUES ('m_a', ?, ?, 'owner', ?, ?);",
                   (self.org1_id, self.u_owner, self.now, self.now), db_path=self.db_path)
        db.execute("INSERT INTO members (id, org_id, user_id, role, created_at, updated_at) VALUES ('m_b', ?, ?, 'admin', ?, ?);",
                   (self.org1_id, self.u_admin, self.now, self.now), db_path=self.db_path)
        db.execute("INSERT INTO members (id, org_id, user_id, role, created_at, updated_at) VALUES ('m_c', ?, ?, 'approver', ?, ?);",
                   (self.org1_id, self.u_approver, self.now, self.now), db_path=self.db_path)
        db.execute("INSERT INTO members (id, org_id, user_id, role, created_at, updated_at) VALUES ('m_d', ?, ?, 'viewer', ?, ?);",
                   (self.org1_id, self.u_viewer, self.now, self.now), db_path=self.db_path)

        # Adhésion Beta pour Eve
        db.execute("INSERT INTO members (id, org_id, user_id, role, created_at, updated_at) VALUES ('m_e', ?, ?, 'owner', ?, ?);",
                   (self.org2_id, self.u_stranger, self.now, self.now), db_path=self.db_path)

    def tearDown(self):
        db.close_all()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_role_hierarchy_matrix(self):
        """Vérifie la matrice complète des rôles : owner > admin > approver > viewer."""
        roles = {
            self.u_owner: "owner",
            self.u_admin: "admin",
            self.u_approver: "approver",
            self.u_viewer: "viewer",
        }
        for uid, r in roles.items():
            # Viewer requis : tous passent
            m = orgs.require_role(uid, self.org1_id, "viewer", db_path=self.db_path)
            self.assertEqual(m["role"], r)

            # Approver requis : approver, admin, owner passent ; viewer échoue (403)
            if r in ("approver", "admin", "owner"):
                m = orgs.require_role(uid, self.org1_id, "approver", db_path=self.db_path)
                self.assertEqual(m["role"], r)
            else:
                with self.assertRaises(orgs.OrgError) as ctx:
                    orgs.require_role(uid, self.org1_id, "approver", db_path=self.db_path)
                self.assertEqual(ctx.exception.code, 403)

            # Admin requis : admin, owner passent ; approver et viewer échouent (403)
            if r in ("admin", "owner"):
                m = orgs.require_role(uid, self.org1_id, "admin", db_path=self.db_path)
                self.assertEqual(m["role"], r)
            else:
                with self.assertRaises(orgs.OrgError) as ctx:
                    orgs.require_role(uid, self.org1_id, "admin", db_path=self.db_path)
                self.assertEqual(ctx.exception.code, 403)

            # Owner requis : seul owner passe
            if r == "owner":
                m = orgs.require_role(uid, self.org1_id, "owner", db_path=self.db_path)
                self.assertEqual(m["role"], r)
            else:
                with self.assertRaises(orgs.OrgError) as ctx:
                    orgs.require_role(uid, self.org1_id, "owner", db_path=self.db_path)
                self.assertEqual(ctx.exception.code, 403)

        # Utilisateur étranger (non membre) : renvoie toujours 404 (anti-IDOR)
        for req_role in ("viewer", "approver", "admin", "owner"):
            with self.assertRaises(orgs.OrgError) as ctx:
                orgs.require_role(self.u_stranger, self.org1_id, req_role, db_path=self.db_path)
            self.assertEqual(ctx.exception.code, 404)

    def test_last_owner_cannot_be_demoted_or_removed(self):
        """On ne peut pas retirer ou rétrograder le dernier owner."""
        # 1. Rétrograder l'owner unique -> 400
        with self.assertRaises(orgs.OrgError) as ctx:
            orgs.change_member_role(self.org1_id, self.u_owner, "m_a", "admin", db_path=self.db_path)
        self.assertEqual(ctx.exception.code, 400)
        self.assertIn("dernier propriétaire", ctx.exception.message)

        # 2. Supprimer l'owner unique -> 400
        with self.assertRaises(orgs.OrgError) as ctx:
            orgs.remove_member(self.org1_id, self.u_owner, "m_a", db_path=self.db_path)
        self.assertEqual(ctx.exception.code, 400)
        self.assertIn("dernier propriétaire", ctx.exception.message)

        # 3. Nommer un second owner par l'owner
        orgs.change_member_role(self.org1_id, self.u_owner, "m_b", "owner", db_path=self.db_path)

        # Maintenant il y a 2 owners : on peut rétrograder m_a
        res = orgs.change_member_role(self.org1_id, self.u_owner, "m_a", "admin", db_path=self.db_path)
        self.assertEqual(res["role"], "admin")

        # Reste 1 seul owner (m_b) : impossible de le rétrograder
        with self.assertRaises(orgs.OrgError) as ctx:
            orgs.change_member_role(self.org1_id, self.u_admin, "m_b", "viewer", db_path=self.db_path)
        self.assertEqual(ctx.exception.code, 400)

    def test_only_owner_can_nominate_owner(self):
        """Seul le propriétaire peut nommer un propriétaire ou inviter comme propriétaire."""
        # Admin tente de promouvoir un membre en owner -> 403
        with self.assertRaises(orgs.OrgError) as ctx:
            orgs.change_member_role(self.org1_id, self.u_admin, "m_d", "owner", db_path=self.db_path)
        self.assertEqual(ctx.exception.code, 403)
        self.assertIn("Seul le propriétaire", ctx.exception.message)

        # Admin tente d'inviter un nouveau propriétaire -> 403
        with self.assertRaises(orgs.OrgError) as ctx:
            orgs.invite_member(self.org1_id, self.u_admin, "new_owner@test.com", "owner", db_path=self.db_path)
        self.assertEqual(ctx.exception.code, 403)

        # L'owner peut promouvoir et inviter en owner
        inv = orgs.invite_member(self.org1_id, self.u_owner, "new_owner@test.com", "owner", db_path=self.db_path)
        self.assertEqual(inv["role"], "owner")

    def test_suspended_organization_is_read_only(self):
        """Une organisation suspendue est en lecture seule absolue."""
        db.execute("UPDATE orgs SET is_suspended = 1 WHERE id = ?;", (self.org1_id,), db_path=self.db_path)

        # Les lectures passent
        ov = orgs.get_overview(self.org1_id, db_path=self.db_path)
        self.assertTrue(ov["org"]["is_suspended"])
        self.assertEqual(ov["org"]["status"], "suspended")
        self.assertIsInstance(orgs.list_payments(self.org1_id, db_path=self.db_path), list)
        self.assertIsInstance(orgs.list_suppliers(self.org1_id, db_path=self.db_path), list)
        self.assertIsInstance(orgs.get_policy(self.org1_id, db_path=self.db_path), dict)
        self.assertIsInstance(orgs.get_audit_trail(self.org1_id, db_path=self.db_path), list)
        self.assertIsInstance(orgs.list_members(self.org1_id, db_path=self.db_path), list)

        # Toute action d'écriture échoue avec 403
        with self.assertRaises(orgs.OrgError) as ctx:
            orgs.add_supplier(self.org1_id, self.u_owner, "Sup", "0x0000000000000000000000000000000000000001", db_path=self.db_path)
        self.assertEqual(ctx.exception.code, 403)
        self.assertIn("suspendue", ctx.exception.message)

        with self.assertRaises(orgs.OrgError) as ctx:
            orgs.update_policy(self.org1_id, self.u_owner, max_tx_gwei=100, db_path=self.db_path)
        self.assertEqual(ctx.exception.code, 403)

        with self.assertRaises(orgs.OrgError) as ctx:
            orgs.create_api_key(self.org1_id, self.u_owner, "Agent 1", db_path=self.db_path)
        self.assertEqual(ctx.exception.code, 403)

    def test_supplier_activation_delay(self):
        """Un fournisseur ajouté n'est payable qu'après activation_delay."""
        addr = "0xd92B1525628baA7AB228796FD49304Ef1435a234"
        sup = orgs.add_supplier(self.org1_id, self.u_admin, "Fournisseur A", addr, db_path=self.db_path)
        self.assertFalse(sup["is_payable"])
        self.assertGreater(sup["remaining_seconds"], 0)

        # Vérification dans la liste
        sups = orgs.list_suppliers(self.org1_id, db_path=self.db_path)
        self.assertEqual(len(sups), 1)
        self.assertFalse(sups[0]["is_payable"])

        # Avancement dans le temps : le délai est écoulé
        db.execute("UPDATE suppliers SET active_after = ? WHERE id = ?;", (self.now - 10, sup["id"]), db_path=self.db_path)
        sups_after = orgs.list_suppliers(self.org1_id, db_path=self.db_path)
        self.assertTrue(sups_after[0]["is_payable"])
        self.assertEqual(sups_after[0]["remaining_seconds"], 0)

    def test_audit_chain_tamper_detection(self):
        """Une altération ou rupture dans la chaîne d'audit est détectée."""
        auth.log_audit("test.action_1", org_id=self.org1_id, user_id=self.u_owner, db_path=self.db_path)
        auth.log_audit("test.action_2", org_id=self.org1_id, user_id=self.u_admin, db_path=self.db_path)
        auth.log_audit("test.action_3", org_id=self.org1_id, user_id=self.u_viewer, db_path=self.db_path)

        res = orgs.verify_audit_chain(db_path=self.db_path)
        self.assertTrue(res["valid"])
        self.assertEqual(res["count"], 3)

        # Altération d'une ligne (simulation de corruption de fichier)
        db.execute("DROP TRIGGER IF EXISTS audit_no_update;", db_path=self.db_path)
        db.execute("UPDATE audit SET details_json = '{\"falsified\": true}' WHERE id = 2;", db_path=self.db_path)

        tampered = orgs.verify_audit_chain(db_path=self.db_path)
        self.assertFalse(tampered["valid"])
        self.assertEqual(tampered["tampered_id"], 2)
        self.assertIn("Altération détectée", tampered["message"])

    def test_audit_csv_cwe_1236_protection(self):
        """L'export CSV neutralise toute formule malveillante (CWE-1236)."""
        auth.log_audit("test.formula", org_id=self.org1_id, user_id=self.u_owner,
                       details={"cmd": "=1+1"}, db_path=self.db_path)
        csv_out = orgs.export_audit_csv(self.org1_id, db_path=self.db_path)
        # La cellule ne doit pas commencer par = directement
        self.assertNotIn("\n=1+1", csv_out)
        self.assertIn("test.formula", csv_out)

    # ---- Non-régression : failles trouvées lors de la revue de l'étape 3

    def test_update_settings_works(self):
        """Modifier le nom de l'organisation ne plante pas (NameError) et est journalisé."""
        res = orgs.update_settings(self.org1_id, self.u_admin, name="Alpha Renommée", db_path=self.db_path)
        self.assertEqual(res["name"], "Alpha Renommée")

    def test_policy_cannot_disable_defenses(self):
        """Un admin (compte volé) ne peut ni annuler le délai d'activation ni le disjoncteur."""
        for kwargs in ({"activation_delay": 0}, {"circuit_breaker_limit": 0}, {"activation_delay": 10**9}):
            with self.assertRaises(orgs.OrgError) as ctx:
                orgs.update_policy(self.org1_id, self.u_admin, db_path=self.db_path, **kwargs)
            self.assertEqual(ctx.exception.code, 400)

    def test_policy_amounts_bounded_and_coherent(self):
        """Montant géant (dépassement d'entier) -> 400 propre ; seuil > plafond refusé ; 1 000 AVAX accepté."""
        with self.assertRaises(orgs.OrgError):
            orgs.update_policy(self.org1_id, self.u_admin, max_tx_gwei=2**70, db_path=self.db_path)
        with self.assertRaises(orgs.OrgError):
            orgs.update_policy(self.org1_id, self.u_admin, human_threshold_gwei=10**12, db_path=self.db_path)
        pol = orgs.update_policy(self.org1_id, self.u_admin, max_daily_gwei=10**12, max_tx_gwei=10**12,
                                 db_path=self.db_path)
        self.assertEqual(pol["max_tx_gwei"], 10**12)  # 1 000 AVAX, impossible à stocker en wei

    def test_supplier_address_case_insensitive(self):
        """La même adresse en MAJUSCULES n'est pas un nouveau fournisseur (pas de contournement du délai)."""
        orgs.add_supplier(self.org1_id, self.u_admin, "A", "0x" + "ab" * 20, db_path=self.db_path)
        with self.assertRaises(orgs.OrgError) as ctx:
            orgs.add_supplier(self.org1_id, self.u_admin, "B", "0x" + "AB" * 20, db_path=self.db_path)
        self.assertEqual(ctx.exception.code, 409)

    def test_payment_approved_only_once_under_concurrency(self):
        """10 validations simultanées du même paiement : une seule réussit."""
        db.execute("INSERT INTO payments (id, org_id, recipient, amount_gwei, decision, created_at, updated_at) "
                   "VALUES ('p_race', ?, '0x1', 1, 'pending_review', ?, ?);",
                   (self.org1_id, self.now, self.now), db_path=self.db_path)
        ok = []

        def w():
            try:
                orgs.approve_payment(self.org1_id, self.u_approver, "p_race", db_path=self.db_path)
                ok.append(1)
            except orgs.OrgError:
                pass
            db.close_all()
        ts = [threading.Thread(target=w) for _ in range(10)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(len(ok), 1)
        n = db.query_one("SELECT COUNT(*) c FROM audit WHERE action = 'payment.approve';", db_path=self.db_path)["c"]
        self.assertEqual(n, 1)

    def test_org_integrity_check_leaks_nothing_about_other_orgs(self):
        """La vérification d'intégrité ne donne que les chiffres de l'organisation qui la demande."""
        for _ in range(5):
            auth.log_audit("beta.secret", org_id=self.org2_id, db_path=self.db_path)
        auth.log_audit("alpha.one", org_id=self.org1_id, db_path=self.db_path)
        before = db.query_one("SELECT COUNT(*) c FROM audit WHERE org_id = ?;", (self.org1_id,), db_path=self.db_path)["c"]
        res = orgs.verify_audit_chain_for_org(self.org1_id, db_path=self.db_path)
        self.assertTrue(res["valid"])
        self.assertEqual(res["count"], before)
        # Altération d'une ligne d'une AUTRE organisation : on signale, sans donner son identifiant.
        db.execute("DROP TRIGGER IF EXISTS audit_no_update;", db_path=self.db_path)
        db.execute("UPDATE audit SET details_json = '{\"x\":1}' WHERE action = 'beta.secret';", db_path=self.db_path)
        res = orgs.verify_audit_chain_for_org(self.org1_id, db_path=self.db_path)
        self.assertFalse(res["valid"])
        self.assertNotIn("tampered_id", res)


class TestAppServerHTTP(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import server
        cls.server = server
        cls.tmp_dir = tempfile.mkdtemp(prefix="vg_http_app_test_")
        cls.db_path = os.path.join(cls.tmp_dir, "test.db")
        os.environ["DB_PATH"] = cls.db_path
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
        shutil.rmtree(cls.tmp_dir, ignore_errors=True)

    def _req(self, method, path, body=None, cookie="", csrf="", headers=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Host": "localhost"}
        if cookie:
            h["Cookie"] = cookie
        if csrf:
            h["X-CSRF-Token"] = csrf
        if body is not None:
            h["Content-Type"] = "application/json"
            data = json.dumps(body).encode()
        else:
            data = None
        if headers:
            h.update(headers)
        c.request(method, path, body=data, headers=h)
        r = c.getresponse()
        payload = r.read()
        sc = r.getheader("Set-Cookie")
        cookie_out = sc.split(";")[0] if sc else cookie
        c.close()
        try:
            parsed = json.loads(payload)
        except Exception:
            parsed = payload
        return r.status, parsed, cookie_out, r

    def _get_csrf(self, cookie=""):
        status, data, new_cookie, _ = self._req("GET", "/api/session", cookie=cookie)
        return data["csrf"], new_cookie

    def test_http_full_app_lifecycle_and_roles(self):
        """Cycle complet sur /api/app/* : matrice des rôles et actions autorisées/interdites."""
        self.server.LIMITER._b.clear()

        # 1. Inscription Owner Org A
        csrf, cookie = self._get_csrf()
        s_res = self._req("POST", "/api/auth/signup",
                          {"email": "owner_a@alpha.local", "password": "PassphraseSecure123!", "org_name": "Alpha Corp"},
                          cookie=cookie, csrf=csrf)
        self.assertEqual(s_res[0], 201)
        owner_cookie = s_res[2]
        owner_csrf = s_res[1]["csrf"]
        org_a_id = s_res[1]["org"]["id"]

        # 2. Invitation d'un approver et d'un viewer pour Org A
        inv_approver = self._req("POST", "/api/app/team/invites",
                                 {"email": "approver_a@alpha.local", "role": "approver"},
                                 cookie=owner_cookie, csrf=owner_csrf)
        self.assertEqual(inv_approver[0], 201)
        token_appr = inv_approver[1]["token"]

        inv_viewer = self._req("POST", "/api/app/team/invites",
                               {"email": "viewer_a@alpha.local", "role": "viewer"},
                               cookie=owner_cookie, csrf=owner_csrf)
        self.assertEqual(inv_viewer[0], 201)
        token_view = inv_viewer[1]["token"]

        # Inscription de l'approver et du viewer
        csrf_a, c_a = self._get_csrf()
        res_a = self._req("POST", "/api/auth/signup",
                          {"email": "approver_a@alpha.local", "password": "PassphraseSecure123!", "invite_token": token_appr},
                          cookie=c_a, csrf=csrf_a)
        self.assertEqual(res_a[0], 201)
        appr_cookie, appr_csrf = res_a[2], res_a[1]["csrf"]

        csrf_v, c_v = self._get_csrf()
        res_v = self._req("POST", "/api/auth/signup",
                          {"email": "viewer_a@alpha.local", "password": "PassphraseSecure123!", "invite_token": token_view},
                          cookie=c_v, csrf=csrf_v)
        self.assertEqual(res_v[0], 201)
        view_cookie, view_csrf = res_v[2], res_v[1]["csrf"]

        # 3. Création d'un paiement en attente dans Org A
        now = int(time.time())
        db.execute("INSERT INTO payments (id, org_id, recipient, amount_gwei, decision, memo, created_at, updated_at) "
                   "VALUES ('pay_alpha_1', ?, '0xd92B1525628baA7AB228796FD49304Ef1435a234', 50000000, 'pending_review', 'Test', ?, ?);",
                   (org_a_id, now, now), db_path=self.db_path)

        # 4. Actions par rôle :
        # Viewer tente d'approuver -> 403
        st, _, _, _ = self._req("POST", "/api/app/payments/approve", {"id": "pay_alpha_1"}, cookie=view_cookie, csrf=view_csrf)
        self.assertEqual(st, 403)

        # Viewer tente d'ajouter un fournisseur -> 403
        st, _, _, _ = self._req("POST", "/api/app/suppliers", {"name": "Sup", "address": "0xd92B1525628baA7AB228796FD49304Ef1435a234"}, cookie=view_cookie, csrf=view_csrf)
        self.assertEqual(st, 403)

        # Approver tente d'ajouter un fournisseur -> 403
        st, _, _, _ = self._req("POST", "/api/app/suppliers", {"name": "Sup", "address": "0xd92B1525628baA7AB228796FD49304Ef1435a234"}, cookie=appr_cookie, csrf=appr_csrf)
        self.assertEqual(st, 403)

        # Approver approuve le paiement -> 200 OK
        st, appr_res, _, _ = self._req("POST", "/api/app/payments/approve", {"id": "pay_alpha_1"}, cookie=appr_cookie, csrf=appr_csrf)
        self.assertEqual(st, 200)
        self.assertEqual(appr_res["decision"], "allowed")

        # Owner ajoute un fournisseur -> 201
        st, sup_res, _, _ = self._req("POST", "/api/app/suppliers", {"name": "Sup", "address": "0xd92B1525628baA7AB228796FD49304Ef1435a234"}, cookie=owner_cookie, csrf=owner_csrf)
        self.assertEqual(st, 201)

        # Owner modifie la politique financière (montants wei) -> 200
        st, pol_res, _, _ = self._req("POST", "/api/app/policy", {"max_tx_gwei": 200000000, "circuit_breaker_limit": 8}, cookie=owner_cookie, csrf=owner_csrf)
        self.assertEqual(st, 200)
        self.assertEqual(pol_res["max_tx_gwei"], 200000000)
        self.assertEqual(pol_res["circuit_breaker_limit"], 8)

        # Owner crée une clé API agent -> 201 (clé affichée une seule fois)
        st, key_res, _, _ = self._req("POST", "/api/app/api-keys", {"name": "Facturation Agent"}, cookie=owner_cookie, csrf=owner_csrf)
        self.assertEqual(st, 201)
        self.assertTrue(key_res["raw_key"].startswith("vg_live_"))

        # Vérification d'intégrité du journal d'audit -> 200
        st, v_res, _, _ = self._req("POST", "/api/app/audit/verify", {}, cookie=owner_cookie, csrf=owner_csrf)
        self.assertEqual(st, 200)
        self.assertTrue(v_res["valid"])

    def test_http_anti_idor_complete_isolation_all_routes(self):
        """Anti-IDOR strict : toute ressource d'une autre organisation renvoie 404 (jamais 403)."""
        self.server.LIMITER._b.clear()

        # 1. Inscription Org A (Alice)
        csrf_a, c_a = self._get_csrf()
        res_a = self._req("POST", "/api/auth/signup",
                          {"email": "alice_idor@alpha.local", "password": "PassphraseSecure123!", "org_name": "Alpha IDOR"},
                          cookie=c_a, csrf=csrf_a)
        self.assertEqual(res_a[0], 201)
        cookie_a, csrf_a = res_a[2], res_a[1]["csrf"]

        # 2. Inscription Org B (Bob)
        csrf_b, c_b = self._get_csrf()
        res_b = self._req("POST", "/api/auth/signup",
                          {"email": "bob_idor@beta.local", "password": "PassphraseSecure123!", "org_name": "Beta IDOR"},
                          cookie=c_b, csrf=csrf_b)
        self.assertEqual(res_b[0], 201)
        cookie_b, csrf_b = res_b[2], res_b[1]["csrf"]
        org_b_id = res_b[1]["org"]["id"]

        # 3. Création de ressources dans Org B
        now = int(time.time())
        db.execute("INSERT INTO payments (id, org_id, recipient, amount_gwei, decision, memo, created_at, updated_at) "
                   "VALUES ('pay_beta_secret', ?, '0xd92B1525628baA7AB228796FD49304Ef1435a234', 100, 'pending_review', 'Secret Beta', ?, ?);",
                   (org_b_id, now, now), db_path=self.db_path)

        sup_res = self._req("POST", "/api/app/suppliers",
                            {"name": "Beta Supplier", "address": "0xd92B1525628baA7AB228796FD49304Ef1435a234"},
                            cookie=cookie_b, csrf=csrf_b)
        self.assertEqual(sup_res[0], 201)
        sup_beta_id = sup_res[1]["id"]

        key_res = self._req("POST", "/api/app/api-keys", {"name": "Beta Agent"}, cookie=cookie_b, csrf=csrf_b)
        self.assertEqual(key_res[0], 201)
        key_beta_id = key_res[1]["id"]

        inv_res = self._req("POST", "/api/app/team/invites", {"email": "invite_beta@test.com", "role": "viewer"},
                            cookie=cookie_b, csrf=csrf_b)
        self.assertEqual(inv_res[0], 201)
        inv_beta_id = inv_res[1]["id"]

        # Récupération de l'ID du membre Bob dans Org B
        member_b_row = db.query_one("SELECT id FROM members WHERE org_id = ?;", (org_b_id,), db_path=self.db_path)
        member_beta_id = member_b_row["id"]

        # 4. ALICE (Org A) tente d'accéder aux ressources de BOB (Org B) -> 404 SUR TOUTES LES ROUTES
        # Lire le paiement de B
        st, _, _, _ = self._req("GET", "/api/app/payments/pay_beta_secret", cookie=cookie_a)
        self.assertEqual(st, 404)

        # Valider le paiement de B
        st, _, _, _ = self._req("POST", "/api/app/payments/approve", {"id": "pay_beta_secret"}, cookie=cookie_a, csrf=csrf_a)
        self.assertEqual(st, 404)

        # Rejeter le paiement de B
        st, _, _, _ = self._req("POST", "/api/app/payments/reject", {"id": "pay_beta_secret"}, cookie=cookie_a, csrf=csrf_a)
        self.assertEqual(st, 404)

        # Supprimer le fournisseur de B
        st, _, _, _ = self._req("POST", "/api/app/suppliers/remove", {"id": sup_beta_id}, cookie=cookie_a, csrf=csrf_a)
        self.assertEqual(st, 404)

        # Révoquer la clé API de B
        st, _, _, _ = self._req("POST", "/api/app/api-keys/revoke", {"id": key_beta_id}, cookie=cookie_a, csrf=csrf_a)
        self.assertEqual(st, 404)

        # Modifier le rôle du membre de B
        st, _, _, _ = self._req("POST", "/api/app/team/members/role", {"member_id": member_beta_id, "role": "viewer"}, cookie=cookie_a, csrf=csrf_a)
        self.assertEqual(st, 404)

        # Retirer le membre de B
        st, _, _, _ = self._req("POST", "/api/app/team/members/remove", {"member_id": member_beta_id}, cookie=cookie_a, csrf=csrf_a)
        self.assertEqual(st, 404)

        # Révoquer l'invitation de B
        st, _, _, _ = self._req("POST", "/api/app/team/invites/revoke", {"invite_id": inv_beta_id}, cookie=cookie_a, csrf=csrf_a)
        self.assertEqual(st, 404)

        # Basculer vers Org B sans en être membre
        st, _, _, _ = self._req("POST", "/api/app/orgs/switch", {"org_id": org_b_id}, cookie=cookie_a, csrf=csrf_a)
        self.assertEqual(st, 404)

        # Le journal d'audit de A ne contient rien de B
        st, audit_a, _, _ = self._req("GET", "/api/app/audit", cookie=cookie_a)
        self.assertEqual(st, 200)
        for entry in audit_a:
            self.assertNotEqual(entry["org_id"], org_b_id)

    def test_http_suspended_org_read_only(self):
        """Organisation suspendue via HTTP : consultation 200, toutes mutations 403."""
        self.server.LIMITER._b.clear()
        csrf, cookie = self._get_csrf()
        res = self._req("POST", "/api/auth/signup",
                        {"email": "owner_susp@test.local", "password": "PassphraseSecure123!", "org_name": "Suspended Org"},
                        cookie=cookie, csrf=csrf)
        self.assertEqual(res[0], 201)
        cookie, csrf = res[2], res[1]["csrf"]
        org_id = res[1]["org"]["id"]

        # Suspension de l'organisation
        db.execute("UPDATE orgs SET is_suspended = 1 WHERE id = ?;", (org_id,), db_path=self.db_path)

        # Lectures : 200 OK
        st, _, _, _ = self._req("GET", "/api/app/overview", cookie=cookie)
        self.assertEqual(st, 200)
        st, _, _, _ = self._req("GET", "/api/app/payments", cookie=cookie)
        self.assertEqual(st, 200)
        st, _, _, _ = self._req("GET", "/api/app/policy", cookie=cookie)
        self.assertEqual(st, 200)

        # Écritures : 403 Forbidden
        st, _, _, _ = self._req("POST", "/api/app/suppliers",
                                {"name": "Test", "address": "0xd92B1525628baA7AB228796FD49304Ef1435a234"},
                                cookie=cookie, csrf=csrf)
        self.assertEqual(st, 403)

        st, _, _, _ = self._req("POST", "/api/app/policy", {"max_tx_gwei": 100}, cookie=cookie, csrf=csrf)
        self.assertEqual(st, 403)

        st, _, _, _ = self._req("POST", "/api/app/api-keys", {"name": "Agent"}, cookie=cookie, csrf=csrf)
        self.assertEqual(st, 403)

    def test_http_static_assets_and_csp(self):
        """Vérifie la mise à disposition des pages et fichiers statiques sécurisés."""
        self.server.LIMITER._b.clear()

        # /app
        st, body, _, r = self._req("GET", "/app")
        self.assertEqual(st, 200)
        self.assertTrue(r.getheader("Content-Type").startswith("text/html"))
        csp = r.getheader("Content-Security-Policy")
        self.assertIn("script-src 'nonce-", csp)
        self.assertIn("'self'", csp)

        # /login et /signup
        st, _, _, r = self._req("GET", "/login")
        self.assertEqual(st, 200)
        self.assertTrue(r.getheader("Content-Type").startswith("text/html"))

        st, _, _, r = self._req("GET", "/signup")
        self.assertEqual(st, 200)
        self.assertTrue(r.getheader("Content-Type").startswith("text/html"))

        # /app.css et /app.js
        st, _, _, r = self._req("GET", "/app.css")
        self.assertEqual(st, 200)
        self.assertTrue(r.getheader("Content-Type").startswith("text/css"))

        st, _, _, r = self._req("GET", "/app.js")
        self.assertEqual(st, 200)
        self.assertTrue(r.getheader("Content-Type").startswith("application/javascript"))


if __name__ == "__main__":
    unittest.main()


