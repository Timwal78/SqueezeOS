"""Multi-rail payment accepts for Swarm MM.

Monthly + pay-per-call can settle in:
  - USDC on Base (8453)          — primary
  - USDC on Solana mainnet       — SPL
  - USDG on Robinhood Chain 4663 — same ACP EOA
  - RLUSD on XRPL                — when XRPL_PAYMENT_RECEIVER set

Note: "USCG" in operator speak maps to **USDG** (Global Dollar on RH chain).
"""

from __future__ import annotations

import os
from typing import Any

from swarm_mm.core.config import (
    BASE_CHAIN_ID,
    BASE_USDC,
    ROBINHOOD_CHAIN_ID,
    SML_PAYMENT_RECEIVER,
    SOLANA_CAIP2,
    SOLANA_PAYMENT_RECEIVER,
    SOLANA_USDC_MINT,
    USDG_PAYMENT_RECEIVER,
    USDG_ROBINHOOD,
    XRPL_PAYMENT_RECEIVER,
)


def evm_pay_to() -> str:
    return os.environ.get("SML_PAYMENT_RECEIVER", SML_PAYMENT_RECEIVER)


def sol_pay_to() -> str:
    return os.environ.get("SOLANA_PAYMENT_RECEIVER", SOLANA_PAYMENT_RECEIVER)


def usdg_pay_to() -> str:
    return os.environ.get("USDG_PAYMENT_RECEIVER", USDG_PAYMENT_RECEIVER or evm_pay_to())


def xrpl_pay_to() -> str:
    return os.environ.get("XRPL_PAYMENT_RECEIVER", XRPL_PAYMENT_RECEIVER).strip()


def amount_units(price_usd: float, decimals: int = 6) -> str:
    return str(int(round(float(price_usd) * (10**decimals))))


def build_accepts(price_usd: float, resource: str, description: str = "") -> list[dict[str, Any]]:
    """x402 accepts[] for all live rails."""
    desc = description or f"swarm-mm {resource}"
    amt = amount_units(price_usd, 6)
    accepts: list[dict[str, Any]] = [
        {
            "scheme": "exact",
            "network": f"eip155:{BASE_CHAIN_ID}",
            "maxAmountRequired": amt,
            "resource": resource,
            "description": desc,
            "mimeType": "application/json",
            "payTo": evm_pay_to(),
            "maxTimeoutSeconds": 300,
            "asset": BASE_USDC,
            "extra": {"name": "USDC", "symbol": "USDC", "decimals": 6, "rail": "base_usdc"},
        },
        {
            "scheme": "exact",
            "network": SOLANA_CAIP2,
            "maxAmountRequired": amt,
            "resource": resource,
            "description": desc,
            "mimeType": "application/json",
            "payTo": sol_pay_to(),
            "maxTimeoutSeconds": 300,
            "asset": SOLANA_USDC_MINT,
            "extra": {"name": "USDC", "symbol": "USDC", "decimals": 6, "rail": "solana_usdc"},
        },
        {
            "scheme": "exact",
            "network": f"eip155:{ROBINHOOD_CHAIN_ID}",
            "maxAmountRequired": amt,
            "resource": resource,
            "description": desc,
            "mimeType": "application/json",
            "payTo": usdg_pay_to(),
            "maxTimeoutSeconds": 300,
            "asset": USDG_ROBINHOOD,
            "extra": {
                "name": "USDG",
                "symbol": "USDG",
                "decimals": 6,
                "rail": "robinhood_usdg",
                "alias": "USCG",  # operator shorthand
            },
        },
    ]
    xrpl = xrpl_pay_to()
    if xrpl:
        # RLUSD typically 6 decimals on XRPL issued currency accounting in drops-equivalent units for challenge
        accepts.append(
            {
                "scheme": "exact",
                "network": "xrpl:0",  # XRPL mainnet CAIP-ish
                "maxAmountRequired": amt,
                "resource": resource,
                "description": desc,
                "mimeType": "application/json",
                "payTo": xrpl,
                "maxTimeoutSeconds": 300,
                "asset": "RLUSD",
                "extra": {
                    "name": "RLUSD",
                    "symbol": "RLUSD",
                    "decimals": 6,
                    "rail": "xrpl_rlusd",
                    "issuer_env": "RLUSD_ISSUER",
                },
            }
        )
    return accepts


def pay_to_by_network() -> dict[str, str]:
    out = {
        f"eip155:{BASE_CHAIN_ID}": evm_pay_to(),
        SOLANA_CAIP2: sol_pay_to(),
        f"eip155:{ROBINHOOD_CHAIN_ID}": usdg_pay_to(),
    }
    xrpl = xrpl_pay_to()
    if xrpl:
        out["xrpl:0"] = xrpl
    return out


def accepts_asset_map() -> dict[str, str]:
    out = {
        f"eip155:{BASE_CHAIN_ID}": BASE_USDC,
        SOLANA_CAIP2: SOLANA_USDC_MINT,
        f"eip155:{ROBINHOOD_CHAIN_ID}": USDG_ROBINHOOD,
    }
    if xrpl_pay_to():
        out["xrpl:0"] = "RLUSD"
    return out


def rails_public() -> dict[str, Any]:
    """Human + agent readable rail card for ads and /v1/pricing."""
    return {
        "monthly_and_ppc_settle_in": ["USDC", "SOL_USDC", "RLUSD", "USDG"],
        "alias_note": "USCG in copy = USDG (Global Dollar on Robinhood Chain 4663)",
        "rails": [
            {
                "id": "base_usdc",
                "symbol": "USDC",
                "network": f"eip155:{BASE_CHAIN_ID}",
                "chain": "Base",
                "asset": BASE_USDC,
                "payTo": evm_pay_to(),
                "primary": True,
            },
            {
                "id": "solana_usdc",
                "symbol": "USDC",
                "network": SOLANA_CAIP2,
                "chain": "Solana",
                "asset": SOLANA_USDC_MINT,
                "payTo": sol_pay_to(),
            },
            {
                "id": "robinhood_usdg",
                "symbol": "USDG",
                "aliases": ["USCG"],
                "network": f"eip155:{ROBINHOOD_CHAIN_ID}",
                "chain": "Robinhood Chain",
                "asset": USDG_ROBINHOOD,
                "payTo": usdg_pay_to(),
            },
            {
                "id": "xrpl_rlusd",
                "symbol": "RLUSD",
                "network": "xrpl:0",
                "chain": "XRPL",
                "asset": "RLUSD",
                "payTo": xrpl_pay_to() or None,
                "status": "live" if xrpl_pay_to() else "set_XRPL_PAYMENT_RECEIVER",
            },
        ],
        "payToByNetwork": pay_to_by_network(),
        "acceptsAsset": accepts_asset_map(),
    }
