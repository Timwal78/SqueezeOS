"""
Engine 7 — SML Parabolic Flight Path
====================================
A standalone sub-routine that slices the Base-4 Matrix diagonally to track
non-linear geometric acceleration, liquidity exhaustion, and symmetrical consolidation.

It is deployed when the HUD detects an 'APEX SINGULARITY'.
"""

import logging
from typing import List, Dict, Any

from core.proprietary_ema_engine import _ema, _tail

logger = logging.getLogger("SML.Engine7")

class Engine7_Parabolic:
    """
    Engine 7 — SML Parabolic Flight Path.
    Extracts non-linear, geometric acceleration curves.
    """

    def analyze(self, closes: List[float], is_singularity: bool) -> dict:
        n = len(closes)
        if n < 48:
            return {"engine": 7, "signal": "INSUFFICIENT_DATA"}

        price = closes[-1]
        
        # Calculate the required diagonal EMAs
        e1  = _tail(_ema(closes, min(1,  n)))
        e4  = _tail(_ema(closes, min(4,  n)))
        e8  = _tail(_ema(closes, min(8,  n)))
        e12 = _tail(_ema(closes, min(12, n)))
        e16 = _tail(_ema(closes, min(16, n)))
        e24 = _tail(_ema(closes, min(24, n)))
        e36 = _tail(_ema(closes, min(36, n)))
        e48 = _tail(_ema(closes, min(48, n)))

        # ── 1. The Quadratic Expansion (4, 16, 36) ─────────────────────────
        # Represents geometric acceleration. Asset is trapped in a mathematically
        # flawless quadratic launch sequence if riding the 4, holding 16, and macro 36.
        quadratic_bull = price > e4 > e16 > e36
        quadratic_bear = price < e4 < e16 < e36

        # ── 2. The Multiplier Compression (1, 8, 24, 48) ───────────────────
        # "Liquidity Exhaustion" tracker. 
        compression_stack_bull = price > e1 > e8 > e24 > e48
        liquidity_exhaustion   = e1 < e8 and e8 > e24 > e48
        compression_failed     = e1 < e8 and price < e24

        # ── 3. The Symmetrical Pivot (12, 16) ──────────────────────────────
        # Symmetrical harmonic pivot point. 16 EMA is the absolute center-of-gravity.
        pivot_diff_pct = abs(e12 - e16) / price if price else 0.0
        symmetrical_consolidation = pivot_diff_pct < 0.005

        # ── Signal Logic ───────────────────────────────────────────────────
        signal = "NEUTRAL"
        
        if is_singularity:
            if quadratic_bull:
                signal = "QUADRATIC_LAUNCH_BULL"
            elif quadratic_bear:
                signal = "QUADRATIC_LAUNCH_BEAR"
            elif compression_failed:
                signal = "COMPRESSION_FAILED"
            elif liquidity_exhaustion:
                signal = "LIQUIDITY_EXHAUSTION"
            elif symmetrical_consolidation:
                signal = "SYMMETRICAL_CONSOLIDATION"
            else:
                signal = "PARABOLIC_CHOP"
        else:
            signal = "DORMANT"

        _score_map = {
            "QUADRATIC_LAUNCH_BULL":     100,
            "QUADRATIC_LAUNCH_BEAR":    -100,
            "LIQUIDITY_EXHAUSTION":      -20,
            "COMPRESSION_FAILED":        -50,
            "SYMMETRICAL_CONSOLIDATION":   0,
            "PARABOLIC_CHOP":              0,
            "DORMANT":                     0,
            "NEUTRAL":                     0,
        }

        return {
            "engine":             7,
            "name":               "SML Parabolic Flight Path",
            "dimension":          "GEOMETRIC_ACCELERATION",
            "is_singularity":     is_singularity,
            "quadratic_bull":     quadratic_bull,
            "quadratic_bear":     quadratic_bear,
            "liquidity_exhaustion": liquidity_exhaustion,
            "compression_failed":   compression_failed,
            "symmetrical_consolidation": symmetrical_consolidation,
            "pivot_diff_pct":     round(pivot_diff_pct * 100, 4),
            "signal":             signal,
            "score_contrib":      _score_map.get(signal, 0),
            
            # Internal raw data (redacted before JSON serialization)
            "_raw_emas":          {"e1": e1, "e4": e4, "e8": e8, "e12": e12, "e16": e16, "e24": e24, "e36": e36, "e48": e48}
        }

def redact_engine7_block(block: dict) -> dict:
    """Strips internal parameters and EMA values from Engine 7 output."""
    if not isinstance(block, dict):
        return block
    
    safe_fields = {
        "engine", "dimension", "signal", "score_contrib", 
        "is_singularity", "quadratic_bull", "quadratic_bear",
        "liquidity_exhaustion", "compression_failed", "symmetrical_consolidation"
    }
    return {k: v for k, v in block.items() if k in safe_fields}
