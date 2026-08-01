"""
Smoke tests for quad_score_engine.py — the new long-only "4-Pillar"
scoring engine (Compression/Trend/Participation/Trigger -> composite gate,
temporal sequence gate, real weekly macro regime filter). Synthetic
fixtures only; the real profitability verdict lives in
tests/backtest_quad_score.py / docs/QUAD_SCORE_BACKTEST_*.md.

Needs ~1000+ bars per fixture since the weekly macro filter requires real
weekly EMA_200 history (~4 years) to ever validate — that's inherent to the
spec's macro filter, not a test artifact.
"""
import random
from datetime import date, timedelta

import quad_score_engine as qse


def _make_dates(n, start=date(2019, 1, 2)):
    dates = []
    d = start
    while len(dates) < n:
        if d.weekday() < 5:
            dates.append(d.isoformat())
        d += timedelta(days=1)
    return dates


def _bull_pretrend(n, base, vol_base, seed):
    rnd = random.Random(seed)
    bars = []
    price = base
    for _ in range(n):
        o = price
        c = price * (1 + 0.0006 + rnd.uniform(-0.004, 0.004))
        h = max(o, c) + rnd.uniform(0.05, 0.3)
        l = min(o, c) - rnd.uniform(0.05, 0.3)
        v = vol_base * rnd.uniform(0.8, 1.3)
        bars.append({"o": o, "h": h, "l": l, "c": c, "v": v})
        price = c
    return bars, price


def _bear_pretrend(n, base, vol_base, seed):
    rnd = random.Random(seed)
    bars = []
    price = base
    for _ in range(n):
        o = price
        c = price * (1 - 0.0015 + rnd.uniform(-0.004, 0.004))
        h = max(o, c) + rnd.uniform(0.05, 0.3)
        l = min(o, c) - rnd.uniform(0.05, 0.3)
        v = vol_base * rnd.uniform(0.8, 1.3)
        bars.append({"o": o, "h": h, "l": l, "c": c, "v": v})
        price = c
    return bars, price


def _flat_choppy(n, base, vol_base, seed):
    rnd = random.Random(seed)
    bars = []
    price = base
    for _ in range(n):
        o = price
        c = price * (1 + rnd.uniform(-0.01, 0.01))
        h = max(o, c) + rnd.uniform(0.05, 0.2)
        l = min(o, c) - rnd.uniform(0.05, 0.2)
        v = vol_base * rnd.uniform(0.7, 1.3)
        bars.append({"o": o, "h": h, "l": l, "c": c, "v": v})
        price = c
    return bars, price


def _coil_then_breakout(price, vol_base, n_coil=160, n_trend=15, seed=99):
    rnd = random.Random(seed)
    bars = []
    for _ in range(n_coil):
        o = price
        c = price * 1.0004 + rnd.uniform(-0.05, 0.05)
        h = max(o, c) + rnd.uniform(0.02, 0.08)
        l = min(o, c) - rnd.uniform(0.02, 0.08)
        v = vol_base * rnd.uniform(0.85, 1.15)
        bars.append({"o": o, "h": h, "l": l, "c": c, "v": v})
        price = c

    o = price
    c = price * 1.06
    h = c + 0.10
    l = o - 0.05
    v = vol_base * 3.5
    bars.append({"o": o, "h": h, "l": l, "c": c, "v": v})
    price = c

    for _ in range(n_trend):
        o = price
        c = price * (1 + rnd.uniform(0.005, 0.02))
        h = c + rnd.uniform(0.05, 0.2)
        l = min(o, c) - rnd.uniform(0.02, 0.1)
        v = vol_base * rnd.uniform(1.2, 2.0)
        bars.append({"o": o, "h": h, "l": l, "c": c, "v": v})
        price = c
    return bars


def _with_dates(bars):
    dates = _make_dates(len(bars))
    for b, d in zip(bars, dates):
        b["date"] = d
    return bars, dates


def _bullish_coil_breakout_bars():
    pretrend, price = _bull_pretrend(1200, 100.0, 1_000_000, seed=1)
    setup = _coil_then_breakout(price, 1_000_000, seed=2)
    bars, dates = _with_dates(pretrend + setup)
    return bars, dates


def test_coil_then_breakout_fires_enter_call():
    bars, dates = _bullish_coil_breakout_bars()
    p = qse.QuadScoreParams.from_env()
    out = qse.compute_series(bars, p)
    entries = [i for i, e in enumerate(out["events"]) if e == "ENTER_CALL"]
    assert entries, "expected at least one ENTER_CALL in a real bull coil->breakout->uptrend fixture"
    for i in entries:
        assert out["live_signal"][i] == "BUY"
        assert out["scores"][i] is not None
        assert out["scores"][i]["composite"] >= p.th_composite
        assert out["temporal_valid"][i] is True
        assert out["macro_valid"][i] is True


def test_entries_have_real_stop_and_target_below_above_entry():
    bars, dates = _bullish_coil_breakout_bars()
    out = qse.compute_series(bars)
    # replay the state machine's own final position fields make sense
    if out["in_pos"]:
        assert out["stop_price"] < out["entry_price"] < out["target_price"]


def test_flat_choppy_series_produces_almost_no_signals():
    """A flat/choppy random walk should essentially never clear the gate --
    percentile-rank-based scores are relative, not absolute, so a rare
    chance alignment (noise ranking high within its own trailing window)
    is not itself a bug; only a MEANINGFUL rate of false positives would
    be. This is a materially looser gate than the operator's original
    spec (composite>=65 vs 70, trend/trigger>=45 vs 50/60) after the real
    TRAIN/VALID search in docs/QUAD_SCORE_OPTIMIZATION_2026-07-31.md, so a
    small number of incidental firings on pure noise is expected."""
    bars, price = _flat_choppy(1400, 100.0, 1_000_000, seed=5)
    bars, dates = _with_dates(bars)
    out = qse.compute_series(bars)
    entries = [i for i, e in enumerate(out["events"]) if e == "ENTER_CALL"]
    assert len(entries) <= 5, f"expected at most a handful of incidental firings on pure noise, got {len(entries)}"


def test_bear_pretrend_blocks_entry_via_macro_regime():
    """Even a real coil+breakout should NOT fire a CALL if the higher-
    timeframe macro regime (weekly close vs weekly EMA200, weekly ADX) is
    bearish going into it -- proves the macro filter is load-bearing, not
    a no-op that's always True."""
    pretrend, price = _bear_pretrend(1200, 300.0, 1_000_000, seed=3)
    setup = _coil_then_breakout(price, 1_000_000, n_trend=5, seed=4)
    bars, dates = _with_dates(pretrend + setup)
    out = qse.compute_series(bars)

    # right where the coil begins, immediately after 1200 bars of a real,
    # sustained decline -- the weekly regime must still read bearish here
    early_setup = range(1200, 1250)
    macro_readings = [out["macro_valid"][i] for i in early_setup if out["macro_valid"][i] is not None]
    assert macro_readings, "expected the macro filter to be computable by this point"
    assert not any(macro_readings), "macro regime should read bearish right after a real sustained downtrend"

    assert "ENTER_CALL" not in out["events"], (
        "a bear-market pretrend fixture should never produce a live CALL entry anywhere in the series"
    )


def test_temporal_gate_matches_its_own_spec():
    """Direct correctness check of the temporal-sequence gate against the
    engine's own compression output: valid iff compression cleared
    temporal_threshold at least once in the 10 bars strictly BEFORE i."""
    bars, dates = _bullish_coil_breakout_bars()
    p = qse.QuadScoreParams.from_env()
    out = qse.compute_series(bars, p)
    compression = out["compression"]
    for i in range(p.temporal_lookback, len(bars), 37):  # sample, not every bar (speed)
        window = [compression[j] for j in range(max(0, i - p.temporal_lookback), i) if compression[j] is not None]
        expected = (max(window) >= p.temporal_threshold) if window else None
        assert out["temporal_valid"][i] == expected


def test_weekly_macro_filter_has_no_lookahead():
    """Mutating a LATER day within the SAME still-forming week as day i
    must never change macro_valid[i] -- day i's macro decision only ever
    reads fully completed PRIOR weeks."""
    bars, dates = _bullish_coil_breakout_bars()
    p = qse.QuadScoreParams.from_env()

    macro_a = qse._weekly_macro_series(bars, p)

    # find a day that is NOT the last day of its own week, so there's a
    # later same-week day left to mutate
    _, day_week_key, _ = qse._aggregate_weekly(bars)
    target_i = None
    for i in range(len(bars) - 5):
        if day_week_key[i] is not None and day_week_key[i] == day_week_key[i + 1]:
            target_i = i
            break
    assert target_i is not None, "fixture should contain at least one mid-week day"

    mutated = [dict(b) for b in bars]
    later_same_week = target_i + 1
    mutated[later_same_week]["c"] = mutated[later_same_week]["c"] * 5.0
    mutated[later_same_week]["h"] = mutated[later_same_week]["c"] * 1.1
    mutated[later_same_week]["l"] = mutated[later_same_week]["c"] * 0.9

    macro_b = qse._weekly_macro_series(mutated, p)
    assert macro_a[target_i] == macro_b[target_i], (
        "macro regime for day i changed after mutating a LATER day in i's own "
        "still-forming week -- that is a lookahead bug"
    )


def test_percentile_rank_basic_correctness():
    # window [2,3,...,10,0.5]: cur=0.5 is <= only itself -> 1/10 = 10%
    vals = [float(x) for x in range(1, 11)] + [0.5]
    out = qse._percentile_rank(vals, window=10)
    assert out[-1] == 10.0

    # strictly increasing series: every new value is the max of its own
    # trailing window -> 100% everywhere a full window exists
    incr = [float(x) for x in range(1, 21)]
    out2 = qse._percentile_rank(incr, window=10)
    assert out2[9] == 100.0
    assert out2[-1] == 100.0


def test_analyze_insufficient_data_reports_honestly():
    result = qse.analyze("TEST", [{"c": 1, "h": 1, "l": 1, "v": 1}] * 10)
    assert result["status"] == "insufficient_data"
    assert result["bars"] == 10


def test_analyze_matches_compute_series_last_bar():
    bars, dates = _bullish_coil_breakout_bars()
    out = qse.compute_series(bars)
    result = qse.analyze("TEST", bars)
    last = len(bars) - 1
    assert result["status"] == "success"
    assert result["event"] == out["events"][last]
    assert result["signal"] == out["live_signal"][last]
    assert result["scores"]["composite"] == out["composite"][last]
