"""
AETHER 5-LOCK Engine — Python port of indicators/AETHER_5LOCK_PROTOCOL_v8.pine
=================================================================================
Single source of truth for the AETHER 5-LOCK math, same convention as
imo_engine.py/orb_engine.py/druck_engine.py/breakout_engine.py (Pine script is
a visual of the same logic — no drift between chart and code).

Long-only, multi-timeframe EMA trend-lock system:
  - lockS = EMA5 > EMA30, lockM = EMA5 > EMA80, lockL = EMA5 > EMA200
  - numL = lockS + lockM + lockL (0-3)
  - GODMODE = numL == 3 AND EMA5 rising over `slope_len` bars AND
    (EMA5-EMA200)/EMA200*100 > min_sep
  - Volume gate: volume > SMA(volume, vol_len) * vol_mult (optional)
  - Persistence: numL/GODMODE must hold at/above its threshold for
    `confirm_bars` CONSECUTIVE closes before firing — fires once, on the bar
    the persistence window completes, not every bar it continues to hold
  - Exit: numL drops below 2 — immediate, no persistence delay (an exit
    should never wait for confirmation the way an entry does, same principle
    used throughout this codebase's other engines)

The Pine script's ATR stop/target lines are COSMETIC ONLY — its actual exit
trigger is purely the lock-count drop above, and the webhook payload it sends
carries no stop/target price. A live position opened by this signal would be
protected by iam_executor's own real stop-loss order (IAM_STOP_LOSS_PCT),
same as every other engine here — not by anything computed in this module.
This backtest harness models that real behavior (see backtest_aether()).
"""
from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass
class AetherParams:
    fast: int = 5
    short: int = 30
    med: int = 80
    long: int = 200
    use_slope: bool = True
    slope_len: int = 3
    min_sep: float = 1.0
    use_vol_filter: bool = True
    vol_mult: float = 1.3
    vol_len: int = 20
    confirm_bars: int = 2

    @classmethod
    def from_env(cls) -> "AetherParams":
        return cls(
            fast=int(os.environ.get("AETHER_FAST", "5")),
            short=int(os.environ.get("AETHER_SHORT", "30")),
            med=int(os.environ.get("AETHER_MED", "80")),
            long=int(os.environ.get("AETHER_LONG", "200")),
            confirm_bars=int(os.environ.get("AETHER_CONFIRM_BARS", "2")),
        )


def _bar_val(bar: dict, *keys, default=0.0) -> float:
    for k in keys:
        v = bar.get(k)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return default


def _ema_series(values: list, period: int) -> list:
    """Standard EMA, seeded with the first value (matches Pine's ta.ema
    warmup behavior closely enough for signal purposes over long series)."""
    k = 2.0 / (period + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def _sma_series(values: list, period: int) -> list:
    out = []
    for i in range(len(values)):
        if i < period - 1:
            out.append(None)
        else:
            out.append(sum(values[i - period + 1:i + 1]) / period)
    return out


def compute_series(bars: list, p: AetherParams = None) -> dict:
    p = p or AetherParams.from_env()
    n = len(bars)
    closes = [_bar_val(b, "close", "c") for b in bars]
    volumes = [_bar_val(b, "volume", "v") for b in bars]

    ema5 = _ema_series(closes, p.fast)
    ema30 = _ema_series(closes, p.short)
    ema80 = _ema_series(closes, p.med)
    ema200 = _ema_series(closes, p.long)
    vol_ma = _sma_series(volumes, p.vol_len)

    num_l = [0] * n
    god_raw = [False] * n
    vol_pass = [True] * n

    for i in range(n):
        lock_s = ema5[i] > ema30[i]
        lock_m = ema5[i] > ema80[i]
        lock_l = ema5[i] > ema200[i]
        num_l[i] = int(lock_s) + int(lock_m) + int(lock_l)

        slope_ok = True
        if p.use_slope and i >= p.slope_len:
            slope_ok = all(ema5[i - j] > ema5[i - j - 1] for j in range(p.slope_len))
        elif p.use_slope:
            slope_ok = False
        sep_ok = ema200[i] != 0 and (ema5[i] - ema200[i]) / ema200[i] * 100 > p.min_sep
        god_raw[i] = (num_l[i] == 3) and slope_ok and sep_ok

        if p.use_vol_filter and vol_ma[i] is not None:
            vol_pass[i] = volumes[i] > vol_ma[i] * p.vol_mult

    def _persist_and_fire(raw: list, threshold_check) -> list:
        """raw: list[bool] per bar. Returns list[bool] True only on the bar
        the persistence window (confirm_bars consecutive True) just completed."""
        fires = [False] * n
        for i in range(n):
            if not raw[i] or not vol_pass[i]:
                continue
            if i < p.confirm_bars - 1:
                continue
            window_ok = all(raw[i - j] for j in range(p.confirm_bars))
            if not window_ok:
                continue
            # must not have already been firing on the bar before this window started
            prior_idx = i - p.confirm_bars
            already_qualified = prior_idx >= 0 and raw[prior_idx] and (vol_pass[prior_idx] if p.use_vol_filter else True)
            if already_qualified:
                continue
            fires[i] = True
        return fires

    num_l2_raw = [v >= 2 for v in num_l]
    num_l3_raw = [v == 3 for v in num_l]

    enter2 = _persist_and_fire(num_l2_raw, None)
    enter3 = _persist_and_fire(num_l3_raw, None)
    enterG = _persist_and_fire(god_raw, None)

    exit_l = [False] * n
    for i in range(1, n):
        exit_l[i] = num_l[i - 1] >= 2 and num_l[i] < 2

    return {
        "num_l": num_l, "god_raw": god_raw, "vol_pass": vol_pass,
        "enter2": enter2, "enter3": enter3, "enterG": enterG, "exit": exit_l,
        "ema5": ema5, "ema200": ema200,
    }


def analyze(symbol: str, bars: list, p: AetherParams = None) -> dict:
    """On-demand analysis of the LATEST bar — same convention as
    orb_engine.analyze()/breakout_engine.analyze()."""
    p = p or AetherParams.from_env()
    min_bars = max(p.long, p.vol_len) + p.confirm_bars + 5
    if not bars or len(bars) < min_bars:
        return {"symbol": symbol.upper(), "status": "insufficient_data",
                "bars": len(bars or []), "min_bars": min_bars}

    out = compute_series(bars, p)
    last = len(bars) - 1
    signal = None
    tier = None
    if out["enterG"][last]:
        signal, tier = "BUY", "GODMODE"
    elif out["enter3"][last]:
        signal, tier = "BUY", "3"
    elif out["enter2"][last]:
        signal, tier = "BUY", "2"
    elif out["exit"][last]:
        signal = "SELL"

    return {
        "symbol": symbol.upper(), "status": "success",
        "price": _bar_val(bars[-1], "close", "c"),
        "signal": signal, "tier": tier,
        "num_l": out["num_l"][last], "godmode": out["god_raw"][last],
        "volume_ok": out["vol_pass"][last],
    }
