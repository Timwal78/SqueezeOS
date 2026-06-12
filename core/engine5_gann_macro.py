"""
Engine 5 — Macro Frequency Confirmation Filter
================================================
Price closes only. The ultimate confirmation filter — does NOT fire on
price position alone. Fires when a fast-tier EMA curls (slope reverses
from descending to ascending) toward a macro-frequency anchor while
price is in a suppressed state from Engine 1. Validates that momentum
is re-accelerating from the loaded-elastic zone.

Internal parameters (periods, slope window, alignment rules) are proprietary.
"""

import logging
from typing import List

logger = logging.getLogger("SML.E5.Gann")

# Import shared EMA primitive
from core.proprietary_ema_engine import _ema, _tail


def _slope(series: list, lookback: int = 3) -> float:
    """
    Direction of change over last `lookback` bars.
    Positive = curling up. Negative = curling down.
    """
    if len(series) < lookback + 1:
        return 0.0
    recent = series[-lookback:]
    # Linear regression slope via least-squares shortcut
    n  = len(recent)
    sx = sum(range(n))
    sy = sum(recent)
    sxy = sum(i * v for i, v in enumerate(recent))
    sx2 = sum(i * i for i in range(n))
    denom = n * sx2 - sx * sx
    if denom == 0:
        return 0.0
    return (n * sxy - sx * sy) / denom


class Engine5_GannMacro:
    """
    Periods: 1 · 42 · 369 · 578  (price dimension only)
    Trigger: 42 EMA curls upward toward 369 while price is suppressed.
    Confirms Engine 1 snapback signal.
    """

    PERIODS = (1, 42, 369, 578)

    def analyze(self, closes: List[float]) -> dict:
        n = len(closes)
        if n < 10:
            return {"engine": 5, "signal": "INSUFFICIENT_DATA",
                    "macro_suppressed": False, "score_contrib": 0}

        price = closes[-1]

        ema42_series  = _ema(closes, min(42,  n))
        ema369_series = _ema(closes, min(369, n))
        ema578_series = _ema(closes, min(578, n))

        ema42  = _tail(ema42_series)
        ema369 = _tail(ema369_series)
        ema578 = _tail(ema578_series)

        # ── Position ──────────────────────────────────────────────
        below_42  = price < ema42
        below_369 = price < ema369
        below_578 = price < ema578

        # Macro suppression: price below ALL three Gann levels
        macro_suppressed = below_42 and below_369 and below_578

        # ── Curl detection on the 42 EMA ──────────────────────────
        # The critical signal: 42 EMA changing from falling → rising
        slope_42  = _slope(ema42_series,  lookback=5)
        slope_369 = _slope(ema369_series, lookback=5)

        # "Curling toward 369" = 42 EMA slope turning positive while still below 369
        curl_up_42  = slope_42  > 0 and ema42 < ema369
        # 369 starting to flatten or rise = macro frequency waking up
        freq_wake   = slope_369 > -0.01   # 369 slope ≥ 0 (flat or rising)

        gann_confirmation = curl_up_42 and freq_wake and below_578

        # ── Stretch from macro anchor ─────────────────────────────
        stretch_369 = (price - ema369) / ema369 * 100 if ema369 else 0.0

        # ── Signal ────────────────────────────────────────────────
        if gann_confirmation and macro_suppressed:
            signal = "GANN_IGNITION"          # 42 curling, macro suppressed = lethal
        elif gann_confirmation:
            signal = "GANN_CURL_CONFIRMED"    # curl confirmed, price partially recovered
        elif macro_suppressed:
            signal = "MACRO_SUPPRESSED"       # all below — waiting for curl
        elif not below_578 and not below_369:
            signal = "MACRO_BREAKOUT"         # price reclaimed both levels
        elif not below_42:
            signal = "ABOVE_GANN_42"          # 42 reclaimed, recovery underway
        else:
            signal = "NEUTRAL"

        _score = {
            "GANN_IGNITION":       25,
            "GANN_CURL_CONFIRMED": 18,
            "MACRO_SUPPRESSED":   -10,   # bearish — but confirms suppression setup
            "MACRO_BREAKOUT":      15,
            "ABOVE_GANN_42":        8,
            "NEUTRAL":              0,
        }

        return {
            "engine":            5,
            "name":              "Tesla/Gann Macro Frequency",
            "sequence":          "PROPRIETARY",
            "dimension":         "PRICE",
            "ema42":             round(ema42,  4),
            "ema369":            round(ema369, 4),
            "ema578":            round(ema578, 4),
            "stretch_369_pct":   round(stretch_369, 3),
            "slope_42":          round(slope_42,  6),
            "slope_369":         round(slope_369, 6),
            "below_42":          below_42,
            "below_369":         below_369,
            "below_578":         below_578,
            "macro_suppressed":  macro_suppressed,
            "curl_up_42":        curl_up_42,
            "freq_wake_369":     freq_wake,
            "gann_confirmation": gann_confirmation,
            "signal":            signal,
            "score_contrib":     _score.get(signal, 0),
        }
