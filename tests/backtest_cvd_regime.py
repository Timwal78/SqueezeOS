"""
Real backtest harness for cvd_regime_engine.py (SML CVD Regime Desk).

Data: real intraday OHLCV bars from CSV, sourced via the Robinhood MCP
`get_equity_historicals` channel — the same real-data path used for the DRUCK,
CIE, Breakout, MM-Intel and Gamma Ramp backtests in this repo (this sandbox has
no direct HTTPS to api.tradier.com / api.polygon.io; that MCP channel is a
separate, working route to real market data).

CSV format (one file per symbol, written by the caller):
    ts,high,low,close,volume
    2026-07-23T13:30:00Z,739.46,738.03,738.155,807654

WHAT THIS MEASURES AND WHAT IT DOES NOT
---------------------------------------
It runs the REAL, UNMODIFIED cvd_regime_engine.compute_series() — the same
function the Pine script mirrors and the same one any future scanner would call.
Nothing about the strategy is reimplemented here.

It models the UNDERLYING's directional %-move with the engine's own ATR stop and
R-multiple target. It does NOT model option premium, leverage, theta, spread or
assignment — the same disclosed limitation as breakout_engine.py /
druck_engine.py / mm_intel_engine.py backtests in this repo. For a script whose
stated purpose is buying 0.30-0.40 delta options, a positive result here is
NECESSARY BUT NOT SUFFICIENT. A negative result, on the other hand, is decisive:
if the directional read loses money before theta is charged, adding theta cannot
rescue it.

Usage:
    python tests/backtest_cvd_regime.py data/SPY_5m.csv data/QQQ_5m.csv ...
"""
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cvd_regime_engine import compute_series, CvdParams  # noqa: E402


def load_csv(path: str) -> list:
    bars = []
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            bars.append({
                "begins_at": row["ts"],
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"]),
            })
    return bars


def stats(trades: list, bars: list) -> dict:
    if not trades:
        return {"trades": 0}
    wins = [t["pnl_pct"] for t in trades if t["pnl_pct"] > 0]
    losses = [t["pnl_pct"] for t in trades if t["pnl_pct"] <= 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    # Compounded return of a fixed-fraction-of-equity-per-trade sequence would
    # need a sizing model; report the plain sum of per-trade %-moves plus the
    # compounded product, and be explicit which is which.
    compounded = 1.0
    for t in trades:
        compounded *= (1.0 + t["pnl_pct"] / 100.0)
    bh = ((bars[-1]["close"] - bars[0]["close"]) / bars[0]["close"]) * 100.0
    reasons = {}
    for t in trades:
        reasons[t["exit_reason"]] = reasons.get(t["exit_reason"], 0) + 1
    longs = [t for t in trades if t["direction"] == "long"]
    shorts = [t for t in trades if t["direction"] == "short"]
    return {
        "trades": len(trades),
        "wins": len(wins),
        "win_rate": round(100.0 * len(wins) / len(trades), 1),
        "profit_factor": round(gross_win / gross_loss, 3) if gross_loss > 0 else float("inf"),
        "sum_pct": round(sum(t["pnl_pct"] for t in trades), 2),
        "compounded_pct": round((compounded - 1.0) * 100.0, 2),
        "avg_pct": round(sum(t["pnl_pct"] for t in trades) / len(trades), 4),
        "best_pct": round(max(t["pnl_pct"] for t in trades), 2),
        "worst_pct": round(min(t["pnl_pct"] for t in trades), 2),
        "avg_bars_held": round(sum(t["bars_held"] for t in trades) / len(trades), 1),
        "buy_hold_pct": round(bh, 2),
        "exit_reasons": reasons,
        "longs": len(longs), "shorts": len(shorts),
        "long_sum_pct": round(sum(t["pnl_pct"] for t in longs), 2),
        "short_sum_pct": round(sum(t["pnl_pct"] for t in shorts), 2),
    }


def run(paths: list, p: CvdParams = None, label: str = "default") -> dict:
    p = p or CvdParams()
    print(f"\n{'=' * 78}")
    print(f"CONFIG [{label}]  min_conviction={p.min_conviction} stop_atr={p.stop_atr} "
          f"target_r={p.target_r} cooldown={p.cooldown_bars} htf={p.htf_minutes}m "
          f"early={p.use_early}")
    print(f"{'=' * 78}")
    header = (f"{'SYM':<6} {'BARS':>5} {'TRD':>4} {'WIN%':>6} {'PF':>7} "
              f"{'SUM%':>8} {'CMPD%':>8} {'B&H%':>8} {'AVG%':>7} {'HELD':>5}")
    print(header)
    print("-" * len(header))

    all_trades = []
    per_symbol = {}
    for path in paths:
        sym = os.path.basename(path).split("_")[0].upper()
        bars = load_csv(path)
        out = compute_series(bars, p)
        s = stats(out["trades"], bars)
        per_symbol[sym] = s
        all_trades.extend(out["trades"])
        if s["trades"] == 0:
            print(f"{sym:<6} {len(bars):>5} {0:>4}   (no qualifying signals)")
            continue
        print(f"{sym:<6} {len(bars):>5} {s['trades']:>4} {s['win_rate']:>6} "
              f"{s['profit_factor']:>7} {s['sum_pct']:>8} {s['compounded_pct']:>8} "
              f"{s['buy_hold_pct']:>8} {s['avg_pct']:>7} {s['avg_bars_held']:>5}")

    if all_trades:
        wins = [t for t in all_trades if t["pnl_pct"] > 0]
        gl = abs(sum(t["pnl_pct"] for t in all_trades if t["pnl_pct"] <= 0))
        gw = sum(t["pnl_pct"] for t in wins)
        pf = round(gw / gl, 3) if gl > 0 else float("inf")
        print("-" * len(header))
        print(f"{'ALL':<6} {'':>5} {len(all_trades):>4} "
              f"{round(100.0*len(wins)/len(all_trades),1):>6} {pf:>7} "
              f"{round(sum(t['pnl_pct'] for t in all_trades),2):>8}")
        reasons = {}
        for t in all_trades:
            reasons[t["exit_reason"]] = reasons.get(t["exit_reason"], 0) + 1
        print(f"       exit reasons: {reasons}")
        nl = len([t for t in all_trades if t['direction'] == 'long'])
        ns = len([t for t in all_trades if t['direction'] == 'short'])
        sl = sum(t['pnl_pct'] for t in all_trades if t['direction'] == 'long')
        ss = sum(t['pnl_pct'] for t in all_trades if t['direction'] == 'short')
        print(f"       long: {nl} trades, {sl:+.2f}%   short: {ns} trades, {ss:+.2f}%")
    return {"per_symbol": per_symbol, "all_trades": all_trades}


if __name__ == "__main__":
    paths = sys.argv[1:]
    if not paths:
        print(__doc__)
        sys.exit(1)

    # Default config first — this is the verdict config. Everything after it is
    # sensitivity analysis, NOT a search for a config that happens to win (that
    # would be curve-fitting on a single short window).
    run(paths, CvdParams(), "DEFAULT (verdict config)")

    print("\n\n### SENSITIVITY (not a tuning search — shows whether the result is "
          "an artifact of one setting) ###")
    run(paths, CvdParams(use_early=False), "confirmed-only (no early signals)")
    run(paths, CvdParams(min_conviction=70), "min_conviction=70")
    run(paths, CvdParams(target_r=1.0), "target_r=1.0")
    run(paths, CvdParams(exit_on_flip=False), "no flip exit")
