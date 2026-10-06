"""Test de parité + bout en bout sur une vraie blockchain locale (anvil).

Lancé par `bash scripts/test-all.sh --full` (qui démarre anvil et déploie). Ignoré si PARITY_ENV n'est pas défini.
Vérifie que MockChain (la démo hors-ligne) prend EXACTEMENT les mêmes décisions que AgentVault.sol.
"""
import os
import unittest

ENV = os.environ.get("PARITY_ENV")


@unittest.skipUnless(ENV and os.path.exists(ENV), "anvil non démarré (utiliser scripts/test-all.sh --full)")
class ParityAndE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from dotenv import dotenv_values
        cfg = dotenv_values(ENV)
        os.environ.update({k: v for k, v in cfg.items() if v is not None})
        from chain import MockChain, Web3Chain
        cls.real = Web3Chain.from_env()
        st = cls.real.state()
        sup, new, canary = cfg["SUPPLIER_ADDRESS"], cfg["NEW_SUPPLIER_ADDRESS"], cfg["CANARY_ADDRESS"]
        now = cls.real.w3.eth.get_block("latest").timestamp
        cls.mock = MockChain(allowed={sup, new}, canaries={canary}, active_from={new: now + st["recipient_delay"]},
                             max_per_tx=st["max_per_tx"], daily_limit=st["daily_limit"], threshold=st["threshold"],
                             max_blocked_per_day=st["max_blocked_per_day"], now=lambda: now)
        cls.addr = {"sup": sup, "new": new, "canary": canary, "evil": "0x" + "be" * 20}

    def test_1_previews_identical(self):
        a = self.addr
        cases = [(a["sup"], 0.01), (a["sup"], 0.06), (a["sup"], 0.2), (a["sup"], 0.0), (a["evil"], 0.01),
                 (a["new"], 0.01), (a["canary"], 0.01), (a["sup"], 0.1), (a["sup"], 0.05)]
        for to, amt in cases:
            self.assertEqual(self.real.preview(to, amt), self.mock.preview(to, amt), (to, amt))

    def test_2_e2e_payment_queue_approve(self):
        r = self.real.request_payment(self.addr["sup"], 0.01, "Facture E2E-1")
        self.assertEqual(r.status, "Executed")
        self.assertTrue(r.tx_hash.startswith("0x"))
        q = self.real.request_payment(self.addr["sup"], 0.06, "Facture E2E-2")
        self.assertEqual(q.status, "Queued")
        self.assertEqual(self.real.approve(q.pending_id).status, "Executed")
        b = self.real.request_payment(self.addr["evil"], 0.01, "x")
        self.assertEqual((b.status, b.reason), ("Blocked", "RecipientNotAllowed"))

    def test_3_events_and_anchor(self):
        self.real.anchor_report("ab" * 32, "test")
        names = {e["event"] for e in self.real.events()}
        self.assertTrue({"PaymentExecuted", "PaymentQueued", "PaymentBlocked", "ReportAnchored"} <= names)

    def test_4_canary_freezes_real_vault(self):
        self.real.request_payment(self.addr["canary"], 0.01, "x")
        self.assertTrue(self.real.state()["paused"])
        self.real.set_paused(False)
        self.assertFalse(self.real.state()["paused"])


if __name__ == "__main__":
    unittest.main()
