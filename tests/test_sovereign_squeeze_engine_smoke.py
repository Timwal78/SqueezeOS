"""
Smoke test for sovereign_squeeze_engine.py — code-correctness only, NOT a
performance claim. Confirms compute_series()/analyze() run without
crashing, produce the documented shapes, and that a genuine
compression -> release -> momentum-confirmed setup actually fires a signal
on a synthetic-but-deterministic bar series (the real profitability
evidence, if any, lives in a dated backtest doc — see CLAUDE.md).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sovereign_squeeze_engine import compute_series, analyze, SovereignSqueezeParams  # noqa: E402


def _flat_bars(n, price=100.0, volume=1000.0):
    return [{"date": f"2026-01-{i+1:02d}", "open": price, "high": price + 0.1,
              "low": price - 0.1, "close": price, "volume": volume} for i in range(n)]


def _coil_then_breakout_bars(coil_len=25, tail_len=8, base=100.0, vol=1000.0):
    """A clean squeeze setup: a tight, low-range coil (BB collapses inside KC)
    followed by a real breakout bar with a volume spike, then several more
    up bars with accelerating closes (so val keeps rising) — an unambiguous
    CALL setup with nothing else confounding it."""
    bars = []
    for i in range(coil_len):
        bars.append({"date": f"2026-01-{i+1:02d}", "open": base, "high": base + 0.15,
                      "low": base - 0.15, "close": base, "volume": vol})
    # breakout bar: wide range, big volume spike
    breakout_close = base + 3.0
    bars.append({"date": f"2026-02-01", "open": base, "high": breakout_close + 0.5,
                  "low": base - 0.2, "close": breakout_close, "volume": vol * 4})
    # follow-through: closes keep rising so linreg momentum accelerates upward
    last_close = breakout_close
    for i in range(tail_len):
        last_close += 0.8
        bars.append({"date": f"2026-02-{i+2:02d}", "open": last_close - 0.8, "high": last_close + 0.3,
                      "low": last_close - 1.0, "close": last_close, "volume": vol * 2})
    return bars


def _coil_then_breakdown_bars(coil_len=25, tail_len=8, base=100.0, vol=1000.0):
    bars = []
    for i in range(coil_len):
        bars.append({"date": f"2026-01-{i+1:02d}", "open": base, "high": base + 0.15,
                      "low": base - 0.15, "close": base, "volume": vol})
    breakdown_close = base - 3.0
    bars.append({"date": f"2026-02-01", "open": base, "high": base + 0.2,
                  "low": breakdown_close - 0.5, "close": breakdown_close, "volume": vol * 4})
    last_close = breakdown_close
    for i in range(tail_len):
        last_close -= 0.8
        bars.append({"date": f"2026-02-{i+2:02d}", "open": last_close + 0.8, "high": last_close + 1.0,
                      "low": last_close - 0.3, "close": last_close, "volume": vol * 2})
    return bars


_TEST_PARAMS = SovereignSqueezeParams(
    bb_length=10, bb_mult=2.0, kc_length=10, kc_mult=1.5,
    min_sqz_bars=2, use_rvol=True, min_rvol=1.2,
    use_macro_ema=False, macro_ema_len=200, rr_ratio=2.0,
)


def test_compute_series_shapes():
    bars = _coil_then_breakout_bars()
    out = compute_series(bars, _TEST_PARAMS)
    for key in ("events", "live_signal", "state_dir", "pnl_pct", "score",
                "sqz_on", "sqz_off", "sqz_bar_count", "val"):
        assert key in out, f"missing key: {key}"
    assert len(out["live_signal"]) == len(bars)
    assert all(s in (None, "BUY", "SELL") for s in out["live_signal"])
    print("PASS: compute_series returns the documented shape")


def test_squeeze_compresses_during_the_coil():
    bars = _coil_then_breakout_bars()
    out = compute_series(bars, _TEST_PARAMS)
    # somewhere late in the coil (once BB/KC have a full window) the squeeze
    # must actually be ON — otherwise the setup can never validate its length
    coil_tail = range(_TEST_PARAMS.bb_length, 25)
    assert any(out["sqz_on"][i] for i in coil_tail), "a genuinely tight coil must register sqz_on somewhere"
    print("PASS: a tight, low-range coil registers squeeze-ON")


def test_coil_then_breakout_fires_a_real_call_setup():
    bars = _coil_then_breakout_bars()
    out = compute_series(bars, _TEST_PARAMS)
    enter_idxs = [i for i, e in enumerate(out["events"]) if e == "ENTER_CALL"]
    assert enter_idxs, f"expected at least one ENTER_CALL; events={out['events']}"
    i = enter_idxs[0]
    assert out["live_signal"][i] == "BUY"
    assert out["score"][i] > 0
    print(f"PASS: coil->breakout fires a real ENTER_CALL at bar {i}, score={out['score'][i]}")


def test_coil_then_breakdown_fires_a_real_put_setup():
    bars = _coil_then_breakdown_bars()
    out = compute_series(bars, _TEST_PARAMS)
    enter_idxs = [i for i, e in enumerate(out["events"]) if e == "ENTER_PUT"]
    assert enter_idxs, f"expected at least one ENTER_PUT; events={out['events']}"
    i = enter_idxs[0]
    assert out["live_signal"][i] == "SELL"
    print(f"PASS: coil->breakdown fires a real ENTER_PUT at bar {i}")


def test_low_rvol_blocks_an_otherwise_qualifying_setup():
    """Same coil/breakout shape but with the RVOL requirement tightened past
    what the fixture can clear -- the setup must NOT fire. Proves the RVOL
    gate is load-bearing, not decorative."""
    bars = _coil_then_breakout_bars()
    strict = SovereignSqueezeParams(**{**_TEST_PARAMS.__dict__, "min_rvol": 50.0})
    out = compute_series(bars, strict)
    assert not any(e == "ENTER_CALL" for e in out["events"]), "an impossible RVOL bar should block the setup"
    print("PASS: RVOL gate genuinely blocks an otherwise-qualifying setup when set impossibly high")


def test_flat_series_produces_no_signals():
    bars = _flat_bars(60)
    out = compute_series(bars, _TEST_PARAMS)
    assert all(s is None for s in out["live_signal"]), "a perfectly flat series must never fire a setup"
    print("PASS: flat series produces no false setups")


def test_exit_target_and_stop_close_a_call_position():
    bars = _coil_then_breakout_bars(tail_len=20)
    out = compute_series(bars, _TEST_PARAMS)
    enter_idxs = [i for i, e in enumerate(out["events"]) if e == "ENTER_CALL"]
    assert enter_idxs
    exit_idxs = [i for i, e in enumerate(out["events"]) if e in ("EXIT_TARGET", "EXIT_STOP")]
    assert exit_idxs, "a long enough follow-through should eventually hit target or stop"
    for i in exit_idxs:
        assert out["live_signal"][i] == "SELL"
    print(f"PASS: CALL position exits emit SELL at bars {exit_idxs}")


def test_analyze_insufficient_data_reports_honestly():
    result = analyze("SPY", [])
    assert result["status"] == "insufficient_data"
    assert result["symbol"] == "SPY"
    print(f"PASS: analyze() with no bars reports insufficient_data honestly — {result}")


def test_analyze_end_to_end_shape():
    bars = _coil_then_breakout_bars()
    result = analyze("SPY", bars, _TEST_PARAMS)
    assert result["status"] == "success", result
    assert result["signal"] in (None, "BUY", "SELL")
    assert result["squeeze_state"] in ("COILING", "RELEASED", "NEUTRAL")
    assert "position" in result and "params" in result
    print(f"PASS: analyze() end-to-end shape correct — signal={result['signal']}, state={result['squeeze_state']}")


if __name__ == "__main__":
    test_compute_series_shapes()
    test_squeeze_compresses_during_the_coil()
    test_coil_then_breakout_fires_a_real_call_setup()
    test_coil_then_breakdown_fires_a_real_put_setup()
    test_low_rvol_blocks_an_otherwise_qualifying_setup()
    test_flat_series_produces_no_signals()
    test_exit_target_and_stop_close_a_call_position()
    test_analyze_insufficient_data_reports_honestly()
    test_analyze_end_to_end_shape()
    print("\nAll smoke tests passed (code correctness only — not a profitability claim).")
