"""
DRUCK-LB v7 BeastMode Backtest — real historical bars only, no synthetic data.
==================================================================================
Drives druck_lb_v7_engine.compute_series over real bars and simulates the position
state machine: fixed ATR stop + R:R target set at entry, ratcheting ATR trailing
stop, and TradingView's default net-position "reversal" behavior (pyramiding=0 —
an opposite-direction signal closes the open position and immediately opens the
new one at the same fill, rather than requiring a flat state first).

See druck_lb_v7_engine.py's module docstring for the audit finding on why this
harness uses a FIXED entry-time stop/target rather than replicating the original
Pine script's every-bar-recalculated stop/limit (calling strategy.exit() on every
bar there updates the pending order's levels using that bar's current close/ATR,
not the entry price) — this harness tests the economically-intended strategy, not
a bit-exact reproduction of that Pine execution quirk.

No lookahead: entries fill at the NEXT bar's open after a signal bar. Stops/targets
checked using that bar's real high/low. Commission modeled as commission_pct per
side (round-trip = 2x), matching the Pine script's commission_type=percent,
commission_value=0.04.

Usage:
  python tests/backtest_druck_lb_v7.py data/amc_4h.csv data/gme_4h.csv ...
  DRUCKV7_ADX_TREND=20 python tests/backtest_druck_lb_v7.py ...

CSV columns expected (case-insensitive): date,open,high,low,close,volume
"date" must be ISO-8601 parseable.
"""
from __future__ import annotations

import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from druck_lb_v7_engine import DruckV7Params, compute_series  # noqa: E402


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


def simulate(bars: list, signals: list, atrs: list, p: DruckV7Params) -> dict:
    """
    pos = {"dir": +1|-1, "entry": px, "stop": px, "target": px, "trail": px,
           "atr_at_entry": px, "entry_i": int}
    trades = [{"pct": signed round-trip % net of commission, "bars_held": int,
               "reason": "STOP"|"TARGET"|"REVERSE"}]
    """
    trades = []
    pos = None
    commission = p.commission_pct / 100.0

    def _close_trade(exit_px: float, entry_i: int, reason: str):
        pct = pos["dir"] * (exit_px / pos["entry"] - 1.0)
        pct -= commission * 2  # entry + exit, each side
        trades.append({"pct": pct, "bars_held": i - entry_i, "reason": reason})

    for i in range(1, len(bars)):
        b = bars[i]
        sig = signals[i - 1]

        # ── 1. Manage an open position: ratchet trail, check stop/target ──
        if pos is not None and i > pos["entry_i"]:
            if pos["dir"] > 0:
                new_trail = b["close"] - pos["atr_at_entry"] * p.trail_atr_mult
                pos["trail"] = max(pos["trail"], new_trail)
                pos["stop"] = max(pos["stop"], pos["trail"])
                stop_hit = b["low"] <= pos["stop"]
                target_hit = b["high"] >= pos["target"]
            else:
                new_trail = b["close"] + pos["atr_at_entry"] * p.trail_atr_mult
                pos["trail"] = min(pos["trail"], new_trail)
                pos["stop"] = min(pos["stop"], pos["trail"])
                stop_hit = b["high"] >= pos["stop"]
                target_hit = b["low"] <= pos["target"]

            if stop_hit or target_hit:
                if stop_hit:
                    exit_px = min(pos["stop"], b["open"]) if pos["dir"] > 0 else max(pos["stop"], b["open"])
                    reason = "STOP"
                else:
                    exit_px = pos["target"]
                    reason = "TARGET"
                _close_trade(exit_px, pos["entry_i"], reason)
                pos = None

        # ── 2. New / reversing entry — fills at THIS bar's open if bar i-1 signaled ──
        if sig in ("BUY", "SELL"):
            want_dir = 1 if sig == "BUY" else -1
            if pos is not None and pos["dir"] != want_dir:
                # Net-position reversal (TradingView default, pyramiding=0):
                # close the open position and flip, same bar's open.
                _close_trade(b["open"], pos["entry_i"], "REVERSE")
                pos = None
            if pos is None:
                atr_at_entry = atrs[i - 1]
                if atr_at_entry and atr_at_entry > 0:
                    entry = b["open"]
                    stop = entry - atr_at_entry * p.atr_stop_mult if want_dir > 0 else entry + atr_at_entry * p.atr_stop_mult
                    target = entry + atr_at_entry * p.atr_stop_mult * p.rr_ratio if want_dir > 0 else entry - atr_at_entry * p.atr_stop_mult * p.rr_ratio
                    trail = entry - atr_at_entry * p.trail_atr_mult if want_dir > 0 else entry + atr_at_entry * p.trail_atr_mult
                    pos = {
                        "dir": want_dir, "entry": entry, "stop": stop, "target": target,
                        "trail": trail, "atr_at_entry": atr_at_entry, "entry_i": i,
                    }
            # same-direction repeat signal while already in that direction: no-op
            # (matches TradingView pyramiding=0 default — no stacking)

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
        "avg_bars_held": (sum(t["bars_held"] for t in trades) / n) if n else 0.0,
        "total_return_pct": (total - 1.0) * 100,
    }


def main(argv: list) -> int:
    if not argv:
        print("usage: python tests/backtest_druck_lb_v7.py <file.csv ...>")
        return 0
    p = DruckV7Params.from_env()
    print(f"params: ADX_trend={p.adx_trend} breakout_len={p.breakout_len} EMA={p.ema_fast}/{p.ema_slow} "
          f"RR={p.rr_ratio} stop_mult={p.atr_stop_mult} trail_mult={p.trail_atr_mult} HTF={p.use_htf}({p.htf_minutes}m) "
          f"vol_mult={p.vol_mult}")
    header = f"{'file':<16}{'trades':>7}{'win%':>7}{'avg%':>8}{'PF':>7}{'bars':>6}{'total%':>9}"
    print(header)
    print("-" * len(header))
    for path in argv:
        label = os.path.basename(path).split(".")[0]
        bars = load_csv(path)
        if len(bars) < 60:
            print(f"{label:<16} INSUFFICIENT REAL DATA ({len(bars)} bars) — skipping")
            continue
        result = compute_series(bars, p)
        s = simulate(bars, result["signals"], result["atr"], p)
        pf = f"{s['profit_factor']:.2f}" if s["profit_factor"] != float("inf") else "inf"
        print(f"{label:<16}{s['trades']:>7}{s['win_rate']:>7.1f}{s['avg_trade_pct']:>8.3f}"
              f"{pf:>7}{s['avg_bars_held']:>6.1f}{s['total_return_pct']:>9.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
