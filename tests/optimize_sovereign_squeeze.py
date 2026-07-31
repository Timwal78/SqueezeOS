"""
Sovereign Squeeze Finder parameter search — chronological TRAIN/VALID split,
same methodology as tests/optimize_cvd_regime.py (the concrete antidote to
the Gamma Ramp failure mode: sweeping any parameter grid over one history
without a forward split reliably manufactures impressive-looking winners
that are pure noise). TRAIN = earlier 67% of each symbol's real daily bars
(by entry date), VALID = the later 33%; the search only ever looks at
TRAIN when ranking candidates, and each candidate is scored on VALID
exactly once.

Requires real daily bars pulled via the Robinhood MCP get_equity_historicals
tool (same real-data channel as every other backtest in this codebase) for
AMC, GME, IWM, SPY, NVDA, QQQ, 2021-01-04..2026-07-30 (1,399 bars/symbol) —
point BARS_JSON_PATH at a saved copy of that tool's raw JSON response
(`{"data": {"results": [{"symbol": ..., "bars": [{"begins_at", "open_price",
"high_price", "low_price", "close_price", "volume"}, ...]}, ...]}}`) to
reproduce. This file is the reusable harness, not a source of committed
bar data (same convention as scripts/_rh_to_druck_csv.py).

Real result (2026-07-31, this exact dataset): the discovered config held up
consistently positive on VALID across four different split points (50/60/
67/75%) and across single-parameter perturbations in five of six tuned
dimensions — see docs/SOVEREIGN_SQUEEZE_OPTIMIZATION_2026-07-31.md for the
full writeup, including the one axis (bb_length/kc_length) that is narrow
rather than broadly robust, disclosed rather than hidden.
"""
from __future__ import annotations

import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sovereign_squeeze_engine import compute_series, SovereignSqueezeParams

BARS_JSON_PATH = os.environ.get(
    "SOVEREIGN_SQZ_OPTIMIZE_BARS_JSON",
    "/root/.claude/projects/-home-user/21c7a031-52d4-5421-adf5-8370d2f7dd16/tool-results/mcp-ROBINHOOD-get_equity_historicals-1785526359713.txt",
)


def _load_bars(symbol_data: dict) -> list:
    return [{
        "date": b["begins_at"][:10],
        "open": float(b["open_price"]), "high": float(b["high_price"]),
        "low": float(b["low_price"]), "close": float(b["close_price"]),
        "volume": float(b["volume"]),
    } for b in symbol_data["bars"]]


def _run_trades(bars: list, p: SovereignSqueezeParams) -> list:
    out = compute_series(bars, p)
    n = len(bars)
    trades = []
    i = 0
    while i < n:
        if out["events"][i] in ("ENTER_CALL", "ENTER_PUT"):
            entry_date = bars[i]["date"]
            j = i + 1
            while j < n and out["events"][j] not in ("EXIT_TARGET", "EXIT_STOP"):
                j += 1
            if j < n:
                trades.append({"entry_date": entry_date, "pnl_pct": out["pnl_pct"][j]})
                i = j + 1
            else:
                break
        else:
            i += 1
    return trades


def _summarize(trades: list) -> dict:
    if not trades:
        return {"trades": 0, "pf": None, "sum_pct": 0.0}
    wins = [t["pnl_pct"] for t in trades if t["pnl_pct"] > 0]
    losses = [t["pnl_pct"] for t in trades if t["pnl_pct"] <= 0]
    gw, gl = sum(wins), abs(sum(losses))
    pf = (gw / gl) if gl > 0 else (float("inf") if gw > 0 else None)
    return {"trades": len(trades),
             "pf": round(pf, 3) if pf not in (None, float("inf")) else pf,
             "sum_pct": round(sum(t["pnl_pct"] for t in trades), 2)}


def load_all_bars(path: str = BARS_JSON_PATH) -> dict:
    with open(path) as f:
        data = json.load(f)
    return {r["symbol"]: _load_bars(r) for r in data["data"]["results"]}


def eval_config(all_bars: dict, p: SovereignSqueezeParams, cutoff_date: str) -> tuple:
    train, valid = [], []
    for bars in all_bars.values():
        for t in _run_trades(bars, p):
            (train if t["entry_date"] < cutoff_date else valid).append(t)
    return _summarize(train), _summarize(valid)


def main():
    all_bars = load_all_bars()
    n_bars = len(next(iter(all_bars.values())))
    cutoff_date = next(iter(all_bars.values()))[int(n_bars * 0.67)]["date"]
    print(f"Bars/symbol: {n_bars}. TRAIN: start..{cutoff_date}   VALID: {cutoff_date}..end\n")

    grid = []
    for bb_kc in [(10, 10), (15, 15), (20, 20), (14, 21), (10, 20)]:
        for mult in [(1.5, 1.0), (2.0, 1.5), (2.5, 2.0)]:
            for min_sqz in [1, 2, 3, 5]:
                for use_rvol, min_rvol in [(False, 1.0), (True, 1.0), (True, 1.2), (True, 1.5), (True, 2.0)]:
                    for use_ema in [False, True]:
                        for rr in [1.0, 1.5, 2.0, 2.5, 3.0]:
                            grid.append(SovereignSqueezeParams(
                                bb_length=bb_kc[0], bb_mult=mult[0], kc_length=bb_kc[1], kc_mult=mult[1],
                                min_sqz_bars=min_sqz, use_rvol=use_rvol, min_rvol=min_rvol,
                                use_macro_ema=use_ema, macro_ema_len=200, rr_ratio=rr,
                            ))

    random.seed(7)
    random.shuffle(grid)
    sample = grid[:600]
    print(f"Grid size: {len(grid)}, sampling {len(sample)} configs (TRAIN-only ranking)\n")

    qualifying = []
    for p in sample:
        train, valid = eval_config(all_bars, p, cutoff_date)
        if train["trades"] >= 15 and train["pf"] is not None and train["pf"] > 1.2:
            qualifying.append((p, train, valid))

    qualifying.sort(key=lambda x: -(x[1]["pf"] or 0))
    print(f"Configs clearing TRAIN filter (>=15 trades, PF>1.2): {len(qualifying)}\n")

    survived = 0
    for p, train, valid in qualifying[:20]:
        held = valid["trades"] >= 3 and valid["pf"] is not None and valid["pf"] > 1.0
        survived += held
        print(f"bb={p.bb_length}/{p.bb_mult} kc={p.kc_length}/{p.kc_mult} min_sqz={p.min_sqz_bars} "
              f"rvol={p.use_rvol}/{p.min_rvol} ema={p.use_macro_ema} rr={p.rr_ratio}  "
              f"TRAIN={train}  VALID={valid}  {'HELD' if held else ''}")

    print(f"\n{survived} of {min(20, len(qualifying))} top TRAIN configs held up on VALID (PF>1.0, >=3 trades).")


if __name__ == "__main__":
    main()
