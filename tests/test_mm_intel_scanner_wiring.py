"""
Tests for the SML Market Maker Intelligence v4 live-execution wiring:
mm_intel_scanner.py's live-signal mapping, dedup/dispatch logic, and
blueprint registration -- the pieces that make the engine actually
reachable from a live scan pass. Same convention as
tests/test_druck_scanner_wiring.py/tests/test_breakout_scanner_wiring.py.

Not a profitability claim -- that's docs/MM_INTEL_BACKTEST_2026-07-25.md
(real data, 81-92 trades/symbol, PF>1.0 on 4/5). This proves the wiring is
correct and reaches the real executor with the correct action mapping.
"""
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _dummy_bars(n=300):
    return [{"date": f"2026-01-{(i % 28) + 1:02d}", "open": 100.0, "high": 100.5,
              "low": 99.5, "close": 100.0, "volume": 1_000_000} for i in range(n)]


def _fake_result(signal, exit_direction=None, inv_z=-2.5, gamma_pressure=0.9, confidence=75.0):
    return {
        "symbol": "SPY", "status": "success", "price": 100.0,
        "inv_z": inv_z, "gamma_pressure": gamma_pressure, "gamma_critical": True,
        "control_action": True, "signal": signal, "confidence": confidence,
        "nearest_strike": 100.0, "active_direction": 0 if signal and signal.startswith("EXIT") else 1,
        "active_invalidation": 98.0, "exit_direction": exit_direction,
        "params": {"z_critical": 2.0, "gamma_thresh": 0.5, "sensitivity": "Normal"},
    }


def test_buy_signal_passes_through_to_executor():
    import mm_intel_scanner

    dm = MagicMock()
    dm.get_bars.return_value = _dummy_bars()

    with patch("core.legacy.get_service", return_value=dm), \
         patch("mm_intel_engine.analyze", return_value=_fake_result("BUY")), \
         patch("mm_intel_scanner._symbols", return_value=["SPY"]), \
         patch("iam_executor.execute_async") as mock_exec:
        mm_intel_scanner._last_fired.clear()
        fired = mm_intel_scanner.scan_once()

    assert fired == 1
    assert mock_exec.call_count == 1
    call_args = mock_exec.call_args
    assert call_args[0][0] == "SPY"
    assert call_args[0][1]["system"] == "SML_MM_INTEL"
    assert call_args[0][1]["action"] == "BUY"
    print("PASS: BUY passes through to the executor tagged system=SML_MM_INTEL")


def test_sell_signal_passes_through_to_executor():
    import mm_intel_scanner

    dm = MagicMock()
    dm.get_bars.return_value = _dummy_bars()

    with patch("core.legacy.get_service", return_value=dm), \
         patch("mm_intel_engine.analyze", return_value=_fake_result("SELL")), \
         patch("mm_intel_scanner._symbols", return_value=["SPY"]), \
         patch("iam_executor.execute_async") as mock_exec:
        mm_intel_scanner._last_fired.clear()
        fired = mm_intel_scanner.scan_once()

    assert fired == 1
    assert mock_exec.call_args[0][1]["action"] == "SELL"
    print("PASS: SELL passes through to the executor")


def test_exit_on_long_maps_to_sell():
    """Closing a LONG thesis must map to SELL (closes the long), matching
    every other engine's 'exits never blocked' convention."""
    import mm_intel_scanner

    dm = MagicMock()
    dm.get_bars.return_value = _dummy_bars()

    with patch("core.legacy.get_service", return_value=dm), \
         patch("mm_intel_engine.analyze", return_value=_fake_result("EXIT_RESOLVED", exit_direction=1)), \
         patch("mm_intel_scanner._symbols", return_value=["SPY"]), \
         patch("iam_executor.execute_async") as mock_exec:
        mm_intel_scanner._last_fired.clear()
        fired = mm_intel_scanner.scan_once()

    assert fired == 1
    assert mock_exec.call_args[0][1]["action"] == "SELL"
    print("PASS: EXIT_RESOLVED closing a long maps to SELL")


def test_exit_on_short_emits_no_signal():
    """Closing a SHORT/put thesis must emit NOTHING -- iam_executor has no
    'close an existing put' mechanism (same gap breakout_engine.py
    documents), so inventing one here would add an un-backtested action."""
    import mm_intel_scanner

    dm = MagicMock()
    dm.get_bars.return_value = _dummy_bars()

    with patch("core.legacy.get_service", return_value=dm), \
         patch("mm_intel_engine.analyze", return_value=_fake_result("EXIT_STOP", exit_direction=-1)), \
         patch("mm_intel_scanner._symbols", return_value=["SPY"]), \
         patch("iam_executor.execute_async") as mock_exec:
        mm_intel_scanner._last_fired.clear()
        fired = mm_intel_scanner.scan_once()

    assert fired == 0
    assert mock_exec.call_count == 0
    print("PASS: EXIT_STOP closing a short emits no live signal")


def test_scanner_dedup_prevents_double_firing_the_same_bar_and_signal():
    import mm_intel_scanner

    dm = MagicMock()
    dm.get_bars.return_value = _dummy_bars()

    with patch("core.legacy.get_service", return_value=dm), \
         patch("mm_intel_engine.analyze", return_value=_fake_result("BUY")), \
         patch("mm_intel_scanner._symbols", return_value=["SPY"]), \
         patch("iam_executor.execute_async") as mock_exec:
        mm_intel_scanner._last_fired.clear()
        fired_1 = mm_intel_scanner.scan_once()
        fired_2 = mm_intel_scanner.scan_once()

    assert fired_1 == 1, "first pass with a real BUY signal must fire exactly once"
    assert fired_2 == 0, "second pass on the SAME bar/signal must be deduped"
    assert mock_exec.call_count == 1
    print("PASS: scanner dedups repeat passes on the same bar/signal")


def test_scanner_skips_honestly_when_no_intraday_data():
    import mm_intel_scanner

    dm = MagicMock()
    dm.get_bars.return_value = []

    with patch("core.legacy.get_service", return_value=dm), \
         patch("mm_intel_scanner._symbols", return_value=["SPY"]), \
         patch("iam_executor.execute_async") as mock_exec:
        mm_intel_scanner._last_fired.clear()
        fired = mm_intel_scanner.scan_once()

    assert fired == 0
    assert mock_exec.call_count == 0
    print("PASS: scanner honestly skips symbols with no real intraday bars, never fabricates a signal")


def test_scanner_does_not_fire_on_none_signal():
    import mm_intel_scanner

    dm = MagicMock()
    dm.get_bars.return_value = _dummy_bars()

    with patch("core.legacy.get_service", return_value=dm), \
         patch("mm_intel_engine.analyze", return_value=_fake_result(None)), \
         patch("mm_intel_scanner._symbols", return_value=["SPY"]), \
         patch("iam_executor.execute_async") as mock_exec:
        mm_intel_scanner._last_fired.clear()
        fired = mm_intel_scanner.scan_once()

    assert fired == 0
    assert mock_exec.call_count == 0
    print("PASS: scanner does not fire the executor on a None (no-signal) bar")


def test_blueprint_registers_at_expected_routes():
    from core.app import create_app
    app = create_app()
    rules = {r.rule for r in app.url_map.iter_rules() if "mm-intel" in r.rule}
    assert "/api/mm-intel/status" in rules, rules
    assert "/api/mm-intel/<symbol>" in rules, rules
    print(f"PASS: /api/mm-intel blueprint registered — {rules}")


if __name__ == "__main__":
    test_buy_signal_passes_through_to_executor()
    test_sell_signal_passes_through_to_executor()
    test_exit_on_long_maps_to_sell()
    test_exit_on_short_emits_no_signal()
    test_scanner_dedup_prevents_double_firing_the_same_bar_and_signal()
    test_scanner_skips_honestly_when_no_intraday_data()
    test_scanner_does_not_fire_on_none_signal()
    test_blueprint_registers_at_expected_routes()
    print("\nAll regression tests passed.")
