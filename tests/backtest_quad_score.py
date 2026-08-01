"""
Real backtest harness for quad_score_engine.py (the new long-only "4-Pillar"
scoring engine). Same convention as tests/backtest_druck.py /
tests/optimize_sovereign_squeeze.py: real daily bars in, compute_series()'s
own walk-forward state machine replayed, honest PF/win-rate reported —
no synthetic data, no curve-fitting the backtest itself.

Data source: real Robinhood MCP get_equity_historicals, AMC/GME/IWM/SPY/
NVDA/QQQ, 2018-01-02 through 2026-07-30 (~2155 daily bars/symbol, split-
adjusted, the one interpolated/zero-volume bar per symbol dropped). Saved
once to QUAD_SCORE_BARS_JSON so this is reproducible without re-fetching.

Usage:
  QUAD_SCORE_BARS_JSON=/path/to/bars.json python3 tests/backtest_quad_score.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import quad_score_engine as qse

DEFAULT_BARS_JSON = "/tmp/claude-0/-home-user/21c7a031-52d4-5421-adf5-8370d2f7dd16/scratchpad/quad_score_bars.json"


def load_bars():
    path = os.environ.get("QUAD_SCORE_BARS_JSON", DEFAULT_BARS_JSON)
    with open(path) as f:
        return json.load(f)


def backtest_symbol(symbol: str, bars: list, p: qse.QuadScoreParams = None):
    p = p or qse.QuadScoreParams.from_env()
    out = qse.compute_series(bars, p)
    events = out["events"]
    pnl = out["pnl_pct"]

    trades = []
    entry_i = None
    for i in range(len(bars)):
        if events[i] == "ENTER_CALL":
            entry_i = i
        elif events[i] in ("EXIT_TARGET", "EXIT_STOP") and entry_i is not None:
            trades.append({
                "entry_date": bars[entry_i].get("date"),
                "exit_date": bars[i].get("date"),
                "exit_type": events[i],
                "pnl_pct": pnl[i],
                "bars_held": i - entry_i,
            })
            entry_i = None

    wins = [t for t in trades if t["pnl_pct"] > 0]
    losses = [t for t in trades if t["pnl_pct"] <= 0]
    gross_win = sum(t["pnl_pct"] for t in wins)
    gross_loss = -sum(t["pnl_pct"] for t in losses)
    pf = (gross_win / gross_loss) if gross_loss > 0 else (float("inf") if gross_win > 0 else 0.0)
    total_pnl = sum(t["pnl_pct"] for t in trades)

    return {
        "symbol": symbol, "trades": len(trades), "wins": len(wins), "losses": len(losses),
        "win_rate": (len(wins) / len(trades) * 100.0) if trades else 0.0,
        "profit_factor": pf, "total_pnl_pct": total_pnl, "trade_list": trades,
    }


def main():
    all_bars = load_bars()
    p = qse.QuadScoreParams.from_env()
    results = []
    for sym, bars in all_bars.items():
        r = backtest_symbol(sym, bars, p)
        results.append(r)
        print(f"{sym:6s} trades={r['trades']:3d} wins={r['wins']:3d} losses={r['losses']:3d} "
              f"win_rate={r['win_rate']:5.1f}% PF={r['profit_factor']:.3f} total_pnl={r['total_pnl_pct']:+.2f}%")
        for t in r["trade_list"]:
            print(f"    {t['entry_date']} -> {t['exit_date']} ({t['exit_type']}, {t['bars_held']}d) {t['pnl_pct']:+.2f}%")

    total_trades = sum(r["trades"] for r in results)
    total_wins = sum(r["wins"] for r in results)
    total_losses = sum(r["losses"] for r in results)
    gross_win = sum(t["pnl_pct"] for r in results for t in r["trade_list"] if t["pnl_pct"] > 0)
    gross_loss = -sum(t["pnl_pct"] for r in results for t in r["trade_list"] if t["pnl_pct"] <= 0)
    agg_pf = (gross_win / gross_loss) if gross_loss > 0 else (float("inf") if gross_win > 0 else 0.0)
    total_pnl = sum(r["total_pnl_pct"] for r in results)
    print()
    print(f"AGGREGATE: trades={total_trades} wins={total_wins} losses={total_losses} "
          f"win_rate={(total_wins/total_trades*100.0) if total_trades else 0:.1f}% "
          f"PF={agg_pf:.3f} summed_pnl={total_pnl:+.2f}%")


if __name__ == "__main__":
    main()
