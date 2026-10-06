"""chain.py — accès au coffre AgentVault.

MockChain  : réplique en Python les règles de AgentVault.sol (démo hors-ligne, tests, bac à sable du dashboard).
Web3Chain  : le vrai contrat sur Anvil (local) ou Avalanche (Fuji testnet / C-Chain mainnet), via web3.py.
Les deux exposent la même interface : preview / request_payment / approve / reject / set_paused / anchor_report / state.
Toute règle ajoutée au contrat DOIT être reproduite ici (test de parité : test_parity.py).
"""
from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

REASONS = ["None", "Paused", "RecipientNotAllowed", "TokenNotAllowed", "OverTxLimit", "OverDailyLimit",
           "ZeroAmount", "RecipientNotYetActive", "TooManyPending", "AgentExpired", "CanaryTriggered"]
STATUSES = ["Executed", "Queued", "Blocked"]
NATIVE = "0x0000000000000000000000000000000000000000"
MAX_MEMO_BYTES = 140
MAX_OPEN_PENDING = 10
PENDING_TTL = 3 * 86400
_HERE = Path(__file__).resolve().parent
ABI_PATHS = [_HERE / "abi" / "AgentVault.json",
             _HERE.parent / "contracts" / "out" / "AgentVault.sol" / "AgentVault.json"]
EXPLORERS = {43113: "https://testnet.snowtrace.io", 43114: "https://snowtrace.io"}
NETWORKS = {43113: "Avalanche Fuji (testnet)", 43114: "Avalanche C-Chain (mainnet)", 31337: "Blockchain locale (anvil)"}


class ChainError(Exception):
    """Erreur attendue (paiement inconnu, expiré, etc.) : message sûr à afficher à l'utilisateur."""


def load_abi() -> list:
    for p in ABI_PATHS:
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            return data["abi"] if isinstance(data, dict) else data
    raise FileNotFoundError("ABI introuvable : lancer `bash scripts/export-abi.sh`")


@dataclass
class TxResult:
    status: str
    reason: str = ""
    pending_id: int | None = None
    tx_hash: str | None = None


@dataclass
class MockChain:
    """Réplique fidèle de AgentVault.sol. `now` est injectable pour les tests (simulation du temps)."""
    allowed: set[str]
    balance: float = 0.5
    max_per_tx: float = 0.1
    daily_limit: float = 0.3
    threshold: float = 0.05
    enforce_policy: bool = True
    paused: bool = False
    canaries: set[str] = field(default_factory=set)
    active_from: dict[str, float] = field(default_factory=dict)
    recipient_delay: float = 86400
    max_blocked_per_day: int = 5
    agent_valid_until: float = 0
    now: Callable[[], float] = field(default=time.time, repr=False)
    spent_today: float = 0.0
    day: int = -1
    blocked_today: int = 0
    blocked_day: int = -1
    pending: list[dict] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    received: dict[str, float] = field(default_factory=dict)

    def __post_init__(self):
        self.allowed = {a.lower() for a in self.allowed}
        self.canaries = {a.lower() for a in self.canaries}
        self.active_from = {k.lower(): v for k, v in self.active_from.items()}
        self._lock = threading.Lock()

    # ---- interne
    def _today(self) -> int:
        return int(self.now() // 86400)

    def _spent(self) -> float:
        return self.spent_today if self.day == self._today() else 0.0

    def _open_pending(self) -> int:
        return sum(1 for p in self.pending if not p["done"])

    def _event(self, name: str, **data) -> None:
        self.events.append({"event": name, "ts": self.now(), **data})
        del self.events[:-500]  # mémoire bornée

    def _pause(self, by: str) -> None:
        self.paused = True
        self._event("Paused", paused=True, by=by)

    def _count_blocked(self) -> None:
        if self.blocked_day != self._today():
            self.blocked_day, self.blocked_today = self._today(), 0
        self.blocked_today += 1
        if self.max_blocked_per_day and self.blocked_today >= self.max_blocked_per_day and not self.paused:
            self._event("CircuitBreakerTripped", blocked_today=self.blocked_today)
            self._pause("vault")

    def _send(self, to: str, amount: float, memo: str) -> None:
        if amount > self.balance + 1e-12:
            raise ChainError("Solde du coffre insuffisant")
        self.balance = round(self.balance - amount, 12)
        self.received[to.lower()] = round(self.received.get(to.lower(), 0) + amount, 12)
        self._event("PaymentExecuted", to=to, amount=amount, memo=memo)

    # ---- interface commune
    def preview(self, to: str, amount: float) -> tuple[str, str]:
        to = to.lower()
        if not self.enforce_policy:  # mode « aucune protection » : seul le solde limite
            return ("Executed", "") if 0 < amount <= self.balance + 1e-12 else ("Blocked", "InsufficientBalance")
        if self.paused:
            return "Blocked", "Paused"
        if self.agent_valid_until and self.now() > self.agent_valid_until:
            return "Blocked", "AgentExpired"
        if to in self.canaries:
            return "Blocked", "CanaryTriggered"
        if amount <= 0:
            return "Blocked", "ZeroAmount"
        if to not in self.allowed:
            return "Blocked", "RecipientNotAllowed"
        if self.now() < self.active_from.get(to, 0):
            return "Blocked", "RecipientNotYetActive"
        if amount > self.max_per_tx + 1e-12:
            return "Blocked", "OverTxLimit"
        if self._spent() + amount > self.daily_limit + 1e-12:
            return "Blocked", "OverDailyLimit"
        if self.threshold and amount >= self.threshold and self._open_pending() >= MAX_OPEN_PENDING:
            return "Blocked", "TooManyPending"
        if self.threshold and amount >= self.threshold:
            return "Queued", ""
        return "Executed", ""

    def request_payment(self, to: str, amount: float, memo: str) -> TxResult:
        if len(memo.encode()) > MAX_MEMO_BYTES:
            raise ChainError("MemoTooLong : memo limité à 140 octets")
        with self._lock:
            status, reason = self.preview(to, amount)
            if status == "Blocked":
                self._event("PaymentBlocked", reason=reason, to=to, amount=amount, memo=memo)
                if self.enforce_policy:
                    if reason == "CanaryTriggered":
                        self._event("CanaryAlert", to=to, amount=amount)
                        self._pause("vault")
                    elif reason != "Paused":
                        self._count_blocked()
                return TxResult(status, reason)
            if status == "Queued":
                pid = len(self.pending)
                self.pending.append({"id": pid, "to": to, "amount": amount, "memo": memo,
                                     "created": self.now(), "done": False})
                self._event("PaymentQueued", id=pid, to=to, amount=amount, memo=memo)
                return TxResult(status, pending_id=pid)
            self.spent_today, self.day = self._spent() + amount, self._today()
            self._send(to, amount, memo)
            return TxResult(status)

    def _get_open(self, pid) -> dict:
        if not isinstance(pid, int) or isinstance(pid, bool) or not 0 <= pid < len(self.pending):
            raise ChainError("Paiement en attente introuvable")
        p = self.pending[pid]
        if p["done"]:
            raise ChainError("Paiement déjà traité")
        return p

    def approve(self, pid: int) -> TxResult:
        with self._lock:
            p = self._get_open(pid)
            if self.now() > p["created"] + PENDING_TTL:
                raise ChainError("Paiement expiré (plus de 3 jours) : à rejeter")
            to = p["to"].lower()
            if self.paused or to not in self.allowed or to in self.canaries:
                raise ChainError("Validation refusée : coffre en pause ou destinataire retiré")
            p["done"] = True
            self.spent_today, self.day = self._spent() + p["amount"], self._today()
            self._event("PaymentApproved", id=pid)
            self._send(p["to"], p["amount"], p["memo"])
            return TxResult("Executed")

    def reject(self, pid: int) -> TxResult:
        with self._lock:
            self._get_open(pid)["done"] = True
            self._event("PaymentRejected", id=pid)
            return TxResult("Rejected")

    def set_paused(self, paused: bool) -> TxResult:
        with self._lock:
            self.paused = paused
            if not paused:
                self.blocked_today = 0
            self._event("Paused", paused=paused, by="owner")
            return TxResult("Paused" if paused else "Resumed")

    def guardian_pause(self) -> TxResult:
        with self._lock:
            if not self.paused:
                self._pause("guardian")
            return TxResult("Paused")

    def anchor_report(self, digest_hex: str, uri: str = "") -> TxResult:
        self._event("ReportAnchored", hash=digest_hex, uri=uri)
        return TxResult("Anchored")

    def state(self) -> dict:
        return {"backend": "mock", "network": "Simulation (hors-ligne)", "chain_id": None, "explorer": "",
                "vault": None, "balance": self.balance, "spent_today": self._spent(),
                "max_per_tx": self.max_per_tx, "daily_limit": self.daily_limit, "threshold": self.threshold,
                "paused": self.paused, "enforce_policy": self.enforce_policy,
                "recipient_delay": self.recipient_delay, "max_blocked_per_day": self.max_blocked_per_day,
                "blocked_today": self.blocked_today if self.blocked_day == self._today() else 0,
                "agent_valid_until": self.agent_valid_until,
                "pending": [{k: p[k] for k in ("id", "to", "amount", "memo", "created")}
                            for p in self.pending if not p["done"]],
                "received": dict(self.received), "events": self.events[-50:]}


class Web3Chain:
    """Vrai contrat. Env : RPC_URL, VAULT_ADDRESS, AGENT_PRIVATE_KEY, OWNER_PRIVATE_KEY (optionnel), DEPLOY_BLOCK.

    En production, ne PAS mettre OWNER_PRIVATE_KEY sur le serveur : l'owner signe depuis son navigateur (Core Wallet).
    """

    LOG_CHUNK = 2000  # les RPC publics d'Avalanche limitent eth_getLogs à ~2048 blocs par requête

    def __init__(self, rpc_url: str, vault_address: str, agent_pk: str, owner_pk: str | None = None,
                 deploy_block: int = 0, guardian_pk: str | None = None):
        from web3 import Web3
        self.Web3 = Web3
        self.w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 20}))
        self.vault = self.w3.eth.contract(address=Web3.to_checksum_address(vault_address), abi=load_abi())
        self.agent = self.w3.eth.account.from_key(agent_pk)
        self.owner = self.w3.eth.account.from_key(owner_pk) if owner_pk else None
        self.guardian = self.w3.eth.account.from_key(guardian_pk) if guardian_pk else None
        self.chain_id = self.w3.eth.chain_id
        self.explorer = os.environ.get("EXPLORER_URL", EXPLORERS.get(self.chain_id, ""))
        self._lock = threading.Lock()
        self._events: list[dict] = []
        self._scanned = max(deploy_block - 1, 0)

    @classmethod
    def from_env(cls) -> "Web3Chain":
        return cls(os.environ["RPC_URL"], os.environ["VAULT_ADDRESS"], os.environ["AGENT_PRIVATE_KEY"],
                   os.environ.get("OWNER_PRIVATE_KEY") or None, int(os.environ.get("DEPLOY_BLOCK") or 0),
                   os.environ.get("GUARDIAN_PRIVATE_KEY") or None)

    def _wei(self, avax: float) -> int:
        return self.Web3.to_wei(round(avax, 18), "ether")

    def _avax(self, wei: int) -> float:
        return float(self.Web3.from_wei(wei, "ether"))

    def _send(self, fn, account):
        with self._lock:  # nonce séquentiel : pas deux transactions concurrentes du même compte
            tx = fn.build_transaction({"from": account.address, "chainId": self.chain_id,
                                       "nonce": self.w3.eth.get_transaction_count(account.address, "pending")})
            signed = account.sign_transaction(tx)
            raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
            h = self.w3.eth.send_raw_transaction(raw)
            rc = self.w3.eth.wait_for_transaction_receipt(h, timeout=120)
        if rc.status != 1:
            raise ChainError("Transaction refusée par le contrat")
        return rc

    def _call_or_explain(self, fn, account):
        try:
            fn.call({"from": account.address})  # simulation : récupère l'erreur custom sans payer de gas
        except Exception as e:  # noqa: BLE001 — on traduit l'erreur du contrat en message sûr
            raise ChainError(f"Refusé par le contrat : {type(e).__name__}") from None
        return self._send(fn, account)

    def preview(self, to: str, amount: float) -> tuple[str, str]:
        s, r = self.vault.functions.previewPayment(NATIVE, self.Web3.to_checksum_address(to), self._wei(amount)).call(
            {"from": self.agent.address})
        return STATUSES[s], "" if r == 0 else REASONS[r]

    def request_payment(self, to: str, amount: float, memo: str) -> TxResult:
        from web3.logs import DISCARD
        if len(memo.encode()) > MAX_MEMO_BYTES:
            raise ChainError("MemoTooLong : memo limité à 140 octets")
        fn = self.vault.functions.requestPayment(NATIVE, self.Web3.to_checksum_address(to), self._wei(amount), memo)
        rc = self._send(fn, self.agent)
        h = self.w3.to_hex(rc.transactionHash)
        for ev in self.vault.events.PaymentBlocked().process_receipt(rc, errors=DISCARD):
            return TxResult("Blocked", REASONS[ev.args.reason], tx_hash=h)
        for ev in self.vault.events.PaymentQueued().process_receipt(rc, errors=DISCARD):
            return TxResult("Queued", pending_id=ev.args.id, tx_hash=h)
        return TxResult("Executed", tx_hash=h)

    def _owner_tx(self, fn) -> str:
        if not self.owner:
            raise ChainError("Action owner : signez-la avec Core Wallet (la clé owner n'est pas sur le serveur)")
        return self.w3.to_hex(self._call_or_explain(fn, self.owner).transactionHash)

    def approve(self, pid: int) -> TxResult:
        return TxResult("Executed", tx_hash=self._owner_tx(self.vault.functions.approve(pid)))

    def reject(self, pid: int) -> TxResult:
        return TxResult("Rejected", tx_hash=self._owner_tx(self.vault.functions.reject(pid)))

    def set_paused(self, paused: bool) -> TxResult:
        return TxResult("Paused" if paused else "Resumed", tx_hash=self._owner_tx(self.vault.functions.setPaused(paused)))

    def guardian_pause(self) -> TxResult:
        """Gel d'urgence. La clé guardian peut rester sur le serveur : elle ne peut QUE geler (jamais dégeler ni payer)."""
        signer = self.guardian or self.owner
        if not signer:
            raise ChainError("Aucune clé guardian configurée (GUARDIAN_PRIVATE_KEY)")
        if self.vault.functions.paused().call():
            return TxResult("Paused")
        rc = self._call_or_explain(self.vault.functions.setPaused(True), signer)
        return TxResult("Paused", tx_hash=self.w3.to_hex(rc.transactionHash))

    def anchor_report(self, digest_hex: str, uri: str = "") -> TxResult:
        fn = self.vault.functions.anchorReport(bytes.fromhex(digest_hex.removeprefix("0x")), uri[:200])
        signer = self.owner or self.guardian
        if not signer:
            raise ChainError("Ancrage : clé owner ou guardian requise")
        return TxResult("Anchored", tx_hash=self.w3.to_hex(self._call_or_explain(fn, signer).transactionHash))

    def events(self) -> list[dict]:
        """Lit les events du coffre depuis DEPLOY_BLOCK, par tranches (incrémental, mis en cache)."""
        head = self.w3.eth.block_number
        if not self._scanned:
            self._scanned = max(head - 20 * self.LOG_CHUNK, 0)  # sans DEPLOY_BLOCK : ~40 000 derniers blocs
        names = ["PaymentExecuted", "PaymentQueued", "PaymentBlocked", "PaymentApproved", "PaymentRejected",
                 "Paused", "CanaryAlert", "CircuitBreakerTripped", "ReportAnchored", "RecipientChanged"]
        while self._scanned < head:
            start, end = self._scanned + 1, min(self._scanned + self.LOG_CHUNK, head)
            for name in names:
                for log in getattr(self.vault.events, name)().get_logs(from_block=start, to_block=end):
                    args = dict(log.args)
                    for k in ("amount",):
                        if k in args:
                            args[k] = self._avax(args[k])
                    if name == "PaymentBlocked":
                        args["reason"] = REASONS[args["reason"]]
                    for k, v in list(args.items()):
                        if isinstance(v, (bytes, bytearray)):
                            args[k] = "0x" + v.hex()
                    self._events.append({"event": name, "block": log.blockNumber,
                                         "tx": self.w3.to_hex(log.transactionHash), **args})
            self._scanned = end
        self._events.sort(key=lambda e: e["block"])
        del self._events[:-500]
        return self._events

    def state(self) -> dict:
        f = self.vault.functions
        mx, daily, thr = f.limits(NATIVE).call()
        now = self.w3.eth.get_block("latest").timestamp
        spent = f.spentToday(NATIVE).call() if f.spentDay(NATIVE).call() == now // 86400 else 0
        pending, n = [], f.pendingCount().call()
        for i in range(max(0, n - 50), n):
            token, to, amount, memo, created, done = f.pending(i).call()
            if not done:
                pending.append({"id": i, "to": to, "amount": self._avax(amount), "memo": memo, "created": created})
        try:
            events = self.events()[-50:]
        except Exception:  # noqa: BLE001 — un RPC lent ne doit pas casser l'affichage du coffre
            events = self._events[-50:]
        return {"backend": "web3", "network": NETWORKS.get(self.chain_id, f"chainId {self.chain_id}"),
                "chain_id": self.chain_id, "vault": self.vault.address, "explorer": self.explorer,
                "owner": f.owner().call(), "agent": f.agent().call(), "guardian": f.guardian().call(),
                "owner_key_on_server": self.owner is not None, "guardian_key_on_server": self.guardian is not None,
                "balance": self._avax(self.w3.eth.get_balance(self.vault.address)), "spent_today": self._avax(spent),
                "max_per_tx": self._avax(mx), "daily_limit": self._avax(daily), "threshold": self._avax(thr),
                "paused": f.paused().call(), "enforce_policy": True,
                "recipient_delay": f.recipientDelay().call(), "max_blocked_per_day": f.maxBlockedPerDay().call(),
                "blocked_today": f.blockedToday().call() if f.blockedDay().call() == now // 86400 else 0,
                "agent_valid_until": f.agentValidUntil().call(),
                "pending": pending, "received": {}, "events": events}
