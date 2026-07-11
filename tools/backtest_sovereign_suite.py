"""
SML Sovereign Signal Suite + 365 Anchor — real historical backtest.
=====================================================================
Same audit goal as tools/backtest_avg_down.py, applied to a different,
separately-monetized product: the "SML Sovereign Signal Suite"
(sovereign_741 / sovereign_365 / sovereign_triplelock / sovereign_full,
0.02-0.10 RLUSD per call) built on core/proprietary_ema_engine.py's four
engines ("Tesla Elastic Stretch", "Lucas Phi^2 Volume Accumulation",
"Harmonic Ladder", "Proprietary 5-EMA Stack").

Reuses the EXACT engine classes from core/proprietary_ema_engine.py via
direct import (_Engine1, _Engine4, _Engine5) — no re-derived logic.
Engine 3 (volume kinetics) is not backtested here as a standalone
tradeable signal since it never independently produces a price entry/exit
in the real product; it only ever gates/confirms the price engines.

Also backtests the 365-day EMA anchor (core/api/signal_products_bp.py's
_get_365_signal — ABOVE/BELOW price vs. its own 365-day EMA) since that's
dead simple and fully defined in source.

Scope explicitly NOT covered here, and not guessed at:
  - The 741 Pure Macro Matrix (core/api/macro741_bp.py / macro_bp.py) uses
    intraday bars and EMA periods from MACRO_STACK_CSV, a server-only env
    var never checked into source. Its real period configuration is not
    knowable from this codebase, and 3-year intraday history isn't
    practically available from Tradier's history endpoint — testing it
    honestly would need a different data pipeline. Left for follow-up.
  - Triple Lock (core/api/triple_lock_bp.py) is a separate file combining
    multiple engines with its own verdict logic not yet audited.

Entry/exit rule for each price engine, since these are regime detectors,
not full position-management systems like avg_down_engine: go long while
the engine's bull_stack (or bull_stack-equivalent signal) is true, flat
otherwise. This is the simplest fair reading of "PERFECT_BULLISH_REGIME
means ride the highway" — not a design choice by this script, an honest
translation of what the product's own language claims the signal means.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from typing import List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.proprietary_ema_engine import _Engine1, _Engine4, _Engine5
import tradier_api as ta

DEFAULT_UNIVERSE = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "AMD", "META", "AMC", "GME"]
DEFAULT_DAYS = 1095


def _ema(values: List[float], period: int) -> List[float]:
    if not values:
        return []
    if period <= 1:
        return list(values)
    k = 2.0 / (period + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1.0 - k))
    return out


@dataclass
class Trade:
    entry_price: float
    exit_price: float

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
        if self.skipped:
            return {"symbol": self.symbol, "strategy": self.strategy, "skipped": True, "skip_reason": self.skip_reason}
        if not self.trades:
            return {"symbol": self.symbol, "strategy": self.strategy, "skipped": False, "trade_count": 0}
        wins = [t for t in self.trades if t.pnl_pct > 0]
        losses = [t for t in self.trades if t.pnl_pct <= 0]
        total_return = 1.0
        for t in self.trades:
            total_return *= (1 + t.pnl_pct)
        total_return -= 1.0
        peak, max_dd = -float("inf"), 0.0
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


def _run_engine_bull_stack(symbol: str, closes: List[float], engine_cls, strategy_name: str, min_bars: int) -> RunResult:
    """Walk forward: long while the real engine reports bull_stack, flat otherwise."""
    result = RunResult(symbol=symbol, strategy=strategy_name)
    if len(closes) < min_bars + 5:
        result.skipped = True
        result.skip_reason = f"only {len(closes)} bars, need {min_bars + 5}+"
        return result

    engine = engine_cls()
    in_pos = False
    entry_price = 0.0
    equity = 1.0

    for i in range(min_bars, len(closes)):
        window = closes[: i + 1]
        analysis = engine.analyze(window)
        bull = bool(analysis.get("bull_stack"))
        close = window[-1]

        if not in_pos and bull:
            in_pos, entry_price = True, close
        elif in_pos and not bull:
            result.trades.append(Trade(entry_price, close))
            in_pos = False

        if in_pos and i > min_bars:
            equity *= closes[i] / closes[i - 1]
        result.equity_curve.append(equity)

    if in_pos:
        result.trades.append(Trade(entry_price, closes[-1]))

    return result


def _run_365_anchor(symbol: str, closes: List[float]) -> RunResult:
    """Long while price > 365-day EMA (the real anchor rule from signal_products_bp.py), flat otherwise."""
    result = RunResult(symbol=symbol, strategy="anchor_365")
    if len(closes) < 370:
        result.skipped = True
        result.skip_reason = f"only {len(closes)} bars, need 370+"
        return result

    ema365 = _ema(closes, 365)
    in_pos = False
    entry_price = 0.0
    equity = 1.0

    for i in range(365, len(closes)):
        close = closes[i]
        above = close > ema365[i]
        if not in_pos and above:
            in_pos, entry_price = True, close
        elif in_pos and not above:
            result.trades.append(Trade(entry_price, close))
            in_pos = False
        if in_pos and i > 365:
            equity *= closes[i] / closes[i - 1]
        result.equity_curve.append(equity)

    if in_pos:
        result.trades.append(Trade(entry_price, closes[-1]))

    return result


def main():
    parser = argparse.ArgumentParser(description="Backtest SML Sovereign Signal Suite engines + 365 anchor on real Tradier data")
    parser.add_argument("--symbols", default=",".join(DEFAULT_UNIVERSE))
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    parser.add_argument("--out", default="sovereign_backtest_results.json")
    args = parser.parse_args()

    if not ta.is_available():
        print("ERROR: Tradier is not configured (TRADIER_API_KEY missing) — cannot fetch real data.", file=sys.stderr)
        sys.exit(1)

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    all_results = {}

    for symbol in symbols:
        df = ta.get_history_df(symbol, days=args.days)
        if df is None or df.empty:
            all_results[symbol] = [{"skipped": True, "skip_reason": "no data from Tradier"}]
            continue
        col = "Close" if "Close" in df.columns else df.columns[-1]
        closes = df[col].dropna().tolist()

        runs = [
            _run_engine_bull_stack(symbol, closes, _Engine1, "engine1_tesla_elastic_stretch", min_bars=963),
            _run_engine_bull_stack(symbol, closes, _Engine4, "engine4_harmonic_ladder", min_bars=135),
            _run_engine_bull_stack(symbol, closes, _Engine5, "engine5_proprietary_5ema", min_bars=61),
            _run_365_anchor(symbol, closes),
        ]
        all_results[symbol] = [r.metrics() for r in runs]

    with open(args.out, "w") as f:
        json.dump(all_results, f, indent=2)

    print(json.dumps(all_results, indent=2))


if __name__ == "__main__":
    main()
