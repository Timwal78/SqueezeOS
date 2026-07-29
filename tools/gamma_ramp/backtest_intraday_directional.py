#!/usr/bin/env python3
"""
Gamma Ramp — Real Intraday Directional Backtest
=================================================
Supersedes backtest_gamma_ramp.py's daily-bar run for evidence purposes.
That backtest had two real problems, found during a full audit of this
desk (2026-07-29):
  1. option_path() priced trades with a hand-built synthetic option-premium
     formula (arbitrary leverage multipliers, quadratic move bonuses, flat
     -4%/day theta) with no empirical validation against real option
     prices -- its -61% drawdown result mostly measured the properties of
     that invented formula, not the strategy.
  2. It ran on DAILY bars while this desk is explicitly designed for 0-3
     DTE index scalps / 7-21 DTE equity swings (edge_stack.py's own
     documented DTE windows) -- the same timeframe-mismatch class already
     flagged for RSI-ML elsewhere in this codebase.
backtest_gamma_ramp.py is left in place (not deleted) since it does still
validate the STRUCTURE (gates fire, both sides route, exits are two-sided)
-- it just was never reliable evidence of profitability either way.

This backtest instead follows the same honest convention already
established and trusted in this codebase for DRUCK/MM-Intel/Breakout: real
intraday bars (5-minute, via Robinhood, matching MM-Intel's own precedent),
the REAL edge_stack.evaluate_edge() gate stack unmodified, and a real
ATR-stop / R:R-target / trailing-stop position state machine applied to
the UNDERLYING's own price move -- NOT a synthetic option-premium formula.

WHAT THIS MEASURES: whether the edge stack's CALL/PUT direction call has
real predictive edge on the underlying's subsequent move.

WHAT THIS DOES NOT MEASURE: actual 0DTE-to-3DTE options P&L. Real option
leverage (delta/gamma), theta decay, and bid-ask spread are NOT modeled --
same disclosed limitation as docs/MM_INTEL_BACKTEST_2026-07-25.md ("this
backtest did not model options at all... it traded the underlying's
directional %-move only... real 0DTE theta decay could easily invert these
numbers once actual option premium/spread is priced in"). A positive
result here is necessary but not sufficient for the options strategy to
work; it is the honest question this data can actually answer.

No lookahead: signals are computed using bar i's data (matches
edge_stack.evaluate_edge()'s own no-lookahead design), entries fill at bar
i+1's OPEN, stops/targets are checked against each subsequent bar's real
high/low, trailing stop only ever ratchets in the trade's favor.

Usage:
  python tools/gamma_ramp/backtest_intraday_directional.py data/SPY_5min.csv data/QQQ_5min.csv ...

CSV columns expected (case-insensitive): t,o,h,l,c,v (or date,open,high,low,close,volume)
"""
from __future__ import annotations

import csv
import os
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from edge_stack import (  # noqa: E402
    HARD_STOP,
    RVOL_EXIT,
    edge_checklist,
    evaluate_edge,
    realized_vol_at,
    vpin_proxy_series,
)

# ── Equity-appropriate risk parameters (NOT the options 50-500% scale --
# these apply to the underlying's own %-move) ──────────────────────────────
ATR_LEN = 14
ATR_STOP_MULT = 1.5      # stop = entry -/+ 1.5x ATR
TARGET_R = 2.0           # target = 2R (2x the stop distance)
TRAIL_ARM_R = 1.0        # start trailing once 1R of profit is banked
TRAIL_ATR_MULT = 1.2     # trail distance in ATR once armed
MAX_HOLD_BARS = 234      # ~3 RTH days at 5-min bars (78 bars/day), matches
                          # edge_stack's own 0-3 DTE window for index/ETF style
COOLDOWN_BARS = 12       # ~1 hour, avoid immediately re-signaling the same name


@dataclass
class Bar:
    t: str
    o: float
    h: float
    l: float
    c: float
    v: float


@dataclass
class Trade:
    symbol: str
    side: str
    entry_i: int
    exit_i: int
    entry_px: float
    exit_px: float
    stop_px: float
    target_px: float
    ret: float
    reason: str
    hold_bars: int
    rvol: float
    zscore: float
    vpin: float
    gates_passed: int


def load_csv(path: str) -> List[Bar]:
    bars: List[Bar] = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            k = {c.lower().strip(): v for c, v in row.items()}
            try:
                t = k.get("t") or k.get("date") or k.get("begins_at") or ""
                o = float(k.get("o") or k.get("open"))
                h = float(k.get("h") or k.get("high"))
                l = float(k.get("l") or k.get("low"))
                c = float(k.get("c") or k.get("close"))
                v = float(k.get("v") or k.get("volume") or 0)
            except (KeyError, ValueError, TypeError):
                continue
            if min(o, h, l, c) <= 0:
                continue
            bars.append(Bar(t=t, o=o, h=h, l=l, c=c, v=v))
    return bars


def atr_series(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, n: int = ATR_LEN) -> np.ndarray:
    """Standard Wilder-style True Range, simple rolling mean (no lookahead --
    ATR at bar i uses only bars up to and including i)."""
    length = len(closes)
    tr = np.zeros(length)
    tr[0] = highs[0] - lows[0]
    for i in range(1, length):
        tr[i] = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
    out = np.full(length, np.nan)
    for i in range(n, length):
        out[i] = float(np.mean(tr[i - n + 1 : i + 1]))
    return out


def backtest_symbol(symbol: str, bars: List[Bar]) -> Tuple[List[Trade], Dict]:
    if len(bars) < 60:
        return [], {"symbol": symbol, "error": "thin_history", "bars": len(bars), "trades": 0}

    opens = np.array([b.o for b in bars], float)
    highs = np.array([b.h for b in bars], float)
    lows = np.array([b.l for b in bars], float)
    closes = np.array([b.c for b in bars], float)
    vols = np.array([b.v for b in bars], float)
    vpin, signed = vpin_proxy_series(highs, lows, closes, vols)
    rvs = np.array([realized_vol_at(closes, i) for i in range(len(closes))])
    atr = atr_series(highs, lows, closes)

    trades: List[Trade] = []
    i = 30
    cool_until = -1

    while i < len(bars) - 2:
        if i < cool_until:
            i += 1
            continue

        edge = evaluate_edge(symbol, i, opens, highs, lows, closes, vols, vpin, signed, rvs)
        if edge.side == "NONE":
            i += 1
            continue

        a = float(atr[i]) if not np.isnan(atr[i]) else 0.0
        if a <= 0:
            i += 1
            continue

        # No lookahead: enter at NEXT bar's open, not the signal bar's own close.
        entry_i = i + 1
        entry_px = float(opens[entry_i])
        sign = 1.0 if edge.side == "CALL" else -1.0
        stop_px = entry_px - sign * ATR_STOP_MULT * a
        risk = abs(entry_px - stop_px)
        target_px = entry_px + sign * TARGET_R * risk

        end = min(len(bars) - 1, entry_i + MAX_HOLD_BARS)
        exit_j = end
        exit_px = float(closes[end])
        reason = "time"
        trail_armed = False
        trail_stop = stop_px

        for j in range(entry_i, end + 1):
            h, l, c = float(highs[j]), float(lows[j]), float(closes[j])
            # Stop check first (conservative -- assume adverse fill within the bar)
            if sign > 0 and l <= (trail_stop if trail_armed else stop_px):
                exit_j, exit_px, reason = j, (trail_stop if trail_armed else stop_px), "stop"
                break
            if sign < 0 and h >= (trail_stop if trail_armed else stop_px):
                exit_j, exit_px, reason = j, (trail_stop if trail_armed else stop_px), "stop"
                break
            # Target
            if sign > 0 and h >= target_px:
                exit_j, exit_px, reason = j, target_px, "target"
                break
            if sign < 0 and l <= target_px:
                exit_j, exit_px, reason = j, target_px, "target"
                break
            # Arm/ratchet trailing stop once 1R is in hand
            profit_r = sign * (c - entry_px) / risk if risk > 0 else 0.0
            if profit_r >= TRAIL_ARM_R:
                trail_armed = True
                new_trail = c - sign * TRAIL_ATR_MULT * a
                if sign > 0:
                    trail_stop = max(trail_stop, new_trail)
                else:
                    trail_stop = min(trail_stop, new_trail) if trail_stop != stop_px else new_trail
            # RVOL fade exit while in profit -- matches edge_stack's own
            # documented exit philosophy ("RVOL fade in profit -> exit")
            if j > entry_i and profit_r > 0:
                from edge_stack import rvol_at
                rv = rvol_at(vols, j)
                if not np.isnan(rv) and rv < RVOL_EXIT:
                    exit_j, exit_px, reason = j, c, "rvol_fade"
                    break

        ret = sign * (exit_px - entry_px) / entry_px
        trades.append(Trade(
            symbol=symbol, side=edge.side, entry_i=entry_i, exit_i=exit_j,
            entry_px=round(entry_px, 4), exit_px=round(exit_px, 4),
            stop_px=round(stop_px, 4), target_px=round(target_px, 4),
            ret=float(ret), reason=reason, hold_bars=int(exit_j - entry_i),
            rvol=edge.rvol, zscore=edge.zscore, vpin=edge.vpin,
            gates_passed=edge.gates_passed,
        ))
        cool_until = exit_j + COOLDOWN_BARS
        i = cool_until + 1

    stats: Dict = {"symbol": symbol, "bars": len(bars), "trades": len(trades)}
    if trades:
        rets = np.array([t.ret for t in trades])
        wins = rets[rets > 0]
        losses = rets[rets <= 0]
        gross_win = float(np.sum(wins)) if len(wins) else 0.0
        gross_loss = float(-np.sum(losses)) if len(losses) else 0.0
        stats.update({
            "win_rate": float(np.mean(rets > 0)),
            "avg_ret_pct": float(np.mean(rets) * 100),
            "profit_factor": (gross_win / gross_loss) if gross_loss > 0 else (float("inf") if gross_win > 0 else 0.0),
            "total_ret_pct": float(np.sum(rets) * 100),
            "best_pct": float(np.max(rets) * 100),
            "worst_pct": float(np.min(rets) * 100),
            "calls": sum(1 for t in trades if t.side == "CALL"),
            "puts": sum(1 for t in trades if t.side == "PUT"),
            "exit_reasons": {r: sum(1 for t in trades if t.reason == r) for r in set(t.reason for t in trades)},
            "avg_hold_bars": float(np.mean([t.hold_bars for t in trades])),
        })
    return trades, stats


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(argv or sys.argv[1:])
    if not argv:
        print("Usage: backtest_intraday_directional.py file1.csv file2.csv ...")
        return 1

    print("=== GAMMA RAMP INTRADAY DIRECTIONAL BACKTEST (real bars, ATR stop/2R target) ===")
    print(f"stop={ATR_STOP_MULT}xATR target={TARGET_R}R trail_arm={TRAIL_ARM_R}R max_hold={MAX_HOLD_BARS}bars")
    print(f"edge_stack: {edge_checklist()['name']}")

    all_trades: List[Trade] = []
    for path in argv:
        symbol = Path(path).stem.split("_")[0].upper()
        bars = load_csv(path)
        trades, stats = backtest_symbol(symbol, bars)
        all_trades.extend(trades)
        wr = stats.get("win_rate")
        pf = stats.get("profit_factor")
        print(
            f"  {symbol:6} bars={stats.get('bars',0):5} n={stats.get('trades',0):3} "
            f"C/P={stats.get('calls',0)}/{stats.get('puts',0)} "
            f"win={('n/a' if wr is None else f'{wr*100:5.1f}%')} "
            f"PF={('n/a' if pf is None else f'{pf:5.2f}')} "
            f"total={stats.get('total_ret_pct', 0):+7.2f}% "
            f"{stats.get('exit_reasons', {})}"
        )

    if all_trades:
        rets = np.array([t.ret for t in all_trades])
        wins = rets[rets > 0]
        losses = rets[rets <= 0]
        gross_win = float(np.sum(wins)) if len(wins) else 0.0
        gross_loss = float(-np.sum(losses)) if len(losses) else 0.0
        pf = (gross_win / gross_loss) if gross_loss > 0 else (float("inf") if gross_win > 0 else 0.0)
        print("\n=== AGGREGATE (all symbols) ===")
        print(f"  trades: {len(all_trades)}")
        print(f"  win_rate: {np.mean(rets>0)*100:.1f}%")
        print(f"  profit_factor: {pf:.2f}")
        print(f"  avg_ret: {np.mean(rets)*100:+.2f}%")
        print(f"  calls: {sum(1 for t in all_trades if t.side=='CALL')}  puts: {sum(1 for t in all_trades if t.side=='PUT')}")
    else:
        print("\nNo trades fired across the full universe/window.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
