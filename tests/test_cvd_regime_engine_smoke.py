"""
Regression + smoke tests for cvd_regime_engine.py — code-correctness only, NOT
a performance claim. Real profitability evidence (such as it is) lives in
docs/CVD_REGIME_BACKTEST_2026-07-30.md.

This file is deliberately organized as ONE TEST PER BUG found in the
operator-submitted Pine script, and where the bug is reproducible it is
reproduced here against the ORIGINAL formula so the fix is demonstrated rather
than asserted. Synthetic-but-deterministic bars are used only to exercise the
mechanics — never presented as a backtest result.
"""
import os
import sys
import random
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cvd_regime_engine import (  # noqa: E402
    compute_series, analyze, CvdParams, bar_delta, _stdev, _clamp,
)

BAR_MIN = 5          # 5-minute chart
SESSION_BARS = 78    # RTH 5-minute bars per day


def _bars(sessions=8, seed=7, bar_min=BAR_MIN, per_session=SESSION_BARS):
    """Deterministic synthetic intraday bars with alternating daily drift, so
    both long and short regimes occur. Timestamps are real UTC RTH stamps so
    the day-reset and HTF-bucket logic are genuinely exercised."""
    random.seed(seed)
    out = []
    px = 100.0
    day0 = datetime(2026, 7, 1, 13, 30, tzinfo=timezone.utc)
    for d in range(sessions):
        drift = 0.02 if d % 2 == 0 else -0.02
        for b in range(per_session):
            t = day0 + timedelta(days=d, minutes=bar_min * b)
            px += drift + random.gauss(0, 0.05)
            hi = px + abs(random.gauss(0, 0.04))
            lo = px - abs(random.gauss(0, 0.04))
            out.append({
                "begins_at": t.isoformat().replace("+00:00", "Z"),
                "open": px, "high": max(hi, px), "low": min(lo, px),
                "close": px, "volume": 100000 + random.randint(0, 50000),
            })
    return out


# ─────────────────────────────────────────────────────────────────────────────
# BUG 1 — the HTF slope was indexed on chart bars, so it was exactly zero on ~3/4
# of bars (no signal possible on those), and a 1-HTF-bar difference on the rest.
# ─────────────────────────────────────────────────────────────────────────────
def test_bug1_original_htf_slope_is_zero_on_most_bars():
    """Reproduces the submitted script's HTF handling faithfully:
        htfCvdS  = request.security(tickerid, "60", cvdS)   # last CLOSED value,
                                                            # held flat
        htfSlope = htfCvdS - htfCvdS[slopeLen]               # indexed on CHART bars
    and shows the slope is exactly 0.0 on the large majority of bars. On every
    such bar htfBull and htfBear are both false, which makes alignedBull /
    alignedBear (and the early path, also gated on HTF) unreachable. On the
    remaining bars the value is the difference between two CONSECUTIVE closed HTF
    bars — a 1-HTF-bar slope, never the intended slope_len."""
    p = CvdParams()
    bars = _bars()
    out = compute_series(bars, p)

    # Rebuild the flat-held HTF series exactly as request.security() presents it.
    held = []
    cur_key = None
    last_closed = None
    pending = None
    for i, b in enumerate(bars):
        ts = datetime.fromisoformat(b["begins_at"].replace("Z", "+00:00"))
        key = int(ts.timestamp() // 60) // p.htf_minutes
        if cur_key is None:
            cur_key = key
        elif key != cur_key:
            last_closed = pending      # previous HTF bar has now closed
            cur_key = key
        pending = out["cvd_smooth"][i]
        held.append(last_closed)

    zero = 0
    total = 0
    for i in range(len(bars)):
        if held[i] is None or held[i - p.slope_len] is None or i < p.slope_len:
            continue
        total += 1
        if (held[i] - held[i - p.slope_len]) == 0.0:
            zero += 1

    assert total > 100, "not enough comparable bars to make the point"
    frac = zero / total
    assert frac > 0.6, (
        f"expected the original chart-indexed HTF slope to be 0 on most bars, "
        f"got {frac:.1%}")
    print(f"PASS (BUG 1 reproduced): original chart-indexed HTF slope == 0.0 on "
          f"{frac:.1%} of bars → on those bars htfBull/htfBear are both false, so "
          f"no signal of any kind could fire")


def test_bug1_fixed_htf_slope_lives_in_htf_space():
    """The fixed engine measures the HTF slope between COMPLETED HTF buckets, so
    it is non-zero on a real fraction of bars and aligned signals can fire."""
    bars = _bars()
    out = compute_series(bars)
    nonzero = sum(1 for v in out["htf_n"] if v not in (None, 0.0))
    total = sum(1 for v in out["htf_n"] if v is not None)
    assert total > 0
    frac = nonzero / total
    assert frac > 0.4, f"HTF confirmation available on only {frac:.1%} of bars"
    entries = [e for e in out["event"] if e in ("ENTER_LONG", "ENTER_SHORT")]
    assert len(entries) > 0, "fixed engine still produces no entries"
    print(f"PASS (BUG 1 fixed): HTF confirmation live on {frac:.1%} of bars, "
          f"{len(entries)} entries produced")


def test_bug1_htf_slope_never_measured_across_a_reset():
    """A slope comparing post-reset CVD against pre-reset CVD is meaningless.
    The first bar of each session must have no HTF confirmation at all (no
    same-session bucket has closed yet), so it can never trade."""
    bars = _bars()
    out = compute_series(bars)
    day_of = [b["begins_at"][:10] for b in bars]
    first_idx = [i for i in range(len(bars)) if i == 0 or day_of[i] != day_of[i - 1]]
    assert len(first_idx) >= 5, "expected several sessions"
    for i in first_idx:
        assert out["htf_n"][i] == 0.0, (
            f"bar {i} is a session's first bar but carries an HTF read "
            f"{out['htf_n'][i]} — that can only come from across the reset")
        assert out["event"][i] not in ("ENTER_LONG", "ENTER_SHORT"), \
            f"entered on session-open bar {i} with no honest HTF confirmation"
    print(f"PASS (BUG 1 fixed): no HTF read and no entry on any of "
          f"{len(first_idx)} session-open bars")


# ─────────────────────────────────────────────────────────────────────────────
# BUG 2 — the conviction filter was a no-op at every usable setting.
# ─────────────────────────────────────────────────────────────────────────────
def test_bug2_conviction_threshold_actually_binds():
    """Under the original flat +-14/+-10/+-10 scoring, an aligned bar always
    scored >=84 (or <=16), so raising minConviction from 55 to 90 could not
    change a single signal. It must change the count now."""
    bars = _bars()
    loose = compute_series(bars, CvdParams(min_conviction=55))
    tight = compute_series(bars, CvdParams(min_conviction=90))
    n_loose = sum(1 for e in loose["event"] if e in ("ENTER_LONG", "ENTER_SHORT"))
    n_tight = sum(1 for e in tight["event"] if e in ("ENTER_LONG", "ENTER_SHORT"))
    assert n_loose > 0, "no entries at all at min_conviction=55"
    assert n_tight < n_loose, (
        f"min_conviction is still a no-op: {n_loose} entries at 55 vs "
        f"{n_tight} at 90")
    print(f"PASS (BUG 2 fixed): min_conviction binds — {n_loose} entries at 55, "
          f"{n_tight} at 90")


def test_bug2_score_is_continuous_not_bimodal():
    """The original score could only land in [0,16] or [84,100] on any bar where
    flow/price/HTF all had a sign. A continuous score must populate the middle."""
    bars = _bars()
    out = compute_series(bars)
    scores = [s for s in out["score"] if s is not None]
    assert len(scores) > 200
    middle = [s for s in scores if 25.0 < s < 75.0]
    frac = len(middle) / len(scores)
    assert frac > 0.3, f"only {frac:.1%} of scores land mid-range — still bimodal"
    print(f"PASS (BUG 2 fixed): {frac:.1%} of conviction scores land in "
          f"(25,75) — the range the original could never produce")


# ─────────────────────────────────────────────────────────────────────────────
# BUG 3 — strength divided a CHANGE by the stdev of a LEVEL.
# ─────────────────────────────────────────────────────────────────────────────
def test_bug3_strength_normalized_in_slope_units():
    """The original computed abs(cvdSlope) / stdev(cvdS, 30) — a 3-bar change
    over the stdev of the cumulative level. Show that ratio is tiny (so
    min(strength*7, 14) never approached its cap and the strength term was dead
    weight), while the fixed slope-over-slope-stdev normalization reaches real
    sigma values."""
    p = CvdParams()
    bars = _bars()
    out = compute_series(bars, p)

    old_ratios = []
    for i in range(p.stdev_len, len(bars)):
        level_win = [v for v in out["cvd_smooth"][i - p.stdev_len + 1:i + 1] if v is not None]
        sd_level = _stdev(level_win)
        if sd_level > 0:
            old_ratios.append(abs(out["cvd_slope"][i]) / sd_level)
    assert old_ratios
    old_med = sorted(old_ratios)[len(old_ratios) // 2]
    old_capped = sum(1 for r in old_ratios if min(r * 7.0, 14.0) >= 14.0) / len(old_ratios)

    new_strength = [abs(v) for v in out["flow_n"] if v is not None]
    new_med = sorted(new_strength)[len(new_strength) // 2]

    assert old_med < 0.5, (
        f"expected the original level-normalized strength to be small, got "
        f"median {old_med:.3f}")
    assert old_capped < 0.05, (
        f"original strength term reached its +-14 cap on {old_capped:.1%} of bars")
    assert new_med > old_med, (
        f"fixed normalization ({new_med:.3f}) is not larger than the broken one "
        f"({old_med:.3f})")
    print(f"PASS (BUG 3 fixed): original strength median {old_med:.3f} (cap hit "
          f"{old_capped:.2%} of bars) → slope-normalized median {new_med:.3f}")


# ─────────────────────────────────────────────────────────────────────────────
# BUG 4 — the smoothed CVD carried across every session reset.
# ─────────────────────────────────────────────────────────────────────────────
def test_bug4_smoothing_reseeds_on_reset_and_no_signal_until_warm():
    """Day 1 closes with a large positive CVD; day 2's first bar is mildly
    negative. If the EMA were not re-seeded (the original bug) the first bars of
    day 2 would inherit day 1's level and show a huge artificial slope."""
    p = CvdParams()
    bars = []
    d1 = datetime(2026, 7, 1, 13, 30, tzinfo=timezone.utc)
    for b in range(SESSION_BARS):           # day 1: strong steady buying
        t = d1 + timedelta(minutes=BAR_MIN * b)
        bars.append({"begins_at": t.isoformat().replace("+00:00", "Z"),
                     "high": 101.0, "low": 100.0, "close": 100.95,
                     "volume": 1_000_000})
    d2 = datetime(2026, 7, 2, 13, 30, tzinfo=timezone.utc)
    for b in range(SESSION_BARS):           # day 2: mild selling
        t = d2 + timedelta(minutes=BAR_MIN * b)
        bars.append({"begins_at": t.isoformat().replace("+00:00", "Z"),
                     "high": 101.0, "low": 100.0, "close": 100.4,
                     "volume": 1_000_000})

    out = compute_series(bars, p)
    first_d2 = SESSION_BARS
    expected_seed = bar_delta(101.0, 100.0, 100.4, 1_000_000)

    assert abs(out["cvd"][first_d2] - expected_seed) < 1e-6, \
        "CVD did not reset at the session boundary"
    assert abs(out["cvd_smooth"][first_d2] - expected_seed) < 1e-6, (
        f"smoothed CVD at the first bar of day 2 is "
        f"{out['cvd_smooth'][first_d2]:.1f}, not the re-seeded "
        f"{expected_seed:.1f} — it inherited day 1's level (BUG 4)")
    assert out["cvd_smooth"][first_d2 - 1] > 10 * abs(expected_seed), \
        "day 1 did not actually build a large CVD, so the test proves nothing"

    for i in range(first_d2, first_d2 + p.slope_len + 1):
        assert out["event"][i] not in ("ENTER_LONG", "ENTER_SHORT"), \
            f"traded at bar {i}, within slope_len of the reset"
    print(f"PASS (BUG 4 fixed): smoothed CVD re-seeded to {expected_seed:.0f} at "
          f"the reset (day 1 ended at {out['cvd_smooth'][first_d2-1]:.0f}); no "
          f"entry inside the first {p.slope_len + 1} bars of the session")


# ─────────────────────────────────────────────────────────────────────────────
# BUG 5 — exits were not position-aware and not edge-gated.
# ─────────────────────────────────────────────────────────────────────────────
def test_bug5_exits_only_occur_while_a_position_is_open():
    bars = _bars(sessions=12, seed=11)
    out = compute_series(bars)
    open_dir = None
    for i, ev in enumerate(out["event"]):
        if ev in ("ENTER_LONG", "ENTER_SHORT"):
            assert open_dir is None, f"entry at bar {i} while already in a position"
            open_dir = "long" if ev == "ENTER_LONG" else "short"
        elif ev in ("EXIT_STOP", "EXIT_TARGET", "EXIT_FLIP"):
            assert open_dir is not None, f"exit event {ev} at bar {i} while FLAT"
            open_dir = None
    exits = sum(1 for e in out["event"] if e in ("EXIT_STOP", "EXIT_TARGET", "EXIT_FLIP"))
    assert exits > 0, "no exits exercised"
    print(f"PASS (BUG 5 fixed): {exits} exits, every one of them paired to an "
          f"open position; no exit ever emitted while flat")


def test_bug5_one_position_at_a_time_and_cooldown_respected():
    p = CvdParams(cooldown_bars=3)
    bars = _bars(sessions=12, seed=11)
    out = compute_series(bars, p)
    last_exit = None
    for i, ev in enumerate(out["event"]):
        if ev in ("EXIT_STOP", "EXIT_TARGET", "EXIT_FLIP"):
            last_exit = i
        elif ev in ("ENTER_LONG", "ENTER_SHORT") and last_exit is not None:
            assert i - last_exit > p.cooldown_bars, (
                f"entered at bar {i}, only {i - last_exit} bars after the exit at "
                f"{last_exit} (cooldown={p.cooldown_bars})")
    print(f"PASS (BUG 5/7 fixed): cooldown of {p.cooldown_bars} bars honoured "
          f"after every exit")


# ─────────────────────────────────────────────────────────────────────────────
# BUG 7 — risk container: ATR stop, R-multiple target.
# ─────────────────────────────────────────────────────────────────────────────
def test_bug7_stop_and_target_are_atr_derived_and_exits_are_consistent():
    p = CvdParams(stop_atr=1.5, target_r=2.0)
    bars = _bars(sessions=12, seed=11)
    out = compute_series(bars, p)
    trades = out["trades"]
    assert trades, "no trades to check"
    for t in trades:
        risk = abs(t["entry_price"] - t["stop_price"])
        reward = abs(t["target_price"] - t["entry_price"])
        assert risk > 0
        assert abs(reward / risk - p.target_r) < 1e-6, \
            f"target is {reward/risk:.3f}R, expected {p.target_r}R"
        if t["exit_reason"] == "EXIT_STOP":
            assert (t["exit_price"] <= t["stop_price"] if t["direction"] == "long"
                    else t["exit_price"] >= t["stop_price"]), t
        if t["exit_reason"] == "EXIT_TARGET":
            assert (t["exit_price"] >= t["target_price"] if t["direction"] == "long"
                    else t["exit_price"] <= t["target_price"]), t
    print(f"PASS (BUG 7 fixed): all {len(trades)} trades carry an ATR stop and a "
          f"{p.target_r}R target consistent with their exit reason")


# ─────────────────────────────────────────────────────────────────────────────
# Causality — the strongest guard against the class of bug that made the
# original repaint (BUG 6). Nothing about bar i may depend on bar i+1.
# ─────────────────────────────────────────────────────────────────────────────
def test_no_lookahead_prefix_stability():
    bars = _bars(sessions=10, seed=3)
    full = compute_series(bars)
    for cut in (200, 400, 600):
        part = compute_series(bars[:cut])
        for key in ("cvd", "cvd_smooth", "score", "flow_n", "htf_n", "price_n",
                    "event", "live_signal"):
            for i in range(cut):
                a, b = full[key][i], part[key][i]
                if isinstance(a, float) and isinstance(b, float):
                    assert abs(a - b) < 1e-9, f"{key}[{i}] changed: {a} vs {b}"
                else:
                    assert a == b, f"{key}[{i}] changed: {a!r} vs {b!r}"
    print("PASS (BUG 6 guard): truncating the series leaves every earlier bar "
          "byte-identical — no lookahead anywhere")


# ─────────────────────────────────────────────────────────────────────────────
# Live-signal mapping (house convention) + honest degradation.
# ─────────────────────────────────────────────────────────────────────────────
def test_live_signal_mapping_matches_house_convention():
    bars = _bars(sessions=12, seed=11)
    out = compute_series(bars)
    seen = {"long_exit_sell": 0, "short_exit_none": 0}
    open_dir = None
    for i, ev in enumerate(out["event"]):
        sig = out["live_signal"][i]
        if ev == "ENTER_LONG":
            assert sig == "BUY", f"ENTER_LONG at {i} emitted {sig!r}"
            open_dir = "long"
        elif ev == "ENTER_SHORT":
            assert sig == "SELL", f"ENTER_SHORT at {i} emitted {sig!r}"
            open_dir = "short"
        elif ev in ("EXIT_STOP", "EXIT_TARGET", "EXIT_FLIP"):
            if open_dir == "long":
                assert sig == "SELL", f"long exit at {i} emitted {sig!r}, expected SELL"
                seen["long_exit_sell"] += 1
            else:
                assert sig is None, (
                    f"short exit at {i} emitted {sig!r} — iam_executor has no "
                    f"'close an existing put' action, so this must stay None")
                seen["short_exit_none"] += 1
            open_dir = None
        else:
            assert sig is None, f"non-event bar {i} emitted {sig!r}"
    assert seen["long_exit_sell"] > 0 and seen["short_exit_none"] > 0, seen
    assert all(s in (None, "BUY", "SELL") for s in out["live_signal"])
    print(f"PASS: live_signal mapping correct — {seen['long_exit_sell']} long "
          f"exits emit SELL, {seen['short_exit_none']} short exits emit nothing "
          f"by design")


def test_analyze_reports_insufficient_data_rather_than_guessing():
    p = CvdParams()
    for n in (0, 5, 20):
        res = analyze("TEST", _bars(sessions=1)[:n], p)
        assert res["status"] == "insufficient_data", (n, res)
        assert "min_bars" in res
    full = analyze("TEST", _bars(sessions=6), p)
    assert full["status"] == "success", full
    for key in ("regime", "conviction", "bias", "components", "position",
                "params", "disclosure"):
        assert key in full, f"analyze() missing {key}"
    assert 0.0 <= full["conviction"] <= 100.0
    assert full["bias"] in ("CALL", "PUT", "EARLY CALL", "EARLY PUT", "WAIT")
    assert "proxy" in full["disclosure"].lower(), \
        "the CVD-proxy disclosure must travel with the payload"
    print(f"PASS: analyze() degrades honestly on short data and returns the "
          f"documented shape on real data (regime={full['regime']}, "
          f"conviction={full['conviction']})")


def test_flat_market_produces_no_signals():
    """A dead-flat series has zero range, so every bar's delta proxy is 0 and no
    conviction can be manufactured."""
    bars = []
    t0 = datetime(2026, 7, 1, 13, 30, tzinfo=timezone.utc)
    for b in range(SESSION_BARS * 4):
        t = t0 + timedelta(minutes=BAR_MIN * b)
        bars.append({"begins_at": t.isoformat().replace("+00:00", "Z"),
                     "high": 100.0, "low": 100.0, "close": 100.0, "volume": 500_000})
    out = compute_series(bars)
    assert not out["trades"], f"flat market produced {len(out['trades'])} trades"
    assert all(e is None for e in out["event"])
    print("PASS: dead-flat market produces no trades and no events")


if __name__ == "__main__":
    test_bug1_original_htf_slope_is_zero_on_most_bars()
    test_bug1_fixed_htf_slope_lives_in_htf_space()
    test_bug1_htf_slope_never_measured_across_a_reset()
    test_bug2_conviction_threshold_actually_binds()
    test_bug2_score_is_continuous_not_bimodal()
    test_bug3_strength_normalized_in_slope_units()
    test_bug4_smoothing_reseeds_on_reset_and_no_signal_until_warm()
    test_bug5_exits_only_occur_while_a_position_is_open()
    test_bug5_one_position_at_a_time_and_cooldown_respected()
    test_bug7_stop_and_target_are_atr_derived_and_exits_are_consistent()
    test_no_lookahead_prefix_stability()
    test_live_signal_mapping_matches_house_convention()
    test_analyze_reports_insufficient_data_rather_than_guessing()
    test_flat_market_produces_no_signals()
    print("\nAll tests passed (code correctness only — NOT a profitability claim). "
          "See docs/CVD_REGIME_BACKTEST_2026-07-30.md for the real verdict.")
