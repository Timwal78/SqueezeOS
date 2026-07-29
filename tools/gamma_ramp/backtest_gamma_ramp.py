#!/usr/bin/env python3
"""
Gamma Ramp Backtest — DYNAMIC UNIVERSE · CALL+PUT · full edge stack

Gates (from edge_stack.py):
  short_gamma · RVOL · z-score · VPIN · flow align · Δ 0.30-0.40

Exits: -20% stop · +50% scale · +150% scale2 · trail · Δ expansion · 50-500% band

Universe: dynamic fetch only (no hardcoded desk list).
Daily bars = structure validation, not live OPRA expectancy.
"""
from __future__ import annotations

import json
import math
import os
import sys
import urllib.request
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

# local imports
sys.path.insert(0, str(Path(__file__).resolve().parent))
from edge_stack import (  # noqa: E402
    DELTA_TARGET,
    HARD_STOP,
    RVOL_ENTRY,
    RVOL_EXIT,
    SCALE2_TP,
    SCALE_TP,
    TARGET_HI,
    TARGET_LO,
    RUNNER_TRAIL,
    RUNNER_TRAIL_LATE,
    DELTA_EXIT,
    DELTA_EXIT_HARD,
    evaluate_edge,
    edge_checklist,
    vpin_proxy_series,
    realized_vol_at,
)
from edge_stack import realized_vol_at as _rv_at  # noqa: E402

# risk
MAX_HOLD_DAYS = 7
COOLDOWN_DAYS = 1
MAX_RISK_FRAC = 0.015
START_EQUITY = 25_000.0
SLIPPAGE = 0.015
SPREAD_PENALTY = 0.01
THETA_DAILY = -0.04
IV0 = 0.50

_FALLBACK_IF_SOURCES_DOWN = ["SPY", "QQQ", "IWM"]


def load_universe() -> list:
    try:
        from universe import fetch_universe, LEVERAGED_INVERSE_ETFS
        u = fetch_universe()
        syms = [s for s in (u.get("symbols") or []) if s not in LEVERAGED_INVERSE_ETFS]
        if syms:
            print(f"[universe] dynamic fetch count={len(syms)} sources={u.get('sources_ok')} (quality filtered)")
            return syms
        print(f"[universe] empty errors={u.get('errors')}")
    except Exception as e:
        print(f"[universe] fail: {e}")
    print("[universe] EMERGENCY FALLBACK — sources down")
    return list(_FALLBACK_IF_SOURCES_DOWN)


@dataclass
class Bar:
    t: int
    o: float
    h: float
    l: float
    c: float
    v: float


@dataclass
class Trade:
    symbol: str
    side: str
    entry_i: int
    exit_i: int
    entry_px: float
    exit_px: float
    entry_spot: float
    exit_spot: float
    qty: int
    pnl: float
    ret: float
    reason: str
    scaled: bool
    hold_days: int
    rvol: float
    zscore: float
    vpin: float
    score: float
    gates_passed: int


def yahoo_daily(symbol: str, range_: str = "1y") -> List[Bar]:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range={range_}&interval=1d"
    req = urllib.request.Request(url, headers={"User-Agent": "SML-GammaRamp-BT/2.0"})
    with urllib.request.urlopen(req, timeout=25) as r:
        data = json.loads(r.read())
    res = (data.get("chart") or {}).get("result") or []
    if not res:
        return []
    r0 = res[0]
    ts = r0.get("timestamp") or []
    q = (r0.get("indicators") or {}).get("quote") or [{}]
    q0 = q[0] if q else {}
    out: List[Bar] = []
    for i, t in enumerate(ts):
        try:
            o = float(q0["open"][i]); h = float(q0["high"][i]); l = float(q0["low"][i])
            c = float(q0["close"][i]); v = float(q0["volume"][i] or 0)
        except (TypeError, ValueError, KeyError, IndexError):
            continue
        if min(o, h, l, c) <= 0:
            continue
        out.append(Bar(t=int(t), o=o, h=h, l=l, c=c, v=v))
    return out


def synth_premium(spot: float, delta: float = DELTA_TARGET) -> float:
    return max(0.15, spot * 0.012 * (delta / 0.35) * (IV0 / 0.40))


def option_path(
    spot0: float,
    spots: np.ndarray,
    prem0: float,
    side: str,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    0.35Δ premium path for CALL or PUT.
    PUT uses inverted underlying returns (downside MM chase).
    """
    n = len(spots)
    marks = np.zeros(n)
    deltas = np.zeros(n)
    marks[0] = prem0
    deltas[0] = DELTA_TARGET
    sign = 1.0 if side == "CALL" else -1.0
    for i in range(1, n):
        s0 = float(spots[i - 1]); s1 = float(spots[i])
        raw_ret = (s1 - s0) / max(s0, 1e-9)
        ret = sign * raw_ret  # favorable direction for this side
        if ret >= 0:
            deltas[i] = min(0.92, deltas[i - 1] + 2.8 * ret + 6.0 * (ret ** 2))
            lev = 7.5 + 12.0 * max(0.0, deltas[i - 1] - 0.30)
            opt_ret = lev * ret + 18.0 * max(0.0, ret) ** 2
        else:
            deltas[i] = max(0.05, deltas[i - 1] + 3.5 * ret)
            lev = 6.0 + 8.0 * max(0.0, deltas[i - 1] - 0.25)
            opt_ret = lev * ret - 4.0 * (ret ** 2)
        opt_ret += THETA_DAILY
        # vs entry spot in side-space
        moved = sign * (s1 - spot0) / max(spot0, 1e-9)
        if moved <= -0.015:
            opt_ret -= 0.08
        if moved <= -0.03:
            opt_ret -= 0.12
        if moved >= 0.03 and deltas[i] >= 0.50:
            opt_ret += 0.10
        if moved >= 0.06 and deltas[i] >= 0.60:
            opt_ret += 0.18
        if moved >= 0.10 and deltas[i] >= 0.70:
            opt_ret += 0.25
        marks[i] = max(0.01, marks[i - 1] * (1.0 + opt_ret))
        if marks[i] > marks[i - 1] * 3.5:
            marks[i] = marks[i - 1] * 3.5
    return marks, deltas


def rv_series(closes: np.ndarray, win: int = 10) -> np.ndarray:
    out = np.full(len(closes), np.nan)
    for i in range(win, len(closes)):
        out[i] = realized_vol_at(closes, i, win)
    return out


def backtest_symbol(symbol: str, bars: List[Bar]) -> Tuple[List[Trade], Dict[str, Any]]:
    if len(bars) < 60:
        return [], {"symbol": symbol, "error": "thin_history", "bars": len(bars), "trades": 0}

    opens = np.array([b.o for b in bars], float)
    highs = np.array([b.h for b in bars], float)
    lows = np.array([b.l for b in bars], float)
    closes = np.array([b.c for b in bars], float)
    vols = np.array([b.v for b in bars], float)
    vpin, signed = vpin_proxy_series(highs, lows, closes, vols)
    rvs = rv_series(closes)

    trades: List[Trade] = []
    i = 30
    cool_until = -1

    while i < len(bars) - 2:
        if i < cool_until:
            i += 1
            continue

        edge = evaluate_edge(symbol, i, opens, highs, lows, closes, vols, vpin, signed, rvs)
        if edge.side == "NONE":
            i += 1
            continue

        spot0 = float(closes[i])
        prem0 = synth_premium(spot0) * (1.0 + SLIPPAGE + SPREAD_PENALTY)
        end = min(len(bars) - 1, i + MAX_HOLD_DAYS)
        spots = closes[i : end + 1]
        marks, deltas = option_path(spot0, spots, prem0, edge.side)

        peak = marks[0]
        scaled = False
        scale_frac = 0.0
        exit_j = len(marks) - 1
        reason = "time"
        # RVOL series for fade exits
        from edge_stack import rvol_at

        for j in range(1, len(marks)):
            m = marks[j]
            peak = max(peak, m)
            ret = (m - marks[0]) / marks[0]
            if ret <= HARD_STOP:
                exit_j, reason = j, "hard_stop"
                break
            if (not scaled) and ret >= SCALE_TP:
                scaled, scale_frac, peak = True, 0.5, m
            if scaled and scale_frac < 0.75 and ret >= SCALE2_TP:
                scale_frac, peak = 0.75, m
            if scaled:
                trail = RUNNER_TRAIL_LATE if scale_frac >= 0.75 else RUNNER_TRAIL
                if peak > 0 and (m - peak) / peak <= -trail:
                    exit_j, reason = j, "trail"
                    break
            if ret >= TARGET_HI * 0.90:
                exit_j, reason = j, "target_500"
                break
            if deltas[j] >= DELTA_EXIT_HARD and ret >= 1.0:
                exit_j, reason = j, "delta_expansion"
                break
            if deltas[j] >= DELTA_EXIT and ret >= 0.50 and not scaled:
                scaled, scale_frac, peak = True, 0.5, m
            ii = i + j
            rvj = rvol_at(vols, ii)
            if not math.isnan(rvj) and rvj < RVOL_EXIT and ret >= TARGET_LO:
                exit_j, reason = j, "rvol_fade"
                break
            if (not scaled) and peak > marks[0] * 1.35 and ret < 0.12:
                exit_j, reason = j, "giveback_lock"
                break
            if scaled and ret < 0.15 and peak >= marks[0] * 1.5:
                exit_j, reason = j, "protect_scale"
                break

        exit_mark = marks[exit_j] * (1.0 - SLIPPAGE)
        entry_mark = marks[0]
        if scaled:
            if scale_frac >= 0.75:
                ret_full = 0.50 * SCALE_TP + 0.25 * SCALE2_TP + 0.25 * ((exit_mark - entry_mark) / entry_mark)
            else:
                ret_full = 0.50 * SCALE_TP + 0.50 * ((exit_mark - entry_mark) / entry_mark)
        else:
            ret_full = (exit_mark - entry_mark) / entry_mark

        trades.append(
            Trade(
                symbol=symbol,
                side=edge.side,
                entry_i=i,
                exit_i=i + exit_j,
                entry_px=round(entry_mark, 4),
                exit_px=round(exit_mark, 4),
                entry_spot=round(spot0, 4),
                exit_spot=round(float(spots[exit_j]), 4),
                qty=1,
                pnl=0.0,
                ret=float(ret_full),
                reason=reason,
                scaled=scaled,
                hold_days=int(exit_j),
                rvol=edge.rvol,
                zscore=edge.zscore,
                vpin=edge.vpin,
                score=edge.score,
                gates_passed=edge.gates_passed,
            )
        )
        cool_until = i + exit_j + COOLDOWN_DAYS
        i = cool_until + 1

    stats: Dict[str, Any] = {"symbol": symbol, "bars": len(bars), "trades": len(trades)}
    if trades:
        rets = np.array([t.ret for t in trades])
        stats.update({
            "win_rate": float(np.mean(rets > 0)),
            "avg_ret": float(np.mean(rets)),
            "med_ret": float(np.median(rets)),
            "best": float(np.max(rets)),
            "worst": float(np.min(rets)),
            "avg_hold_days": float(np.mean([t.hold_days for t in trades])),
            "hit_50pct": int(np.sum(rets >= 0.50)),
            "hit_150pct": int(np.sum(rets >= 1.50)),
            "hit_300pct": int(np.sum(rets >= 3.00)),
            "hit_500pct": int(np.sum(rets >= 5.00)),
            "calls": sum(1 for t in trades if t.side == "CALL"),
            "puts": sum(1 for t in trades if t.side == "PUT"),
            "exit_reasons": {r: sum(1 for t in trades if t.reason == r) for r in set(t.reason for t in trades)},
            "avg_score": float(np.mean([t.score for t in trades])),
            "avg_gates": float(np.mean([t.gates_passed for t in trades])),
        })
    return trades, stats


def portfolio_sim(all_trades: List[Trade]) -> Dict[str, Any]:
    eq = START_EQUITY
    peak = eq
    max_dd = 0.0
    curve = [eq]
    realized: List[float] = []
    halted = False
    for t in all_trades:
        if eq < START_EQUITY * 0.40 or eq < 1000:
            halted = True
            break
        risk_budget = eq * MAX_RISK_FRAC
        # full-size conviction gets slightly more risk
        if t.score >= 80 and t.gates_passed >= 5:
            risk_budget *= 1.25
        cost = t.entry_px * 100.0
        if cost <= 0:
            continue
        stop_risk_per = cost * abs(HARD_STOP)
        qty = max(1, int(risk_budget // max(stop_risk_per, 1.0)))
        qty = min(qty, 10)
        while qty > 1 and cost * qty > eq * 0.10:
            qty -= 1
        if cost * qty > eq * 0.25:
            continue
        pnl = cost * t.ret * qty
        pnl = max(pnl, -cost * qty)
        t.qty = qty
        t.pnl = round(pnl, 2)
        eq = max(0.0, eq + pnl)
        peak = max(peak, eq)
        max_dd = max(max_dd, (peak - eq) / peak if peak else 0.0)
        curve.append(eq)
        realized.append(t.ret)

    rets = np.array(realized) if realized else np.array([0.0])
    def bucket(lo, hi=None):
        if hi is None:
            return int(np.sum(rets >= lo))
        return int(np.sum((rets >= lo) & (rets < hi)))

    return {
        "start_equity": START_EQUITY,
        "end_equity": round(eq, 2),
        "return_pct": round((eq / START_EQUITY - 1.0) * 100.0, 2),
        "max_drawdown_pct": round(max_dd * 100.0, 2),
        "trades": len(realized),
        "win_rate": round(float(np.mean(rets > 0)) * 100.0, 1) if len(realized) else 0.0,
        "avg_trade_ret_pct": round(float(np.mean(rets)) * 100.0, 2) if len(realized) else 0.0,
        "median_trade_ret_pct": round(float(np.median(rets)) * 100.0, 2) if len(realized) else 0.0,
        "best_trade_pct": round(float(np.max(rets)) * 100.0, 2) if len(realized) else 0.0,
        "worst_trade_pct": round(float(np.min(rets)) * 100.0, 2) if len(realized) else 0.0,
        "capture_ge_50pct": bucket(0.50),
        "capture_ge_150pct": bucket(1.50),
        "capture_ge_300pct": bucket(3.00),
        "capture_ge_500pct": bucket(5.00),
        "capture_50_to_150": bucket(0.50, 1.50),
        "capture_150_to_500": bucket(1.50, 5.00),
        "calls": sum(1 for t in all_trades[:len(realized)] if t.side == "CALL"),
        "puts": sum(1 for t in all_trades[:len(realized)] if t.side == "PUT"),
        "equity_curve_tail": [round(float(x), 2) for x in curve[-10:]],
        "halted_risk_rail": halted,
        "universe_mode": "dynamic_fetch",
        "option_model": "0.35d_call_put_edge_stack_daily_proxy",
        "edge": edge_checklist(),
    }


def main() -> int:
    # load env
    env_path = Path(__file__).resolve().parent.parent / "gamma_ramp.env"
    if env_path.is_file():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

    print("=== GAMMA RAMP BT · DYNAMIC UNIVERSE · CALL+PUT · RVOL/Z/VPIN/Δ/MM ===")
    print(json.dumps(edge_checklist(), indent=2)[:500], "...")
    universe = load_universe()
    print(f"universe={len(universe)} stop={HARD_STOP} scale={SCALE_TP}/{SCALE2_TP} rvol>={RVOL_ENTRY} delta={DELTA_TARGET}")

    per_sym = []
    tagged: List[Tuple[int, Trade]] = []

    for sym in universe:
        try:
            bars = yahoo_daily(sym, "1y")
        except Exception as e:
            print(f"  {sym:6} fetch_fail {e}")
            continue
        if len(bars) < 60:
            print(f"  {sym:6} bars={len(bars):3} SKIP thin_history")
            per_sym.append({"symbol": sym, "bars": len(bars), "trades": 0, "error": "thin_history"})
            continue
        trades, stats = backtest_symbol(sym, bars)
        per_sym.append(stats)
        wr = stats.get("win_rate")
        ar = stats.get("avg_ret")
        print(
            f"  {sym:6} bars={stats.get('bars',0):3} n={stats.get('trades',0):3} "
            f"C/P={stats.get('calls',0)}/{stats.get('puts',0)} "
            f"win={('n/a' if wr is None else f'{wr*100:5.1f}%')} "
            f"avg={('n/a' if ar is None else f'{ar*100:+6.1f}%')} "
            f"hit50={stats.get('hit_50pct',0)} hit150={stats.get('hit_150pct',0)} "
            f"{stats.get('exit_reasons',{})}"
        )
        for t in trades:
            ts = bars[t.exit_i].t if t.exit_i < len(bars) else bars[-1].t
            tagged.append((ts, t))

    tagged.sort(key=lambda x: x[0])
    ordered = [t for _, t in tagged]
    port = portfolio_sim(ordered)
    reasons: Dict[str, int] = {}
    for t in ordered:
        reasons[t.reason] = reasons.get(t.reason, 0) + 1

    print("\n=== PORTFOLIO ===")
    for k, v in port.items():
        if k == "edge":
            continue
        print(f"  {k}: {v}")
    print(f"  exit_reasons: {reasons}")
    print(
        f"  capture >=50%: {port.get('capture_ge_50pct')} | "
        f">=150%: {port.get('capture_ge_150pct')} | "
        f">=300%: {port.get('capture_ge_300pct')} | "
        f">=500%: {port.get('capture_ge_500pct')}"
    )

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "edge": edge_checklist(),
        "per_symbol": per_sym,
        "portfolio": port,
        "exit_reasons": reasons,
        "sample_trades": [asdict(t) for t in ordered[:20]],
        "best_trades": [asdict(t) for t in sorted(ordered, key=lambda x: -x.ret)[:10]],
    }
    out_path = Path("/workspace/squeezeos-temp/logs/gamma_ramp_backtest.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2))
    print(f"\nWrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
