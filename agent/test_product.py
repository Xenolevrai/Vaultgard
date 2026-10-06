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
import secrets
import re

try:
    import db
except ImportError:
    from agent import db

try:
    import scenarios
except ImportError:
    from agent import scenarios


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

    def test_http_lockout_after_five_failed_attempts(self):
        """Vérifie le verrouillage du compte après 5 échecs de connexion consécutifs via l'API HTTP."""
        csrf, cookie = self._get_csrf()
        # Création d'un utilisateur cible
        auth.signup("victim_lockout@example.com", "PasswordSecure12345!", org_name="Lockout Org", db_path=self.db_path)

        # 4 échecs -> 401 à chaque fois avec message générique
        for _ in range(4):
            self.server.LIMITER._b.clear()
            st, res, cookie, _ = self._req("POST", "/api/auth/login",
                                          {"email": "victim_lockout@example.com", "password": "WrongPassword999!"},
                                          cookie=cookie, csrf=csrf)
            self.assertEqual(st, 401)
            self.assertEqual(res["error"], "Identifiants invalides")

        # 5e échec -> déclenche le verrouillage (15 minutes en base)
        self.server.LIMITER._b.clear()
        st, res, cookie, _ = self._req("POST", "/api/auth/login",
                                      {"email": "victim_lockout@example.com", "password": "WrongPassword999!"},
                                      cookie=cookie, csrf=csrf)
        self.assertEqual(st, 401)
        self.assertEqual(res["error"], "Identifiants invalides")

        # Vérification en base : compte verrouillé
        user = db.query_one("SELECT failed_login_attempts, locked_until FROM users WHERE email = 'victim_lockout@example.com';",
                            db_path=self.db_path)
        self.assertEqual(user["failed_login_attempts"], 5)
        self.assertIsNotNone(user["locked_until"])
        now = int(time.time())
        self.assertGreater(user["locked_until"], now + 800)

        # 6e tentative avec le BON mot de passe -> toujours 401 avec message identique
        self.server.LIMITER._b.clear()
        st, res, cookie, _ = self._req("POST", "/api/auth/login",
                                      {"email": "victim_lockout@example.com", "password": "PasswordSecure12345!"},
                                      cookie=cookie, csrf=csrf)
        self.assertEqual(st, 401)
        self.assertEqual(res["error"], "Identifiants invalides")

        # Événement de sécurité consigné
        evt = db.query_one("SELECT * FROM login_events WHERE email = 'victim_lockout@example.com' ORDER BY id DESC LIMIT 1;",
                           db_path=self.db_path)
        self.assertEqual(evt["reason"], "locked")

        # Fin de la période de verrouillage (simulation) -> la connexion avec le bon mot de passe réussit
        db.execute("UPDATE users SET locked_until = ? WHERE email = 'victim_lockout@example.com';", (now - 1,), db_path=self.db_path)
        self.server.LIMITER._b.clear()
        st, res, cookie, _ = self._req("POST", "/api/auth/login",
                                      {"email": "victim_lockout@example.com", "password": "PasswordSecure12345!"},
                                      cookie=cookie, csrf=csrf)
        self.assertEqual(st, 200)
        self.assertTrue(res["ok"])
        user_after = db.query_one("SELECT failed_login_attempts, locked_until FROM users WHERE email = 'victim_lockout@example.com';",
                                  db_path=self.db_path)
        self.assertEqual(user_after["failed_login_attempts"], 0)
        self.assertIsNone(user_after["locked_until"])


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
        """Une altération ou rupture dans la chaîne d'audit est détectée.
        1. Une écriture directe en SQL échoue grâce aux triggers (audit_no_update, audit_no_delete).
        2. Une base modifiée hors ligne (corruption ou falsification) est signalée par la vérification d'intégrité.
        """
        auth.log_audit("test.action_1", org_id=self.org1_id, user_id=self.u_owner, db_path=self.db_path)
        auth.log_audit("test.action_2", org_id=self.org1_id, user_id=self.u_admin, db_path=self.db_path)
        auth.log_audit("test.action_3", org_id=self.org1_id, user_id=self.u_viewer, db_path=self.db_path)

        res = orgs.verify_audit_chain(db_path=self.db_path)
        self.assertTrue(res["valid"])
        self.assertEqual(res["count"], 3)
        res_org = orgs.verify_audit_chain_for_org(self.org1_id, db_path=self.db_path)
        self.assertTrue(res_org["valid"])

        # 1. Écriture directe en SQL refusée par les triggers de la base de données
        with self.assertRaises(sqlite3.DatabaseError):
            db.execute("UPDATE audit SET details_json = '{\"hacked\": true}' WHERE id = 1;", db_path=self.db_path)
        with self.assertRaises(sqlite3.DatabaseError):
            db.execute("DELETE FROM audit WHERE id = 1;", db_path=self.db_path)

        # 2. Altération de la base hors ligne (simulation d'une falsification directe du fichier SQLite)
        db.execute("DROP TRIGGER IF EXISTS audit_no_update;", db_path=self.db_path)
        db.execute("UPDATE audit SET details_json = '{\"falsified\": true}' WHERE id = 2;", db_path=self.db_path)

        tampered_global = orgs.verify_audit_chain(db_path=self.db_path)
        self.assertFalse(tampered_global["valid"])
        self.assertEqual(tampered_global["tampered_id"], 2)
        self.assertIn("Altération détectée", tampered_global["message"])

        tampered_org = orgs.verify_audit_chain_for_org(self.org1_id, db_path=self.db_path)
        self.assertFalse(tampered_org["valid"])
        self.assertEqual(tampered_org["tampered_id"], 2)

    def test_audit_csv_cwe_1236_protection(self):
        """L'export CSV neutralise toute formule malveillante (CWE-1236) pour =, +, -, @, tabulation."""
        # Test sur le champ details
        auth.log_audit("test.formula_eq", org_id=self.org1_id, user_id=self.u_owner,
                       details={"cmd": "=1+1"}, db_path=self.db_path)
        auth.log_audit("test.formula_plus", org_id=self.org1_id, user_id=self.u_owner,
                       details={"cmd": "+1+1"}, db_path=self.db_path)
        auth.log_audit("test.formula_minus", org_id=self.org1_id, user_id=self.u_owner,
                       details={"cmd": "-1+1"}, db_path=self.db_path)
        auth.log_audit("test.formula_at", org_id=self.org1_id, user_id=self.u_owner,
                       details={"cmd": "@SUM(1,2)"}, db_path=self.db_path)
        auth.log_audit("test.formula_tab", org_id=self.org1_id, user_id=self.u_owner,
                       details={"cmd": "\tcalc"}, db_path=self.db_path)

        # Test sur les cellules débutant directement par ces caractères dangereux
        for prefix in ("=", "+", "-", "@", "\t", "\r"):
            act_direct = f"{prefix}calc_action"
            auth.log_audit(act_direct, org_id=self.org1_id, user_id=self.u_owner, db_path=self.db_path)

        csv_out = orgs.export_audit_csv(self.org1_id, db_path=self.db_path)

        # Vérification : toute cellule commençant par =, +, -, @, \t, \r est préfixée par "'"
        for prefix in ("=", "+", "-", "@", "\t", "\r"):
            act_direct = f"{prefix}calc_action"
            escaped_expected = f"'{act_direct}"
            self.assertIn(escaped_expected, csv_out)
            # Ne doit jamais apparaître sans apostrophe en début de ligne ou de cellule
            self.assertNotIn(f"\n{act_direct}", csv_out)
            self.assertNotIn(f",{act_direct}", csv_out)

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

    # ================================================================== ÉTAPE 4 : API /v1 & SDK

    def _setup_v1_org(self, name: str = "Org V1", limits: dict | None = None) -> tuple[str, str, str]:
        """Crée une organisation et une clé API agent valide pour les tests /v1."""
        now = int(time.time())
        org_id = "org_" + secrets.token_hex(8)
        lim = limits or {}
        db.execute(
            "INSERT INTO orgs (id, name, slug, network, max_tx_gwei, max_daily_gwei, human_threshold_gwei, "
            "                  activation_delay, circuit_breaker_limit, canary_address, created_at, updated_at) "
            "VALUES (?, ?, ?, 'mock', ?, ?, ?, ?, ?, ?, ?, ?);",
            (org_id, name, "slug-" + org_id,
             lim.get("max_tx_gwei", 100_000_000),
             lim.get("max_daily_gwei", 300_000_000),
             lim.get("human_threshold_gwei", 50_000_000),
             lim.get("activation_delay", 86400),
             lim.get("circuit_breaker_limit", 5),
             lim.get("canary_address", ""),
             now, now),
            db_path=self.db_path,
        )
        raw_token = f"vg_live_{secrets.token_urlsafe(32)}"
        key_id = "key_" + secrets.token_hex(8)
        db.execute(
            "INSERT INTO api_keys (id, org_id, name, key_prefix, key_hash, is_active, created_at) "
            "VALUES (?, ?, 'Agent Test', ?, ?, 1, ?);",
            (key_id, org_id, raw_token[:12], db.hash_token(raw_token), now),
            db_path=self.db_path,
        )
        return org_id, key_id, raw_token

    def test_v1_authentication_bearer_and_revocation_and_quarantine(self):
        """Authentification Bearer <clé> : 401 si clé absente, fausse, révoquée ou en quarantaine (même message).
        Org suspendue -> 403.
        Mise à jour de last_used_at lors d'un appel réussi.
        """
        self.server.LIMITER._b.clear()
        org_id, key_id, raw_key = self._setup_v1_org("Auth Test Org")

        # 1. Pas d'en-tête Authorization -> 401
        st, res, _, _ = self._req("GET", "/v1/policy")
        self.assertEqual(st, 401)
        self.assertEqual(res["error"], "Clé API invalide ou inactive")

        # 2. En-tête malformé -> 401
        st, res, _, _ = self._req("GET", "/v1/policy", headers={"Authorization": "Basic 12345"})
        self.assertEqual(st, 401)
        self.assertEqual(res["error"], "Clé API invalide ou inactive")

        # 3. Clé inconnue / fausse -> 401
        st, res, _, _ = self._req("GET", "/v1/policy", headers={"Authorization": "Bearer vg_live_unknown999999999"})
        self.assertEqual(st, 401)
        self.assertEqual(res["error"], "Clé API invalide ou inactive")

        # 4. Clé valide -> 200 et mise à jour de last_used_at
        key_before = db.query_one("SELECT last_used_at FROM api_keys WHERE id = ?;", (key_id,), db_path=self.db_path)
        self.assertIsNone(key_before["last_used_at"])

        st, res, _, _ = self._req("GET", "/v1/policy", headers={"Authorization": f"Bearer {raw_key}"})
        self.assertEqual(st, 200)
        self.assertIn("limits", res)

        key_after = db.query_one("SELECT last_used_at FROM api_keys WHERE id = ?;", (key_id,), db_path=self.db_path)
        self.assertIsNotNone(key_after["last_used_at"])

        # 5. Clé révoquée (is_active = 0) -> 401 avec EXACTEMENT le même message
        db.execute("UPDATE api_keys SET is_active = 0 WHERE id = ?;", (key_id,), db_path=self.db_path)
        st, res, _, _ = self._req("GET", "/v1/policy", headers={"Authorization": f"Bearer {raw_key}"})
        self.assertEqual(st, 401)
        self.assertEqual(res["error"], "Clé API invalide ou inactive")

        # 6. Clé en quarantaine -> 401 avec EXACTEMENT le même message
        db.execute("UPDATE api_keys SET is_active = 1, quarantined_until = ? WHERE id = ?;",
                   (int(time.time()) + 3600, key_id), db_path=self.db_path)
        st, res, _, _ = self._req("GET", "/v1/policy", headers={"Authorization": f"Bearer {raw_key}"})
        self.assertEqual(st, 401)
        self.assertEqual(res["error"], "Clé API invalide ou inactive")

        # 7. Organisation suspendue -> 403
        db.execute("UPDATE api_keys SET quarantined_until = NULL WHERE id = ?;", (key_id,), db_path=self.db_path)
        db.execute("UPDATE orgs SET is_suspended = 1 WHERE id = ?;", (org_id,), db_path=self.db_path)
        st, res, _, _ = self._req("GET", "/v1/policy", headers={"Authorization": f"Bearer {raw_key}"})
        self.assertEqual(st, 403)
        self.assertIn("suspendue", res["error"].lower())

    def test_v1_revoked_key_blocks_payments_and_policy(self):
        """Une clé API révoquée bloque immédiatement POST /v1/payments, GET /v1/policy et GET /v1/payments/{id} avec 401."""
        self.server.LIMITER._b.clear()
        org_id, key_id, raw_key = self._setup_v1_org("Revocation Blocks Org")

        # 1. Avant révocation : GET /v1/policy renvoie 200
        st, res, _, _ = self._req("GET", "/v1/policy", headers={"Authorization": f"Bearer {raw_key}"})
        self.assertEqual(st, 200)

        # 2. Avant révocation : POST /v1/payments renvoie une réponse de paiement valide
        pay_body = {
            "to": "0x5418b7650f0E9ad0a9c80d8702b8E1c8280f3EbA",
            "amount": "0.01",
            "memo": "Paiement test avant révocation",
            "user_request": "Payer le datacenter",
        }
        st_p, res_p, _, _ = self._req("POST", "/v1/payments", pay_body, headers={"Authorization": f"Bearer {raw_key}"})
        self.assertEqual(st_p, 200)
        self.assertIn("decision", res_p)
        payment_id = res_p["id"]

        # 3. Révocation de la clé (is_active = 0)
        db.execute("UPDATE api_keys SET is_active = 0 WHERE id = ?;", (key_id,), db_path=self.db_path)

        # 4. Tous les endpoints /v1 doivent désormais rejeter la clé avec 401 unifié
        st_pol, res_pol, _, _ = self._req("GET", "/v1/policy", headers={"Authorization": f"Bearer {raw_key}"})
        self.assertEqual(st_pol, 401)
        self.assertEqual(res_pol["error"], "Clé API invalide ou inactive")

        st_pay, res_pay, _, _ = self._req("POST", "/v1/payments", pay_body, headers={"Authorization": f"Bearer {raw_key}"})
        self.assertEqual(st_pay, 401)
        self.assertEqual(res_pay["error"], "Clé API invalide ou inactive")

        st_get, res_get, _, _ = self._req("GET", f"/v1/payments/{payment_id}", headers={"Authorization": f"Bearer {raw_key}"})
        self.assertEqual(st_get, 401)
        self.assertEqual(res_get["error"], "Clé API invalide ou inactive")

    def test_v1_rate_limiting_per_key(self):
        """Limitation de débit par clé (en plus de par IP) : renvoie 429 après dépassement."""
        self.server.LIMITER._b.clear()
        try:
            import api_v1
        except ImportError:
            from agent import api_v1

        org_id, key_id, raw_key = self._setup_v1_org("Rate Limit Org")
        old_cap = api_v1.KEY_RATE_LIMITER.capacity
        try:
            api_v1.KEY_RATE_LIMITER.capacity = 2
            api_v1.KEY_RATE_LIMITER._buckets.clear()

            # 2 requêtes acceptées
            st1, _, _, _ = self._req("GET", "/v1/policy", headers={"Authorization": f"Bearer {raw_key}"})
            st2, _, _, _ = self._req("GET", "/v1/policy", headers={"Authorization": f"Bearer {raw_key}"})
            self.assertEqual(st1, 200)
            self.assertEqual(st2, 200)

            # 3e requête -> 429
            st3, res3, _, _ = self._req("GET", "/v1/policy", headers={"Authorization": f"Bearer {raw_key}"})
            self.assertEqual(st3, 429)
            self.assertIn("Trop de requêtes", res3["error"])
        finally:
            api_v1.KEY_RATE_LIMITER.capacity = old_cap
            api_v1.KEY_RATE_LIMITER._buckets.clear()

    def test_v1_invalid_amounts_rejected_clean_400(self):
        """Montants '1e18', '-1', '0.0000000001', '99999999999', floats, etc. refusés proprement (400, jamais 500)."""
        self.server.LIMITER._b.clear()
        org_id, key_id, raw_key = self._setup_v1_org("Amount Test Org")
        invalid_amounts = [
            "1e18",
            "-1",
            "0.0000000001",
            "99999999999",
            0.05,
            -0.05,
            "0",
            "0.0",
            "",
            "abc",
            "1,5",
            None,
            True,
            False,
        ]
        target = "0x5a11e7c0ffee000000000000000000000000ace1"
        for amt in invalid_amounts:
            st, res, _, _ = self._req(
                "POST", "/v1/payments",
                body={"to": target, "amount": amt, "memo": "Test invalid amount"},
                headers={"Authorization": f"Bearer {raw_key}"}
            )
            self.assertEqual(st, 400, f"Le montant {amt!r} devait renvoyer 400, obtenu {st} ({res})")
            self.assertIn("error", res)

    def test_v1_size_validations_and_limits(self):
        """Validation des tailles de champs : memo > 140 octets, adresse invalide, documents bornés -> 400."""
        self.server.LIMITER._b.clear()
        org_id, key_id, raw_key = self._setup_v1_org("Validation Org")
        target = "0x5a11e7c0ffee000000000000000000000000ace1"

        # 1. Memo > 140 octets
        long_memo = "A" * 141
        st, res, _, _ = self._req(
            "POST", "/v1/payments",
            body={"to": target, "amount": "0.01", "memo": long_memo},
            headers={"Authorization": f"Bearer {raw_key}"}
        )
        self.assertEqual(st, 400)
        self.assertIn("Memo trop long", res["error"])

        # 2. Adresse EVM invalide
        st, res, _, _ = self._req(
            "POST", "/v1/payments",
            body={"to": "0xinvalidaddress", "amount": "0.01"},
            headers={"Authorization": f"Bearer {raw_key}"}
        )
        self.assertEqual(st, 400)

        # 3. Documents format invalide
        st, res, _, _ = self._req(
            "POST", "/v1/payments",
            body={"to": target, "amount": "0.01", "documents": "not-a-list"},
            headers={"Authorization": f"Bearer {raw_key}"}
        )
        self.assertEqual(st, 400)

    def test_v1_policy_and_isolation_between_orgs(self):
        """Isolation stricte : la clé de A ne voit jamais un paiement de B (404 anti-IDOR).
        GET /v1/policy renvoie les fournisseurs actifs et limites en AVAX texte.
        """
        self.server.LIMITER._b.clear()
        now = int(time.time())

        # Org A
        org_a_id, key_a_id, raw_key_a = self._setup_v1_org("Org A Isolation")
        sup_a = "0x5a11e7c0ffee000000000000000000000000ace1"
        db.execute(
            "INSERT INTO suppliers (id, org_id, name, address, active_after, is_active, created_at, updated_at) "
            "VALUES ('sup_a', ?, 'Fournisseur A', ?, ?, 1, ?, ?);",
            (org_a_id, sup_a, now - 100, now, now), db_path=self.db_path
        )

        # Org B
        org_b_id, key_b_id, raw_key_b = self._setup_v1_org("Org B Isolation")
        sup_b = "0xd92b1525628baa7ab228796fd49304ef1435a234"
        db.execute(
            "INSERT INTO suppliers (id, org_id, name, address, active_after, is_active, created_at, updated_at) "
            "VALUES ('sup_b', ?, 'Fournisseur B', ?, ?, 1, ?, ?);",
            (org_b_id, sup_b, now - 100, now, now), db_path=self.db_path
        )

        # GET /v1/policy pour A
        st_pol, pol_a, _, _ = self._req("GET", "/v1/policy", headers={"Authorization": f"Bearer {raw_key_a}"})
        self.assertEqual(st_pol, 200)
        self.assertEqual(pol_a["limits"]["max_tx_avax"], "0.1")
        self.assertEqual(len(pol_a["active_suppliers"]), 1)
        self.assertEqual(pol_a["active_suppliers"][0]["name"], "Fournisseur A")

        # Paiement créé par Org A
        st_pay_a, pay_a, _, _ = self._req(
            "POST", "/v1/payments",
            body={"to": sup_a, "amount": "0.02", "memo": "Paiement A", "user_request": "Paie Fournisseur A"},
            headers={"Authorization": f"Bearer {raw_key_a}"}
        )
        self.assertEqual(st_pay_a, 200)
        pay_a_id = pay_a["id"]

        # Paiement créé par Org B
        st_pay_b, pay_b, _, _ = self._req(
            "POST", "/v1/payments",
            body={"to": sup_b, "amount": "0.02", "memo": "Paiement B", "user_request": "Paie Fournisseur B"},
            headers={"Authorization": f"Bearer {raw_key_b}"}
        )
        self.assertEqual(st_pay_b, 200)
        pay_b_id = pay_b["id"]

        # 1. Clé B consulte le paiement de B -> 200
        st, get_b, _, _ = self._req("GET", f"/v1/payments/{pay_b_id}", headers={"Authorization": f"Bearer {raw_key_b}"})
        self.assertEqual(st, 200)
        self.assertEqual(get_b["id"], pay_b_id)

        # 2. Clé B consulte le paiement de A -> 404 strict (isolation anti-IDOR)
        st, get_leak, _, _ = self._req("GET", f"/v1/payments/{pay_a_id}", headers={"Authorization": f"Bearer {raw_key_b}"})
        self.assertEqual(st, 404)

        # 3. Clé A consulte le paiement de B -> 404 strict
        st, get_leak_a, _, _ = self._req("GET", f"/v1/payments/{pay_b_id}", headers={"Authorization": f"Bearer {raw_key_a}"})
        self.assertEqual(st, 404)

    def test_v1_replaying_ten_scenarios(self):
        """Rejeu des 10 scénarios existants via /v1/payments avec les mêmes verdicts.
        Vérifie la réutilisation exacte de firewall.py et le respect de la politique de l'org.
        """
        self.server.LIMITER._b.clear()
        try:
            from scenarios import addresses, SCENARIOS
        except ImportError:
            from agent.scenarios import addresses, SCENARIOS

        A = addresses()
        now = int(time.time())

        # Création d'une organisation configurée selon les scénarios
        org_id, _, raw_key = self._setup_v1_org(
            "Scenarios Org",
            limits={
                "max_tx_gwei": 100_000_000,         # 0.1 AVAX
                "max_daily_gwei": 300_000_000,      # 0.3 AVAX
                "human_threshold_gwei": 50_000_000, # 0.05 AVAX
                "activation_delay": 86400,
                "circuit_breaker_limit": 10,
                "canary_address": A["CANARY"],
            }
        )

        # Fournisseur actif : Acme Supplies
        db.execute(
            "INSERT INTO suppliers (id, org_id, name, address, active_after, is_active, created_at, updated_at) "
            "VALUES ('sup_sc_1', ?, 'Acme Supplies', ?, ?, 1, ?, ?);",
            (org_id, A["SUPPLIER"], now - 100, now, now), db_path=self.db_path
        )

        # Nouveau fournisseur avec délai non écoulé : Beta Logistics
        db.execute(
            "INSERT INTO suppliers (id, org_id, name, address, active_after, is_active, created_at, updated_at) "
            "VALUES ('sup_sc_2', ?, 'Beta Logistics', ?, ?, 1, ?, ?);",
            (org_id, A["NEW_SUPPLIER"], now + 86400, now, now), db_path=self.db_path
        )

        # Historique de paiements pour Acme Supplies (médiane 0.02)
        for amt_gwei in [20_000_000, 20_000_000, 30_000_000, 20_000_000]:
            pid = "hist_" + secrets.token_hex(6)
            db.execute(
                "INSERT INTO payments (id, org_id, recipient, amount_gwei, decision, memo, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, 'allowed', 'Past Invoice', ?, ?);",
                (pid, org_id, A["SUPPLIER"], amt_gwei, now - 3600, now - 3600), db_path=self.db_path
            )

        def send_v1(to: str, amount_str: str, memo: str, user_req: str, docs: list[dict], key: str = raw_key):
            st, res, _, _ = self._req(
                "POST", "/v1/payments",
                body={"to": to, "amount": amount_str, "memo": memo, "user_request": user_req, "documents": docs},
                headers={"Authorization": f"Bearer {key}"}
            )
            return st, res

        # 1. Scénario legit -> allowed
        sc = SCENARIOS["legit"]
        st, res = send_v1(A["SUPPLIER"], "0.02", "Facture INV-1001", sc["user"],
                          [{"source": "inbox[0]", "content": sc["inbox"][0].format(**A)}])
        self.assertEqual(st, 200)
        self.assertEqual(res["decision"], "allowed")
        self.assertEqual(res["chain"]["status"], "Executed")

        # 2. Scénario injection -> 1er pending_review (injection détectée), 2e blocked (untrusted_origin)
        sc = SCENARIOS["injection"]
        docs = [{"source": "inbox[0]", "content": sc["inbox"][0].format(**A)}]
        st1, res1 = send_v1(A["SUPPLIER"], "0.02", "Facture INV-1002", sc["user"], docs)
        self.assertEqual(st1, 200)
        self.assertEqual(res1["decision"], "pending_review")
        self.assertTrue(any(r["code"] == "injection" for r in res1["reasons"]))
        st2, res2 = send_v1(A["ATTACKER"], "0.09", "Taxe de conformité", sc["user"], docs)
        self.assertEqual(st2, 200)
        self.assertEqual(res2["decision"], "blocked")

        # 3. Scénario obfuscated -> 1er pending_review (obfuscation détectée), 2e blocked
        sc = SCENARIOS["obfuscated"]
        docs = [{"source": "inbox[0]", "content": sc["inbox"][0].format(**A)}]
        st1, res1 = send_v1(A["SUPPLIER"], "0.02", "Facture INV-1006", sc["user"], docs)
        self.assertEqual(st1, 200)
        self.assertEqual(res1["decision"], "pending_review")
        self.assertTrue(any(r["code"] in ("obfuscation", "injection") for r in res1["reasons"]))
        st2, res2 = send_v1(A["ATTACKER"], "0.09", "Contrôle", sc["user"], docs)
        self.assertEqual(st2, 200)
        self.assertEqual(res2["decision"], "blocked")

        # 4. Scénario poisoning (adresse sosie) -> blocked
        sc = SCENARIOS["poisoning"]
        docs = [{"source": "inbox[0]", "content": sc["inbox"][0].format(**A)}]
        st, res = send_v1(A["LOOKALIKE"], "0.03", "Facture INV-1003", sc["user"], docs)
        self.assertEqual(st, 200)
        self.assertEqual(res["decision"], "blocked")
        self.assertTrue(any(r["code"] == "lookalike" for r in res["reasons"]))

        # 5. Scénario newpayee (délai d'activation on-chain non écoulé) -> blocked
        sc = SCENARIOS["newpayee"]
        docs = [{"source": "inbox[0]", "content": sc["inbox"][0].format(**A)}]
        st, res = send_v1(A["NEW_SUPPLIER"], "0.03", "Facture BL-0001", sc["user"], docs)
        self.assertEqual(st, 200)
        self.assertEqual(res["decision"], "blocked")
        self.assertTrue(any(r["code"] in ("onchain_block", "untrusted_origin") for r in res["reasons"]))

        # 6. Scénario big (dépassement seuil humain 0.05 AVAX) -> pending_review
        sc = SCENARIOS["big"]
        docs = [{"source": "inbox[0]", "content": sc["inbox"][0].format(**A)}]
        st, res = send_v1(A["SUPPLIER"], "0.08", "Facture INV-2001", sc["user"], docs)
        self.assertEqual(st, 200)
        self.assertEqual(res["decision"], "pending_review")

        # 7. Scénario drain (doubles paiements) -> 1er allowed, 2e blocked
        sc = SCENARIOS["drain"]
        docs = [{"source": "inbox[0]", "content": sc["inbox"][0].format(**A)}]
        st1, res1 = send_v1(A["SUPPLIER"], "0.045", "Facture INV-1004 part 1", sc["user"], docs)
        self.assertEqual(st1, 200)
        self.assertEqual(res1["decision"], "pending_review")
        st2, res2 = send_v1(A["SUPPLIER"], "0.045", "Facture INV-1004 part 2", sc["user"], docs)
        self.assertEqual(st2, 200)
        self.assertEqual(res2["decision"], "blocked")
        self.assertTrue(any(r["code"] == "double_payment" for r in res2["reasons"]))

        # 8. Scénario leak (secret masqué dans le memo) -> pending_review et memo masqué
        sc = SCENARIOS["leak"]
        docs = [{"source": "inbox[0]", "content": sc["inbox"][0].format(**A)}]
        memo_with_secret = sc["naive_actions"][0]["memo"].format(**A)
        st, res = send_v1(A["SUPPLIER"], "0.01", memo_with_secret, sc["user"], docs)
        self.assertEqual(st, 200)
        self.assertEqual(res["decision"], "pending_review")
        self.assertIn("[MASQUE:private_key_hex]", res["memo"])

        # 9. Scénario canary (adresse appât) -> blocked + clé mise en quarantaine immédiate
        _, _, canary_key = self._setup_v1_org("Canary Scenario Org", limits={"canary_address": A["CANARY"]})
        sc = SCENARIOS["canary"]
        docs = [{"source": "inbox[0]", "content": sc["inbox"][0].format(**A)}]
        st, res = send_v1(A["CANARY"], "0.02", "Facture INV-1007", sc["user"], docs, key=canary_key)
        self.assertEqual(st, 200)
        self.assertEqual(res["decision"], "blocked")
        self.assertTrue(any(r["code"] == "canary" for r in res["reasons"]))
        # Requête suivante avec cette clé -> 401
        st_after, res_after, _, _ = self._req("GET", "/v1/policy", headers={"Authorization": f"Bearer {canary_key}"})
        self.assertEqual(st_after, 401)
        self.assertEqual(res_after["error"], "Clé API invalide ou inactive")

        # 10. Scénario probe (agent compromis en rafale) -> circuit breaker limit déclenché
        _, _, probe_key = self._setup_v1_org("Probe Scenario Org", limits={"circuit_breaker_limit": 5})
        sc = SCENARIOS["probe"]
        docs = [{"source": "inbox[0]", "content": sc["inbox"][0].format(**A)}]
        for i in range(1, 6):
            st_p, res_p = send_v1(A["ATTACKER"], "0.01", f"controle {i}", sc["user"], docs, key=probe_key)
            self.assertEqual(st_p, 200)
            self.assertEqual(res_p["decision"], "blocked")
        # 6e tentative -> clé en quarantaine
        st_p6, res_p6 = send_v1(A["ATTACKER"], "0.01", "controle 6", sc["user"], docs, key=probe_key)
        self.assertEqual(st_p6, 401)
        self.assertEqual(res_p6["error"], "Clé API invalide ou inactive")

    def test_v1_canary_immediate_quarantine_and_dashboard_alert(self):
        """Toucher l'adresse appât met la clé en quarantaine immédiate et génère une alerte visible dans /app."""
        self.server.LIMITER._b.clear()
        try:
            import orgs
        except ImportError:
            from agent import orgs

        canary_addr = "0xc0ffee00000000000000000000000000ca4a7700"
        org_id, key_id, raw_key = self._setup_v1_org("Canary Alert Org", limits={"canary_address": canary_addr})

        # Appel vers l'appât
        st, res, _, _ = self._req(
            "POST", "/v1/payments",
            body={"to": canary_addr, "amount": "0.02", "memo": "Honeytoken"},
            headers={"Authorization": f"Bearer {raw_key}"}
        )
        self.assertEqual(st, 200)
        self.assertEqual(res["decision"], "blocked")

        # La clé est en quarantaine immédiate
        key_row = db.query_one("SELECT quarantined_until, quarantine_reason FROM api_keys WHERE id = ?;",
                               (key_id,), db_path=self.db_path)
        self.assertIsNotNone(key_row["quarantined_until"])
        self.assertGreater(key_row["quarantined_until"], int(time.time()))
        self.assertIn("appât", key_row["quarantine_reason"].lower())

        # Requête ultérieure refusée en 401
        st_after, res_after, _, _ = self._req("GET", "/v1/policy", headers={"Authorization": f"Bearer {raw_key}"})
        self.assertEqual(st_after, 401)

        # L'alerte est visible dans /app/overview
        overview = orgs.get_overview(org_id, db_path=self.db_path)
        quarantine_alerts = [a for a in overview["alerts"] if a["type"] == "quarantine"]
        self.assertEqual(len(quarantine_alerts), 1)
        self.assertIn("quarantaine", quarantine_alerts[0]["message"].lower())

    # ---- Non-régression de la revue de l'étape 4 (attaques d'un agent compromis)

    def _api_v1(self):
        try:
            import api_v1
        except ImportError:
            from agent import api_v1
        return api_v1

    def test_v1_policy_never_reveals_canary(self):
        """L'adresse appât n'est jamais renvoyée à l'agent : sinon un agent compromis saurait l'éviter."""
        api_v1 = self._api_v1()
        canary = "0x" + "ca" * 20
        _, _, raw_key = self._setup_v1_org("Canary Hidden Org", limits={"canary_address": canary})
        st, res = api_v1.dispatch_v1("GET", "/v1/policy", {"Authorization": f"Bearer {raw_key}"}, db_path=self.db_path)
        self.assertEqual(st, 200)
        self.assertNotIn("ca" * 20, json.dumps(res).lower())

    def test_v1_parallel_payments_cannot_exceed_daily_cap(self):
        """Course : 20 paiements parallèles de 0,04 AVAX (plafond jour 0,3) ne doivent pas dépasser le plafond."""
        api_v1 = self._api_v1()
        org_id, _, raw_key = self._setup_v1_org("Race Org", limits={"circuit_breaker_limit": 100})
        sup = "0x" + "11" * 20
        now = int(time.time())
        db.execute("INSERT INTO suppliers (id, org_id, name, address, active_after, is_active, created_at, updated_at) "
                   "VALUES (?, ?, 'Acme', ?, ?, 1, ?, ?);",
                   ("sup_" + secrets.token_hex(6), org_id, sup, now - 10, now, now), db_path=self.db_path)
        api_v1.KEY_RATE_LIMITER._buckets.clear()
        hdr = {"Authorization": f"Bearer {raw_key}"}

        def pay(i):
            api_v1.dispatch_v1("POST", "/v1/payments", hdr, {"to": sup, "amount": "0.04", "memo": f"Facture INV-{1000 + i}",
                                                             "user_request": "Paie Acme"}, db_path=self.db_path)

        threads = [threading.Thread(target=pay, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        row = db.query_one("SELECT COALESCE(SUM(amount_gwei), 0) AS s FROM payments WHERE org_id = ? AND decision = 'allowed';",
                           (org_id,), db_path=self.db_path)
        self.assertLessEqual(row["s"], 300_000_000)
        self.assertGreater(row["s"], 0)

    def test_v1_quarantine_never_expires_and_blocks_inflight_requests(self):
        """La quarantaine ne se lève pas seule (pas de retour d'un agent compromis après 24 h) et une requête déjà
        authentifiée avant la mise en quarantaine est refusée."""
        api_v1 = self._api_v1()
        org_id, key_id, raw_key = self._setup_v1_org("Quarantine Org")
        key, org = api_v1.authenticate_key(f"Bearer {raw_key}", db_path=self.db_path)
        api_v1.quarantine_key(key_id, org_id, "test", db_path=self.db_path)
        row = db.query_one("SELECT quarantined_until FROM api_keys WHERE id = ?;", (key_id,), db_path=self.db_path)
        self.assertGreater(row["quarantined_until"], int(time.time()) + 50 * 365 * 86400)
        with self.assertRaises(api_v1.ApiV1Error) as ctx:
            api_v1.handle_post_payment({"to": "0x" + "11" * 20, "amount": "0.01", "memo": "INV-1"}, key, org,
                                       db_path=self.db_path)
        self.assertEqual(ctx.exception.code, 401)

    def test_v1_amount_ascii_digits_only(self):
        """Les chiffres non ASCII (arabes, devanagari...) sont refusés : int() les accepterait silencieusement."""
        api_v1 = self._api_v1()
        for bad in ["١٢", "१", "0.٥"]:
            with self.assertRaises(api_v1.ApiV1Error):
                api_v1.parse_avax_to_gwei(bad)
        self.assertEqual(api_v1.parse_avax_to_gwei("0.05"), 50_000_000)

    def test_v1_sdk_client_integration(self):
        """Vérifie le bon fonctionnement du SDK sdk/vaultguard_client.py."""
        self.server.LIMITER._b.clear()
        try:
            from sdk.vaultguard_client import VaultGuardClient, VaultGuardError
        except ImportError:
            import sys
            from pathlib import Path
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
            from sdk.vaultguard_client import VaultGuardClient, VaultGuardError

        org_id, key_id, raw_key = self._setup_v1_org("SDK Test Org")
        now = int(time.time())
        sup = "0x5a11e7c0ffee000000000000000000000000ace1"
        db.execute(
            "INSERT INTO suppliers (id, org_id, name, address, active_after, is_active, created_at, updated_at) "
            "VALUES ('sup_sdk_1', ?, 'Acme Supplies', ?, ?, 1, ?, ?);",
            (org_id, sup, now - 100, now, now), db_path=self.db_path
        )

        base_url = f"http://127.0.0.1:{self.port}"
        client = VaultGuardClient(api_key=raw_key, base_url=base_url)

        # 1. get_policy
        pol = client.get_policy()
        self.assertEqual(pol["network"], "mock")
        self.assertEqual(len(pol["active_suppliers"]), 1)

        # 2. pay nominal
        res = client.pay(to=sup, amount="0.02", memo="SDK Payment", user_request="Paie Acme Supplies")
        self.assertEqual(res["decision"], "allowed")
        pay_id = res["id"]

        # 3. get_payment
        p_detail = client.get_payment(pay_id)
        self.assertEqual(p_detail["id"], pay_id)
        self.assertEqual(p_detail["amount_avax"], "0.02")

        # 4. Erreur type amount (doit être str)
        with self.assertRaises(TypeError):
            client.pay(to=sup, amount=0.02)  # type: ignore

        # 5. Clé invalide -> VaultGuardError 401
        bad_client = VaultGuardClient(api_key="vg_live_badkey", base_url=base_url)
        with self.assertRaises(VaultGuardError) as ctx:
            bad_client.get_policy()
        self.assertEqual(ctx.exception.status_code, 401)

    def _auth(self):
        try:
            import auth
        except ImportError:
            from agent import auth
        return auth

    def _setup_superadmin_with_2fa(self, email=None, password="SuperAdminPassword123!") -> tuple[str, str, str, str, str]:
        """Crée un super-administrateur avec 2FA activée et retourne (user_id, org_id, cookie, csrf, secret)."""
        self.server.LIMITER._b.clear()
        auth = self._auth()
        clean_email = email or f"super_{secrets.token_hex(6)}@vaultguard.local"
        user_info = auth.create_superadmin(clean_email, password, db_path=self.db_path)
        user_id = user_info["id"]

        # Récupère l'organisation créée pour l'admin
        m = db.query_one("SELECT org_id FROM members WHERE user_id = ? AND role = 'owner';", (user_id,), db_path=self.db_path)
        org_id = m["org_id"] if m else ""

        # Setup 2FA
        s_res = auth.setup_2fa(user_id, db_path=self.db_path)
        secret = s_res["secret"]
        code = auth.hotp(secret, int(time.time()) // 30)
        auth.enable_2fa(user_id, code, db_path=self.db_path)
        db.execute("DELETE FROM totp_used_codes WHERE user_id = ?;", (user_id,), db_path=self.db_path)

        # Login avec 2FA
        csrf, cookie = self._get_csrf()
        status, data, new_cookie, _ = self._req(
            "POST", "/api/auth/login",
            {"email": clean_email, "password": password, "totp_code": code},
            cookie=cookie, csrf=csrf
        )
        self.assertEqual(status, 200)
        return user_id, org_id, new_cookie, data["csrf"], secret

    def test_admin_endpoints_return_404_for_unauthorized_users(self):
        """Un non-admin et un admin sans 2FA reçoivent 404 (pas 403), protégeant l'existence de l'espace."""
        self.server.LIMITER._b.clear()
        auth = self._auth()

        # 1. Visiteur anonyme
        s1, _, _, _ = self._req("GET", "/admin")
        self.assertEqual(s1, 404)
        s2, _, _, _ = self._req("GET", "/api/admin/stats")
        self.assertEqual(s2, 404)
        s3, _, _, _ = self._req("GET", "/api/admin/orgs")
        self.assertEqual(s3, 404)
        s4, _, _, _ = self._req("POST", "/api/admin/orgs/suspend", {"org_id": "org_x"})
        self.assertEqual(s4, 404)

        # 2. Utilisateur standard authentifié (non super-admin)
        csrf_u, c_u = self._get_csrf()
        u_res = self._req("POST", "/api/auth/signup",
                          {"email": f"norm_{secrets.token_hex(4)}@alpha.local", "password": "PasswordStrong123!", "org_name": "NormOrg"},
                          cookie=c_u, csrf=csrf_u)
        self.assertEqual(u_res[0], 201)
        norm_cookie = u_res[2]
        norm_csrf = u_res[1]["csrf"]

        s5, _, _, _ = self._req("GET", "/admin", cookie=norm_cookie)
        self.assertEqual(s5, 404)
        s6, _, _, _ = self._req("GET", "/api/admin/stats", cookie=norm_cookie)
        self.assertEqual(s6, 404)
        s7, _, _, _ = self._req("POST", "/api/admin/orgs/suspend", {"org_id": "org_x"}, cookie=norm_cookie, csrf=norm_csrf)
        self.assertEqual(s7, 404)

        # 3. Super-admin SANS 2FA activée
        pwd = "AdminWithout2fa123!"
        admin_no2fa_email = f"no2fa_{secrets.token_hex(4)}@vaultguard.local"
        auth.create_superadmin(admin_no2fa_email, pwd, db_path=self.db_path)

        csrf_a, c_a = self._get_csrf()
        login_res = self._req("POST", "/api/auth/login",
                              {"email": admin_no2fa_email, "password": pwd},
                              cookie=c_a, csrf=csrf_a)
        self.assertEqual(login_res[0], 200)
        no2fa_cookie = login_res[2]
        no2fa_csrf = login_res[1]["csrf"]

        s8, _, _, _ = self._req("GET", "/admin", cookie=no2fa_cookie)
        self.assertEqual(s8, 404)
        s9, _, _, _ = self._req("GET", "/api/admin/stats", cookie=no2fa_cookie)
        self.assertEqual(s9, 404)
        s10, _, _, _ = self._req("POST", "/api/admin/orgs/suspend", {"org_id": "org_x"}, cookie=no2fa_cookie, csrf=no2fa_csrf)
        self.assertEqual(s10, 404)

        # 4. Super-admin AVEC 2FA active : accès 200
        _, _, admin_cookie, admin_csrf, _ = self._setup_superadmin_with_2fa()
        s11, _, _, _ = self._req("GET", "/admin", cookie=admin_cookie)
        self.assertEqual(s11, 200)

        s12, stats, _, _ = self._req("GET", "/api/admin/stats", cookie=admin_cookie)
        self.assertEqual(s12, 200)
        self.assertIn("users", stats)
        self.assertIn("orgs", stats)
        self.assertIn("payments", stats)
        # Règle stricte de confidentialité : comptages uniquement, jamais de données financières
        self.assertNotIn("amount", str(stats))
        self.assertNotIn("recipient", str(stats))
        self.assertNotIn("memo", str(stats))

    def test_admin_org_suspension_cuts_v1_and_app(self):
        """La suspension d'une organisation coupe immédiatement /v1 (403) et /app (lecture seule)."""
        self.server.LIMITER._b.clear()
        _, _, admin_cookie, admin_csrf, _ = self._setup_superadmin_with_2fa()

        # 1. Mise en place d'une organisation cible avec clé API agent
        org_id, key_id, raw_key = self._setup_v1_org("Org To Suspend")
        now = int(time.time())
        sup = "0x5a11e7c0ffee000000000000000000000000ace2"
        db.execute(
            "INSERT INTO suppliers (id, org_id, name, address, active_after, is_active, created_at, updated_at) "
            "VALUES ('sup_susp_1', ?, 'Supplier Susp', ?, ?, 1, ?, ?);",
            (org_id, sup, now - 100, now, now), db_path=self.db_path
        )

        # 2. Paiement /v1 passe nominalement
        h = {"Authorization": f"Bearer {raw_key}"}
        s1, res1, _, _ = self._req("POST", "/v1/payments",
                                   {"to": sup, "amount": "0.01", "memo": "Before suspension", "user_request": "Paie Supplier Susp"},
                                   headers=h)
        self.assertEqual(s1, 200)
        self.assertEqual(res1["decision"], "allowed")

        # 3. Super-admin suspend l'organisation
        s2, res2, _, _ = self._req("POST", "/api/admin/orgs/suspend",
                                   {"org_id": org_id},
                                   cookie=admin_cookie, csrf=admin_csrf)
        self.assertEqual(s2, 200)
        self.assertTrue(res2["is_suspended"])

        # 4. /v1 est immédiatement coupé avec 403
        s3, res3, _, _ = self._req("POST", "/v1/payments",
                                   {"to": sup, "amount": "0.01", "memo": "During suspension", "user_request": "Paie Supplier Susp"},
                                   headers=h)
        self.assertEqual(s3, 403)
        self.assertIn("Organisation suspendue", res3.get("error", ""))

        # 5. Tentative de re-suspension -> 400 (rowcount check: déjà suspendue)
        s_dup, _, _, _ = self._req("POST", "/api/admin/orgs/suspend",
                                   {"org_id": org_id},
                                   cookie=admin_cookie, csrf=admin_csrf)
        self.assertEqual(s_dup, 400)

        # 6. Super-admin réactive l'organisation
        s4, res4, _, _ = self._req("POST", "/api/admin/orgs/reactivate",
                                   {"org_id": org_id},
                                   cookie=admin_cookie, csrf=admin_csrf)
        self.assertEqual(s4, 200)
        self.assertFalse(res4["is_suspended"])

        # 7. /v1 fonctionne à nouveau
        s5, res5, _, _ = self._req("POST", "/v1/payments",
                                   {"to": sup, "amount": "0.01", "memo": "After reactivate", "user_request": "Paie Supplier Susp"},
                                   headers=h)
        self.assertEqual(s5, 200)
        self.assertEqual(res5["decision"], "allowed")

    def test_admin_protects_last_superadmin_and_prevents_self_deactivation(self):
        """Un super-admin ne peut ni se désactiver ni se suspendre lui-même, et le dernier est protégé."""
        self.server.LIMITER._b.clear()
        auth = self._auth()
        admin1_id, admin1_org, admin1_cookie, admin1_csrf, _ = self._setup_superadmin_with_2fa()

        # 1. Impossible de suspendre sa propre organisation
        s_self_org, _, _, _ = self._req("POST", "/api/admin/orgs/suspend",
                                        {"org_id": admin1_org},
                                        cookie=admin1_cookie, csrf=admin1_csrf)
        self.assertEqual(s_self_org, 400)

        # 2. Impossible de se désactiver soi-même
        s_self_deact, _, _, _ = self._req("POST", "/api/admin/users/deactivate",
                                          {"user_id": admin1_id},
                                          cookie=admin1_cookie, csrf=admin1_csrf)
        self.assertEqual(s_self_deact, 400)

        # 3. Création d'un second super-admin
        admin2_email = f"admin2_{secrets.token_hex(4)}@vaultguard.local"
        admin2_pwd = "Admin2Password123!"
        u2 = auth.create_superadmin(admin2_email, admin2_pwd, db_path=self.db_path)
        admin2_id = u2["id"]

        # Admin 1 désactive Admin 2
        s_deact, res_deact, _, _ = self._req("POST", "/api/admin/users/deactivate",
                                             {"user_id": admin2_id},
                                             cookie=admin1_cookie, csrf=admin1_csrf)
        self.assertEqual(s_deact, 200)
        self.assertFalse(res_deact["is_active"])

        # Rowcount check : tenter de désactiver à nouveau Admin 2 -> 400
        s_dup_deact, _, _, _ = self._req("POST", "/api/admin/users/deactivate",
                                         {"user_id": admin2_id},
                                         cookie=admin1_cookie, csrf=admin1_csrf)
        self.assertEqual(s_dup_deact, 400)

        # 4. Protection du dernier super-admin actif :
        # Comme Admin 2 est inactif, Admin 1 est le seul super-admin actif restant.
        # Si on tente de désactiver Admin 1 par n'importe quelle requête -> refusé
        s_last, res_last, _, _ = self._req("POST", "/api/admin/users/deactivate",
                                           {"user_id": admin1_id},
                                           cookie=admin1_cookie, csrf=admin1_csrf)
        self.assertEqual(s_last, 400)

        # 5. Réactivation d'Admin 2
        s_act, res_act, _, _ = self._req("POST", "/api/admin/users/activate",
                                         {"user_id": admin2_id},
                                         cookie=admin1_cookie, csrf=admin1_csrf)
        self.assertEqual(s_act, 200)
        self.assertTrue(res_act["is_active"])

    def test_admin_disconnect_all_sessions(self):
        """L'action « déconnecter partout » supprime les sessions en base et coupe immédiatement l'accès."""
        self.server.LIMITER._b.clear()
        _, _, admin_cookie, admin_csrf, _ = self._setup_superadmin_with_2fa()

        # 1. Inscription d'un utilisateur cible
        user_email = f"target_{secrets.token_hex(4)}@alpha.local"
        user_pwd = "TargetPassword123!"
        csrf1, c1 = self._get_csrf()
        signup_res = self._req("POST", "/api/auth/signup",
                               {"email": user_email, "password": user_pwd, "org_name": "Target Org"},
                               cookie=c1, csrf=csrf1)
        self.assertEqual(signup_res[0], 201)
        sess1_cookie = signup_res[2]
        target_uid = signup_res[1]["user"]["id"]

        # 2. Deuxième connexion (deuxième session active en base)
        csrf2, c2 = self._get_csrf()
        login_res = self._req("POST", "/api/auth/login",
                              {"email": user_email, "password": user_pwd},
                              cookie=c2, csrf=csrf2)
        self.assertEqual(login_res[0], 200)
        sess2_cookie = login_res[2]

        # Vérifie qu'il y a au moins 2 sessions actives en base
        active_sessions = db.query_all("SELECT id FROM sessions WHERE user_id = ?;", (target_uid,), db_path=self.db_path)
        self.assertGreaterEqual(len(active_sessions), 2)

        # Les deux sessions accèdent nominalement à /api/auth/me
        s_me1, r_me1, _, _ = self._req("GET", "/api/auth/me", cookie=sess1_cookie)
        self.assertEqual(s_me1, 200)
        self.assertTrue(r_me1["authenticated"])

        s_me2, r_me2, _, _ = self._req("GET", "/api/auth/me", cookie=sess2_cookie)
        self.assertEqual(s_me2, 200)
        self.assertTrue(r_me2["authenticated"])

        # 3. Super-admin déclenche « déconnecter partout »
        s_disc, res_disc, _, _ = self._req("POST", "/api/admin/users/disconnect-all",
                                           {"user_id": target_uid},
                                           cookie=admin_cookie, csrf=admin_csrf)
        self.assertEqual(s_disc, 200)
        self.assertGreaterEqual(res_disc["deleted_sessions"], 2)

        # 4. Vérification en base : zéro session restante
        remaining = db.query_all("SELECT id FROM sessions WHERE user_id = ?;", (target_uid,), db_path=self.db_path)
        self.assertEqual(len(remaining), 0)

        # 5. Les deux sessions sont immédiatement invalides (401)
        s_cut1, _, _, _ = self._req("GET", "/api/auth/me", cookie=sess1_cookie)
        self.assertEqual(s_cut1, 401)
        s_cut2, _, _, _ = self._req("GET", "/api/app/overview", cookie=sess2_cookie)
        self.assertEqual(s_cut2, 401)

    def test_unpause_vault_reserved_to_owner_with_2fa(self):
        """Le bouton « dégeler » est réservé à l'owner avec 2FA, vérification rowcount et trace d'audit."""
        self.server.LIMITER._b.clear()
        auth = self._auth()

        # 1. Inscription d'un Owner pour Org Vault
        owner_email = f"owner_vault_{secrets.token_hex(4)}@alpha.local"
        owner_pwd = "OwnerPassword123!"
        csrf_o, c_o = self._get_csrf()
        reg_res = self._req("POST", "/api/auth/signup",
                            {"email": owner_email, "password": owner_pwd, "org_name": "Vault Test Org"},
                            cookie=c_o, csrf=csrf_o)
        self.assertEqual(reg_res[0], 201)
        owner_cookie = reg_res[2]
        owner_csrf = reg_res[1]["csrf"]
        owner_id = reg_res[1]["user"]["id"]
        vault_org_id = reg_res[1]["org"]["id"]

        # Configuration 2FA pour l'Owner
        s_res = auth.setup_2fa(owner_id, db_path=self.db_path)
        owner_secret = s_res["secret"]
        code_owner = auth.hotp(owner_secret, int(time.time()) // 30)
        auth.enable_2fa(owner_id, code_owner, db_path=self.db_path)
        db.execute("DELETE FROM totp_used_codes WHERE user_id = ?;", (owner_id,), db_path=self.db_path)

        # 2. Invitation et inscription d'un Approver dans la même organisation
        inv_res = self._req("POST", "/api/app/team/invites",
                            {"email": f"appr_v_{secrets.token_hex(4)}@alpha.local", "role": "approver"},
                            cookie=owner_cookie, csrf=owner_csrf)
        self.assertEqual(inv_res[0], 201)
        inv_token = inv_res[1]["token"]

        appr_email = inv_res[1]["email"]
        appr_pwd = "ApproverPassword123!"
        csrf_ap, c_ap = self._get_csrf()
        appr_reg = self._req("POST", "/api/auth/signup",
                             {"email": appr_email, "password": appr_pwd, "invite_token": inv_token},
                             cookie=c_ap, csrf=csrf_ap)
        self.assertEqual(appr_reg[0], 201)
        appr_cookie = appr_reg[2]
        appr_csrf = appr_reg[1]["csrf"]
        appr_id = appr_reg[1]["user"]["id"]

        # Setup 2FA pour l'approver
        s_appr = auth.setup_2fa(appr_id, db_path=self.db_path)
        appr_secret = s_appr["secret"]
        code_appr = auth.hotp(appr_secret, int(time.time()) // 30)
        auth.enable_2fa(appr_id, code_appr, db_path=self.db_path)

        # 3. Gèle le coffre en base (simulation déclenchement appât/disjoncteur)
        now = int(time.time())
        db.execute(
            "INSERT OR REPLACE INTO org_vault_states (org_id, balance_gwei, spent_today_gwei, is_paused, updated_at) "
            "VALUES (?, 10000000000, 0, 1, ?);",
            (vault_org_id, now), db_path=self.db_path
        )

        # 4. Dans /app, la vue d'ensemble affiche que le coffre est gelé
        s_ov, r_ov, _, _ = self._req("GET", "/api/app/overview", cookie=owner_cookie)
        self.assertEqual(s_ov, 200)
        self.assertTrue(r_ov["vault"]["is_paused"])
        self.assertTrue(r_ov["org"]["vault_paused"])

        # 5. L'approver tente de dégeler le coffre -> 403 (strictement réservé au rôle owner)
        code_appr_fresh = auth.hotp(appr_secret, (int(time.time()) + 1) // 30)
        s_fail_role, r_fail_role, _, _ = self._req("POST", "/api/app/vault/unpause",
                                                   {"code": code_appr_fresh},
                                                   cookie=appr_cookie, csrf=appr_csrf)
        self.assertEqual(s_fail_role, 403)

        # 6. L'owner tente avec un mauvais code 2FA -> 401
        s_bad_2fa, _, _, _ = self._req("POST", "/api/app/vault/unpause",
                                       {"code": "000000"},
                                       cookie=owner_cookie, csrf=owner_csrf)
        self.assertEqual(s_bad_2fa, 401)

        # 7. L'owner dégèle avec un code 2FA valide -> 200
        # Utilise un compteur frais pour éviter le rejeu
        t_now = int(time.time()) + 2
        fresh_code = auth.hotp(owner_secret, t_now // 30)
        s_ok, r_ok, _, _ = self._req("POST", "/api/app/vault/unpause",
                                     {"code": fresh_code},
                                     cookie=owner_cookie, csrf=owner_csrf)
        self.assertEqual(s_ok, 200)
        self.assertTrue(r_ok["ok"])
        self.assertFalse(r_ok["is_paused"])

        # 8. Vérification en base et dans l'overview
        v_state = db.query_one("SELECT is_paused FROM org_vault_states WHERE org_id = ?;", (vault_org_id,), db_path=self.db_path)
        self.assertEqual(v_state["is_paused"], 0)

        s_ov2, r_ov2, _, _ = self._req("GET", "/api/app/overview", cookie=owner_cookie)
        self.assertEqual(s_ov2, 200)
        self.assertFalse(r_ov2["vault"]["is_paused"])

        # 9. Trace d'audit vérifiée
        audit_entry = db.query_one(
            "SELECT action, user_id FROM audit WHERE org_id = ? AND action = 'vault.unpause';",
            (vault_org_id,), db_path=self.db_path
        )
        self.assertIsNotNone(audit_entry)
        self.assertEqual(audit_entry["user_id"], owner_id)

        # 10. Dégeler alors que le coffre n'est pas gelé -> 400 (rowcount check: WHERE is_paused = 1)
        db.execute("DELETE FROM totp_used_codes WHERE user_id = ?;", (owner_id,), db_path=self.db_path)
        t_now2 = int(time.time()) + 35
        fresh_code2 = auth.hotp(owner_secret, t_now2 // 30)
        s_already, _, _, _ = self._req("POST", "/api/app/vault/unpause",
                                       {"code": fresh_code2},
                                       cookie=owner_cookie, csrf=owner_csrf)
        self.assertEqual(s_already, 400)

    def test_admin_health_and_audit_verify(self):
        """Vérifie les diagnostics de santé et la vérification d'intégrité de la chaîne d'audit."""
        self.server.LIMITER._b.clear()
        _, _, admin_cookie, admin_csrf, _ = self._setup_superadmin_with_2fa()

        # 1. Santé système
        s_h, r_h, _, _ = self._req("GET", "/api/admin/health", cookie=admin_cookie)
        self.assertEqual(s_h, 200)
        self.assertEqual(r_h["version"], "3.0.0")
        self.assertEqual(r_h["database"]["status"], "ok")
        self.assertIn("avalanche_rpc", r_h)

        # 2. Vérification d'intégrité du journal d'audit
        s_v, r_v, _, _ = self._req("POST", "/api/admin/audit/verify",
                                   {}, cookie=admin_cookie, csrf=admin_csrf)
        self.assertEqual(s_v, 200)
        self.assertTrue(r_v["valid"])

        # 3. Événements de sécurité
        s_sec, r_sec, _, _ = self._req("GET", "/api/admin/security-events", cookie=admin_cookie)
        self.assertEqual(s_sec, 200)
        self.assertIn("failed_logins", r_sec)
        self.assertIn("quarantined_keys", r_sec)
        self.assertIn("canary_events", r_sec)

    # ---- Non-régression de la revue de l'étape 5

    def _admin_mod(self):
        try:
            import admin
        except ImportError:
            from agent import admin
        return admin

    def test_admin_mutual_deactivation_race_keeps_one_superadmin(self):
        """Deux super-admins qui se désactivent mutuellement en parallèle : il en reste toujours un actif."""
        admin = self._admin_mod()
        auth = self._auth()
        for _ in range(5):
            db.execute("UPDATE users SET is_superadmin = 0 WHERE is_superadmin = 1;", db_path=self.db_path)
            a = auth.create_superadmin(f"ra_{secrets.token_hex(4)}@vaultguard.local", "RaceAdmin123456!", db_path=self.db_path)["id"]
            b = auth.create_superadmin(f"rb_{secrets.token_hex(4)}@vaultguard.local", "RaceAdmin123456!", db_path=self.db_path)["id"]

            def deact(target, by):
                try:
                    admin.deactivate_user(target, by, db_path=self.db_path)
                except admin.AdminError:
                    pass

            t1 = threading.Thread(target=deact, args=(a, b))
            t2 = threading.Thread(target=deact, args=(b, a))
            t1.start(); t2.start(); t1.join(); t2.join()
            n = db.query_one("SELECT COUNT(*) AS c FROM users WHERE is_superadmin = 1 AND is_active = 1;",
                             db_path=self.db_path)["c"]
            self.assertEqual(n, 1)

    def test_admin_health_hides_rpc_url_secret(self):
        """L'URL RPC affichée ne garde que schéma + hôte (une clé de fournisseur est souvent dans le chemin)."""
        admin = self._admin_mod()
        old = os.environ.get("RPC_URL")
        os.environ["RPC_URL"] = "http://127.0.0.1:9/v3/SECRETKEY123?token=abc"
        try:
            url = admin.get_health(db_path=self.db_path)["avalanche_rpc"]["url"]
        finally:
            if old is None:
                os.environ.pop("RPC_URL", None)
            else:
                os.environ["RPC_URL"] = old
        self.assertEqual(url, "http://127.0.0.1")

    # ---- Étape 6 : Pages publiques et démo

    def test_public_pages_served_with_nonce_csp_and_no_external_urls(self):
        """Chaque page publique renvoie 200 text/html avec nonce CSP, sans URL externe ni adresse appât."""
        self.server.LIMITER._b.clear()
        canary = scenarios.addresses().get("CANARY", scenarios.DEFAULT_CANARY)
        public_pages = [
            "/",
            "/demo",
            "/docs",
            "/securite",
            "/mentions-legales",
            "/confidentialite",
            "/demo.html",
            "/docs.html",
            "/securite.html",
            "/mentions-legales.html",
            "/confidentialite.html",
        ]
        for path in public_pages:
            status, payload, _, resp = self._req("GET", path)
            self.assertEqual(status, 200, f"Page {path} doit renvoyer 200 (reçu {status})")
            ct = resp.getheader("Content-Type") or ""
            self.assertIn("text/html", ct, f"Page {path} doit être text/html")
            csp = resp.getheader("Content-Security-Policy") or ""
            self.assertIn("'nonce-", csp, f"Page {path} doit comporter une CSP avec nonce")
            self.assertEqual(resp.getheader("X-Frame-Options"), "DENY")
            self.assertEqual(resp.getheader("X-Content-Type-Options"), "nosniff")
            self.assertEqual(resp.getheader("Referrer-Policy"), "no-referrer")

            html = payload.decode("utf-8") if isinstance(payload, bytes) else str(payload)
            # Aucune référence http(s):// externe
            external_urls = [u for u in re.findall(r"https?://[^\s\"'<>]+", html)
                             if not (u.startswith("http://localhost") or u.startswith("http://127.0.0.1"))]
            self.assertEqual(external_urls, [], f"Page {path} contient des liens externes : {external_urls}")

            # Aucune page ne contient l'adresse appât configurée
            self.assertNotIn(canary.lower(), html.lower(), f"Page {path} expose l'adresse appât configurée")

    def test_demo_works_with_session_and_csrf(self):
        """La démo interactive fonctionne sur /demo : session, CSRF et exécution d'un scénario."""
        self.server.LIMITER._b.clear()
        # Chargement de la page de démo
        status, _, demo_cookie, _ = self._req("GET", "/demo")
        self.assertEqual(status, 200)

        # Récupération de la session et du jeton CSRF
        csrf, session_cookie = self._get_csrf(cookie=demo_cookie)
        self.assertTrue(csrf, "Le jeton CSRF doit être présent")

        # Exécution d'un scénario de démonstration
        status_run, res_run, _, _ = self._req(
            "POST", "/api/run",
            body={"scenario": "legit", "mode": "contract"},
            cookie=session_cookie,
            csrf=csrf
        )
        self.assertEqual(status_run, 200)
        self.assertEqual(res_run.get("scenario"), "legit")
        self.assertEqual(res_run.get("mode"), "contract")
        self.assertIn("summary", res_run)
        self.assertEqual(res_run["summary"]["lost"], 0.0)
        self.assertIn("trace", res_run)

    def test_unknown_url_returns_clean_404_html(self):
        """Une URL inconnue renvoie une vraie page 404 HTML avec CSP et sans fuite interne."""
        self.server.LIMITER._b.clear()
        for unknown_path in ["/introuvable", "/docs/inexistante", "/page-404-test", "/demo/rien"]:
            status, payload, _, resp = self._req("GET", unknown_path)
            self.assertEqual(status, 404, f"Le chemin {unknown_path} doit renvoyer 404")
            ct = resp.getheader("Content-Type") or ""
            self.assertIn("text/html", ct)
            csp = resp.getheader("Content-Security-Policy") or ""
            self.assertIn("'nonce-", csp)
            html = payload.decode("utf-8") if isinstance(payload, bytes) else str(payload)
            self.assertIn("404", html)
            self.assertIn("Page introuvable", html)
            # Pas de trace d'erreur Python interne
            self.assertNotIn("Traceback", html)
            self.assertNotIn("Exception", html)

    def test_no_inline_style_or_handler_attributes_in_html(self):
        """La CSP à nonce bloque les attributs style="..." et on*="..." : ils casseraient l'affichage en silence
        (ex. un bloc « display: none » qui reste visible). Revue de l'étape 6 : 92 attributs trouvés et convertis."""
        import re
        dash = Path(__file__).resolve().parent.parent / "dashboard"
        for page in sorted(dash.glob("*.html")):
            html = page.read_text(encoding="utf-8")
            self.assertNotRegex(html, r"<[^>]+\sstyle\s*=", f"attribut style dans {page.name}")
            self.assertIsNone(re.search(r"<[^>]+\son[a-z]+\s*=", html), f"gestionnaire on*= dans {page.name}")


if __name__ == "__main__":
    unittest.main()


