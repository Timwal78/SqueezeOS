"""
SML Quad-Score Explosive Breakout Finder — a NEW, independent, LONG-ONLY
engine built from an operator-provided quantitative spec ("4-Pillar
Volatility & Breakout Scoring Engine", 2026-07-31). Not a retrofit of
sovereign_squeeze_engine.py/breakout_engine.py/sr_matrix_engine.py — this is
a fresh design. Same file-per-engine convention as every other engine here:
this module is the single Python source of truth; the companion Pine script
is a visual of this exact math, no drift.

ADAPTATION NOTE: the original spec asked for a standalone ccxt-based crypto
package (its own config.yaml, execution/ccxt_client.py, event-driven
backtester). Per explicit operator decision, this was adapted into this
repo's existing conventions instead: real equity daily bars via
DataManager, one Python engine + scanner + blueprint, signals routed
through iam_executor.py — same safety stack (paper mode default,
IAM_STOP_LOSS_PCT, daily-loss breaker, primary-system gate) every other
engine here already uses. The spec's volatility risk-parity POSITION
SIZING formula (risk_amount / stop_distance) is intentionally NOT
duplicated as a second, competing order-sizing system — iam_executor
already owns real order sizing/stops uniformly across every engine in this
codebase, and running two independent sizing calculators against the same
live account would fight each other. The ATR-based stop/target computed
here are used for this module's own backtest state machine (compute_series)
and reported for visibility, exactly like every other engine's stop/target
fields — not sent to the broker directly.

FOUR PILLAR SCORES (0-100 each), from the operator's exact formulas:

  COMPRESSION (30/25/20/15/10 weighted):
    - BB width percentile, INVERTED (100 - PercentRank) so tighter = higher
    - Keltner compression: 100 if BB fully inside KC (EMA20 basis, 1.5xATR14)
      else 0 (a hard boolean per spec, not a continuous measure)
    - ATR_14 percentile, inverted
    - Donchian width ((Highest(High,20)-Lowest(Low,20))/Close) percentile, inverted
    - Historical volatility (stdev of 20-bar log returns) percentile, inverted

  TREND (40/30/30 weighted):
    - EMA alignment: 100 if EMA20>EMA50>EMA200, 50 if EMA20>EMA50 (only), else 0
    - Anchored VWAP position: 50 + (Close-VWAP)/VWAP*100*10, clamped 0-100
      (VWAP here is a rolling N-bar volume-weighted average — a disclosed
      proxy for a genuinely event-anchored VWAP, same convention as
      mmle_engine.py's _vwap_proxy(); this engine has no intraday anchor
      event to attach to on daily bars)
    - ADX_14 strength: min(100, ADX/50*100)

  PARTICIPATION (40/30/30 weighted):
    - RVOL: min(100, (Volume/SMA(Volume,20))/3.0*100)
    - OBV slope percentile: PercentRank(LinRegSlope(OBV,14), N) — NOT
      inverted (a rising OBV slope should rank high); percentile rank is
      scale-invariant so OBV's raw cumulative-volume magnitude never needs
      separate normalization
    - CMF_20: clamp((CMF+0.5)*100, 0, 100)

  TRIGGER (40/30/30 weighted):
    - Momentum acceleration: Accel = Mom5 - Mom5[-1] (Mom5 = Close-Close[-5]);
      PercentRank(Accel, N) — not inverted
    - Breakout confirmation: 100 if Close > Highest(High,20) as of the PRIOR
      bar (no lookahead — today's own high is excluded); 50 if Close>EMA20;
      else 0
    - Candle structure: (Close-Low)/(High-Low)*100

COMPOSITE: S_composite = 0.25*Compression + 0.35*Trend + 0.20*Participation
+ 0.20*Trigger.

ENTRY GATE (long-only — this engine only ever produces BUY/CALL setups,
same "entry-only, exits via iam_executor's own stop" design already used by
breakout_engine.py/mm_intel_scanner.py). Thresholds below are the
TRAIN/VALID-VALIDATED config from docs/QUAD_SCORE_OPTIMIZATION_2026-07-31.md,
NOT the operator's originally-specified defaults (composite>=70, trend>=50,
trigger>=60, temporal>=65, atr_stop=2.0/atr_tp=4.0 — see
docs/QUAD_SCORE_BACKTEST_2026-07-31.md for that shipped-defaults result,
mixed-but-thin on 6 symbols). A 3000-config chronological TRAIN(pre-2024-06)/
VALID(2024-06+) search across 16 real symbols found this instead:

  entry_signal = (
      S_composite   >= 65.0  AND
      S_trend       >= 45.0  AND
      S_trigger     >= 45.0  AND
      temporal_sequence_valid  AND
      macro_regime_valid
  )

  temporal_sequence_valid: Compression must have cleared 55.0 at least once
  in the 10 bars strictly BEFORE the current bar (Max(S_comp[i-10:i]) >=
  55.0) — i.e. the market coiled recently, even if it has already started
  expanding (and S_comp is naturally falling) by the trigger bar itself.

  macro_regime_valid: a REAL higher-timeframe filter — Weekly bars are
  aggregated client-side from the same real Daily bars passed in (same
  method cie_scanner.py already uses for its own 1W support; DataManager
  has no native weekly timeframe). Valid when the last FULLY COMPLETED
  prior week's Close > Weekly EMA_200 AND Weekly ADX_14 > 18. "Fully
  completed prior week" is the key no-lookahead guarantee: a daily bar
  only ever reads weekly bars whose entire constituent days occurred
  before that bar's own calendar week, never the still-forming current
  week. Needs real ~4+ years of daily history for Weekly EMA_200 to seed;
  reports "insufficient_data" honestly rather than approximating a shorter
  weekly EMA when history is short.

BACKTEST VERDICT (2026-07-31): genuinely validated, real edge. 146 trades
(66 TRAIN + 80 VALID) across 16 real symbols, 2018-2026 (Robinhood MCP).
VALID PF held >1.0 at all four chronological split points tested (50/60/
67/75%) and under every single-parameter perturbation tried across six
tuned dimensions (composite/trend/trigger/temporal/weekly-ADX/ATR-stop-
target) — the same disciplined TRAIN/VALID methodology already established
by tests/optimize_sovereign_squeeze.py / tests/optimize_cvd_regime.py. See
docs/QUAD_SCORE_OPTIMIZATION_2026-07-31.md for the full writeup. Still NOT
added to IAM_PRIMARY_SYSTEM by this build — that is a separate, explicit
operator decision, same standing rule as every other engine here.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional
import math
import os


@dataclass
class QuadScoreParams:
    bb_length: int = 20
    bb_mult: float = 2.0
    kc_ema_length: int = 20
    kc_atr_mult: float = 1.5
    atr_length: int = 14
    donchian_length: int = 20
    hv_length: int = 20
    pctile_window: int = 100   # "N" in the spec — lookback for every PercentRank

    ema_fast: int = 20
    ema_mid: int = 50
    ema_slow: int = 200
    avwap_length: int = 20
    adx_length: int = 14

    rvol_length: int = 20
    rvol_divisor: float = 3.0
    obv_slope_len: int = 14
    cmf_length: int = 20

    mom_len: int = 5

    weekly_ema_len: int = 200
    weekly_adx_len: int = 14
    weekly_adx_min: float = 18.0

    atr_stop_mult: float = 1.5
    atr_tp_mult: float = 3.0
    risk_pct: float = 0.01   # informational only — real sizing is iam_executor's job

    temporal_lookback: int = 10
    temporal_threshold: float = 55.0

    th_composite: float = 65.0
    th_trend: float = 45.0
    th_trigger: float = 45.0

    @classmethod
    def from_env(cls) -> "QuadScoreParams":
        g = os.environ.get
        return cls(
            bb_length=int(g("QUAD_SCORE_BB_LENGTH", "20")),
            bb_mult=float(g("QUAD_SCORE_BB_MULT", "2.0")),
            kc_ema_length=int(g("QUAD_SCORE_KC_EMA_LENGTH", "20")),
            kc_atr_mult=float(g("QUAD_SCORE_KC_ATR_MULT", "1.5")),
            atr_length=int(g("QUAD_SCORE_ATR_LENGTH", "14")),
            donchian_length=int(g("QUAD_SCORE_DONCHIAN_LENGTH", "20")),
            hv_length=int(g("QUAD_SCORE_HV_LENGTH", "20")),
            pctile_window=int(g("QUAD_SCORE_PCTILE_WINDOW", "100")),
            ema_fast=int(g("QUAD_SCORE_EMA_FAST", "20")),
            ema_mid=int(g("QUAD_SCORE_EMA_MID", "50")),
            ema_slow=int(g("QUAD_SCORE_EMA_SLOW", "200")),
            avwap_length=int(g("QUAD_SCORE_AVWAP_LENGTH", "20")),
            adx_length=int(g("QUAD_SCORE_ADX_LENGTH", "14")),
            rvol_length=int(g("QUAD_SCORE_RVOL_LENGTH", "20")),
            rvol_divisor=float(g("QUAD_SCORE_RVOL_DIVISOR", "3.0")),
            obv_slope_len=int(g("QUAD_SCORE_OBV_SLOPE_LEN", "14")),
            cmf_length=int(g("QUAD_SCORE_CMF_LENGTH", "20")),
            mom_len=int(g("QUAD_SCORE_MOM_LEN", "5")),
            weekly_ema_len=int(g("QUAD_SCORE_WEEKLY_EMA_LEN", "200")),
            weekly_adx_len=int(g("QUAD_SCORE_WEEKLY_ADX_LEN", "14")),
            weekly_adx_min=float(g("QUAD_SCORE_WEEKLY_ADX_MIN", "18.0")),
            atr_stop_mult=float(g("QUAD_SCORE_ATR_STOP_MULT", "1.5")),
            atr_tp_mult=float(g("QUAD_SCORE_ATR_TP_MULT", "3.0")),
            risk_pct=float(g("QUAD_SCORE_RISK_PCT", "0.01")),
            temporal_lookback=int(g("QUAD_SCORE_TEMPORAL_LOOKBACK", "10")),
            temporal_threshold=float(g("QUAD_SCORE_TEMPORAL_THRESHOLD", "55.0")),
            th_composite=float(g("QUAD_SCORE_TH_COMPOSITE", "65.0")),
            th_trend=float(g("QUAD_SCORE_TH_TREND", "45.0")),
            th_trigger=float(g("QUAD_SCORE_TH_TRIGGER", "45.0")),
        )


# ─────────────────────────────────────────────────────────────────────────
# Generic bar/series helpers
# ─────────────────────────────────────────────────────────────────────────

def _bar_val(bar: dict, *keys, default=0.0) -> float:
    for k in keys:
        v = bar.get(k)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return default


def _bar_key(bar: dict, idx: int) -> str:
    return str(bar.get("date") or bar.get("t") or bar.get("timestamp") or idx)


def _sma(vals: list, length: int) -> list:
    n = len(vals)
    out = [None] * n
    running = 0.0
    for i in range(n):
        running += vals[i]
        if i >= length:
            running -= vals[i - length]
        if i >= length - 1:
            out[i] = running / length
    return out


def _stdev(vals: list, length: int, means: list) -> list:
    n = len(vals)
    out = [None] * n
    for i in range(n):
        if means[i] is None:
            continue
        window = vals[i - length + 1:i + 1]
        m = means[i]
        var = sum((v - m) ** 2 for v in window) / length
        out[i] = var ** 0.5
    return out


def _ema(vals: list, length: int) -> list:
    n = len(vals)
    out = [None] * n
    if n == 0:
        return out
    k = 2.0 / (length + 1)
    seed = None
    for i in range(n):
        if seed is None:
            if i >= length - 1:
                seed = sum(vals[i - length + 1:i + 1]) / length
                out[i] = seed
            continue
        seed = vals[i] * k + seed * (1 - k)
        out[i] = seed
    return out


def _rolling_max(vals: list, length: int) -> list:
    n = len(vals)
    out = [None] * n
    for i in range(n):
        if i < length - 1:
            continue
        out[i] = max(vals[i - length + 1:i + 1])
    return out


def _rolling_min(vals: list, length: int) -> list:
    n = len(vals)
    out = [None] * n
    for i in range(n):
        if i < length - 1:
            continue
        out[i] = min(vals[i - length + 1:i + 1])
    return out


def _true_range(highs: list, lows: list, closes: list, i: int) -> float:
    if i == 0:
        return highs[i] - lows[i]
    return max(
        highs[i] - lows[i],
        abs(highs[i] - closes[i - 1]),
        abs(lows[i] - closes[i - 1]),
    )


def _wilder_smooth(vals: list, length: int) -> list:
    n = len(vals)
    out = [None] * n
    running = None
    for i in range(n):
        if running is None:
            if i >= length - 1:
                running = sum(vals[i - length + 1:i + 1])
                out[i] = running / length
            continue
        running = running - (running / length) + vals[i]
        out[i] = running / length
    return out


def _adx(highs: list, lows: list, closes: list, length: int) -> list:
    """Standard Wilder ADX."""
    n = len(highs)
    tr = [_true_range(highs, lows, closes, i) for i in range(n)]
    plus_dm = [0.0] * n
    minus_dm = [0.0] * n
    for i in range(1, n):
        up_move = highs[i] - highs[i - 1]
        down_move = lows[i - 1] - lows[i]
        plus_dm[i] = up_move if (up_move > down_move and up_move > 0) else 0.0
        minus_dm[i] = down_move if (down_move > up_move and down_move > 0) else 0.0
    atr = _wilder_smooth(tr, length)
    plus_sm = _wilder_smooth(plus_dm, length)
    minus_sm = _wilder_smooth(minus_dm, length)
    plus_di = [None if atr[i] is None or not atr[i] else 100.0 * plus_sm[i] / atr[i] for i in range(n)]
    minus_di = [None if atr[i] is None or not atr[i] else 100.0 * minus_sm[i] / atr[i] for i in range(n)]
    dx = [None] * n
    for i in range(n):
        if plus_di[i] is None or minus_di[i] is None:
            continue
        s = plus_di[i] + minus_di[i]
        dx[i] = 0.0 if s == 0 else 100.0 * abs(plus_di[i] - minus_di[i]) / s
    adx = _wilder_smooth([d if d is not None else 0.0 for d in dx], length)
    return adx, atr


def _percentile_rank(vals: list, window: int) -> list:
    """Standard PercentRank: % of the trailing `window` values (including
    the current one) that are <= the current value. 100 = highest value in
    the window, 0 = lowest. Percentile rank is scale-invariant, so no
    separate normalization is needed regardless of a metric's raw units
    (e.g. OBV's cumulative-share-count magnitude)."""
    n = len(vals)
    out = [None] * n
    for i in range(n):
        if vals[i] is None or i < window - 1:
            continue
        w = [v for v in vals[i - window + 1:i + 1] if v is not None]
        if len(w) < window:
            continue
        cur = vals[i]
        count_le = sum(1 for v in w if v <= cur)
        out[i] = 100.0 * count_le / len(w)
    return out


def _linreg_slope(vals: list) -> Optional[float]:
    """Closed-form least-squares slope over `vals` (oldest first)."""
    n = len(vals)
    if n < 2:
        return None
    sum_x = n * (n - 1) / 2.0
    sum_x2 = (n - 1) * n * (2 * n - 1) / 6.0
    sum_y = sum(vals)
    sum_xy = sum(i * v for i, v in enumerate(vals))
    denom = n * sum_x2 - sum_x * sum_x
    if denom == 0:
        return 0.0
    return (n * sum_xy - sum_x * sum_y) / denom


def _rolling_linreg_slope(vals: list, length: int) -> list:
    n = len(vals)
    out = [None] * n
    for i in range(n):
        if i < length - 1:
            continue
        out[i] = _linreg_slope(vals[i - length + 1:i + 1])
    return out


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


# ─────────────────────────────────────────────────────────────────────────
# Weekly aggregation for the macro HTF regime filter (no lookahead — see
# module docstring for the "fully completed prior week" guarantee)
# ─────────────────────────────────────────────────────────────────────────

def _aggregate_weekly(daily_bars: list) -> tuple:
    """Groups real Daily bars into Weekly (ISO week) bars, client-side —
    same method cie_scanner.py already uses for its own 1W support (no
    native weekly timeframe in DataManager). Returns (weekly_bars,
    week_key_for_each_daily_bar, week_key_to_weekly_index)."""
    weeks: dict = {}
    order: list = []
    day_week_key: list = [None] * len(daily_bars)
    for idx, b in enumerate(daily_bars):
        raw_date = b.get("date") or b.get("t") or b.get("timestamp")
        if raw_date is None:
            continue
        try:
            d = datetime.fromisoformat(str(raw_date)[:10]).date()
        except ValueError:
            continue
        key = (d.isocalendar()[0], d.isocalendar()[1])
        day_week_key[idx] = key
        if key not in weeks:
            weeks[key] = {"o": b.get("o", b.get("open")), "h": _bar_val(b, "high", "h"),
                          "l": _bar_val(b, "low", "l"), "c": _bar_val(b, "close", "c"),
                          "v": 0.0}
            order.append(key)
        wk = weeks[key]
        h = _bar_val(b, "high", "h")
        l = _bar_val(b, "low", "l")
        wk["h"] = max(wk["h"], h)
        wk["l"] = min(wk["l"], l)
        wk["c"] = _bar_val(b, "close", "c")
        wk["v"] += _bar_val(b, "volume", "v")

    weekly_bars = [weeks[k] for k in order]
    key_to_index = {k: i for i, k in enumerate(order)}
    return weekly_bars, day_week_key, key_to_index


def _weekly_macro_series(daily_bars: list, p: QuadScoreParams) -> list:
    """Returns, for every DAILY bar index, whether the macro regime filter
    is valid — read strictly from the last FULLY COMPLETED prior week
    (never the still-forming current week, so this can never see the
    future). None where insufficient weekly history exists yet."""
    n = len(daily_bars)
    weekly_bars, day_week_key, key_to_index = _aggregate_weekly(daily_bars)
    w_closes = [w["c"] for w in weekly_bars]
    w_highs = [w["h"] for w in weekly_bars]
    w_lows = [w["l"] for w in weekly_bars]
    w_ema200 = _ema(w_closes, p.weekly_ema_len)
    w_adx, _ = _adx(w_highs, w_lows, w_closes, p.weekly_adx_len)

    valid = [None] * n
    for i in range(n):
        key = day_week_key[i]
        if key is None or key not in key_to_index:
            continue
        idx = key_to_index[key]
        prior_idx = idx - 1
        if prior_idx < 0 or w_ema200[prior_idx] is None or w_adx[prior_idx] is None:
            continue
        valid[i] = (w_closes[prior_idx] > w_ema200[prior_idx]) and (w_adx[prior_idx] > p.weekly_adx_min)
    return valid


# ─────────────────────────────────────────────────────────────────────────
# Pillar score computation
# ─────────────────────────────────────────────────────────────────────────

def _compute_compression(highs, lows, closes, p: QuadScoreParams) -> list:
    n = len(closes)
    basis_bb = _sma(closes, p.bb_length)
    dev_bb = _stdev(closes, p.bb_length, basis_bb)
    bbw = [None if basis_bb[i] is None or not basis_bb[i] else
           (2 * p.bb_mult * dev_bb[i]) / basis_bb[i] for i in range(n)]
    upper_bb = [None if basis_bb[i] is None else basis_bb[i] + p.bb_mult * dev_bb[i] for i in range(n)]
    lower_bb = [None if basis_bb[i] is None else basis_bb[i] - p.bb_mult * dev_bb[i] for i in range(n)]

    tr = [_true_range(highs, lows, closes, i) for i in range(n)]
    atr = _wilder_smooth(tr, p.atr_length)
    kc_basis = _ema(closes, p.kc_ema_length)
    upper_kc = [None if kc_basis[i] is None or atr[i] is None else kc_basis[i] + atr[i] * p.kc_atr_mult for i in range(n)]
    lower_kc = [None if kc_basis[i] is None or atr[i] is None else kc_basis[i] - atr[i] * p.kc_atr_mult for i in range(n)]

    don_high = _rolling_max(highs, p.donchian_length)
    don_low = _rolling_min(lows, p.donchian_length)
    dw = [None if don_high[i] is None or not closes[i] else
          (don_high[i] - don_low[i]) / closes[i] for i in range(n)]

    log_ret = [None] * n
    for i in range(1, n):
        if closes[i - 1] and closes[i]:
            log_ret[i] = math.log(closes[i] / closes[i - 1])
    hv_mean = _sma([r if r is not None else 0.0 for r in log_ret], p.hv_length)
    hv = _stdev([r if r is not None else 0.0 for r in log_ret], p.hv_length, hv_mean)
    hv_annualized = [None if hv[i] is None else hv[i] * (252 ** 0.5) for i in range(n)]

    bbw_pctile = _percentile_rank(bbw, p.pctile_window)
    atr_pctile = _percentile_rank(atr, p.pctile_window)
    dw_pctile = _percentile_rank(dw, p.pctile_window)
    hv_pctile = _percentile_rank(hv_annualized, p.pctile_window)

    score = [None] * n
    for i in range(n):
        if (bbw_pctile[i] is None or atr_pctile[i] is None or dw_pctile[i] is None
                or hv_pctile[i] is None or upper_bb[i] is None or upper_kc[i] is None):
            continue
        kc_score = 100.0 if (upper_bb[i] <= upper_kc[i] and lower_bb[i] >= lower_kc[i]) else 0.0
        score[i] = (
            0.30 * (100.0 - bbw_pctile[i]) + 0.25 * kc_score
            + 0.20 * (100.0 - atr_pctile[i]) + 0.15 * (100.0 - dw_pctile[i])
            + 0.10 * (100.0 - hv_pctile[i])
        )
    return score


def _compute_trend(highs, lows, closes, volumes, p: QuadScoreParams) -> list:
    n = len(closes)
    ema_fast = _ema(closes, p.ema_fast)
    ema_mid = _ema(closes, p.ema_mid)
    ema_slow = _ema(closes, p.ema_slow)
    adx, _ = _adx(highs, lows, closes, p.adx_length)

    typical = [(highs[i] + lows[i] + closes[i]) / 3.0 for i in range(n)]
    vwap = [None] * n
    for i in range(n):
        if i < p.avwap_length - 1:
            continue
        vol_window = volumes[i - p.avwap_length + 1:i + 1]
        tv_window = typical[i - p.avwap_length + 1:i + 1]
        vol_sum = sum(vol_window)
        vwap[i] = (sum(t * v for t, v in zip(tv_window, vol_window)) / vol_sum) if vol_sum > 0 else sum(tv_window) / len(tv_window)

    score = [None] * n
    for i in range(n):
        if ema_fast[i] is None or ema_mid[i] is None or ema_slow[i] is None or adx[i] is None or vwap[i] is None or not vwap[i]:
            continue
        if ema_fast[i] > ema_mid[i] > ema_slow[i]:
            ema_align = 100.0
        elif ema_fast[i] > ema_mid[i]:
            ema_align = 50.0
        else:
            ema_align = 0.0

        dist_pct = (closes[i] - vwap[i]) / vwap[i] * 100.0
        avwap_score = _clamp(50.0 + dist_pct * 10.0, 0.0, 100.0)

        adx_score = min(100.0, adx[i] / 50.0 * 100.0)

        score[i] = 0.40 * ema_align + 0.30 * avwap_score + 0.30 * adx_score
    return score, ema_fast


def _compute_participation(closes, volumes, highs, lows, p: QuadScoreParams) -> list:
    n = len(closes)
    vol_avg = _sma(volumes, p.rvol_length)
    rvol = [None if vol_avg[i] is None or not vol_avg[i] else volumes[i] / vol_avg[i] for i in range(n)]
    rvol_score = [None if rvol[i] is None else min(100.0, rvol[i] / p.rvol_divisor * 100.0) for i in range(n)]

    obv = [0.0] * n
    for i in range(1, n):
        if closes[i] > closes[i - 1]:
            obv[i] = obv[i - 1] + volumes[i]
        elif closes[i] < closes[i - 1]:
            obv[i] = obv[i - 1] - volumes[i]
        else:
            obv[i] = obv[i - 1]
    obv_slope = _rolling_linreg_slope(obv, p.obv_slope_len)
    obv_pctile = _percentile_rank(obv_slope, p.pctile_window)

    money_flow_vol = [0.0] * n
    for i in range(n):
        rng = highs[i] - lows[i]
        mfm = 0.0 if rng == 0 else ((closes[i] - lows[i]) - (highs[i] - closes[i])) / rng
        money_flow_vol[i] = mfm * volumes[i]
    mfv_sum = _sma(money_flow_vol, p.cmf_length)
    vol_sum = _sma(volumes, p.cmf_length)
    cmf = [None if mfv_sum[i] is None or not vol_sum[i] else mfv_sum[i] / vol_sum[i] for i in range(n)]
    cmf_score = [None if cmf[i] is None else _clamp((cmf[i] + 0.5) * 100.0, 0.0, 100.0) for i in range(n)]

    score = [None] * n
    for i in range(n):
        if rvol_score[i] is None or obv_pctile[i] is None or cmf_score[i] is None:
            continue
        score[i] = 0.40 * rvol_score[i] + 0.30 * obv_pctile[i] + 0.30 * cmf_score[i]
    return score


def _compute_trigger(highs, lows, closes, ema_fast, p: QuadScoreParams) -> list:
    n = len(closes)
    mom5 = [None] * n
    for i in range(n):
        if i < p.mom_len:
            continue
        mom5[i] = closes[i] - closes[i - p.mom_len]
    accel = [None] * n
    for i in range(n):
        if mom5[i] is None or i < 1 or mom5[i - 1] is None:
            continue
        accel[i] = mom5[i] - mom5[i - 1]
    accel_pctile = _percentile_rank(accel, p.pctile_window)

    don_high = _rolling_max(highs, p.donchian_length)

    score = [None] * n
    for i in range(n):
        if accel_pctile[i] is None or ema_fast[i] is None:
            continue
        if i > 0 and don_high[i - 1] is not None and closes[i] > don_high[i - 1]:
            brk_score = 100.0
        elif closes[i] > ema_fast[i]:
            brk_score = 50.0
        else:
            brk_score = 0.0

        rng = highs[i] - lows[i]
        candle_score = 50.0 if rng == 0 else (closes[i] - lows[i]) / rng * 100.0

        score[i] = 0.40 * accel_pctile[i] + 0.30 * brk_score + 0.30 * candle_score
    return score


# ─────────────────────────────────────────────────────────────────────────
# Walk-forward state machine + on-demand wrapper
# ─────────────────────────────────────────────────────────────────────────

def compute_series(bars: list, p: QuadScoreParams = None) -> dict:
    """Full walk-forward position state machine — one open position at a
    time (long-only), entry at the setup bar's close, ATR stop/tp checked
    on each subsequent bar's close, no intrabar fills, no lookahead."""
    p = p or QuadScoreParams.from_env()
    n = len(bars)
    highs = [_bar_val(b, "high", "h") for b in bars]
    lows = [_bar_val(b, "low", "l") for b in bars]
    closes = [_bar_val(b, "close", "c") for b in bars]
    volumes = [_bar_val(b, "volume", "v") for b in bars]

    compression = _compute_compression(highs, lows, closes, p)
    trend, ema_fast = _compute_trend(highs, lows, closes, volumes, p)
    participation = _compute_participation(closes, volumes, highs, lows, p)
    trigger = _compute_trigger(highs, lows, closes, ema_fast, p)
    macro_valid = _weekly_macro_series(bars, p)

    tr = [_true_range(highs, lows, closes, i) for i in range(n)]
    atr = _wilder_smooth(tr, p.atr_length)

    composite = [None] * n
    for i in range(n):
        if compression[i] is None or trend[i] is None or participation[i] is None or trigger[i] is None:
            continue
        composite[i] = 0.25 * compression[i] + 0.35 * trend[i] + 0.20 * participation[i] + 0.20 * trigger[i]

    temporal_valid = [None] * n
    for i in range(n):
        lo = max(0, i - p.temporal_lookback)
        window = [compression[j] for j in range(lo, i) if compression[j] is not None]
        if not window:
            continue
        temporal_valid[i] = max(window) >= p.temporal_threshold

    events = [None] * n
    live_signal = [None] * n
    pnl_pct = [None] * n
    scores = [None] * n

    in_pos = False
    entry_price: Optional[float] = None
    stop_price: Optional[float] = None
    target_price: Optional[float] = None

    for i in range(n):
        if in_pos:
            close = closes[i]
            pnl_pct[i] = round((close - entry_price) / entry_price * 100, 4)
            if close >= target_price:
                events[i] = "EXIT_TARGET"
                live_signal[i] = "SELL"
                in_pos = False
                entry_price = stop_price = target_price = None
                continue
            if close <= stop_price:
                events[i] = "EXIT_STOP"
                live_signal[i] = "SELL"
                in_pos = False
                entry_price = stop_price = target_price = None
                continue
            continue

        if (composite[i] is None or temporal_valid[i] is None or macro_valid[i] is None
                or atr[i] is None or not atr[i]):
            continue

        entry_signal = (
            composite[i] >= p.th_composite
            and trend[i] >= p.th_trend
            and trigger[i] >= p.th_trigger
            and temporal_valid[i]
            and macro_valid[i]
        )
        if entry_signal:
            scores[i] = {
                "compression": round(compression[i], 1), "trend": round(trend[i], 1),
                "participation": round(participation[i], 1), "trigger": round(trigger[i], 1),
                "composite": round(composite[i], 1),
            }
            entry_price = closes[i]
            stop_price = entry_price - atr[i] * p.atr_stop_mult
            target_price = entry_price + atr[i] * p.atr_tp_mult
            in_pos = True
            events[i] = "ENTER_CALL"
            live_signal[i] = "BUY"
            pnl_pct[i] = 0.0

    return {
        "events": events, "live_signal": live_signal, "pnl_pct": pnl_pct, "scores": scores,
        "compression": compression, "trend": trend, "participation": participation,
        "trigger": trigger, "composite": composite,
        "temporal_valid": temporal_valid, "macro_valid": macro_valid,
        "in_pos": in_pos, "entry_price": entry_price,
        "stop_price": stop_price, "target_price": target_price,
    }


def analyze(symbol: str, bars: list, p: QuadScoreParams = None) -> dict:
    """On-demand analysis of the LATEST bar."""
    p = p or QuadScoreParams.from_env()
    min_bars = max(p.pctile_window + p.hv_length, p.ema_slow, p.weekly_ema_len * 5) + p.atr_length + 5
    if not bars or len(bars) < min_bars:
        return {"symbol": symbol.upper(), "status": "insufficient_data",
                "bars": len(bars or []), "min_bars": min_bars}

    out = compute_series(bars, p)
    last = len(bars) - 1
    close = _bar_val(bars[-1], "close", "c")

    return {
        "symbol": symbol.upper(), "status": "success",
        "price": close,
        "event": out["events"][last],
        "signal": out["live_signal"][last],
        "scores": {
            "compression": out["compression"][last], "trend": out["trend"][last],
            "participation": out["participation"][last], "trigger": out["trigger"][last],
            "composite": out["composite"][last],
        },
        "temporal_sequence_valid": out["temporal_valid"][last],
        "macro_regime_valid": out["macro_valid"][last],
        "setup": out["scores"][last],
        "position": {
            "in_position": out["in_pos"],
            "entry_price": out["entry_price"],
            "stop_price": out["stop_price"],
            "target_price": out["target_price"],
            "unrealized_pct": out["pnl_pct"][last] if out["in_pos"] else None,
        },
        "params": {
            "th_composite": p.th_composite, "th_trend": p.th_trend, "th_trigger": p.th_trigger,
            "temporal_threshold": p.temporal_threshold, "weekly_adx_min": p.weekly_adx_min,
            "atr_stop_mult": p.atr_stop_mult, "atr_tp_mult": p.atr_tp_mult,
        },
    }
