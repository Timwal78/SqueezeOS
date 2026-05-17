"""
402Proof payment client — handles the full x402 cycle for AI agents.

Flow:
  1. Hit protected endpoint → receive 402 + invoice
  2. Pay XRPL (XRP or RLUSD) with invoice memo_hex
  3. Call /v1/verify → receive access_token
  4. Retry original endpoint with X-Payment-Token header
"""

import requests
import time
import logging
from typing import Optional
from xrpl.wallet import Wallet

from .xrpl_pay import pay_invoice

log = logging.getLogger("proof402.client")

PROOF402_SERVER = "https://four02proof.onrender.com"
REQUEST_TIMEOUT = 30


class Proof402Client:
    """
    Drop-in HTTP client for agents. Automatically handles 402 payment flow.

    Usage:
        wallet = Wallet.from_seed(os.environ["AGENT_XRPL_SEED"])
        client = Proof402Client(wallet, agent_domain="my-agent.example.com")
        data = client.get("https://four02proof.onrender.com/api/council")
    """

    def __init__(self, wallet: Wallet, agent_domain: str = "", server: str = PROOF402_SERVER):
        self.wallet      = wallet
        self.agent_domain = agent_domain
        self.server      = server.rstrip("/")
        self._tokens: dict[str, str] = {}  # endpoint_id → access_token
        self.receipts: list[dict]    = []

    # ── Public API ──────────────────────────────────────────────────────────

    def get(self, url: str, **kwargs) -> requests.Response:
        return self._request("GET", url, **kwargs)

    def post(self, url: str, **kwargs) -> requests.Response:
        return self._request("POST", url, **kwargs)

    def get_invoice(self, endpoint_id: str) -> dict:
        resp = requests.post(
            f"{self.server}/v1/invoice",
            json={"endpoint_id": endpoint_id},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()

    def verify_payment(self, invoice_id: str, tx_hash: str) -> str:
        """Submit tx hash to 402Proof, receive access token."""
        resp = requests.post(
            f"{self.server}/v1/verify",
            json={
                "invoice_id":   invoice_id,
                "tx_hash":      tx_hash,
                "agent_wallet": self.wallet.classic_address,
                "agent_domain": self.agent_domain,
            },
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        self.receipts.append(data)
        log.info(f"[402Proof] settled receipt={data.get('receipt_id')} risk={data.get('risk_level')}")
        return data["access_token"]

    # ── Internal ─────────────────────────────────────────────────────────────

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        headers = kwargs.pop("headers", {})

        # Inject cached token if we have one for this URL
        cached = self._find_token(url)
        if cached:
            headers["X-Payment-Token"] = cached

        resp = requests.request(method, url, headers=headers, timeout=REQUEST_TIMEOUT, **kwargs)

        if resp.status_code != 402:
            return resp

        # ── 402 received — execute payment cycle ─────────────────────────────
        invoice_id  = resp.headers.get("X-Invoice-ID")
        endpoint_id = None

        # Try to get endpoint_id from response body
        try:
            body = resp.json()
            inv  = body.get("invoice", {})
            endpoint_id = inv.get("endpoint_id") or resp.headers.get("X-Invoice-ID", "")
        except Exception:
            inv = {}

        # Fetch fresh invoice if we don't have full details
        if not inv.get("pay_to") and endpoint_id:
            inv = self.get_invoice(endpoint_id)
            invoice_id = inv["invoice_id"]

        if not inv.get("pay_to"):
            log.error("[402Proof] Cannot extract invoice details from 402 response")
            return resp

        log.info(f"[402Proof] Paying invoice {invoice_id} — {inv['amount']} {inv['asset']} → {inv['pay_to']}")

        # Pay on XRPL
        tx_hash = pay_invoice(self.wallet, inv)
        log.info(f"[402Proof] TX submitted: {tx_hash}")

        # Verify and get token
        token = self.verify_payment(invoice_id, tx_hash)
        self._cache_token(url, token)

        # Retry original request with token
        headers["X-Payment-Token"] = token
        return requests.request(method, url, headers=headers, timeout=REQUEST_TIMEOUT, **kwargs)

    def _find_token(self, url: str) -> Optional[str]:
        # Simple URL-prefix match
        for key, token in self._tokens.items():
            if url.startswith(key) or key in url:
                return token
        return None

    def _cache_token(self, url: str, token: str) -> None:
        # Cache by base URL so token reuse works across calls
        from urllib.parse import urlparse
        parsed = urlparse(url)
        key = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        self._tokens[key] = token
