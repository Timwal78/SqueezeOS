"""
SML Breakout Engine — Python port of indicators/SML_Breakout_Target_Stop_v6.pine
====================================================================================
Single source of truth for the breakout math, same convention as imo_engine.py /
orb_engine.py / druck_engine.py (Pine script is a visual of the same logic — no
drift between chart and code). Also the same math independently verified in
docs/BREAKOUT_BACKTEST_2026-07-25.md (imported directly from mnemos/modules/
breakout_signal.py::detect_breakout() for that backtest; reimplemented here in
walk-forward form since this module needs full position-state tracking for the
on-demand /api/breakout/<symbol> display, not just a single yes/no per call).

Entry: classic Donchian N-day high/low break (close beyond the prior N bars'
high/low, excluding the current bar). Exit: fixed target-gain / stop-loss on
directional %-move.

Live-execution signal mapping (compute_series()'s "live_signal" per bar) is
DELIBERATELY NARROWER than the full backtest state machine: only fresh ENTRY
events (ENTER_UP -> BUY, ENTER_DOWN -> SELL) map to a live signal. EXIT_TARGET/
EXIT_STOP do NOT emit a live signal — matching the existing convention every
other engine in this codebase already uses (druck_engine.py, orb_engine.py):
none of them auto-fire a take-profit close either. iam_executor.py's SELL
action has a compound meaning here ("close any long AND open a bear/put leg" —
see _execute_tradier), not a pure flat-exit; reusing it for a target-hit exit
would silently add an un-backtested fresh short bet on every winning trade.
Downside protection instead comes from iam_executor's own real stop-loss order
(IAM_STOP_LOSS_PCT), placed automatically at BUY time exactly like every other
engine — this backtest's 5% stop is the chart/research model, not a literal
live take-profit/stop-loss executor.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
import os


@dataclass
class BreakoutParams:
    lookback: int = 20
    target_pct: float = 0.10
    stop_pct: float = 0.05

    @classmethod
    def from_env(cls) -> "BreakoutParams":
        return cls(
            lookback=int(os.environ.get("BREAKOUT_LOOKBACK", "20")),
            target_pct=float(os.environ.get("BREAKOUT_TARGET_PCT", "0.10")),
            stop_pct=float(os.environ.get("BREAKOUT_STOP_PCT", "0.05")),
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


def _bar_key(bar: dict, idx: int) -> str:
    return str(bar.get("date") or bar.get("t") or bar.get("timestamp") or idx)


def compute_series(bars: list, p: BreakoutParams = None) -> dict:
    """Full walk-forward position state machine — mirrors the Pine script and
    docs/BREAKOUT_BACKTEST_2026-07-25.md exactly (one open position at a time,
    entry at the breakout bar's close, exit checked on each subsequent bar's
    close, no intrabar fills, no lookahead)."""
    p = p or BreakoutParams.from_env()
    n = len(bars)
    highs  = [_bar_val(b, "high", "h") for b in bars]
    lows   = [_bar_val(b, "low", "l") for b in bars]
    closes = [_bar_val(b, "close", "c") for b in bars]

    events      = [None] * n   # "ENTER_UP" | "ENTER_DOWN" | "EXIT_TARGET" | "EXIT_STOP" | None
    live_signal = [None] * n   # "BUY" | "SELL" | None — narrower, see module docstring
    state_dir   = [None] * n   # direction of the position held AFTER this bar, if any
    pnl_pct     = [None] * n   # live/realized pnl at this bar, if in/just-closed a position

    in_pos = False
    direction: Optional[str] = None
    entry_price: Optional[float] = None

    for i in range(n):
        if i < p.lookback:
            continue
        window_start = i - p.lookback
        prior_high = max(highs[window_start:i])
        prior_low = min(lows[window_start:i])
        close = closes[i]

        if in_pos:
            if direction == "up":
                pnl = (close - entry_price) / entry_price
            else:
                pnl = (entry_price - close) / entry_price
            pnl_pct[i] = round(pnl * 100, 4)

            if pnl >= p.target_pct:
                events[i] = "EXIT_TARGET"
                if direction == "up":
                    live_signal[i] = "SELL"
                in_pos = False
                direction = None
                entry_price = None
                continue
            if pnl <= -p.stop_pct:
                events[i] = "EXIT_STOP"
                if direction == "up":
                    live_signal[i] = "SELL"
                in_pos = False
                direction = None
                entry_price = None
                continue
            state_dir[i] = direction
            continue

        if close > prior_high:
            in_pos = True
            direction = "up"
            entry_price = close
            events[i] = "ENTER_UP"
            live_signal[i] = "BUY"
            state_dir[i] = "up"
            pnl_pct[i] = 0.0
        elif close < prior_low:
            in_pos = True
            direction = "down"
            entry_price = close
            events[i] = "ENTER_DOWN"
            live_signal[i] = "SELL"
            state_dir[i] = "down"
            pnl_pct[i] = 0.0

    return {
        "events": events, "live_signal": live_signal,
        "state_dir": state_dir, "pnl_pct": pnl_pct,
        "in_pos": in_pos, "direction": direction, "entry_price": entry_price,
    }


def analyze(symbol: str, bars: list, p: BreakoutParams = None) -> dict:
    """On-demand analysis of the LATEST bar — same convention as
    orb_engine.analyze()/druck_engine.analyze(). Real bars only."""
    p = p or BreakoutParams.from_env()
    min_bars = p.lookback + 1  # index `lookback` is the first bar with a full prior window
    if not bars or len(bars) < min_bars:
        return {"symbol": symbol.upper(), "status": "insufficient_data",
                "bars": len(bars or []), "min_bars": min_bars}

    out = compute_series(bars, p)
    last = len(bars) - 1
    close = _bar_val(bars[-1], "close", "c")

    target_px = stop_px = None
    if out["in_pos"] and out["entry_price"]:
        if out["direction"] == "up":
            target_px = round(out["entry_price"] * (1 + p.target_pct), 4)
            stop_px = round(out["entry_price"] * (1 - p.stop_pct), 4)
        else:
            target_px = round(out["entry_price"] * (1 - p.target_pct), 4)
            stop_px = round(out["entry_price"] * (1 + p.stop_pct), 4)

    return {
        "symbol": symbol.upper(), "status": "success",
        "price": close,
        "event": out["events"][last],
        "signal": out["live_signal"][last],
        "position": {
            "in_position": out["in_pos"],
            "direction": out["direction"],
            "entry_price": out["entry_price"],
            "target_price": target_px,
            "stop_price": stop_px,
            "unrealized_pct": out["pnl_pct"][last] if out["in_pos"] else None,
        },
        "params": {"lookback": p.lookback, "target_pct": p.target_pct, "stop_pct": p.stop_pct},
    }
