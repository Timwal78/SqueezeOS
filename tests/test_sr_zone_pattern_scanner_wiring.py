"""
Tests for the SML S/R Zone + Candlestick Pattern live-execution wiring:
sr_zone_pattern_scanner.py's dedup/dispatch logic and blueprint registration
-- the pieces that make this engine actually reachable from a live scan
pass, not just a backtest harness. Same convention as
tests/test_breakout_scanner_wiring.py / tests/test_sr_matrix_scanner_wiring.py.

Not a profitability claim -- see docs/SR_ZONE_PATTERN_BACKTEST_2026-07-30.md
for the honest (thin, mixed) backtest evidence. This proves the wiring is
correct and reaches the real executor.
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
    import sr_zone_pattern_scanner

    bars = _bars_with_last_close()
    fixed_out = {
        "events": [None] * (len(bars) - 1) + ["ENTER_UP"],
        "live_signal": [None] * (len(bars) - 1) + ["BUY"],
        "pnl_pct": [None] * (len(bars) - 1) + [0.0],
    }

    dm = MagicMock()
    dm.get_bars.return_value = bars

    with patch("core.legacy.get_service", return_value=dm), \
         patch("sr_zone_pattern_engine.compute_series", return_value=fixed_out), \
         patch("sr_zone_pattern_scanner._symbols", return_value=["SPY"]), \
         patch("iam_executor.execute_async") as mock_exec:
        sr_zone_pattern_scanner._last_fired.clear()
        fired_1 = sr_zone_pattern_scanner.scan_once()
        fired_2 = sr_zone_pattern_scanner.scan_once()

    assert fired_1 == 1, "first pass with a real BUY signal must fire exactly once"
    assert fired_2 == 0, "second pass on the SAME bar/action must be deduped, not re-fired"
    assert mock_exec.call_count == 1
    call_args = mock_exec.call_args
    assert call_args[0][0] == "SPY"
    assert call_args[0][1]["system"] == "SML_SR_ZONE_PATTERN"
    assert call_args[0][1]["action"] == "BUY"
    print("PASS: scanner dedups repeat passes and tags the resolution system=SML_SR_ZONE_PATTERN correctly")


def test_no_fire_on_no_signal():
    import sr_zone_pattern_scanner

    bars = _bars_with_last_close()
    fixed_out = {
        "events": [None] * len(bars),
        "live_signal": [None] * len(bars),
        "pnl_pct": [None] * len(bars),
    }

    dm = MagicMock()
    dm.get_bars.return_value = bars

    with patch("core.legacy.get_service", return_value=dm), \
         patch("sr_zone_pattern_engine.compute_series", return_value=fixed_out), \
         patch("sr_zone_pattern_scanner._symbols", return_value=["SPY"]), \
         patch("iam_executor.execute_async") as mock_exec:
        sr_zone_pattern_scanner._last_fired.clear()
        fired = sr_zone_pattern_scanner.scan_once()

    assert fired == 0
    assert mock_exec.call_count == 0
    print("PASS: no signal -> no executor call")


def test_no_fire_on_insufficient_bars():
    import sr_zone_pattern_scanner

    dm = MagicMock()
    dm.get_bars.return_value = [{"open": 1, "high": 1, "low": 1, "close": 1}]

    with patch("core.legacy.get_service", return_value=dm), \
         patch("sr_zone_pattern_scanner._symbols", return_value=["SPY"]), \
         patch("iam_executor.execute_async") as mock_exec:
        fired = sr_zone_pattern_scanner.scan_once()

    assert fired == 0
    assert mock_exec.call_count == 0
    print("PASS: insufficient bars -> no executor call")


def test_no_fire_when_no_universe():
    import sr_zone_pattern_scanner

    with patch("sr_zone_pattern_scanner._symbols", return_value=[]), \
         patch("iam_executor.execute_async") as mock_exec:
        fired = sr_zone_pattern_scanner.scan_once()

    assert fired == 0
    assert mock_exec.call_count == 0
    print("PASS: empty universe -> no executor call")


def test_blueprint_registered():
    from core.api.sr_zone_pattern_bp import sr_zone_pattern_bp
    assert sr_zone_pattern_bp.name == "sr_zone_pattern"
    print("PASS: blueprint registered")


if __name__ == "__main__":
    test_scanner_dedup_prevents_double_firing_the_same_bar_and_action()
    test_no_fire_on_no_signal()
    test_no_fire_on_insufficient_bars()
    test_no_fire_when_no_universe()
    test_blueprint_registered()
    print("ALL PASS")
