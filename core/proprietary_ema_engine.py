"""
SML Proprietary EMA Engine Suite
=================================
Engine 1  — Tesla Sequence (1-24-578-963)
           Digital roots: 1-6-2-9 | 24x geometric expansion | tracks price elastic stretch

Engine 3  — Lucas / Phi² Sequence (11-47-123-321)
           Digital roots: 2-2-6-6 mirror symmetry (containment field)
           Phi² = 2.618 expansion: 47→123 (÷2.617), 123→321 (÷2.609)
           Tracks algorithmic dark-pool volume accumulation

Engine 2 will be wired in when the sequence is provided.
"""

import logging
from typing import List, Optional

logger = logging.getLogger("SML.PropEMA")

PHI     = (1.0 + 5.0 ** 0.5) / 2.0   # 1.61803...
PHI_SQ  = PHI ** 2                    # 2.61803...


# ── Core EMA primitive (matches PineScript ta.ema exactly) ────────────────────

def _ema(values: List[float], period: int) -> List[float]:
    if not values:
        return []
    if period <= 1:
        return list(values)
    k = 2.0 / (period + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1.0 - k))
    return out


def _tail(series: List[float]) -> float:
    return series[-1] if series else 0.0


def _digital_root(n: int) -> int:
    n = abs(n)
    while n >= 10:
        n = sum(int(d) for d in str(n))
    return n


# ── Engine 1 — Tesla Sequence ─────────────────────────────────────────────────

class Engine1_TeslaStretch:
    """
    Periods: 1 · 24 · 578 · 963
    Ratios : 24x seed → 24x^2 ≈ 578 → macro anchor at 963
    Tesla digital signature: 963 contains digits 9-6-3 (descending Tesla triad)

    Tracks how far price is elastically stretched from its macro baseline.
    Used as the primary price-structure engine.
    """

    PERIODS = (1, 24, 578, 963)

    def analyze(self, closes: List[float]) -> dict:
        n = len(closes)
        if n < 10:
            return {"engine": 1, "signal": "INSUFFICIENT_DATA"}

        price = closes[-1]

        ema24  = _tail(_ema(closes, min(24,  n)))
        ema578 = _tail(_ema(closes, min(578, n)))
        ema963 = _tail(_ema(closes, min(963, n)))

        stretch_pct   = (price - ema963) / ema963 * 100 if ema963 else 0.0
        deviation_24  = (price - ema24)  / ema24  * 100 if ema24  else 0.0

        bull_stack = price > ema24 > ema578 > ema963
        bear_stack = price < ema24 < ema578 < ema963

        if abs(stretch_pct) > 15 and bull_stack:
            signal = "ELASTIC_IGNITION_BULL"
        elif abs(stretch_pct) > 15 and bear_stack:
            signal = "ELASTIC_IGNITION_BEAR"
        elif abs(stretch_pct) > 8 and bull_stack:
            signal = "BULL_STRETCH"
        elif abs(stretch_pct) > 8 and bear_stack:
            signal = "BEAR_STRETCH"
        elif abs(stretch_pct) < 1.5:
            signal = "COMPRESSION"
        else:
            signal = "NEUTRAL"

        # Score contribution: 0-25 pts toward Oracle composite
        score_contribution = min(25, abs(stretch_pct) * 1.2) if bull_stack else \
                             max(-25, -abs(stretch_pct) * 1.2) if bear_stack else 0

        return {
            "engine":         1,
            "name":           "Tesla Elastic Stretch",
            "sequence":       "1-24-578-963",
            "ema24":          round(ema24,  4),
            "ema578":         round(ema578, 4),
            "ema963":         round(ema963, 4),
            "stretch_pct":    round(stretch_pct,  3),
            "deviation_24":   round(deviation_24, 3),
            "bull_stack":     bull_stack,
            "bear_stack":     bear_stack,
            "signal":         signal,
            "score_contrib":  round(score_contribution, 2),
        }


# ── Engine 3 — Lucas / Phi² Volume Accumulation ───────────────────────────────

class Engine3_LucasPhi:
    """
    Periods: 11 · 47 · 123 · 321
    Digital roots: 2-2-6-6 (mirror symmetry — "As Above, So Below" containment field)
    Phi² expansion: 47/11=4.27, 123/47=2.617≈Phi², 321/123=2.609≈Phi²

    Ignition bands (11 · 47) — track initial institutional order flow
    Macro baselines (123 · 321) — dark-pool volume ceilings

    Applied to BOTH price and volume in parallel.
    """

    PERIODS       = (11, 47, 123, 321)
    DIGITAL_ROOTS = {11: 2, 47: 2, 123: 6, 321: 6}
    PHI_SQ        = PHI_SQ

    # Phi² tolerance band for expansion validation
    _PHI_SQ_LO = 2.35
    _PHI_SQ_HI = 2.90

    def analyze(self, closes: List[float], volumes: Optional[List[float]] = None) -> dict:
        n = len(closes)
        if n < 11:
            return {"engine": 3, "signal": "INSUFFICIENT_DATA"}

        price = closes[-1]

        # Price EMAs
        p11  = _tail(_ema(closes, min(11,  n)))
        p47  = _tail(_ema(closes, min(47,  n)))
        p123 = _tail(_ema(closes, min(123, n)))
        p321 = _tail(_ema(closes, min(321, n)))

        # Volume VMAs (fall back gracefully if no volume data)
        have_vol = bool(volumes and len(volumes) >= 11)
        nv = len(volumes) if have_vol else 0

        v11  = _tail(_ema(volumes, min(11,  nv))) if have_vol else 0.0
        v47  = _tail(_ema(volumes, min(47,  nv))) if have_vol else 0.0
        v123 = _tail(_ema(volumes, min(123, nv))) if have_vol else 0.0
        v321 = _tail(_ema(volumes, min(321, nv))) if have_vol else 0.0
        vol  = volumes[-1] if have_vol else 0.0

        # ── "As Above, So Below" mirror lock ─────────────────────────
        ignition_bull = price > p11 > p47
        ignition_bear = price < p11 < p47
        macro_bull    = p123 > p321
        macro_bear    = p123 < p321
        mirror_lock_bull = ignition_bull and macro_bull
        mirror_lock_bear = ignition_bear and macro_bear

        # ── Volume bands ─────────────────────────────────────────────
        vol_above_11  = vol > v11  if have_vol else False
        vol_above_47  = vol > v47  if have_vol else False
        vol_above_123 = vol > v123 if have_vol else False
        vol_above_321 = vol > v321 if have_vol else False

        # ── Phi² expansion check (VMA47 / VMA11 ≈ Phi²) ─────────────
        phi_sq_ratio       = v47 / v11 if (have_vol and v11 > 0) else 0.0
        phi_expansion_live = self._PHI_SQ_LO < phi_sq_ratio < self._PHI_SQ_HI

        # ── Signal determination ──────────────────────────────────────
        if vol_above_321 and mirror_lock_bull:
            signal = "DARK_POOL_CEILING_BREACH"
        elif vol_above_123 and mirror_lock_bull:
            signal = "DARK_POOL_ACCUMULATION"
        elif vol_above_47 and phi_expansion_live and ignition_bull:
            signal = "PHI_IGNITION_BULL"
        elif vol_above_47 and phi_expansion_live and ignition_bear:
            signal = "PHI_IGNITION_BEAR"
        elif vol_above_11 and ignition_bull:
            signal = "IGNITION_BAND_ACTIVE"
        elif mirror_lock_bear and vol_above_123:
            signal = "DISTRIBUTION"
        else:
            signal = "NEUTRAL"

        # Score contribution: 0-20 pts toward Oracle composite
        if signal in ("DARK_POOL_CEILING_BREACH", "PHI_IGNITION_BULL", "DARK_POOL_ACCUMULATION"):
            score_contribution = 20 if signal == "DARK_POOL_CEILING_BREACH" else 15
        elif signal == "IGNITION_BAND_ACTIVE":
            score_contribution = 8
        elif signal == "DISTRIBUTION":
            score_contribution = -15
        else:
            score_contribution = 0

        return {
            "engine":   3,
            "name":     "Lucas Phi² Volume Accumulation",
            "sequence": "11-47-123-321",
            "digital_roots": self.DIGITAL_ROOTS,
            "phi_squared":   round(self.PHI_SQ, 4),
            "price": {
                "ema11":  round(p11,  4),
                "ema47":  round(p47,  4),
                "ema123": round(p123, 4),
                "ema321": round(p321, 4),
            },
            "volume": {
                "vma11":   round(v11,  2) if have_vol else None,
                "vma47":   round(v47,  2) if have_vol else None,
                "vma123":  round(v123, 2) if have_vol else None,
                "vma321":  round(v321, 2) if have_vol else None,
                "current": round(vol,  2) if have_vol else None,
            },
            "ignition_bull":      ignition_bull,
            "ignition_bear":      ignition_bear,
            "macro_bull":         macro_bull,
            "mirror_lock_bull":   mirror_lock_bull,
            "mirror_lock_bear":   mirror_lock_bear,
            "phi_sq_ratio":       round(phi_sq_ratio, 4),
            "phi_expansion_live": phi_expansion_live,
            "ceiling_breach":     vol_above_321,
            "signal":             signal,
            "score_contrib":      score_contribution,
        }


# ── Combined runner ───────────────────────────────────────────────────────────

def run_proprietary_suite(closes: List[float],
                          volumes: Optional[List[float]] = None,
                          symbol: str = "") -> dict:
    """Run all available engines and return a unified payload."""
    e1 = Engine1_TeslaStretch().analyze(closes)
    e3 = Engine3_LucasPhi().analyze(closes, volumes)

    # Combined directional score
    raw_score = e1.get("score_contrib", 0) + e3.get("score_contrib", 0)
    # Normalise to 0-100 range (max additive: 45 pts bull)
    combined_score = max(0, min(100, 50 + raw_score))

    # Master signal: if both engines agree, signal is stronger
    e1_bull = e1.get("bull_stack", False)
    e3_bull = e3.get("mirror_lock_bull", False) or e3.get("signal") in (
        "DARK_POOL_CEILING_BREACH", "DARK_POOL_ACCUMULATION",
        "PHI_IGNITION_BULL", "IGNITION_BAND_ACTIVE"
    )
    e1_bear = e1.get("bear_stack", False)
    e3_bear = e3.get("mirror_lock_bear", False) or e3.get("signal") == "DISTRIBUTION"

    if e1_bull and e3_bull:
        consensus = "BULL_CONFLUENCE"
    elif e1_bear and e3_bear:
        consensus = "BEAR_CONFLUENCE"
    elif e1_bull or e3_bull:
        consensus = "BULL_DIVERGENT"
    elif e1_bear or e3_bear:
        consensus = "BEAR_DIVERGENT"
    else:
        consensus = "NEUTRAL"

    return {
        "symbol":         symbol,
        "consensus":      consensus,
        "combined_score": combined_score,
        "engine_1":       e1,
        "engine_3":       e3,
    }
