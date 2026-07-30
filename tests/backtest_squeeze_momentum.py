"""
Independent verification of the operator-submitted "ScriptMaster - Squeeze
Momentum Engine v6" TradingView Strategy Tester results.

Runs the real, unmodified squeeze_momentum_engine.run_strategy() against real
bars (Robinhood MCP `get_equity_historicals`, the same real-data channel used
for the DRUCK/CIE/Breakout/MM-Intel/CVD backtests in this repo).

Why this exists: this repo has a precedent — see the "History note" under SML
Breakout Target/Stop in CLAUDE.md — where a chat-reported backtest table
(336-parameter sweep, 191 trades) could not be reproduced and its aggregate
totals did not match an independent run. Chat-reported Strategy Tester output is
not evidence until someone re-derives it. This is the re-derivation.

Usage:
    python tests/backtest_squeeze_momentum.py <datadir>
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from squeeze_momentum_engine import run_strategy, SqueezeParams  # noqa: E402


def load_csv(path: str) -> list:
    import csv
    bars = []
    with open(path, newline="") as fh:
        for r in csv.DictReader(fh):
            bars.append({"ts": r["ts"], "open": float(r["open"]),
                         "high": float(r["high"]), "low": float(r["low"]),
                         "close": float(r["close"]), "volume": float(r["volume"])})
    return bars


def aggregate(bars: list, n: int) -> list:
    """Aggregate n consecutive bars into one (Pine's 2D from 1D, etc.)."""
    out = []
    for i in range(0, len(bars) - n + 1, n):
        grp = bars[i:i + n]
        out.append({"ts": grp[0]["ts"], "open": grp[0]["open"],
                    "high": max(b["high"] for b in grp),
                    "low": min(b["low"] for b in grp),
                    "close": grp[-1]["close"],
                    "volume": sum(b["volume"] for b in grp)})
    return out


HDR = (f"{'SYMBOL':<12}{'BARS':>6}{'TRD':>5}{'LONG':>5}{'SHRT':>5}{'WIN%':>7}"
       f"{'PF':>8}{'NET$':>11}{'NET%':>8}{'MAXDD%':>8}{'B&H%':>10}{'FILT%':>7}")


def report(label: str, bars: list, p: SqueezeParams = None):
    r = run_strategy(bars, p or SqueezeParams())
    print(f"{label:<12}{len(bars):>6}{r['n_trades']:>5}{r['n_long']:>5}"
          f"{r['n_short']:>5}{r['win_rate']:>7}{r['profit_factor']:>8}"
          f"{r['net_pnl']:>11}{r['net_pct_of_equity']:>8}{r['max_dd_pct']:>8}"
          f"{r['buy_hold_pct']:>10}"
          f"{str(r['extreme_filter_bind_pct']):>7}")
    return r


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    d = sys.argv[1]

    print("Claimed vs measured. FILT% = share of otherwise-qualifying bars the")
    print("`val > lowest(val,100)[1]` filter actually rejected (ISSUE C).\n")
    print(HDR)
    print("-" * len(HDR))

    results = {}
    # AMC 2D 2013-2026 — a directly claimed row (claimed +$5,930.40, PF 5.007)
    if os.path.exists(f"{d}/AMC_1d.csv"):
        amc = load_csv(f"{d}/AMC_1d.csv")
        results["AMC 2D"] = report("AMC 2D", aggregate(amc, 2))
        results["AMC 1D"] = report("AMC 1D", amc)
    # GME — claimed on 1h; daily included since full clean history exists
    if os.path.exists(f"{d}/GME_1d.csv"):
        results["GME 1D"] = report("GME 1D", load_csv(f"{d}/GME_1d.csv"))
    if os.path.exists(f"{d}/GME_1h.csv"):
        results["GME 1H"] = report("GME 1H", load_csv(f"{d}/GME_1h.csv"))
    for sym, tf in (("DJT", "4h"), ("IONQ", "4h"), ("COSM", "1d")):
        pth = f"{d}/{sym}_{tf}.csv"
        if os.path.exists(pth):
            results[f"{sym} {tf}"] = report(f"{sym} {tf}", load_csv(pth))

    print("\n--- ISOLATING THE SHORT SIDE (ISSUE A) ---")
    print("The submitted short trigger fires on squeeze ONSET, not release.")
    print(HDR)
    print("-" * len(HDR))
    if os.path.exists(f"{d}/AMC_1d.csv"):
        amc2 = aggregate(load_csv(f"{d}/AMC_1d.csv"), 2)
        report("AMC 2D L-only", amc2, SqueezeParams(allow_short=False))
    if os.path.exists(f"{d}/GME_1d.csv"):
        report("GME 1D L-only", load_csv(f"{d}/GME_1d.csv"), SqueezeParams(allow_short=False))

    print("\n--- SIZING: the same strategy at 100% of equity instead of 2% ---")
    print("PF / win% / trade count are size-invariant; NET% and MAXDD% are not.")
    print(HDR)
    print("-" * len(HDR))
    if os.path.exists(f"{d}/AMC_1d.csv"):
        amc2 = aggregate(load_csv(f"{d}/AMC_1d.csv"), 2)
        report("AMC 2D @100%", amc2, SqueezeParams(qty_pct_equity=100.0))
    if os.path.exists(f"{d}/GME_1d.csv"):
        report("GME 1D @100%", load_csv(f"{d}/GME_1d.csv"), SqueezeParams(qty_pct_equity=100.0))

    print("\n--- CONCENTRATION: how much of the P&L is the single best trade? ---")
    for k, r in results.items():
        if r["n_trades"] == 0:
            continue
        pnls = sorted((t["pnl"] for t in r["trades"]), reverse=True)
        tot = sum(pnls)
        if tot <= 0:
            print(f"{k:<12} net negative or flat ({tot:.2f}) — concentration moot")
            continue
        best = pnls[0]
        top3 = sum(pnls[:3])
        print(f"{k:<12} best trade {best:>10.2f} = {100*best/tot:>5.1f}% of net;"
              f"  top 3 = {100*top3/tot:>5.1f}%   (n={r['n_trades']})")
