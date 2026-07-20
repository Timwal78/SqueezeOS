"""
SML-DRUCK Engine — Python port of indicators/SML_Druckenmiller_Liquidity_Breakout_v6.pine
============================================================================================
Single source of truth for the DRUCK-LB math, same convention as imo_engine.py and
orb_engine.py (Pine script is a visual of the same logic; this is what backtest_druck.py
and any future live-execution wiring both run against — no drift between chart and code).

Every block below is commented with the Pine script line range it mirrors. Indicator
math (ADX/DMI, ATR, EMA) reuses the same Wilder/RMA conventions already established in
imo_engine.py's Ema class and Wilder-ATR block.

Ported from indicators/SML_Druckenmiller_Liquidity_Breakout_v6.pine v6.4 as of 2026-07-20.

Known implementation-detail assumption (flagged, not hidden): Pine's ta.percentrank(source,
length) is implemented here as "count of the trailing `length` bars (including current)
whose value is strictly less than the current value, divided by length, times 100" — the
standard, widely-documented definition. If TradingView's exact tie-handling differs at the
margin, it would only matter on bars where atr is EXACTLY tied with a historical value,
which is a measure-zero case for a continuous series like ATR — not expected to materially
change backtest results, but noted here rather than asserted as verified against the real
Pine runtime (no network access to confirm against TradingView from this environment).

HTF (higher-timeframe) alignment: request.security(..., lookahead=barmerge.lookahead_off)
means each base-timeframe bar sees the LAST CONFIRMED (fully closed) higher-timeframe bar's
EMA values, never the currently-forming one. _resample_htf() below reproduces that: a base
bar only gets HTF EMA values once the HTF bucket it belongs to has been fully closed by a
later base bar.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


# ── Params (mirrors the Pine `input.*` block, lines 44-86) ────────────────────────────

@dataclass
class DruckParams:
    adx_len: int = 14
    adx_trend: float = 25.0
    atr_len: int = 14
    atr_pctile_len: int = 100
    atr_vol_pct: float = 85.0

    breakout_len: int = 20
    ema_fast: int = 9
    ema_slow: int = 20
    volume_filter: bool = True
    vol_mult: float = 1.5
    range_zscore: float = 2.0

    risk_pct: float = 1.0
    jug_risk_pct: float = 3.0
    rr_ratio: float = 3.0
    atr_stop_mult: float = 2.0
    trail_atr_mult: float = 3.0

    max_pyramids: int = 3
    pyramid_trigger: float = 1.0

    use_dxy: bool = False
    dxy_sma_len: int = 50
    use_higher_trend: bool = True
    htf_minutes: int = 120  # matches Pine default input.timeframe("120", ...)

    @classmethod
    def from_env(cls) -> "DruckParams":
        def f(k, d):
            try: return float(os.environ.get(k, d))
            except Exception: return d
        def i(k, d):
            try: return int(os.environ.get(k, d))
            except Exception: return d
        def b(k, d):
            return os.environ.get(k, str(d)).strip().lower() in ("true", "1", "yes")
        return cls(
            adx_len=i("DRUCK_ADX_LEN", 14), adx_trend=f("DRUCK_ADX_TREND", 25.0),
            atr_len=i("DRUCK_ATR_LEN", 14), atr_pctile_len=i("DRUCK_ATR_PCTILE_LEN", 100),
            atr_vol_pct=f("DRUCK_ATR_VOL_PCT", 85.0),
            breakout_len=i("DRUCK_BREAKOUT_LEN", 20),
            ema_fast=i("DRUCK_EMA_FAST", 9), ema_slow=i("DRUCK_EMA_SLOW", 20),
            volume_filter=b("DRUCK_VOLUME_FILTER", True), vol_mult=f("DRUCK_VOL_MULT", 1.5),
            range_zscore=f("DRUCK_RANGE_ZSCORE", 2.0),
            risk_pct=f("DRUCK_RISK_PCT", 1.0), jug_risk_pct=f("DRUCK_JUG_RISK_PCT", 3.0),
            rr_ratio=f("DRUCK_RR_RATIO", 3.0), atr_stop_mult=f("DRUCK_ATR_STOP_MULT", 2.0),
            trail_atr_mult=f("DRUCK_TRAIL_ATR_MULT", 3.0),
            max_pyramids=i("DRUCK_MAX_PYRAMIDS", 3), pyramid_trigger=f("DRUCK_PYRAMID_TRIGGER", 1.0),
            use_dxy=b("DRUCK_USE_DXY", False), dxy_sma_len=i("DRUCK_DXY_SMA_LEN", 50),
            use_higher_trend=b("DRUCK_USE_HTF", True), htf_minutes=i("DRUCK_HTF_MINUTES", 120),
        )


# ── Shared indicator primitives ─────────────────────────────────────────────────────

class Ema:
    """Same recursion as imo_engine.py's Ema — standard TradingView ta.ema()."""
    def __init__(self, length: int):
        self.k = 2.0 / (length + 1)
        self.v: Optional[float] = None

    def update(self, x: float) -> float:
        self.v = x if self.v is None else self.v + self.k * (x - self.v)
        return self.v


def _bar_val(bar: dict, *keys, default=0.0) -> float:
    for k in keys:
        v = bar.get(k)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return default


def _bar_time(bar: dict) -> Optional[datetime]:
    raw = bar.get("date") or bar.get("t") or bar.get("timestamp")
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        ts = raw / 1000.0 if raw > 1e12 else raw
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


class WilderRMA:
    """Wilder's smoothing (== ta.rma in Pine) — same recursion as imo_engine.py's
    'Wilder ATR' block, generalized for reuse in ADX/DMI below."""
    def __init__(self, length: int):
        self.length = length
        self.v: Optional[float] = None
        self._seed_buf: list = []

    def update(self, x: float) -> float:
        if self.v is None:
            self._seed_buf.append(x)
            if len(self._seed_buf) < self.length:
                # Not enough bars to seed yet — return the running simple mean as a
                # reasonable warmup value (never used for real signals since all
                # signal logic below also requires len(history) >= warmup lengths).
                self.v = sum(self._seed_buf) / len(self._seed_buf)
                return self.v
            self.v = sum(self._seed_buf) / self.length
            return self.v
        self.v = (self.v * (self.length - 1) + x) / self.length
        return self.v


class AdxDmi:
    """
    Wilder's DMI/ADX — mirrors Pine line 91: `[diPlus, diMinus, adx] = ta.dmi(adxLen, adxLen)`.
    Standard formula: +DM/-DM smoothed with Wilder's RMA, DI = 100*smoothed(DM)/ATR,
    DX = 100*|DI+ - DI-|/(DI+ + DI-), ADX = RMA(DX, len).
    """
    def __init__(self, length: int):
        self.length = length
        self.tr_rma = WilderRMA(length)
        self.plus_dm_rma = WilderRMA(length)
        self.minus_dm_rma = WilderRMA(length)
        self.dx_rma = WilderRMA(length)
        self._prev_high: Optional[float] = None
        self._prev_low: Optional[float] = None
        self._prev_close: Optional[float] = None

    def update(self, h: float, l: float, c: float) -> tuple:
        if self._prev_high is None:
            self._prev_high, self._prev_low, self._prev_close = h, l, c
            return 0.0, 0.0, 0.0

        up_move = h - self._prev_high
        down_move = self._prev_low - l
        plus_dm = up_move if (up_move > down_move and up_move > 0) else 0.0
        minus_dm = down_move if (down_move > up_move and down_move > 0) else 0.0

        tr = max(h - l, abs(h - self._prev_close), abs(l - self._prev_close))

        atr = self.tr_rma.update(tr)
        plus_smoothed = self.plus_dm_rma.update(plus_dm)
        minus_smoothed = self.minus_dm_rma.update(minus_dm)

        di_plus = 100.0 * plus_smoothed / atr if atr > 0 else 0.0
        di_minus = 100.0 * minus_smoothed / atr if atr > 0 else 0.0
        di_sum = di_plus + di_minus
        dx = 100.0 * abs(di_plus - di_minus) / di_sum if di_sum > 0 else 0.0
        adx = self.dx_rma.update(dx)

        self._prev_high, self._prev_low, self._prev_close = h, l, c
        return di_plus, di_minus, adx


def _percentrank(history: list, current: float, length: int) -> float:
    """
    ta.percentrank(source, length) — percentage of the trailing `length` bars
    (including current) strictly less than the current value. See module
    docstring for the caveat on this being the standard definition, not
    verified against the live Pine runtime from this sandbox.
    """
    window = (history + [current])[-length:]
    if len(window) < length:
        return 0.0
    less = sum(1 for v in window if v < current)
    return 100.0 * less / length


def _resample_htf(bars: list, htf_minutes: int) -> list:
    """
    Group bars into htf_minutes buckets by wall-clock time, return one dict per
    COMPLETED bucket: {"close_time": <bucket end>, "close": <last bar's close in bucket>}.
    A bucket is "completed" once a bar outside it has been seen — mirrors
    request.security's lookahead_off (never see the still-forming HTF bar).
    """
    buckets: list = []
    cur_bucket_key = None
    cur_close = None
    for bar in bars:
        t = _bar_time(bar)
        c = _bar_val(bar, "close", "c")
        if t is None:
            continue
        epoch_min = int(t.timestamp() // 60)
        bucket_key = epoch_min - (epoch_min % htf_minutes)
        if cur_bucket_key is None:
            cur_bucket_key = bucket_key
        elif bucket_key != cur_bucket_key:
            buckets.append({"bucket_key": cur_bucket_key, "close": cur_close})
            cur_bucket_key = bucket_key
        cur_close = c
    # Deliberately do NOT append the final still-forming bucket — it's never
    # "completed" within this dataset, matching lookahead_off semantics.
    return buckets


def _htf_ema_series(bars: list, p: DruckParams) -> list:
    """
    Per base bar: the (fast_ema, slow_ema) of the higher timeframe as of the
    LAST FULLY CLOSED htf bucket strictly before this base bar's own bucket.
    None until the first htf bucket has closed.
    """
    htf_closes = _resample_htf(bars, p.htf_minutes)
    fast, slow = Ema(p.ema_fast), Ema(p.ema_slow)
    # bucket_key -> (fast, slow) as of that bucket's close
    htf_ema_by_bucket: dict = {}
    for b in htf_closes:
        f = fast.update(b["close"])
        s = slow.update(b["close"])
        htf_ema_by_bucket[b["bucket_key"]] = (f, s)

    sorted_keys = sorted(htf_ema_by_bucket.keys())
    result = []
    last_completed_idx = -1
    for bar in bars:
        t = _bar_time(bar)
        if t is None:
            result.append((None, None))
            continue
        epoch_min = int(t.timestamp() // 60)
        bucket_key = epoch_min - (epoch_min % p.htf_minutes)
        # Advance to the last completed bucket strictly before this bar's own bucket
        while (last_completed_idx + 1 < len(sorted_keys)
               and sorted_keys[last_completed_idx + 1] < bucket_key):
            last_completed_idx += 1
        if last_completed_idx < 0:
            result.append((None, None))
        else:
            result.append(htf_ema_by_bucket[sorted_keys[last_completed_idx]])
    return result


# ── Main series computation (mirrors Pine lines 88-265) ────────────────────────────

def compute_series(bars: list, p: DruckParams = None) -> dict:
    """
    bars: chronological list of dicts with open/high/low/close/volume (o/h/l/c/v
    accepted) and a date/timestamp field for HTF resampling.

    Returns {"signals": [None|"BUY"|"SELL"] per bar (BUY/SELL = a fresh long/short
    ENTRY on that bar, mirrors longSignal/shortSignal), "jugular": [bool] per bar,
    "state": last bar's full indicator state}.

    No stop/target/trailing-stop/pyramid state machine here — that's simulated by
    the backtest harness (tests/backtest_druck.py), same separation of concerns as
    orb_engine.compute_series (signals) vs. tests/backtest_orb_mm.py (position sim).
    """
    p = p or DruckParams.from_env()

    ema_f, ema_s = Ema(p.ema_fast), Ema(p.ema_slow)
    adx_dmi = AdxDmi(p.adx_len)
    atr_rma = WilderRMA(p.atr_len)
    vol_avg_hist: list = []

    highs: list = []
    lows: list = []
    closes: list = []
    atr_hist: list = []
    hh_hist: list = []
    ll_hist: list = []

    htf_series = _htf_ema_series(bars, p) if p.use_higher_trend else [(None, None)] * len(bars)

    signals: list = [None] * len(bars)
    jugular: list = [False] * len(bars)
    state: dict = {}

    for i, bar in enumerate(bars):
        h = _bar_val(bar, "high", "h")
        l = _bar_val(bar, "low", "l")
        c = _bar_val(bar, "close", "c")
        v = _bar_val(bar, "volume", "v")
        if c <= 0:
            continue

        # ── Regime detection — Pine lines 91-99 ──
        di_plus, di_minus, adx = adx_dmi.update(h, l, c)
        prev_close = closes[-1] if closes else c
        tr = max(h - l, abs(h - prev_close), abs(l - prev_close))
        atr = atr_rma.update(tr)

        atr_pctile = _percentrank(atr_hist, atr, p.atr_pctile_len)
        is_trending = adx >= p.adx_trend
        is_volatile = atr_pctile >= p.atr_vol_pct
        regime = 0 if is_volatile else (2 if is_trending else 1)  # 0=VOLATILE 1=RANGE 2=TREND

        # ── Trend filters — Pine lines 108-124 ──
        f = ema_f.update(c)
        s = ema_s.update(c)
        trend_up = f > s
        trend_down = f < s

        htf_f, htf_s = htf_series[i]
        htf_up = (htf_f is not None and htf_s is not None and htf_f > htf_s) if p.use_higher_trend else True
        htf_down = (htf_f is not None and htf_s is not None and htf_f < htf_s) if p.use_higher_trend else True
        # Until the first HTF bucket closes, htf_up/htf_down are both False
        # (matches Pine's na comparisons evaluating false) — no entries gated
        # by an unavailable HTF filter fire early by accident.
        if p.use_higher_trend and htf_f is None:
            htf_up = htf_down = False

        # ── Breakout logic — Pine lines 129-137 ──
        # ta.crossover(close, hh[1]) compares close[i] against hh[1] AT bar i
        # (== hh(i-1), the highest-high window ending at bar i-1) AND close[i-1]
        # against hh[1] AT bar i-1 (== hh(i-2)). hh[1] is a shifted SERIES, not a
        # constant, so crossover needs its own two-bar lookback on EACH side —
        # a single shared "prior_hh" value for both legs (an earlier draft of
        # this port) is not equivalent and would misdate the entry bar. hh_hist/
        # ll_hist hold the full per-bar hh/ll series so both lags are available.
        prior_hh = hh_hist[-1] if hh_hist else None              # hh(i-1) == hh[1] at bar i
        prior_prior_hh = hh_hist[-2] if len(hh_hist) >= 2 else None  # hh(i-2) == hh[1] at bar i-1
        prior_ll = ll_hist[-1] if ll_hist else None
        prior_prior_ll = ll_hist[-2] if len(ll_hist) >= 2 else None

        highs.append(h); lows.append(l)
        hh = max(highs[-p.breakout_len:]) if len(highs) >= p.breakout_len else None
        ll = min(lows[-p.breakout_len:]) if len(lows) >= p.breakout_len else None
        hh_hist.append(hh)
        ll_hist.append(ll)

        vol_avg_hist.append(v)
        vol_window = vol_avg_hist[-20:]
        vol_avg = sum(vol_window) / len(vol_window)
        vol_expanded = (not p.volume_filter) or (v > vol_avg * p.vol_mult)

        long_breakout = (
            prior_hh is not None and prior_prior_hh is not None
            and c > prior_hh and prev_close <= prior_prior_hh and vol_expanded
        )
        short_breakout = (
            prior_ll is not None and prior_prior_ll is not None
            and c < prior_ll and prev_close >= prior_prior_ll and vol_expanded
        )

        # ── Mean reversion — Pine lines 140-147 ──
        closes.append(c)
        window = closes[-p.breakout_len:]
        mean = sum(window) / len(window) if len(window) >= p.breakout_len else None
        if mean is not None and len(window) > 1:
            var = sum((x - mean) ** 2 for x in window) / (len(window) - 1)
            std = math.sqrt(var)
        else:
            std = None
        z = (c - mean) / std if (mean is not None and std and std > 0) else 0.0

        long_mr = False
        short_mr = False

        # crossunder(zScore, -rangeZScore): prev_z > -range AND z <= -range. Unlike
        # the breakout crossovers above, the right-hand side here is a CONSTANT
        # (-rangeZScore), not a shifted series, so a single one-bar lag is exact.
        prev_z = state.get("_prev_z", 0.0)
        if ll is not None:
            long_mr = (prev_z > -p.range_zscore >= z) and c > ll
        if hh is not None:
            short_mr = (prev_z < p.range_zscore <= z) and c < hh
        state["_prev_z"] = z

        atr_hist.append(atr)

        # ── Conviction scoring — Pine lines 152-157 ──
        conv_base = 2 if adx > 35 else 0
        conv_long = conv_base + (1 if (trend_up and htf_up) else 0) + (1 if (di_plus - di_minus > 15) else 0)
        conv_short = conv_base + (1 if (trend_down and htf_down) else 0) + (1 if (di_minus - di_plus > 15) else 0)
        # DXY filter omitted here (use_dxy defaults False in the Pine script too;
        # this port doesn't ingest a second real symbol's series — see module docstring).
        jugular_long = conv_long >= 4
        jugular_short = conv_short >= 4

        # ── Signal conditions — Pine lines 162-173 (bar-close-confirmed by construction:
        # backtest bars are always closed bars, unlike a live intrabar feed) ──
        long_entry_cond = regime == 2 and long_breakout and trend_up and (not p.use_higher_trend or htf_up)
        short_entry_cond = regime == 2 and short_breakout and trend_down and (not p.use_higher_trend or htf_down)
        long_mr_cond = regime == 1 and long_mr
        short_mr_cond = regime == 1 and short_mr

        long_signal = long_entry_cond or long_mr_cond
        short_signal = short_entry_cond or short_mr_cond

        if long_signal and not short_signal:
            signals[i] = "BUY"
            jugular[i] = jugular_long
        elif short_signal and not long_signal:
            signals[i] = "SELL"
            jugular[i] = jugular_short
        elif long_signal and short_signal:
            # Structurally near-impossible (breakout up and down, or z-score crossing
            # both extremes, on the same bar) — Pine's two independent `if` blocks
            # would leave the LAST-executed (short) as final state; mirrored here.
            signals[i] = "SELL"
            jugular[i] = jugular_short

        state.update({
            "regime": regime, "adx": adx, "atr": atr, "atr_pctile": atr_pctile,
            "ema_fast": f, "ema_slow": s, "conv_long": conv_long, "conv_short": conv_short,
            "hh": hh, "ll": ll,
        })

    return {"signals": signals, "jugular": jugular, "state": state}


def analyze(symbol: str, bars: list, p: DruckParams = None) -> dict:
    """
    On-demand analysis of the LATEST bar. Real bars only — same convention as
    orb_engine.analyze() / imo_engine's on-demand path.

    min_bars is a buffer past the largest internal lookback window
    (atr_pctile_len defaults to 100 — the biggest of the bunch) so the
    percentrank/regime/HTF math has real history to work with, not a cold start.
    """
    p = p or DruckParams.from_env()
    min_bars = max(p.atr_pctile_len, p.breakout_len, p.ema_slow, p.adx_len) + 10
    if not bars or len(bars) < min_bars:
        return {"symbol": symbol.upper(), "status": "insufficient_data",
                "bars": len(bars or []), "min_bars": min_bars}
    out = compute_series(bars, p)
    if not out["state"]:
        return {"symbol": symbol.upper(), "status": "insufficient_data",
                "bars": len(bars), "detail": "no parseable timestamps"}
    # Internal-only keys (prefixed "_") are carry-over state for compute_series's
    # own next-bar math (e.g. "_prev_z") — not part of the public response shape.
    public_state = {k: v for k, v in out["state"].items() if not k.startswith("_")}
    return {
        "symbol": symbol.upper(), "status": "success",
        "signal": out["signals"][-1], "jugular": bool(out["jugular"][-1]),
        "price": _bar_val(bars[-1], "close", "c"),
        **public_state,
    }
