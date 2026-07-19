"""
Supertrend Strategy Backtest — Python port of the operator's Pine strategy.
===========================================================================
Pine source (operator, 2026-07-19): ta.supertrend(factor, atrPeriod);
long on direction flip down, short on flip up — always in the market,
next-bar-open fills (TradingView strategy.entry semantics).

This harness ports ta.supertrend exactly (Wilder ATR, hl2 basis, band
ratchet) and adds:
  • --sweep: grid over ATR length × factor to find what the strategy can
    actually earn per symbol (in-sample tuning — treat best cells as an
    UPPER BOUND, not an expectation)
  • intraday mode: with 5-minute bars, optional EOD-flat variant
    (IAM/0DTE style — no overnight holds) alongside the always-in variant

Real bars only (CSV: date,open,high,low,close,volume). No synthetic data.

Usage:
  python tests/backtest_supertrend.py data/amc.csv data/gme.csv
  SWEEP=1 python tests/backtest_supertrend.py data/amc.csv
  EOD_FLAT=1 python tests/backtest_supertrend.py data/iwm_5m.csv
"""
from __future__ import annotations

import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orb_engine import bar_time_ny  # noqa: E402  (timestamp parsing, NY session)


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


def supertrend_directions(bars: list, atr_period: int, factor: float) -> list:
    """Returns per-bar direction: -1 = uptrend (long), +1 = downtrend (short).
    Exact port of Pine ta.supertrend (hl2 basis, Wilder ATR, band ratchet)."""
    dirs = [0] * len(bars)
    atr = None
    up_band = dn_band = None
    direction = 1
    for i, b in enumerate(bars):
        h, l, c = b["high"], b["low"], b["close"]
        if i == 0:
            atr = h - l
            up_band = (h + l) / 2 + factor * atr
            dn_band = (h + l) / 2 - factor * atr
            dirs[i] = direction
            continue
        pc = bars[i - 1]["close"]
        tr = max(h - l, abs(h - pc), abs(l - pc))
        atr = (atr * (atr_period - 1) + tr) / atr_period
        hl2 = (h + l) / 2
        basic_up = hl2 + factor * atr
        basic_dn = hl2 - factor * atr
        up_band = basic_up if (basic_up < up_band or pc > up_band) else up_band
        dn_band = basic_dn if (basic_dn > dn_band or pc < dn_band) else dn_band
        if c > up_band:
            direction = -1
        elif c < dn_band:
            direction = 1
        dirs[i] = direction
    return dirs


def simulate(bars: list, dirs: list, eod_flat: bool) -> dict:
    """Always-in flip strategy, next-bar-open fills. eod_flat: close any
    position on the session's last bar and re-enter next day only on a flip."""
    trades = []
    pos = None  # {"dir": ±1, "entry": px}
    ny = [bar_time_ny(b) for b in bars] if eod_flat else None

    for i in range(1, len(bars)):
        b = bars[i]
        flip = dirs[i - 1] != dirs[i - 2] if i >= 2 else False
        want = -1 if dirs[i - 1] == -1 else 1  # Pine: dir -1 = long
        last_of_day = False
        if eod_flat and ny is not None and ny[i] is not None:
            last_of_day = i == len(bars) - 1 or (ny[i + 1] is not None and ny[i + 1].date() != ny[i].date())

        if pos is not None and (flip or (eod_flat and last_of_day)):
            side = 1 if pos["dir"] == -1 else -1
            trades.append(side * (b["open"] / pos["entry"] - 1.0))
            pos = None
        if pos is None and flip and not (eod_flat and last_of_day):
            pos = {"dir": want, "entry": b["open"]}

    if pos is not None:
        side = 1 if pos["dir"] == -1 else -1
        trades.append(side * (bars[-1]["close"] / pos["entry"] - 1.0))

    n = len(trades)
    wins = [t for t in trades if t > 0]
    gw, gl = sum(wins), -sum(t for t in trades if t <= 0)
    equity = 1.0
    for t in trades:
        equity *= 1.0 + t
    peak, dd = 1.0, 0.0
    eq = 1.0
    for t in trades:
        eq *= 1.0 + t
        peak = max(peak, eq)
        dd = max(dd, 1.0 - eq / peak)
    return {"trades": n, "win_rate": len(wins) / n * 100 if n else 0.0,
            "profit_factor": gw / gl if gl > 0 else float("inf") if gw > 0 else 0.0,
            "total_pct": (equity - 1.0) * 100, "max_dd_pct": dd * 100}


def run(path: str, atr_period: int, factor: float, eod_flat: bool) -> dict:
    bars = load_csv(path)
    if len(bars) < 100:
        return {}
    dirs = supertrend_directions(bars, atr_period, factor)
    s = simulate(bars, dirs, eod_flat)
    s["buy_hold_pct"] = (bars[-1]["close"] / bars[0]["close"] - 1.0) * 100
    return s


def main(argv: list) -> int:
    if not argv:
        print("usage: python tests/backtest_supertrend.py <file.csv ...>")
        return 0
    eod_flat = os.environ.get("EOD_FLAT", "").strip() == "1"
    sweep = os.environ.get("SWEEP", "").strip() == "1"
    mode = "EOD-FLAT day-trade" if eod_flat else "always-in (Pine default)"

    if sweep:
        atrs = [7, 10, 14, 21]
        factors = [2.0, 2.5, 3.0, 3.5, 4.0]
        for path in argv:
            sym = os.path.basename(path).split(".")[0].upper()
            print(f"\n=== SWEEP {sym} ({mode}) — total% [trades] ===")
            atr_f_label = "ATR\\F"
            print(f"{atr_f_label:>6}" + "".join(f"{f:>14}" for f in factors))
            for a in atrs:
                row = f"{a:>6}"
                for f in factors:
                    s = run(path, a, f, eod_flat)
                    row += f"{s['total_pct']:>9.1f} [{s['trades']:>3}]" if s else f"{'—':>14}"
                print(row)
        return 0

    atr_period = int(os.environ.get("ST_ATR", "10"))
    factor = float(os.environ.get("ST_FACTOR", "3.0"))
    print(f"supertrend ATR={atr_period} factor={factor} | {mode}")
    header = f"{'symbol':<10}{'trades':>7}{'win%':>7}{'PF':>7}{'total%':>9}{'B&H%':>9}{'maxDD%':>8}"
    print(header)
    print("-" * len(header))
    for path in argv:
        sym = os.path.basename(path).split(".")[0].upper()
        s = run(path, atr_period, factor, eod_flat)
        if not s:
            print(f"{sym:<10} INSUFFICIENT REAL DATA")
            continue
        pf = f"{s['profit_factor']:.2f}" if s["profit_factor"] != float("inf") else "inf"
        print(f"{sym:<10}{s['trades']:>7}{s['win_rate']:>7.1f}{pf:>7}{s['total_pct']:>9.1f}{s['buy_hold_pct']:>9.1f}{s['max_dd_pct']:>8.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
