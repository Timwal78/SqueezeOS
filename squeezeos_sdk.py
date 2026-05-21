"""
SqueezeOS Python SDK
====================
Autonomous agent client for the SqueezeOS Market Intelligence API.

Handles the full x402 payment lifecycle automatically:
  1. Hit endpoint → receive HTTP 402 + invoice
  2. Pay RLUSD on XRPL with the required memo
  3. POST /v1/verify → receive signed access token
  4. Retry original request with X-Payment-Token header

Tokens are cached on disk (TTL-aware) so a single payment unlocks an
endpoint for up to one hour without re-paying.

Dependencies (pip install):
    xrpl-py >= 2.7
    requests >= 2.31

Usage:
    client = SqueezeOSClient(xrpl_seed="sEd...", agent_domain="mybot.example.com")
    verdict = client.council("IWM")
    scan    = client.scan()
    opts    = client.options("IWM")
    iwm     = client.iwm()
    loyalty = client.loyalty_status()
"""

from __future__ import annotations

import json
import os
import time
import logging
from pathlib import Path
from typing import Any, Dict, Optional

import requests
from xrpl.core import keypairs
from xrpl.models.transactions import Payment, Memo
from xrpl.models.amounts import IssuedCurrencyAmount
from xrpl.transaction import autofill_and_sign, submit_and_wait
from xrpl.clients import JsonRpcClient
from xrpl.wallet import Wallet

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Platform constants
# ---------------------------------------------------------------------------

SQUEEZEOS_API   = "https://squeezeos-api.onrender.com"
PROOF402_API    = "https://four02proof.onrender.com"
XRPL_RPC        = "https://s1.ripple.com:51234/"   # mainnet JSON-RPC
RLUSD_ISSUER    = "rMxCKbEDwqr76QuheSUMdEGf4B9xJ8m5De"
RLUSD_CURRENCY  = "RLUSD"

# Endpoint registry — endpoint_id is the stable identifier used by 402Proof
ENDPOINTS: Dict[str, Dict[str, Any]] = {
    "council": {
        "path":        "/api/council",
        "endpoint_id": "12a0e7a1-6812-4c3f-aa24-de6e3bc12b5a",
        "price_rlusd": 0.10,
        "method":      "POST",
    },
    "scan": {
        "path":        "/api/scan",
        "endpoint_id": "160cf28d-b364-44eb-adbd-2489c5cc2cf8",
        "price_rlusd": 0.05,
        "method":      "GET",
    },
    "options": {
        "path":        "/api/options",
        "endpoint_id": "c951a374-2424-4064-ab80-35afe8053d29",
        "price_rlusd": 0.05,
        "method":      "GET",
    },
    "iwm": {
        "path":        "/api/iwm",
        "endpoint_id": "60f48ce0-6002-4385-9b60-03a0d2bbebab",
        "price_rlusd": 0.03,
        "method":      "GET",
    },
}

# Default path for the on-disk token cache
_DEFAULT_TOKEN_CACHE = Path.home() / ".squeezeos_tokens.json"

# How many seconds before token expiry to consider it stale and re-pay
_TOKEN_REFRESH_BUFFER_SECS = 120


# ---------------------------------------------------------------------------
# Token cache helpers
# ---------------------------------------------------------------------------

def _load_token_cache(path: Path) -> Dict[str, Any]:
    """Load the token cache from disk, returning an empty dict on any error."""
    try:
        if path.exists():
            with path.open("r") as fh:
                return json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not read token cache %s: %s", path, exc)
    return {}


def _save_token_cache(cache: Dict[str, Any], path: Path) -> None:
    """Persist the token cache to disk atomically."""
    try:
        tmp = path.with_suffix(".tmp")
        with tmp.open("w") as fh:
            json.dump(cache, fh, indent=2)
        tmp.replace(path)
    except OSError as exc:
        logger.warning("Could not write token cache %s: %s", path, exc)


def _parse_token_exp(token: str) -> Optional[int]:
    """
    Extract the expiry (Unix timestamp) from the 402Proof JWT-like token.

    Token format:  <base64url-payload>.<signature>
    The payload is a base64url-encoded JSON object with an 'exp' field.
    Returns None if parsing fails (treat as already expired).
    """
    import base64
    try:
        dot = token.rfind(".")
        if dot < 0:
            return None
        encoded = token[:dot]
        # Restore base64url padding
        padding = 4 - len(encoded) % 4
        payload = json.loads(
            base64.urlsafe_b64decode(encoded + "=" * padding)
        )
        return int(payload.get("exp", 0))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# XRPL payment helper
# ---------------------------------------------------------------------------

def _build_rlusd_memo(memo_hex: str) -> Memo:
    """Build an XRPL Memo object from the 402Proof hex string."""
    return Memo(memo_data=memo_hex)


def _rlusd_amount(amount_str: str) -> IssuedCurrencyAmount:
    """Return an IssuedCurrencyAmount for RLUSD."""
    return IssuedCurrencyAmount(
        currency=RLUSD_CURRENCY,
        issuer=RLUSD_ISSUER,
        value=str(amount_str),
    )


# ---------------------------------------------------------------------------
# Main SDK class
# ---------------------------------------------------------------------------

class SqueezeOSClient:
    """
    Autonomous agent client for the SqueezeOS / Script Master Labs platform.

    All paid endpoints are accessed through the x402 RLUSD payment flow.
    On the first call to any paid endpoint the client:
      - Requests a payment invoice from 402Proof
      - Submits an RLUSD payment on the XRPL mainnet
      - Verifies the transaction with 402Proof and receives an access token
      - Caches the token on disk for reuse within its TTL window

    Parameters
    ----------
    xrpl_seed : str
        XRPL family-seed or secret key (sEd… or s…).  The derived wallet
        must already have an RLUSD trust line to rMxCKbEDwqr76QuheSUMdEGf4B9xJ8m5De.
    agent_domain : str
        Human-readable identifier attributed to this agent in loyalty tracking
        and compliance receipts.  Defaults to "myagent.example.com".
    token_cache_path : Path | str | None
        File path for the on-disk token cache.  Defaults to
        ~/.squeezeos_tokens.json.  Pass None to disable disk caching (tokens
        are still cached in memory for the lifetime of this object).
    xrpl_rpc_url : str
        XRPL mainnet JSON-RPC endpoint.  Override for testnet.
    squeezeos_url : str
        Base URL for the SqueezeOS API.
    proof402_url : str
        Base URL for the 402Proof payment gateway.
    http_timeout : int
        Timeout in seconds for all HTTP requests.
    """

    def __init__(
        self,
        xrpl_seed: str,
        agent_domain: str = "myagent.example.com",
        token_cache_path: Optional[Any] = _DEFAULT_TOKEN_CACHE,
        xrpl_rpc_url: str = XRPL_RPC,
        squeezeos_url: str = SQUEEZEOS_API,
        proof402_url: str = PROOF402_API,
        http_timeout: int = 30,
    ) -> None:
        # Derive XRPL wallet from seed
        self._wallet = Wallet.from_seed(xrpl_seed)
        self.agent_domain = agent_domain
        self._xrpl_rpc_url = xrpl_rpc_url
        self._squeezeos_url = squeezeos_url.rstrip("/")
        self._proof402_url = proof402_url.rstrip("/")
        self._http_timeout = http_timeout

        # Token cache (in-memory + optional disk)
        self._cache_path: Optional[Path] = (
            Path(token_cache_path) if token_cache_path is not None else None
        )
        self._token_cache: Dict[str, Dict[str, Any]] = (
            _load_token_cache(self._cache_path)
            if self._cache_path is not None
            else {}
        )

        logger.info(
            "SqueezeOSClient initialised — wallet=%s domain=%s",
            self.wallet_address,
            self.agent_domain,
        )

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------

    @property
    def wallet_address(self) -> str:
        """Classic XRPL address (rADDRESS) of the agent wallet."""
        return self._wallet.classic_address

    # ------------------------------------------------------------------
    # Paid API methods
    # ------------------------------------------------------------------

    def council(self, symbol: str) -> Dict[str, Any]:
        """
        AI council verdict for *symbol*.

        Aggregates SML Fractal Cascade, Battle Computer, and Gamma Flow
        Engine signals into a regime classification, directional bias,
        confidence score, and institutional trading thesis.

        Cost: 0.10 RLUSD

        Parameters
        ----------
        symbol : str
            Equity ticker, e.g. "IWM", "SPY", "QQQ".

        Returns
        -------
        dict
            CouncilVerdict — see openapi.json for schema.
        """
        endpoint = ENDPOINTS["council"]
        return self._call(
            endpoint,
            method="POST",
            json_body={"symbol": symbol.upper()},
        )

    def scan(self) -> Dict[str, Any]:
        """
        Full $1–$50 market universe squeeze scanner.

        Scores every qualifying equity using the 8-module SML engine and
        returns all setups ranked by squeeze score.

        Cost: 0.05 RLUSD

        Returns
        -------
        dict
            ScanResponse — list of ScanResult objects with scores, regime,
            signal, and options pick recommendations.
        """
        endpoint = ENDPOINTS["scan"]
        return self._call(endpoint, method="GET")

    def options(self, symbol: str = "IWM") -> Dict[str, Any]:
        """
        Institutional options intelligence for *symbol*.

        Detects institutional sweeps, whale premium blocks, unusual volume,
        and scores top contract recommendations.  Includes net delta, GEX,
        put/call ratios, and max pain.

        Cost: 0.05 RLUSD

        Parameters
        ----------
        symbol : str
            Equity ticker.  Defaults to "IWM".

        Returns
        -------
        dict
            OptionsResponse — sweeps, whales, unusual_volume, recommendations,
            flow_summary.
        """
        endpoint = ENDPOINTS["options"]
        return self._call(endpoint, method="GET", params={"symbol": symbol.upper()})

    def iwm(self) -> Dict[str, Any]:
        """
        IWM zero-day-to-expiry scanner with Greeks.

        Scores 0DTE IWM contracts by delta/gamma profile, bid-ask spread,
        and volume/OI ratio.  Identifies gamma flip levels and max pain.

        Cost: 0.03 RLUSD

        Returns
        -------
        dict
            IwmResponse — contracts[], gamma_flip_level, max_pain, spot.
        """
        endpoint = ENDPOINTS["iwm"]
        return self._call(endpoint, method="GET")

    # ------------------------------------------------------------------
    # Loyalty / passport
    # ------------------------------------------------------------------

    def loyalty_status(self) -> Dict[str, Any]:
        """
        Retrieve the Agent Passport and loyalty tier for this wallet.

        Returns tier (Bronze → Diamond), lifetime spend, free-call balance,
        effective cost multiplier, and next-tier distance.  No payment required.

        Returns
        -------
        dict
            LoyaltyStatus schema from 402Proof.
        """
        url = f"{self._proof402_url}/v1/agent/{self.wallet_address}"
        resp = requests.get(url, timeout=self._http_timeout)
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Internal payment machinery
    # ------------------------------------------------------------------

    def _call(
        self,
        endpoint: Dict[str, Any],
        *,
        method: str = "GET",
        json_body: Optional[Dict] = None,
        params: Optional[Dict] = None,
        _retry: bool = True,
    ) -> Dict[str, Any]:
        """
        Make an authenticated call to a paid SqueezeOS endpoint.

        Checks the token cache first.  On a 402 response, pays automatically
        and retries once.
        """
        endpoint_id = endpoint["endpoint_id"]
        token = self._get_cached_token(endpoint_id)

        headers = {
            "X-Agent-Wallet": self.wallet_address,
            "Content-Type": "application/json",
        }
        if token:
            headers["X-Payment-Token"] = token

        url = f"{self._squeezeos_url}{endpoint['path']}"

        resp = requests.request(
            method,
            url,
            headers=headers,
            json=json_body,
            params=params,
            timeout=self._http_timeout,
        )

        if resp.status_code == 402 and _retry:
            logger.info(
                "Received 402 for %s — initiating RLUSD payment", endpoint["path"]
            )
            body = resp.json()
            invoice = body.get("invoice") or self._request_invoice(endpoint_id)
            access_token = self._pay_and_verify(invoice)
            self._cache_token(endpoint_id, access_token)
            # Retry with token — _retry=False prevents infinite loop
            return self._call(
                endpoint,
                method=method,
                json_body=json_body,
                params=params,
                _retry=False,
            )

        if not resp.ok:
            raise SqueezeOSError(
                f"HTTP {resp.status_code} from {endpoint['path']}: {resp.text[:400]}"
            )

        return resp.json()

    def _get_cached_token(self, endpoint_id: str) -> Optional[str]:
        """
        Return a cached access token for *endpoint_id* if it is still valid.

        A token is considered valid when its expiry is more than
        _TOKEN_REFRESH_BUFFER_SECS seconds in the future.
        """
        entry = self._token_cache.get(endpoint_id)
        if not entry:
            return None
        token = entry.get("token", "")
        exp = entry.get("exp") or _parse_token_exp(token)
        if exp is None:
            return None
        if time.time() + _TOKEN_REFRESH_BUFFER_SECS < exp:
            logger.debug("Cache hit for endpoint_id=%s (exp=%s)", endpoint_id, exp)
            return token
        logger.debug("Cached token for endpoint_id=%s is expired", endpoint_id)
        return None

    def _cache_token(self, endpoint_id: str, token: str) -> None:
        """Store a token in memory and on disk."""
        exp = _parse_token_exp(token)
        self._token_cache[endpoint_id] = {"token": token, "exp": exp}
        if self._cache_path is not None:
            _save_token_cache(self._token_cache, self._cache_path)
        logger.info(
            "Token cached for endpoint_id=%s exp=%s", endpoint_id, exp
        )

    def _request_invoice(self, endpoint_id: str) -> Dict[str, Any]:
        """
        Request a fresh payment invoice from 402Proof.

        This is called when the 402 response body does not already contain
        an invoice (defensive path).
        """
        url = f"{self._proof402_url}/v1/invoice"
        resp = requests.post(
            url,
            json={"endpoint_id": endpoint_id},
            timeout=self._http_timeout,
        )
        resp.raise_for_status()
        invoice = resp.json()
        logger.info(
            "Invoice received: id=%s amount=%s %s",
            invoice.get("invoice_id"),
            invoice.get("amount"),
            invoice.get("asset"),
        )
        return invoice

    def _pay_and_verify(self, invoice: Dict[str, Any]) -> str:
        """
        Pay an invoice on the XRPL and return the verified access token.

        Steps:
          1. Submit an RLUSD Payment with the invoice memo_hex
          2. POST /v1/verify with invoice_id, tx_hash, agent_wallet
          3. Return the access_token from the verify response

        Raises
        ------
        SqueezeOSPaymentError
            If the XRPL transaction fails or 402Proof rejects the proof.
        """
        tx_hash = self._submit_xrpl_payment(invoice)
        logger.info("XRPL payment submitted: tx_hash=%s", tx_hash)
        return self._verify_payment(invoice["invoice_id"], tx_hash)

    def _submit_xrpl_payment(self, invoice: Dict[str, Any]) -> str:
        """
        Build, sign, and submit an RLUSD Payment transaction on the XRPL.

        Returns the confirmed transaction hash.
        """
        client = JsonRpcClient(self._xrpl_rpc_url)

        # 402Proof invoices always specify RLUSD amounts as a numeric value
        amount_value = str(invoice["amount"])
        destination  = invoice["pay_to"]
        memo_hex     = invoice["memo_hex"]

        payment = Payment(
            account=self._wallet.classic_address,
            destination=destination,
            amount=_rlusd_amount(amount_value),
            memos=[_build_rlusd_memo(memo_hex)],
            # Prevent payment through intermediary offers that could alter amount
            send_max=IssuedCurrencyAmount(
                currency=RLUSD_CURRENCY,
                issuer=RLUSD_ISSUER,
                value=amount_value,
            ),
        )

        signed_tx = autofill_and_sign(payment, client, self._wallet)
        result = submit_and_wait(signed_tx, client)

        meta = result.result.get("meta") or result.result.get("metaData") or {}
        tx_result = meta.get("TransactionResult", "")

        if tx_result != "tesSUCCESS":
            raise SqueezeOSPaymentError(
                f"XRPL payment failed: {tx_result} — {result.result}"
            )

        tx_hash = result.result.get("hash") or result.result.get("tx_json", {}).get("hash")
        if not tx_hash:
            raise SqueezeOSPaymentError("XRPL response contained no transaction hash")

        return tx_hash

    def _verify_payment(self, invoice_id: str, tx_hash: str) -> str:
        """
        Submit the XRPL transaction hash to 402Proof and retrieve an access token.

        Returns
        -------
        str
            Signed access token for use as X-Payment-Token header.
        """
        url = f"{self._proof402_url}/v1/verify"
        payload = {
            "invoice_id":   invoice_id,
            "tx_hash":      tx_hash,
            "agent_wallet": self.wallet_address,
            "agent_domain": self.agent_domain,
        }
        resp = requests.post(url, json=payload, timeout=self._http_timeout)

        if not resp.ok:
            raise SqueezeOSPaymentError(
                f"402Proof verification failed ({resp.status_code}): {resp.text[:400]}"
            )

        data = resp.json()
        token = data.get("access_token")
        if not token:
            raise SqueezeOSPaymentError(
                f"402Proof returned no access_token: {data}"
            )

        logger.info(
            "Payment verified — receipt_id=%s risk_level=%s",
            data.get("receipt_id"),
            data.get("risk_level"),
        )
        return token


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class SqueezeOSError(Exception):
    """Base exception for all SqueezeOS SDK errors."""


class SqueezeOSPaymentError(SqueezeOSError):
    """Raised when the XRPL payment or 402Proof verification step fails."""


# ---------------------------------------------------------------------------
# Usage example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import os
    import pprint
    import logging

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    # ----------------------------------------------------------------
    # Configuration — set AGENT_XRPL_SEED in your environment.
    # The wallet must have:
    #   - Sufficient XRP for reserves and transaction fees (~2 XRP minimum)
    #   - An RLUSD trust line to rMxCKbEDwqr76QuheSUMdEGf4B9xJ8m5De
    #   - RLUSD balance sufficient for at least one call (0.10 RLUSD for council)
    # ----------------------------------------------------------------
    seed = os.environ.get("AGENT_XRPL_SEED")
    if not seed:
        raise SystemExit(
            "Set AGENT_XRPL_SEED in your environment before running this example."
        )

    client = SqueezeOSClient(
        xrpl_seed=seed,
        agent_domain="sdk-example.scriptmasterlabs.com",
    )

    print(f"\nAgent wallet: {client.wallet_address}")

    # Check loyalty tier before making paid calls
    print("\n--- Loyalty Status ---")
    loyalty = client.loyalty_status()
    pprint.pprint(loyalty)

    # Council verdict for IWM (0.10 RLUSD — token cached after first call)
    print("\n--- Council Verdict: IWM ---")
    verdict = client.council("IWM")
    pprint.pprint(verdict)

    # Second council call for SPY reuses the cached IWM token only if the
    # endpoint_id matches.  Council has one endpoint_id for all symbols, so
    # this call is free within the token TTL.
    print("\n--- Council Verdict: SPY (cached token) ---")
    verdict_spy = client.council("SPY")
    pprint.pprint(verdict_spy)

    # IWM 0DTE scan (0.03 RLUSD — separate endpoint, separate payment)
    print("\n--- IWM 0DTE Contracts ---")
    iwm_data = client.iwm()
    pprint.pprint(iwm_data)
