"""Tests de la couche de sécurité : python3 -m unittest -v"""
import os
import tempfile
import unittest

from agent import POLICY
from guard import Guard, Session, find_secrets, redact, wrap_untrusted


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.g = Guard(POLICY, audit_path=os.path.join(tempfile.mkdtemp(), "audit.jsonl"))

    def test_role_least_privilege(self):
        self.assertFalse(self.g.check_tool_call(Session("guest"), "get_customer", {"customer_id": "C-001"}).allowed)

    def test_unknown_tool(self):
        self.assertFalse(self.g.check_tool_call(Session("support"), "rm_rf", {}).allowed)

    def test_egress_domain_allowlist(self):
        s = Session("support")
        self.assertTrue(self.g.check_tool_call(s, "send_email", {"to": "a@acme.test", "body": "x"}).allowed)
        self.assertFalse(self.g.check_tool_call(s, "send_email", {"to": "a@other.example", "body": "x"}).allowed)

    def test_taint_requires_confirmation(self):
        s = Session("support")
        self.g.after_tool(s, "get_customer", "{}")
        d = self.g.check_tool_call(s, "send_email", {"to": "a@acme.test", "body": "x"})
        self.assertTrue(d.allowed and d.needs_confirmation)

    def test_quota(self):
        s = Session("support")
        s.tool_calls = POLICY.max_tool_calls
        self.assertFalse(self.g.check_tool_call(s, "search_kb", {"query": "x"}).allowed)

    def test_redaction(self):
        fake = "AKIA" + "ABCDEFGHIJKLMNOP"
        self.assertIn("aws_access_key", find_secrets(fake))
        self.assertNotIn(fake, redact(f"clé: {fake}"))

    def test_untrusted_wrapping(self):
        self.assertIn("DONNEE_NON_FIABLE", wrap_untrusted("search_kb", "texte"))


if __name__ == "__main__":
    unittest.main()
