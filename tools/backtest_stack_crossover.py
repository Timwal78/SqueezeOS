"""
Simple 2-EMA crossover backtest — Stack 1 (55/365) vs Stack 2 (30/741).

Same test another AI agent proposed (yfinance-based), ported onto this
repo's existing real Tradier data pipeline since yfinance/Yahoo Finance
is unreachable from this sandbox's network. Same methodology: long
while fast EMA > anchor EMA, flat otherwise, compared to buy-and-hold.

Stack 1 (55/365) mirrors CASCADE ACCUMULATOR's own fast EMA vs its
365-day anchor. Stack 2 (30/741) mirrors the 741 Pure Macro Matrix's
documented example periods (real server config unknown - see
backtest_handoff_brief.md).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import List

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


def _run_stack(closes: List[float], fast_period: int, anchor_period: int) -> dict:
    min_bars = anchor_period + 5
    if len(closes) < min_bars:
        return {"skipped": True, "skip_reason": f"only {len(closes)} bars, need {min_bars}+"}

    ema_fast = _ema(closes, fast_period)
    ema_anchor = _ema(closes, anchor_period)

    in_pos = False
    equity = 1.0
    trades = 0
    wins = 0
    entry_price = 0.0
    peak, max_dd = -float("inf"), 0.0

    for i in range(anchor_period, len(closes)):
        above = ema_fast[i] > ema_anchor[i]
        close = closes[i]

        if not in_pos and above:
            in_pos, entry_price = True, close
        elif in_pos and not above:
            trades += 1
            if close > entry_price:
                wins += 1
            in_pos = False

        if in_pos and i > anchor_period:
            equity *= closes[i] / closes[i - 1]

        peak = max(peak, equity)
        if peak > 0:
            max_dd = max(max_dd, (peak - equity) / peak)

    if in_pos:
        trades += 1
        if closes[-1] > entry_price:
            wins += 1

    total_return_pct = round((equity - 1) * 100, 2)
    return {
        "skipped": False,
        "trade_count": trades,
        "win_rate_pct": round(100 * wins / trades, 1) if trades else None,
        "total_return_pct": total_return_pct,
        "max_drawdown_pct": round(max_dd * 100, 2),
    }


def _buy_and_hold(closes: List[float]) -> dict:
    if len(closes) < 2:
        return {"skipped": True, "skip_reason": "insufficient bars"}
    total_return_pct = round((closes[-1] / closes[0] - 1) * 100, 2)
    peak, max_dd = -float("inf"), 0.0
    for c in closes:
        peak = max(peak, c)
        if peak > 0:
            max_dd = max(max_dd, (peak - c) / peak)
    return {"skipped": False, "total_return_pct": total_return_pct, "max_drawdown_pct": round(max_dd * 100, 2)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", default="SPY,QQQ,AAPL,MSFT,NVDA,TSLA,AMD,META,AMC,GME")
    parser.add_argument("--days", type=int, default=1095)
    parser.add_argument("--out", default="stack_crossover_results.json")
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
            "stack1_55_365": _run_stack(closes, 55, 365),
            "stack2_30_741": _run_stack(closes, 30, 741),
            "buy_and_hold": _buy_and_hold(closes),
        }

    with open(args.out, "w") as f:
        json.dump(results, f, indent=2)

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
