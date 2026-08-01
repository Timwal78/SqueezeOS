"""
Shared dynamic scan-width allocator for the Tradier-daily-bar scanners
(breakout_scanner.py, sr_matrix_scanner.py, sr_zone_pattern_scanner.py,
sovereign_squeeze_scanner.py, quad_score_scanner.py).

WHY DYNAMIC, NOT A STATIC PER-SCANNER NUMBER: a fixed "25" baked into each
scanner assumes exactly 5 siblings are always sharing the queue. If a
scanner is ever disabled (its own *_SCAN_ENABLED=false) or a new one is
added later, a static number either wastes safe headroom or, worse, drifts
stale without anyone recomputing the math. This module computes the total
safe shared budget ONCE from the real, verified constraint below, then
divides it evenly across however many secondary scanners are ACTUALLY
enabled right now -- so the allotment self-adjusts.

REAL CONSTRAINT (verified by reading tradier_api.py, not assumed):
`_rate_limit()` there enforces a GLOBAL, process-wide floor of
`_MIN_INTERVAL_SEC=1.05` seconds between ANY two Tradier API calls,
regardless of which scanner/thread makes them. This makes an actual
Tradier rate-limit violation structurally impossible no matter how wide
scans get -- the only real cost of going too wide is scan-cycle staleness
(an individual pass takes longer to finish), never an API error. So the
"allotment" here isn't a hard API quota; it's a self-imposed ceiling sized
so each scanner's own 300s SCAN_INTERVAL stays comfortably fresh even in
the pessimistic case where every scanner's pass starts at the same instant.

CASCADE (avg_down_engine.py) is NOT part of this dynamic pool -- it has its
own separately-decided, already-fixed AVG_DOWN_SCAN_TOP_N (default 40,
env-overridable, see the "No cap, many tickers" directive in CLAUDE.md) and
has no on/off flag of its own (always runs) -- its budget is reserved off
the top of the shared ceiling before dividing the remainder.

See CLAUDE.md's "Scan-width widened..." section for the full math and history.
"""
from __future__ import annotations

import os

TRADIER_MIN_INTERVAL_SEC = 1.05
SHARED_SCAN_INTERVAL_S = 300     # common SCAN_INTERVAL default across all 6 scanners
SAFETY_MARGIN = 0.5              # use at most half the interval for worst-case queue drain
MIN_PER_SCANNER = 5              # never starve an active scanner below a minimal useful width

# {display_name: enabled-flag env var} for every scanner that shares the
# Tradier-daily queue and can be toggled independently.
_SECONDARY_ENABLED_VARS = {
    "BREAKOUT": "BREAKOUT_SCAN_ENABLED",
    "SR_MATRIX": "SR_MATRIX_SCAN_ENABLED",
    "SR_ZONE_PATTERN": "SR_ZONE_PATTERN_SCAN_ENABLED",
    "SOVEREIGN_SQZ": "SOVEREIGN_SQZ_SCAN_ENABLED",
    "QUAD_SCORE": "QUAD_SCORE_SCAN_ENABLED",
}


def _is_enabled(env_var: str) -> bool:
    return os.environ.get(env_var, "true").strip().lower() == "true"


def _cascade_reserved() -> int:
    try:
        return int(os.environ.get("AVG_DOWN_SCAN_TOP_N", "40"))
    except ValueError:
        return 40


def active_secondary_scanners() -> list:
    """Names of the secondary (non-CASCADE) Tradier-daily scanners that are
    currently enabled, per their own *_SCAN_ENABLED flags."""
    return [name for name, var in _SECONDARY_ENABLED_VARS.items() if _is_enabled(var)]


def shared_budget_total() -> int:
    """Total safe call budget for one worst-case simultaneous queue-drain,
    using half the shared 300s interval as margin."""
    return int((SHARED_SCAN_INTERVAL_S * SAFETY_MARGIN) / TRADIER_MIN_INTERVAL_SEC)


def dynamic_top_n(scanner_name: str, explicit_env_var: str) -> int:
    """
    Returns the scan width this scanner should use.

    - An explicit `explicit_env_var` (e.g. BREAKOUT_SCAN_TOP_N) set on Render
      ALWAYS wins -- an operator's stated value is never second-guessed by
      this dynamic calculation.
    - Otherwise, computes an even share of the safe shared Tradier queue
      budget (after reserving CASCADE's own fixed allotment) across every
      secondary scanner that is CURRENTLY enabled, `scanner_name` included.
      If `scanner_name` itself isn't in the currently-enabled set (e.g. it
      was called before its own _ENABLED flag was read), it's still counted
      so a scanner never divides by a pool that excludes itself.
    """
    override = os.environ.get(explicit_env_var, "").strip()
    if override:
        return int(override)

    remaining = max(shared_budget_total() - _cascade_reserved(), 0)
    active = set(active_secondary_scanners())
    active.add(scanner_name)
    n_active = max(len(active), 1)
    return max(remaining // n_active, MIN_PER_SCANNER)
