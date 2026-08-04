"""Monthly crypto subscriptions for Swarm MM.

Plans settle in USDC (Base/Sol), USDG (RH 4663), or RLUSD (XRPL).
Soft proof mode accepts X-PAYMENT / X-Payment-Hash like pay-per-call.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from swarm_mm.billing.rails import build_accepts, rails_public
from swarm_mm.core.config import (
    DISCLAIMER,
    MECHANISM_ONE_LINER,
    PLAN_B2B,
    PLAN_SIGNAL,
    PLAN_SIM_FREE,
    PLAN_SIM_PREMIUM,
    PRICE_B2B_PLATFORM_USD,
    PRICE_SIGNAL_SUB_USD,
    PRICE_SIM_PREMIUM_USD,
)
from swarm_mm.core.state import store

PLANS: dict[str, dict[str, Any]] = {
    PLAN_SIM_FREE: {
        "id": PLAN_SIM_FREE,
        "name": "Sim Free",
        "variant": "D",
        "price_usd_mo": 0.0,
        "interval": "month",
        "free": True,
        "includes": [
            "Paper swarm join + virtual capital",
            "Sim limit orders vs market data",
            "Leaderboard + basic account stats",
            "Upgrade funnel to A/B/C",
        ],
        "excludes": ["Premium analytics", "Live signal stream priority"],
    },
    PLAN_SIM_PREMIUM: {
        "id": PLAN_SIM_PREMIUM,
        "name": "Sim Premium",
        "variant": "D",
        "price_usd_mo": PRICE_SIM_PREMIUM_USD,
        "interval": "month",
        "free": False,
        "includes": [
            "Everything in Sim Free",
            "Premium analytics + backtest engine access",
            "Priority sim ladder depth",
        ],
        "resource": "/v1/billing/subscribe/sim_premium",
    },
    PLAN_SIGNAL: {
        "id": PLAN_SIGNAL,
        "name": "Signal Swarm",
        "variant": "A",
        "price_usd_mo": PRICE_SIGNAL_SUB_USD,
        "interval": "month",
        "free": False,
        "includes": [
            "Limit-order level signals",
            "Venue map (maker-rebate weighted)",
            "Rebate tracker",
            "Broker order previews (Alpaca/Tradier/IBKR) — you submit",
            "WebSocket signal stream",
        ],
        "excludes": [
            "No capital custody",
            "No pooled execution",
            "No broker order submission by SML",
        ],
        "resource": "/v1/billing/subscribe/signal",
        "headline": "Default retail monthly",
    },
    PLAN_B2B: {
        "id": PLAN_B2B,
        "name": "B2B Platform",
        "variant": "C",
        "price_usd_mo": PRICE_B2B_PLATFORM_USD,
        "interval": "month",
        "free": False,
        "includes": [
            "White-label swarm engine",
            "Multi-tenant configure/optimize/report",
            "Customer owns KYC + licenses + capital",
        ],
        "add_on": "2% of incremental maker-rebate improvement",
        "resource": "/v1/billing/subscribe/b2b",
    },
}


def list_plans() -> dict[str, Any]:
    return {
        "product": "swarm-mm",
        "mechanism": MECHANISM_ONE_LINER,
        "plans": list(PLANS.values()),
        "agent_pay_per_call": {
            "levels": 0.001,
            "venue_map": 0.001,
            "rebate_tracker": 0.001,
            "broker_orders": 0.001,
            "b2b_optimize": 0.05,
            "b2b_report": 0.10,
        },
        "crypto_monthly": True,
        "rails": rails_public(),
        "disclaimer": DISCLAIMER,
    }


def _sub_key(user_id: str) -> str:
    return f"sub:{user_id}"


def get_subscription(user_id: str) -> dict[str, Any]:
    raw = store.get(_sub_key(user_id))
    if not raw:
        return {
            "user_id": user_id,
            "plan": PLAN_SIM_FREE,
            "status": "free",
            "price_usd_mo": 0.0,
            "features": PLANS[PLAN_SIM_FREE]["includes"],
        }
    # expiry check
    exp = raw.get("expires_at")
    if exp:
        try:
            exp_dt = datetime.fromisoformat(exp.replace("Z", "+00:00"))
            if exp_dt < datetime.now(timezone.utc):
                raw["status"] = "expired"
                store.set(_sub_key(user_id), raw)
        except Exception:
            pass
    return raw


def start_subscription(
    user_id: str,
    plan: str,
    rail: str = "base_usdc",
    payment_proof: Optional[str] = None,
    force: bool = False,
) -> dict[str, Any]:
    plan = (plan or "").strip().lower()
    if plan not in PLANS:
        raise ValueError(f"unknown plan '{plan}'. choose: {sorted(PLANS)}")
    meta = PLANS[plan]
    if meta["free"]:
        sub = {
            "user_id": user_id,
            "plan": plan,
            "status": "active",
            "price_usd_mo": 0.0,
            "rail": None,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": None,
            "features": meta["includes"],
            "subscription_id": str(uuid.uuid4()),
        }
        store.set(_sub_key(user_id), sub)
        return {"status": "active", "payment_required": False, "subscription": sub}

    price = float(meta["price_usd_mo"])
    resource = meta.get("resource") or f"/v1/billing/subscribe/{plan}"
    challenge = {
        "x402Version": 1,
        "error": "Payment required for monthly plan",
        "plan": plan,
        "price_usd": price,
        "interval": "month",
        "accepts": build_accepts(price, resource, f"Swarm MM {meta['name']} monthly"),
        "rails": rails_public()["rails"],
        "pay_instructions": (
            f"Send {price} stablecoin on any listed rail to the matching payTo, "
            f"then retry with header X-PAYMENT or X-Payment-Hash = tx hash/proof. "
            f"Preferred rail: {rail}."
        ),
    }
    if not payment_proof and not force:
        return {
            "status": "payment_required",
            "payment_required": True,
            "http_hint": 402,
            "challenge": challenge,
            "user_id": user_id,
            "plan": plan,
        }

    # Activate on soft proof / operator force
    now = datetime.now(timezone.utc)
    exp = now + timedelta(days=30)
    sub = {
        "user_id": user_id,
        "plan": plan,
        "status": "active",
        "price_usd_mo": price,
        "rail": rail,
        "payment_proof_prefix": (payment_proof or "operator")[:24],
        "started_at": now.isoformat(),
        "expires_at": exp.isoformat(),
        "features": meta["includes"],
        "subscription_id": str(uuid.uuid4()),
        "variant": meta["variant"],
    }
    store.set(_sub_key(user_id), sub)
    # index
    users = store.get("sub:users", []) or []
    if user_id not in users:
        users.append(user_id)
        store.set("sub:users", users)
    return {
        "status": "active",
        "payment_required": False,
        "subscription": sub,
        "next_renewal_usd": price,
        "disclaimer": DISCLAIMER,
    }


def cancel_subscription(user_id: str) -> dict[str, Any]:
    raw = get_subscription(user_id)
    if raw.get("plan") == PLAN_SIM_FREE and raw.get("status") == "free":
        return {"status": "already_free", "subscription": raw}
    raw["status"] = "cancelled"
    raw["cancelled_at"] = datetime.now(timezone.utc).isoformat()
    raw["plan"] = PLAN_SIM_FREE
    raw["price_usd_mo"] = 0.0
    store.set(_sub_key(user_id), raw)
    return {"status": "cancelled", "subscription": raw}


def pricing_card() -> dict[str, Any]:
    """Full public pricing: free portion, monthly, agent PPC, rails, mechanism."""
    return {
        "product": "Swarm Market Making",
        "company": "Script Master Labs",
        "mechanism": {
            "one_liner": MECHANISM_ONE_LINER,
            "steps": [
                "1. Intent aggregation — swarm sees size/side pressure across participants (or paper cohort).",
                "2. Ladder engine — builds resting limit prices around mid with confidence decay by depth.",
                "3. Venue weights — tilts to maker-rebate venues (IEX/MEMX/…) for expected fill quality.",
                "4. Signal delivery — HTTP + WebSocket + MCP; broker preview payloads for YOUR account.",
                "5. You execute — Variant A never custodies capital and never submits the order for you.",
            ],
            "why_gamechanging": (
                "Coordination without becoming a broker. The edge is shared microstructure "
                "intelligence (levels + venues + rebate estimate), not a pooled dark book."
            ),
        },
        "free": {
            "plan": "sim_free",
            "price_usd": 0,
            "includes": PLANS[PLAN_SIM_FREE]["includes"],
            "endpoints": [
                "POST /v1/sim/join",
                "POST /v1/sim/trade",
                "GET /v1/sim/leaderboard",
                "POST /v1/sim/upgrade",
                "GET /health",
                "GET /mcp/tools",
                "GET /.well-known/x402",
                "WS /ws/signals (subscribe snapshots)",
            ],
        },
        "monthly": [
            {
                "plan": PLAN_SIM_PREMIUM,
                "name": "Sim Premium",
                "usd": PRICE_SIM_PREMIUM_USD,
                "crypto": True,
                "best_for": "Prove the algo on paper with analytics",
            },
            {
                "plan": PLAN_SIGNAL,
                "name": "Signal Swarm",
                "usd": PRICE_SIGNAL_SUB_USD,
                "crypto": True,
                "best_for": "Retail — default paid monthly",
                "headline": True,
            },
            {
                "plan": PLAN_B2B,
                "name": "B2B Platform",
                "usd": PRICE_B2B_PLATFORM_USD,
                "crypto": True,
                "best_for": "Licensed brokers / prop / international BDs",
                "plus": "2% of incremental rebate lift",
            },
        ],
        "agent_pay_per_call": {
            "currency_stable": True,
            "floor_usd": 0.001,
            "tools": [
                {"tool": "signal_swarm.levels", "usd": 0.001},
                {"tool": "signal_swarm.venue_map", "usd": 0.001},
                {"tool": "signal_swarm.rebate_tracker", "usd": 0.001},
                {"tool": "signal_swarm.broker_orders", "usd": 0.001},
                {"tool": "b2b_swarm.optimize", "usd": 0.05},
                {"tool": "b2b_swarm.report", "usd": 0.10},
                {"tool": "crypto_swarm.positions", "usd": 0.001},
            ],
            "how": (
                "Agent hits paid route → HTTP 402 with accepts[] multi-rail → "
                "pays USDC/USDG/RLUSD → retries with X-PAYMENT proof → JSON result + receipt."
            ),
        },
        "crypto_rails": rails_public(),
        "not_a_broker": True,
        "disclaimer": DISCLAIMER,
        "ts": time.time(),
    }
