"""
Grid 369 Engine — Proprietary 3×3 Anchor Matrix
================================================
Second proprietary grid from PROPRIETARY.txt.
9 configurations: 3 base levels × 3 gap sizes, all 5-EMA sequences.

Structure:
  Base 3 × Gap 12 → [3·6·9·12·15]    Anchor 15
  Base 3 × Gap 24 → [3·9·15·21·27]   Anchor 27
  Base 3 × Gap 36 → [3·12·21·30·39]  Anchor 39
  Base 6 × Gap 12 → [6·9·12·15·18]   Anchor 18
  Base 6 × Gap 24 → [6·12·18·24·30]  Anchor 30
  Base 6 × Gap 36 → [6·15·24·33·42]  Anchor 36
  Base 9 × Gap 12 → [9·12·15·18·21]  Anchor 21  ← Selected (tightest kinetic cluster)
  Base 9 × Gap 24 → [9·15·21·27·33]  Anchor 33
  Base 9 × Gap 36 → [9·18·27·36·45]  Anchor 45

Selected Gap: 12 · Anchor Depth: 15
Grid ID 6 [9·12·15·18·21] = identical to Grid 1 Rank 1 (SET9_GAP3_5EMA, score 98.7, φ 0.987)
Grid ID 7 [9·15·21·27·33] = identical to Grid 1 Rank 2 (SET9_GAP6_5EMA, PF 2.37)
Grid ID 8 [9·18·27·36·45] = identical to Grid 1 Rank 3 (SET9_GAP9_5EMA, PF 2.35)

DUAL GRID LOCK: Grid 1 GOD_MODE (≥3 of its 6 configs stacked) AND a majority of
Grid 2's Base-3/Base-6 rows (IDs 0-5) stacked.

Base-9 IDs 6/7/8 are IDENTICAL EMA sequences to Grid 1 ranks 1/2/3
(SET9_GAP3/6/9_5EMA) — recomputing them as a "second" confirmation isn't an
independent methodology, it's the same three sequences evaluated twice. The
genuinely independent second opinion lives in the Base-3 and Base-6 rows
(IDs 0-5), which use different EMA period families entirely. Dual Grid Lock
below requires a majority (4 of 6) of THOSE to agree with Grid 1, not a
re-check of Grid 1's own numbers. base9_stacked is still reported for
diagnostic visibility, just no longer used to gate the lock.

APEX Committee Engine — patent-pending. Internal parameters redacted from API layer.
"""

import logging
from typing import List

from core.ema_stack_utils import stack_persistence

logger = logging.getLogger("SML.Grid369")

# ── Proprietary 3×3 Grid Configurations ──────────────────────────────────────

GRID_369_CONFIGS = [
    {"id": 0, "base": 3, "gap": 12, "sequence": [3, 6,  9,  12, 15], "anchor": 15, "row": "BASE_3"},
    {"id": 1, "base": 3, "gap": 24, "sequence": [3, 9,  15, 21, 27], "anchor": 27, "row": "BASE_3"},
    {"id": 2, "base": 3, "gap": 36, "sequence": [3, 12, 21, 30, 39], "anchor": 39, "row": "BASE_3"},
    {"id": 3, "base": 6, "gap": 12, "sequence": [6, 9,  12, 15, 18], "anchor": 18, "row": "BASE_6"},
    {"id": 4, "base": 6, "gap": 24, "sequence": [6, 12, 18, 24, 30], "anchor": 30, "row": "BASE_6"},
    {"id": 5, "base": 6, "gap": 36, "sequence": [6, 15, 24, 33, 42], "anchor": 42, "row": "BASE_6"},
    {"id": 6, "base": 9, "gap": 12, "sequence": [9, 12, 15, 18, 21], "anchor": 21, "row": "BASE_9", "selected": True},
    {"id": 7, "base": 9, "gap": 24, "sequence": [9, 15, 21, 27, 33], "anchor": 33, "row": "BASE_9"},
    {"id": 8, "base": 9, "gap": 36, "sequence": [9, 18, 27, 36, 45], "anchor": 45, "row": "BASE_9"},
]

# Base-9 IDs that mirror Grid 1's top 3 GOD_MODE configs
_DUAL_LOCK_IDS = {6, 7, 8}

_MIN_BARS = 20


def analyze(closes: List[float], grid1_god_stacked: int = 0, grid1_bear_god_stacked: int = 0,
            confirm_bars: int = 2) -> dict:
    """
    Run all 9 Grid 369 configurations against the close series.
    grid1_god_stacked / grid1_bear_god_stacked: pass in god_stacked/bear_god_stacked
    from harmonic_matrix_engine so we can compute DUAL GRID LOCK (both directions)
    without re-running Grid 1.
    confirm_bars: same persistence filter as harmonic_matrix_engine.analyze() —
    a config only counts as stacked if it's held for this many consecutive
    bars, not just the current one. Pass 1 to restore the old single-bar
    behavior.
    """
    n = len(closes)
    if n < _MIN_BARS:
        return {
            "error":          f"insufficient_bars:{n}",
            "grid":           {},
            "signal":         "INSUFFICIENT_DATA",
            "dual_grid_lock": False,
            "base9_stacked":  0,
            "bear_signal":         "INSUFFICIENT_DATA",
            "dual_grid_lock_bear": False,
            "base9_stacked_bear":  0,
        }

    confirm_bars = max(1, int(confirm_bars))
    window = min(confirm_bars, n)

    grid       = {}
    base3_stacked = 0
    base6_stacked = 0
    base9_stacked = 0
    base3_stacked_bear = 0
    base6_stacked_bear = 0
    base9_stacked_bear = 0

    for cfg in GRID_369_CONFIGS:
        seq = cfg["sequence"]
        try:
            is_stacked, is_stacked_bear, emas = stack_persistence(closes, seq, window)
        except Exception as e:
            logger.warning(f"[Grid369] EMA error id={cfg['id']}: {e}")
            continue

        if is_stacked:
            if cfg["base"] == 3:
                base3_stacked += 1
            elif cfg["base"] == 6:
                base6_stacked += 1
            else:
                base9_stacked += 1
        elif is_stacked_bear:
            if cfg["base"] == 3:
                base3_stacked_bear += 1
            elif cfg["base"] == 6:
                base6_stacked_bear += 1
            else:
                base9_stacked_bear += 1

        grid[cfg["id"]] = {
            "id":         cfg["id"],
            "base":       cfg["base"],
            "gap":        cfg["gap"],
            "row":        cfg["row"],
            "sequence":   seq,
            "anchor":     cfg["anchor"],
            "stacked":    is_stacked,
            "stacked_bear": is_stacked_bear,
            "ema_values": [round(e, 2) for e in emas],
            "selected":   cfg.get("selected", False),
        }

    total_stacked = base3_stacked + base6_stacked + base9_stacked
    total_stacked_bear = base3_stacked_bear + base6_stacked_bear + base9_stacked_bear

    # DUAL GRID LOCK: Grid 1 GOD_MODE (≥3 of its 6 configs) AND a majority (4 of
    # 6) of Grid 2's genuinely independent Base-3/Base-6 configs agree — see the
    # module docstring for why base9_stacked (IDs 6/7/8, identical to Grid 1
    # ranks 1-3) can't be the thing that confirms Grid 1 without it being a
    # circular re-check of the same three EMA sequences.
    independent_stacked = base3_stacked + base6_stacked
    independent_stacked_bear = base3_stacked_bear + base6_stacked_bear
    dual_grid_lock = (grid1_god_stacked >= 3) and (independent_stacked >= 4)
    dual_grid_lock_bear = (grid1_bear_god_stacked >= 3) and (independent_stacked_bear >= 4)

    # Signal
    if dual_grid_lock:
        signal = "DUAL_GRID_LOCK"
    elif base9_stacked == 3 and base6_stacked >= 2:
        signal = "GRID369_PRIME_BULL"
    elif base9_stacked >= 2:
        signal = "GRID369_BASE9_ACTIVE"
    elif base9_stacked >= 1 and base6_stacked >= 1:
        signal = "GRID369_CONVERGENCE"
    elif total_stacked >= 3:
        signal = "GRID369_PARTIAL"
    else:
        signal = "GRID369_NEUTRAL"

    # Mirror of the bullish signal ladder above, bearish labels.
    if dual_grid_lock_bear:
        bear_signal = "DUAL_GRID_LOCK_BEAR"
    elif base9_stacked_bear == 3 and base6_stacked_bear >= 2:
        bear_signal = "GRID369_PRIME_BEAR"
    elif base9_stacked_bear >= 2:
        bear_signal = "GRID369_BASE9_ACTIVE_BEAR"
    elif base9_stacked_bear >= 1 and base6_stacked_bear >= 1:
        bear_signal = "GRID369_CONVERGENCE_BEAR"
    elif total_stacked_bear >= 3:
        bear_signal = "GRID369_PARTIAL_BEAR"
    else:
        bear_signal = "GRID369_NEUTRAL"

    return {
        "grid":           grid,
        "signal":         signal,
        "dual_grid_lock": dual_grid_lock,
        "base3_stacked":  base3_stacked,
        "base6_stacked":  base6_stacked,
        "base9_stacked":  base9_stacked,
        "total_stacked":  total_stacked,
        # ── Bearish mirror ──────────────────────────────────────────────────
        "bear_signal":          bear_signal,
        "dual_grid_lock_bear":  dual_grid_lock_bear,
        "base3_stacked_bear":   base3_stacked_bear,
        "base6_stacked_bear":   base6_stacked_bear,
        "base9_stacked_bear":   base9_stacked_bear,
        "total_stacked_bear":   total_stacked_bear,
        "confirm_bars":   window,
        "selected_gap":   12,
        "anchor_depth":   15,
    }
