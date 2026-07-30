"""
Before/after signal-frequency measurement on REAL bars: the operator-submitted
"CVD Regime Fast -> Call/Put Desk" script as written, versus the corrected
cvd_regime_engine.py.

WHY THIS EXISTS: the BUG 1 claim (the HTF slope was indexed on chart bars, so it
was structurally zero most of the time and blocked signals) is proved
mechanically on synthetic bars in tests/test_cvd_regime_engine_smoke.py. This
file measures what it actually cost on REAL market data — how many signals the
submitted script would have fired over the same window the backtest ran on.

`_original_signals()` reproduces the submitted script faithfully:
  * no EMA re-seed on the daily CVD reset (BUG 4 present)
  * cvdSlope = cvdS - cvdS[slopeLen] straddling session boundaries (BUG 4)
  * htfCvdS held flat at the last CLOSED 60m value, slope indexed on CHART bars
    (BUG 1 present — this is exactly what request.security() presents)
  * strength = abs(cvdSlope) / stdev(cvdS, 30)  (BUG 3 present)
  * flat +-14 / +-10 / +-10 scoring off a base of 50 (BUG 2 present)
  * the original toCall/toPut rising-edge logic

Two knowingly-inexact details, called out rather than glossed: Pine's ta.ema()
seeds from an SMA of the first `length` values (this seeds from the first value),
and Pine's ta.stdev() is population where this uses sample. Neither shifts a
signal count materially — the effect being measured is whole bars where the HTF
term is exactly 0.0.

Usage: python tests/compare_cvd_original_vs_fixed.py data/*.csv
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cvd_regime_engine import (  # noqa: E402
    compute_series, CvdParams, bar_delta, _bar_dt, _reset_key, _htf_key, _stdev,
)
from tests.backtest_cvd_regime import load_csv  # noqa: E402


def _original_signals(bars: list, p: CvdParams) -> dict:
    """The submitted script, as submitted. Returns its signal counts."""
    n = len(bars)
    cvd = 0.0
    ema_cvd = None
    ema_px = None
    prev_rkey = None
    smooth = []          # cvdS history, NEVER cleared (no reset awareness)
    held = []            # htfCvdS as request.security() presents it
    cur_htf = None
    pending = None
    last_closed = None
    k_cvd = 2.0 / (p.smooth_len + 1.0)
    k_px = 2.0 / (p.ema_len + 1.0)

    call_prev = put_prev = early_call_prev = early_put_prev = False
    to_call = to_put = 0
    htf_zero = 0
    htf_total = 0

    for i, b in enumerate(bars):
        high = float(b["high"]); low = float(b["low"])
        close = float(b["close"]); vol = float(b["volume"])
        dt = _bar_dt(b, i)
        rkey = _reset_key(dt, p.reset_period)
        do_reset = rkey is not None and prev_rkey is not None and rkey != prev_rkey
        prev_rkey = rkey if rkey is not None else prev_rkey

        d = bar_delta(high, low, close, vol)
        cvd = d if do_reset else cvd + d
        # BUG 4: the EMA is NOT re-seeded on reset
        ema_cvd = cvd if ema_cvd is None else ema_cvd + k_cvd * (cvd - ema_cvd)
        smooth.append(ema_cvd)

        # BUG 4: slope straddles the session boundary
        slope = ema_cvd - smooth[-1 - p.slope_len] if len(smooth) > p.slope_len else 0.0

        # BUG 1: held-flat HTF value, slope indexed on CHART bars
        hkey = _htf_key(dt, p.htf_minutes)
        if cur_htf is None:
            cur_htf = hkey
        elif hkey != cur_htf:
            last_closed = pending
            cur_htf = hkey
        pending = ema_cvd
        held.append(last_closed)
        htf_slope = 0.0
        if len(held) > p.slope_len and held[-1] is not None and held[-1 - p.slope_len] is not None:
            htf_slope = held[-1] - held[-1 - p.slope_len]
            htf_total += 1
            if htf_slope == 0.0:
                htf_zero += 1

        ema_px = close if ema_px is None else ema_px + k_px * (close - ema_px)

        # BUG 3: change divided by the stdev of the LEVEL
        sd_level = _stdev(smooth[-p.stdev_len:])
        strength = abs(slope) / sd_level if sd_level > 0 else 0.0

        flow_bull, flow_bear = slope > 0, slope < 0
        px_bull, px_bear = close > ema_px, close < ema_px
        htf_bull, htf_bear = htf_slope > 0, htf_slope < 0

        aligned_bull = flow_bull and px_bull and htf_bull
        aligned_bear = flow_bear and px_bear and htf_bear
        divergence = (flow_bull and px_bear) or (flow_bear and px_bull)

        # BUG 2: flat contributions
        score = 50.0
        score += 14.0 if flow_bull else -14.0 if flow_bear else 0.0
        score += 10.0 if px_bull else -10.0 if px_bear else 0.0
        score += 10.0 if htf_bull else -10.0 if htf_bear else 0.0
        score += min(strength * 7.0, 14.0) * (1.0 if flow_bull else -1.0 if flow_bear else 0.0)
        score += -16.0 if divergence else 0.0
        score = max(0.0, min(100.0, score))

        call_sig = aligned_bull and score >= p.min_conviction
        put_sig = aligned_bear and score <= (100 - p.min_conviction)
        early_call = p.use_early and flow_bull and htf_bull and score >= p.min_conviction - 8
        early_put = p.use_early and flow_bear and htf_bear and score <= (100 - p.min_conviction) + 8

        if (call_sig and not call_prev) or (early_call and not early_call_prev and not call_sig):
            to_call += 1
        if (put_sig and not put_prev) or (early_put and not early_put_prev and not put_sig):
            to_put += 1
        call_prev, put_prev = call_sig, put_sig
        early_call_prev, early_put_prev = early_call, early_put

    return {"to_call": to_call, "to_put": to_put, "total": to_call + to_put,
            "htf_zero_pct": round(100.0 * htf_zero / htf_total, 1) if htf_total else None}


def main(paths: list):
    p = CvdParams()
    print(f"{'SYM':<6}{'BARS':>6} | {'ORIGINAL (as submitted)':<40} | {'FIXED':<22}")
    print(f"{'':<6}{'':>6} | {'toCall':>7}{'toPut':>7}{'total':>7}{'HTFslope=0':>12} | "
          f"{'entries':>8}{'trades':>8}")
    print("-" * 90)
    tot_o = tot_f = 0
    for path in paths:
        sym = os.path.basename(path).split("_")[0].upper()
        bars = load_csv(path)
        o = _original_signals(bars, p)
        out = compute_series(bars, p)
        entries = sum(1 for e in out["event"] if e in ("ENTER_LONG", "ENTER_SHORT"))
        tot_o += o["total"]
        tot_f += entries
        print(f"{sym:<6}{len(bars):>6} | {o['to_call']:>7}{o['to_put']:>7}{o['total']:>7}"
              f"{str(o['htf_zero_pct']) + '%':>12} | {entries:>8}{len(out['trades']):>8}")
    print("-" * 90)
    print(f"{'ALL':<6}{'':>6} | {'':>14}{tot_o:>7}{'':>12} | {tot_f:>8}")
    print("\nNOTE: signal COUNT is not signal QUALITY, and the direction of the "
          "difference is\nnot the point. The original emits MORE signals, because its "
          "conviction gate was\ninert (BUG 2) and it had no position state or cooldown "
          "(BUG 5/7) — so every\nre-arming of a loose early condition counted, including "
          "while already in a trade.\nIts signals were also confined to a burst after "
          "each hourly close (BUG 1). The\noriginal has NO exit logic at all, so no P&L "
          "can be computed for it — that is why\nthis compares counts, not returns. "
          "Whether the FIXED signals make money is a\nseparate question, answered in "
          "docs/CVD_REGIME_BACKTEST_2026-07-30.md: they do not,\non the window tested.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    main(sys.argv[1:])
