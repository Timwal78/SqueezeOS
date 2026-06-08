"""
Engine 6 — Base-4 Fractal Matrix
================================
Implements the interlocking 9-set ScriptMaster Base-4 Fractal Grid.
By running X from 1 through 9 through the Base-4 Fractal formula (X, 4X, 8X, 12X),
it creates a completely interlocking grid of moving averages.

Set N structure: [Base Trigger (N), Core Baseline (4N), Validator (8N), Macro Anchor (12N)]
"""

import logging
from typing import List, Dict, Any

from core.proprietary_ema_engine import _ema, _tail

logger = logging.getLogger("SML.Engine6")

class Engine6_Base4Matrix:
    """
    Engine 6 — The Base-4 Fractal Matrix.
    Evaluates 36 EMAs across 9 harmonically bound sets.
    """

    def __init__(self):
        # Generate the 9 sets
        self.sets = {}
        for x in range(1, 10):
            self.sets[x] = {
                "trigger": x,
                "core": 4 * x,
                "validator": 8 * x,
                "anchor": 12 * x
            }

    def analyze(self, closes: List[float]) -> dict:
        n = len(closes)
        # We need at least 108 bars to properly calculate Set 9's anchor
        if n < 108:
            return {"engine": 6, "signal": "INSUFFICIENT_DATA"}

        price = closes[-1]
        
        calculated_emas = {}
        bull_stacks = 0
        bear_stacks = 0
        
        # Calculate all EMAs and count alignments
        for x, periods in self.sets.items():
            t = _tail(_ema(closes, min(periods["trigger"], n)))
            c = _tail(_ema(closes, min(periods["core"], n)))
            v = _tail(_ema(closes, min(periods["validator"], n)))
            a = _tail(_ema(closes, min(periods["anchor"], n)))
            
            calculated_emas[x] = {"t": t, "c": c, "v": v, "a": a}
            
            if t > c > v > a:
                bull_stacks += 1
            elif t < c < v < a:
                bear_stacks += 1

        # Calculate cross-matrix dynamics
        set1 = calculated_emas[1]
        set9 = calculated_emas[9]
        
        # Matrix Expansion / Compression
        # Distance from the fastest trigger (1) to the slowest anchor (108)
        matrix_width_pct = abs(set1["t"] - set9["a"]) / price if price else 0.0
        
        matrix_compressed = matrix_width_pct < 0.02
        matrix_expanding  = matrix_width_pct > 0.15

        # Macro Cross: Set 1 Trigger crosses Set 9 Macro Anchor
        macro_cross_bull = set1["t"] > set9["a"]
        macro_cross_bear = set1["t"] < set9["a"]

        # Signal Logic
        if bull_stacks == 9 and matrix_expanding:
            signal = "GOD_MODE_BULL"
        elif bear_stacks == 9 and matrix_expanding:
            signal = "GOD_MODE_BEAR"
        elif bull_stacks == 9:
            signal = "FRACTAL_LOCK_BULL"
        elif bear_stacks == 9:
            signal = "FRACTAL_LOCK_BEAR"
        elif macro_cross_bull and bull_stacks >= 5:
            signal = "MACRO_IGNITION_BULL"
        elif macro_cross_bear and bear_stacks >= 5:
            signal = "MACRO_IGNITION_BEAR"
        elif matrix_compressed:
            signal = "MATRIX_COMPRESSED"
        else:
            signal = "NEUTRAL"

        _score_map = {
            "GOD_MODE_BULL":        50,
            "GOD_MODE_BEAR":       -50,
            "FRACTAL_LOCK_BULL":    30,
            "FRACTAL_LOCK_BEAR":   -30,
            "MACRO_IGNITION_BULL":  15,
            "MACRO_IGNITION_BEAR": -15,
            "MATRIX_COMPRESSED":     0,
            "NEUTRAL":               0,
        }

        # The raw values are collected here but will be stripped by the API layer redaction
        return {
            "engine":             6,
            "name":               "Base-4 Fractal Matrix",
            "dimension":          "HARMONIC_GRID",
            "bull_stacks":        bull_stacks,
            "bear_stacks":        bear_stacks,
            "total_sets":         9,
            "matrix_width_pct":   round(matrix_width_pct * 100, 4),
            "matrix_compressed":  matrix_compressed,
            "matrix_expanding":   matrix_expanding,
            "macro_cross_bull":   macro_cross_bull,
            "macro_cross_bear":   macro_cross_bear,
            "signal":             signal,
            "score_contrib":      _score_map.get(signal, 0),
            
            # Internal raw data (redacted before JSON serialization)
            "_raw_sets":          calculated_emas
        }

def redact_engine6_block(block: dict) -> dict:
    """Strips internal parameters and EMA values from Engine 6 output."""
    if not isinstance(block, dict):
        return block
    
    safe_fields = {
        "engine", "dimension", "signal", "score_contrib", 
        "bull_stacks", "bear_stacks", "total_sets",
        "matrix_compressed", "matrix_expanding",
        "macro_cross_bull", "macro_cross_bear"
    }
    return {k: v for k, v in block.items() if k in safe_fields}
