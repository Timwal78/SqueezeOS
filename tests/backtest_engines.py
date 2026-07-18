"""
Engine Evidence Scoreboard — real data only.
============================================
Runs every OHLCV-capable signal engine through the same long-only
simulation as tests/backtest_imo.py (next-bar entries, hard intrabar
stops, no lookahead) and prints a comparable scoreboard. This is the
measurement step of the operator's 2026-07-17 "delete what doesn't win"
directive — it produces evidence; it deletes nothing.

Engines covered:
  IMO      — indicators/SML_Institutional_Momentum_Oscillator_v6.pine (Python port)
  CASCADE  — avg_down_engine (ENTER/ADD → BUY, EXIT/STOP/HARD_STOP → SELL)
  IAM      — iam_engine.IAMEngine full committee, driven bar-by-bar with a
             rolling 252-bar history window. Gamma walls are passed empty —
             historical option chains are NOT available and will not be
             faked; the dealer analyst degrades exactly as it does in
             production when chains are missing.

Engines NOT covered (and why — no fake inputs, per the Prime Directive):
  gamma_flow, mmle (standalone), options_intelligence, iwm_odte,
  whale_stalker — all require recorded live options-flow/dark-pool data
  that does not exist historically in this repo.
  sml_engine.compute_all — requires simultaneous real history for the
  9-symbol macro complex (SPY VIX TLT DXY QQQ IWM IJR XRT + target);
  wiring that data set is future work, not a reason to synthesize it.

Usage:
  python tests/backtest_engines.py data/spy.csv data/iwm.csv ...
  IAM_STOP_LOSS_PCT=8 python tests/backtest_engines.py ...   # stop overlay
  ENGINES=IMO,CASCADE python tests/backtest_engines.py ...   # subset
"""
from __future__ import annotations

import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.disable(logging.ERROR)  # engines log per call; keep the scoreboard readable

from backtest_imo import Bar, ImoParams, compute_signals, load_csv, simulate  # noqa: E402


# ── Adapters — each returns a list (len == len(bars)) of None|'BUY'|'SELL' ──

def imo_signals(bars: list, p: ImoParams) -> list:
    return compute_signals(bars, p)


def cascade_signals(bars: list, p: ImoParams) -> list:
    import avg_down_engine as cascade
    cascade._positions.clear()
    closes = [b.close for b in bars]
    sigs = [None] * len(bars)
    warmup = 380  # L5 anchor is a 365-period EMA by default
    for i in range(warmup, len(bars)):
        s = cascade._evaluate("BACKTEST", closes[: i + 1], bars[i].date)
        if s:
            sigs[i] = "BUY" if s["action"] in ("ENTER", "ADD") else "SELL"
    cascade._positions.clear()
    return sigs


def iam_signals(bars: list, p: ImoParams) -> list:
    from iam_engine import IAMEngine
    eng = IAMEngine({})
    eng._cached = lambda key, fn, ttl=None: fn()  # no cross-bar caching
    eng._fetch_gamma_walls = lambda s, price: {}  # no historical chains — never faked
    sigs = [None] * len(bars)
    window = 252
    for i in range(window, len(bars)):
        hist = [{"open": b.open, "high": b.high, "low": b.low,
                 "close": b.close, "volume": b.volume}
                for b in bars[i - window + 1: i + 1]]
        eng._fetch_bars = lambda s, h=hist: h
        eng._fetch_quote = lambda s, b=bars[i]: {"price": b.close, "volume": b.volume}
        try:
            r = eng.resolve("BACKTEST")
        except Exception:
            continue
        action = (r.get("resolution") or {}).get("action")
        if action in ("BUY", "SELL"):
            sigs[i] = action
    return sigs


ADAPTERS = {
    "IMO": imo_signals,
    "CASCADE": cascade_signals,
    "IAM": iam_signals,
}


def main(argv: list) -> int:
    if not argv:
        print("usage: python tests/backtest_engines.py <file.csv ...>")
        return 0
    p = ImoParams(stop_pct=float(os.environ.get("IAM_STOP_LOSS_PCT", "8.0")))
    wanted = [e.strip().upper() for e in os.environ.get("ENGINES", "IMO,CASCADE,IAM").split(",") if e.strip()]

    header = f"{'engine':<9}{'symbol':<8}{'trades':>7}{'win%':>7}{'PF':>7}{'stops':>6}{'strat%':>9}{'B&H%':>9}{'maxDD%':>8}"
    print(f"stop overlay: {p.stop_pct}%  (executor IAM_STOP_LOSS_PCT semantics)")
    print(header)
    print("-" * len(header))
    for path in argv:
        symbol = os.path.splitext(os.path.basename(path))[0].upper()
        bars = load_csv(path)
        if len(bars) < 420:
            print(f"{'-':<9}{symbol:<8} INSUFFICIENT REAL DATA ({len(bars)} bars) — skipping")
            continue
        for name in wanted:
            fn = ADAPTERS.get(name)
            if not fn:
                continue
            s = simulate(symbol, bars, fn(bars, p), p).summary()
            pf = f"{s['profit_factor']:.2f}" if s["profit_factor"] != float("inf") else "inf"
            print(f"{name:<9}{symbol:<8}{s['trades']:>7}{s['win_rate']:>7.1f}{pf:>7}{s['stop_exits']:>6}"
                  f"{s['strategy_pct']:>9.1f}{s['buy_hold_pct']:>9.1f}{s['max_dd_pct']:>8.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
