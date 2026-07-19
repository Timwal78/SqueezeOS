"""
SML-IMO Backtest Harness — real data only, no synthetic bars.
=============================================================
Python port of indicators/SML_Institutional_Momentum_Oscillator_v6.pine
(Jurik core, volume-force momentum, dynamic variance bands, Kaufman-ER
regime filter, early hooks) plus a long-only execution simulation that
mirrors the IAM executor's rules:

  • BUY signals  (ignition long / fade long / early buy)  → enter next bar OPEN
  • SELL signals (ignition short / fade short / early sell) → exit next bar OPEN
  • Hard stop: entry × (1 − stop%) — if a bar's LOW touches it, exit AT the stop
  • One position at a time, full-notional units of 1 (percent math, no leverage)

No lookahead: signals computed on bar N are executed on bar N+1's open.

Data sources (in priority order):
  1. CSV files passed on the CLI:  python tests/backtest_imo.py data/*.csv
     Expected columns: date,open,high,low,close,volume  (header required)
  2. Tradier daily history (TRADIER_API_KEY set):
     python tests/backtest_imo.py SPY IWM AMC
Per the Prime Directive this harness NEVER generates fake bars — if it has
no real data it exits with an error.

Output: per-symbol trade stats + a strategy-vs-buy-hold comparison, printed
as a table. Exit code 0 always (it's a research tool, not a CI gate).
"""
from __future__ import annotations

import csv
import math
import os
import sys
from dataclasses import dataclass, field


# ──────────────────────────────────────────────────────────────────
# IMO math — the single implementation lives in imo_engine.py (shared
# with imo_scanner.py and /api/imo). This harness only converts bars
# and simulates execution.
# ──────────────────────────────────────────────────────────────────

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from imo_engine import ImoParams, compute_series  # noqa: E402


@dataclass
class Bar:
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float


def compute_signals(bars: list, p: ImoParams) -> list:
    """Returns a list (len == len(bars)) of None | 'BUY' | 'SELL' per bar."""
    dict_bars = [{"date": b.date, "open": b.open, "high": b.high,
                  "low": b.low, "close": b.close, "volume": b.volume} for b in bars]
    return compute_series(dict_bars, p)["signals"]


# ──────────────────────────────────────────────────────────────────
# Long-only simulation (mirrors IAM executor semantics)
# ──────────────────────────────────────────────────────────────────

@dataclass
class Result:
    symbol: str
    trades: list = field(default_factory=list)  # each: pct return
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
            "symbol": self.symbol,
            "trades": n,
            "win_rate": (len(self.wins) / n * 100) if n else 0.0,
            "avg_win": (gross_win / len(self.wins)) if self.wins else 0.0,
            "avg_loss": (gross_loss / (n - len(self.wins))) if n - len(self.wins) else 0.0,
            "profit_factor": (gross_win / gross_loss) if gross_loss > 0 else float("inf") if gross_win > 0 else 0.0,
            "stop_exits": self.stop_exits,
            "strategy_pct": self.strategy_return * 100,
            "buy_hold_pct": self.buy_hold_return * 100,
            "max_dd_pct": self.max_drawdown * 100,
        }


def simulate(symbol: str, bars: list, signals: list, p: ImoParams) -> Result:
    res = Result(symbol)
    equity = 1.0
    peak = 1.0
    entry = None
    stop = None

    for i in range(1, len(bars)):
        b = bars[i]
        sig_prev = signals[i - 1]

        if entry is not None:
            # hard stop first — intrabar low touches it, we're out at the stop
            if b.low <= stop:
                exit_px = min(stop, b.open)  # gap through the stop fills worse, be honest
                pct = exit_px / entry - 1.0
                res.trades.append(pct)
                equity *= 1.0 + pct
                res.stop_exits += 1
                entry = stop = None
            elif sig_prev == "SELL":
                pct = b.open / entry - 1.0
                res.trades.append(pct)
                equity *= 1.0 + pct
                entry = stop = None
        if entry is None and sig_prev == "BUY":
            entry = b.open
            stop = entry * (1.0 - p.stop_pct / 100.0)

        peak = max(peak, equity)
        res.max_drawdown = max(res.max_drawdown, 1.0 - equity / peak)

    if entry is not None:  # mark open position to last close
        pct = bars[-1].close / entry - 1.0
        res.trades.append(pct)
        equity *= 1.0 + pct

    res.strategy_return = equity - 1.0
    res.buy_hold_return = bars[-1].close / bars[0].close - 1.0
    return res


# ──────────────────────────────────────────────────────────────────
# Data loading — real bars only
# ──────────────────────────────────────────────────────────────────

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


def load_tradier(symbol: str) -> list:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import requests
    key = os.environ.get("TRADIER_API_KEY", "").strip()
    if not key:
        return []
    env = (os.environ.get("TRADIER_ENV") or "sandbox").strip().lower()
    base = "https://api.tradier.com/v1" if env == "production" else "https://sandbox.tradier.com/v1"
    r = requests.get(f"{base}/markets/history",
                     params={"symbol": symbol, "interval": "daily", "start": "2020-01-01"},
                     headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
                     timeout=30)
    days = ((r.json() or {}).get("history") or {}).get("day") or []
    if isinstance(days, dict):
        days = [days]
    return [Bar(d["date"], float(d["open"]), float(d["high"]), float(d["low"]),
                float(d["close"]), float(d.get("volume", 0) or 0)) for d in days]


def main(argv: list) -> int:
    p = ImoParams(stop_pct=float(os.environ.get("IAM_STOP_LOSS_PCT", "3.0")),
                  use_early=os.environ.get("IMO_USE_EARLY", "true").strip().lower() == "true")
    if not argv:
        print("usage: python tests/backtest_imo.py <file.csv ...  |  SYMBOL ...>")
        return 0

    header = f"{'symbol':<8}{'trades':>7}{'win%':>7}{'avgW%':>7}{'avgL%':>7}{'PF':>6}{'stops':>6}{'strat%':>9}{'B&H%':>9}{'maxDD%':>8}"
    print(header)
    print("-" * len(header))
    for arg in argv:
        if arg.lower().endswith(".csv"):
            symbol = os.path.splitext(os.path.basename(arg))[0].upper()
            bars = load_csv(arg)
        else:
            symbol, bars = arg.upper(), load_tradier(arg.upper())
        if len(bars) < 150:
            print(f"{symbol:<8} INSUFFICIENT REAL DATA ({len(bars)} bars) — no synthetic fallback, skipping")
            continue
        s = simulate(symbol, bars, compute_signals(bars, p), p).summary()
        pf = f"{s['profit_factor']:.2f}" if s['profit_factor'] != float('inf') else "inf"
        print(f"{s['symbol']:<8}{s['trades']:>7}{s['win_rate']:>7.1f}{s['avg_win']*100:>7.2f}{-s['avg_loss']*100:>7.2f}{pf:>6}"
              f"{s['stop_exits']:>6}{s['strategy_pct']:>9.1f}{s['buy_hold_pct']:>9.1f}{s['max_dd_pct']:>8.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
