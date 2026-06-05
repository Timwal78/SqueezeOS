"""
SML Engine 4 — Multi-Symbol Backtest Harness  (internal-use)
═════════════════════════════════════════════════════════════
Runs the proprietary price-ribbon ladder strategy across a watchlist and
reports per-symbol metrics + aggregate. Strategy:
  LONG  when the ribbon is fully stacked bullish
  SHORT when the ribbon is fully stacked bearish
  FLAT  otherwise

No stops, no targets — pure signal evaluation. Internal parameters live in
core.proprietary_ema_engine and are imported, not hard-coded here.

Two data modes:
  --mode synthetic   Bull/chop/bear regime walks (no API keys needed).
  --mode live        Real OHLC via data_providers.DataManager.

Usage:
  python tools/backtest_5ema.py
  python tools/backtest_5ema.py --symbols IWM,SPY,GME --mode live --bars 1000
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import List, Optional

import numpy as np
import pandas as pd

# Make the repo root importable when running from tools/
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.proprietary_ema_engine import Engine4_HarmonicLadder

EMA_PERIODS = list(Engine4_HarmonicLadder.PERIODS)   # [3, 36, 69, 102, 135]

DEFAULT_WATCHLIST = ["IWM", "SPY", "QQQ", "GME", "AMC", "NVDA", "TSLA", "PLTR", "HOOD", "MSTR"]


# ── EMA primitive (matches core.proprietary_ema_engine._ema exactly) ──────────

def ema(values: pd.Series, period: int) -> pd.Series:
    return values.ewm(span=period, adjust=False).mean()


# ── Data sources ──────────────────────────────────────────────────────────────

def synthetic_bars(symbol: str, n: int, seed: int) -> pd.DataFrame:
    """Three-regime synthetic walk: 1/3 bull, 1/3 chop, 1/3 bear."""
    rng = np.random.default_rng(seed + hash(symbol) % 10000)
    third = n // 3
    bull = rng.normal(loc=0.0006, scale=0.008, size=third)
    chop = rng.normal(loc=0.0000, scale=0.020, size=third)
    bear = rng.normal(loc=-0.0006, scale=0.008, size=n - 2 * third)
    rets = np.concatenate([bull, chop, bear])
    close = 100 * np.exp(np.cumsum(rets))
    regime = (["BULL"] * third + ["CHOP"] * third + ["BEAR"] * (n - 2 * third))
    return pd.DataFrame({"symbol": symbol, "close": close, "ret": rets, "regime": regime})


_LIVE_DM_CACHE = {"dm": None}   # share DataManager across symbols in one run


def _get_data_manager():
    if _LIVE_DM_CACHE["dm"] is not None:
        return _LIVE_DM_CACHE["dm"]
    try:
        from data_providers import DataManager
    except ImportError as e:
        print(f"  [live] DataManager import failed: {e}")
        return None
    try:
        _LIVE_DM_CACHE["dm"] = DataManager()
        dm = _LIVE_DM_CACHE["dm"]
        live = [name for name in ("tradier", "polygon", "alpaca", "alpha")
                if getattr(getattr(dm, name, None), "available", False)]
        print(f"  [live] DataManager ready. Active providers: {live or 'NONE'}")
        return dm
    except Exception as e:
        print(f"  [live] DataManager init failed: {type(e).__name__}: {e}")
        return None


def live_bars(symbol: str, n: int, timeframe: str = "1D") -> Optional[pd.DataFrame]:
    """Fetch OHLC via DataManager.get_bars (Polygon → Alpaca fallback handled internally).

    Returns None on any error or empty response — caller decides whether to skip.
    """
    dm = _get_data_manager()
    if dm is None:
        return None

    try:
        bars = dm.get_bars(symbol, timeframe=timeframe, limit=n)
    except Exception as e:
        print(f"  [live] {symbol}: get_bars raised {type(e).__name__}: {e}")
        return None

    if not bars:
        print(f"  [live] {symbol}: no bars returned (all providers unavailable or symbol invalid)")
        return None

    df = pd.DataFrame(bars)
    # Tolerate provider-specific column naming
    close_col = next((c for c in ("close", "c", "Close") if c in df.columns), None)
    if not close_col:
        print(f"  [live] {symbol}: no close column. Got: {list(df.columns)}")
        return None

    df = df.rename(columns={close_col: "close"})
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df = df.dropna(subset=["close"]).reset_index(drop=True)
    if len(df) < max(EMA_PERIODS) + 10:
        print(f"  [live] {symbol}: only {len(df)} bars after parse (need >{max(EMA_PERIODS) + 10})")
        return None

    df["symbol"] = symbol
    df["ret"]    = df["close"].pct_change().fillna(0)
    df["regime"] = "LIVE"
    return df[["symbol", "close", "ret", "regime"]]


# ── Backtest core ─────────────────────────────────────────────────────────────

def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    for p in EMA_PERIODS:
        df[f"ema_{p}"] = ema(df["close"], p)
    e3, e36, e69, e102, e135 = (df[f"ema_{p}"] for p in EMA_PERIODS)
    df["stack_bull"] = (e3 > e36) & (e36 > e69) & (e69 > e102) & (e102 > e135)
    df["stack_bear"] = (e3 < e36) & (e36 < e69) & (e69 < e102) & (e102 < e135)
    df["fan_width"] = (e3 - e135).abs() / df["close"]
    df["compressed"] = df["fan_width"] < Engine4_HarmonicLadder.COMPRESSION_PCT
    return df


def run_one(df: pd.DataFrame) -> dict:
    df = add_indicators(df)
    df["position"] = 0
    df.loc[df["stack_bull"], "position"] = 1
    df.loc[df["stack_bear"], "position"] = -1

    # Discard warmup — first 135 bars (longest EMA) before measuring
    warmup = max(EMA_PERIODS)
    df_eval = df.iloc[warmup:].copy()
    df_eval["strat_ret"] = df_eval["position"].shift(1).fillna(0) * df_eval["ret"]

    eq = (1 + df_eval["strat_ret"]).cumprod()
    bh = (1 + df_eval["ret"]).cumprod()

    if df_eval["strat_ret"].std() > 0:
        sharpe = (df_eval["strat_ret"].mean() / df_eval["strat_ret"].std()) * np.sqrt(252)
    else:
        sharpe = 0.0

    max_dd = (eq / eq.cummax() - 1).min()

    # Trade extraction
    pos_change = df_eval["position"].diff().fillna(0) != 0
    trades = []
    open_idx, open_pos = None, 0
    for i, row in df_eval.iterrows():
        if open_pos == 0 and row["position"] != 0:
            open_idx, open_pos = i, row["position"]
        elif open_pos != 0 and row["position"] != open_pos:
            entry = df_eval.loc[open_idx, "close"]
            exit_ = row["close"]
            trades.append({
                "side": "LONG" if open_pos == 1 else "SHORT",
                "entry_idx": open_idx,
                "exit_idx": i,
                "bars": i - open_idx,
                "pnl_pct": (exit_ / entry - 1) * open_pos,
                "regime_at_entry": df_eval.loc[open_idx, "regime"],
            })
            if row["position"] != 0:
                open_idx, open_pos = i, row["position"]
            else:
                open_idx, open_pos = None, 0

    tdf = pd.DataFrame(trades)
    return {
        "symbol":       df["symbol"].iloc[0],
        "bars":         len(df_eval),
        "n_trades":     len(tdf),
        "strat_return": eq.iloc[-1] - 1 if len(eq) else 0.0,
        "bh_return":    bh.iloc[-1] - 1 if len(bh) else 0.0,
        "sharpe":       sharpe,
        "max_dd":       max_dd,
        "win_rate":     (tdf["pnl_pct"] > 0).mean() if len(tdf) else 0.0,
        "avg_win":      tdf.loc[tdf["pnl_pct"] > 0, "pnl_pct"].mean() if (tdf["pnl_pct"] > 0).any() else 0.0,
        "avg_loss":     tdf.loc[tdf["pnl_pct"] < 0, "pnl_pct"].mean() if (tdf["pnl_pct"] < 0).any() else 0.0,
        "exposure_pct": (df_eval["position"] != 0).mean(),
        "compression_pct": df_eval["compressed"].mean(),
        "trades":       tdf,
    }


# ── Aggregation + reporting ───────────────────────────────────────────────────

def print_per_symbol_table(results: List[dict]):
    rows = []
    for r in results:
        payoff = abs(r["avg_win"] / r["avg_loss"]) if r["avg_loss"] != 0 else float("inf")
        rows.append({
            "Symbol":   r["symbol"],
            "Trades":   r["n_trades"],
            "Strat %":  f"{r['strat_return']*100:+.1f}%",
            "B&H %":    f"{r['bh_return']*100:+.1f}%",
            "Sharpe":   f"{r['sharpe']:.2f}",
            "DD":       f"{r['max_dd']*100:+.1f}%",
            "Win %":    f"{r['win_rate']*100:.1f}%",
            "Payoff":   f"{payoff:.2f}" if payoff != float("inf") else "∞",
            "Time in":  f"{r['exposure_pct']*100:.1f}%",
        })
    out = pd.DataFrame(rows)
    print(out.to_string(index=False))


def print_aggregate(results: List[dict]):
    n = len(results)
    if n == 0:
        return
    mean_strat = np.mean([r["strat_return"] for r in results]) * 100
    mean_bh    = np.mean([r["bh_return"]    for r in results]) * 100
    mean_sharpe = np.mean([r["sharpe"] for r in results])
    mean_dd    = np.mean([r["max_dd"] for r in results]) * 100
    total_trades = sum(r["n_trades"] for r in results)
    winners = sum(1 for r in results if r["strat_return"] > r["bh_return"])
    print()
    print(f"── AGGREGATE ({n} symbols) ──")
    print(f"  Mean strategy return:  {mean_strat:+.2f}%")
    print(f"  Mean buy-and-hold:     {mean_bh:+.2f}%")
    print(f"  Mean Sharpe:           {mean_sharpe:.2f}")
    print(f"  Mean max drawdown:     {mean_dd:+.2f}%")
    print(f"  Total trades:          {total_trades}")
    print(f"  Symbols beating B&H:   {winners}/{n}")


# ── Entrypoint ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--symbols", default=",".join(DEFAULT_WATCHLIST),
                        help="Comma-separated tickers (default: DEFAULT_WATCHLIST)")
    parser.add_argument("--mode", choices=["synthetic", "live"], default="synthetic",
                        help="Data source mode")
    parser.add_argument("--bars", type=int, default=3000, help="Bars per symbol")
    parser.add_argument("--timeframe", default="1D",
                        help="Bar timeframe for live mode: 1D | 5M | 1M (default 1D)")
    parser.add_argument("--seed", type=int, default=42, help="Synthetic RNG seed")
    parser.add_argument("--save", default=None, metavar="PATH",
                        help="Write per-symbol results as JSON to PATH")
    args = parser.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]

    print("=" * 78)
    print(f" SML ENGINE 4 — HARMONIC LADDER BACKTEST  ({args.mode.upper()} MODE)")
    print(f" Periods: {EMA_PERIODS}  |  Step: {Engine4_HarmonicLadder.STEP}")
    if args.mode == "live":
        print(f" Timeframe: {args.timeframe}  |  Bars/symbol: {args.bars}")
    print(f" Watchlist: {' '.join(symbols)}")
    print("=" * 78)

    results = []
    for sym in symbols:
        if args.mode == "synthetic":
            df = synthetic_bars(sym, args.bars, args.seed)
        else:
            df = live_bars(sym, args.bars, args.timeframe)
            if df is None or len(df) < max(EMA_PERIODS) + 10:
                print(f"  [skip] {sym}: insufficient data")
                continue
        results.append(run_one(df))

    if not results:
        print("\nNo symbols produced results.")
        return 1

    print()
    print_per_symbol_table(results)
    print_aggregate(results)

    if args.save:
        import json
        payload = [
            {k: v for k, v in r.items() if k != "trades"}   # trades is a DataFrame
            for r in results
        ]
        # Cast pandas/numpy scalars to plain JSON-able primitives
        for row in payload:
            for k, v in list(row.items()):
                if hasattr(v, "item"):
                    row[k] = v.item()
        with open(args.save, "w") as fh:
            json.dump(payload, fh, indent=2)
        print(f"\nResults written to {args.save}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
