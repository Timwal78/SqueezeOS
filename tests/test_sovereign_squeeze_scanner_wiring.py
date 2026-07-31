"""
Tests for the SML Sovereign Squeeze Finder live-execution wiring:
sovereign_squeeze_scanner.py's dedup/dispatch logic and blueprint
registration — the pieces that make the setup actually reachable from a
live scan pass, not just a backtest harness. Same convention as
tests/test_sr_matrix_scanner_wiring.py/tests/test_breakout_scanner_wiring.py.

Not a profitability claim — see the dated backtest doc in CLAUDE.md for
that. This proves the wiring is correct and reaches the real executor.
"""
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _dummy_bars(n=25):
    return [{"date": f"2026-01-{i+1:02d}", "open": 100.0, "high": 100.5, "low": 99.5,
              "close": 100.0, "volume": 1000.0} for i in range(n)]


def _small_params():
    """Test-only params — the real default (macro_ema_len=200) needs 200+
    bars just to clear the min-bars check, which isn't the thing these
    dedup/dispatch tests exercise."""
    from sovereign_squeeze_engine import SovereignSqueezeParams
    return SovereignSqueezeParams(bb_length=10, kc_length=10, use_macro_ema=False, macro_ema_len=200)


def test_scanner_dedup_prevents_double_firing_the_same_bar_and_action():
    """sovereign_squeeze_scanner.scan_once()'s per-bar dedup key must not
    re-fire the executor for the same (symbol, bar, action) across
    consecutive passes — same convention as sr_matrix_scanner.py/
    breakout_scanner.py's _last_fired guard."""
    import sovereign_squeeze_scanner

    bars = _dummy_bars()
    fixed_out = {
        "events": [None] * (len(bars) - 1) + ["ENTER_CALL"],
        "live_signal": [None] * (len(bars) - 1) + ["BUY"],
        "score": [0] * (len(bars) - 1) + [85],
        "sqz_bar_count": [0] * len(bars),
    }

    dm = MagicMock()
    dm.get_bars.return_value = bars

    with patch("core.legacy.get_service", return_value=dm), \
         patch("sovereign_squeeze_engine.SovereignSqueezeParams.from_env", return_value=_small_params()), \
         patch("sovereign_squeeze_engine.compute_series", return_value=fixed_out), \
         patch("sovereign_squeeze_scanner._symbols", return_value=["SPY"]), \
         patch("iam_executor.execute_async") as mock_exec:
        sovereign_squeeze_scanner._last_fired.clear()
        fired_1 = sovereign_squeeze_scanner.scan_once()
        fired_2 = sovereign_squeeze_scanner.scan_once()

    assert fired_1 == 1, "first pass with a real BUY signal must fire exactly once"
    assert fired_2 == 0, "second pass on the SAME bar/action must be deduped, not re-fired"
    assert mock_exec.call_count == 1, "executor must only be called once across both passes"
    call_args = mock_exec.call_args
    assert call_args[0][0] == "SPY"
    assert call_args[0][1]["system"] == "SML_SOVEREIGN_SQUEEZE"
    assert call_args[0][1]["action"] == "BUY"
    print("PASS: scanner dedups repeat passes and tags the resolution system=SML_SOVEREIGN_SQUEEZE correctly")


def test_scanner_skips_honestly_when_no_daily_data():
    """No fabricated bars, no fabricated signal, when the data provider has nothing."""
    import sovereign_squeeze_scanner

    dm = MagicMock()
    dm.get_bars.return_value = []

    with patch("core.legacy.get_service", return_value=dm), \
         patch("sovereign_squeeze_scanner._symbols", return_value=["SPY"]), \
         patch("iam_executor.execute_async") as mock_exec:
        sovereign_squeeze_scanner._last_fired.clear()
        fired = sovereign_squeeze_scanner.scan_once()

    assert fired == 0
    assert mock_exec.call_count == 0
    print("PASS: scanner honestly skips symbols with no real daily bars, never fabricates a signal")


def test_scanner_does_not_fire_on_none_signal():
    """A flat/no-setup bar must never reach the executor."""
    import sovereign_squeeze_scanner

    bars = _dummy_bars()
    fixed_out = {
        "events": [None] * len(bars),
        "live_signal": [None] * len(bars),
        "score": [0] * len(bars),
        "sqz_bar_count": [0] * len(bars),
    }

    dm = MagicMock()
    dm.get_bars.return_value = bars

    with patch("core.legacy.get_service", return_value=dm), \
         patch("sovereign_squeeze_engine.SovereignSqueezeParams.from_env", return_value=_small_params()), \
         patch("sovereign_squeeze_engine.compute_series", return_value=fixed_out), \
         patch("sovereign_squeeze_scanner._symbols", return_value=["SPY"]), \
         patch("iam_executor.execute_async") as mock_exec:
        sovereign_squeeze_scanner._last_fired.clear()
        fired = sovereign_squeeze_scanner.scan_once()

    assert fired == 0
    assert mock_exec.call_count == 0
    print("PASS: scanner does not fire the executor on a None (no-setup) bar")


def test_blueprint_registers_at_expected_routes():
    from core.app import create_app
    app = create_app()
    rules = {r.rule for r in app.url_map.iter_rules() if "sovereign-squeeze" in r.rule}
    assert "/api/sovereign-squeeze/status" in rules, rules
    assert "/api/sovereign-squeeze/<symbol>" in rules, rules
    print(f"PASS: /api/sovereign-squeeze blueprint registered — {rules}")


if __name__ == "__main__":
    test_scanner_dedup_prevents_double_firing_the_same_bar_and_action()
    test_scanner_skips_honestly_when_no_daily_data()
    test_scanner_does_not_fire_on_none_signal()
    test_blueprint_registers_at_expected_routes()
    print("\nAll regression tests passed.")
