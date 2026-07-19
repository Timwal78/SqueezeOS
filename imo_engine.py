"""
SML-IMO Engine — Institutional Momentum Oscillator, server-side Python.
=======================================================================
The SINGLE implementation of the IMO math. Consumers:

  • imo_scanner.py            — background loop → iam_executor (auto-trading)
  • core/api/imo_bp.py        — /api/imo/<symbol> on-demand analysis
  • tests/backtest_imo.py     — backtest harness (imports from here)

Mirrors indicators/SML_Institutional_Momentum_Oscillator_v6.pine exactly:
Jurik zero-lag core → ATR-normalized velocity × relative-volume force ×
acceleration expander → dynamic ±σ variance bands over the oscillator's own
distribution → Kaufman-ER trend/bracket regime → regime-gated signals
(zero-cross ignition in trend, outer-band fade in bracket, early hooks).

TradingView is NOT required for execution — the Pine script is a visual of
this same math. Bars in, signals out; no synthetic data anywhere.

Env-tunable defaults (all optional):
  IMO_SMOOTH_LEN=14  IMO_MOM_LEN=8  IMO_ATR_LEN=14  IMO_VOL_BASE_LEN=55
  IMO_VOL_GAMMA=0.6  IMO_ACCEL_GAIN=0.5  IMO_SIG_LEN=4
  IMO_BAND_LOOK=100  IMO_BAND_INNER=1.5  IMO_BAND_OUTER=2.5
  IMO_ER_LEN=20      IMO_ER_THRESH=0.30  IMO_USE_EARLY=true
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass


def _env_f(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key, default))
    except (TypeError, ValueError):
        return default


def _env_i(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, default))
    except (TypeError, ValueError):
        return default


@dataclass
class ImoParams:
    smooth_len: int = 14
    mom_len: int = 8
    atr_len: int = 14
    vol_base_len: int = 55
    vol_gamma: float = 0.6
    accel_gain: float = 0.5
    sig_len: int = 4
    band_look: int = 100
    band_inner: float = 1.5
    band_outer: float = 2.5
    er_len: int = 20
    er_thresh: float = 0.30
    use_early: bool = True
    stop_pct: float = 3.0  # used by the backtest simulator, not signal math

    @classmethod
    def from_env(cls) -> "ImoParams":
        return cls(
            smooth_len=_env_i("IMO_SMOOTH_LEN", 14),
            mom_len=_env_i("IMO_MOM_LEN", 8),
            atr_len=_env_i("IMO_ATR_LEN", 14),
            vol_base_len=_env_i("IMO_VOL_BASE_LEN", 55),
            vol_gamma=_env_f("IMO_VOL_GAMMA", 0.6),
            accel_gain=_env_f("IMO_ACCEL_GAIN", 0.5),
            sig_len=_env_i("IMO_SIG_LEN", 4),
            band_look=_env_i("IMO_BAND_LOOK", 100),
            band_inner=_env_f("IMO_BAND_INNER", 1.5),
            band_outer=_env_f("IMO_BAND_OUTER", 2.5),
            er_len=_env_i("IMO_ER_LEN", 20),
            er_thresh=_env_f("IMO_ER_THRESH", 0.30),
            use_early=os.environ.get("IMO_USE_EARLY", "true").strip().lower() == "true",
            stop_pct=_env_f("IAM_STOP_LOSS_PCT", 3.0),
        )


class Jurik:
    """Stateful Jurik-style adaptive filter — same recursion as the Pine f_jurik()."""

    def __init__(self, length: int, phase: float = 0.0, power: float = 2.0):
        pr = 0.5 if phase < -100 else 2.5 if phase > 100 else phase / 100.0 + 1.5
        beta = 0.45 * (length - 1) / (0.45 * (length - 1) + 2.0)
        self.pr, self.beta, self.alpha = pr, beta, beta ** power
        self.e0 = self.e1 = self.e2 = self.jma = None

    def update(self, src: float) -> float:
        if self.jma is None:
            self.e0, self.e1, self.e2, self.jma = src, 0.0, 0.0, src
            return src
        self.e0 = (1 - self.alpha) * src + self.alpha * self.e0
        self.e1 = (src - self.e0) * (1 - self.beta) + self.beta * self.e1
        self.e2 = (self.e0 + self.pr * self.e1 - self.jma) * (1 - self.alpha) ** 2 + self.alpha ** 2 * self.e2
        self.jma = self.jma + self.e2
        return self.jma


class Ema:
    def __init__(self, length: int):
        self.k = 2.0 / (length + 1)
        self.v = None

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


def _rolling_mean_std(values: list, look: int):
    if len(values) < look:
        return None, None
    window = values[-look:]
    m = sum(window) / look
    var = sum((v - m) ** 2 for v in window) / (look - 1)
    return m, math.sqrt(var)


def compute_series(bars: list, p: ImoParams = None) -> dict:
    """
    bars: chronological list of dicts with open/high/low/close/volume
    (o/h/l/c/v accepted). Returns:
      {
        "signals": [None|'BUY'|'SELL'] per bar,
        "state":   dict of the LAST bar's full oscillator state,
      }
    Signal semantics match the Pine script: BUY = ignition long / fade long /
    early buy; SELL = ignition short / fade short / early sell.
    """
    p = p or ImoParams.from_env()
    price_f = Jurik(p.smooth_len)
    osc_f = Jurik(p.sig_len)
    rel_fast, rel_slow, er_ema = Ema(3), Ema(12), Ema(4)

    src_hist: list = []
    atr_prev = None
    vol_hist: list = []
    osc_hist: list = []
    close_hist: list = []
    signals: list = [None] * len(bars)
    state: dict = {}

    for i, bar in enumerate(bars):
        h = _bar_val(bar, "high", "h")
        l = _bar_val(bar, "low", "l")
        c = _bar_val(bar, "close", "c")
        v = _bar_val(bar, "volume", "v")
        if c <= 0:
            continue
        src = (h + l + c) / 3.0 if h > 0 and l > 0 else c
        s = price_f.update(src)
        src_hist.append(s)

        # Wilder ATR
        if atr_prev is None:
            atr_prev = max(h - l, 0.0)
        else:
            pc = close_hist[-1] if close_hist else c
            tr = max(h - l, abs(h - pc), abs(l - pc))
            atr_prev = (atr_prev * (p.atr_len - 1) + tr) / p.atr_len
        atr = atr_prev

        velocity = 0.0
        if len(src_hist) > p.mom_len and atr > 0:
            velocity = (s - src_hist[-1 - p.mom_len]) / (atr * math.sqrt(p.mom_len))

        vol_hist.append(v)
        base_w = vol_hist[-p.vol_base_len:]
        vol_base = sum(base_w) / len(base_w) if base_w else 0.0
        rel_vol = v / vol_base if vol_base > 0 else 1.0
        vol_force = max(rel_vol, 0.05) ** p.vol_gamma
        accel = rel_fast.update(rel_vol) - rel_slow.update(rel_vol)
        accel_boost = min(1.0 + p.accel_gain * max(accel, 0.0), 3.0)

        osc = osc_f.update(100.0 * velocity * vol_force * accel_boost)
        osc_hist.append(osc)
        close_hist.append(c)

        mean, dev = _rolling_mean_std(osc_hist, p.band_look)
        bands_ready = dev is not None

        er = 0.0
        if len(close_hist) > p.er_len:
            num = abs(c - close_hist[-1 - p.er_len])
            den = sum(abs(close_hist[j] - close_hist[j - 1])
                      for j in range(len(close_hist) - p.er_len, len(close_hist)))
            er = num / den if den > 0 else 0.0
        er_s = er_ema.update(er)
        trending = er_s > p.er_thresh

        sig = None
        detail = None
        if len(osc_hist) >= 3 and bands_ready:
            o0, o1, o2 = osc_hist[-1], osc_hist[-2], osc_hist[-3]
            up_in, up_out = mean + p.band_inner * dev, mean + p.band_outer * dev
            dn_in, dn_out = mean - p.band_inner * dev, mean - p.band_outer * dev

            ignition_long = trending and o1 <= 0 < o0
            ignition_short = trending and o1 >= 0 > o0
            fade_long = (not trending) and o1 <= dn_out < o0
            fade_short = (not trending) and o1 >= up_out > o0
            hook_up = o0 > o1 <= o2
            hook_down = o0 < o1 >= o2
            early_buy = p.use_early and o0 < dn_in and hook_up
            early_sell = p.use_early and o0 > up_in and hook_down

            if ignition_long or fade_long or early_buy:
                sig = "BUY"
                detail = "IGNITION_LONG" if ignition_long else "FADE_LONG" if fade_long else "EARLY_BUY"
            elif ignition_short or fade_short or early_sell:
                sig = "SELL"
                detail = "IGNITION_SHORT" if ignition_short else "FADE_SHORT" if fade_short else "EARLY_SELL"
            signals[i] = sig

        if i == len(bars) - 1:
            z = (osc - mean) / dev if bands_ready and dev > 0 else 0.0
            state = {
                "oscillator": round(osc, 4),
                "z_score": round(z, 3),
                "regime": "TREND" if trending else "BRACKET",
                "efficiency_ratio": round(er_s, 4),
                "rel_volume": round(rel_vol, 3),
                "vol_accelerating": accel > 0,
                "bands_ready": bands_ready,
                "band_inner": round(mean + p.band_inner * dev, 4) if bands_ready else None,
                "band_outer": round(mean + p.band_outer * dev, 4) if bands_ready else None,
                "signal": sig,
                "signal_detail": detail,
                "price": c,
                "bar_key": str(bar.get("date") or bar.get("t") or bar.get("timestamp") or len(bars)),
                "bars_used": len(bars),
            }

    return {"signals": signals, "state": state}


def analyze(symbol: str, bars: list, p: ImoParams = None) -> dict:
    """On-demand single-symbol analysis of the LATEST bar. Real bars only."""
    if not bars or len(bars) < 120:
        return {"symbol": symbol.upper(), "status": "insufficient_data",
                "bars": len(bars or []), "min_bars": 120}
    out = compute_series(bars, p)
    return {"symbol": symbol.upper(), "status": "success", **out["state"]}
