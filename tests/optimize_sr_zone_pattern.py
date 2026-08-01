"""
S/R Zone + Candlestick Pattern Engine parameter search — chronological
TRAIN/VALID split, same disciplined methodology as
tests/optimize_sovereign_squeeze.py / tests/optimize_quad_score.py: sweeping
any grid over one history without a forward split reliably manufactures
impressive-looking winners that are pure noise. The search only ever ranks
candidates on TRAIN; each candidate is scored on VALID exactly once.

Run per operator directive (2026-08-01) after a full-codebase audit flagged
this as the one live IAM_PRIMARY_SYSTEM engine that never cleared the same
evidentiary bar as the other six (12 trades, PF 1.186, shipped-defaults —
docs/SR_ZONE_PATTERN_BACKTEST_2026-07-30.md). Real daily bars, the same 16
symbols/dataset used for the Quad-Score search (2018-01-02..2026-07-30
where available). Point SR_ZONE_PATTERN_OPTIMIZE_BARS_JSON at an equivalent
{symbol: [bars]} JSON file to reproduce.
"""
from __future__ import annotations

import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sr_zone_pattern_engine import compute_series, ZonePatternParams

BARS_JSON_PATH = os.environ.get(
    "SR_ZONE_PATTERN_OPTIMIZE_BARS_JSON",
    "/tmp/claude-0/-home-user/21c7a031-52d4-5421-adf5-8370d2f7dd16/scratchpad/quad_score_bars_all.json",
)

CUTOFF_DATE = os.environ.get("SR_ZONE_PATTERN_OPTIMIZE_CUTOFF", "2024-06-01")


def load_all_bars(path: str = BARS_JSON_PATH) -> dict:
    with open(path) as f:
        return json.load(f)


def _run_trades(bars: list, p: ZonePatternParams) -> list:
    out = compute_series(bars, p)
    n = len(bars)
    trades = []
    i = 0
    while i < n:
        if out["events"][i] == "ENTER_UP":
            entry_date = bars[i].get("date")
            j = i + 1
            while j < n and out["events"][j] not in ("EXIT_TARGET", "EXIT_STOP", "EXIT_OPPOSITE_ZONE"):
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


def eval_config(all_bars: dict, p: ZonePatternParams, cutoff_date: str) -> tuple:
    train, valid = [], []
    for bars in all_bars.values():
        for t in _run_trades(bars, p):
            (train if t["entry_date"] < cutoff_date else valid).append(t)
    return _summarize(train), _summarize(valid)


def build_grid():
    grid = []
    for bars_ in [5, 7, 10, 14, 20]:
        for no_of_pivots in [2, 3, 4]:
            for zone_expiry in [0, 100, 200, 400]:
                for zone_buffer_pct in [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]:
                    for exit_mode in ["atr_target", "opposite_zone"]:
                        for atr_length in [1, 7, 14, 21]:
                            for atr_stop_mult, atr_target_mult in [(1.0, 2.0), (1.5, 3.0), (2.0, 4.0), (2.0, 3.0)]:
                                if exit_mode == "opposite_zone" and (atr_length != 1 or (atr_stop_mult, atr_target_mult) != (1.5, 3.0)):
                                    continue  # atr params are irrelevant to opposite_zone -- don't waste sweep budget on duplicates
                                grid.append(ZonePatternParams(
                                    bars=bars_, no_of_pivots=no_of_pivots, zone_expiry=zone_expiry,
                                    zone_buffer_pct=zone_buffer_pct, exit_mode=exit_mode,
                                    atr_length=atr_length, atr_stop_mult=atr_stop_mult, atr_target_mult=atr_target_mult,
                                ))
    return grid


def main():
    all_bars = load_all_bars()
    print(f"Symbols: {sorted(all_bars.keys())}", flush=True)
    print(f"TRAIN: start..{CUTOFF_DATE}   VALID: {CUTOFF_DATE}..end\n", flush=True)

    grid = build_grid()
    random.seed(23)
    random.shuffle(grid)
    sample_size = int(os.environ.get("SR_ZONE_PATTERN_OPTIMIZE_SAMPLE", "2000"))
    sample = grid[:sample_size]
    print(f"Grid size: {len(grid)}, sampling {len(sample)} configs (TRAIN-only ranking)\n", flush=True)

    qualifying = []
    for i, p in enumerate(sample):
        train, valid = eval_config(all_bars, p, CUTOFF_DATE)
        if train["trades"] >= 15 and train["pf"] is not None and train["pf"] > 1.2:
            qualifying.append((p, train, valid))
        if (i + 1) % 300 == 0:
            print(f"  ...{i+1}/{len(sample)} evaluated, {len(qualifying)} qualifying so far", flush=True)

    qualifying.sort(key=lambda x: -(x[1]["pf"] or 0))
    print(f"\nConfigs clearing TRAIN filter (>=15 trades, PF>1.2): {len(qualifying)}\n", flush=True)

    survived = 0
    for p, train, valid in qualifying[:25]:
        held = valid["trades"] >= 5 and valid["pf"] is not None and valid["pf"] > 1.0
        survived += held
        print(f"bars={p.bars} pivots={p.no_of_pivots} expiry={p.zone_expiry} buf={p.zone_buffer_pct} "
              f"exit={p.exit_mode} atrLen={p.atr_length} atrStop={p.atr_stop_mult}/atrTgt={p.atr_target_mult}  "
              f"TRAIN={train}  VALID={valid}  {'HELD' if held else ''}", flush=True)

    print(f"\n{survived} of {min(25, len(qualifying))} top TRAIN configs held up on VALID (PF>1.0, >=5 trades).", flush=True)


if __name__ == "__main__":
    main()
