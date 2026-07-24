"""
CIE Backtest — real historical bars only, no synthetic data.
==============================================================
Walks an expanding window of real Daily (or Weekly, aggregated) bars
through cycle_intelligence_engine.analyze(), simulating a long-only,
no-lookahead trade on every qualifying signal: entries fill at the NEXT
bar's open after the signal bar; positions are held a fixed
CIE_BT_HOLD_BARS bars (default 10, matching the fractal matcher's own
forward-return horizon) then closed at that bar's close.

SCOPE LIMITATION — read before trusting any result this prints:
Settlement layer (real SEC FTD/threshold data) and dark-pool layer (no
real feed exists anywhere in this codebase) are BOTH unavailable in a
historical backtest — SEC's FTD archive isn't pulled here, and there is
no dark-pool print source to backtest against at all. That leaves only
the fractal + meme-cycle axes active, so full CIE_FIRE (which needs
composite_z >= 3.0 with >=2 axes active — realistically unreachable from
just those two axes maxing out simultaneously) essentially never fires.
This harness instead enters on state in (PRIMED, CIE_FIRE) with a
resolved BUY direction — a materially weaker bar than production's
CIE_FIRE, and NOT what a live, fully-fed CIE would trigger on. Any
verdict here describes "fractal+meme convergence only", not the full
4-axis engine. Say so in any writeup — do not round this off to
"CIE backtest" without the caveat.

No lookahead: analyze() only ever sees bars[:i+1] when evaluating bar i.
Entries fill at bars[i+1]'s open. Long-only (no short leg in this pass).
No stop-loss in this v1 harness — pure fixed-horizon exit only.

Usage:
  python tests/backtest_cie.py data/gme_1d.csv data/spy_1d.csv ...
  CIE_BT_HOLD_BARS=15 python tests/backtest_cie.py ...

CSV columns expected (case-insensitive): date,open,high,low,close,volume
"""
from __future__ import annotations

import csv
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cycle_intelligence_engine import analyze, CIE_CONFIG  # noqa: E402

HOLD_BARS = int(os.environ.get("CIE_BT_HOLD_BARS", "10"))
WARMUP = CIE_CONFIG["hfm_window"] + 40  # enough history for a real signature library


def load_csv(path: str) -> list:
    bars = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            k = {c.lower().strip(): v for c, v in row.items()}
            try:
                bars.append({
                    "date": k["date"],
                    "o": float(k["open"]), "h": float(k["high"]),
                    "l": float(k["low"]), "c": float(k["close"]),
                    "v": float(k.get("volume", 0) or 0),
                })
            except (KeyError, ValueError):
                continue
    return bars


def simulate(bars: list, symbol: str) -> dict:
    trades = []
    pos = None  # {"entry_i": int, "entry_px": float}
    signals_seen = 0

    n = len(bars)
    for i in range(WARMUP, n - 1):
        window = bars[: i + 1]  # no lookahead — only bars up to and including i

        if pos is not None:
            held = i - pos["entry_i"]
            if held >= HOLD_BARS:
                exit_px = bars[i]["c"]
                pct = (exit_px / pos["entry_px"] - 1.0) * 100.0
                trades.append({"pct": pct, "bars_held": held, "entry_i": pos["entry_i"]})
                pos = None
            continue  # don't stack entries while a position is open

        result = analyze(symbol, window, today=None)
        if result.get("status") != "success":
            continue
        if result.get("state") in ("PRIMED", "CIE_FIRE") and result.get("direction") == "BUY":
            signals_seen += 1
            entry_px = bars[i + 1]["o"]  # fill at NEXT bar's open — no lookahead
            pos = {"entry_i": i + 1, "entry_px": entry_px}

    # close any still-open position at the last available bar
    if pos is not None:
        exit_px = bars[-1]["c"]
        pct = (exit_px / pos["entry_px"] - 1.0) * 100.0
        trades.append({"pct": pct, "bars_held": n - 1 - pos["entry_i"], "entry_i": pos["entry_i"]})

    wins = [t for t in trades if t["pct"] > 0]
    losses = [t for t in trades if t["pct"] <= 0]
    gross_win = sum(t["pct"] for t in wins)
    gross_loss = abs(sum(t["pct"] for t in losses))
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else (float("inf") if gross_win > 0 else 0.0)
    total_pct = sum(t["pct"] for t in trades)

    return {
        "symbol": symbol,
        "bars": n,
        "signals_seen": signals_seen,
        "trades": len(trades),
        "win_rate": round(100.0 * len(wins) / len(trades), 2) if trades else None,
        "profit_factor": round(profit_factor, 3) if trades else None,
        "total_pct": round(total_pct, 2),
        "avg_pct_per_trade": round(total_pct / len(trades), 3) if trades else None,
    }


def main():
    paths = sys.argv[1:]
    if not paths:
        print(__doc__)
        print("No CSV paths given — nothing to backtest.")
        sys.exit(1)

    print(f"HOLD_BARS={HOLD_BARS}  WARMUP={WARMUP} bars")
    print("=" * 78)
    all_results = []
    for path in paths:
        symbol = os.path.basename(path).split("_")[0].upper()
        bars = load_csv(path)
        if len(bars) < WARMUP + HOLD_BARS + 2:
            print(f"{symbol}: only {len(bars)} bars — need >= {WARMUP + HOLD_BARS + 2}, skipping")
            continue
        r = simulate(bars, symbol)
        all_results.append(r)
        print(f"{symbol:6s} bars={r['bars']:4d} signals={r['signals_seen']:3d} trades={r['trades']:3d} "
              f"win_rate={r['win_rate']}% PF={r['profit_factor']} total={r['total_pct']}% "
              f"avg/trade={r['avg_pct_per_trade']}%")

    print("=" * 78)
    if all_results:
        traded = [r for r in all_results if r["trades"]]
        print(f"{len(all_results)} symbols, {len(traded)} produced at least one trade, "
              f"{sum(r['trades'] for r in all_results)} total trades")


if __name__ == "__main__":
    main()
