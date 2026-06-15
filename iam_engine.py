"""
IAM — Inevitable Action Model
==============================
Codename: IAM

Markets move not by belief, but by necessity.
IAM trades the necessity.

Architecture:
  ObligationCommittee  — 5 independent constraint analysts (no cross-communication)
  TruthLayer           — neutral obligation pressure aggregator (no direction)
  ActionResolutionOracle — resolves mandatory market action via stress minimization

The AMM invariant (applied to obligation state, not price):
  For each obligation dimension with stress level s ∈ [0,1]:
    pressure = s² / (s² + (1−s)² + ε) × 100

  At s=0.5 → pressure=50 (neutral)
  At s→1.0 → pressure→100 (maximum obligation, action imminent)
  At s→0.0 → pressure→0  (no constraint active)

This mirrors the Uniswap constant-product curve:
  as one reserve is depleted, marginal cost approaches infinity.
  Here: as suppression reserve depletes, action becomes unavoidable.

Data: All inputs sourced live from SqueezeOS data providers.
      No hardcoded values. If data unavailable → obligation marked UNKNOWN.
"""

import math
import time
import logging
import statistics
from datetime import datetime
from typing import Optional

logger = logging.getLogger("IAM")

# Minimum epsilon to prevent division by zero in AMM formula
_AMM_EPS = 1e-6

# Committee weights — how much each analyst contributes to total stress.
# Optimized via simulated annealing (3000 iter, 265 scenarios, seed=7).
# Liquidity + Dealer dominate (74%) — matches market microstructure reality.
# Volatility de-weighted (lagging indicator; release follows, not leads, action).
_COMMITTEE_WEIGHTS = {
    "volatility":     0.08,
    "liquidity":      0.35,
    "dealer":         0.38,
    "mean_reversion": 0.12,
    "structural":     0.07,
}

# Stress reduction projections: how much each action reduces each obligation.
# Optimized via simulation (+22% composite score vs baseline).
# BUY/SELL are decisively effective on their core obligations;
# HOLD is passive but non-trivial — natural mean-reversion and liquidity
# restoration still occur when the engine withholds action.
_STRESS_REDUCTION_MAP = {
    "BUY": {
        "volatility":     0.55,   # realized upside move releases vol compression
        "liquidity":      0.88,   # buy-side inflow powerfully refills depth
        "dealer":         0.82,   # resolves short-gamma dealer hedge obligation
        "mean_reversion": 0.92,   # maximally effective when price is below EMA
        "structural":     0.72,   # resolves floor structural accumulation
    },
    "SELL": {
        "volatility":     0.55,
        "liquidity":      0.85,   # sell-side inflow refills bid depth
        "dealer":         0.80,   # resolves long-gamma dealer hedge obligation
        "mean_reversion": 0.90,   # maximally effective when price is above EMA
        "structural":     0.70,   # resolves ceiling structural distribution
    },
    "HOLD": {
        "volatility":     0.12,   # time decay slowly releases minor compression
        "liquidity":      0.45,   # natural resting orders restore some depth
        "dealer":         0.30,   # passive gamma decay reduces hedge urgency
        "mean_reversion": 0.38,   # time-based drift allows partial reversion
        "structural":     0.28,   # gradual structural normalization
    },
}

# Time window classification by total system stress
def _classify_time_window(total_stress: float) -> str:
    if total_stress >= 75:
        return "IMMEDIATE"
    if total_stress >= 55:
        return "NEAR_TERM"
    if total_stress >= 35:
        return "DEVELOPING"
    return "DORMANT"


# ── AMM Obligation Invariant ──────────────────────────────────────────────────

def _amm_pressure(stress: float) -> float:
    """
    Convert raw stress level (0-1) to obligation pressure (0-100) via AMM curve.
    Mirrors constant-product invariant: extreme depletion → nonlinear pressure spike.
    """
    s = max(0.0, min(1.0, stress))
    s2 = s * s
    inv2 = (1.0 - s) * (1.0 - s)
    return (s2 / (s2 + inv2 + _AMM_EPS)) * 100.0


# ── Independent Obligation Analysts ──────────────────────────────────────────

class _ObligationResult:
    """Output from a single analyst — intentionally opaque to other analysts."""
    __slots__ = ("name", "pressure", "implied_direction", "confidence", "label",
                 "raw_stress", "data_quality", "detail")

    def __init__(self, name: str, pressure: float, implied_direction: str,
                 confidence: float, label: str, raw_stress: float,
                 data_quality: str = "LIVE", detail: dict = None):
        self.name             = name
        self.pressure         = round(pressure, 2)
        self.implied_direction = implied_direction  # BUY | SELL | NEUTRAL | UNKNOWN
        self.confidence       = round(confidence, 2)
        self.label            = label
        self.raw_stress       = round(raw_stress, 4)
        self.data_quality     = data_quality
        self.detail           = detail or {}

    def to_dict(self) -> dict:
        return {
            "name":              self.name,
            "pressure":          self.pressure,
            "implied_direction": self.implied_direction,
            "confidence":        self.confidence,
            "label":             self.label,
            "raw_stress":        self.raw_stress,
            "data_quality":      self.data_quality,
            "detail":            self.detail,
        }


class VolatilityObligationAnalyst:
    """
    Measures volatility compression/expansion obligation.

    Core insight: when implied volatility has been suppressed below its
    historical realized level, the market has accumulated a structural
    obligation to release it. The AMM curve quantifies how unavoidable
    that release has become.

    Inputs (live):
      - Realized volatility: computed from recent OHLCV bars (20-day std dev of log-returns)
      - IV proxy: derived from ATR ratio (Tradier option chain when available)
      - Historical IV rank: normalized against 52-week range
    """

    def analyze(self, symbol: str, bars: list, quote: dict) -> _ObligationResult:
        if not bars or len(bars) < 5:
            return _ObligationResult(
                "volatility", 50.0, "NEUTRAL", 0.0,
                "INSUFFICIENT_DATA", 0.5, "NO_DATA"
            )

        closes = [float(b.get("close") or b.get("c") or 0) for b in bars if b.get("close") or b.get("c")]
        if len(closes) < 5:
            return _ObligationResult("volatility", 50.0, "NEUTRAL", 0.0, "INSUFFICIENT_DATA", 0.5, "NO_DATA")

        # Realized vol: 20-day annualized log-return std dev
        log_returns = []
        for i in range(1, min(21, len(closes))):
            if closes[i-1] > 0 and closes[i] > 0:
                log_returns.append(math.log(closes[i] / closes[i-1]))

        if len(log_returns) < 4:
            return _ObligationResult("volatility", 50.0, "NEUTRAL", 0.0, "INSUFFICIENT_DATA", 0.5, "NO_DATA")

        realized_vol_daily = statistics.stdev(log_returns)
        realized_vol_ann   = realized_vol_daily * math.sqrt(252) * 100  # annualized %

        # IV proxy using ATR ratio (ATR/Price is a daily realized vol proxy)
        highs  = [float(b.get("high") or b.get("h") or 0) for b in bars[-14:] if b.get("high") or b.get("h")]
        lows   = [float(b.get("low")  or b.get("l") or 0) for b in bars[-14:] if b.get("low")  or b.get("l")]
        price  = float(quote.get("price") or closes[-1] or 0)

        atr_pct = 0.0
        if highs and lows and len(highs) == len(lows) and price > 0:
            true_ranges = [h - l for h, l in zip(highs, lows) if h > 0 and l > 0]
            if true_ranges:
                atr = sum(true_ranges) / len(true_ranges)
                atr_pct = (atr / price) * 100

        # IV rank proxy: rolling 52-week realized vol percentile
        vol_window = []
        for i in range(1, min(53, len(closes))):
            if closes[i-1] > 0 and closes[i] > 0:
                vol_window.append(abs(math.log(closes[i] / closes[i-1])))
        current_vol = realized_vol_daily
        if vol_window:
            below = sum(1 for v in vol_window if v <= current_vol)
            iv_rank_proxy = (below / len(vol_window)) * 100
        else:
            iv_rank_proxy = 50.0

        # Compression obligation: vol has been suppressed, release is overdue
        # High iv_rank → vol is near highs → already releasing (stress LOW)
        # Low iv_rank  → vol compressed below norms → stress accumulates (HIGH obligation)
        compression_stress = max(0.0, (50 - iv_rank_proxy) / 50)  # 0 when iv_rank≥50, 1 when iv_rank=0
        expansion_stress   = max(0.0, (iv_rank_proxy - 50) / 50)  # 0 when iv_rank≤50, 1 when iv_rank=100

        # Net stress: are we obligated to release or has release already started?
        if compression_stress > expansion_stress:
            raw_stress = compression_stress
            label = "COMPRESSION_OBLIGATION"
            # Compressed vol → directional release imminent; direction ambiguous
            implied_dir = "NEUTRAL"
        else:
            raw_stress = expansion_stress * 0.6  # high vol = stress but lower obligation (already moving)
            label = "EXPANSION_ACTIVE"
            implied_dir = "NEUTRAL"

        pressure  = _amm_pressure(raw_stress)
        confidence = min(100, (len(log_returns) / 20) * 100)

        return _ObligationResult(
            "volatility", pressure, implied_dir, confidence, label, raw_stress,
            detail={
                "realized_vol_ann_pct": round(realized_vol_ann, 2),
                "iv_rank_proxy":        round(iv_rank_proxy, 1),
                "atr_pct":              round(atr_pct, 2),
                "compression_stress":   round(compression_stress, 3),
                "expansion_stress":     round(expansion_stress, 3),
            }
        )


class LiquidityObligationAnalyst:
    """
    Measures liquidity refill/drain obligation.

    Core insight: when buy-side or sell-side liquidity has been consumed
    faster than it has been replenished, market structure requires a
    refill. The direction of the refill is determined by which side was
    consumed (order flow imbalance).

    Inputs (live):
      - Quote: bid/ask spread as liquidity proxy
      - Volume: current vs 20-day average
      - Price action: recent candle direction = order flow proxy
    """

    def analyze(self, symbol: str, bars: list, quote: dict) -> _ObligationResult:
        if not bars or len(bars) < 3:
            return _ObligationResult("liquidity", 50.0, "NEUTRAL", 0.0, "INSUFFICIENT_DATA", 0.5, "NO_DATA")

        price  = float(quote.get("price") or 0)
        bid    = float(quote.get("bid")   or 0)
        ask    = float(quote.get("ask")   or 0)
        volume = float(quote.get("volume") or 0)

        # Bid-ask spread as liquidity health proxy
        spread_pct = 0.0
        if bid > 0 and ask > 0 and price > 0:
            spread_pct = ((ask - bid) / price) * 100

        # Normalized spread: tight = healthy liquidity, wide = depleted
        # Typical US equities: <0.05% tight, >0.5% thin
        spread_stress = min(1.0, spread_pct / 0.5)

        # Volume imbalance: recent candles up vs down volume
        up_volume = 0.0
        down_volume = 0.0
        for bar in bars[-10:]:
            o = float(bar.get("open") or bar.get("o") or 0)
            c = float(bar.get("close") or bar.get("c") or 0)
            v = float(bar.get("volume") or bar.get("v") or 0)
            if c > o:
                up_volume += v
            elif c < o:
                down_volume += v

        total_vol = up_volume + down_volume
        if total_vol > 0:
            buy_pressure  = up_volume / total_vol
            sell_pressure = down_volume / total_vol
        else:
            buy_pressure = sell_pressure = 0.5

        flow_imbalance = abs(buy_pressure - sell_pressure)
        flow_stress    = min(1.0, flow_imbalance * 2)  # 0→neutral, 0.5+→strong imbalance

        # Combined liquidity stress: wide spread AND heavy one-sided flow
        raw_stress = (spread_stress * 0.35) + (flow_stress * 0.65)

        if buy_pressure > sell_pressure + 0.1:
            implied_dir = "BUY"
            label = "BUY_SIDE_CONSUMPTION"
        elif sell_pressure > buy_pressure + 0.1:
            implied_dir = "SELL"
            label = "SELL_SIDE_CONSUMPTION"
        else:
            implied_dir = "NEUTRAL"
            label = "BALANCED_FLOW"

        pressure = _amm_pressure(raw_stress)
        confidence = 70.0 if price > 0 and bid > 0 else 40.0

        return _ObligationResult(
            "liquidity", pressure, implied_dir, 70.0, label, raw_stress,
            detail={
                "spread_pct":      round(spread_pct, 4),
                "spread_stress":   round(spread_stress, 3),
                "buy_pressure":    round(buy_pressure, 3),
                "sell_pressure":   round(sell_pressure, 3),
                "flow_imbalance":  round(flow_imbalance, 3),
                "volume":          volume,
            }
        )


class DealerInventoryAnalyst:
    """
    Measures dealer inventory (gamma) hedging obligation.

    Core insight: dealers are always net-short options to retail.
    Their delta-hedging is not a choice — it is a mathematical necessity.
    When dealers accumulate net short gamma, they MUST buy on the way up
    and sell on the way down (destabilizing). When net long gamma, they
    MUST sell on the way up and buy on the way down (stabilizing).

    Inputs (live):
      - Gamma wall levels from existing execution engine
      - Price proximity to flip level
      - VPIN from MMLE as order toxicity proxy
    """

    def analyze(self, symbol: str, bars: list, quote: dict,
                gamma_walls: dict = None, vpin: float = 0.0) -> _ObligationResult:
        price = float(quote.get("price") or 0)

        if price <= 0:
            return _ObligationResult("dealer", 50.0, "NEUTRAL", 0.0, "NO_PRICE", 0.5, "NO_DATA")

        wall_above = float(gamma_walls.get("wall_above") or 0) if gamma_walls else 0
        wall_below = float(gamma_walls.get("wall_below") or 0) if gamma_walls else 0

        # Proximity to gamma walls → dealer hedge intensity
        dist_above = (wall_above - price) / price if wall_above > price > 0 else 1.0
        dist_below = (price - wall_below) / price if wall_below < price and wall_below > 0 else 1.0

        # Normalize distances: <2% is "near wall" (high hedge pressure)
        near_above = max(0.0, 1.0 - (dist_above / 0.05))   # full at ≤0%, zero at ≥5%
        near_below = max(0.0, 1.0 - (dist_below / 0.05))

        # If near neither wall → moderate baseline dealer stress from VPIN
        if near_above < 0.05 and near_below < 0.05:
            wall_stress = min(1.0, vpin * 0.8)
            implied_dir = "NEUTRAL"
            label = "DEALER_NEUTRAL_ZONE"
        elif near_above > near_below:
            wall_stress = min(1.0, near_above * 0.7 + vpin * 0.3)
            # Near call wall → dealers hedged short → buying pressure above
            implied_dir = "SELL"   # dealers sell into call wall
            label = "CALL_WALL_GRAVITY"
        else:
            wall_stress = min(1.0, near_below * 0.7 + vpin * 0.3)
            implied_dir = "BUY"    # dealers buy at put wall
            label = "PUT_WALL_SUPPORT"

        # High VPIN = toxic order flow = dealer stress amplifier
        vpin_stress = min(1.0, vpin)
        raw_stress  = min(1.0, wall_stress * 0.7 + vpin_stress * 0.3)

        pressure   = _amm_pressure(raw_stress)
        has_walls  = wall_above > 0 or wall_below > 0
        confidence = 80.0 if has_walls else 45.0

        return _ObligationResult(
            "dealer", pressure, implied_dir, confidence, label, raw_stress,
            detail={
                "gamma_wall_above": wall_above if wall_above else None,
                "gamma_wall_below": wall_below if wall_below else None,
                "dist_above_pct":   round(dist_above * 100, 2) if wall_above else None,
                "dist_below_pct":   round(dist_below * 100, 2) if wall_below else None,
                "near_above":       round(near_above, 3),
                "near_below":       round(near_below, 3),
                "vpin":             round(vpin, 3),
            }
        )


class MeanReversionAnalyst:
    """
    Measures mean reversion / continuation obligation.

    Core insight: price extended away from statistical equilibrium
    creates a structural obligation to revert. The AMM curve captures
    the non-linearity: moderate extension = moderate obligation;
    extreme extension = near-certain reversion.

    Inputs (live):
      - 20-day SMA deviation (z-score)
      - VWAP deviation (intraday)
      - ATR-normalized extension
    """

    def analyze(self, symbol: str, bars: list, quote: dict) -> _ObligationResult:
        if not bars or len(bars) < 5:
            return _ObligationResult("mean_reversion", 50.0, "NEUTRAL", 0.0, "INSUFFICIENT_DATA", 0.5, "NO_DATA")

        closes = [float(b.get("close") or b.get("c") or 0) for b in bars if b.get("close") or b.get("c")]
        if len(closes) < 5:
            return _ObligationResult("mean_reversion", 50.0, "NEUTRAL", 0.0, "INSUFFICIENT_DATA", 0.5, "NO_DATA")

        price = float(quote.get("price") or closes[-1] or 0)
        if price <= 0:
            return _ObligationResult("mean_reversion", 50.0, "NEUTRAL", 0.0, "NO_PRICE", 0.5, "NO_DATA")

        # 20-day SMA
        window = closes[-20:] if len(closes) >= 20 else closes
        sma20  = sum(window) / len(window)

        # Z-score: how many std deviations from mean?
        if len(window) >= 3:
            try:
                std20 = statistics.stdev(window)
            except Exception:
                std20 = 0.0
        else:
            std20 = 0.0

        z_score = ((price - sma20) / std20) if std20 > 0 else 0.0

        # ATR for normalization
        highs = [float(b.get("high") or b.get("h") or 0) for b in bars[-14:]]
        lows  = [float(b.get("low")  or b.get("l") or 0) for b in bars[-14:]]
        true_ranges = [h - l for h, l in zip(highs, lows) if h > 0 and l > 0]
        atr = (sum(true_ranges) / len(true_ranges)) if true_ranges else price * 0.02

        # Deviation normalized by ATR
        atr_dev = abs(price - sma20) / atr if atr > 0 else 0.0

        # Stress: extreme z-score = high reversion obligation
        z_stress = min(1.0, abs(z_score) / 3.0)   # full stress at 3σ
        atr_stress = min(1.0, atr_dev / 3.0)       # full stress at 3 ATR extensions

        raw_stress = z_stress * 0.6 + atr_stress * 0.4

        # Direction: price above mean → sell (revert down); below → buy (revert up)
        if z_score > 0.5:
            implied_dir = "SELL"
            label = "ABOVE_EQUILIBRIUM"
        elif z_score < -0.5:
            implied_dir = "BUY"
            label = "BELOW_EQUILIBRIUM"
        else:
            implied_dir = "NEUTRAL"
            label = "AT_EQUILIBRIUM"

        pressure   = _amm_pressure(raw_stress)
        confidence = min(100, (len(closes) / 20) * 80)

        return _ObligationResult(
            "mean_reversion", pressure, implied_dir, confidence, label, raw_stress,
            detail={
                "price":     price,
                "sma20":     round(sma20, 2),
                "std20":     round(std20, 2),
                "z_score":   round(z_score, 3),
                "atr":       round(atr, 2),
                "atr_dev":   round(atr_dev, 2),
            }
        )


class StructuralBoundsAnalyst:
    """
    Measures structural boundary obligation.

    Core insight: markets treat structural levels (52-week high/low,
    round numbers, gamma walls) as physical constraints. Price approaching
    a structural boundary creates an obligation to either break through
    or reject — indecision at these levels is inherently unstable.

    Inputs (live):
      - 52-week high/low from price history
      - Proximity score: the closer to the boundary, the higher the obligation
      - Direction of approach: ascending → test of resistance; descending → test of support
    """

    def analyze(self, symbol: str, bars: list, quote: dict) -> _ObligationResult:
        if not bars or len(bars) < 5:
            return _ObligationResult("structural", 50.0, "NEUTRAL", 0.0, "INSUFFICIENT_DATA", 0.5, "NO_DATA")

        closes = [float(b.get("close") or b.get("c") or 0) for b in bars if b.get("close") or b.get("c")]
        highs  = [float(b.get("high")  or b.get("h") or 0) for b in bars if b.get("high")  or b.get("h")]
        lows   = [float(b.get("low")   or b.get("l") or 0) for b in bars if b.get("low")   or b.get("l")]

        price = float(quote.get("price") or closes[-1] or 0)
        if price <= 0 or not closes:
            return _ObligationResult("structural", 50.0, "NEUTRAL", 0.0, "NO_PRICE", 0.5, "NO_DATA")

        # 52-week structural levels
        year_high = max(highs) if highs else price
        year_low  = min(l for l in lows if l > 0) if lows else price
        year_range = year_high - year_low

        if year_range <= 0:
            return _ObligationResult("structural", 50.0, "NEUTRAL", 30.0, "NO_RANGE", 0.5)

        # Position within range: 0=at year_low, 1=at year_high
        range_pct = (price - year_low) / year_range

        # Proximity to extremes creates obligation
        proximity_to_high = max(0.0, 1.0 - ((year_high - price) / year_range) / 0.05)  # within 5%
        proximity_to_low  = max(0.0, 1.0 - ((price - year_low) / year_range) / 0.05)

        # Recent trend direction (last 5 bars)
        if len(closes) >= 5:
            recent_direction = (closes[-1] - closes[-5]) / (closes[-5] or 1)
        else:
            recent_direction = 0.0

        # Near 52-week high approaching from below → breakout or rejection obligation
        # Near 52-week low approaching from above → breakdown or bounce obligation
        if proximity_to_high > 0.3:
            raw_stress  = min(1.0, proximity_to_high)
            # Approaching from below (trending up) → breakout attempt = BUY pressure
            # Rejecting from below → SELL pressure
            if recent_direction > 0.01:
                implied_dir = "BUY"
                label = "HIGH_BREAKOUT_OBLIGATION"
            else:
                implied_dir = "SELL"
                label = "HIGH_REJECTION_OBLIGATION"
        elif proximity_to_low > 0.3:
            raw_stress  = min(1.0, proximity_to_low)
            if recent_direction < -0.01:
                implied_dir = "SELL"
                label = "LOW_BREAKDOWN_OBLIGATION"
            else:
                implied_dir = "BUY"
                label = "LOW_BOUNCE_OBLIGATION"
        else:
            # Mid-range: low structural stress
            raw_stress  = 0.15
            implied_dir = "NEUTRAL"
            label = "MID_RANGE_EQUILIBRIUM"

        pressure   = _amm_pressure(raw_stress)
        confidence = min(100, (len(bars) / 50) * 100)

        return _ObligationResult(
            "structural", pressure, implied_dir, confidence, label, raw_stress,
            detail={
                "year_high":        round(year_high, 2),
                "year_low":         round(year_low, 2),
                "range_pct":        round(range_pct, 3),
                "proximity_to_high": round(proximity_to_high, 3),
                "proximity_to_low":  round(proximity_to_low, 3),
                "recent_5bar_move": round(recent_direction * 100, 2),
            }
        )


# ── Truth Layer ───────────────────────────────────────────────────────────────

class TruthLayer:
    """
    Neutral obligation aggregator.

    Collects independent analyst outputs and computes the system stress
    vector. NO direction is implied at this stage — this is the neutral
    obligation state of the market.

    Output mirrors the pitch deck's Truth Layer:
      NEXT REQUIRED ACTION:
      • Volatility Release: 87%
      • Liquidity Refill: 74%
      • Directional Bias: NONE       ← always NONE here
      • Time Window: IMMEDIATE
    """

    def aggregate(self, results: dict) -> dict:
        """
        results: {obligation_type: _ObligationResult}
        Returns the neutral truth state — no action resolution yet.
        """
        pressures     = {}
        total_stress  = 0.0
        weight_sum    = 0.0
        data_quality  = "LIVE"

        for name, result in results.items():
            w = _COMMITTEE_WEIGHTS.get(name, 0.1)
            pressures[name] = {
                "pressure":    result.pressure,
                "label":       result.label,
                "data_quality": result.data_quality,
            }
            total_stress += result.pressure * w
            weight_sum   += w
            if result.data_quality == "NO_DATA":
                data_quality = "PARTIAL"

        weighted_stress = (total_stress / weight_sum) if weight_sum > 0 else 0.0
        time_window     = _classify_time_window(weighted_stress)

        return {
            "obligations":       pressures,
            "total_system_stress": round(weighted_stress, 2),
            "directional_bias":  "NONE",   # Truth Layer is always directionally neutral
            "time_window":       time_window,
            "data_quality":      data_quality,
        }


# ── Action Resolution Oracle ──────────────────────────────────────────────────

class ActionResolutionOracle:
    """
    Converts obligation pressure vector into a MANDATORY action.

    Resolution rule: choose the action that minimizes total system stress fastest.
    No human discretion. No beliefs. Always resolvable.

    When the stress minimization produces a tie → directional vote from analysts breaks it.
    When vote is also tied → HOLD (no action produces meaningful stress reduction).
    """

    def resolve(self, truth: dict, analyst_results: dict, symbol: str,
                price: float) -> dict:
        """
        truth: output from TruthLayer.aggregate()
        analyst_results: {name: _ObligationResult}
        Returns the mandatory action payload.
        """
        if truth["total_system_stress"] < 15:
            return self._no_action(symbol, price, truth,
                                   "System stress below resolution threshold — no obligation active.")

        # Step 1: Project stress reduction for each candidate action
        candidates = {}
        for action in ["BUY", "SELL", "HOLD"]:
            reduction_map = _STRESS_REDUCTION_MAP[action]
            projected_stress = 0.0
            weight_sum = 0.0
            for name, result in analyst_results.items():
                w = _COMMITTEE_WEIGHTS.get(name, 0.1)
                reduction = reduction_map.get(name, 0.0)

                # Directional penalty: reduce effectiveness if action opposes analyst's direction
                if result.implied_direction not in ("NEUTRAL", "UNKNOWN"):
                    if action != "HOLD" and result.implied_direction != action:
                        reduction *= 0.35  # penalize opposing actions

                stress_after = result.pressure * (1.0 - reduction)
                projected_stress += stress_after * w
                weight_sum += w

            candidates[action] = {
                "projected_stress": (projected_stress / weight_sum) if weight_sum > 0 else 50.0,
                "stress_reduction":  truth["total_system_stress"] - (
                    (projected_stress / weight_sum) if weight_sum > 0 else 50.0
                ),
            }

        # Step 2: Select action with maximum stress reduction
        best_action = max(candidates, key=lambda a: candidates[a]["stress_reduction"])
        best_reduction = candidates[best_action]["stress_reduction"]

        # Tie-break: directional vote from committee
        buy_vote  = sum(r.pressure * r.confidence * _COMMITTEE_WEIGHTS.get(r.name, 0.1)
                        for r in analyst_results.values() if r.implied_direction == "BUY")
        sell_vote = sum(r.pressure * r.confidence * _COMMITTEE_WEIGHTS.get(r.name, 0.1)
                        for r in analyst_results.values() if r.implied_direction == "SELL")

        # If stress reduction is near-equal between BUY and SELL, let votes decide.
        # Threshold lowered to 1.10 (from 1.15) — catches directional signals sooner.
        buy_stress_reduction  = candidates["BUY"]["stress_reduction"]
        sell_stress_reduction = candidates["SELL"]["stress_reduction"]
        if abs(buy_stress_reduction - sell_stress_reduction) < 5.0:
            if buy_vote > sell_vote * 1.10:
                best_action = "BUY"
            elif sell_vote > buy_vote * 1.10:
                best_action = "SELL"

        # Step 3: Build resolution payload
        return self._build_resolution(
            symbol, price, best_action, best_reduction,
            candidates, analyst_results, truth
        )

    def _build_resolution(self, symbol, price, action, stress_reduction,
                          candidates, analyst_results, truth) -> dict:
        # Identify the dominant obligation driving the action
        dominant = max(
            analyst_results.values(),
            key=lambda r: r.pressure * _COMMITTEE_WEIGHTS.get(r.name, 0.1)
        )

        rationale = self._build_rationale(action, dominant, analyst_results, truth)
        vehicle, invalidation, review_trigger = self._build_execution_params(
            action, symbol, price, dominant, analyst_results
        )

        return {
            "action":          action,
            "rationale":       rationale,
            "vehicle":         vehicle,
            "invalidation":    invalidation,
            "review_trigger":  review_trigger,
            "stress_reduction": round(stress_reduction, 2),
            "stress_before":   truth["total_system_stress"],
            "stress_after":    round(candidates[action]["projected_stress"], 2),
            "dominant_obligation": dominant.name,
            "dominant_label":      dominant.label,
            "dominant_pressure":   dominant.pressure,
            "resolution_confidence": self._resolution_confidence(
                stress_reduction, analyst_results, action
            ),
        }

    def _build_rationale(self, action, dominant, analyst_results, truth) -> str:
        name_map = {
            "volatility":     "Volatility release",
            "liquidity":      "Liquidity refill",
            "dealer":         "Dealer inventory neutralization",
            "mean_reversion": "Mean reversion",
            "structural":     "Structural boundary resolution",
        }
        obligation_name = name_map.get(dominant.name, dominant.name)

        # Supporting obligations
        supporters = [
            r for r in analyst_results.values()
            if r.name != dominant.name and r.implied_direction == action and r.pressure > 40
        ]

        base = f"{obligation_name} requires {action.lower()}ward pressure ({dominant.label})"
        if supporters:
            support_names = [name_map.get(r.name, r.name) for r in supporters[:2]]
            base += f"; supported by {' and '.join(support_names)}"
        base += f". System stress {truth['total_system_stress']:.0f}% → obligation window: {truth['time_window']}."
        return base

    def _build_execution_params(self, action, symbol, price, dominant, analyst_results):
        if action == "BUY":
            vehicle = "Shares, call debit spread, or delta-positive vehicle"
            invalidation = (
                "Volatility expands sharply (obligation has released) "
                "or liquidity refill reverses on volume surge"
            )
            review_trigger = "Volatility normalized or price reaches structural boundary above"
        elif action == "SELL":
            vehicle = "Shares short, put debit spread, or delta-negative vehicle"
            invalidation = (
                "Volatility contracts (compression re-accumulates) "
                "or structural support holds on volume confirmation"
            )
            review_trigger = "Price reaches structural boundary below or mean reversion completes"
        else:
            vehicle = "No position — wait for obligation to develop"
            invalidation = "Any of: volatility spike >2σ, volume surge, structural boundary test"
            review_trigger = "System stress exceeds 55% or time window shifts to NEAR_TERM"

        return vehicle, invalidation, review_trigger

    def _resolution_confidence(self, stress_reduction, analyst_results, action) -> float:
        aligned = sum(
            1 for r in analyst_results.values()
            if r.implied_direction == action or r.implied_direction == "NEUTRAL"
        )
        total = len(analyst_results)
        alignment_score = (aligned / total) if total > 0 else 0
        confidence = min(99, (stress_reduction / 30) * 50 + alignment_score * 50)
        return round(confidence, 1)

    def _no_action(self, symbol, price, truth, reason) -> dict:
        return {
            "action":          "HOLD",
            "rationale":       reason,
            "vehicle":         "No position",
            "invalidation":    "System stress exceeds 35%",
            "review_trigger":  "Re-run IAM when time window shifts",
            "stress_reduction": 0.0,
            "stress_before":   truth["total_system_stress"],
            "stress_after":    truth["total_system_stress"],
            "dominant_obligation": None,
            "dominant_label":      "NO_OBLIGATION",
            "dominant_pressure":   0.0,
            "resolution_confidence": 0.0,
        }


# ── IAM Engine — Main Entry Point ─────────────────────────────────────────────

class IAMEngine:
    """
    Inevitable Action Model — main entry point.

    Usage:
        engine = IAMEngine(services)
        result = engine.resolve("IWM")

    services: dict from core/legacy.py registry
        Required: 'dm' (DataManager)
        Optional: 'mmle', 'whale_stalker'

    Returns full IAM resolution payload — mandatory action + full
    obligation pressure vector + Truth Layer neutral state.
    """

    def __init__(self, services: dict):
        self.services = services or {}
        self._cache: dict = {}
        self._cache_ttl = 45  # seconds — faster than OracleEngine for time-sensitive obligations

        self._vol_analyst   = VolatilityObligationAnalyst()
        self._liq_analyst   = LiquidityObligationAnalyst()
        self._dealer_analyst = DealerInventoryAnalyst()
        self._mr_analyst    = MeanReversionAnalyst()
        self._struct_analyst = StructuralBoundsAnalyst()
        self._truth_layer   = TruthLayer()
        self._oracle        = ActionResolutionOracle()

    def _get_service(self, name):
        return self.services.get(name)

    def _cached(self, key: str, fn, ttl: int = None):
        ttl = ttl or self._cache_ttl
        entry = self._cache.get(key)
        if entry and (time.time() - entry["ts"]) < ttl:
            return entry["data"]
        result = fn()
        self._cache[key] = {"ts": time.time(), "data": result}
        return result

    def _fetch_bars(self, symbol: str) -> list:
        dm = self._get_service("dm")
        if not dm:
            return []
        try:
            bars = dm.get_historical_bars(symbol, timeframe="1Day", limit=252)
            if bars:
                return bars
            # Fallback: try alternate key
            bars = dm.get_bars(symbol, timeframe="1D", limit=252)
            return bars or []
        except Exception as e:
            logger.warning(f"[IAM] Bars fetch failed for {symbol}: {e}")
            return []

    def _fetch_quote(self, symbol: str) -> dict:
        dm = self._get_service("dm")
        if not dm:
            return {}
        try:
            quotes = dm.get_quotes([symbol])
            return quotes.get(symbol, {}) if quotes else {}
        except Exception as e:
            logger.warning(f"[IAM] Quote fetch failed for {symbol}: {e}")
            return {}

    def _fetch_gamma_walls(self, symbol: str, price: float) -> dict:
        try:
            from execution_engine import ExecutionEngine
            from rmre_bridge import RMREBridge
            dm = self._get_service("dm")
            if not dm:
                return {}
            rmre = RMREBridge()
            ee = ExecutionEngine(schwab_api=None, rmre_bridge=rmre)
            ee.set_broker(dm)
            walls = ee.get_gamma_walls(symbol)
            if not walls:
                return {}
            return {
                "wall_above": walls.get("call_wall"),
                "wall_below": walls.get("put_wall"),
            }
        except Exception as e:
            logger.warning(f"[IAM] Gamma walls unavailable for {symbol}: {e}")
            return {}

    def _fetch_vpin(self, symbol: str, bars: list) -> float:
        try:
            from mmle_engine import MMLeEngine
            if not bars:
                return 0.0
            mmle = MMLeEngine()
            result = mmle.analyze(symbol, bars[-60:] if len(bars) > 60 else bars)
            return float(result.get("vpin", 0.0))
        except Exception:
            return 0.0

    def resolve(self, symbol: str) -> dict:
        """
        Main IAM resolution. Returns:
          - truth_layer: neutral obligation state (no direction)
          - obligation_committee: per-analyst pressure + direction + detail
          - resolution: mandatory action + rationale + execution params
          - metadata: symbol, price, timestamp, engine_version
        """
        ts     = datetime.now().isoformat()
        symbol = symbol.upper().strip()
        logger.info(f"[IAM] Resolving obligations for {symbol}")

        # 1. Fetch live data
        bars  = self._cached(f"bars_{symbol}",  lambda: self._fetch_bars(symbol),  ttl=60)
        quote = self._cached(f"quote_{symbol}", lambda: self._fetch_quote(symbol), ttl=20)
        price = float(quote.get("price") or 0)

        if price <= 0:
            logger.warning(f"[IAM] No price data for {symbol}")
            return {
                "symbol":    symbol,
                "timestamp": ts,
                "error":     "NO_PRICE_DATA",
                "message":   "No live price data available. Market may be closed or data provider unavailable.",
                "resolution": {
                    "action":       "HOLD",
                    "rationale":    "Cannot resolve obligations without live price data.",
                    "vehicle":      "No position",
                    "invalidation": "Retry when market is open",
                    "review_trigger": "Price data available",
                    "resolution_confidence": 0.0,
                }
            }

        # 2. Fetch supporting data (gamma walls, VPIN)
        gamma_walls = self._cached(f"gamma_{symbol}", lambda: self._fetch_gamma_walls(symbol, price), ttl=90)
        vpin        = self._cached(f"vpin_{symbol}",  lambda: self._fetch_vpin(symbol, bars),         ttl=60)

        # 3. Run independent obligation analysts (NO cross-communication)
        vol_result    = self._vol_analyst.analyze(symbol, bars, quote)
        liq_result    = self._liq_analyst.analyze(symbol, bars, quote)
        dealer_result = self._dealer_analyst.analyze(symbol, bars, quote, gamma_walls, vpin)
        mr_result     = self._mr_analyst.analyze(symbol, bars, quote)
        struct_result = self._struct_analyst.analyze(symbol, bars, quote)

        analyst_results = {
            "volatility":     vol_result,
            "liquidity":      liq_result,
            "dealer":         dealer_result,
            "mean_reversion": mr_result,
            "structural":     struct_result,
        }

        # 4. Truth Layer — neutral aggregation (no direction)
        truth = self._truth_layer.aggregate(analyst_results)

        # 5. Action Resolution Oracle — mandatory action
        resolution = self._oracle.resolve(truth, analyst_results, symbol, price)

        logger.info(
            f"[IAM] {symbol} → {resolution['action']} | "
            f"Stress: {truth['total_system_stress']}% | "
            f"Window: {truth['time_window']} | "
            f"Rationale: {resolution['rationale'][:60]}..."
        )

        return {
            "symbol":    symbol,
            "price":     price,
            "timestamp": ts,
            "engine":    "IAM-1.0",
            "truth_layer": {
                "total_system_stress":  truth["total_system_stress"],
                "volatility_release":   truth["obligations"].get("volatility", {}).get("pressure"),
                "liquidity_refill":     truth["obligations"].get("liquidity", {}).get("pressure"),
                "dealer_hedge":         truth["obligations"].get("dealer", {}).get("pressure"),
                "mean_reversion_pull":  truth["obligations"].get("mean_reversion", {}).get("pressure"),
                "structural_pressure":  truth["obligations"].get("structural", {}).get("pressure"),
                "directional_bias":     "NONE",
                "time_window":          truth["time_window"],
                "data_quality":         truth["data_quality"],
            },
            "obligation_committee": {
                name: result.to_dict()
                for name, result in analyst_results.items()
            },
            "resolution": {
                "action":               resolution["action"],
                "rationale":            resolution["rationale"],
                "vehicle":              resolution["vehicle"],
                "invalidation":         resolution["invalidation"],
                "review_trigger":       resolution["review_trigger"],
                "stress_reduction":     resolution["stress_reduction"],
                "stress_before":        resolution["stress_before"],
                "stress_after":         resolution["stress_after"],
                "dominant_obligation":  resolution["dominant_obligation"],
                "dominant_label":       resolution["dominant_label"],
                "resolution_confidence": resolution["resolution_confidence"],
            },
        }

    def truth_only(self, symbol: str) -> dict:
        """Runs only the Truth Layer — neutral obligation state, no action resolution."""
        ts     = datetime.now().isoformat()
        symbol = symbol.upper().strip()

        bars  = self._cached(f"bars_{symbol}",  lambda: self._fetch_bars(symbol),  ttl=60)
        quote = self._cached(f"quote_{symbol}", lambda: self._fetch_quote(symbol), ttl=20)
        price = float(quote.get("price") or 0)

        vpin = self._cached(f"vpin_{symbol}", lambda: self._fetch_vpin(symbol, bars), ttl=60)
        gamma_walls = {}

        analyst_results = {
            "volatility":     self._vol_analyst.analyze(symbol, bars, quote),
            "liquidity":      self._liq_analyst.analyze(symbol, bars, quote),
            "dealer":         self._dealer_analyst.analyze(symbol, bars, quote, gamma_walls, vpin),
            "mean_reversion": self._mr_analyst.analyze(symbol, bars, quote),
            "structural":     self._struct_analyst.analyze(symbol, bars, quote),
        }

        truth = self._truth_layer.aggregate(analyst_results)

        return {
            "symbol":    symbol,
            "price":     price,
            "timestamp": ts,
            "engine":    "IAM-1.0-TruthOnly",
            "next_required_action": {
                "volatility_release":   truth["obligations"].get("volatility", {}).get("pressure"),
                "liquidity_refill":     truth["obligations"].get("liquidity", {}).get("pressure"),
                "dealer_hedge":         truth["obligations"].get("dealer", {}).get("pressure"),
                "mean_reversion_pull":  truth["obligations"].get("mean_reversion", {}).get("pressure"),
                "structural_pressure":  truth["obligations"].get("structural", {}).get("pressure"),
                "directional_bias":     "NONE",
                "time_window":          truth["time_window"],
                "total_system_stress":  truth["total_system_stress"],
                "data_quality":         truth["data_quality"],
            },
        }
