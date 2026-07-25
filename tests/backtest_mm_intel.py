"""
tests/backtest_mm_intel.py -- real OHLCV backtest of mm_intel_engine.py's
long/short forced-hedge signal, using the engine's own entry (BUY/SELL) and
exit (EXIT_STOP/EXIT_RESOLVED) events from compute_series()'s (bug-fixed)
invalidation state machine. Position sizing is directional %-move on the
underlying (same convention as breakout_engine.py/druck_engine.py) -- not
modeled option premium/theta/leverage, and no pyramiding (one position at a
time, matching the engine's own entry gating).

Real data: 5-minute bars, SPY/QQQ/IWM/NVDA/TSLA, 2026-06-01 to 2026-07-25,
Robinhood MCP get_equity_historicals (same real-data channel used for the
DRUCK/CIE/Breakout backtests). No options-chain data needed -- inv_z/gamma
pressure are entirely OHLCV-derived (unlike SML_Gamma_Pin_v6.pine's pin-risk
constraint, which has no historical options-chain source to backtest
against at all).
"""
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mm_intel_engine import MMIntelParams, compute_series

DATA_DIR = os.environ.get(
    "MM_INTEL_BACKTEST_DATA_DIR",
    "/tmp/claude-0/-home-user/366a66f8-6aaf-57fa-a1dd-a07cbe6989fb/scratchpad/mm_intel_data",
)


def load_bars(csv_path):
    bars = []
    with open(csv_path, newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            bars.append({
                "date": row["date"], "open": float(row["open"]), "high": float(row["high"]),
                "low": float(row["low"]), "close": float(row["close"]), "volume": float(row["volume"]),
            })
    return bars


def run_backtest(symbol: str, bars: list, p: MMIntelParams = None) -> dict:
    p = p or MMIntelParams.from_env()
    out = compute_series(bars, p)
    live = out["live_signal"]
    closes = [b["close"] for b in bars]

    trades = []
    direction = None
    entry_price = None
    entry_idx = None
    for i, sig in enumerate(live):
        if sig in ("BUY", "SELL") and direction is None:
            direction = "up" if sig == "BUY" else "down"
            entry_price = closes[i]
            entry_idx = i
        elif sig in ("EXIT_STOP", "EXIT_RESOLVED") and direction is not None:
            exit_price = closes[i]
            pnl_pct = ((exit_price - entry_price) / entry_price if direction == "up"
                       else (entry_price - exit_price) / entry_price)
            trades.append({
                "entry_idx": entry_idx, "exit_idx": i, "direction": direction,
                "entry_price": entry_price, "exit_price": exit_price,
                "pnl_pct": pnl_pct, "exit_reason": sig,
            })
            direction, entry_price, entry_idx = None, None, None

    wins = [t for t in trades if t["pnl_pct"] > 0]
    losses = [t for t in trades if t["pnl_pct"] <= 0]
    gross_win = sum(t["pnl_pct"] for t in wins)
    gross_loss = -sum(t["pnl_pct"] for t in losses)
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else (float("inf") if gross_win > 0 else 0.0)
    total_return_pct = sum(t["pnl_pct"] for t in trades) * 100.0
    win_rate = (len(wins) / len(trades) * 100.0) if trades else 0.0
    buy_hold_pct = (closes[-1] - closes[0]) / closes[0] * 100.0 if closes else 0.0

    return {
        "symbol": symbol, "trades": len(trades), "win_rate": win_rate,
        "profit_factor": profit_factor, "total_return_pct": total_return_pct,
        "buy_hold_pct": buy_hold_pct, "bars": len(bars), "trade_list": trades,
    }


def main():
    symbols = ["SPY", "QQQ", "IWM", "NVDA", "TSLA"]
    results = []
    for sym in symbols:
        path = os.path.join(DATA_DIR, f"{sym}.csv")
        if not os.path.exists(path):
            print(f"SKIP {sym}: no data file at {path}")
            continue
        bars = load_bars(path)
        res = run_backtest(sym, bars)
        results.append(res)
        pf_str = "inf" if res["profit_factor"] == float("inf") else f"{res['profit_factor']:.2f}"
        print(f"{sym}: {res['trades']} trades, {res['win_rate']:.1f}% win rate, "
              f"PF {pf_str}, return {res['total_return_pct']:+.2f}% "
              f"(buy&hold {res['buy_hold_pct']:+.2f}%), {res['bars']} bars")
    return results


if __name__ == "__main__":
    main()
