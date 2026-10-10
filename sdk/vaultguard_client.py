"""vaultguard_client.py — SDK Python officiel pour agents IA (VaultGuard v3).

Client HTTP minimal utilisant EXCLUSIVEMENT la bibliothèque standard (urllib).
Permet à tout agent IA d'interagir de manière sécurisée avec le pare-feu et le coffre :
  - Consultation de la politique et des fournisseurs autorisés (get_policy)
  - Soumission d'un paiement avec documents de preuve pour analyse (pay)
  - Suivi d'une transaction mise en attente de validation humaine (get_payment)
"""
from __future__ import annotations

import json
from typing import Any
import urllib.error
import urllib.parse
import urllib.request


class VaultGuardError(Exception):
    """Exception levée lors d'une erreur API VaultGuard."""

    def __init__(self, status_code: int, message: str, details: dict[str, Any] | None = None):
        super().__init__(f"[{status_code}] {message}")
        self.status_code = status_code
        self.message = message
        self.details = details or {}


class VaultGuardClient:
    """Client API pour agents autonomes de paiement."""

    def __init__(self, api_key: str, base_url: str = "http://127.0.0.1:8000", timeout: float = 10.0):
        if not api_key or not isinstance(api_key, str):
            raise ValueError("Une clé API valide est requise (ex. 'vg_live_...')")
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        # La clé part dans chaque requête : en HTTP clair hors de la machine locale, elle serait lisible sur le réseau.
        parsed = urllib.parse.urlsplit(self.base_url)
        if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost", "::1")):
            raise ValueError("base_url doit être en https:// (http:// accepté seulement sur localhost)")
        self.timeout = timeout

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "User-Agent": "VaultGuard-Agent-SDK/1.0",
        }
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")

        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # nosec B310
                raw = resp.read()
                if not raw:
                    return {}
                return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as e:
            raw_err = e.read()
            msg = e.reason
            details = None
            try:
                parsed = json.loads(raw_err.decode("utf-8"))
                if isinstance(parsed, dict):
                    msg = parsed.get("error", msg)
                    details = parsed
            except Exception:
                pass
            raise VaultGuardError(e.code, str(msg), details) from None
        except urllib.error.URLError as e:
            raise VaultGuardError(0, f"Erreur de connexion vers {self.base_url} : {e.reason}") from None

    def get_policy(self) -> dict[str, Any]:
        """Récupère la politique de sécurité active (fournisseurs et plafonds en AVAX)."""
        return self._request("GET", "/v1/policy")

    def pay(self, to: str, amount: str, memo: str = "", user_request: str = "",
            documents: list[dict[str, str]] | None = None,
            invoice: dict[str, Any] | None = None) -> dict[str, Any]:
        """Soumet un paiement à l'évaluation du pare-feu et du coffre on-chain.

        Arguments :
          to           : adresse EVM de destination (0x...)
          amount       : montant en AVAX sous forme de CHAÎNE stricte (ex. "0.05")
          memo         : note publique associée au paiement (max 140 octets)
          user_request : consigne initiale de l'utilisateur (donnée fiable de mandat)
          documents    : liste des documents analysés par l'agent [{source, content, file_sha256}] ;
                         VaultGuard les analyse en mémoire et n'en garde que l'empreinte SHA-256
          invoice      : facture structurée pour le contrôle de cohérence (voir sdk/invoice_reader.py) :
                         {currency, total, tax, lines: [{label, quantity, unit_price}],
                          references: [{label, unit_price}]} — nombres en chaînes

        Retourne :
          {
            "id": "pay_...",
            "decision": "allowed" | "pending_review" | "blocked",
            "reasons": [...],
            "chain": {"status": "Executed" | "Queued" | "Blocked", ...},
            "memo": "..."
          }
        """
        if not isinstance(amount, str):
            raise TypeError("Le paramètre amount doit être une chaîne en AVAX (ex: '0.05')")

        payload = {
            "to": to,
            "amount": amount,
            "memo": memo,
            "user_request": user_request,
            "documents": documents or [],
        }
        if invoice is not None:
            payload["invoice"] = invoice
        return self._request("POST", "/v1/payments", body=payload)

    def get_payment(self, payment_id: str) -> dict[str, Any]:
        """Consulte l'état et la décision d'un paiement existant."""
        if not payment_id or not isinstance(payment_id, str):
            raise ValueError("Identifiant de paiement requis")
        return self._request("GET", f"/v1/payments/{payment_id}")
