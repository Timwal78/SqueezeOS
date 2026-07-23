"""
DRUCK-LB v7 BeastMode Engine — Python port of the operator-supplied
"DRUCK-LB v7 BeastMode - Full Portfolio (IWM Added)" Pine v6 strategy.
============================================================================================
Same convention as druck_engine.py / imo_engine.py / orb_engine.py: one Python
implementation of the signal math, reused by both the backtest harness and any
future on-demand/live wiring — no drift between "what the Pine script says" and
"what actually runs."

This is a DIFFERENT, SIMPLER strategy than indicators/SML_Druckenmiller_Liquidity_
Breakout_v6.pine (no regime/percentrank/mean-reversion mode, no pyramiding) — kept
as its own module rather than folded into druck_engine.py.

Reuses the shared Ema/WilderRMA/AdxDmi primitives from druck_engine.py (same
Wilder/RMA conventions already established there).

── AUDIT FINDING (not a silent fix — read before trusting any TradingView
   Strategy Tester screenshot of this script) ──────────────────────────────
The Pine script calls `strategy.exit("Exit Long", "Beast Long", stop=..., limit=...,
trail_points=...)` UNCONDITIONALLY on every bar, with stop/limit computed from
THAT BAR'S close and ATR:
    stop=close * (1 - atrStopMult * atrVal / close), limit=close * (1 + rrRatio *
    atrStopMult * atrVal / close)
Per TradingView's own docs, calling strategy.exit() again for the same id UPDATES
the pending order's stop/limit levels rather than creating a new one. That means
the "stop" and "target" are NOT fixed relative to the entry price the way the
input names ("ATR Stop Mult", "Risk:Reward") suggest — they ratchet to track
whatever the CURRENT close and CURRENT ATR are, every single bar, for as long as
the position stays open. This is very likely an unintended side effect of not
gating the strategy.exit() call to fire once at entry (e.g. inside a
`barsSinceEntry == 0` check), not a deliberate "moving bracket" design.

This port implements the ECONOMICALLY INTENDED reading instead: stop and target
fixed at entry using ATR-at-entry (standard R:R bracket, matching the input
names), plus a ratcheting ATR trailing stop that only ever tightens in the
trade's favor — the same convention already used by druck_engine.py /
tests/backtest_druck.py's simulate() for the v6 script. Treat any comparison
between this port's backtest output and a live TradingView Strategy Tester
screenshot of the ORIGINAL script as intended-strategy vs. as-actually-executed
— not an apples-to-apples reproduction of that exact screenshot's numbers.

── Second finding: HTF direction ─────────────────────────────────────────────
The script requests "120" (2-hour) as its "HTF" via request.security while the
operator runs it on a 4-hour chart per the supplied screenshot — i.e. the
"higher" timeframe requested is actually LOWER resolution than the chart it's
displayed on. Ported faithfully as coded (a real, if unusually-named, 2H-bucket
EMA sampled at each base-timeframe bar), not "corrected" to be genuinely higher
than the base timeframe — that would be a different filter than what produced
the screenshot.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from druck_engine import Ema, WilderRMA, AdxDmi, _bar_val, _bar_time  # noqa: F401 shared primitives


@dataclass
class DruckV7Params:
    adx_len: int = 22
    adx_trend: float = 22.0
    breakout_len: int = 15
    ema_fast: int = 8
    ema_slow: int = 21
    atr_len: int = 14
    atr_stop_mult: float = 1.5
    trail_atr_mult: float = 2.5
    rr_ratio: float = 2.5
    use_htf: bool = True
    htf_minutes: int = 120
    vol_mult: float = 1.8
    vol_avg_len: int = 20
    commission_pct: float = 0.04  # strategy.commission.percent, per side

    @classmethod
    def from_env(cls) -> "DruckV7Params":
        def f(k, d):
            try: return float(os.environ.get(k, d))
            except Exception: return d
        def i(k, d):
            try: return int(os.environ.get(k, d))
            except Exception: return d
        def b(k, d):
            return os.environ.get(k, str(d)).strip().lower() in ("true", "1", "yes")
        return cls(
            adx_len=i("DRUCKV7_ADX_LEN", 22), adx_trend=f("DRUCKV7_ADX_TREND", 22.0),
            breakout_len=i("DRUCKV7_BREAKOUT_LEN", 15),
            ema_fast=i("DRUCKV7_EMA_FAST", 8), ema_slow=i("DRUCKV7_EMA_SLOW", 21),
            atr_len=i("DRUCKV7_ATR_LEN", 14),
            atr_stop_mult=f("DRUCKV7_ATR_STOP_MULT", 1.5),
            trail_atr_mult=f("DRUCKV7_TRAIL_ATR_MULT", 2.5),
            rr_ratio=f("DRUCKV7_RR_RATIO", 2.5),
            use_htf=b("DRUCKV7_USE_HTF", True), htf_minutes=i("DRUCKV7_HTF_MINUTES", 120),
            vol_mult=f("DRUCKV7_VOL_MULT", 1.8), vol_avg_len=i("DRUCKV7_VOL_AVG_LEN", 20),
            commission_pct=f("DRUCKV7_COMMISSION_PCT", 0.04),
        )


def _resample_htf_single_ema(bars: list, htf_minutes: int, ema_len: int) -> list:
    """
    Per-base-bar HTF EMA(ema_len) of close, sampled from htf_minutes buckets,
    using only the LAST FULLY CLOSED bucket strictly before the base bar's own
    bucket — mirrors request.security(..., lookahead=barmerge.lookahead_off).
    Same bucket-completion convention as druck_engine._resample_htf /
    _htf_ema_series, specialized to a single EMA length (v7 only needs
    htfEMA = ema(close, fastLen) on the HTF, not a fast/slow pair).
    """
    buckets: list = []
    cur_key = None
    cur_close = None
    for bar in bars:
        t = _bar_time(bar)
        c = _bar_val(bar, "close", "c")
        if t is None:
            continue
        epoch_min = int(t.timestamp() // 60)
        key = epoch_min - (epoch_min % htf_minutes)
        if cur_key is None:
            cur_key = key
        elif key != cur_key:
            buckets.append((cur_key, cur_close))
            cur_key = key
        cur_close = c

    ema = Ema(ema_len)
    ema_by_bucket: dict = {}
    for key, close in buckets:
        ema_by_bucket[key] = ema.update(close)

    sorted_keys = sorted(ema_by_bucket.keys())
    result = []
    last_idx = -1
    for bar in bars:
        t = _bar_time(bar)
        if t is None:
            result.append(None)
            continue
        epoch_min = int(t.timestamp() // 60)
        key = epoch_min - (epoch_min % htf_minutes)
        while last_idx + 1 < len(sorted_keys) and sorted_keys[last_idx + 1] < key:
            last_idx += 1
        result.append(ema_by_bucket[sorted_keys[last_idx]] if last_idx >= 0 else None)
    return result


def compute_series(bars: list, p: DruckV7Params = None) -> dict:
    """
    bars: chronological list of dicts with open/high/low/close/volume (o/h/l/c/v
    accepted) and a date/timestamp field for HTF resampling.

    Returns {"signals": [None|"BUY"|"SELL"] per bar, "atr": [float] per bar}.
    No position/exit state machine here — see tests/backtest_druck_lb_v7.py's
    simulate(), same separation of concerns as druck_engine.compute_series.
    """
    p = p or DruckV7Params.from_env()

    ema_f, ema_s = Ema(p.ema_fast), Ema(p.ema_slow)
    adx_dmi = AdxDmi(p.adx_len)
    atr_rma = WilderRMA(p.atr_len)

    htf_series = _resample_htf_single_ema(bars, p.htf_minutes, p.ema_fast) if p.use_htf else [None] * len(bars)

    highs: list = []
    lows: list = []
    closes: list = []
    vols: list = []
    hh_hist: list = []
    ll_hist: list = []
    atr_series: list = [None] * len(bars)

    signals: list = [None] * len(bars)

    for i, bar in enumerate(bars):
        h = _bar_val(bar, "high", "h")
        l = _bar_val(bar, "low", "l")
        c = _bar_val(bar, "close", "c")
        v = _bar_val(bar, "volume", "v")
        if c <= 0:
            continue

        prev_close = closes[-1] if closes else c
        di_plus, di_minus, adx = adx_dmi.update(h, l, c)
        tr = max(h - l, abs(h - prev_close), abs(l - prev_close))
        atr = atr_rma.update(tr)
        atr_series[i] = atr

        f = ema_f.update(c)
        s = ema_s.update(c)

        htf_f = htf_series[i]
        htf_up = (not p.use_htf) or (htf_f is not None and htf_f > f)
        htf_down = (not p.use_htf) or (htf_f is not None and htf_f < f)
        if p.use_htf and htf_f is None:
            # No HTF bucket has closed yet — matches Pine's na comparisons (false)
            htf_up = htf_down = False

        trend_up = f > s and htf_up
        trend_down = f < s and htf_down

        # ta.crossover(close, highest(high, breakLen)[1]) needs BOTH legs of the
        # shifted hh series (same two-bar-lookback reasoning as druck_engine.py's
        # breakout port — hh[1] is a series, not a constant).
        prior_hh = hh_hist[-1] if hh_hist else None
        prior_prior_hh = hh_hist[-2] if len(hh_hist) >= 2 else None
        prior_ll = ll_hist[-1] if ll_hist else None
        prior_prior_ll = ll_hist[-2] if len(ll_hist) >= 2 else None

        highs.append(h); lows.append(l)
        hh = max(highs[-p.breakout_len:]) if len(highs) >= p.breakout_len else None
        ll = min(lows[-p.breakout_len:]) if len(lows) >= p.breakout_len else None
        hh_hist.append(hh)
        ll_hist.append(ll)

        vols.append(v)
        vol_window = vols[-p.vol_avg_len:]
        vol_avg = sum(vol_window) / len(vol_window)
        vol_ok = v > vol_avg * p.vol_mult

        long_break = (
            prior_hh is not None and prior_prior_hh is not None
            and c > prior_hh and prev_close <= prior_prior_hh and vol_ok
        )
        short_break = (
            prior_ll is not None and prior_prior_ll is not None
            and c < prior_ll and prev_close >= prior_prior_ll and vol_ok
        )

        long_signal = adx > p.adx_trend and trend_up and long_break
        short_signal = adx > p.adx_trend and trend_down and short_break

        if long_signal and not short_signal:
            signals[i] = "BUY"
        elif short_signal and not long_signal:
            signals[i] = "SELL"
        elif long_signal and short_signal:
            # Structurally near-impossible (breakout up and down on the same
            # bar) — Pine's two independent `if` blocks would leave the
            # last-executed (short) as final state, mirrored here.
            signals[i] = "SELL"

        closes.append(c)

    return {"signals": signals, "atr": atr_series}


def analyze(symbol: str, bars: list, p: DruckV7Params = None) -> dict:
    """On-demand analysis of the latest bar. Real bars only."""
    p = p or DruckV7Params.from_env()
    min_bars = max(p.breakout_len, p.ema_slow, p.adx_len, p.vol_avg_len, p.atr_len) + 10
    if not bars or len(bars) < min_bars:
        return {"symbol": symbol.upper(), "status": "insufficient_data",
                "bars": len(bars or []), "min_bars": min_bars}
    out = compute_series(bars, p)
    return {
        "symbol": symbol.upper(), "status": "success",
        "signal": out["signals"][-1],
        "atr": out["atr"][-1],
        "price": _bar_val(bars[-1], "close", "c"),
    }
