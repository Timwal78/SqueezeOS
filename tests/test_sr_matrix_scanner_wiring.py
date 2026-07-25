"""
Tests for the SML Support/Resistance Matrix live-execution wiring:
sr_matrix_scanner.py's dedup/dispatch logic and blueprint registration --
the pieces that make the pivot strategy actually reachable from a live scan
pass, not just a backtest harness. Same convention as
tests/test_breakout_scanner_wiring.py.

Not a profitability claim -- that's docs/SR_MATRIX_PIVOT_BACKTEST_2026-07-25.md
(real data, 22-30 trades/symbol, positive PF on 3/4). This proves the wiring
is correct and reaches the real executor.
"""
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _dummy_bars(n=25):
    return [{"date": f"2026-01-{i+1:02d}", "open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0}
            for i in range(n)]


def test_scanner_dedup_prevents_double_firing_the_same_bar_and_action():
    """sr_matrix_scanner.scan_once()'s per-bar dedup key must not re-fire the
    executor for the same (symbol, bar, action) across consecutive passes --
    same convention as orb_scanner.py/breakout_scanner.py's _last_fired guard."""
    import sr_matrix_scanner

    bars = _dummy_bars()
    fixed_out = {
        "pivot_high": [None] * len(bars),
        "pivot_low": [None] * (len(bars) - 1) + [95.0],
        "confirmed_high": [False] * len(bars),
        "confirmed_low": [False] * (len(bars) - 1) + [True],
        "live_signal": [None] * (len(bars) - 1) + ["BUY"],
    }

    dm = MagicMock()
    dm.get_bars.return_value = bars

    with patch("core.legacy.get_service", return_value=dm), \
         patch("sr_matrix_engine.compute_series", return_value=fixed_out), \
         patch("sr_matrix_scanner._symbols", return_value=["SPY"]), \
         patch("iam_executor.execute_async") as mock_exec:
        sr_matrix_scanner._last_fired.clear()
        fired_1 = sr_matrix_scanner.scan_once()
        fired_2 = sr_matrix_scanner.scan_once()

    assert fired_1 == 1, "first pass with a real BUY signal must fire exactly once"
    assert fired_2 == 0, "second pass on the SAME bar/action must be deduped, not re-fired"
    assert mock_exec.call_count == 1, "executor must only be called once across both passes"
    call_args = mock_exec.call_args
    assert call_args[0][0] == "SPY"
    assert call_args[0][1]["system"] == "SML_SR_MATRIX"
    assert call_args[0][1]["action"] == "BUY"
    print("PASS: scanner dedups repeat passes and tags the resolution system=SML_SR_MATRIX correctly")


def test_scanner_skips_honestly_when_no_daily_data():
    """No fabricated bars, no fabricated signal, when the data provider has nothing."""
    import sr_matrix_scanner

    dm = MagicMock()
    dm.get_bars.return_value = []

    with patch("core.legacy.get_service", return_value=dm), \
         patch("sr_matrix_scanner._symbols", return_value=["SPY"]), \
         patch("iam_executor.execute_async") as mock_exec:
        sr_matrix_scanner._last_fired.clear()
        fired = sr_matrix_scanner.scan_once()

    assert fired == 0
    assert mock_exec.call_count == 0
    print("PASS: scanner honestly skips symbols with no real daily bars, never fabricates a signal")


def test_scanner_does_not_fire_on_none_signal():
    """A flat/no-pivot bar must never reach the executor."""
    import sr_matrix_scanner

    bars = _dummy_bars()
    fixed_out = {
        "pivot_high": [None] * len(bars), "pivot_low": [None] * len(bars),
        "confirmed_high": [False] * len(bars), "confirmed_low": [False] * len(bars),
        "live_signal": [None] * len(bars),
    }

    dm = MagicMock()
    dm.get_bars.return_value = bars

    with patch("core.legacy.get_service", return_value=dm), \
         patch("sr_matrix_engine.compute_series", return_value=fixed_out), \
         patch("sr_matrix_scanner._symbols", return_value=["SPY"]), \
         patch("iam_executor.execute_async") as mock_exec:
        sr_matrix_scanner._last_fired.clear()
        fired = sr_matrix_scanner.scan_once()

    assert fired == 0
    assert mock_exec.call_count == 0
    print("PASS: scanner does not fire the executor on a None (no-pivot) bar")


def test_blueprint_registers_at_expected_routes():
    from core.app import create_app
    app = create_app()
    rules = {r.rule for r in app.url_map.iter_rules() if "sr-matrix" in r.rule}
    assert "/api/sr-matrix/status" in rules, rules
    assert "/api/sr-matrix/<symbol>" in rules, rules
    print(f"PASS: /api/sr-matrix blueprint registered — {rules}")


if __name__ == "__main__":
    test_scanner_dedup_prevents_double_firing_the_same_bar_and_action()
    test_scanner_skips_honestly_when_no_daily_data()
    test_scanner_does_not_fire_on_none_signal()
    test_blueprint_registers_at_expected_routes()
    print("\nAll regression tests passed.")
