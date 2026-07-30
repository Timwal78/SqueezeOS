"""
Smoke test for ttm_squeeze_engine.py — code-correctness only, NOT a
performance claim. Confirms compute_series()/analyze() run without crashing,
produce the documented output shapes, that squeeze-on/fire detection behaves
correctly on deterministic synthetic bars, and that the entry/exit state
machine is a real walk-forward simulation with no lookahead.

The real profitability evidence is docs/TTM_SQUEEZE_BACKTEST_2026-07-30.md
(real data via Robinhood MCP) — verdict: NOT profitable as-configured. This
file uses synthetic-but-deterministic bars ONLY to exercise the state
machine mechanically — never presented as a backtest result.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ttm_squeeze_engine import compute_series, analyze, SqueezeParams  # noqa: E402


def _tight_range_bars(n, center=100.0, band=0.15):
    """Very tight consolidation -- Bollinger Bands should sit inside Keltner
    Channels here (low realized vol relative to true range)."""
    bars = []
    for i in range(n):
        px = center + (band if i % 2 == 0 else -band) * 0.3
        bars.append({"close": px, "high": px + band, "low": px - band})
    return bars


def _tight_then_expand_up(warmup=45, tight_len=30, breakout_len=10):
    """Tight consolidation followed by a real trending expansion -- should
    produce a squeeze ON -> FIRE -> ENTER_UP sequence."""
    bars = _tight_range_bars(warmup, center=100.0, band=0.1)
    bars += _tight_range_bars(tight_len, center=100.0, band=0.08)
    px = 100.0
    for i in range(breakout_len):
        px += 1.2
        bars.append({"close": px, "high": px + 0.3, "low": px - 0.3})
    return bars


def test_compute_series_shapes():
    p = SqueezeParams()
    bars = _tight_then_expand_up()
    out = compute_series(bars, p)
    for key in ("events", "live_signal", "state_dir", "pnl_pct", "in_squeeze",
                "fired", "momentum", "in_pos", "direction", "entry_price",
                "stop_price", "target_price"):
        assert key in out, f"missing key: {key}"
    for key in ("events", "live_signal", "state_dir", "pnl_pct", "in_squeeze", "fired", "momentum"):
        assert len(out[key]) == len(bars), f"{key} length mismatch"
    print("PASS: compute_series() returns all documented keys at correct length")


def test_squeeze_detected_during_tight_consolidation():
    p = SqueezeParams()
    bars = _tight_range_bars(80, center=100.0, band=0.08)
    out = compute_series(bars, p)
    on_count = sum(1 for v in out["in_squeeze"] if v is True)
    assert on_count > 0, "expected at least some squeeze-ON bars during a tight consolidation"
    print(f"PASS: squeeze ON detected on {on_count}/{len(bars)} bars during tight consolidation")


def test_fire_and_entry_on_real_expansion():
    p = SqueezeParams()
    bars = _tight_then_expand_up()
    out = compute_series(bars, p)
    fires = sum(1 for f in out["fired"] if f)
    assert fires >= 1, "expected at least one squeeze fire on tight->expansion sequence"
    entries = [e for e in out["events"] if e == "ENTER_UP"]
    assert len(entries) >= 1, "expected at least one ENTER_UP after a bullish fire"
    print(f"PASS: {fires} fire(s), {len(entries)} ENTER_UP event(s) on tight->expansion sequence")


def test_no_lookahead_bb_kc_only_use_past_and_current_bar():
    """Perturbing a FUTURE bar must never change in_squeeze[] at an EARLIER
    index -- proves the walk-forward computation has no lookahead."""
    p = SqueezeParams()
    bars = _tight_then_expand_up()
    out_a = compute_series(bars, p)

    bars_b = [dict(b) for b in bars]
    last = bars_b[-1]
    bars_b[-1] = {"close": last["close"] + 500.0, "high": last["high"] + 500.0, "low": last["low"] + 500.0}
    out_b = compute_series(bars_b, p)

    n = len(bars)
    assert out_a["in_squeeze"][: n - 1] == out_b["in_squeeze"][: n - 1], \
        "changing the LAST bar altered an earlier bar's squeeze state -- lookahead bug"
    assert out_a["events"][: n - 1] == out_b["events"][: n - 1], \
        "changing the LAST bar altered an earlier bar's event -- lookahead bug"
    print("PASS: no lookahead -- perturbing the final bar leaves all earlier bars unchanged")


def test_exit_on_stop_and_target_close_the_position():
    """A position that hits its ATR target must close with EXIT_TARGET and a
    positive pnl_pct; one that gaps through its stop must close with
    EXIT_STOP and a negative pnl_pct."""
    p = SqueezeParams(atr_stop_mult=1.5, atr_target_mult=1.5)  # tight target for a fast, deterministic hit
    bars = _tight_then_expand_up(breakout_len=25)
    out = compute_series(bars, p)
    exit_events = [(i, e) for i, e in enumerate(out["events"]) if e in ("EXIT_TARGET", "EXIT_STOP")]
    assert exit_events, "expected the long entered during the expansion to eventually exit"
    for i, ev in exit_events:
        pnl = out["pnl_pct"][i]
        assert pnl is not None
        if ev == "EXIT_TARGET":
            assert pnl > 0, f"EXIT_TARGET should be a positive pnl, got {pnl}"
        else:
            assert pnl < 0, f"EXIT_STOP should be a negative pnl, got {pnl}"
    print(f"PASS: {len(exit_events)} exit(s), pnl sign matches EXIT_TARGET/EXIT_STOP correctly")


def test_analyze_insufficient_data():
    p = SqueezeParams()
    r = analyze("TEST", [{"close": 1, "high": 1, "low": 1}] * 5, p)
    assert r["status"] == "insufficient_data"
    print("PASS: analyze() reports insufficient_data honestly on too-short input")


def test_analyze_on_demand_matches_compute_series_last_bar():
    p = SqueezeParams()
    bars = _tight_then_expand_up()
    out = compute_series(bars, p)
    r = analyze("TEST", bars, p)
    last = len(bars) - 1
    assert r["status"] == "success"
    assert r["event"] == out["events"][last]
    assert r["signal"] == out["live_signal"][last]
    assert r["in_squeeze"] == out["in_squeeze"][last]
    assert r["just_fired"] == out["fired"][last]
    print("PASS: analyze() on-demand result matches compute_series()'s own last-bar state exactly")


if __name__ == "__main__":
    test_compute_series_shapes()
    test_squeeze_detected_during_tight_consolidation()
    test_fire_and_entry_on_real_expansion()
    test_no_lookahead_bb_kc_only_use_past_and_current_bar()
    test_exit_on_stop_and_target_close_the_position()
    test_analyze_insufficient_data()
    test_analyze_on_demand_matches_compute_series_last_bar()
    print("\nAll tests passed.")
