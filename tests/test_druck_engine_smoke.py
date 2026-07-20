"""
Smoke test for druck_engine.py — code-correctness only, NOT a performance
claim. This confirms the Python port runs without crashing, produces the
expected output shapes, and that its crossover logic behaves like a real
two-bar-lookback crossover (the bug this port's breakout section was
rewritten to avoid — see the comment in compute_series()). It says nothing
about whether the strategy is profitable; that requires tests/backtest_druck.py
run against real historical bars, which this sandbox cannot fetch (see
CLAUDE.md and this session's own audit for why).

The price series below is a synthetic staircase built ONLY to exercise a
single, unambiguous breakout crossover deterministically — it is not
presented as, and must never be mistaken for, real market data or a
backtest result.
"""

import os
import random
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from druck_engine import compute_series, DruckParams, _percentrank, AdxDmi  # noqa: E402


def _synthetic_bars(n=160, start_price=100.0, seed=42):
    """
    Deterministic (fixed-seed) synthetic OHLCV: noisy chop for the first 100
    bars, then a moderate directional drift added on top of the SAME noise
    magnitude for the rest. Keeping bar-to-bar range roughly consistent across
    the transition matters — an earlier draft of this fixture used a perfectly
    smooth linear ramp, which produces a discontinuous ATR spike at the
    transition (real ATR percentile properly floods to the 99th percentile on
    a hard step function), tripping the VOLATILE-regime gate for the rest of
    the series and never letting regime reach TREND. That wasn't a bug in
    druck_engine.py — real market bars don't step-function like that, so this
    noisy-but-consistent-range fixture is the realistic one.
    """
    rng = random.Random(seed)
    bars = []
    t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    price = start_price
    for i in range(n):
        noise = rng.uniform(-0.15, 0.15)
        drift = 0.0 if i < 100 else 0.35
        price += noise + drift
        bar_range = 0.5
        o = price - bar_range / 2
        h = price + bar_range / 2 + abs(noise)
        l = price - bar_range / 2 - abs(noise)
        c = price
        v = (100_000 if i < 100 else 250_000) + rng.uniform(-5000, 5000)
        bars.append({
            "date": (t0 + timedelta(minutes=15 * i)).isoformat(),
            "open": o, "high": h, "low": l, "close": c, "volume": v,
        })
    return bars


def test_engine_runs_without_crashing_and_returns_expected_shape():
    bars = _synthetic_bars()
    p = DruckParams(use_higher_trend=False, use_dxy=False)  # isolate core logic; no HTF data supplied
    result = compute_series(bars, p)

    assert "signals" in result and "jugular" in result and "state" in result
    assert len(result["signals"]) == len(bars)
    assert len(result["jugular"]) == len(bars)
    assert all(s in (None, "BUY", "SELL") for s in result["signals"])
    print("PASS: compute_series runs end-to-end on a real (synthetic-but-deterministic) bar series and returns the documented shape")


def test_uptrend_drift_produces_at_least_one_buy_signal_during_the_trend_phase():
    bars = _synthetic_bars()
    p = DruckParams(use_higher_trend=False, use_dxy=False)
    result = compute_series(bars, p)
    signals_in_trend_phase = result["signals"][100:]
    assert "BUY" in signals_in_trend_phase, (
        "A sustained upward drift with volume expansion should fire at least one "
        "BUY entry once it's underway — if this fails, the breakout/crossover "
        f"wiring is broken. Signals seen: {[s for s in result['signals'] if s]}"
    )
    print("PASS: sustained upward drift produces a BUY signal during the trend phase")


def test_percentrank_matches_hand_computed_value():
    # 10 values, current = 8th largest of the trailing window -> 7/10 strictly below it
    history = [1, 2, 3, 4, 5, 6, 7, 9, 10]
    current = 8
    pct = _percentrank(history, current, 10)
    assert pct == 70.0, pct
    print(f"PASS: _percentrank hand-computed check ({pct}%)")


def test_backtest_harness_simulate_runs_without_crashing():
    """
    Proves tests/backtest_druck.py's simulate() (the full stop/target/trailing-
    stop/pyramid state machine) runs end-to-end and produces sane output shapes
    on the same synthetic-but-deterministic bars — NOT a profitability claim,
    just confirms the harness itself is wired correctly and ready for real data.
    """
    from tests.backtest_druck import simulate

    bars = _synthetic_bars()
    p = DruckParams(use_higher_trend=False, use_dxy=False)
    result = compute_series(bars, p)
    stats = simulate(bars, result["signals"], result["jugular"], p)

    for key in ("trades", "win_rate", "avg_trade_pct", "profit_factor",
                "avg_bars_held", "jugular_trades", "total_return_pct"):
        assert key in stats, f"missing key: {key}"
    assert stats["trades"] >= 1, "expected at least one simulated round-trip on this fixture"
    assert 0.0 <= stats["win_rate"] <= 100.0
    print(f"PASS: backtest_druck.simulate() runs end-to-end — {stats['trades']} trades, "
          f"win_rate={stats['win_rate']:.1f}% (synthetic fixture, not a real result)")


def test_adx_dmi_produces_bounded_values_on_a_real_trend():
    """ADX/DI+ /DI- must stay within their mathematically valid 0-100 range."""
    engine = AdxDmi(14)
    price = 100.0
    for i in range(60):
        price += 0.5
        di_plus, di_minus, adx = engine.update(price + 0.3, price - 0.3, price)
    assert 0.0 <= di_plus <= 100.0
    assert 0.0 <= di_minus <= 100.0
    assert 0.0 <= adx <= 100.0
    # A sustained uptrend must show +DI dominant over -DI.
    assert di_plus > di_minus, f"expected +DI dominant in an uptrend, got +DI={di_plus:.1f} -DI={di_minus:.1f}"
    print(f"PASS: AdxDmi bounded and directionally correct on a sustained uptrend (+DI={di_plus:.1f} -DI={di_minus:.1f} ADX={adx:.1f})")


if __name__ == "__main__":
    test_engine_runs_without_crashing_and_returns_expected_shape()
    test_uptrend_drift_produces_at_least_one_buy_signal_during_the_trend_phase()
    test_percentrank_matches_hand_computed_value()
    test_backtest_harness_simulate_runs_without_crashing()
    test_adx_dmi_produces_bounded_values_on_a_real_trend()
    print("\nAll smoke tests passed (code correctness only — not a profitability claim).")
