"""
Tests for the SML Quad-Score Explosive Breakout Finder live-execution
wiring: quad_score_scanner.py's dedup/dispatch logic and blueprint
registration — the pieces that make the setup actually reachable from a
live scan pass, not just a backtest harness. Same convention as
tests/test_sovereign_squeeze_scanner_wiring.py.

Not a profitability claim — see docs/QUAD_SCORE_BACKTEST_2026-07-31.md for
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
    """Test-only params — the real defaults need ~1000+ bars just to clear
    the min-bars check (the weekly-macro-regime filter needs ~4 years of
    real history), which isn't the thing these dedup/dispatch tests
    exercise."""
    from quad_score_engine import QuadScoreParams
    return QuadScoreParams(pctile_window=10, hv_length=5, ema_slow=10, weekly_ema_len=2, atr_length=5)


def test_scanner_dedup_prevents_double_firing_the_same_bar_and_action():
    """quad_score_scanner.scan_once()'s per-bar dedup key must not re-fire
    the executor for the same (symbol, bar, action) across consecutive
    passes — same convention as every other scanner's _last_fired guard."""
    import quad_score_scanner

    bars = _dummy_bars()
    fixed_out = {
        "events": [None] * (len(bars) - 1) + ["ENTER_CALL"],
        "live_signal": [None] * (len(bars) - 1) + ["BUY"],
        "scores": [None] * (len(bars) - 1) + [{"composite": 82.0}],
    }

    dm = MagicMock()
    dm.get_bars.return_value = bars

    with patch("core.legacy.get_service", return_value=dm), \
         patch("quad_score_engine.QuadScoreParams.from_env", return_value=_small_params()), \
         patch("quad_score_engine.compute_series", return_value=fixed_out), \
         patch("quad_score_scanner._symbols", return_value=["SPY"]), \
         patch("iam_executor.execute_async") as mock_exec:
        quad_score_scanner._last_fired.clear()
        fired_1 = quad_score_scanner.scan_once()
        fired_2 = quad_score_scanner.scan_once()

    assert fired_1 == 1, "first pass with a real BUY signal must fire exactly once"
    assert fired_2 == 0, "second pass on the SAME bar/action must be deduped, not re-fired"
    assert mock_exec.call_count == 1, "executor must only be called once across both passes"
    call_args = mock_exec.call_args
    assert call_args[0][0] == "SPY"
    assert call_args[0][1]["system"] == "SML_QUAD_SCORE"
    assert call_args[0][1]["action"] == "BUY"
    print("PASS: scanner dedups repeat passes and tags the resolution system=SML_QUAD_SCORE correctly")


def test_scanner_skips_honestly_when_no_daily_data():
    """No fabricated bars, no fabricated signal, when the data provider has nothing."""
    import quad_score_scanner

    dm = MagicMock()
    dm.get_bars.return_value = []

    with patch("core.legacy.get_service", return_value=dm), \
         patch("quad_score_scanner._symbols", return_value=["SPY"]), \
         patch("iam_executor.execute_async") as mock_exec:
        quad_score_scanner._last_fired.clear()
        fired = quad_score_scanner.scan_once()

    assert fired == 0
    assert mock_exec.call_count == 0
    print("PASS: scanner honestly skips symbols with no real daily bars, never fabricates a signal")


def test_scanner_does_not_fire_on_none_signal():
    """A flat/no-setup bar must never reach the executor."""
    import quad_score_scanner

    bars = _dummy_bars()
    fixed_out = {
        "events": [None] * len(bars),
        "live_signal": [None] * len(bars),
        "scores": [None] * len(bars),
    }

    dm = MagicMock()
    dm.get_bars.return_value = bars

    with patch("core.legacy.get_service", return_value=dm), \
         patch("quad_score_engine.QuadScoreParams.from_env", return_value=_small_params()), \
         patch("quad_score_engine.compute_series", return_value=fixed_out), \
         patch("quad_score_scanner._symbols", return_value=["SPY"]), \
         patch("iam_executor.execute_async") as mock_exec:
        quad_score_scanner._last_fired.clear()
        fired = quad_score_scanner.scan_once()

    assert fired == 0
    assert mock_exec.call_count == 0
    print("PASS: scanner does not fire the executor on a None (no-setup) bar")


def test_blueprint_registers_at_expected_routes():
    from core.app import create_app
    app = create_app()
    rules = {r.rule for r in app.url_map.iter_rules() if "quad-score" in r.rule}
    assert "/api/quad-score/status" in rules, rules
    assert "/api/quad-score/<symbol>" in rules, rules
    print(f"PASS: /api/quad-score blueprint registered — {rules}")


if __name__ == "__main__":
    test_scanner_dedup_prevents_double_firing_the_same_bar_and_action()
    test_scanner_skips_honestly_when_no_daily_data()
    test_scanner_does_not_fire_on_none_signal()
    test_blueprint_registers_at_expected_routes()
    print("\nAll regression tests passed.")
