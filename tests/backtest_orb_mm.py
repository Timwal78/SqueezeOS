"""
ORB v6 BEASTMODE Backtest — real intraday bars only.
====================================================
Drives orb_engine.compute_series over real 5-minute bars and simulates the
strategy as a DAY TRADE, both directions:

  • signal on bar N → enter bar N+1 OPEN (long on BUY, short on SELL)
  • hard intraday stop: ORB_STOP_PCT (default 1.0%) from entry — a bar
    touching it exits AT the stop (gap-through fills at the worse open)
  • otherwise exit at the session's last bar close (no overnight holds —
    matches the OR-breakout day-trade design)
  • no lookahead, no synthetic bars

Usage:
  python tests/backtest_orb_mm.py data/spy_5m.csv data/qqq_5m.csv ...
  ORB_STOP_PCT=1.5 ORB_Z_CRITICAL=1.0 python tests/backtest_orb_mm.py ...
"""
from __future__ import annotations

import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orb_engine import OrbParams, compute_series, bar_time_ny  # noqa: E402


def load_csv(path: str) -> list:
    bars = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            k = {c.lower().strip(): v for c, v in row.items()}
            try:
                bars.append({"date": k["date"], "open": float(k["open"]), "high": float(k["high"]),
                             "low": float(k["low"]), "close": float(k["close"]),
                             "volume": float(k.get("volume", 0) or 0)})
            except (KeyError, ValueError):
                continue
    return bars


def simulate(bars: list, signals: list, stop_pct: float) -> dict:
    trades = []          # signed pct per round trip
    stop_exits = 0
    pos = None           # {"dir": +1|-1, "entry": px, "stop": px}
    days = set()

    ny = [bar_time_ny(b) for b in bars]
    for i in range(1, len(bars)):
        b = bars[i]
        t = ny[i]
        if t is None:
            continue
        days.add(t.date())
        last_of_day = i == len(bars) - 1 or (ny[i + 1] is not None and ny[i + 1].date() != t.date())

        if pos is not None:
            hit = (pos["dir"] > 0 and b["low"] <= pos["stop"]) or (pos["dir"] < 0 and b["high"] >= pos["stop"])
            if hit:
                exit_px = min(pos["stop"], b["open"]) if pos["dir"] > 0 else max(pos["stop"], b["open"])
                trades.append(pos["dir"] * (exit_px / pos["entry"] - 1.0))
                stop_exits += 1
                pos = None
            elif last_of_day:
                trades.append(pos["dir"] * (b["close"] / pos["entry"] - 1.0))
                pos = None

        if pos is None and not last_of_day and signals[i - 1] in ("BUY", "SELL"):
            d = 1 if signals[i - 1] == "BUY" else -1
            entry = b["open"]
            pos = {"dir": d, "entry": entry, "stop": entry * (1.0 - d * stop_pct / 100.0)}

    n = len(trades)
    wins = [t for t in trades if t > 0]
    gw, gl = sum(wins), -sum(t for t in trades if t <= 0)
    total = 1.0
    for t in trades:
        total *= 1.0 + t
    return {
        "sessions": len(days), "trades": n,
        "win_rate": len(wins) / n * 100 if n else 0.0,
        "avg_trade_pct": (sum(trades) / n * 100) if n else 0.0,
        "profit_factor": gw / gl if gl > 0 else float("inf") if gw > 0 else 0.0,
        "stop_exits": stop_exits,
        "total_return_pct": (total - 1.0) * 100,
    }


def main(argv: list) -> int:
    if not argv:
        print("usage: python tests/backtest_orb_mm.py <file_5m.csv ...>")
        return 0
    p = OrbParams.from_env()
    stop_pct = float(os.environ.get("ORB_STOP_PCT", "1.0"))
    print(f"params: OR={p.or_minutes}min z_crit={p.z_critical} stop={stop_pct}% (day-trade, both directions)")
    header = f"{'symbol':<8}{'days':>6}{'trades':>7}{'win%':>7}{'avg%':>7}{'PF':>7}{'stops':>6}{'total%':>8}"
    print(header)
    print("-" * len(header))
    for path in argv:
        symbol = os.path.basename(path).split("_")[0].split(".")[0].upper()
        bars = load_csv(path)
        if len(bars) < 200:
            print(f"{symbol:<8} INSUFFICIENT REAL DATA ({len(bars)} bars) — skipping")
            continue
        sigs = compute_series(bars, p)["signals"]
        s = simulate(bars, sigs, stop_pct)
        pf = f"{s['profit_factor']:.2f}" if s["profit_factor"] != float("inf") else "inf"
        print(f"{symbol:<8}{s['sessions']:>6}{s['trades']:>7}{s['win_rate']:>7.1f}{s['avg_trade_pct']:>7.3f}"
              f"{pf:>7}{s['stop_exits']:>6}{s['total_return_pct']:>8.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
