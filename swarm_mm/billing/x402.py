"""x402 payment challenge helpers for swarm-mm — multi-rail.

Rails: Base USDC, Solana USDC, Robinhood USDG (USCG alias), XRPL RLUSD.
Operator bypass: X-Operator-Key == SML_API_KEY (server-side only).
"""

from __future__ import annotations

import os
import secrets
from typing import Any, Optional

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from swarm_mm.billing.rails import (
    build_accepts,
    evm_pay_to,
    pay_to_by_network,
    rails_public,
    accepts_asset_map,
)
from swarm_mm.core.config import (
    OPERATOR_KEY_ENV,
    PRICE_B2B_OPTIMIZE_USD,
    PRICE_B2B_PLATFORM_USD,
    PRICE_B2B_REPORT_USD,
    PRICE_BROKER_ORDERS_USD,
    PRICE_LEVELS_CALL_USD,
    PRICE_REBATE_TRACKER_USD,
    PRICE_SIGNAL_SUB_USD,
    PRICE_SIM_PREMIUM_USD,
    PRICE_VENUE_MAP_USD,
)


def get_pay_to() -> str:
    return evm_pay_to()


def operator_authorized(
    x_operator_key: Optional[str] = None,
    x_sml_api_key: Optional[str] = None,
) -> bool:
    expected = os.environ.get(OPERATOR_KEY_ENV, "").strip()
    if not expected:
        return os.environ.get("SWARM_MM_DEV_OPEN", "1") == "1"
    got = (x_operator_key or x_sml_api_key or "").strip()
    return bool(got) and secrets.compare_digest(got, expected)


def x402_challenge(price_usd: float, resource: str, description: str = "") -> dict[str, Any]:
    accepts = build_accepts(price_usd, resource, description)
    return {
        "x402Version": 1,
        "error": "Payment required",
        "accepts": accepts,
        "payToByNetwork": pay_to_by_network(),
        "acceptsAsset": accepts_asset_map(),
        "price_usd": price_usd,
        "rails": rails_public()["rails"],
        "settle_in": ["USDC", "USDG", "RLUSD"],
    }


def payment_response(price_usd: float, resource: str, description: str = "") -> JSONResponse:
    body = x402_challenge(price_usd, resource, description)
    return JSONResponse(status_code=402, content=body, headers={"X-Payment-Required": "true"})


async def require_payment_or_operator(
    request: Request,
    price_usd: float,
    resource: str,
    description: str = "",
    x_operator_key: Optional[str] = None,
    x_payment: Optional[str] = None,
    x_payment_hash: Optional[str] = None,
) -> dict[str, Any]:
    if price_usd <= 0:
        return {"paid": False, "free": True, "price_usd": 0.0}

    if x_operator_key is None:
        x_operator_key = request.headers.get("X-Operator-Key") or request.headers.get("x-operator-key")
    if x_payment is None:
        x_payment = request.headers.get("X-PAYMENT") or request.headers.get("x-payment")
    if x_payment_hash is None:
        x_payment_hash = request.headers.get("X-Payment-Hash") or request.headers.get("x-payment-hash")

    if operator_authorized(x_operator_key):
        return {"paid": True, "via": "operator", "price_usd": price_usd}

    mode = os.environ.get("SWARM_MM_PAYMENT_VERIFY", "soft").lower()
    proof = (x_payment or x_payment_hash or "").strip()
    if proof:
        if mode == "strict":
            raise HTTPException(
                status_code=501,
                detail="strict payment verify not wired in swarm-mm MVP — use operator key or soft mode",
            )
        return {"paid": True, "via": "x402_proof_soft", "price_usd": price_usd, "proof_prefix": proof[:18]}

    raise PaymentRequired(price_usd=price_usd, resource=resource, description=description)


class PaymentRequired(Exception):
    def __init__(self, price_usd: float, resource: str, description: str = "") -> None:
        self.price_usd = price_usd
        self.resource = resource
        self.description = description
        super().__init__("payment_required")


def well_known_resources() -> dict[str, Any]:
    pay_to = get_pay_to()
    resources = [
        # Free
        {"resource": "/v1/sim/join", "description": "Join simulated swarm (FREE)", "price_usd": 0.0, "variant": "D", "tier": "free"},
        {"resource": "/v1/sim/trade", "description": "Paper trade (FREE)", "price_usd": 0.0, "variant": "D", "tier": "free"},
        {"resource": "/v1/sim/leaderboard", "description": "Sim leaderboard (FREE)", "price_usd": 0.0, "variant": "D", "tier": "free"},
        {"resource": "/v1/sim/upgrade", "description": "Upgrade funnel (FREE)", "price_usd": 0.0, "variant": "D", "tier": "free"},
        {"resource": "/health", "description": "Health (FREE)", "price_usd": 0.0, "tier": "free"},
        {"resource": "/v1/pricing", "description": "Full pricing card (FREE)", "price_usd": 0.0, "tier": "free"},
        {"resource": "/mcp/tools", "description": "MCP catalog (FREE)", "price_usd": 0.0, "tier": "free"},
        # Agent pay-per-call
        {"resource": "/v1/signal/levels", "description": "Signal swarm limit-order levels", "price_usd": PRICE_LEVELS_CALL_USD, "variant": "A", "tier": "ppc"},
        {"resource": "/v1/signal/venue-map", "description": "Venue allocation map", "price_usd": PRICE_VENUE_MAP_USD, "variant": "A", "tier": "ppc"},
        {"resource": "/v1/signal/rebate-tracker", "description": "Maker rebate estimate", "price_usd": PRICE_REBATE_TRACKER_USD, "variant": "A", "tier": "ppc"},
        {"resource": "/v1/signal/broker-orders", "description": "Broker order preview (user submits)", "price_usd": PRICE_BROKER_ORDERS_USD, "variant": "A", "tier": "ppc"},
        {"resource": "/v1/b2b/optimize", "description": "B2B optimize pass", "price_usd": PRICE_B2B_OPTIMIZE_USD, "variant": "C", "tier": "ppc"},
        {"resource": "/v1/b2b/report", "description": "B2B performance report", "price_usd": PRICE_B2B_REPORT_USD, "variant": "C", "tier": "ppc"},
        {"resource": "/v1/crypto/positions", "description": "Crypto swarm positions", "price_usd": PRICE_LEVELS_CALL_USD, "variant": "B", "tier": "ppc"},
        # Monthly crypto
        {"resource": "/v1/billing/subscribe/sim_premium", "description": "Sim Premium monthly", "price_usd": PRICE_SIM_PREMIUM_USD, "variant": "D", "tier": "monthly", "interval": "month"},
        {"resource": "/v1/billing/subscribe/signal", "description": "Signal Swarm monthly", "price_usd": PRICE_SIGNAL_SUB_USD, "variant": "A", "tier": "monthly", "interval": "month"},
        {"resource": "/v1/billing/subscribe/b2b", "description": "B2B Platform monthly", "price_usd": PRICE_B2B_PLATFORM_USD, "variant": "C", "tier": "monthly", "interval": "month"},
    ]
    rails = rails_public()
    return {
        "x402Version": 1,
        "product": "swarm-mm",
        "company": "Script Master Labs",
        "payTo": pay_to,
        "networks": list(rails["payToByNetwork"].keys()),
        "payToByNetwork": rails["payToByNetwork"],
        "acceptsAsset": rails["acceptsAsset"],
        "rails": rails["rails"],
        "monthly_crypto": ["USDC", "SOL_USDC", "RLUSD", "USDG"],
        "agent_pay_per_call": True,
        "resources": resources,
    }
