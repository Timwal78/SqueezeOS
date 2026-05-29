"""
XRPL payment verifier for Stigmergy Protocol.

Fail-closed: if the ledger is unreachable, verification fails rather than
letting unverified payment claims through.

Uses the public XRPL JSON-RPC API (HTTP POST) with three-node fallback.
No API key required — XRPL is a public ledger.
"""

import re
import logging
import requests

logger = logging.getLogger("SqueezeOS-XRPLVerify")

RLUSD_ISSUER       = "rMxCKbEDwqr76QuheSUMdEGf4B9xJ8m5De"
RLUSD_CURRENCY     = "RLUSD"
RLUSD_CURRENCY_HEX = "524C555344000000000000000000000000000000"

_TX_HASH_RE = re.compile(r"^[0-9A-Fa-f]{64}$")

_XRPL_NODES = [
    "https://xrplcluster.com",
    "https://s1.ripple.com:51234",
    "https://s2.ripple.com:51234",
]
_TIMEOUT = 10  # seconds per node


def _validate_hash_format(tx_hash: str) -> None:
    if not _TX_HASH_RE.match(tx_hash or ""):
        raise ValueError(f"Invalid tx_hash format — expected 64 hex chars, got: {tx_hash!r}")


def _fetch_tx(tx_hash: str) -> dict:
    """
    Fetch a transaction from the XRPL public ledger.
    Tries nodes in order. Returns the `result` dict on success.
    Raises ValueError if all nodes fail or if the tx is not found.
    """
    payload = {
        "method": "tx",
        "params": [{"transaction": tx_hash, "binary": False}],
    }
    last_exc: Exception = RuntimeError("no nodes tried")
    for node in _XRPL_NODES:
        try:
            resp = requests.post(node, json=payload, timeout=_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            result = data.get("result", {})
            if result.get("status") == "success":
                return result
            # API returned an error result (e.g. txnNotFound)
            last_exc = ValueError(
                result.get("error_message")
                or result.get("error")
                or "XRPL returned error status"
            )
        except requests.RequestException as e:
            last_exc = e
            logger.warning(f"[XRPL-VERIFY] node {node} unreachable: {e}")
        except Exception as e:
            last_exc = e
            logger.warning(f"[XRPL-VERIFY] node {node} error: {e}")
    raise ValueError(f"XRPL ledger unreachable (all nodes failed): {last_exc}")


def verify_rlusd_payment(
    tx_hash: str,
    expected_destination: str,
    expected_amount_rlusd: float,
    tolerance_rlusd: float = 0.0001,
) -> float:
    """
    Verify that an XRPL transaction is a validated, successful RLUSD Payment
    to the correct destination for (approximately) the correct amount.

    Checks in order:
      1. tx_hash is 64 hex chars
      2. Transaction exists in a validated ledger
      3. TransactionResult == tesSUCCESS
      4. TransactionType == Payment
      5. Destination == expected_destination
      6. Amount.currency == RLUSD from issuer rMxCKbEDwqr76QuheSUMdEGf4B9xJ8m5De
      7. Amount.value within tolerance of expected_amount_rlusd

    Returns the actual paid amount (float) on success.
    Raises ValueError with a human-readable reason on any failure.
    """
    _validate_hash_format(tx_hash)

    result = _fetch_tx(tx_hash)

    if not result.get("validated", False):
        raise ValueError(
            "Transaction is not yet validated — it may still be in-flight. "
            "Wait a few seconds and retry."
        )

    # XRPL HTTP JSON-RPC places tx fields directly in `result`.
    # XRPL WebSocket wraps them in `result.tx_json`.
    # Handle both shapes defensively.
    tx   = result.get("tx_json") or result
    meta = result.get("meta", {})

    tx_result = meta.get("TransactionResult", "")
    if tx_result and tx_result != "tesSUCCESS":
        raise ValueError(f"Transaction was rejected on the ledger: {tx_result}")

    tx_type = tx.get("TransactionType", "")
    if tx_type != "Payment":
        raise ValueError(f"Transaction type is {tx_type!r}, expected Payment")

    destination = tx.get("Destination", "")
    if destination != expected_destination:
        raise ValueError(
            f"Payment went to wrong destination. "
            f"Expected {expected_destination[:16]}…, got {destination[:16] if destination else 'none'}…"
        )

    amount = tx.get("Amount", {})
    if isinstance(amount, str):
        raise ValueError("Payment is in XRP drops, not RLUSD — send RLUSD IOU")
    if not isinstance(amount, dict):
        raise ValueError("Cannot parse Amount field in transaction")

    currency = amount.get("currency", "")
    issuer   = amount.get("issuer",   "")

    if currency not in (RLUSD_CURRENCY, RLUSD_CURRENCY_HEX):
        raise ValueError(f"Wrong currency: {currency!r} — send RLUSD from the correct issuer")

    if issuer != RLUSD_ISSUER:
        raise ValueError(
            f"RLUSD issuer mismatch: got {issuer}, "
            f"expected {RLUSD_ISSUER}"
        )

    paid = float(amount.get("value", "0"))
    if abs(paid - expected_amount_rlusd) > tolerance_rlusd:
        raise ValueError(
            f"Amount mismatch: sent {paid} RLUSD, "
            f"expected {expected_amount_rlusd} RLUSD (±{tolerance_rlusd})"
        )

    logger.info(
        f"[XRPL-VERIFY] ✓ {paid} RLUSD → {destination[:20]}… "
        f"tx={tx_hash[:12]}…"
    )
    return paid
