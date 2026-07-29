#!/usr/bin/env python3
"""
Gamma Ramp Desk — WHAT MAKES IT GOOD (edge stack)

Not a ticker list. A mechanical checklist for Market-Maker forced moves.

══════════════════════════════════════════════════════════════════
EDGE STACK (all gates; meticulous = more than half must fire hard)
══════════════════════════════════════════════════════════════════

1) REGIME — Short / Negative Gamma (MM accelerator, not stabilizer)
   - Positive GEX: MMs fade moves → SKIP options premium long
   - Negative GEX / short gamma: MMs chase → PLAY the forced hedge
   Daily proxy when no chain: elevated realized-vol + impulse day

2) RVOL — Relative Volume ignition
   - Entry: RVOL >= 1.35 (prefer >= 1.8 for full size)
   - Exit:  RVOL fades < 1.05 while in profit → bank the ramp

3) Z-SCORE — Return dislocation vs own history
   - z = (r - μ_20) / σ_20 on log returns
   - CALL setup: z >= +1.5 (upside dislocation)
   - PUT  setup: z <= -1.5 (downside dislocation)
   - |z| >= 2.0 = full aggression tier

4) VPIN / flow toxicity (volume-synchronized PIN proxy)
   - Daily proxy from bar: buy_vol≈v*(c-l)/(h-l), sell_vol≈v*(h-c)/(h-l)
   - vpin = |buy-sell| / (buy+sell) rolling
   - Need VPIN elevated (toxic flow) + signed direction aligned with trade
   - CALL: signed_flow > 0 (ask aggression / upside absorption fail)
   - PUT:  signed_flow < 0

5) DELTA SWEET SPOT — 0.30 to 0.40 (target 0.35)
   - Too high (0.50+): expensive, less gamma torque per dollar
   - Too low (0.10): lottery, needs monster move
   - 0.35: MM must hedge ~35 shares/contract; gamma expands into squeeze

6) SIDE — Calls AND Puts (never calls-only)
   - CALL when: short-gamma + RVOL + z>0 + VPIN buy-flow
   - PUT  when: short-gamma + RVOL + z<0 + VPIN sell-flow
   - Both are MM forced-move trades — direction is the forced hedge side

7) CONTRACT WINDOW
   - Index/ETF scalp: 0–3 DTE
   - HV equity swing: 7–21 DTE
   - Daily backtest proxies hold days, not OPRA stamps

8) EXIT RAILS (keep gains — this is half the edge)
   - Hard stop: -20% premium
   - Scale 1: +50% sell half
   - Scale 2: +150% sell half of runner
   - Trail after scale (22% → 18% late)
   - Delta expansion exit: Δ >= 0.60–0.70 (MM hedge slowing)
   - Harvest band: +50% to +500%
   - RVOL fade in profit → exit
   - Never hold hope through theta if flow dies

9) DYNAMIC UNIVERSE ONLY
   - Fetch actives/movers/beastmode every cycle
   - No hardcoded desk list
   - Strip levered/inverse tox ETFs

══════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Tuple
import math
import numpy as np

# ── Canonical thresholds (live + backtest share these) ───────────────────────
RVOL_ENTRY = 1.35
RVOL_ENTRY_FULL = 1.80
RVOL_EXIT = 1.05

Z_ENTRY = 1.50
Z_FULL = 2.00
Z_WIN = 20  # lookback days for μ,σ

VPIN_ENTRY = 0.28
VPIN_FULL = 0.40
VPIN_WIN = 10

DELTA_MIN = 0.30
DELTA_MAX = 0.40
DELTA_TARGET = 0.35
DELTA_EXIT = 0.60
DELTA_EXIT_HARD = 0.70

HARD_STOP = -0.20
SCALE_TP = 0.50
SCALE2_TP = 1.50
RUNNER_TRAIL = 0.22
RUNNER_TRAIL_LATE = 0.18
TARGET_LO = 0.50
TARGET_HI = 5.00

MIN_GATES_LONG = 4   # of 5 core gates
MIN_GATES_FULL = 5


@dataclass
class EdgeSnapshot:
    symbol: str
    side: str              # CALL | PUT | NONE
    rvol: float
    zscore: float
    vpin: float
    signed_flow: float     # +buy / -sell
    rv: float              # realized vol
    short_gamma: bool
    delta_target: float
    gates_passed: int
    gates: Dict[str, bool]
    score: float           # 0-100 conviction
    full_size: bool
    reason: str


def rvol_at(volumes: np.ndarray, i: int, win: int = 20) -> float:
    if i < win:
        return float("nan")
    base = float(np.mean(volumes[i - win : i]))
    if base <= 0:
        return float("nan")
    return float(volumes[i] / base)


def zscore_at(closes: np.ndarray, i: int, win: int = Z_WIN) -> float:
    if i < win + 1:
        return float("nan")
    # log returns ending at i
    rets = np.diff(np.log(closes[i - win : i + 1]))
    if len(rets) < win:
        return float("nan")
    mu = float(np.mean(rets[:-1])) if len(rets) > 1 else 0.0
    sig = float(np.std(rets[:-1])) if len(rets) > 1 else 0.0
    if sig < 1e-12:
        return 0.0
    return float((rets[-1] - mu) / sig)


def vpin_proxy_series(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    volumes: np.ndarray,
    win: int = VPIN_WIN,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Daily VPIN-style toxicity + signed flow.
    Classify volume with bar close location in range (Lee-Ready-ish daily).
    """
    n = len(closes)
    buy = np.zeros(n)
    sell = np.zeros(n)
    for i in range(n):
        h, l, c, v = float(highs[i]), float(lows[i]), float(closes[i]), float(volumes[i])
        rng = h - l
        if rng <= 1e-12 or v <= 0:
            buy[i] = v * 0.5
            sell[i] = v * 0.5
            continue
        # fraction of bar that closed near high = buy pressure
        buy_frac = (c - l) / rng
        buy_frac = min(1.0, max(0.0, buy_frac))
        buy[i] = v * buy_frac
        sell[i] = v * (1.0 - buy_frac)

    vpin = np.full(n, np.nan)
    signed = np.full(n, np.nan)
    for i in range(win, n):
        b = float(np.sum(buy[i - win + 1 : i + 1]))
        s = float(np.sum(sell[i - win + 1 : i + 1]))
        tot = b + s
        if tot <= 0:
            continue
        vpin[i] = abs(b - s) / tot
        signed[i] = (b - s) / tot  # + buy tox, - sell tox
    return vpin, signed


def realized_vol_at(closes: np.ndarray, i: int, win: int = 10) -> float:
    if i < win:
        return float("nan")
    rets = np.diff(np.log(closes[i - win + 1 : i + 1]))
    if len(rets) < 2:
        return float("nan")
    return float(np.std(rets) * math.sqrt(252))


def short_gamma_proxy(
    i: int,
    closes: np.ndarray,
    rvol: float,
    rv: float,
    rv_hist: np.ndarray,
) -> bool:
    """
    Without full GEX chain: short-gamma-ish = elevated RV regime + volume ignition.
    Live engine replaces this with Tradier/chain GEX when available.
    """
    if i < 5 or math.isnan(rvol) or math.isnan(rv):
        return False
    if rvol < RVOL_ENTRY:
        return False
    hist = rv_hist[max(0, i - 40) : i]
    hist = hist[~np.isnan(hist)]
    if len(hist) < 10:
        return False
    # vol elevated vs its own median → dealers less comfortable / more chase risk
    if rv < float(np.median(hist)) * 1.05:
        return False
    return True


def evaluate_edge(
    symbol: str,
    i: int,
    opens: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    volumes: np.ndarray,
    vpin: np.ndarray,
    signed_flow: np.ndarray,
    rv_series: np.ndarray,
) -> EdgeSnapshot:
    """
    Full gate stack → CALL / PUT / NONE + conviction score.
    """
    rvol = rvol_at(volumes, i)
    z = zscore_at(closes, i)
    vp = float(vpin[i]) if i < len(vpin) and not np.isnan(vpin[i]) else float("nan")
    sf = float(signed_flow[i]) if i < len(signed_flow) and not np.isnan(signed_flow[i]) else float("nan")
    rv = float(rv_series[i]) if i < len(rv_series) and not np.isnan(rv_series[i]) else realized_vol_at(closes, i)

    sg = short_gamma_proxy(i, closes, rvol if not math.isnan(rvol) else 0.0, rv if not math.isnan(rv) else 0.0, rv_series)

    gates = {
        "short_gamma": bool(sg),
        "rvol": (not math.isnan(rvol)) and rvol >= RVOL_ENTRY,
        "zscore": (not math.isnan(z)) and abs(z) >= Z_ENTRY,
        "vpin": (not math.isnan(vp)) and vp >= VPIN_ENTRY,
        "flow_align": False,  # set after side chosen
        "delta_window": True,  # structural — we only buy 0.30-0.40
    }

    # Direction from z + signed flow agreement (MM forced side)
    side = "NONE"
    bull = (not math.isnan(z) and z >= Z_ENTRY) and (math.isnan(sf) or sf > 0.05)
    bear = (not math.isnan(z) and z <= -Z_ENTRY) and (math.isnan(sf) or sf < -0.05)
    # If z and flow disagree, require stronger z
    if not math.isnan(z) and not math.isnan(sf):
        if z >= Z_FULL and sf >= 0:
            bull = True
        if z <= -Z_FULL and sf <= 0:
            bear = True
        if z >= Z_ENTRY and sf < -0.15:
            bull = False  # flow against
        if z <= -Z_ENTRY and sf > 0.15:
            bear = False

    if bull and not bear:
        side = "CALL"
        gates["flow_align"] = math.isnan(sf) or sf > 0.0
    elif bear and not bull:
        side = "PUT"
        gates["flow_align"] = math.isnan(sf) or sf < 0.0
    else:
        side = "NONE"
        gates["flow_align"] = False

    # Core gates for pass count (flow_align only counts if side exists)
    core = ["short_gamma", "rvol", "zscore", "vpin", "flow_align"]
    passed = sum(1 for k in core if gates.get(k))

    score = 0.0
    if gates["short_gamma"]:
        score += 20
    if gates["rvol"]:
        score += 15 + min(15.0, max(0.0, (rvol - RVOL_ENTRY) * 10))
    if gates["zscore"]:
        score += 15 + min(15.0, max(0.0, (abs(z) - Z_ENTRY) * 8))
    if gates["vpin"]:
        score += 15 + min(10.0, max(0.0, (vp - VPIN_ENTRY) * 40))
    if gates["flow_align"]:
        score += 15
    if side != "NONE":
        score += 5
    score = float(min(100.0, score))

    full = (
        side != "NONE"
        and passed >= MIN_GATES_FULL
        and (not math.isnan(rvol) and rvol >= RVOL_ENTRY_FULL)
        and (not math.isnan(z) and abs(z) >= Z_FULL)
    )

    ok = side != "NONE" and passed >= MIN_GATES_LONG and gates["short_gamma"] and gates["rvol"]

    reason_parts = []
    if ok:
        reason_parts.append(f"{side}")
        reason_parts.append(f"rvol={rvol:.2f}" if not math.isnan(rvol) else "rvol=?")
        reason_parts.append(f"z={z:+.2f}" if not math.isnan(z) else "z=?")
        reason_parts.append(f"vpin={vp:.2f}" if not math.isnan(vp) else "vpin=?")
        reason_parts.append(f"flow={sf:+.2f}" if not math.isnan(sf) else "flow=?")
        reason_parts.append(f"gates={passed}/5")
    else:
        reason_parts.append("NO_TRADE")
        dead = [k for k in core if not gates.get(k)]
        reason_parts.append("fail=" + ",".join(dead) if dead else "side_none")

    if not ok:
        side = "NONE"

    return EdgeSnapshot(
        symbol=symbol,
        side=side,
        rvol=float(rvol) if not math.isnan(rvol) else 0.0,
        zscore=float(z) if not math.isnan(z) else 0.0,
        vpin=float(vp) if not math.isnan(vp) else 0.0,
        signed_flow=float(sf) if not math.isnan(sf) else 0.0,
        rv=float(rv) if not math.isnan(rv) else 0.0,
        short_gamma=bool(sg),
        delta_target=DELTA_TARGET,
        gates_passed=int(passed),
        gates=gates,
        score=score,
        full_size=bool(full),
        reason=" ".join(reason_parts),
    )


def edge_checklist() -> Dict[str, Any]:
    """Machine + human readable desk card."""
    return {
        "name": "Gamma Ramp MM Forced-Move Stack",
        "sides": ["CALL", "PUT"],
        "delta": {"min": DELTA_MIN, "max": DELTA_MAX, "target": DELTA_TARGET},
        "gates": {
            "short_gamma": "MM accelerator regime (chain GEX live; RV+RVOL proxy in BT)",
            "rvol": f">= {RVOL_ENTRY} entry, full size >= {RVOL_ENTRY_FULL}, exit fade < {RVOL_EXIT}",
            "zscore": f"|z| >= {Z_ENTRY} (full >= {Z_FULL}) on {Z_WIN}d log-return window",
            "vpin": f">= {VPIN_ENTRY} toxicity (full >= {VPIN_FULL})",
            "flow_align": "signed VPIN direction matches CALL/PUT",
            "delta_window": f"only buy Δ in [{DELTA_MIN},{DELTA_MAX}]",
        },
        "min_gates": MIN_GATES_LONG,
        "exits": {
            "hard_stop": HARD_STOP,
            "scale_1": SCALE_TP,
            "scale_2": SCALE2_TP,
            "trail": RUNNER_TRAIL,
            "trail_late": RUNNER_TRAIL_LATE,
            "delta_exit": DELTA_EXIT,
            "capture_band": [TARGET_LO, TARGET_HI],
        },
        "why_it_prints": [
            "MM short gamma must chase underlying as Δ expands",
            "0.35Δ maximizes gamma torque per premium dollar",
            "RVOL+VPIN confirm forced flow not dead-cat drift",
            "z-score confirms dislocation vs self, not random noise",
            "calls AND puts — forced moves are two-sided",
            "scale/trail exits keep 50-500% ramps from round-tripping",
        ],
    }


if __name__ == "__main__":
    import json
    print(json.dumps(edge_checklist(), indent=2))
