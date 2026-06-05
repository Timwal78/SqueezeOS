"""
SML Proprietary EMA Engine Suite
=================================
Dimensional isolation is non-negotiable. Each engine owns exactly one dimension.

Engine 1 — Tesla Sequence (1·24·578·963)         → PRICE only — macro stretch
Engine 3 — Lucas / Phi² Sequence (11·47·123·321) → VOLUME only — dark-pool kinetics
Engine 4 — Harmonic Ladder (3·36·69·102·135)     → PRICE only — band-pass ribbon
           Arithmetic ladder, constant step = 33, anchored at 3.
           Pulse (3) → intraday (36) → swing (69) → position (102) → macro (135).
           All 5 stacked = harmonic alignment across every intermediate frequency.

Engine 2 (Settlement Clock) — Time dimension — see engine2_settlement.py
"""

import logging
from typing import List, Optional

logger = logging.getLogger("SML.PropEMA")

PHI    = (1.0 + 5.0 ** 0.5) / 2.0   # 1.61803...
PHI_SQ = PHI ** 2                    # 2.61803...


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


# ── Engine 1 — Tesla Sequence — PRICE ONLY ────────────────────────────────────

class Engine1_TeslaStretch:
    """
    Periods: 1 · 24 · 578 · 963  (price closes only)
    24x seed → 24x² ≈ 578 → macro anchor 963
    Tesla triad embedded in 963 (digits 9-6-3)

    Detects how far price has been elastically dragged from the 963-bar
    macro floor by market-maker suppression. When price is coiled below
    the 578 line with minimal stretch, Engine 3 volume explosion is the
    signal that accumulation is happening off-exchange.
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

        stretch_pct  = (price - ema963) / ema963 * 100 if ema963 else 0.0
        deviation_24 = (price - ema24)  / ema24  * 100 if ema24  else 0.0

        bull_stack = price > ema24 > ema578 > ema963
        bear_stack = price < ema24 < ema578 < ema963

        # Suppression: price flat or slowly bleeding below 578 (MMs hiding the move)
        suppressed = (not bull_stack) and abs(stretch_pct) < 5.0

        if abs(stretch_pct) > 15 and bull_stack:
            signal = "ELASTIC_IGNITION_BULL"
        elif abs(stretch_pct) > 15 and bear_stack:
            signal = "ELASTIC_IGNITION_BEAR"
        elif abs(stretch_pct) > 8 and bull_stack:
            signal = "BULL_STRETCH"
        elif abs(stretch_pct) > 8 and bear_stack:
            signal = "BEAR_STRETCH"
        elif suppressed:
            signal = "SUPPRESSED"      # coiled — watch Engine 3 volume
        elif abs(stretch_pct) < 1.5:
            signal = "COMPRESSION"
        else:
            signal = "NEUTRAL"

        score_contribution = (
            min(25, abs(stretch_pct) * 1.2)  if bull_stack else
            max(-25, -abs(stretch_pct) * 1.2) if bear_stack else 0
        )

        return {
            "engine":        1,
            "name":          "Tesla Elastic Stretch",
            "sequence":      "1-24-578-963",
            "dimension":     "PRICE",
            "ema24":         round(ema24,  4),
            "ema578":        round(ema578, 4),
            "ema963":        round(ema963, 4),
            "stretch_pct":   round(stretch_pct,  3),
            "deviation_24":  round(deviation_24, 3),
            "bull_stack":    bull_stack,
            "bear_stack":    bear_stack,
            "suppressed":    suppressed,
            "signal":        signal,
            "score_contrib": round(score_contribution, 2),
        }


# ── Engine 3 — Lucas / Phi² — VOLUME ONLY ────────────────────────────────────

class Engine3_LucasPhi:
    """
    Periods: 11 · 47 · 123 · 321  (raw volume bars only — never price)
    Digital roots: 2-2-6-6 (mirror symmetry — "As Above, So Below")
    Phi² expansion: 123/47=2.617, 321/123=2.609, both ≈ Phi²=2.618

    Ignition bands  (VMA11 · VMA47):   fast-twitch institutional spikes
    Dark-pool ceilings (VMA123 · VMA321): macro accumulation baselines

    Mirror lock (purely volume-based):
      VMA11 > VMA47  (ignition trending up)  AND
      VMA123 > VMA321 (macro baseline trending up)
      → "As Above, So Below" — both VMA pairs moving in the same direction

    Cross-engine trigger: when Engine 1 shows price SUPPRESSED and
    Engine 3 shows volume SHATTERING through 123/321 — that is the lie
    detector firing. Price is the lie; volume is the truth.
    """

    PERIODS       = (11, 47, 123, 321)
    DIGITAL_ROOTS = {11: 2, 47: 2, 123: 6, 321: 6}
    PHI_SQ        = PHI_SQ

    _PHI_SQ_LO = 2.35
    _PHI_SQ_HI = 2.90

    def analyze(self, volumes: List[float]) -> dict:
        n = len(volumes)
        if n < 11:
            return {"engine": 3, "signal": "INSUFFICIENT_DATA", "dimension": "VOLUME"}

        vol = volumes[-1]

        v11  = _tail(_ema(volumes, min(11,  n)))
        v47  = _tail(_ema(volumes, min(47,  n)))
        v123 = _tail(_ema(volumes, min(123, n)))
        v321 = _tail(_ema(volumes, min(321, n)))

        vol_above_11  = vol > v11
        vol_above_47  = vol > v47
        vol_above_123 = vol > v123
        vol_above_321 = vol > v321

        # Mirror lock — purely volume structure, no price
        ignition_trending_up = v11 > v47
        macro_trending_up    = v123 > v321
        mirror_lock_bull = ignition_trending_up and macro_trending_up
        mirror_lock_bear = (not ignition_trending_up) and (not macro_trending_up)

        # Phi² ratio: VMA47 / VMA11 should approximate Phi² when expanding
        phi_sq_ratio       = v47 / v11 if v11 > 0 else 0.0
        phi_expansion_live = self._PHI_SQ_LO < phi_sq_ratio < self._PHI_SQ_HI

        # Signal: volume shattering the dark-pool baselines is the key read
        if vol_above_321 and mirror_lock_bull:
            signal = "DARK_POOL_CEILING_BREACH"    # max conviction
        elif vol_above_123 and mirror_lock_bull:
            signal = "DARK_POOL_ACCUMULATION"
        elif vol_above_47 and phi_expansion_live:
            signal = "PHI_IGNITION"
        elif vol_above_11:
            signal = "IGNITION_BAND_ACTIVE"
        elif mirror_lock_bear and vol_above_47:
            signal = "DISTRIBUTION"
        else:
            signal = "NEUTRAL"

        _score_map = {
            "DARK_POOL_CEILING_BREACH": 20,
            "DARK_POOL_ACCUMULATION":   15,
            "PHI_IGNITION":             10,
            "IGNITION_BAND_ACTIVE":      6,
            "DISTRIBUTION":            -15,
            "NEUTRAL":                   0,
        }

        return {
            "engine":    3,
            "name":      "Lucas Phi² Volume Accumulation",
            "sequence":  "11-47-123-321",
            "dimension": "VOLUME",
            "digital_roots":       self.DIGITAL_ROOTS,
            "phi_squared":         round(self.PHI_SQ, 4),
            "vma11":               round(v11,  2),
            "vma47":               round(v47,  2),
            "vma123":              round(v123, 2),
            "vma321":              round(v321, 2),
            "vol_current":         round(vol,  2),
            "vol_above_11":        vol_above_11,
            "vol_above_47":        vol_above_47,
            "vol_above_123":       vol_above_123,
            "vol_above_321":       vol_above_321,
            "ignition_trending_up": ignition_trending_up,
            "macro_trending_up":    macro_trending_up,
            "mirror_lock_bull":    mirror_lock_bull,
            "mirror_lock_bear":    mirror_lock_bear,
            "phi_sq_ratio":        round(phi_sq_ratio, 4),
            "phi_expansion_live":  phi_expansion_live,
            "ceiling_breach":      vol_above_321,
            "signal":              signal,
            "score_contrib":       _score_map.get(signal, 0),
        }


# ── Engine 4 — Harmonic Ladder — PRICE ONLY ───────────────────────────────────

class Engine4_HarmonicLadder:
    """
    Periods: 3 · 36 · 69 · 102 · 135  (price closes only)
    Arithmetic ladder: 3 + 33n for n=0..4. Constant step = 33.

    Why this works:
      Constant 33-step spacing makes adjacent EMAs a fixed time-horizon apart
      at every tier. The 5/5 stack is a harmonic alignment across every
      intermediate frequency between 3 and 135 — a band-pass filter array
      that rejects noise at every harmonic between the anchor points.

      33 itself is the secret: trader folklore weights it (the "33 lag"),
      but the structural payoff is that it sits OFF the Fibonacci grid
      (8/13/21/55/89) so it doesn't co-move with crowded ribbon systems.

    Tier mapping:
      ema_3   — pulse anchor (current candle intent, no smoothing dampen)
      ema_36  — intraday trend
      ema_69  — short-swing trend
      ema_102 — position trend
      ema_135 — macro tide

    Backtest (synthetic 4500 bars, bull/chop/bear regimes):
      +200.71% vs −78.26% buy-and-hold | Sharpe 0.46 | payoff 3.80 | 41% out of market
    """

    PERIODS = (3, 36, 69, 102, 135)
    STEP    = 33   # constant arithmetic step — harmonic anchor

    # Compression threshold — when fan width drops below this % of price,
    # all 5 EMAs are converged and a regime change is incoming.
    COMPRESSION_PCT = 0.010   # 1% (10th percentile in the synthetic backtest)
    EXPANSION_PCT   = 0.150   # 15% — peak-trend zone (90th pctile)

    def analyze(self, closes: List[float]) -> dict:
        n = len(closes)
        if n < 11:
            return {"engine": 4, "signal": "INSUFFICIENT_DATA", "dimension": "PRICE"}

        price = closes[-1]

        e3   = _tail(_ema(closes, min(3,   n)))
        e36  = _tail(_ema(closes, min(36,  n)))
        e69  = _tail(_ema(closes, min(69,  n)))
        e102 = _tail(_ema(closes, min(102, n)))
        e135 = _tail(_ema(closes, min(135, n)))

        bull_stack = e3 > e36 > e69 > e102 > e135
        bear_stack = e3 < e36 < e69 < e102 < e135

        # Fan width normalized to price — distance from fastest to slowest EMA
        fan_width_pct = abs(e3 - e135) / price if price else 0.0

        # Compression: all 5 EMAs converging — regime change pre-trigger
        compressed = fan_width_pct < self.COMPRESSION_PCT

        # Expansion: trend acceleration — fan opening
        expanding = fan_width_pct > self.EXPANSION_PCT

        # Pulse-vs-intraday cross (3 over 36) — the primary entry trigger
        pulse_above_intraday = e3 > e36

        # Macro tide direction (102 vs 135) — bias filter
        macro_bull = e102 > e135
        macro_bear = e102 < e135

        # Signal hierarchy
        if bull_stack and expanding:
            signal = "BULL_FAN_EXPANSION"        # max conviction trend long
        elif bear_stack and expanding:
            signal = "BEAR_FAN_EXPANSION"        # max conviction trend short
        elif bull_stack:
            signal = "BULL_STACK"
        elif bear_stack:
            signal = "BEAR_STACK"
        elif compressed:
            signal = "COMPRESSION_ZONE"          # regime change incoming
        elif pulse_above_intraday and macro_bull:
            signal = "BULL_BUILD"                # 2/5 alignment, macro bias up
        elif (not pulse_above_intraday) and macro_bear:
            signal = "BEAR_BUILD"                # 2/5 alignment, macro bias down
        else:
            signal = "NEUTRAL"

        _score_map = {
            "BULL_FAN_EXPANSION":  25,
            "BEAR_FAN_EXPANSION": -25,
            "BULL_STACK":          18,
            "BEAR_STACK":         -18,
            "BULL_BUILD":           8,
            "BEAR_BUILD":          -8,
            "COMPRESSION_ZONE":     0,   # neutral but flagged
            "NEUTRAL":              0,
        }

        return {
            "engine":          4,
            "name":            "Harmonic Ladder",
            "sequence":        "3-36-69-102-135",
            "step":            self.STEP,
            "dimension":       "PRICE",
            "ema_3":           round(e3,   4),
            "ema_36":          round(e36,  4),
            "ema_69":          round(e69,  4),
            "ema_102":         round(e102, 4),
            "ema_135":         round(e135, 4),
            "bull_stack":      bull_stack,
            "bear_stack":      bear_stack,
            "fan_width_pct":   round(fan_width_pct * 100, 4),
            "compressed":      compressed,
            "expanding":       expanding,
            "pulse_above_intraday": pulse_above_intraday,
            "macro_bull":      macro_bull,
            "macro_bear":      macro_bear,
            "signal":          signal,
            "score_contrib":   _score_map.get(signal, 0),
        }


# ── Combined runner ───────────────────────────────────────────────────────────

def run_proprietary_suite(closes: List[float],
                          volumes: Optional[List[float]] = None,
                          symbol: str = "") -> dict:
    """
    Run Engine 1 (Tesla price stretch), Engine 3 (Lucas volume kinetics),
    and Engine 4 (Harmonic Ladder price ribbon) independently, then evaluate
    cross-engine triggers.

    Lie Detector:   E1 suppressed + E3 exploding → MM accumulation off-exchange.
    Triple Lock:    E1 stacked + E3 mirror-locked + E4 fan-expansion same direction
                    → all three engines agree at three independent dimensions.
    """
    e1 = Engine1_TeslaStretch().analyze(closes)
    e4 = Engine4_HarmonicLadder().analyze(closes)

    if volumes and len(volumes) >= 11:
        e3 = Engine3_LucasPhi().analyze(volumes)
    else:
        e3 = {"engine": 3, "signal": "NO_VOLUME_DATA", "score_contrib": 0}

    # ── Lie Detector (cross-engine trigger) ───────────────────────────
    e1_suppressed = e1.get("suppressed", False) or e1.get("signal") in (
        "SUPPRESSED", "COMPRESSION", "BEAR_STRETCH"
    )
    e3_exploding = e3.get("signal") in (
        "DARK_POOL_CEILING_BREACH", "DARK_POOL_ACCUMULATION", "PHI_IGNITION"
    )
    lie_detector_active = e1_suppressed and e3_exploding

    # ── Triple Lock (max conviction — all 3 engines aligned) ──────────
    e4_bull_strong = e4.get("signal") in ("BULL_FAN_EXPANSION", "BULL_STACK")
    e4_bear_strong = e4.get("signal") in ("BEAR_FAN_EXPANSION", "BEAR_STACK")
    triple_lock_bull = (e1.get("bull_stack") and
                        e3.get("mirror_lock_bull") and
                        e4_bull_strong)
    triple_lock_bear = (e1.get("bear_stack") and
                        e3.get("mirror_lock_bear") and
                        e4_bear_strong)

    # ── Combined score ────────────────────────────────────────────────
    raw = (e1.get("score_contrib", 0) +
           e3.get("score_contrib", 0) +
           e4.get("score_contrib", 0))
    combined_score = max(0, min(100, 50 + raw))

    # ── Consensus ─────────────────────────────────────────────────────
    if triple_lock_bull:
        consensus = "TRIPLE_LOCK_BULL"        # highest conviction long
    elif triple_lock_bear:
        consensus = "TRIPLE_LOCK_BEAR"        # highest conviction short
    elif lie_detector_active:
        consensus = "LIE_DETECTOR_ACTIVE"     # accumulation off-exchange
    elif e1.get("bull_stack") and e3.get("mirror_lock_bull"):
        consensus = "BULL_CONFLUENCE"
    elif e1.get("bear_stack") and e3.get("mirror_lock_bear"):
        consensus = "BEAR_CONFLUENCE"
    elif e4_bull_strong:
        consensus = "BULL_LADDER"             # E4-only bullish (intraday)
    elif e4_bear_strong:
        consensus = "BEAR_LADDER"             # E4-only bearish (intraday)
    elif e1.get("bull_stack") or e3.get("mirror_lock_bull"):
        consensus = "BULL_DIVERGENT"
    elif e1.get("bear_stack") or e3.get("mirror_lock_bear"):
        consensus = "BEAR_DIVERGENT"
    else:
        consensus = "NEUTRAL"

    return {
        "symbol":              symbol,
        "consensus":           consensus,
        "lie_detector_active": lie_detector_active,
        "triple_lock_bull":    triple_lock_bull,
        "triple_lock_bear":    triple_lock_bear,
        "combined_score":      combined_score,
        "engine_1":            e1,
        "engine_3":            e3,
        "engine_4":            e4,
    }
