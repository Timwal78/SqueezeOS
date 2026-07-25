"""
Tests for mm_intel_engine.py -- the Python port of
indicators/SML_Market_Maker_Intelligence_v4.pine. Verifies the Kalman
filter/HJB/gamma-pressure math runs cleanly on real-shaped OHLCV, the
strike-increment grid matches the Pine script's exact tiers (both crypto
and equity branches), and the invalidation-state-machine fix actually
persists a thesis across bars (the bug it corrects: same-bar self-resolve).

Not a profitability claim -- that's docs/MM_INTEL_BACKTEST_2026-07-25.md.
This proves the math runs correctly and the discovered bug is really fixed.
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mm_intel_engine import MMIntelParams, compute_series, analyze, _strike_increment


def _synthetic_bars(n=250, start=100.0, seed=7):
    """Deterministic pseudo-random walk (no external randomness) with real
    OHLCV shape -- enough variation to exercise the Kalman filter and
    gamma-pressure sections without needing live data for a smoke test."""
    bars = []
    price = start
    state = seed
    for i in range(n):
        state = (1103515245 * state + 12345) & 0x7FFFFFFF
        r = (state / 0x7FFFFFFF) - 0.5  # -0.5..0.5
        drift = r * start * 0.01
        o = price
        c = max(0.01, price + drift)
        h = max(o, c) + abs(r) * start * 0.003
        l = min(o, c) - abs(r) * start * 0.003
        v = 1_000_000 * (1.0 + abs(r))
        bars.append({"date": f"2026-01-{(i % 28) + 1:02d}", "open": o, "high": h, "low": l, "close": c, "volume": v})
        price = c
    return bars


def test_compute_series_runs_clean_no_nan_or_inf():
    bars = _synthetic_bars(250)
    out = compute_series(bars)
    for key in ("inv_z", "total_gamma_pressure", "signal_confidence", "tactical_target", "structural_target"):
        for v in out[key]:
            assert v is not None
            assert not (isinstance(v, float) and (math.isnan(v) or math.isinf(v)))
    print("PASS: compute_series() produces no NaN/Inf across all real-valued series")


def test_inv_z_is_zero_before_lookback_window_fills():
    p = MMIntelParams(inv_lookback=75)
    bars = _synthetic_bars(250)
    out = compute_series(bars, p)
    # Before 75 bars of inventory_estimate history exist, stdev is None and
    # inv_z must fall back to 0.0 (matching Pine's `inv_std > 0 ? ... : 0.0`).
    assert out["inv_z"][10] == 0.0
    print("PASS: inv_z safely defaults to 0.0 before the lookback window fills")


def test_strike_increment_matches_pine_tiers_equity():
    assert _strike_increment(600.0, is_crypto=False) == 5.0
    assert _strike_increment(150.0, is_crypto=False) == 1.0
    assert _strike_increment(50.0, is_crypto=False) == 0.5
    assert _strike_increment(10.0, is_crypto=False) == 0.5
    print("PASS: equity strike_increment tiers match the Pine script exactly")


def test_strike_increment_matches_pine_tiers_crypto():
    assert _strike_increment(64000.0, is_crypto=True) == 500.0
    assert _strike_increment(5000.0, is_crypto=True) == 100.0
    assert _strike_increment(500.0, is_crypto=True) == 10.0
    assert _strike_increment(50.0, is_crypto=True) == 1.0
    assert _strike_increment(5.0, is_crypto=True) == 0.1
    assert _strike_increment(0.5, is_crypto=True) == 0.01
    print("PASS: crypto strike_increment tiers match the Pine script exactly")


def test_invalidation_persists_across_bars_after_fix():
    """The whole point of the discovered-bug fix: once a BUY/SELL fires,
    active_direction must stay non-zero on the bars immediately after entry
    (not instantly self-resolve on the same bar), giving the thesis a real
    chance to be stopped out or resolved on a LATER bar."""
    bars = _synthetic_bars(400, seed=42)
    out = compute_series(bars)
    entries = [i for i, s in enumerate(out["live_signal"]) if s in ("BUY", "SELL")]
    assert entries, "synthetic series should produce at least one entry to test the fix against"
    persisted = False
    for i in entries:
        if i + 1 < len(bars) and out["active_direction"][i + 1] != 0:
            persisted = True
            break
    assert persisted, "active_direction must persist past the entry bar at least once -- the same-bar self-resolve bug is not fixed"
    print(f"PASS: active_direction persists past the entry bar (checked {len(entries)} entries)")


def test_analyze_reports_insufficient_data_below_min_bars():
    result = analyze("SPY", _synthetic_bars(30))
    assert result["status"] == "insufficient_data"
    print("PASS: analyze() honestly reports insufficient_data below the minimum bar count")


def test_analyze_success_shape_on_enough_bars():
    result = analyze("SPY", _synthetic_bars(250))
    assert result["status"] == "success"
    for key in ("inv_z", "gamma_pressure", "signal", "confidence", "nearest_strike"):
        assert key in result
    print("PASS: analyze() returns the expected fields once enough bars are available")


if __name__ == "__main__":
    test_compute_series_runs_clean_no_nan_or_inf()
    test_inv_z_is_zero_before_lookback_window_fills()
    test_strike_increment_matches_pine_tiers_equity()
    test_strike_increment_matches_pine_tiers_crypto()
    test_invalidation_persists_across_bars_after_fix()
    test_analyze_reports_insufficient_data_below_min_bars()
    test_analyze_success_shape_on_enough_bars()
    print("\nAll regression tests passed.")
