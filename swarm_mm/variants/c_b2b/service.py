"""Variant C — B2B Swarm Engine (software vendor, customer bears regulatory burden)."""

from __future__ import annotations

import time
from typing import Any

from swarm_mm.core.config import DISCLAIMER, PRICE_B2B_PLATFORM_USD, PRICE_B2B_REBATE_SHARE, Side, Variant
from swarm_mm.core.engine import compute_levels
from swarm_mm.core.models import B2BConfigureRequest, B2BOptimizeRequest, LevelRequest
from swarm_mm.core.state import store


def configure(req: B2BConfigureRequest) -> dict[str, Any]:
    key = f"b2b:cust:{req.customer_id}"
    existing = store.get(key) or {}
    cfg = {
        "customer_id": req.customer_id,
        "asset_universe": [t.strip().upper() for t in req.asset_universe],
        "risk_params": {
            "max_notional_per_symbol": 1_000_000,
            "max_participation_rate": 0.08,
            "confidence_floor": 0.75,
            **(existing.get("risk_params") or {}),
            **(req.risk_params or {}),
        },
        "status": "active",
        "license_usd_mo": PRICE_B2B_PLATFORM_USD,
        "rebate_share": PRICE_B2B_REBATE_SHARE,
        "updated_at": time.time(),
        "disclaimer": (
            "Software vendor license only. Customer is solely responsible for "
            "broker-dealer / MiFID / local registration, KYC, capital, and execution. "
            + DISCLAIMER
        ),
    }
    store.set(key, cfg)
    customers = store.get("b2b:customers", []) or []
    if req.customer_id not in customers:
        customers.append(req.customer_id)
        store.set("b2b:customers", customers)
    return cfg


def optimize(req: B2BOptimizeRequest) -> dict[str, Any]:
    cfg = store.get(f"b2b:cust:{req.customer_id}")
    if not cfg:
        raise ValueError("unknown customer_id — call b2b_swarm.configure first")

    universe = cfg.get("asset_universe") or ["SPY"]
    conf = float(cfg.get("risk_params", {}).get("confidence_floor", 0.75))
    ladders = []
    total_rebate_bps = 0.0
    total_spread_bps = 0.0

    for ticker in universe[:25]:
        lr = compute_levels(
            LevelRequest(ticker=ticker, side=Side.BOTH, confidence_threshold=conf),
            variant=Variant.C_B2B,
            paper=False,
        )
        avg_reb = (
            sum(lv.expected_rebate_bps for lv in lr.levels) / len(lr.levels) if lr.levels else 0.0
        )
        total_rebate_bps += avg_reb
        total_spread_bps += lr.spread_bps
        ladders.append(
            {
                "ticker": ticker,
                "mid": lr.mid,
                "levels": len(lr.levels),
                "avg_rebate_bps": round(avg_reb, 4),
                "spread_bps": lr.spread_bps,
            }
        )

    n = max(1, len(ladders))
    baseline_rebate_bps = 0.12  # assumed pre-swarm capture
    improved = max(0.0, (total_rebate_bps / n) - baseline_rebate_bps)
    incremental_usd_per_1m = 1_000_000 * (improved / 10_000.0)
    fee = incremental_usd_per_1m * PRICE_B2B_REBATE_SHARE

    result = {
        "customer_id": req.customer_id,
        "target": req.target,
        "symbols_optimized": n,
        "avg_swarm_rebate_bps": round(total_rebate_bps / n, 4),
        "avg_spread_bps": round(total_spread_bps / n, 4),
        "baseline_rebate_bps": baseline_rebate_bps,
        "incremental_rebate_bps": round(improved, 4),
        "est_incremental_usd_per_1m_notional": round(incremental_usd_per_1m, 4),
        "est_platform_share_usd_per_1m": round(fee, 4),
        "ladders": ladders if req.target == "rebate_capture" else ladders,
        "disclaimer": cfg.get("disclaimer", DISCLAIMER),
    }
    store.set(f"b2b:last_opt:{req.customer_id}", result, ttl=3600)
    return result


def report(customer_id: str, period: str = "30d") -> dict[str, Any]:
    cfg = store.get(f"b2b:cust:{customer_id}")
    if not cfg:
        raise ValueError("unknown customer_id")
    last = store.get(f"b2b:last_opt:{customer_id}") or {}
    return {
        "customer_id": customer_id,
        "period": period,
        "license_usd_mo": PRICE_B2B_PLATFORM_USD,
        "asset_universe": cfg.get("asset_universe"),
        "risk_params": cfg.get("risk_params"),
        "performance": {
            "fill_rate_est": 0.62,
            "slippage_bps_est": 0.8,
            "rebate_capture_bps": last.get("avg_swarm_rebate_bps"),
            "incremental_rebate_bps": last.get("incremental_rebate_bps"),
            "note": "Forward-looking estimates until customer wires production fill tapes.",
        },
        "last_optimize": last or None,
        "sla": {"uptime_target": 0.999, "signal_latency_ms_p99": 150},
        "disclaimer": cfg.get("disclaimer", DISCLAIMER),
    }


def mcp_tools() -> list[dict[str, Any]]:
    return [
        {
            "name": "b2b_swarm.configure",
            "description": "Configure white-label swarm for a licensed customer.",
            "price_usd": 0.0,
            "input": {"customer_id": "string", "asset_universe": "string[]", "risk_params": "object"},
        },
        {
            "name": "b2b_swarm.optimize",
            "description": "Run rebate_capture or spread optimization across customer universe.",
            "price_usd": 0.05,
            "input": {"customer_id": "string", "target": "rebate_capture|spread"},
        },
        {
            "name": "b2b_swarm.report",
            "description": "Performance, fill rates, slippage report for period.",
            "price_usd": 0.10,
            "input": {"customer_id": "string", "period": "string"},
        },
    ]
