"""
Parameter search for cvd_regime_engine.py with OUT-OF-SAMPLE validation.

WHY THE SPLIT EXISTS (read before trusting any number this prints)
------------------------------------------------------------------
Sweeping ~1000 configurations over a fixed price history will ALWAYS surface
configurations that look excellent. Most of them are fitted noise: with enough
knobs and one dataset, "best" mostly measures which config happened to line up
with this particular sequence of bars. A sweep alone therefore cannot answer
"is this strategy profitable" — it can only answer "which config fits the past."

So the data is split chronologically:

    TRAIN  — the earlier sessions. The search sees ONLY this.
    VALID  — the later sessions. Never touched during the search; every
             candidate is scored on it exactly once, at the end.

That ordering matters: fit on the past, verify forward, which is the only split
that mirrors how the strategy would actually be deployed. A config that wins on
TRAIN and collapses on VALID was curve-fit — that is the expected outcome for
most of them, and reporting it is the point of this script, not a failure of it.

A config is only worth calling a "winner" if it holds up on VALID, on multiple
symbols, with a real trade count. Anything else is noise dressed up as edge.

Everything runs the real, unmodified cvd_regime_engine.compute_series().

Usage:
    python tests/optimize_cvd_regime.py <datadir> [n_configs]
"""
import os
import random
import sys
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cvd_regime_engine import compute_series, CvdParams  # noqa: E402
from tests.backtest_cvd_regime import load_csv  # noqa: E402

TRAIN_FRAC = 0.67
MIN_TRADES_TRAIN = 300      # across all symbols; below this it is not a sample
MIN_SYMBOLS_POSITIVE = 5    # of 8 — a config that only works on one name is noise

# Search space. Deliberately centred on plausible trading values rather than
# extreme ones; an "optimum" at the edge of a grid is usually a fitting artifact.
SPACE = {
    "smooth_len":     [3, 5, 8, 13],
    "slope_len":      [2, 3, 5, 8],
    "htf_minutes":    [15, 30, 60, 120],
    "stdev_len":      [20, 30, 50],
    "ema_len":        [8, 13, 21, 34],
    "min_conviction": [55, 60, 65, 70, 75, 80],
    "use_early":      [True, False],
    "stop_atr":       [0.75, 1.0, 1.5, 2.0, 2.5, 3.0],
    "target_r":       [0.75, 1.0, 1.5, 2.0, 3.0],
    "cooldown_bars":  [0, 2, 3, 6],
    "exit_on_flip":   [True, False],
}

_DATA = {}      # symbol -> (train_bars, valid_bars)


def _split(bars: list) -> tuple:
    """Chronological split on a SESSION boundary, so neither slice starts
    mid-day (the engine resets CVD daily; splitting inside a session would
    hand the validation slice a half-formed session)."""
    days = sorted({b["begins_at"][:10] for b in bars})
    cut_day = days[int(len(days) * TRAIN_FRAC)]
    train = [b for b in bars if b["begins_at"][:10] < cut_day]
    valid = [b for b in bars if b["begins_at"][:10] >= cut_day]
    return train, valid, cut_day


def _init(datadir: str):
    global _DATA
    for path in sorted(os.listdir(datadir)):
        if not path.endswith(".csv"):
            continue
        sym = path.split("_")[0].upper()
        tr, va, _ = _split(load_csv(os.path.join(datadir, path)))
        _DATA[sym] = (tr, va)


def _pf(trades: list) -> float:
    gw = sum(t["pnl_pct"] for t in trades if t["pnl_pct"] > 0)
    gl = abs(sum(t["pnl_pct"] for t in trades if t["pnl_pct"] <= 0))
    if gl == 0:
        return float("inf") if gw > 0 else 0.0
    return gw / gl


def _score(cfg: dict, slice_idx: int) -> dict:
    """slice_idx 0 = TRAIN, 1 = VALID."""
    p = CvdParams(**cfg)
    per = {}
    everything = []
    for sym, slices in _DATA.items():
        out = compute_series(slices[slice_idx], p)
        tr = out["trades"]
        per[sym] = {"trades": len(tr), "pf": round(_pf(tr), 3),
                    "sum": round(sum(t["pnl_pct"] for t in tr), 2)}
        everything.extend(tr)
    pfs = sorted(per[s]["pf"] for s in per)
    med = pfs[len(pfs) // 2] if pfs else 0.0
    n_pos = sum(1 for s in per if per[s]["pf"] > 1.0)
    return {
        "cfg": cfg, "per": per,
        "trades": len(everything),
        "pf": round(_pf(everything), 3),
        "median_pf": round(med, 3),
        "symbols_positive": n_pos,
        "sum": round(sum(t["pnl_pct"] for t in everything), 2),
        "win_rate": round(100.0 * sum(1 for t in everything if t["pnl_pct"] > 0)
                          / len(everything), 1) if everything else 0.0,
    }


def _train_worker(cfg: dict) -> dict:
    return _score(cfg, 0)


def _valid_worker(cfg: dict) -> dict:
    return _score(cfg, 1)


def _sample(n: int, seed: int = 20260730) -> list:
    rng = random.Random(seed)
    seen = set()
    out = []
    while len(out) < n:
        cfg = {k: rng.choice(v) for k, v in SPACE.items()}
        key = tuple(sorted(cfg.items()))
        if key in seen:
            continue
        seen.add(key)
        out.append(cfg)
    return out


def _fmt(r: dict) -> str:
    return (f"PF {r['pf']:>6} medPF {r['median_pf']:>6} +sym {r['symbols_positive']}/8 "
            f"trades {r['trades']:>5} win {r['win_rate']:>5}% sum {r['sum']:>9}")


def _cfg_str(c: dict) -> str:
    return (f"sm{c['smooth_len']} sl{c['slope_len']} htf{c['htf_minutes']} "
            f"sd{c['stdev_len']} ema{c['ema_len']} mc{c['min_conviction']} "
            f"early{int(c['use_early'])} stop{c['stop_atr']} tr{c['target_r']} "
            f"cd{c['cooldown_bars']} flip{int(c['exit_on_flip'])}")


def main(datadir: str, n_configs: int):
    _init(datadir)
    syms = sorted(_DATA)
    tr_days = len({b["begins_at"][:10] for b in _DATA[syms[0]][0]})
    va_days = len({b["begins_at"][:10] for b in _DATA[syms[0]][1]})
    print(f"symbols: {', '.join(syms)}")
    print(f"TRAIN {tr_days} sessions ({len(_DATA[syms[0]][0])} bars/sym)  |  "
          f"VALID {va_days} sessions ({len(_DATA[syms[0]][1])} bars/sym)")

    base = CvdParams()
    base_cfg = {k: getattr(base, k) for k in SPACE}
    print("\n--- BASELINE (shipped defaults) ---")
    print(f"  TRAIN  {_fmt(_score(base_cfg, 0))}")
    print(f"  VALID  {_fmt(_score(base_cfg, 1))}")

    cfgs = _sample(n_configs)
    print(f"\n--- SEARCHING {len(cfgs)} configs on TRAIN ONLY ---", flush=True)
    with Pool(initializer=_init, initargs=(datadir,)) as pool:
        results = pool.map(_train_worker, cfgs, chunksize=4)

    ok = [r for r in results
          if r["trades"] >= MIN_TRADES_TRAIN
          and r["symbols_positive"] >= MIN_SYMBOLS_POSITIVE]
    ok.sort(key=lambda r: (r["median_pf"], r["pf"]), reverse=True)
    print(f"{len(ok)} of {len(results)} configs cleared the TRAIN filters "
          f"(>={MIN_TRADES_TRAIN} trades, >={MIN_SYMBOLS_POSITIVE}/8 symbols PF>1)")
    if not ok:
        print("\nNothing cleared the filters on TRAIN. No candidate to validate.")
        return

    top = ok[:15]
    print("\n--- TOP 15 ON TRAIN (in-sample; expect these to be flattered) ---")
    for i, r in enumerate(top, 1):
        print(f"{i:>3}. {_fmt(r)}\n     {_cfg_str(r['cfg'])}")

    print("\n--- THE SAME 15 ON VALID (never seen by the search) ---", flush=True)
    with Pool(initializer=_init, initargs=(datadir,)) as pool:
        vres = pool.map(_valid_worker, [r["cfg"] for r in top], chunksize=1)

    print(f"{'#':>3}  {'TRAIN medPF':>11} {'VALID medPF':>11} {'VALID PF':>9} "
          f"{'+sym':>5} {'trades':>7} {'sum%':>9}  verdict")
    survivors = []
    for i, (t, v) in enumerate(zip(top, vres), 1):
        held = v["pf"] > 1.0 and v["symbols_positive"] >= MIN_SYMBOLS_POSITIVE
        if held:
            survivors.append((t, v))
        print(f"{i:>3}  {t['median_pf']:>11} {v['median_pf']:>11} {v['pf']:>9} "
              f"{str(v['symbols_positive']) + '/8':>5} {v['trades']:>7} {v['sum']:>9}  "
              f"{'HELD UP' if held else 'collapsed'}")

    print(f"\n{len(survivors)} of {len(top)} candidates held up out-of-sample.")
    if not survivors:
        print("VERDICT: no configuration survived out-of-sample. The TRAIN winners\n"
              "were fitted noise — which is the honest result, and exactly what the\n"
              "split exists to detect. Do NOT ship any config off the TRAIN table.")
        return
    survivors.sort(key=lambda tv: (tv[1]["median_pf"], tv[1]["pf"]), reverse=True)
    bt, bv = survivors[0]
    print("\nBEST OUT-OF-SAMPLE SURVIVOR")
    print(f"  config: {_cfg_str(bt['cfg'])}")
    print(f"  TRAIN : {_fmt(bt)}")
    print(f"  VALID : {_fmt(bv)}")
    print("  VALID per symbol:")
    for s in sorted(bv["per"]):
        d = bv["per"][s]
        print(f"    {s:<6} trades {d['trades']:>4}  PF {d['pf']:>6}  sum {d['sum']:>8}%")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 1000)
