"""
EdgeScanner — Risk & R:R Engine
════════════════════════════════
Calculates entry, stop, and target levels for each setup.
Enforces a minimum 2:1 reward-to-risk ratio.
All levels derived from price action (ATR-based). No arbitrary constants.
"""

import logging
from typing import Optional

logger = logging.getLogger("RISK_ENGINE")


class RiskEngine:
    """
    Converts raw setup detections into actionable trade plans.

    Stop placement:
      - Bullish: entry - (atr_mult * ATR)
      - Bearish: entry + (atr_mult * ATR)

    Target placement:
      - Uses R:R ratio applied to the stop distance
      - Minimum 2:1 enforced; patterns with stronger momentum get up to 3:1
    """

    # ATR multiplier varies by pattern — tighter for momentum, wider for mean-reversion
    _ATR_MULTS = {
        "TTM Squeeze Breakout": 1.2,
        "VWAP Reclaim": 1.0,
        "Bull Flag": 1.0,
        "Bear Flag": 1.0,
        "Volume Breakout": 1.5,
        "Oversold Bounce": 1.3,
    }
    _DEFAULT_ATR_MULT = 1.3
    _MIN_RR = 2.0
    _MAX_RR = 3.5

    def calculate(self, setup: dict) -> Optional[dict]:
        """
        Returns trade plan dict or None if the setup fails R:R minimum.

        Keys added:
          entry, stop, target, stop_dist, risk_pct,
          rr_ratio, position_size_1k (shares per $1000 risked)
        """
        price = float(setup.get("price", 0.0))
        atr = float(setup.get("atr", 0.0))
        pattern = setup.get("pattern", "")
        direction = setup.get("direction", "bullish")
        edge_score = float(setup.get("edge_score", 50.0))

        if price <= 0 or atr <= 0:
            return None

        atr_mult = self._ATR_MULTS.get(pattern, self._DEFAULT_ATR_MULT)

        # Entry at current close (market order assumption)
        entry = price

        if direction == "bullish":
            stop = round(entry - atr_mult * atr, 4)
            stop_dist = entry - stop
        else:
            stop = round(entry + atr_mult * atr, 4)
            stop_dist = stop - entry

        if stop_dist <= 0:
            return None

        # R:R scales with edge_score — higher confidence setups get a wider target
        rr_ratio = self._MIN_RR + (self._MAX_RR - self._MIN_RR) * (edge_score / 100.0)
        rr_ratio = round(rr_ratio, 2)

        if direction == "bullish":
            target = round(entry + rr_ratio * stop_dist, 4)
        else:
            target = round(entry - rr_ratio * stop_dist, 4)

        risk_pct = round(stop_dist / entry * 100, 2)
        pos_size_1k = round(1000.0 / stop_dist, 1) if stop_dist > 0 else 0.0

        return {
            "entry": round(entry, 2),
            "stop": round(stop, 2),
            "target": round(target, 2),
            "stop_dist": round(stop_dist, 4),
            "risk_pct": risk_pct,
            "rr_ratio": rr_ratio,
            "position_size_1k": pos_size_1k,
        }

    def enrich(self, setups: list[dict]) -> list[dict]:
        """Apply risk calculations to a list of setups. Drops setups that fail."""
        result = []
        for setup in setups:
            plan = self.calculate(setup)
            if plan is None:
                logger.debug(f"[RISK] {setup.get('symbol')} dropped — invalid R:R")
                continue
            result.append({**setup, **plan})
        return result
