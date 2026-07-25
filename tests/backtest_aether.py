"""
AETHER 5-LOCK Backtest Harness — real data only, no synthetic bars.
======================================================================
Python port of indicators/AETHER_5LOCK_PROTOCOL_v8.pine (aether_engine.py)
plus a long-only execution simulation mirroring what would ACTUALLY happen
if this were wired to iam_executor (it currently is not — the Pine script's
webhook only fires if the user manually adds a matching TradingView alert):

  - Entry: enter2/enter3/enterG signal on bar N -> filled at bar N+1's open
    (no lookahead)
  - Exit: exitL (lock-count drop below 2) on bar N -> filled at bar N+1's open,
    OR a hard stop at entry*(1-stop_pct) if a bar's low touches it first —
    same IAM_STOP_LOSS_PCT-equivalent stop every other engine in this
    codebase gets automatically, since the Pine script's own ATR lines are
    cosmetic only (see aether_engine.py's module docstring)
  - One position at a time

Tests tier=2 and tier=3 separately (the script's own "Minimum Tier to Send
Live Signal" choice) since they produce meaningfully different trade counts.

Data: CSV files (date,open,high,low,close,volume) passed on the CLI.
"""
from __future__ import annotations

import csv
import os
import sys
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aether_engine import AetherParams, compute_series  # noqa: E402


@dataclass
class Bar:
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class Result:
    symbol: str
    tier: str
    trades: list = field(default_factory=list)
    strategy_return: float = 0.0
    buy_hold_return: float = 0.0
    max_drawdown: float = 0.0
    stop_exits: int = 0

    @property
    def wins(self):
        return [t for t in self.trades if t > 0]

    def summary(self) -> dict:
        n = len(self.trades)
        gross_win = sum(self.wins)
        gross_loss = -sum(t for t in self.trades if t <= 0)
        return {
            "symbol": self.symbol, "tier": self.tier, "trades": n,
            "win_rate": (len(self.wins) / n * 100) if n else 0.0,
            "profit_factor": (gross_win / gross_loss) if gross_loss > 0 else float("inf") if gross_win > 0 else 0.0,
            "stop_exits": self.stop_exits,
            "strategy_pct": self.strategy_return * 100,
            "buy_hold_pct": self.buy_hold_return * 100,
            "max_dd_pct": self.max_drawdown * 100,
        }


def simulate(symbol: str, bars: list, entries: list, exits: list, tier_label: str,
             stop_pct: float = 3.0) -> Result:
    res = Result(symbol, tier_label)
    equity = 1.0
    peak = 1.0
    entry = None
    stop = None

    for i in range(1, len(bars)):
        b = bars[i]
        entry_prev = entries[i - 1]
        exit_prev = exits[i - 1]

        if entry is not None:
            if b.low <= stop:
                exit_px = min(stop, b.open)
                pct = exit_px / entry - 1.0
                res.trades.append(pct)
                equity *= 1.0 + pct
                res.stop_exits += 1
                entry = stop = None
            elif exit_prev:
                pct = b.open / entry - 1.0
                res.trades.append(pct)
                equity *= 1.0 + pct
                entry = stop = None
        if entry is None and entry_prev:
            entry = b.open
            stop = entry * (1.0 - stop_pct / 100.0)

        peak = max(peak, equity)
        res.max_drawdown = max(res.max_drawdown, 1.0 - equity / peak)

    if entry is not None:
        pct = bars[-1].close / entry - 1.0
        res.trades.append(pct)
        equity *= 1.0 + pct

    res.strategy_return = equity - 1.0
    res.buy_hold_return = bars[-1].close / bars[0].close - 1.0
    return res


def load_csv(path: str) -> list:
    bars = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            k = {c.lower().strip(): v for c, v in row.items()}
            try:
                bars.append(Bar(k.get("date", ""), float(k["open"]), float(k["high"]),
                                float(k["low"]), float(k["close"]), float(k.get("volume", 0) or 0)))
            except (KeyError, ValueError):
                continue
    return bars


def main(argv: list) -> int:
    if not argv:
        print("usage: python tests/backtest_aether.py <file.csv ...>")
        return 0

    p = AetherParams()
    header = f"{'symbol':<8}{'tier':<10}{'trades':>7}{'win%':>7}{'PF':>7}{'stops':>7}{'strat%':>9}{'B&H%':>9}{'maxDD%':>8}"
    print(header)
    print("-" * len(header))
    for arg in argv:
        symbol = os.path.splitext(os.path.basename(arg))[0].upper()
        bars = load_csv(arg)
        if len(bars) < 220:
            print(f"{symbol:<8} INSUFFICIENT REAL DATA ({len(bars)} bars, need 220+ for EMA200 warmup) — skipping")
            continue
        dict_bars = [{"date": b.date, "open": b.open, "high": b.high,
                      "low": b.low, "close": b.close, "volume": b.volume} for b in bars]
        out = compute_series(dict_bars, p)
        for tier_label, entries in (("tier2", out["enter2"]), ("tier3", out["enter3"])):
            s = simulate(symbol, bars, entries, out["exit"], tier_label).summary()
            pf = f"{s['profit_factor']:.2f}" if s['profit_factor'] != float('inf') else "inf"
            print(f"{s['symbol']:<8}{s['tier']:<10}{s['trades']:>7}{s['win_rate']:>7.1f}{pf:>7}"
                  f"{s['stop_exits']:>7}{s['strategy_pct']:>9.1f}{s['buy_hold_pct']:>9.1f}{s['max_dd_pct']:>8.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
