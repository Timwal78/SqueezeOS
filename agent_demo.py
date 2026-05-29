"""
SqueezeOS Agent Demo
====================
Standalone walkthrough of the complete x402 pay-and-call flow.

No SDK dependency — uses only stdlib, requests, and xrpl-py so you can
read every step as plainly as possible.

REQUIREMENTS
------------
    pip install requests xrpl-py

ENVIRONMENT
-----------
    AGENT_XRPL_SEED   — XRPL family-seed for your agent wallet.
                        The wallet must hold RLUSD and have a trust line to
                        rMxCKbEDwqr76QuheSUMdEGf4B9xJ8m5De.

DEMO MODE
---------
Set DEMO_MODE = True to skip actual on-chain payment and see what the agent
would do at each step.  Useful when you don't have RLUSD yet, or are
evaluating integration on testnet.
"""

from __future__ import annotations

import os
import sys
import json
import time
import textwrap
from typing import Any, Dict, Optional

import requests

# ---------------------------------------------------------------------------
# Configuration — edit these or supply via environment
# ---------------------------------------------------------------------------

DEMO_MODE       = True          # Flip to False for a live end-to-end run
SYMBOL          = "IWM"         # Symbol to query via /api/council

SQUEEZEOS_URL   = "https://squeezeos-api.onrender.com"
PROOF402_URL    = "https://four02proof.onrender.com"
XRPL_RPC        = "https://s1.ripple.com:51234/"

RLUSD_ISSUER   = "rMxCKbEDwqr76QuheSUMdEGf4B9xJ8m5De"
RLUSD_CURRENCY = "RLUSD"

COUNCIL_ENDPOINT_ID = "12a0e7a1-6812-4c3f-aa24-de6e3bc12b5a"
COUNCIL_PATH        = "/api/council"
COUNCIL_PRICE       = "0.10 RLUSD"


# ---------------------------------------------------------------------------
# Step helpers
# ---------------------------------------------------------------------------

def _banner(step: int, title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  Step {step}: {title}")
    print(f"{'='*60}")


def _json_pp(data: Any, indent: int = 2) -> None:
    print(json.dumps(data, indent=indent, default=str))


def _demo_note(msg: str) -> None:
    print(f"\n  [DEMO MODE] {msg}")


# ---------------------------------------------------------------------------
# Step 1 — Call the endpoint (expect HTTP 402)
# ---------------------------------------------------------------------------

def step1_call_endpoint(agent_wallet: str) -> Dict[str, Any]:
    """
    Hit /api/council without a payment token.

    The server responds with HTTP 402 Payment Required and an invoice
    embedded in the response body.
    """
    _banner(1, f"Calling {COUNCIL_PATH} for {SYMBOL} (expecting 402)")

    url = f"{SQUEEZEOS_URL}{COUNCIL_PATH}"
    headers = {"X-Agent-Wallet": agent_wallet, "Content-Type": "application/json"}

    print(f"  POST {url}")
    print(f"  Body: {{\"symbol\": \"{SYMBOL}\"}}")

    resp = requests.post(
        url,
        headers=headers,
        json={"symbol": SYMBOL},
        timeout=15,
    )

    print(f"\n  HTTP {resp.status_code} received")

    if resp.status_code == 200:
        print("  NOTE: endpoint returned 200 — already paid or payment not enforced.")
        return {"status": "already_paid", "data": resp.json()}

    if resp.status_code != 402:
        resp.raise_for_status()

    body = resp.json()
    invoice = body.get("invoice", {})
    instructions = body.get("instructions", {})

    print("\n  Invoice received:")
    _json_pp(invoice)
    if instructions:
        print("\n  Payment instructions:")
        for k, v in instructions.items():
            print(f"    {k}: {v}")

    return invoice


# ---------------------------------------------------------------------------
# Step 2 — Submit RLUSD payment on the XRPL
# ---------------------------------------------------------------------------

def step2_pay_rlusd(invoice: Dict[str, Any], wallet) -> str:
    """
    Build, sign, and submit an RLUSD Payment to the XRPL.

    In DEMO_MODE this is skipped and a placeholder hash is returned so you
    can trace the full flow without spending real RLUSD.
    """
    _banner(2, f"Paying {COUNCIL_PRICE} RLUSD on XRPL")

    destination = invoice.get("pay_to", "<pay_to>")
    amount_val  = str(invoice.get("amount", "0.10"))
    memo_hex    = invoice.get("memo_hex", "<memo_hex>")

    print(f"  Destination : {destination}")
    print(f"  Amount      : {amount_val} {RLUSD_CURRENCY}")
    print(f"  Memo (hex)  : {memo_hex}")
    print(f"  From wallet : {wallet.classic_address if wallet else '<wallet>'}")

    if DEMO_MODE:
        _demo_note(
            "Skipping on-chain payment in DEMO_MODE.\n"
            "  In a live run, the SDK would:\n"
            "    a) Construct an XRPL Payment with the RLUSD IssuedCurrencyAmount\n"
            "    b) Attach the memo_hex as MemoData\n"
            "    c) autofill_and_sign() → submit_and_wait()\n"
            "    d) Confirm tesSUCCESS in the transaction metadata"
        )
        fake_hash = "A" * 64
        print(f"\n  [DEMO] Simulated tx hash: {fake_hash}")
        return fake_hash

    # --- Live path ---------------------------------------------------------
    from xrpl.models.transactions import Payment, Memo
    from xrpl.models.amounts import IssuedCurrencyAmount
    from xrpl.transaction import autofill_and_sign, submit_and_wait
    from xrpl.clients import JsonRpcClient

    client = JsonRpcClient(XRPL_RPC)

    rlusd_amount = IssuedCurrencyAmount(
        currency=RLUSD_CURRENCY,
        issuer=RLUSD_ISSUER,
        value=amount_val,
    )

    payment_tx = Payment(
        account=wallet.classic_address,
        destination=destination,
        amount=rlusd_amount,
        memos=[Memo(memo_data=memo_hex)],
        send_max=rlusd_amount,  # prevent DEX slippage
    )

    print("\n  Signing and submitting transaction…")
    signed = autofill_and_sign(payment_tx, client, wallet)
    result = submit_and_wait(signed, client)

    meta = result.result.get("meta") or result.result.get("metaData") or {}
    tx_result = meta.get("TransactionResult", "UNKNOWN")
    print(f"  Transaction result: {tx_result}")

    if tx_result != "tesSUCCESS":
        raise RuntimeError(f"XRPL payment failed: {tx_result}")

    tx_hash = (
        result.result.get("hash")
        or result.result.get("tx_json", {}).get("hash")
    )
    print(f"  Transaction hash   : {tx_hash}")
    return tx_hash


# ---------------------------------------------------------------------------
# Step 3 — Verify payment with 402Proof and collect access token
# ---------------------------------------------------------------------------

def step3_verify(
    invoice_id: str,
    tx_hash: str,
    agent_wallet: str,
) -> str:
    """
    Submit the XRPL transaction hash to 402Proof.

    On success, 402Proof returns a signed access token (1-hour TTL).
    The token encodes the paying wallet so the SqueezeOS server can enforce
    wallet binding when ENFORCE_WALLET_BINDING is enabled.
    """
    _banner(3, "Verifying payment with 402Proof")

    url = f"{PROOF402_URL}/v1/verify"
    payload = {
        "invoice_id":   invoice_id,
        "tx_hash":      tx_hash,
        "agent_wallet": agent_wallet,
        "agent_domain": "agent-demo.scriptmasterlabs.com",
    }

    print(f"  POST {url}")
    print(f"  Payload:")
    _json_pp(payload)

    if DEMO_MODE:
        _demo_note(
            "Skipping 402Proof verification in DEMO_MODE.\n"
            "  In a live run, 402Proof would:\n"
            "    a) Look up the invoice by invoice_id\n"
            "    b) Query the XRPL for the tx_hash and confirm MemoData matches\n"
            "    c) Confirm amount >= price and destination == pay_to\n"
            "    d) Issue a signed HMAC access token with 1-hour TTL\n"
            "    e) Record loyalty points for the paying wallet"
        )
        demo_token = (
            "eyJlaWQiOiIxMmEwZTdhMS02ODEyLTRjM2YtYWEyNC1kZTZlM2JjMTJiNWEi"
            "LCJ3bHQiOiJyREVNT1hSUEwxMjM0NTY3ODkiLCJleHAiOjk5OTk5OTk5OTl9"
            ".DEMO_SIGNATURE_NOT_VALID"
        )
        print(f"\n  [DEMO] Simulated access token:\n  {demo_token}")
        return demo_token

    resp = requests.post(url, json=payload, timeout=20)

    if not resp.ok:
        print(f"\n  ERROR: {resp.status_code} — {resp.text[:400]}")
        resp.raise_for_status()

    data = resp.json()
    print(f"\n  Verify response:")
    _json_pp(data)

    token = data.get("access_token")
    if not token:
        raise RuntimeError(f"No access_token in verify response: {data}")

    return token


# ---------------------------------------------------------------------------
# Step 4 — Retry the endpoint with the access token
# ---------------------------------------------------------------------------

def step4_call_with_token(access_token: str, agent_wallet: str) -> Dict[str, Any]:
    """
    Retry /api/council with the X-Payment-Token header set.

    The server validates the token locally (zero network round-trip) and
    returns the full council verdict.
    """
    _banner(4, f"Retrying {COUNCIL_PATH} with X-Payment-Token")

    url = f"{SQUEEZEOS_URL}{COUNCIL_PATH}"
    headers = {
        "X-Agent-Wallet":  agent_wallet,
        "X-Payment-Token": access_token,
        "Content-Type":    "application/json",
    }

    print(f"  POST {url}")
    print(f"  X-Payment-Token: {access_token[:40]}…")

    if DEMO_MODE:
        _demo_note(
            "Skipping live API call in DEMO_MODE.\n"
            "  In a live run, SqueezeOS would:\n"
            "    a) HMAC-verify the token locally (sub-millisecond, zero network)\n"
            "    b) Check token.endpoint_id matches the route's endpoint_id\n"
            "    c) Optionally verify X-Agent-Wallet == token.wlt (wallet binding)\n"
            "    d) Return the AI council verdict"
        )
        demo_verdict = {
            "symbol":           SYMBOL,
            "regime":           "EXECUTION",
            "lifecycle":        "Building",
            "directional_bias": "BULLISH",
            "confidence":       0.83,
            "squeeze_score":    78,
            "thesis": (
                "IWM is in an EXECUTION regime with a building momentum profile. "
                "Options flow shows institutional call sweeps at the 210 strike. "
                "Gamma flip is above spot — dealers are long gamma and will dampen "
                "intraday moves until price breaks the flip level."
            ),
            "engines": {
                "sml":        {"signal": "LONG", "score": 81},
                "battle":     {"bias": "BULL", "conviction": 0.79},
                "gamma_flow": {"gex": 142_000_000, "flip_level": 211.50},
            },
            "timestamp": "2026-05-18T00:00:00Z",
        }
        return demo_verdict

    resp = requests.post(
        url,
        headers=headers,
        json={"symbol": SYMBOL},
        timeout=30,
    )

    print(f"\n  HTTP {resp.status_code}")

    if not resp.ok:
        print(f"  ERROR: {resp.text[:400]}")
        resp.raise_for_status()

    return resp.json()


# ---------------------------------------------------------------------------
# Verdict display
# ---------------------------------------------------------------------------

def display_verdict(verdict: Dict[str, Any]) -> None:
    """Pretty-print the council verdict in a human-readable format."""
    _banner(5, "Council Verdict")

    symbol    = verdict.get("symbol", "?")
    regime    = verdict.get("regime", "?")
    lifecycle = verdict.get("lifecycle", "?")
    bias      = verdict.get("directional_bias", "?")
    conf      = verdict.get("confidence", 0)
    score     = verdict.get("squeeze_score", 0)
    thesis    = verdict.get("thesis", "")

    print(f"  Symbol         : {symbol}")
    print(f"  Regime         : {regime}")
    print(f"  Lifecycle      : {lifecycle}")
    print(f"  Directional    : {bias}")
    print(f"  Confidence     : {conf:.0%}")
    print(f"  Squeeze Score  : {score}/100")
    if thesis:
        print(f"\n  Thesis:")
        for line in textwrap.wrap(thesis, width=70):
            print(f"    {line}")

    engines = verdict.get("engines", {})
    if engines:
        print(f"\n  Engine signals :")
        for name, data in engines.items():
            print(f"    {name:12s}: {data}")

    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("\n" + "=" * 60)
    print("  SqueezeOS Agent Demo — x402 RLUSD Pay-and-Call Flow")
    print("=" * 60)

    if DEMO_MODE:
        print("\n  Running in DEMO_MODE — no real RLUSD will be spent.")
        print("  Set DEMO_MODE = False in this file for a live run.")

    # ----------------------------------------------------------------
    # Wallet setup
    # ----------------------------------------------------------------
    seed = os.environ.get("AGENT_XRPL_SEED")

    if DEMO_MODE and not seed:
        # Use a deterministic demo wallet address without touching XRPL
        agent_wallet_address = "rDemoXRPL1234567890AgentWalletPlaceholder"
        wallet = None
        print(f"\n  Demo wallet address : {agent_wallet_address}")
    else:
        if not seed:
            sys.exit(
                "\nERROR: Set AGENT_XRPL_SEED environment variable.\n"
                "  The wallet must have RLUSD and a trust line to:\n"
                f"  {RLUSD_ISSUER}"
            )
        try:
            from xrpl.wallet import Wallet
            wallet = Wallet.from_seed(seed)
            agent_wallet_address = wallet.classic_address
            print(f"\n  Agent wallet : {agent_wallet_address}")
        except Exception as exc:
            sys.exit(f"\nERROR: Could not derive wallet from seed — {exc}")

    # ----------------------------------------------------------------
    # Execute the 4-step flow
    # ----------------------------------------------------------------

    # Step 1: Hit endpoint, receive 402 + invoice
    result = step1_call_endpoint(agent_wallet_address)

    if isinstance(result, dict) and result.get("status") == "already_paid":
        print("\n  Endpoint returned 200 without payment — displaying result:")
        display_verdict(result["data"])
        return

    invoice = result

    # Step 2: Pay RLUSD on XRPL
    tx_hash = step2_pay_rlusd(invoice, wallet)

    # Step 3: Verify with 402Proof
    invoice_id = invoice.get("invoice_id", "DEMO_INVOICE_ID")
    access_token = step3_verify(invoice_id, tx_hash, agent_wallet_address)

    # Step 4: Retry with token
    verdict = step4_call_with_token(access_token, agent_wallet_address)

    # Display the verdict
    display_verdict(verdict)

    # ----------------------------------------------------------------
    # Token reuse note
    # ----------------------------------------------------------------
    print(
        "NOTE: The access token is valid for ~1 hour.\n"
        "      Cache it (e.g. in ~/.squeezeos_tokens.json) to avoid\n"
        "      re-paying for subsequent calls within the TTL window.\n"
        "      The SqueezeOSClient in squeezeos_sdk.py does this automatically."
    )


if __name__ == "__main__":
    main()
