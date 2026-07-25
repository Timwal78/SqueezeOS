"""
Tests for the SML Breakout live-execution wiring: breakout_scanner.py's
dedup/dispatch logic and blueprint registration -- the pieces that make the
breakout strategy actually reachable from a live scan pass, not just a
backtest harness. Same convention as tests/test_druck_scanner_wiring.py.

Not a profitability claim -- that's docs/BREAKOUT_BACKTEST_2026-07-25.md
(real data, real detect_breakout()). This proves the wiring is correct and
reaches the real executor.
"""
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _bars_with_last_close(n=25, close=115.0):
    bars = []
    for i in range(n - 1):
        bars.append({"date": f"2026-01-{i+1:02d}", "open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0})
    bars.append({"date": "2026-02-01", "open": 114.0, "high": close + 1, "low": 114.0, "close": close})
    return bars


def test_scanner_dedup_prevents_double_firing_the_same_bar_and_action():
    """breakout_scanner.scan_once()'s per-bar dedup key must not re-fire the
    executor for the same (symbol, bar, action) across consecutive passes --
    same convention as orb_scanner.py/druck_scanner.py's _last_fired guard."""
    import breakout_scanner

    bars = _bars_with_last_close()
    fixed_out = {
        "events": [None] * (len(bars) - 1) + ["ENTER_UP"],
        "live_signal": [None] * (len(bars) - 1) + ["BUY"],
        "state_dir": [None] * (len(bars) - 1) + ["up"],
        "pnl_pct": [None] * (len(bars) - 1) + [0.0],
        "in_pos": True, "direction": "up", "entry_price": bars[-1]["close"],
    }

    dm = MagicMock()
    dm.get_bars.return_value = bars

    with patch("core.legacy.get_service", return_value=dm), \
         patch("breakout_engine.compute_series", return_value=fixed_out), \
         patch("breakout_scanner._symbols", return_value=["SPY"]), \
         patch("iam_executor.execute_async") as mock_exec:
        breakout_scanner._last_fired.clear()
        fired_1 = breakout_scanner.scan_once()
        fired_2 = breakout_scanner.scan_once()

    assert fired_1 == 1, "first pass with a real BUY signal must fire exactly once"
    assert fired_2 == 0, "second pass on the SAME bar/action must be deduped, not re-fired"
    assert mock_exec.call_count == 1, "executor must only be called once across both passes"
    call_args = mock_exec.call_args
    assert call_args[0][0] == "SPY"
    assert call_args[0][1]["system"] == "SML_BREAKOUT"
    assert call_args[0][1]["action"] == "BUY"
    print("PASS: scanner dedups repeat passes and tags the resolution system=SML_BREAKOUT correctly")


def test_scanner_skips_honestly_when_no_daily_data():
    """No fabricated bars, no fabricated signal, when the data provider has nothing."""
    import breakout_scanner

    dm = MagicMock()
    dm.get_bars.return_value = []

    with patch("core.legacy.get_service", return_value=dm), \
         patch("breakout_scanner._symbols", return_value=["SPY"]), \
         patch("iam_executor.execute_async") as mock_exec:
        breakout_scanner._last_fired.clear()
        fired = breakout_scanner.scan_once()

    assert fired == 0
    assert mock_exec.call_count == 0
    print("PASS: scanner honestly skips symbols with no real daily bars, never fabricates a signal")


def test_scanner_does_not_fire_on_none_signal():
    """A flat/no-signal bar must never reach the executor."""
    import breakout_scanner

    bars = _bars_with_last_close(close=100.2)  # inside the flat range, no breakout
    fixed_out = {
        "events": [None] * len(bars),
        "live_signal": [None] * len(bars),
        "state_dir": [None] * len(bars),
        "pnl_pct": [None] * len(bars),
        "in_pos": False, "direction": None, "entry_price": None,
    }

    dm = MagicMock()
    dm.get_bars.return_value = bars

    with patch("core.legacy.get_service", return_value=dm), \
         patch("breakout_engine.compute_series", return_value=fixed_out), \
         patch("breakout_scanner._symbols", return_value=["SPY"]), \
         patch("iam_executor.execute_async") as mock_exec:
        breakout_scanner._last_fired.clear()
        fired = breakout_scanner.scan_once()

    assert fired == 0
    assert mock_exec.call_count == 0
    print("PASS: scanner does not fire the executor on a None (no-signal) bar")


def test_blueprint_registers_at_expected_routes():
    from core.app import create_app
    app = create_app()
    rules = {r.rule for r in app.url_map.iter_rules() if "breakout" in r.rule}
    assert "/api/breakout/status" in rules, rules
    assert "/api/breakout/<symbol>" in rules, rules
    print(f"PASS: /api/breakout blueprint registered — {rules}")


if __name__ == "__main__":
    test_scanner_dedup_prevents_double_firing_the_same_bar_and_action()
    test_scanner_skips_honestly_when_no_daily_data()
    test_scanner_does_not_fire_on_none_signal()
    test_blueprint_registers_at_expected_routes()
    print("\nAll regression tests passed.")
