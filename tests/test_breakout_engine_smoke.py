"""
Smoke test for breakout_engine.py — code-correctness only, NOT a performance
claim. Confirms compute_series()/analyze() run without crashing, produce the
documented output shapes, and that the entry/exit state machine matches the
Pine script (indicators/SML_Breakout_Target_Stop_v6.pine) and
docs/BREAKOUT_BACKTEST_2026-07-25.md: one position at a time, entry at the
breakout bar's close, target/stop measured off that entry price.

The real profitability evidence is docs/BREAKOUT_BACKTEST_2026-07-25.md (real
data via Robinhood MCP, real detect_breakout() from mnemos). This file uses
synthetic-but-deterministic bars ONLY to exercise the state machine
mechanically — never presented as a backtest result.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from breakout_engine import compute_series, analyze, BreakoutParams  # noqa: E402


def _flat_then_breakout_up(lookback=20, flat_price=100.0, breakout_close=115.0):
    """`lookback` flat bars (tight range around flat_price) followed by one
    bar closing well above the flat range's high — an unambiguous breakout."""
    bars = []
    for i in range(lookback):
        bars.append({"date": f"2026-01-{i+1:02d}", "open": flat_price - 0.5,
                     "high": flat_price + 0.5, "low": flat_price - 0.5, "close": flat_price})
    bars.append({"date": "2026-02-01", "open": flat_price, "high": breakout_close + 0.5,
                 "low": flat_price, "close": breakout_close})
    return bars


def test_compute_series_shapes_and_insufficient_data():
    p = BreakoutParams(lookback=20)
    bars = _flat_then_breakout_up(lookback=20)
    out = compute_series(bars, p)
    for key in ("events", "live_signal", "state_dir", "pnl_pct", "in_pos", "direction", "entry_price"):
        assert key in out, f"missing key: {key}"
    assert len(out["events"]) == len(bars)
    assert len(out["live_signal"]) == len(bars)
    assert all(s in (None, "BUY", "SELL") for s in out["live_signal"])
    print("PASS: compute_series returns the documented shape")


def test_up_breakout_fires_enter_up_and_buy_signal():
    p = BreakoutParams(lookback=20)
    bars = _flat_then_breakout_up(lookback=20, flat_price=100.0, breakout_close=115.0)
    out = compute_series(bars, p)
    last = len(bars) - 1
    assert out["events"][last] == "ENTER_UP", out["events"]
    assert out["live_signal"][last] == "BUY", out["live_signal"]
    assert out["in_pos"] is True
    assert out["direction"] == "up"
    assert out["entry_price"] == 115.0
    print("PASS: unambiguous up-breakout fires ENTER_UP -> live BUY signal")


def test_down_breakout_fires_enter_down_and_sell_signal():
    p = BreakoutParams(lookback=20)
    bars = _flat_then_breakout_up(lookback=20, flat_price=100.0, breakout_close=85.0)
    out = compute_series(bars, p)
    last = len(bars) - 1
    assert out["events"][last] == "ENTER_DOWN", out["events"]
    assert out["live_signal"][last] == "SELL", out["live_signal"]
    assert out["direction"] == "down"
    print("PASS: unambiguous down-breakout fires ENTER_DOWN -> live SELL signal (bear resolution)")


def test_target_hit_closes_up_position_and_emits_sell():
    p = BreakoutParams(lookback=20, target_pct=0.10, stop_pct=0.05)
    bars = _flat_then_breakout_up(lookback=20, flat_price=100.0, breakout_close=110.0)
    # Next bar closes well past the +10% target (110 * 1.10 = 121)
    bars.append({"date": "2026-02-02", "open": 122.0, "high": 123.0, "low": 121.5, "close": 122.0})
    out = compute_series(bars, p)
    last = len(bars) - 1
    assert out["events"][last] == "EXIT_TARGET", out["events"]
    assert out["live_signal"][last] == "SELL", (
        "an UP position's target exit MUST map to a live SELL (closes the long) "
        f"-- got {out['live_signal'][last]}"
    )
    assert out["in_pos"] is False
    print("PASS: target hit on an UP position closes it and emits a live SELL")


def test_stop_hit_closes_up_position_and_emits_sell():
    p = BreakoutParams(lookback=20, target_pct=0.10, stop_pct=0.05)
    bars = _flat_then_breakout_up(lookback=20, flat_price=100.0, breakout_close=110.0)
    # Next bar closes well past the -5% stop (110 * 0.95 = 104.5)
    bars.append({"date": "2026-02-02", "open": 103.0, "high": 103.5, "low": 102.0, "close": 103.0})
    out = compute_series(bars, p)
    last = len(bars) - 1
    assert out["events"][last] == "EXIT_STOP", out["events"]
    assert out["live_signal"][last] == "SELL"
    assert out["in_pos"] is False
    print("PASS: stop hit on an UP position closes it and emits a live SELL")


def test_down_position_exit_emits_no_live_signal_by_design():
    """See breakout_engine.py's module docstring: EXIT events on a DOWN
    (put) position are tracked for backtest/display parity but deliberately
    do NOT map to a live signal -- there is no clean 'close a put' action in
    iam_executor's BUY/SELL vocabulary, same gap every other engine here has."""
    p = BreakoutParams(lookback=20, target_pct=0.10, stop_pct=0.05)
    bars = _flat_then_breakout_up(lookback=20, flat_price=100.0, breakout_close=90.0)
    # Next bar closes well past the down position's -10% target (90 * 0.90 = 81)
    bars.append({"date": "2026-02-02", "open": 80.0, "high": 80.5, "low": 79.0, "close": 80.0})
    out = compute_series(bars, p)
    last = len(bars) - 1
    assert out["events"][last] == "EXIT_TARGET", out["events"]
    assert out["live_signal"][last] is None, (
        f"a DOWN position's exit must NOT emit a live signal -- got {out['live_signal'][last]}"
    )
    print("PASS: DOWN position exit tracked for display but correctly emits no live signal")


def test_analyze_insufficient_data_reports_honestly():
    result = analyze("SPY", [])
    assert result["status"] == "insufficient_data"
    assert result["symbol"] == "SPY"
    print(f"PASS: analyze() with no bars reports insufficient_data honestly — {result}")


def test_analyze_end_to_end_shape():
    bars = _flat_then_breakout_up(lookback=20, flat_price=100.0, breakout_close=115.0)
    result = analyze("SPY", bars)
    assert result["status"] == "success", result
    assert result["signal"] == "BUY"
    assert result["position"]["in_position"] is True
    assert result["position"]["entry_price"] == 115.0
    assert result["position"]["target_price"] == round(115.0 * 1.10, 4)
    assert result["position"]["stop_price"] == round(115.0 * 0.95, 4)
    print(f"PASS: analyze() end-to-end shape correct — signal={result['signal']}, "
          f"target={result['position']['target_price']}, stop={result['position']['stop_price']}")


if __name__ == "__main__":
    test_compute_series_shapes_and_insufficient_data()
    test_up_breakout_fires_enter_up_and_buy_signal()
    test_down_breakout_fires_enter_down_and_sell_signal()
    test_target_hit_closes_up_position_and_emits_sell()
    test_stop_hit_closes_up_position_and_emits_sell()
    test_down_position_exit_emits_no_live_signal_by_design()
    test_analyze_insufficient_data_reports_honestly()
    test_analyze_end_to_end_shape()
    print("\nAll smoke tests passed (code correctness only — not a profitability claim).")
