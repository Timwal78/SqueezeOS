"""
TTM Squeeze Engine Backtest — real historical bars only, no synthetic data.
==============================================================================
Drives ttm_squeeze_engine.compute_series() over real daily bars and reports
the honest verdict on the standalone squeeze-fire signal (isolated out of
squeeze_analyzer.py's 8-module composite for the first time, see
ttm_squeeze_engine.py's module docstring). compute_series() already runs the
FULL position state machine (ATR stop/target, both long and short) — this
harness just extracts closed trades from its pnl_pct/events output and
computes standard stats, same metrics convention as backtest_druck.py
(trades, win%, avg%, PF, total%).

No claim of profitability is made until this has actually been run against
real data — see the printed verdict, and cross-reference against
docs/TTM_SQUEEZE_BACKTEST_2026-07-30.md for the committed result.

Usage:
  python tests/backtest_ttm_squeeze.py data/spy_1d.csv data/qqq_1d.csv ...
"""
from __future__ import annotations

import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ttm_squeeze_engine import SqueezeParams, compute_series  # noqa: E402


def load_csv(path: str) -> list:
    bars = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            k = {c.lower().strip(): v for c, v in row.items()}
            try:
                bars.append({
                    "date": k["date"],
                    "open": float(k["open"]), "high": float(k["high"]),
                    "low": float(k["low"]), "close": float(k["close"]),
                    "volume": float(k.get("volume", 0) or 0),
                })
            except (KeyError, ValueError):
                continue
    return bars


def extract_trades(out: dict) -> list:
    """compute_series() already runs the full state machine -- pnl_pct[i] is
    set to the FINAL realized pct on the exact bar an EXIT_TARGET/EXIT_STOP
    event fires. Just walk the events array and pull those out."""
    trades = []
    for i, ev in enumerate(out["events"]):
        if ev in ("EXIT_TARGET", "EXIT_STOP"):
            trades.append({"pct": out["pnl_pct"][i] / 100.0, "reason": ev})
    return trades


def stats(trades: list) -> dict:
    n = len(trades)
    wins = [t for t in trades if t["pct"] > 0]
    gw = sum(t["pct"] for t in wins)
    gl = -sum(t["pct"] for t in trades if t["pct"] <= 0)
    total = 1.0
    for t in trades:
        total *= 1.0 + t["pct"]
    return {
        "trades": n,
        "win_rate": len(wins) / n * 100 if n else 0.0,
        "avg_trade_pct": (sum(t["pct"] for t in trades) / n * 100) if n else 0.0,
        "profit_factor": gw / gl if gl > 0 else float("inf") if gw > 0 else 0.0,
        "total_return_pct": (total - 1.0) * 100,
    }


def buy_and_hold_pct(bars: list) -> float:
    if len(bars) < 2:
        return 0.0
    return (bars[-1]["close"] / bars[0]["close"] - 1.0) * 100.0


def main(argv: list) -> int:
    if not argv:
        print("usage: python tests/backtest_ttm_squeeze.py <file_1d.csv ...>")
        return 0
    p = SqueezeParams.from_env()
    print(f"params: BB={p.bb_length}/{p.bb_mult} KC={p.kc_length}/{p.kc_mult} "
          f"mom_len={p.mom_length} ATR_stop={p.atr_stop_mult}x ATR_target={p.atr_target_mult}x")
    header = f"{'symbol':<8}{'bars':>6}{'fires':>7}{'trades':>7}{'win%':>7}{'avg%':>7}{'PF':>7}{'total%':>8}{'buyhold%':>10}"
    print(header)
    print("-" * len(header))

    agg_trades = []
    for path in argv:
        symbol = os.path.basename(path).split("_")[0].upper()
        bars = load_csv(path)
        if len(bars) < 200:
            print(f"{symbol:<8} INSUFFICIENT REAL DATA ({len(bars)} bars) — skipping")
            continue
        out = compute_series(bars, p)
        trades = extract_trades(out)
        agg_trades.extend(trades)
        s = stats(trades)
        bh = buy_and_hold_pct(bars)
        fires = sum(1 for f in out["fired"] if f)
        pf = f"{s['profit_factor']:.2f}" if s["profit_factor"] != float("inf") else "inf"
        print(f"{symbol:<8}{len(bars):>6}{fires:>7}{s['trades']:>7}{s['win_rate']:>7.1f}"
              f"{s['avg_trade_pct']:>7.3f}{pf:>7}{s['total_return_pct']:>8.2f}{bh:>10.2f}")

    print("-" * len(header))
    agg = stats(agg_trades)
    pf = f"{agg['profit_factor']:.3f}" if agg["profit_factor"] != float("inf") else "inf"
    print(f"AGGREGATE: {agg['trades']} trades, win_rate={agg['win_rate']:.1f}%, "
          f"avg_trade={agg['avg_trade_pct']:.3f}%, PF={pf}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
