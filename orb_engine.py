"""
ORB v6 BEASTMODE Engine — Opening Range Breakout × Kalman MM Inventory.
=======================================================================
The SINGLE Python implementation of the ORB+MM math. Consumers:

  • orb_scanner.py             — background intraday loop → iam_executor
  • core/api/orb_bp.py         — /api/orb status + on-demand analysis
  • tests/backtest_orb_mm.py   — intraday backtest harness

Mirrors indicators/SML_ORB_MM_Intelligence_v6.pine exactly:
  1. Opening range = first N minutes from 9:30 ET (per NY calendar day)
  2. Kalman-filtered dealer inventory from signed volume flow
     (mm_position = −net_flow; dealers absorb the other side)
  3. Signal only on OR breakout WITH dealers trapped on the wrong side:
     BUY  = close crosses above OR-high while inventory z ≤ −z_critical
     SELL = close crosses below OR-low  while inventory z ≥ +z_critical
  4. One signal per direction per day.

Intraday bars required (5-minute recommended). Bars must carry a parseable
timestamp; if none can be parsed the engine refuses rather than guessing
session boundaries. No synthetic data anywhere.

Env-tunable (all optional):
  ORB_MINUTES=15  ORB_MIN_PRICE=1.0  ORB_LAMBDA=0.15  ORB_Q=0.5  ORB_R=1.0
  ORB_INV_LOOKBACK=75  ORB_Z_CRITICAL=1.4
"""
from __future__ import annotations

import math
import os
import zoneinfo
from dataclasses import dataclass
from datetime import datetime, timezone

_TZ_NY = zoneinfo.ZoneInfo("America/New_York")


def _env_f(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key, default))
    except (TypeError, ValueError):
        return default


@dataclass
class OrbParams:
    or_minutes: int = 15
    min_price: float = 1.0
    lam: float = 0.15
    q_process: float = 0.5
    r_measurement: float = 1.0
    inv_lookback: int = 75
    z_critical: float = 1.4

    @classmethod
    def from_env(cls) -> "OrbParams":
        return cls(
            or_minutes=int(_env_f("ORB_MINUTES", 15)),
            min_price=_env_f("ORB_MIN_PRICE", 1.0),
            lam=_env_f("ORB_LAMBDA", 0.15),
            q_process=_env_f("ORB_Q", 0.5),
            r_measurement=_env_f("ORB_R", 1.0),
            inv_lookback=int(_env_f("ORB_INV_LOOKBACK", 75)),
            z_critical=_env_f("ORB_Z_CRITICAL", 1.4),
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


def bar_time_ny(bar: dict):
    """Parse a bar's timestamp into America/New_York. None if unparseable."""
    raw = bar.get("date") or bar.get("t") or bar.get("timestamp") or bar.get("begins_at")
    if raw is None:
        return None
    try:
        if isinstance(raw, (int, float)):
            ts = float(raw)
            if ts > 1e12:  # epoch ms
                ts /= 1000.0
            return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(_TZ_NY)
        s = str(raw).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(_TZ_NY)
    except Exception:
        return None


def compute_series(bars: list, p: OrbParams = None) -> dict:
    """
    Chronological intraday bars in → {"signals": [None|'BUY'|'SELL'], "state": {...}}.
    Signal semantics match the Pine script exactly (one per direction per day).
    """
    p = p or OrbParams.from_env()

    inv_est, inv_var = 0.0, 1.0
    inv_hist: list = []
    signals: list = [None] * len(bars)
    state: dict = {}

    cur_day = None
    or_h = or_l = None
    long_done = short_done = False
    prev_close = None
    prev_or_h = prev_or_l = None

    for i, bar in enumerate(bars):
        t = bar_time_ny(bar)
        if t is None:
            continue  # refuse to guess session boundaries
        o = _bar_val(bar, "open", "o")
        h = _bar_val(bar, "high", "h")
        l = _bar_val(bar, "low", "l")
        c = _bar_val(bar, "close", "c")
        v = _bar_val(bar, "volume", "v")
        if c <= 0:
            continue

        day = t.date()
        if day != cur_day:
            cur_day = day
            or_h = or_l = None
            long_done = short_done = False
            prev_or_h = prev_or_l = None

        cur_min = t.hour * 60 + t.minute
        in_or = 570 <= cur_min < 570 + p.or_minutes
        if in_or:
            or_h = h if or_h is None else max(or_h, h)
            or_l = l if or_l is None else min(or_l, l)

        # Kalman inventory (continuous across days, like the Pine `var`s)
        rng = h - l + 0.001
        buy_flow = v * (c - o) / rng if c > o else 0.0
        sell_flow = v * (o - c) / rng if c < o else 0.0
        mm_position = -(buy_flow - sell_flow)
        pred_inv = inv_est * (1.0 - p.lam)
        pred_var = inv_var + p.q_process ** 2
        k_gain = pred_var / (pred_var + p.r_measurement ** 2)
        inv_est = pred_inv + k_gain * (mm_position - pred_inv)
        inv_var = (1.0 - k_gain) * pred_var
        inv_hist.append(inv_est)

        inv_z = 0.0
        if len(inv_hist) >= p.inv_lookback:
            window = inv_hist[-p.inv_lookback:]
            m = sum(window) / len(window)
            var = sum((x - m) ** 2 for x in window) / (len(window) - 1)
            sd = math.sqrt(var)
            inv_z = (inv_est - m) / sd if sd > 0 else 0.0

        sig = None
        if (or_h is not None and not in_or and prev_close is not None
                and prev_or_h is not None and c >= p.min_price):
            cross_up = prev_close <= prev_or_h and c > or_h
            cross_dn = prev_close >= prev_or_l and c < or_l
            if cross_up and not long_done and inv_z <= -p.z_critical:
                sig = "BUY"
                long_done = True
            elif cross_dn and not short_done and inv_z >= p.z_critical:
                sig = "SELL"
                short_done = True
        signals[i] = sig

        prev_close = c
        prev_or_h, prev_or_l = or_h, or_l

        if i == len(bars) - 1:
            state = {
                "or_high": round(or_h, 4) if or_h is not None else None,
                "or_low": round(or_l, 4) if or_l is not None else None,
                "inventory_z": round(inv_z, 3),
                "mm_position": "SHORT" if inv_z > 0.5 else "LONG" if inv_z < -0.5 else "BALANCED",
                "long_fired_today": long_done,
                "short_fired_today": short_done,
                "signal": sig,
                "price": c,
                "bar_key": str(bar.get("date") or bar.get("t") or bar.get("timestamp") or len(bars)),
                "bars_used": len(bars),
                "session_day": str(cur_day),
            }

    return {"signals": signals, "state": state}


def analyze(symbol: str, bars: list, p: OrbParams = None) -> dict:
    """On-demand analysis of the LATEST intraday bar. Real bars only."""
    min_bars = (p or OrbParams.from_env()).inv_lookback + 10
    if not bars or len(bars) < min_bars:
        return {"symbol": symbol.upper(), "status": "insufficient_data",
                "bars": len(bars or []), "min_bars": min_bars}
    out = compute_series(bars, p)
    if not out["state"]:
        return {"symbol": symbol.upper(), "status": "insufficient_data",
                "bars": len(bars), "detail": "no parseable timestamps"}
    return {"symbol": symbol.upper(), "status": "success", **out["state"]}
