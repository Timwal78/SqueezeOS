"""
Engine 4 — Temporal Mirror (As Above, So Below)
================================================
Pivot date: February 22, 2026.

Pre-pivot: the price sequence leading into the Feb 22 anchor is captured.
Post-pivot: that sequence is mirrored (reversed, reflected around pivot price)
           to create a shadow projection of where price "should" be.

Signal fires when live price holds ≥70% Pearson correlation with the
mirrored shadow — confirming that the post-pivot price is tracking the
mirror of the pre-pivot suppression pattern. This is the temporal proof
that a cyclical reversal is underway on schedule.

123/321 pivot: these are the lookback windows (trading bar counts) that
anchor the mirror on both the near (123-bar) and far (321-bar) time horizon.
"""

import logging
from datetime import date
from typing import List, Optional

logger = logging.getLogger("SML.E4.Temporal")

# ── Constants ─────────────────────────────────────────────────────────────────
PIVOT_DATE            = date(2026, 2, 22)
CORRELATION_THRESHOLD = 0.70
MIRROR_WINDOW_BARS    = 90    # how many pre-pivot bars to mirror
NEAR_WINDOW           = 123   # "near" temporal anchor (trading days)
FAR_WINDOW            = 321   # "far" temporal anchor (trading days)


def _pearson_r(x: list, y: list) -> float:
    """Pearson correlation — pure stdlib, no numpy dependency."""
    n = len(x)
    if n < 3:
        return 0.0
    mx = sum(x) / n
    my = sum(y) / n
    num  = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y))
    s_x  = sum((xi - mx) ** 2 for xi in x) ** 0.5
    s_y  = sum((yi - my) ** 2 for yi in y) ** 0.5
    if s_x == 0 or s_y == 0:
        return 0.0
    return num / (s_x * s_y)


def _find_pivot_bar(bars_with_dates: list) -> Optional[int]:
    """Find the index of the bar closest to Feb 22, 2026."""
    pivot_str = PIVOT_DATE.isoformat()
    closest_i = None
    closest_d = None
    for i, bar in enumerate(bars_with_dates):
        d = str(bar.get("date") or bar.get("t", ""))[:10]
        if not d:
            continue
        if closest_d is None or abs((date.fromisoformat(d) - PIVOT_DATE).days) < abs((date.fromisoformat(closest_d) - PIVOT_DATE).days):
            closest_d = d
            closest_i = i
    return closest_i


class Engine4_TemporalMirror:
    """
    Pivot: Feb 22, 2026
    Mirror window: up to 90 pre-pivot bars reversed and reflected
    Signal: Pearson r ≥ 0.70 between mirror projection and live price
    """

    PIVOT_DATE            = PIVOT_DATE
    CORRELATION_THRESHOLD = CORRELATION_THRESHOLD

    def analyze(self,
                closes: List[float],
                bars_with_dates: Optional[list] = None) -> dict:

        n     = len(closes)
        today = date.today()

        days_since_pivot = (today - PIVOT_DATE).days

        # Pre-pivot: engine waits silently
        if days_since_pivot < 0:
            return {
                "engine":          4,
                "name":            "Temporal Mirror",
                "pivot_date":      PIVOT_DATE.isoformat(),
                "status":          "PRE_PIVOT",
                "signal":          "STANDBY",
                "aligned":         False,
                "correlation":     0.0,
                "score_contrib":   0,
            }

        # Approximate trading days since pivot (~70% of calendar days)
        td_since = max(1, int(days_since_pivot * 0.70))

        # Find pivot bar index
        if bars_with_dates and len(bars_with_dates) >= 5:
            pivot_idx = _find_pivot_bar(bars_with_dates)
            if pivot_idx is None:
                pivot_idx = max(0, n - td_since)
        else:
            pivot_idx = max(0, n - td_since)

        # We need at least MIRROR_WINDOW_BARS of pre-pivot data
        avail_pre  = pivot_idx
        avail_post = n - pivot_idx

        if avail_pre < 5 or avail_post < 2:
            return {
                "engine":        4,
                "name":          "Temporal Mirror",
                "pivot_date":    PIVOT_DATE.isoformat(),
                "status":        "INSUFFICIENT_DATA",
                "signal":        "NEUTRAL",
                "aligned":       False,
                "correlation":   0.0,
                "score_contrib": 0,
            }

        window = min(MIRROR_WINDOW_BARS, avail_pre, avail_post)

        # Pre-pivot sequence (price going INTO the pivot)
        pre_pivot  = closes[pivot_idx - window : pivot_idx]
        # Post-pivot sequence (actual price AFTER pivot)
        post_pivot = closes[pivot_idx : pivot_idx + window]

        # Mirror: reverse the pre-pivot sequence
        # Amplitude-reflect around the pivot price so the shadow is directional
        pivot_price  = closes[pivot_idx] if pivot_idx < n else closes[-1]
        pre_reversed = list(reversed(pre_pivot))[:len(post_pivot)]
        mirror_proj  = [pivot_price + (pivot_price - p) for p in pre_reversed]

        actual = post_pivot[:len(mirror_proj)]

        if len(actual) < 3:
            return {
                "engine":        4, "signal": "NEUTRAL", "aligned": False,
                "correlation": 0.0, "score_contrib": 0,
                "pivot_date": PIVOT_DATE.isoformat(),
            }

        r = _pearson_r(actual, mirror_proj)

        # 22nd-of-month window check
        near_22nd = abs(today.day - 22) <= 3

        # Near / far temporal band alignment
        p_near = closes[-min(NEAR_WINDOW, n)]
        p_far  = closes[-min(FAR_WINDOW, n)]
        price  = closes[-1]
        in_temporal_band = min(p_near, p_far) * 0.97 <= price <= max(p_near, p_far) * 1.03

        aligned = r >= CORRELATION_THRESHOLD

        if aligned and near_22nd:
            signal = "TEMPORAL_ALIGNED_22ND"
        elif aligned:
            signal = "TEMPORAL_ALIGNED"
        elif r >= 0.50:
            signal = "PARTIAL_CORRELATION"
        elif near_22nd:
            signal = "NEAR_22ND_WATCH"
        elif in_temporal_band:
            signal = "IN_TEMPORAL_BAND"
        else:
            signal = "NEUTRAL"

        return {
            "engine":             4,
            "name":               "Temporal Mirror",
            "pivot_date":         PIVOT_DATE.isoformat(),
            "days_since_pivot":   days_since_pivot,
            "mirror_window_bars": window,
            "pivot_price":        round(pivot_price, 4),
            "correlation":        round(r, 4),
            "correlation_threshold": CORRELATION_THRESHOLD,
            "near_22nd_window":   near_22nd,
            "in_temporal_band":   in_temporal_band,
            "p_near_123":         round(p_near, 4),
            "p_far_321":          round(p_far,  4),
            "aligned":            aligned,
            "signal":             signal,
            "score_contrib":      20 if aligned else 8 if r >= 0.50 else 3 if near_22nd else 0,
        }
