"""
SML Support/Resistance Matrix Engine — Python implementation of the pivot
cross signals from indicators/SML_Support_Resistance_Matrix.pine (the
red/green '+' markers: plot(PivotHigh, style=cross, color=red, offset=-Bars) /
plot(PivotLow, style=cross, color=green, offset=-Bars)). Same convention as
imo_engine.py/orb_engine.py/druck_engine.py/breakout_engine.py — single
source of truth, Pine is a visual of the same math.

The Pine script itself defines no trading signal beyond these pivot crosses
(its zones and candle-pattern labels are informational only, no entry/exit
logic anywhere in the script). The live signal here is the operator-specified
rule backtested in docs/SR_MATRIX_PIVOT_BACKTEST_2026-07-25.md: long-only —
BUY when a pivot low confirms, SELL (close) when a pivot high confirms.

No lookahead: Pine's ta.pivotlow(Bars, Bars)/ta.pivothigh(Bars, Bars) only
confirm a pivot Bars bars AFTER it occurred (needs bars on both sides to know
it was a local extreme) — a pivot at bar i-Bars only becomes knowable at bar
i. live_signal[i] therefore reflects information genuinely available at bar
i, not the pivot bar itself.
"""
from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass
class SrMatrixParams:
    bars: int = 10  # pivot lookback, matches the Pine script's "Bars" input default

    @classmethod
    def from_env(cls) -> "SrMatrixParams":
        return cls(bars=int(os.environ.get("SR_MATRIX_BARS", "10")))


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


def _pivot_high(highs: list, n: int) -> list:
    out = [None] * len(highs)
    for i in range(n, len(highs) - n):
        window = highs[i - n:i + n + 1]
        if highs[i] == max(window) and window.count(highs[i]) == 1:
            out[i] = highs[i]
    return out


def _pivot_low(lows: list, n: int) -> list:
    out = [None] * len(lows)
    for i in range(n, len(lows) - n):
        window = lows[i - n:i + n + 1]
        if lows[i] == min(window) and window.count(lows[i]) == 1:
            out[i] = lows[i]
    return out


def compute_series(bars: list, p: SrMatrixParams = None) -> dict:
    p = p or SrMatrixParams.from_env()
    n = len(bars)
    highs = [_bar_val(b, "high", "h") for b in bars]
    lows = [_bar_val(b, "low", "l") for b in bars]

    ph = _pivot_high(highs, p.bars)
    pl = _pivot_low(lows, p.bars)

    confirmed_high = [False] * n
    confirmed_low = [False] * n
    live_signal = [None] * n

    for i in range(n):
        if i >= p.bars and ph[i - p.bars] is not None:
            confirmed_high[i] = True
            live_signal[i] = "SELL"
        if i >= p.bars and pl[i - p.bars] is not None:
            confirmed_low[i] = True
            # A bar can theoretically confirm both a high and a low
            # (extremely rare with a real strict-max/strict-min pivot
            # definition) -- SELL (protect gains) takes priority, matching
            # every other engine's "exits never blocked" convention.
            if live_signal[i] is None:
                live_signal[i] = "BUY"

    return {
        "pivot_high": ph, "pivot_low": pl,
        "confirmed_high": confirmed_high, "confirmed_low": confirmed_low,
        "live_signal": live_signal,
    }


def analyze(symbol: str, bars: list, p: SrMatrixParams = None) -> dict:
    """On-demand analysis of the LATEST bar — same convention as
    orb_engine.analyze()/breakout_engine.analyze()."""
    p = p or SrMatrixParams.from_env()
    min_bars = p.bars * 2 + 2
    if not bars or len(bars) < min_bars:
        return {"symbol": symbol.upper(), "status": "insufficient_data",
                "bars": len(bars or []), "min_bars": min_bars}

    out = compute_series(bars, p)
    last = len(bars) - 1
    return {
        "symbol": symbol.upper(), "status": "success",
        "price": _bar_val(bars[-1], "close", "c"),
        "signal": out["live_signal"][last],
        "pivot_high_confirmed": out["confirmed_high"][last],
        "pivot_low_confirmed": out["confirmed_low"][last],
        "params": {"bars": p.bars},
    }
