"""
Quad-Score Explosive Breakout Finder parameter search — chronological
TRAIN/VALID split, same disciplined methodology as
tests/optimize_sovereign_squeeze.py / tests/optimize_cvd_regime.py: sweeping
any grid over one history without a forward split reliably manufactures
impressive-looking winners that are pure noise. The search only ever ranks
candidates on TRAIN; each candidate is scored on VALID exactly once.

Real daily bars, 16 symbols (AMC/GME/IWM/SPY/NVDA/QQQ/MSTR/TSLA/PLTR/HOOD/
AMD/MSFT/AAPL/META/COIN/SMCI), 2018-01-02..2026-07-30 where available
(PLTR/HOOD/COIN have shorter real history from their real IPO dates —
their pre-IPO "interpolated" placeholder bars were dropped, not backfilled)
— Robinhood MCP get_equity_historicals, same real-data channel as every
other backtest in this codebase. Point QUAD_SCORE_OPTIMIZE_BARS_JSON at an
equivalent {symbol: [bars]} JSON file to reproduce.

PERFORMANCE NOTE: this sweep only varies GATE thresholds (composite/trend/
trigger/temporal/weekly-ADX minimums) and the ATR stop/target multipliers —
none of the swept params affect the underlying pillar-score math (BB/KC/
ATR/Donchian/HV lengths, EMA periods, RVOL/OBV/CMF windows, etc. are all
held at their shipped defaults). So compression/trend/participation/
trigger/composite and the raw weekly (close, EMA, ADX) values are each
computed ONCE PER SYMBOL and cached — a per-config "replay" over the cache
does only cheap O(n) arithmetic. Without this, a 900-config x 16-symbol
sweep took ~2m47s by naively re-running the full engine every time;
cached, the same sweep runs in a couple of seconds.
"""
from __future__ import annotations

import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import quad_score_engine as qse
from quad_score_engine import QuadScoreParams

BARS_JSON_PATH = os.environ.get(
    "QUAD_SCORE_OPTIMIZE_BARS_JSON",
    "/tmp/claude-0/-home-user/21c7a031-52d4-5421-adf5-8370d2f7dd16/scratchpad/quad_score_bars_all.json",
)

CUTOFF_DATE = os.environ.get("QUAD_SCORE_OPTIMIZE_CUTOFF", "2024-06-01")


def load_all_bars(path: str = BARS_JSON_PATH) -> dict:
    with open(path) as f:
        return json.load(f)


def _weekly_raw(bars: list, p: QuadScoreParams):
    """Same no-lookahead mapping as quad_score_engine._weekly_macro_series,
    but returns the raw (weekly_close, weekly_ema, weekly_adx) triplet per
    daily bar instead of baking in a specific weekly_adx_min threshold —
    lets the sweep vary that threshold for free without recomputing the
    weekly aggregation/EMA/ADX."""
    n = len(bars)
    weekly_bars, day_week_key, key_to_index = qse._aggregate_weekly(bars)
    w_closes = [w["c"] for w in weekly_bars]
    w_highs = [w["h"] for w in weekly_bars]
    w_lows = [w["l"] for w in weekly_bars]
    w_ema200 = qse._ema(w_closes, p.weekly_ema_len)
    w_adx, _ = qse._adx(w_highs, w_lows, w_closes, p.weekly_adx_len)

    out_close = [None] * n
    out_ema = [None] * n
    out_adx = [None] * n
    for i in range(n):
        key = day_week_key[i]
        if key is None or key not in key_to_index:
            continue
        idx = key_to_index[key]
        prior_idx = idx - 1
        if prior_idx < 0 or w_ema200[prior_idx] is None or w_adx[prior_idx] is None:
            continue
        out_close[i] = w_closes[prior_idx]
        out_ema[i] = w_ema200[prior_idx]
        out_adx[i] = w_adx[prior_idx]
    return out_close, out_ema, out_adx


def precompute(all_bars: dict, base_params: QuadScoreParams) -> dict:
    """One real, full engine pass per symbol (pillar scores are independent
    of every swept param), plus the raw weekly triplet. Cached and reused
    across the entire sweep."""
    cache = {}
    for sym, bars in all_bars.items():
        out = qse.compute_series(bars, base_params)
        w_close, w_ema, w_adx = _weekly_raw(bars, base_params)
        cache[sym] = {
            "bars": bars, "compression": out["compression"], "trend": out["trend"],
            "participation": out["participation"], "trigger": out["trigger"],
            "composite": out["composite"], "atr": None,
            "w_close": w_close, "w_ema": w_ema, "w_adx": w_adx,
        }
        # ATR needed for stop/target — recompute cheaply (pure arithmetic,
        # not a rolling percentile) directly here rather than threading it
        # through compute_series's return dict.
        highs = [qse._bar_val(b, "high", "h") for b in bars]
        lows = [qse._bar_val(b, "low", "l") for b in bars]
        closes = [qse._bar_val(b, "close", "c") for b in bars]
        tr = [qse._true_range(highs, lows, closes, i) for i in range(len(bars))]
        cache[sym]["atr"] = qse._wilder_smooth(tr, base_params.atr_length)
        cache[sym]["closes"] = closes
    return cache


def _run_trades_cached(c: dict, p: QuadScoreParams) -> list:
    bars = c["bars"]
    n = len(bars)
    compression, trend, participation, trigger, composite = (
        c["compression"], c["trend"], c["participation"], c["trigger"], c["composite"]
    )
    atr, closes = c["atr"], c["closes"]
    w_close, w_ema, w_adx = c["w_close"], c["w_ema"], c["w_adx"]

    trades = []
    in_pos = False
    entry_price = stop_price = target_price = None
    entry_date = None

    for i in range(n):
        if in_pos:
            close = closes[i]
            if close >= target_price or close <= stop_price:
                pnl_pct = (close - entry_price) / entry_price * 100.0
                trades.append({"entry_date": entry_date, "pnl_pct": pnl_pct})
                in_pos = False
                entry_price = stop_price = target_price = None
            continue

        if (composite[i] is None or trend[i] is None or trigger[i] is None
                or atr[i] is None or not atr[i] or w_ema[i] is None or w_adx[i] is None):
            continue

        lo = max(0, i - p.temporal_lookback)
        window = [compression[j] for j in range(lo, i) if compression[j] is not None]
        temporal_valid = (max(window) >= p.temporal_threshold) if window else False
        macro_valid = (w_close[i] > w_ema[i]) and (w_adx[i] > p.weekly_adx_min)

        entry_signal = (
            composite[i] >= p.th_composite and trend[i] >= p.th_trend
            and trigger[i] >= p.th_trigger and temporal_valid and macro_valid
        )
        if entry_signal:
            entry_price = closes[i]
            stop_price = entry_price - atr[i] * p.atr_stop_mult
            target_price = entry_price + atr[i] * p.atr_tp_mult
            in_pos = True
            entry_date = bars[i].get("date")

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


def eval_config(cache: dict, p: QuadScoreParams, cutoff_date: str) -> tuple:
    train, valid = [], []
    for c in cache.values():
        for t in _run_trades_cached(c, p):
            (train if t["entry_date"] < cutoff_date else valid).append(t)
    return _summarize(train), _summarize(valid)


def build_grid():
    grid = []
    for th_composite in [55.0, 60.0, 65.0, 70.0, 75.0]:
        for th_trend in [40.0, 45.0, 50.0, 55.0]:
            for th_trigger in [45.0, 50.0, 55.0, 60.0, 65.0]:
                for temporal_threshold in [50.0, 55.0, 60.0, 65.0, 70.0]:
                    for weekly_adx_min in [10.0, 12.0, 15.0, 18.0, 22.0]:
                        for atr_stop_mult, atr_tp_mult in [(1.5, 3.0), (2.0, 4.0), (2.5, 5.0), (2.0, 3.0), (1.5, 4.5), (2.5, 3.5)]:
                            grid.append(QuadScoreParams(
                                th_composite=th_composite, th_trend=th_trend, th_trigger=th_trigger,
                                temporal_threshold=temporal_threshold, weekly_adx_min=weekly_adx_min,
                                atr_stop_mult=atr_stop_mult, atr_tp_mult=atr_tp_mult,
                            ))
    return grid


def main():
    all_bars = load_all_bars()
    print(f"Symbols: {sorted(all_bars.keys())}", flush=True)
    print(f"TRAIN: start..{CUTOFF_DATE}   VALID: {CUTOFF_DATE}..end\n", flush=True)

    base_params = QuadScoreParams()
    print("Precomputing pillar scores + weekly regime per symbol (once)...", flush=True)
    cache = precompute(all_bars, base_params)
    print("Precompute done.\n", flush=True)

    grid = build_grid()
    random.seed(11)
    random.shuffle(grid)
    sample_size = int(os.environ.get("QUAD_SCORE_OPTIMIZE_SAMPLE", "3000"))
    sample = grid[:sample_size]
    print(f"Grid size: {len(grid)}, sampling {len(sample)} configs (TRAIN-only ranking)\n", flush=True)

    qualifying = []
    for i, p in enumerate(sample):
        train, valid = eval_config(cache, p, CUTOFF_DATE)
        if train["trades"] >= 25 and train["pf"] is not None and train["pf"] > 1.3:
            qualifying.append((p, train, valid))
        if (i + 1) % 500 == 0:
            print(f"  ...{i+1}/{len(sample)} evaluated, {len(qualifying)} qualifying so far", flush=True)

    qualifying.sort(key=lambda x: -(x[1]["pf"] or 0))
    print(f"\nConfigs clearing TRAIN filter (>=25 trades, PF>1.3): {len(qualifying)}\n", flush=True)

    survived = 0
    for p, train, valid in qualifying[:25]:
        held = valid["trades"] >= 8 and valid["pf"] is not None and valid["pf"] > 1.0
        survived += held
        print(f"composite>={p.th_composite} trend>={p.th_trend} trigger>={p.th_trigger} "
              f"temporal>={p.temporal_threshold} wkAdx>{p.weekly_adx_min} "
              f"atrStop={p.atr_stop_mult}/atrTp={p.atr_tp_mult}  "
              f"TRAIN={train}  VALID={valid}  {'HELD' if held else ''}", flush=True)

    print(f"\n{survived} of {min(25, len(qualifying))} top TRAIN configs held up on VALID (PF>1.0, >=8 trades).", flush=True)


if __name__ == "__main__":
    main()
