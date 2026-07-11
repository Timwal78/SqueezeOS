"""
CASCADE ACCUMULATOR (avg_down_engine) — real historical backtest.
==================================================================
Answers a question the codebase couldn't answer before this script existed:
does this strategy actually win, on real historical data, and how does it
compare to something much simpler?

Reuses the EXACT signal math already running in production
(avg_down_engine._compute_layers / _ribbon_state) via direct import — this
script does not re-derive or approximate the EMA ribbon logic, so there is
no risk of the backtest silently drifting from what's actually live.

Runs against real Tradier daily bars (same data path avg_down_engine.py uses
in production) — requires TRADIER_API_KEY. Not runnable in an environment
without real market-data network access; see
.github/workflows/backtest-avg-down.yml for the CI job that actually runs it.

Also runs two baselines over the identical bars for honest comparison:
  - buy_and_hold: what you'd have made just holding the symbol
  - single_ema_50: price > 50-day EMA = long, else flat — the simplest
    reasonable trend rule, to see whether CASCADE's 5-layer ribbon is
    actually earning its complexity over something almost anyone could
    build in an afternoon.

No claim in this script's output is invented — every number is computed
from real Tradier bars fetched at run time. If Tradier is unavailable, the
symbol is skipped and reported as skipped, never silently substituted with
fake data (Prime Directive: NO DEMO DATA).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# avg_down_engine.py and tradier_api.py live at the repo root, not under
# tools/ — when this script is invoked as `python tools/backtest_avg_down.py`,
# Python only puts tools/ on sys.path, not the repo root, so the plain
# `import avg_down_engine` below fails with ModuleNotFoundError unless the
# repo root is added explicitly here.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import avg_down_engine as engine
import tradier_api as ta

DEFAULT_UNIVERSE = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "AMD", "META"]
DEFAULT_DAYS = 1095  # ~3 years of daily bars


def _ema_series(values: List[float], period: int) -> List[float]:
    return engine._ema(values, period)


@dataclass
class Trade:
    entry_price: float
    exit_price: float
    entry_idx: int
    exit_idx: int
    reason: str

    @property
    def pnl_pct(self) -> float:
        return (self.exit_price - self.entry_price) / self.entry_price


@dataclass
class RunResult:
    symbol: str
    strategy: str
    trades: List[Trade] = field(default_factory=list)
    equity_curve: List[float] = field(default_factory=list)
    skipped: bool = False
    skip_reason: str = ""

    def metrics(self) -> dict:
        if self.skipped or not self.trades:
            return {
                "symbol": self.symbol,
                "strategy": self.strategy,
                "skipped": self.skipped,
                "skip_reason": self.skip_reason,
                "trade_count": 0,
            }
        wins = [t for t in self.trades if t.pnl_pct > 0]
        losses = [t for t in self.trades if t.pnl_pct <= 0]
        total_return = 1.0
        for t in self.trades:
            total_return *= (1 + t.pnl_pct)
        total_return -= 1.0

        peak = -float("inf")
        max_dd = 0.0
        for v in self.equity_curve:
            peak = max(peak, v)
            if peak > 0:
                max_dd = max(max_dd, (peak - v) / peak)

        return {
            "symbol": self.symbol,
            "strategy": self.strategy,
            "skipped": False,
            "trade_count": len(self.trades),
            "win_count": len(wins),
            "loss_count": len(losses),
            "win_rate_pct": round(100 * len(wins) / len(self.trades), 1),
            "avg_win_pct": round(100 * sum(t.pnl_pct for t in wins) / len(wins), 2) if wins else None,
            "avg_loss_pct": round(100 * sum(t.pnl_pct for t in losses) / len(losses), 2) if losses else None,
            "total_return_pct": round(100 * total_return, 2),
            "max_drawdown_pct": round(100 * max_dd, 2),
        }


def run_avg_down(symbol: str, closes: List[float]) -> RunResult:
    """
    Walk-forward simulation using the SAME pure EMA/ribbon functions
    avg_down_engine.py uses live — but with its own local position state,
    never touching the live module's global _positions/_signals, so this
    can't interfere with (or be interfered with by) a running server.
    """
    result = RunResult(symbol=symbol, strategy="cascade_avg_down")
    layers = engine._load_layers()
    min_bars = layers[-1]
    if len(closes) < min_bars + 20:
        result.skipped = True
        result.skip_reason = f"only {len(closes)} bars, need {min_bars + 20}+"
        return result

    in_pos = False
    avg_price = 0.0
    level = 0
    entry_idx = 0

    for i in range(min_bars, len(closes)):
        window = closes[: i + 1]
        lv = engine._compute_layers(window)
        if not lv:
            continue
        close = window[-1]
        ribbon = engine._ribbon_state(lv, close)

        if in_pos:
            pnl = (close - avg_price) / avg_price if avg_price > 0 else 0.0

            if pnl < -engine.MAX_LOSS_PCT:
                result.trades.append(Trade(avg_price, close, entry_idx, i, "HARD_STOP"))
                in_pos, avg_price, level = False, 0.0, 0
                continue

            if not ribbon["above_anchor"]:
                result.trades.append(Trade(avg_price, close, entry_idx, i, "STOP"))
                in_pos, avg_price, level = False, 0.0, 0
                continue

            if pnl >= engine.EXIT_GAIN or (pnl > 0.005 and ribbon["full_bull"] and ribbon["above_anchor"]):
                result.trades.append(Trade(avg_price, close, entry_idx, i, "EXIT"))
                in_pos, avg_price, level = False, 0.0, 0
                continue

            threshold = -engine.ADD_PCT * (level + 1)
            if pnl < threshold and level < engine.MAX_LEVELS and ribbon["loose_bull"] and ribbon["above_anchor"]:
                old_size = engine.INITIAL_SIZE * sum(engine.SCALE_FACTOR ** l for l in range(level + 1))
                add_size = engine.INITIAL_SIZE * (engine.SCALE_FACTOR ** (level + 1))
                avg_price = (avg_price * old_size + close * add_size) / (old_size + add_size)
                level += 1

            result.equity_curve.append(1.0 + pnl)
        else:
            if ribbon["full_bull"] and ribbon["above_anchor"] and close > lv["L1"]:
                in_pos, avg_price, level, entry_idx = True, close, 0, i
            result.equity_curve.append(1.0)

    return result


def run_buy_and_hold(symbol: str, closes: List[float]) -> RunResult:
    result = RunResult(symbol=symbol, strategy="buy_and_hold")
    if len(closes) < 2:
        result.skipped = True
        result.skip_reason = "insufficient bars"
        return result
    result.trades.append(Trade(closes[0], closes[-1], 0, len(closes) - 1, "HOLD"))
    result.equity_curve = [c / closes[0] for c in closes]
    return result


def run_single_ema_50(symbol: str, closes: List[float]) -> RunResult:
    """Simplest reasonable trend rule: long while price > 50-day EMA, flat otherwise."""
    result = RunResult(symbol=symbol, strategy="single_ema_50")
    if len(closes) < 70:
        result.skipped = True
        result.skip_reason = f"only {len(closes)} bars, need 70+"
        return result

    ema50 = _ema_series(closes, 50)
    in_pos = False
    entry_price = 0.0
    entry_idx = 0
    equity = 1.0

    for i in range(50, len(closes)):
        close = closes[i]
        above = close > ema50[i]
        if not in_pos and above:
            in_pos, entry_price, entry_idx = True, close, i
        elif in_pos and not above:
            result.trades.append(Trade(entry_price, close, entry_idx, i, "TREND_FLIP"))
            in_pos = False
        if in_pos:
            equity = equity * (close / closes[i - 1])
        result.equity_curve.append(equity)

    if in_pos:
        result.trades.append(Trade(entry_price, closes[-1], entry_idx, len(closes) - 1, "OPEN_AT_END"))

    return result


def main():
    parser = argparse.ArgumentParser(description="Backtest CASCADE ACCUMULATOR vs. baselines on real Tradier data")
    parser.add_argument("--symbols", default=",".join(DEFAULT_UNIVERSE))
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    parser.add_argument("--out", default="backtest_results.json")
    args = parser.parse_args()

    if not ta.is_available():
        print("ERROR: Tradier is not configured (TRADIER_API_KEY missing) — cannot fetch real data.", file=sys.stderr)
        sys.exit(1)

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    all_results: Dict[str, List[dict]] = {}

    for symbol in symbols:
        df = ta.get_history_df(symbol, days=args.days)
        if df is None or df.empty:
            all_results[symbol] = [{"skipped": True, "skip_reason": "no data from Tradier"}]
            continue
        col = "Close" if "Close" in df.columns else df.columns[-1]
        closes = df[col].dropna().tolist()

        runs = [
            run_avg_down(symbol, closes),
            run_buy_and_hold(symbol, closes),
            run_single_ema_50(symbol, closes),
        ]
        all_results[symbol] = [r.metrics() for r in runs]

    with open(args.out, "w") as f:
        json.dump(all_results, f, indent=2)

    print(json.dumps(all_results, indent=2))


if __name__ == "__main__":
    main()
