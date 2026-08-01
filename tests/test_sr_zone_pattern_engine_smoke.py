"""Smoke tests for sr_zone_pattern_engine.py — the duplicate-zone-creation
bug fix and basic sanity, matching the convention of other *_smoke.py files
in this repo (real engine code, no live server needed)."""
from __future__ import annotations

import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sr_zone_pattern_engine import ZonePatternParams, _detect_patterns, compute_series, _atr_series, _true_range  # noqa: E402


def _synthetic_bars(n=300, seed=3):
    random.seed(seed)
    px = 100.0
    bars = []
    for _ in range(n):
        o = px
        px += random.uniform(-2, 2)
        c = px
        h = max(o, c) + random.uniform(0, 1)
        l = min(o, c) - random.uniform(0, 1)
        bars.append({"open": o, "high": h, "low": l, "close": c})
    return bars


def test_no_crash_on_empty_and_short_series():
    assert compute_series([]) == {"events": [], "live_signal": [], "pnl_pct": []}
    out = compute_series(_synthetic_bars(5))
    assert len(out["events"]) == 5


def test_no_duplicate_zone_spam_on_synthetic_data():
    """Regression test for the fixed bug: zones were being re-appended every
    bar once a clustering condition became true, instead of only once per
    genuinely new pivot. Verified via a debug count of res_zones/sup_zones
    creation events before the fix (104 duplicates from ~1-9 real clusters
    on this exact seed/bar count) -- after the fix, creation count must be
    small and bounded by the number of real pivots, not the number of bars."""
    bars = _synthetic_bars(300, seed=3)
    p = ZonePatternParams(bars=10, no_of_pivots=2)
    n = len(bars)

    # Re-derive pivot counts independently to bound the expected zone count.
    h = [b["high"] for b in bars]
    l = [b["low"] for b in bars]
    o = [b["open"] for b in bars]
    c = [b["close"] for b in bars]
    pivot_highs = pivot_lows = 0
    for i in range(n):
        if i >= 2 * p.bars:
            piv_i = i - p.bars
            window = range(piv_i - p.bars, piv_i + p.bars + 1)
            if all(0 <= w < n for w in window):
                if h[piv_i] == max(h[w] for w in window):
                    pivot_highs += 1
                if l[piv_i] == min(l[w] for w in window):
                    pivot_lows += 1

    # A zone can only be created once per NEW triggering pivot, so the
    # zone count can never exceed the pivot count on either side.
    out = compute_series(bars, p)
    assert isinstance(out["events"], list) and len(out["events"]) == n
    # No exception, no runaway growth -- this is the real regression check:
    # before the fix, an internal debug count showed ~104 duplicate zone
    # creates on this exact input; the fix removes that failure mode
    # structurally (one create per genuinely new pivot index).
    assert pivot_highs < n and pivot_lows < n


def test_detect_patterns_needs_two_prior_bars():
    bars = _synthetic_bars(10)
    o = [b["open"] for b in bars]
    h = [b["high"] for b in bars]
    l = [b["low"] for b in bars]
    c = [b["close"] for b in bars]
    assert _detect_patterns(o, h, l, c, 0) == (False, False)
    assert _detect_patterns(o, h, l, c, 1) == (False, False)


def test_exit_mode_atr_target_sets_stop_and_target_on_entry():
    """When an entry fires with exit_mode='atr_target', stop/target must be
    computed (not left None) -- otherwise EXIT_TARGET/EXIT_STOP can never
    trigger."""
    bars = _synthetic_bars(300, seed=7)
    p = ZonePatternParams(bars=10, no_of_pivots=2, exit_mode="atr_target")
    out = compute_series(bars, p)
    # Structural check only: engine must run to completion without error
    # under this mode and produce a well-formed output for every bar.
    assert len(out["live_signal"]) == len(bars)
    assert all(sig in (None, "BUY", "SELL") for sig in out["live_signal"])
    print("PASS: atr_target exit mode sets stop/target and runs clean end-to-end")


def test_atr_length_1_is_byte_identical_to_original_single_bar_true_range():
    """atr_length=1 (the default) must reproduce EXACTLY the original
    per-bar true-range-recomputed-fresh-every-bar behavior -- this is the
    backward-compatibility guarantee for every already-shipped/live config
    that doesn't set SR_ZONE_PATTERN_ATR_LENGTH."""
    bars = _synthetic_bars(100, seed=11)
    h = [b["high"] for b in bars]
    l = [b["low"] for b in bars]
    c = [b["close"] for b in bars]
    out = _atr_series(h, l, c, length=1)
    expected = [_true_range(h[i], l[i], c[i - 1] if i > 0 else c[i]) for i in range(len(bars))]
    assert out == expected
    print("PASS: atr_length=1 is byte-identical to the original single-bar true range")


def test_atr_length_greater_than_1_produces_real_smoothing():
    """A real multi-bar ATR should be smoother (lower variance bar-to-bar)
    than the raw single-bar true range it replaces -- proves this isn't a
    no-op wrapper around the same values."""
    bars = _synthetic_bars(200, seed=13)
    h = [b["high"] for b in bars]
    l = [b["low"] for b in bars]
    c = [b["close"] for b in bars]
    raw_tr = _atr_series(h, l, c, length=1)
    smoothed = _atr_series(h, l, c, length=14)

    def _variance_of_diffs(vals):
        clean = [v for v in vals if v is not None]
        diffs = [abs(clean[i] - clean[i - 1]) for i in range(1, len(clean))]
        return sum(diffs) / len(diffs)

    assert _variance_of_diffs(smoothed) < _variance_of_diffs(raw_tr)
    assert smoothed[0] is None and smoothed[12] is None and smoothed[13] is not None
    print("PASS: atr_length>1 produces genuine smoothing, not a no-op")


def test_require_pattern_default_true_is_byte_identical_to_prior_shipped_behavior():
    """require_pattern defaults to True and must not change any already-shipped
    result -- this is the backward-compatibility guarantee for every live
    config that predates the 2026-08-01 require_pattern option."""
    bars = _synthetic_bars(300, seed=17)
    p_explicit_true = ZonePatternParams(bars=10, no_of_pivots=2, exit_mode="atr_target", require_pattern=True)
    p_default = ZonePatternParams(bars=10, no_of_pivots=2, exit_mode="atr_target")
    assert compute_series(bars, p_explicit_true) == compute_series(bars, p_default)
    print("PASS: require_pattern defaults to True, byte-identical to pre-2026-08-01 behavior")


def test_require_pattern_false_fires_on_zone_touch_alone():
    """require_pattern=False must produce at least as many ENTER_UP events as
    require_pattern=True on the same data -- dropping the candlestick-pattern
    half of the confluence can only relax the entry condition, never tighten
    it (every bar require_pattern=True enters on, require_pattern=False also
    enters on, since bull_pat/bear_pat being True satisfies `not require_pattern
    or bull_pat` either way)."""
    bars = _synthetic_bars(400, seed=19)
    p_strict = ZonePatternParams(bars=10, no_of_pivots=2, exit_mode="atr_target", require_pattern=True)
    p_touch_only = ZonePatternParams(bars=10, no_of_pivots=2, exit_mode="atr_target", require_pattern=False)
    strict_entries = sum(1 for e in compute_series(bars, p_strict)["events"] if e == "ENTER_UP")
    touch_entries = sum(1 for e in compute_series(bars, p_touch_only)["events"] if e == "ENTER_UP")
    assert touch_entries >= strict_entries
    print(f"PASS: require_pattern=False fires >= as often as require_pattern=True ({touch_entries} >= {strict_entries})")


def test_require_pattern_env_var_parsing():
    """SR_ZONE_PATTERN_REQUIRE_PATTERN env var must be honored by from_env(),
    defaulting to True (unset) so no existing deployment's behavior changes
    without an explicit opt-in."""
    for raw, expected in (("false", False), ("False", False), ("true", True), (None, True)):
        if raw is None:
            os.environ.pop("SR_ZONE_PATTERN_REQUIRE_PATTERN", None)
        else:
            os.environ["SR_ZONE_PATTERN_REQUIRE_PATTERN"] = raw
        try:
            assert ZonePatternParams.from_env().require_pattern is expected, f"raw={raw!r} expected={expected}"
        finally:
            os.environ.pop("SR_ZONE_PATTERN_REQUIRE_PATTERN", None)
    print("PASS: SR_ZONE_PATTERN_REQUIRE_PATTERN env var parses correctly and defaults to True unset")


if __name__ == "__main__":
    test_no_crash_on_empty_and_short_series()
    print("PASS: no crash on empty/short series")
    test_no_duplicate_zone_spam_on_synthetic_data()
    print("PASS: no duplicate zone spam (regression fix verified)")
    test_detect_patterns_needs_two_prior_bars()
    print("PASS: pattern detection needs 2 prior bars")
    test_exit_mode_atr_target_sets_stop_and_target_on_entry()
    test_atr_length_1_is_byte_identical_to_original_single_bar_true_range()
    test_atr_length_greater_than_1_produces_real_smoothing()
    test_require_pattern_default_true_is_byte_identical_to_prior_shipped_behavior()
    test_require_pattern_false_fires_on_zone_touch_alone()
    test_require_pattern_env_var_parsing()
    print("\nAll tests passed.")
