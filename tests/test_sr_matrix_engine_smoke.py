"""
Smoke test for sr_matrix_engine.py — code-correctness only, NOT a
performance claim. Confirms compute_series()/analyze() run without
crashing, produce the documented shapes, and that the pivot-confirmation
timing matches Pine's ta.pivothigh(Bars,Bars)/ta.pivotlow(Bars,Bars)
semantics: a pivot at bar i is only confirmed (and therefore live-tradeable)
at bar i+Bars, never earlier (no lookahead).

The real profitability evidence is docs/SR_MATRIX_PIVOT_BACKTEST_2026-07-25.md
(real data, 22-30 trades/symbol, positive PF on 3/4). This file uses a
synthetic-but-deterministic bar series only to exercise the pivot mechanics.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sr_matrix_engine import compute_series, analyze, SrMatrixParams  # noqa: E402


def _v_shape_bars(bars_count=25, flat_price=100.0, dip_at=12, dip_low=90.0):
    """A clean V-shape: flat, one clear low at `dip_at`, flat again — an
    unambiguous single pivot low with nothing else confounding it."""
    bars = []
    for i in range(bars_count):
        if i == dip_at:
            low = dip_low
            high = flat_price
        else:
            low = flat_price - 0.5
            high = flat_price + 0.5
        bars.append({"date": f"2026-01-{i+1:02d}", "open": flat_price, "high": high,
                     "low": low, "close": flat_price})
    return bars


def _peak_shape_bars(bars_count=25, flat_price=100.0, peak_at=12, peak_high=110.0):
    bars = []
    for i in range(bars_count):
        if i == peak_at:
            high = peak_high
            low = flat_price
        else:
            low = flat_price - 0.5
            high = flat_price + 0.5
        bars.append({"date": f"2026-01-{i+1:02d}", "open": flat_price, "high": high,
                     "low": low, "close": flat_price})
    return bars


def test_compute_series_shapes():
    p = SrMatrixParams(bars=5)
    bars = _v_shape_bars(bars_count=25, dip_at=12)
    out = compute_series(bars, p)
    for key in ("pivot_high", "pivot_low", "confirmed_high", "confirmed_low", "live_signal"):
        assert key in out, f"missing key: {key}"
    assert len(out["live_signal"]) == len(bars)
    assert all(s in (None, "BUY", "SELL") for s in out["live_signal"])
    print("PASS: compute_series returns the documented shape")


def test_pivot_low_confirms_exactly_bars_bars_later_and_fires_buy():
    p = SrMatrixParams(bars=5)
    dip_at = 12
    bars = _v_shape_bars(bars_count=25, dip_at=dip_at)
    out = compute_series(bars, p)

    confirm_idx = dip_at + p.bars
    assert out["pivot_low"][dip_at] is not None, "the dip bar itself must be detected as a pivot low"
    assert out["confirmed_low"][confirm_idx] is True
    assert out["live_signal"][confirm_idx] == "BUY"
    # No lookahead: nothing before confirm_idx should already show it confirmed
    assert all(not c for c in out["confirmed_low"][:confirm_idx])
    print(f"PASS: pivot low at bar {dip_at} confirms at bar {confirm_idx} (dip_at+bars) and fires BUY, never earlier")


def test_pivot_high_confirms_exactly_bars_bars_later_and_fires_sell():
    p = SrMatrixParams(bars=5)
    peak_at = 12
    bars = _peak_shape_bars(bars_count=25, peak_at=peak_at)
    out = compute_series(bars, p)

    confirm_idx = peak_at + p.bars
    assert out["pivot_high"][peak_at] is not None
    assert out["confirmed_high"][confirm_idx] is True
    assert out["live_signal"][confirm_idx] == "SELL"
    assert all(not c for c in out["confirmed_high"][:confirm_idx])
    print(f"PASS: pivot high at bar {peak_at} confirms at bar {confirm_idx} and fires SELL, never earlier")


def test_flat_series_produces_no_signals():
    p = SrMatrixParams(bars=5)
    bars = [{"date": f"2026-01-{i+1:02d}", "open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0}
            for i in range(30)]
    out = compute_series(bars, p)
    assert all(s is None for s in out["live_signal"]), "a perfectly flat series must never fire a pivot signal"
    print("PASS: flat series produces no false pivot signals")


def test_analyze_insufficient_data_reports_honestly():
    result = analyze("SPY", [])
    assert result["status"] == "insufficient_data"
    assert result["symbol"] == "SPY"
    print(f"PASS: analyze() with no bars reports insufficient_data honestly — {result}")


def test_analyze_end_to_end_shape():
    p = SrMatrixParams(bars=5)
    bars = _v_shape_bars(bars_count=25, dip_at=12)
    result = analyze("SPY", bars, p)
    assert result["status"] == "success", result
    assert result["signal"] in (None, "BUY", "SELL")
    assert "pivot_high_confirmed" in result and "pivot_low_confirmed" in result
    print(f"PASS: analyze() end-to-end shape correct — signal={result['signal']}")


if __name__ == "__main__":
    test_compute_series_shapes()
    test_pivot_low_confirms_exactly_bars_bars_later_and_fires_buy()
    test_pivot_high_confirms_exactly_bars_bars_later_and_fires_sell()
    test_flat_series_produces_no_signals()
    test_analyze_insufficient_data_reports_honestly()
    test_analyze_end_to_end_shape()
    print("\nAll smoke tests passed (code correctness only — not a profitability claim).")
