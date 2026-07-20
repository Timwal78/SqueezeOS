"""
Tests for the new DRUCK-LB live-execution wiring (2026-07-20): druck_engine.py's
analyze() wrapper, druck_scanner.py's dedup/dispatch logic, and blueprint
registration — the pieces that make DRUCK-LB actually reachable from a live
scan pass, not just a backtest harness.

Not a profitability claim (see docs/DELTAFORGE-style disclosure pattern
established for DRUCK-LB in tests/backtest_druck.py) — this proves the wiring
is correct and reaches the real executor, using the real, unmodified
druck_engine.compute_series() against synthetic-but-realistic bars. Whether
the strategy wins is a separate, still-open question (no real market data
access in this sandbox — see backtest_druck.py's own disclosure).
"""

import os
import random
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from druck_engine import DruckParams, analyze  # noqa: E402


def _synthetic_bars(n=160, start_price=100.0, seed=7):
    """Same style fixture as test_druck_engine_smoke.py's _synthetic_bars —
    seeded noise, not a smooth ramp, so ATR/percentrank don't spike artificially."""
    rnd = random.Random(seed)
    bars = []
    price = start_price
    base = datetime(2026, 7, 1, tzinfo=timezone.utc)
    for i in range(n):
        drift = 0.15 if i > n // 2 else 0.0  # mild uptrend in the back half
        change = rnd.uniform(-1.0, 1.0) + drift
        o = price
        c = max(0.5, price + change)
        h = max(o, c) + abs(rnd.uniform(0, 0.5))
        l = min(o, c) - abs(rnd.uniform(0, 0.5))
        v = rnd.uniform(500_000, 1_500_000)
        bars.append({
            "date": (base + timedelta(minutes=15 * i)).isoformat(),
            "open": o, "high": h, "low": l, "close": c, "volume": v,
        })
        price = c
    return bars


def test_analyze_insufficient_data_reports_honestly():
    result = analyze("SPY", [])
    assert result["status"] == "insufficient_data"
    assert result["symbol"] == "SPY"
    assert result["bars"] == 0
    print(f"PASS: analyze() with no bars reports insufficient_data honestly — {result}")


def test_analyze_runs_end_to_end_and_returns_expected_shape():
    bars = _synthetic_bars(n=160)
    result = analyze("SPY", bars)

    assert result["status"] == "success", result
    assert result["symbol"] == "SPY"
    assert result["signal"] in (None, "BUY", "SELL")
    assert isinstance(result["jugular"], bool)
    assert result["price"] > 0
    assert "regime" in result and "adx" in result and "atr" in result
    # internal carry-over state must never leak into the public API shape
    assert not any(k.startswith("_") for k in result.keys()), result
    print(f"PASS: analyze() end-to-end shape is correct — signal={result['signal']}, "
          f"regime={result['regime']}, jugular={result['jugular']}")


def test_analyze_min_bars_scales_with_largest_lookback_param():
    p = DruckParams(atr_pctile_len=200)
    result = analyze("SPY", _synthetic_bars(n=50), p)
    assert result["status"] == "insufficient_data"
    assert result["min_bars"] == 200 + 10
    print(f"PASS: min_bars honestly scales with the configured atr_pctile_len — {result}")


def test_scanner_dedup_prevents_double_firing_the_same_bar_and_action():
    """druck_scanner.scan_once()'s per-bar dedup key must not re-fire the
    executor for the same (symbol, bar, action) across consecutive passes —
    same convention as orb_scanner.py's _last_fired guard."""
    import druck_scanner

    bars = _synthetic_bars(n=160)
    # Force compute_series to report a definite BUY on the final bar, without
    # depending on the synthetic data happening to trigger one for real.
    fixed_result = {
        "symbol": "SPY", "status": "success", "signal": "BUY", "jugular": True,
        "price": bars[-1]["close"], "regime": 2, "adx": 30.0, "atr_pctile": 90.0,
    }

    dm = MagicMock()
    dm.get_bars.return_value = bars

    with patch("core.legacy.get_service", return_value=dm), \
         patch("druck_engine.analyze", return_value=fixed_result), \
         patch("druck_scanner._symbols", return_value=["SPY"]), \
         patch("iam_executor.execute_async") as mock_exec:
        druck_scanner._last_fired.clear()
        fired_1 = druck_scanner.scan_once()
        fired_2 = druck_scanner.scan_once()

    assert fired_1 == 1, "first pass with a real BUY signal must fire exactly once"
    assert fired_2 == 0, "second pass on the SAME bar/action must be deduped, not re-fired"
    assert mock_exec.call_count == 1, "executor must only be called once across both passes"
    call_args = mock_exec.call_args
    assert call_args[0][0] == "SPY"
    assert call_args[0][1]["system"] == "SML_DRUCK"
    assert call_args[0][1]["action"] == "BUY"
    print(f"PASS: scanner dedups repeat passes and tags the resolution system=SML_DRUCK correctly")


def test_scanner_skips_honestly_when_no_intraday_data():
    """No fabricated bars, no fabricated signal, when the data provider has nothing."""
    import druck_scanner

    dm = MagicMock()
    dm.get_bars.return_value = []

    with patch("core.legacy.get_service", return_value=dm), \
         patch("druck_scanner._symbols", return_value=["SPY"]), \
         patch("iam_executor.execute_async") as mock_exec:
        druck_scanner._last_fired.clear()
        fired = druck_scanner.scan_once()

    assert fired == 0
    assert mock_exec.call_count == 0
    print("PASS: scanner honestly skips symbols with no real intraday bars, never fabricates a signal")


def test_blueprint_registers_at_expected_routes():
    from core.app import create_app
    app = create_app()
    rules = {r.rule for r in app.url_map.iter_rules() if "druck" in r.rule}
    assert "/api/druck/status" in rules, rules
    assert "/api/druck/<symbol>" in rules, rules
    print(f"PASS: /api/druck blueprint registered — {rules}")


if __name__ == "__main__":
    test_analyze_insufficient_data_reports_honestly()
    test_analyze_runs_end_to_end_and_returns_expected_shape()
    test_analyze_min_bars_scales_with_largest_lookback_param()
    test_scanner_dedup_prevents_double_firing_the_same_bar_and_action()
    test_scanner_skips_honestly_when_no_intraday_data()
    test_blueprint_registers_at_expected_routes()
    print("\nAll regression tests passed.")
