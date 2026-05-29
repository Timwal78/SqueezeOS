"""
proof402_client.py — real 402Proof client.

Talks to the live 402Proof server (the same one the rest of SqueezeOS uses):
  - POST /v1/invoice                 → issue a payment invoice for an endpoint
  - GET  /v1/bureau/score/{wallet}   → Agent Credit Bureau score (FICO 300-850)

This is NOT a mock. It issues real invoices and reads real on-chain-backed
bureau scores. When the server is unreachable it returns an explicit
{"offline": True} marker — callers must degrade gracefully (repo convention:
never fabricate data when a service is down).

Token *verification* stays local and pure-CPU (HMAC-SHA256), identical to
proof402_integration._verify_token_local — see x402_settlement.verify_settlement_token.
"""

from __future__ import annotations

import os
import json
import logging
import urllib.request
import urllib.error

logger = logging.getLogger("StellarForge-402")

PROOF402_SERVER = os.environ.get("PROOF402_SERVER_URL", "https://four02proof.onrender.com")
_UA = "StellarForge-Economy/1.0"


class Proof402Client:
    """Thin, real HTTP client for the 402Proof payment + bureau API."""

    def __init__(self, base_url: str = PROOF402_SERVER, timeout: float = 15.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _get(self, path: str) -> dict:
        url = f"{self.base_url}{path}"
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            logger.warning("[402] %s -> HTTP %s", path, e.code)
            return {"offline": False, "error": f"HTTP {e.code}", "status": e.code}
        except Exception as e:  # connection refused, timeout, DNS, etc.
            logger.warning("[402] %s unreachable: %s", path, e)
            return {"offline": True}

    def _post(self, path: str, body: dict) -> dict:
        url = f"{self.base_url}{path}"
        data = json.dumps(body).encode()
        req = urllib.request.Request(
            url, data=data, method="POST",
            headers={"User-Agent": _UA, "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            logger.warning("[402] POST %s -> HTTP %s", path, e.code)
            return {"offline": False, "error": f"HTTP {e.code}", "status": e.code}
        except Exception as e:
            logger.warning("[402] POST %s unreachable: %s", path, e)
            return {"offline": True}

    # ------------------------------------------------------------------ API
    def issue_invoice(self, endpoint_id: str) -> dict:
        """Request a real payment invoice. Returns the 402Proof invoice payload
        (address, amount, invoice_id, ...) or an offline marker."""
        return self._post("/v1/invoice", {"endpoint_id": endpoint_id})

    def bureau_score(self, wallet: str) -> dict:
        """Real Agent Credit Bureau score for an XRPL wallet.

        Returns e.g. {"wallet":..., "score": 720, "grade": "B", "tier": "...",
        "payments": 42} or {"offline": True}. Never fabricates a score.
        """
        if not wallet:
            return {"offline": False, "error": "empty wallet"}
        return self._get(f"/v1/bureau/score/{wallet}")
