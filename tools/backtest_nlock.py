"""
N-Lock Confluence System — real design, real backtest, no invented numbers.

Design rationale (why this isn't the 90/95/105 system another agent proposed):
That system used three EMA pairs almost on top of each other (90/95/105) -
three near-copies of the same signal dressed up as "independent locks."
Real confluence needs genuinely distinct timeframes, so each lock actually
tells you something the others don't:

  Lock A (short-term momentum):  EMA10  > EMA30
  Lock B (medium-term trend):    EMA50  > EMA100
  Lock C (long-term regime):     EMA100 > EMA200

N-Lock = how many of the 3 are bullish right now (0-3). Trade at whatever
threshold you choose (1/2/3-Lock). Exit when the count drops below it.

Godmode is not "3-Lock plus an arbitrary extra EMA" (which just makes the
signal rarer without adding real information) - it's 3-Lock PLUS a genuine
volatility-normalized momentum filter: price must be extended above EMA200
by at least 1x its own 20-day ATR, confirming the trend has real force
behind it, not just technical alignment. This is a different kind of
information (magnitude, not just direction) - actual added selectivity,
not redundancy.

No number in this file's output is invented. It runs against real Tradier
history across the same 10-symbol universe used for every other backtest
in this audit, and reports exactly what happens - including if the answer
is "this doesn't beat buy-and-hold either." That's the whole point of
testing across many assets instead of tuning to one.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tradier_api as ta


def _ema(values: List[float], period: int) -> List[float]:
    if not values:
        return []
    k = 2.0 / (period + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1.0 - k))
    return out


def _atr(closes: List[float], period: int = 20) -> List[Optional[float]]:
    """True range approximated from closes only (no high/low fetched here) -
    absolute daily change, smoothed. A real ATR would use high/low/close;
    this is a close-only proxy, clearly labeled as such."""
    if len(closes) < 2:
        return [None] * len(closes)
    tr = [0.0] + [abs(closes[i] - closes[i - 1]) for i in range(1, len(closes))]
    out: List[Optional[float]] = [None] * len(closes)
    for i in range(len(closes)):
        if i < period:
            continue
        window = tr[i - period + 1 : i + 1]
        out[i] = sum(window) / len(window)
    return out


def _run_system(closes: List[float], threshold: int, godmode: bool = False) -> dict:
    min_bars = 200 + 25
    if len(closes) < min_bars:
        return {"skipped": True, "skip_reason": f"only {len(closes)} bars, need {min_bars}+"}

    ema10 = _ema(closes, 10)
    ema30 = _ema(closes, 30)
    ema50 = _ema(closes, 50)
    ema100 = _ema(closes, 100)
    ema200 = _ema(closes, 200)
    atr20 = _atr(closes, 20)

    in_pos = False
    entry_price = 0.0
    equity = 1.0
    trades = 0
    wins = 0
    days_in_market = 0
    total_days = 0
    peak, max_dd = -float("inf"), 0.0

    for i in range(200, len(closes)):
        lock_a = ema10[i] > ema30[i]
        lock_b = ema50[i] > ema100[i]
        lock_c = ema100[i] > ema200[i]
        locks = int(lock_a) + int(lock_b) + int(lock_c)

        if godmode:
            extension = (closes[i] - ema200[i])
            atr_val = atr20[i]
            extended_enough = (atr_val is not None and atr_val > 0 and extension > atr_val)
            active = (locks == 3) and extended_enough
        else:
            active = locks >= threshold

        close = closes[i]
        total_days += 1

        if not in_pos and active:
            in_pos, entry_price = True, close
        elif in_pos and not active:
            trades += 1
            if close > entry_price:
                wins += 1
            in_pos = False

        if in_pos:
            days_in_market += 1
            if i > 200:
                equity *= closes[i] / closes[i - 1]

        peak = max(peak, equity)
        if peak > 0:
            max_dd = max(max_dd, (peak - equity) / peak)

    if in_pos:
        trades += 1
        if closes[-1] > entry_price:
            wins += 1

    return {
        "skipped": False,
        "trade_count": trades,
        "win_rate_pct": round(100 * wins / trades, 1) if trades else None,
        "total_return_pct": round((equity - 1) * 100, 2),
        "time_in_market_pct": round(100 * days_in_market / total_days, 1) if total_days else None,
        "max_drawdown_pct": round(max_dd * 100, 2),
    }


def _buy_and_hold(closes: List[float]) -> dict:
    if len(closes) < 2:
        return {"skipped": True, "skip_reason": "insufficient bars"}
    return {"skipped": False, "total_return_pct": round((closes[-1] / closes[0] - 1) * 100, 2)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", default="SPY,QQQ,AAPL,MSFT,NVDA,TSLA,AMD,META,AMC,GME")
    parser.add_argument("--days", type=int, default=1095)
    parser.add_argument("--out", default="nlock_backtest_results.json")
    args = parser.parse_args()

    if not ta.is_available():
        print("ERROR: Tradier is not configured (TRADIER_API_KEY missing).", file=sys.stderr)
        sys.exit(1)

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    results = {}

    for symbol in symbols:
        df = ta.get_history_df(symbol, days=args.days)
        if df is None or df.empty:
            results[symbol] = {"skipped": True, "skip_reason": "no data from Tradier"}
            continue
        col = "Close" if "Close" in df.columns else df.columns[-1]
        closes = df[col].dropna().tolist()

        results[symbol] = {
            "bars_available": len(closes),
            "lock_1": _run_system(closes, 1),
            "lock_2": _run_system(closes, 2),
            "lock_3": _run_system(closes, 3),
            "godmode": _run_system(closes, 3, godmode=True),
            "buy_and_hold": _buy_and_hold(closes),
        }

    with open(args.out, "w") as f:
        json.dump(results, f, indent=2)

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
