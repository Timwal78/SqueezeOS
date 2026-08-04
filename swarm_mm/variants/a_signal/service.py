"""Variant A — Signal Swarm (lowest risk retail path).

Coordinated limit-order intelligence. NO capital pooling. NO pooled execution.
Each trader places their own resting orders at swarm-recommended levels via
their own brokerage account. Swarm earns subscription fee only.
"""

from __future__ import annotations

from typing import Any, Optional

from swarm_mm.core.config import DISCLAIMER, PRICE_SIGNAL_SUB_USD, Side, Variant
from swarm_mm.core.engine import compute_levels, rebate_tracker, record_intent, venue_map
from swarm_mm.core.models import LevelRequest, LevelResponse, RebateEstimate, SwarmIntent, VenueMapResponse
from swarm_mm.core.state import store


def levels(
    ticker: str,
    side: str | Side = Side.BOTH,
    confidence_threshold: float = 0.75,
    notional_usd: Optional[float] = None,
    depth: int = 5,
) -> LevelResponse:
    side_e = Side(side) if not isinstance(side, Side) else side
    req = LevelRequest(
        ticker=ticker,
        side=side_e,
        confidence_threshold=confidence_threshold,
        notional_usd=notional_usd,
        depth=depth,
    )
    # Register lightweight intent so subsequent callers see swarm density
    record_intent(
        SwarmIntent(
            ticker=req.ticker,
            side=side_e if side_e != Side.BOTH else Side.BUY,
            notional_usd=float(notional_usd or 25_000),
            participant_count=1,
            urgency=0.5,
        )
    )
    return compute_levels(req, variant=Variant.A_SIGNAL, paper=False)


def venue_map_for(ticker: str) -> VenueMapResponse:
    return venue_map(ticker)


def rebate(user_id: str, ticker: str, notional_usd: float = 100_000.0) -> RebateEstimate:
    return rebate_tracker(user_id, ticker, notional_usd=notional_usd)


def subscribe(user_id: str, broker: str = "alpaca") -> dict[str, Any]:
    """Record SaaS subscription intent. Billing settled via x402 $19/mo."""
    key = f"signal:sub:{user_id}"
    store.set(
        key,
        {
            "user_id": user_id,
            "broker": broker.lower(),
            "plan_usd_mo": PRICE_SIGNAL_SUB_USD,
            "status": "active_pending_payment",
            "features": ["levels", "venue_map", "rebate_tracker", "ws_broadcast"],
            "execution": "user_broker_only",
            "disclaimer": DISCLAIMER,
        },
    )
    return store.get(key)


def subscription_status(user_id: str) -> dict[str, Any]:
    return store.get(f"signal:sub:{user_id}") or {
        "user_id": user_id,
        "status": "none",
        "plan_usd_mo": PRICE_SIGNAL_SUB_USD,
    }


def mcp_tools() -> list[dict[str, Any]]:
    return [
        {
            "name": "signal_swarm.levels",
            "description": "Optimal limit-order price levels for a ticker (signal only — user executes at own broker).",
            "price_usd": 0.001,
            "input": {
                "ticker": "string",
                "side": "buy|sell|both",
                "confidence_threshold": "float default 0.75",
            },
        },
        {
            "name": "signal_swarm.venue_map",
            "description": "Recommended venue allocation (e.g. 60% IEX / 40% MEMX).",
            "price_usd": 0.001,
            "input": {"ticker": "string"},
        },
        {
            "name": "signal_swarm.rebate_tracker",
            "description": "Estimated maker rebate + spread capture for user/ticker.",
            "price_usd": 0.001,
            "input": {"user_id": "string", "ticker": "string"},
        },
        {
            "name": "signal_swarm.broker_orders",
            "description": "Broker-native order preview (user executes — no swarm custody).",
            "price_usd": 0.001,
            "input": {"broker": "alpaca|tradier|ibkr", "ticker": "string", "side": "buy|sell|both"},
        },
    ]
