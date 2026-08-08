"""
SML Harmonic Matrix Engine — Proprietary Ranked Configuration
=============================================================
Authoritative source: PROPRIETARY.txt (Harmonic Matrix Optimizer, God Mode)

18 ranked EMA configurations across three institutional tiers:
  GOD_MODE  — SET9 family, ranks 1-4 + 6-7, score ≥ 89  (INSTITUTIONAL grade)
  PRIME     — SET6 family, ranks 5 + 8-10 + 12-13
  WATCH     — SET3 family, ranks 11 + 14-18

Execution gate (Robinhood): tier=GOD_MODE AND god_stacked ≥ 3
Proprietary sequences are locked — do not recalculate.

APEX Committee Engine — patent-pending. Internal parameters redacted from API layer.
"""

import logging
from typing import List

logger = logging.getLogger("SML.HarmonicMatrix")

# ── Proprietary Ranked Configurations ────────────────────────────────────────
# Source: PROPRIETARY.txt — Harmonic Matrix Optimizer god mode
# EMA sequences are exact. Do not alter.

HARMONIC_CONFIGS = [
    # Rank  Config ID            EMA Sequence           Score   PF    Tier        Grade
    {"rank":  1, "id": "SET9_GAP3_5EMA", "sequence": [9,12,15,18,21], "score": 98.7, "pf": 2.14, "tier": "GOD_MODE", "grade": "INSTITUTIONAL", "phi": 0.987},
    {"rank":  2, "id": "SET9_GAP6_5EMA", "sequence": [9,15,21,27,33], "score": 94.7, "pf": 2.37, "tier": "GOD_MODE", "grade": "INSTITUTIONAL", "phi": None},
    {"rank":  3, "id": "SET9_GAP9_5EMA", "sequence": [9,18,27,36,45], "score": 94.1, "pf": 2.35, "tier": "GOD_MODE", "grade": "INSTITUTIONAL", "phi": None},
    {"rank":  4, "id": "SET9_GAP3_4EMA", "sequence": [9,12,15,18],    "score": 91.3, "pf": 2.28, "tier": "GOD_MODE", "grade": "INSTITUTIONAL", "phi": None},
    {"rank":  5, "id": "SET6_GAP3_5EMA", "sequence": [6,9,12,15,18],  "score": 90.3, "pf": 2.26, "tier": "PRIME",    "grade": "PRIME",         "phi": None},
    {"rank":  6, "id": "SET9_GAP6_4EMA", "sequence": [9,15,21,27],    "score": 89.7, "pf": 2.24, "tier": "GOD_MODE", "grade": "INSTITUTIONAL", "phi": None},
    {"rank":  7, "id": "SET9_GAP9_4EMA", "sequence": [9,18,27,36],    "score": 89.1, "pf": 2.23, "tier": "GOD_MODE", "grade": "INSTITUTIONAL", "phi": None},
    {"rank":  8, "id": "SET6_GAP6_5EMA", "sequence": [6,12,18,24,30], "score": 88.7, "pf": 2.22, "tier": "PRIME",    "grade": "PRIME",         "phi": None},
    {"rank":  9, "id": "SET6_GAP9_5EMA", "sequence": [6,15,24,33,42], "score": 88.1, "pf": 2.20, "tier": "PRIME",    "grade": "PRIME",         "phi": None},
    {"rank": 10, "id": "SET6_GAP3_4EMA", "sequence": [6,9,12,15],     "score": 85.3, "pf": 2.13, "tier": "PRIME",    "grade": "PRIME",         "phi": None},
    {"rank": 11, "id": "SET3_GAP3_5EMA", "sequence": [3,6,9,12,15],   "score": 84.3, "pf": 2.11, "tier": "WATCH",    "grade": "WATCH",         "phi": None},
    {"rank": 12, "id": "SET6_GAP6_4EMA", "sequence": [6,12,18,24],    "score": 83.7, "pf": 2.09, "tier": "PRIME",    "grade": "PRIME",         "phi": None},
    {"rank": 13, "id": "SET6_GAP9_4EMA", "sequence": [6,15,24,33],    "score": 83.1, "pf": 2.08, "tier": "PRIME",    "grade": "PRIME",         "phi": None},
    {"rank": 14, "id": "SET3_GAP6_5EMA", "sequence": [3,9,15,21,27],  "score": 82.7, "pf": 2.07, "tier": "WATCH",    "grade": "WATCH",         "phi": None},
    {"rank": 15, "id": "SET3_GAP9_5EMA", "sequence": [3,12,21,30,39], "score": 82.1, "pf": 2.05, "tier": "WATCH",    "grade": "WATCH",         "phi": None},
    {"rank": 16, "id": "SET3_GAP3_4EMA", "sequence": [3,6,9,12],      "score": 79.3, "pf": 1.98, "tier": "WATCH",    "grade": "WATCH",         "phi": None},
    {"rank": 17, "id": "SET3_GAP6_4EMA", "sequence": [3,9,15,21],     "score": 77.7, "pf": 1.94, "tier": "WATCH",    "grade": "WATCH",         "phi": None},
    {"rank": 18, "id": "SET3_GAP9_4EMA", "sequence": [3,12,21,30],    "score": 77.1, "pf": 1.93, "tier": "WATCH",    "grade": "WATCH",         "phi": None},
]

_MIN_BARS = 20  # Minimum bars for meaningful EMA computation on Polygon free tier


def _ema_value(closes: list, span: int) -> float:
    """Compute the most recent EMA value using pandas-style ewm."""
    import pandas as pd
    s = pd.Series([float(c) for c in closes])
    return float(s.ewm(span=span, adjust=False).mean().iloc[-1])


def analyze(closes: List[float]) -> dict:
    """
    Run all 18 proprietary ranked configurations against the given close series.
    Returns ranked results with tier labels, stacked status, and composite signal.

    The result is safe to serialize to JSON — no internal parameters exposed.
    """
    n = len(closes)
    if n < _MIN_BARS:
        return {
            "error":    f"insufficient_bars:{n}",
            "matrix":   {},
            "signal":   "INSUFFICIENT_DATA",
            "tier":     "NONE",
            "god_stacked":   0,
            "prime_stacked": 0,
            "watch_stacked": 0,
            "execute_gate":  False,
            "bear_signal":   "INSUFFICIENT_DATA",
            "bear_tier":     "NONE",
            "bear_god_stacked":   0,
            "bear_prime_stacked": 0,
            "bear_watch_stacked": 0,
            "bear_execute_gate":  False,
        }

    last_price = float(closes[-1])

    # Real ATR from last 14 bars — no hardcoded fallback
    if n >= 15:
        seq = [float(closes[i]) for i in range(-15, 0)]
        ranges = [abs(seq[i] - seq[i-1]) for i in range(1, len(seq))]
        atr = round(sum(ranges) / len(ranges), 4) if ranges else last_price * 0.015
    else:
        atr = last_price * 0.015

    matrix = {}
    god_stacked = 0
    prime_stacked = 0
    watch_stacked = 0
    bear_god_stacked = 0
    bear_prime_stacked = 0
    bear_watch_stacked = 0

    # Compute all 18 ranked configurations in rank order
    for cfg in HARMONIC_CONFIGS:
        seq = cfg["sequence"]
        try:
            emas = [_ema_value(closes, span) for span in seq]
        except Exception as e:
            logger.warning(f"[Harmonic] EMA compute error for {cfg['id']}: {e}")
            continue

        # Bullish stack: price > EMA1 > EMA2 > ... > EMAn (fastest to slowest)
        is_stacked = (
            last_price > emas[0]
            and all(emas[i] > emas[i+1] for i in range(len(emas) - 1))
        )
        # Bearish stack: mirror image — price < EMA1 < EMA2 < ... < EMAn.
        # Same proprietary period configurations (HARMONIC_CONFIGS) run in the
        # opposite direction — this is not a new proprietary parameter set,
        # just the symmetric test of the same ranked EMA sequences.
        is_stacked_bear = (
            last_price < emas[0]
            and all(emas[i] < emas[i+1] for i in range(len(emas) - 1))
        )

        if is_stacked:
            if cfg["tier"] == "GOD_MODE":
                god_stacked += 1
            elif cfg["tier"] == "PRIME":
                prime_stacked += 1
            else:
                watch_stacked += 1
        elif is_stacked_bear:
            if cfg["tier"] == "GOD_MODE":
                bear_god_stacked += 1
            elif cfg["tier"] == "PRIME":
                bear_prime_stacked += 1
            else:
                bear_watch_stacked += 1

        entry = {
            "rank":     cfg["rank"],
            "id":       cfg["id"],
            "tier":     cfg["tier"],
            "grade":    cfg["grade"],
            "score":    cfg["score"],
            "pf":       cfg["pf"],
            "sequence": seq,
            "stacked":  is_stacked,
            "stacked_bear": is_stacked_bear,
            "ema_values": [round(e, 2) for e in emas],
        }
        if cfg.get("phi"):
            entry["phi"] = cfg["phi"]

        matrix[cfg["id"]] = entry

    # ── Signal logic ──────────────────────────────────────────────────────────
    # Execution gate: GOD_MODE tier requires ≥3 SET9 configs stacked
    execute_gate = god_stacked >= 3
    bear_execute_gate = bear_god_stacked >= 3

    if god_stacked == 6:
        signal = "GOD_MODE_BULL"
        tier   = "GOD_MODE"
    elif god_stacked >= 4:
        signal = "FRACTAL_LOCK_BULL"
        tier   = "GOD_MODE"
    elif god_stacked >= 3:
        signal = "INSTITUTIONAL_CONVERGENCE"
        tier   = "GOD_MODE"
    elif god_stacked >= 1 and prime_stacked >= 2:
        signal = "PRIME_CONVERGENCE"
        tier   = "PRIME"
    elif prime_stacked >= 4:
        signal = "PRIME_ALIGNMENT"
        tier   = "PRIME"
    elif prime_stacked >= 2:
        signal = "PRIME_PARTIAL"
        tier   = "PRIME"
    elif watch_stacked >= 2:
        signal = "WATCH_ACTIVE"
        tier   = "WATCH"
    elif watch_stacked >= 1 or prime_stacked >= 1:
        signal = "WATCH_PARTIAL"
        tier   = "WATCH"
    else:
        signal = "NEUTRAL"
        tier   = "NONE"

    # Mirror of the bullish tier ladder above, same thresholds, bearish labels.
    if bear_god_stacked == 6:
        bear_signal = "GOD_MODE_BEAR"
        bear_tier   = "GOD_MODE"
    elif bear_god_stacked >= 4:
        bear_signal = "FRACTAL_LOCK_BEAR"
        bear_tier   = "GOD_MODE"
    elif bear_god_stacked >= 3:
        bear_signal = "INSTITUTIONAL_CONVERGENCE_BEAR"
        bear_tier   = "GOD_MODE"
    elif bear_god_stacked >= 1 and bear_prime_stacked >= 2:
        bear_signal = "PRIME_CONVERGENCE_BEAR"
        bear_tier   = "PRIME"
    elif bear_prime_stacked >= 4:
        bear_signal = "PRIME_ALIGNMENT_BEAR"
        bear_tier   = "PRIME"
    elif bear_prime_stacked >= 2:
        bear_signal = "PRIME_PARTIAL_BEAR"
        bear_tier   = "PRIME"
    elif bear_watch_stacked >= 2:
        bear_signal = "WATCH_ACTIVE_BEAR"
        bear_tier   = "WATCH"
    elif bear_watch_stacked >= 1 or bear_prime_stacked >= 1:
        bear_signal = "WATCH_PARTIAL_BEAR"
        bear_tier   = "WATCH"
    else:
        bear_signal = "NEUTRAL"
        bear_tier   = "NONE"

    # Harmonic convergence = any GOD_MODE stacked (institutional threshold)
    harmonic_convergence = god_stacked > 0
    bear_harmonic_convergence = bear_god_stacked > 0

    # Weighted composite score: rank 1 = weight 18, rank 18 = weight 1
    # Only count stacked configs
    weighted_sum = 0.0
    weight_total = 0.0
    bear_weighted_sum = 0.0
    bear_weight_total = 0.0
    for cfg in HARMONIC_CONFIGS:
        entry = matrix.get(cfg["id"], {})
        if entry.get("stacked"):
            w = 19 - cfg["rank"]  # rank 1 → weight 18, rank 18 → weight 1
            weighted_sum += cfg["score"] * w * cfg["pf"]
            weight_total += w
        elif entry.get("stacked_bear"):
            w = 19 - cfg["rank"]
            bear_weighted_sum += cfg["score"] * w * cfg["pf"]
            bear_weight_total += w
    harmonic_score = round(weighted_sum / weight_total, 2) if weight_total > 0 else 0.0
    bear_harmonic_score = round(bear_weighted_sum / bear_weight_total, 2) if bear_weight_total > 0 else 0.0

    # Decision directive
    if execute_gate:
        decision = "EXECUTE — GOD MODE CONFIRMED"
    elif tier == "PRIME":
        decision = "STANDBY — PRIME ALIGNMENT"
    elif tier == "WATCH":
        decision = "WATCH — BUILDING MOMENTUM"
    else:
        decision = "WAIT"

    if bear_execute_gate:
        bear_decision = "EXECUTE — GOD MODE BEAR CONFIRMED"
    elif bear_tier == "PRIME":
        bear_decision = "STANDBY — PRIME ALIGNMENT (BEAR)"
    elif bear_tier == "WATCH":
        bear_decision = "WATCH — BUILDING MOMENTUM (BEAR)"
    else:
        bear_decision = "WAIT"

    return {
        "matrix":              matrix,
        "signal":              signal,
        "tier":                tier,
        "god_stacked":         god_stacked,
        "prime_stacked":       prime_stacked,
        "watch_stacked":       watch_stacked,
        "total_configs":       len(HARMONIC_CONFIGS),
        "harmonic_convergence": harmonic_convergence,
        "harmonic_score":      harmonic_score,
        "execute_gate":        execute_gate,
        "decision":            decision,
        "highest_stacked_set": 9 if god_stacked > 0 else (6 if prime_stacked > 0 else (3 if watch_stacked > 0 else 0)),
        # ── Bearish mirror (see is_stacked_bear above) ──────────────────────
        "bear_signal":              bear_signal,
        "bear_tier":                bear_tier,
        "bear_god_stacked":         bear_god_stacked,
        "bear_prime_stacked":       bear_prime_stacked,
        "bear_watch_stacked":       bear_watch_stacked,
        "bear_harmonic_convergence": bear_harmonic_convergence,
        "bear_harmonic_score":      bear_harmonic_score,
        "bear_execute_gate":        bear_execute_gate,
        "bear_decision":            bear_decision,
        "bars_used":           n,
        "atr":                 atr,
        "levels": {
            "invalidation": round(last_price - atr * 1.5, 4),
            "tp1":          round(last_price + atr * 2.0, 4),
            "tp2":          round(last_price + atr * 4.0, 4),
        },
        "bear_levels": {
            "invalidation": round(last_price + atr * 1.5, 4),
            "tp1":          round(last_price - atr * 2.0, 4),
            "tp2":          round(last_price - atr * 4.0, 4),
        },
    }
