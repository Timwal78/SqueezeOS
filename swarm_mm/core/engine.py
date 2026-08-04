"""Core shared swarm coordination algorithm.

Build once, deploy four ways (A/B/C/D). This module is pure coordination logic:
  - aggregate intent across participants
  - compute optimal limit-order price levels, sizes, venue mix
  - estimate maker rebate + spread capture
  - NO custody, NO pooled execution here (Variant A/D stay signal/sim only)

Market data: uses a live quote probe when available; otherwise a deterministic
synthetic mid derived from ticker hash + session clock so paper/sim never
fabricates "live fills" against unknown prices without disclosure.
"""

from __future__ import annotations

import hashlib
import logging
import math
import os
import time
from dataclasses import dataclass
from typing import Optional

from swarm_mm.core.config import (
    CRYPTO_DEX_WEIGHTS_DEFAULT,
    DEFAULT_CONFIDENCE,
    DEFAULT_SWARM_DEPTH,
    DISCLAIMER,
    MAKER_REBATE_BPS_DEFAULT,
    SPREAD_CAPTURE_BPS_DEFAULT,
    VENUE_WEIGHTS_DEFAULT,
    Side,
    Variant,
)
from swarm_mm.core.models import (
    LevelRequest,
    LevelResponse,
    PriceLevel,
    RebateEstimate,
    SwarmIntent,
    VenueAllocation,
    VenueMapResponse,
)
from swarm_mm.core.state import store

logger = logging.getLogger("swarm-mm.engine")

# Optional live quote URL (Tradier/polygon proxy). Empty = synthetic disclosed mid.
QUOTE_URL = os.environ.get("SWARM_MM_QUOTE_URL", "").strip()


@dataclass
class Quote:
    ticker: str
    bid: float
    ask: float
    mid: float
    source: str  # "live" | "synthetic_disclosed"


def _ticker_seed(ticker: str) -> int:
    h = hashlib.sha256(ticker.encode("utf-8")).hexdigest()
    return int(h[:12], 16)


def synthetic_quote(ticker: str, now: Optional[float] = None) -> Quote:
    """Deterministic synthetic NBBO for paper/sim when no live feed is configured.

    Explicitly labeled synthetic_disclosed — never presented as a live exchange quote.
    """
    now = now if now is not None else time.time()
    seed = _ticker_seed(ticker)
    # Base price band 10..500 from hash; slow sine drift for session realism
    base = 10.0 + (seed % 49000) / 100.0
    drift = 1.0 + 0.002 * math.sin(now / 300.0 + (seed % 1000) / 100.0)
    mid = round(base * drift, 4)
    half_spread = max(0.01, round(mid * 0.0004, 4))  # ~4 bps half-spread
    return Quote(
        ticker=ticker,
        bid=round(mid - half_spread, 4),
        ask=round(mid + half_spread, 4),
        mid=mid,
        source="synthetic_disclosed",
    )


def fetch_quote(ticker: str) -> Quote:
    if not QUOTE_URL:
        return synthetic_quote(ticker)
    try:
        import httpx

        url = QUOTE_URL.format(ticker=ticker)
        with httpx.Client(timeout=3.0) as client:
            r = client.get(url)
            r.raise_for_status()
            data = r.json()
        bid = float(data.get("bid") or data.get("bidPrice"))
        ask = float(data.get("ask") or data.get("askPrice"))
        mid = (bid + ask) / 2.0 if bid and ask else float(data.get("mid") or data.get("last"))
        return Quote(ticker=ticker, bid=bid, ask=ask, mid=mid, source="live")
    except Exception as exc:
        logger.warning("live quote failed for %s (%s); using synthetic_disclosed", ticker, exc)
        q = synthetic_quote(ticker)
        return q


def record_intent(intent: SwarmIntent) -> None:
    key = f"intent:{intent.ticker}:{intent.side.value}"
    blob = store.get(key, {"notional_usd": 0.0, "participant_count": 0, "urgency_sum": 0.0})
    blob["notional_usd"] = float(blob.get("notional_usd", 0.0)) + float(intent.notional_usd)
    blob["participant_count"] = int(blob.get("participant_count", 0)) + max(1, intent.participant_count)
    blob["urgency_sum"] = float(blob.get("urgency_sum", 0.0)) + float(intent.urgency)
    blob["ts"] = intent.ts.isoformat()
    store.set(key, blob, ttl=3600)


def _intent_snapshot(ticker: str, side: Side) -> dict:
    if side == Side.BOTH:
        buy = store.get(f"intent:{ticker}:buy", {}) or {}
        sell = store.get(f"intent:{ticker}:sell", {}) or {}
        return {
            "notional_usd": float(buy.get("notional_usd", 0)) + float(sell.get("notional_usd", 0)),
            "participant_count": int(buy.get("participant_count", 0)) + int(sell.get("participant_count", 0)),
            "urgency": (
                (float(buy.get("urgency_sum", 0)) + float(sell.get("urgency_sum", 0)))
                / max(1, int(buy.get("participant_count", 0)) + int(sell.get("participant_count", 0)))
            ),
        }
    blob = store.get(f"intent:{ticker}:{side.value}", {}) or {}
    pc = int(blob.get("participant_count", 0))
    return {
        "notional_usd": float(blob.get("notional_usd", 0.0)),
        "participant_count": pc,
        "urgency": float(blob.get("urgency_sum", 0.0)) / max(1, pc),
    }


def _level_ladder(
    mid: float,
    side: Side,
    depth: int,
    confidence_threshold: float,
    spread_bps: float,
    urgency: float,
    notional: float,
) -> list[PriceLevel]:
    """Build resting limit ladder around mid.

    Buy levels step down from bid; sell levels step up from ask.
    Size decays with distance; confidence decays with distance + rises with swarm notional.
    """
    levels: list[PriceLevel] = []
    tick = max(0.01, round(mid * 0.0005, 4))  # ~5 bps step
    half_spread = mid * (spread_bps / 10_000.0) / 2.0
    base_notional = max(notional, 10_000.0)
    participants_boost = min(0.15, math.log10(max(10.0, base_notional)) / 100.0)

    def one_side(s: Side) -> None:
        for i in range(depth):
            dist = i + 1
            if s == Side.BUY:
                px = round(mid - half_spread - dist * tick, 4)
            else:
                px = round(mid + half_spread + dist * tick, 4)
            # Size: more at touch, less deeper; urgency pulls size toward touch
            weight = (depth - i) / sum(range(1, depth + 1))
            urgency_shift = 1.0 + 0.35 * urgency * (1.0 - i / depth)
            size_usd = base_notional * weight * urgency_shift / max(1, depth // 2)
            shares = max(1.0, round(size_usd / max(px, 0.01), 2))
            conf = max(0.0, min(1.0, 0.92 - 0.06 * i + participants_boost - 0.05 * urgency * i))
            if conf < confidence_threshold:
                continue
            rebate = MAKER_REBATE_BPS_DEFAULT * (1.0 + 0.1 * (depth - i) / depth)
            venue = _venue_for_level(i)
            levels.append(
                PriceLevel(
                    price=px,
                    size=shares,
                    side=s,
                    confidence=round(conf, 4),
                    venue_hint=venue,
                    expected_rebate_bps=round(rebate, 4),
                    rationale=(
                        f"{'Bid' if s == Side.BUY else 'Offer'} L{dist} @ {px}: "
                        f"swarm-weighted maker level, conf={conf:.2f}, venue={venue}"
                    ),
                )
            )

    if side in (Side.BUY, Side.BOTH):
        one_side(Side.BUY)
    if side in (Side.SELL, Side.BOTH):
        one_side(Side.SELL)
    return levels


def _venue_for_level(index: int) -> str:
    # Prefer maker-rebate venues near touch
    ordered = sorted(VENUE_WEIGHTS_DEFAULT.items(), key=lambda kv: -kv[1])
    return ordered[index % len(ordered)][0]


def compute_levels(req: LevelRequest, variant: Variant = Variant.A_SIGNAL, paper: bool = False) -> LevelResponse:
    q = fetch_quote(req.ticker)
    snap = _intent_snapshot(req.ticker, req.side)
    # Seed baseline swarm presence so empty books still produce a usable ladder
    participants = max(snap["participant_count"], 12 if paper else 3)
    notional = req.notional_usd if req.notional_usd is not None else max(snap["notional_usd"], 50_000.0)
    urgency = float(snap.get("urgency") or 0.45)
    spread_bps = max(2.0, (q.ask - q.bid) / q.mid * 10_000.0) if q.mid else 8.0

    levels = _level_ladder(
        mid=q.mid,
        side=req.side,
        depth=req.depth or DEFAULT_SWARM_DEPTH,
        confidence_threshold=req.confidence_threshold or DEFAULT_CONFIDENCE,
        spread_bps=spread_bps,
        urgency=urgency,
        notional=notional,
    )

    # Cache last ladder for rebate / venue tools
    store.set(
        f"ladder:{req.ticker}",
        {
            "mid": q.mid,
            "spread_bps": spread_bps,
            "levels": [lv.model_dump(mode="json") for lv in levels],
            "source": q.source,
            "variant": variant.value,
        },
        ttl=300,
    )

    return LevelResponse(
        ticker=req.ticker,
        side=req.side,
        mid=q.mid,
        spread_bps=round(spread_bps, 4),
        levels=levels,
        swarm_participants=participants,
        confidence_threshold=req.confidence_threshold,
        variant=variant,
        disclaimer=DISCLAIMER + (f" Quote source: {q.source}." if q.source != "live" else " Quote source: live."),
        paper=paper or q.source != "live",
    )


def venue_map(ticker: str) -> VenueMapResponse:
    ticker = ticker.strip().upper()
    ladder = store.get(f"ladder:{ticker}")
    weights = dict(VENUE_WEIGHTS_DEFAULT)
    # If ladder exists, tilt toward venues already hinted on high-confidence levels
    if ladder and ladder.get("levels"):
        counts: dict[str, float] = {}
        for lv in ladder["levels"]:
            v = lv.get("venue_hint") or "IEX"
            counts[v] = counts.get(v, 0.0) + float(lv.get("confidence") or 0.5)
        total = sum(counts.values()) or 1.0
        blended = {k: 0.5 * weights.get(k, 0.0) + 0.5 * (counts.get(k, 0.0) / total) for k in weights}
        s = sum(blended.values()) or 1.0
        weights = {k: round(v / s, 4) for k, v in blended.items()}

    allocs = [
        VenueAllocation(
            venue=v,
            weight=w,
            reason="Primary maker-rebate venue" if v == "IEX" else "Secondary maker / capture venue",
        )
        for v, w in sorted(weights.items(), key=lambda kv: -kv[1])
    ]
    top = allocs[0]
    second = allocs[1] if len(allocs) > 1 else None
    summary = f"Place {int(top.weight * 100)}% on {top.venue}"
    if second:
        summary += f", {int(second.weight * 100)}% on {second.venue}"
    summary += f" for {ticker}."

    return VenueMapResponse(
        ticker=ticker,
        allocations=allocs,
        summary=summary,
        disclaimer=DISCLAIMER,
    )


def rebate_tracker(user_id: str, ticker: str, notional_usd: float = 100_000.0) -> RebateEstimate:
    ticker = ticker.strip().upper()
    ladder = store.get(f"ladder:{ticker}") or {}
    bps_rebate = MAKER_REBATE_BPS_DEFAULT
    bps_spread = SPREAD_CAPTURE_BPS_DEFAULT
    if ladder.get("levels"):
        confs = [float(lv.get("confidence") or 0) for lv in ladder["levels"]]
        avg_conf = sum(confs) / len(confs) if confs else 0.75
        bps_rebate *= 0.8 + 0.4 * avg_conf
        bps_spread *= 0.8 + 0.4 * avg_conf

    # Pull any realized sim rebates for this user
    sim_key = f"sim:acct:{user_id}"
    acct = store.get(sim_key) or {}
    realized = float(acct.get("maker_rebate_earned", 0.0))

    est_rebate = notional_usd * (bps_rebate / 10_000.0)
    est_spread = notional_usd * (bps_spread / 10_000.0)
    return RebateEstimate(
        user_id=user_id,
        ticker=ticker,
        estimated_maker_rebate_usd=round(est_rebate + realized * 0.1, 6),
        estimated_spread_capture_usd=round(est_spread, 6),
        notional_usd=notional_usd,
        bps_rebate=round(bps_rebate, 4),
        bps_spread=round(bps_spread, 4),
    )


def crypto_dex_weights() -> dict[str, float]:
    return dict(CRYPTO_DEX_WEIGHTS_DEFAULT)


def engine_info() -> dict:
    return {
        "engine": "swarm-mm-core",
        "quote_mode": "live" if QUOTE_URL else "synthetic_disclosed",
        "default_venues": VENUE_WEIGHTS_DEFAULT,
        "crypto_dexes": CRYPTO_DEX_WEIGHTS_DEFAULT,
        "state": store.snapshot(),
    }
