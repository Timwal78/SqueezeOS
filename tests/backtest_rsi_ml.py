"""
SML RSI Multi Length PRO Backtest Harness — real data only, no synthetic bars.
=================================================================================
Long-only proxy simulation of the CALL/PUT crossover signal (rsi_ml_engine.py):
CALL -> enter long, PUT -> exit long, next-bar-open fill, no lookahead, one
position at a time, plus the same 3%-equivalent hard stop used elsewhere in
this codebase for comparability (this script is not wired to iam_executor,
so there is no real stop — this models what a live equivalent would look
like, same convention as backtest_aether.py/backtest_imo.py).

The Pine script's actual intended use is CALL/PUT OPTIONS entries (per its
own plotshape labels), not equity long/short — same "directional proxy, not
modeled option premium/theta/leverage" caveat as every other engine's
options-adjacent backtest in this repo.
"""
from __future__ import annotations

import csv
import os
import sys
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rsi_ml_engine import RsiMlParams, compute_series  # noqa: E402


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
            "symbol": self.symbol, "trades": n,
            "win_rate": (len(self.wins) / n * 100) if n else 0.0,
            "profit_factor": (gross_win / gross_loss) if gross_loss > 0 else float("inf") if gross_win > 0 else 0.0,
            "stop_exits": self.stop_exits,
            "strategy_pct": self.strategy_return * 100,
            "buy_hold_pct": self.buy_hold_return * 100,
            "max_dd_pct": self.max_drawdown * 100,
        }


def simulate(symbol: str, bars: list, cross_up: list, cross_dn: list, stop_pct: float = 3.0) -> Result:
    res = Result(symbol)
    equity = 1.0
    peak = 1.0
    entry = None
    stop = None

    for i in range(1, len(bars)):
        b = bars[i]
        up_prev = cross_up[i - 1]
        dn_prev = cross_dn[i - 1]

        if entry is not None:
            if b.low <= stop:
                exit_px = min(stop, b.open)
                pct = exit_px / entry - 1.0
                res.trades.append(pct)
                equity *= 1.0 + pct
                res.stop_exits += 1
                entry = stop = None
            elif dn_prev:
                pct = b.open / entry - 1.0
                res.trades.append(pct)
                equity *= 1.0 + pct
                entry = stop = None
        if entry is None and up_prev:
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
        print("usage: python tests/backtest_rsi_ml.py <file.csv ...>")
        return 0

    p = RsiMlParams()
    header = f"{'symbol':<8}{'trades':>7}{'win%':>7}{'PF':>7}{'stops':>7}{'strat%':>9}{'B&H%':>9}{'maxDD%':>8}"
    print(header)
    print("-" * len(header))
    for arg in argv:
        symbol = os.path.splitext(os.path.basename(arg))[0].upper()
        bars = load_csv(arg)
        if len(bars) < 65:
            print(f"{symbol:<8} INSUFFICIENT REAL DATA ({len(bars)} bars) — skipping")
            continue
        dict_bars = [{"date": b.date, "open": b.open, "high": b.high,
                      "low": b.low, "close": b.close, "volume": b.volume} for b in bars]
        out = compute_series(dict_bars, p)
        s = simulate(symbol, bars, out["cross_up"], out["cross_dn"]).summary()
        pf = f"{s['profit_factor']:.2f}" if s['profit_factor'] != float('inf') else "inf"
        print(f"{s['symbol']:<8}{s['trades']:>7}{s['win_rate']:>7.1f}{pf:>7}"
              f"{s['stop_exits']:>7}{s['strategy_pct']:>9.1f}{s['buy_hold_pct']:>9.1f}{s['max_dd_pct']:>8.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
