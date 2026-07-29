"""
SML Squeeze Fuel Composite Engine — combines every REAL squeeze-relevant
data source already live in this codebase (plus the new FINRA short-volume
feed) into one weighted score, instead of leaving them as separate,
un-combined signals.

Built per operator directive (2026-07-29): "the best ever squeeze setup...
find and profit off of every squeeze play we can." A genuine short squeeze
needs both FUEL (real shorting pressure trapped in the name) and IGNITION
(a real, current price/volume catalyst forcing that pressure to release).
Before this, this codebase had good ignition detection (squeeze_analyzer.py,
8-module price/volume scoring, already live) and two real fuel-adjacent
signals that were never combined with it: SEC FTD data + Reg SHO threshold-
list status (core/ftd_data.py, already live via CIE) and dealer gamma
positioning (gamma_flow_engine.py, already live via Oracle/Gamma Pin). This
module is the first thing in the codebase that actually combines them.

FOUR REAL COMPONENTS, EACH HONESTLY SCOPED:

  1. IGNITION (0-40): squeeze_analyzer.SqueezeAnalyzer's existing 8-module
     price/volume score, scaled from its native 0-100 to 0-40. Real,
     already-live, unmodified logic -- this module does not re-derive it.

  2. FTD FUEL (0-20): core/ftd_data.py's real SEC fails-to-deliver
     percentile rank within a symbol's own 180-day window, plus a flat
     bonus for currently being on the Reg SHO threshold list (a genuine
     regulatory signal of persistent failures -- GME was on this list for
     an extended stretch during 2021). Real, already-live data.

  3. SHORT-VOLUME PRESSURE (0-20): finra_short_data.py's new FINRA daily
     short-volume-ratio, scored on how far today's ratio sits above this
     symbol's own recent window average. Real, free, official FINRA data --
     but see finra_short_data.py's docstring: this is short VOLUME (today's
     shorting activity), not short INTEREST (total shares currently short
     as % of float). That's the metric everyone actually means by "squeeze
     fuel," and no free, no-account source for it exists anywhere in this
     codebase or was found for one. This component is a real, disclosed
     proxy, not a substitute claimed to be the real thing.

  4. GAMMA AMPLIFIER (0-20): gamma_flow_engine.calculate_gex_profile()'s
     real dealer positioning (already live). A short-gamma regime means
     dealers must buy into upside strength to stay hedged -- a genuine,
     well-documented mechanical amplifier of a squeeze once it starts
     (this is the same mechanism gamma_pin_scanner.py already trades on).
     Requires a live Tradier option chain; scores 0 (disclosed, not
     guessed) when unavailable rather than assuming a regime.

NO BACKTEST EVIDENCE EXISTS FOR THIS COMPOSITE, and none is fabricated to
fill the gap -- same disclosure convention as Gamma Pin. A real backtest
would need historical short-volume-ratio AND historical FTD data on the
same clock as historical price bars; the FTD/threshold archive covers real
history but the FINRA short-volume feed only backfills ~10 trading days by
default (see finra_short_data.BACKFILL_DAYS) since this module was just
built today, and historical options chains still don't exist anywhere in
this codebase (same gap already documented for Gamma Pin/Gamma Ramp). Do
not add SML_SQUEEZE_FUEL to IAM_PRIMARY_SYSTEM or represent this as a
proven signal -- weights below are a transparent, disclosed starting point
(not curve-fit to any dataset), not evidence of anything.

Only fires BUY (this is a squeeze-fuel detector, not a short-squeeze-
reversal short seller -- inventing a short-side mechanic here without
evidence would be the same un-backtested-action mistake documented in
breakout_engine.py's and mm_intel_scanner.py's docstrings for their own
narrower live-signal mappings). Downside protection on any live position
this fires comes from iam_executor's own real stop-loss order
(IAM_STOP_LOSS_PCT), exactly like every other entry-only engine here.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Optional


IGNITION_WEIGHT = 40.0
FTD_WEIGHT = 20.0
SHORT_VOL_WEIGHT = 20.0
GAMMA_WEIGHT = 20.0

ENTRY_THRESHOLD = 70.0  # composite score (0-100) required to fire a BUY


def _sigmoid(x: float, center: float, steepness: float) -> float:
    try:
        return 1.0 / (1.0 + math.exp(-steepness * (x - center)))
    except OverflowError:
        return 1.0 if x > center else 0.0


@dataclass
class FuelComponents:
    ignition: float
    ignition_available: bool
    ftd_fuel: float
    ftd_available: bool
    on_threshold_list: bool
    short_vol_fuel: float
    short_vol_available: bool
    gamma_amp: float
    gamma_available: bool
    gamma_regime: Optional[str]

    @property
    def composite(self) -> float:
        return round(self.ignition + self.ftd_fuel + self.short_vol_fuel + self.gamma_amp, 2)

    def as_dict(self) -> dict:
        return {
            "composite_score": self.composite,
            "ignition": {"score": round(self.ignition, 2), "max": IGNITION_WEIGHT, "available": self.ignition_available},
            "ftd_fuel": {"score": round(self.ftd_fuel, 2), "max": FTD_WEIGHT, "available": self.ftd_available,
                         "on_reg_sho_threshold_list": self.on_threshold_list},
            "short_volume_fuel": {"score": round(self.short_vol_fuel, 2), "max": SHORT_VOL_WEIGHT,
                                   "available": self.short_vol_available,
                                   "note": "FINRA short VOLUME proxy, not short INTEREST -- see finra_short_data.py docstring"},
            "gamma_amplifier": {"score": round(self.gamma_amp, 2), "max": GAMMA_WEIGHT,
                                 "available": self.gamma_available, "regime": self.gamma_regime},
        }


def _ignition_score(symbol: str, quote_data: Optional[dict], history: Optional[list]) -> tuple:
    if not quote_data:
        return 0.0, False, "NEUTRAL"
    try:
        from squeeze_analyzer import SqueezeAnalyzer
        result = SqueezeAnalyzer().analyze_symbol(symbol, quote_data=quote_data, history=history)
    except Exception:
        return 0.0, False, "NEUTRAL"
    if not result:
        return 0.0, False, "NEUTRAL"
    raw = result.get("squeeze_score", 0.0)  # already 0-100
    return round((raw / 100.0) * IGNITION_WEIGHT, 2), True, result.get("direction", "NEUTRAL")


def _ftd_fuel_score(symbol: str) -> tuple:
    try:
        from core.ftd_data import get_store
        store = get_store()
        ratio = store.latest_ratio(symbol)
        on_list = store.is_on_threshold_list(symbol)
    except Exception:
        return 0.0, False, False
    if ratio is None and not on_list:
        return 0.0, False, False
    percentile = ratio["rank_percentile"] if ratio else 0.0
    score = percentile * (FTD_WEIGHT * 0.6)
    if on_list:
        score += FTD_WEIGHT * 0.4
    return round(min(score, FTD_WEIGHT), 2), (ratio is not None), on_list


def _short_vol_fuel_score(symbol: str) -> tuple:
    try:
        from finra_short_data import get_store
        latest = get_store().latest(symbol)
    except Exception:
        return 0.0, False
    if not latest:
        return 0.0, False
    delta = latest["ratio_vs_window_avg"]  # e.g. +0.15 = 15pp above this symbol's own recent average
    # Sigmoid-mapped: +0.10 above own average -> ~half credit, +0.25 -> near full.
    score = _sigmoid(delta, 0.10, 12.0) * SHORT_VOL_WEIGHT
    return round(score, 2), True


def _gamma_amp_score(symbol: str, raw_chain: Optional[dict], spot: float) -> tuple:
    if not raw_chain or spot <= 0:
        return 0.0, False, None
    try:
        from gamma_flow_engine import calculate_gex_profile
        profile = calculate_gex_profile(raw_chain, spot, symbol)
    except Exception:
        return 0.0, False, None
    if not profile:
        return 0.0, False, None
    if profile.profile_shape == "short_gamma":
        score = GAMMA_WEIGHT if spot > profile.zero_gamma_line else GAMMA_WEIGHT * 0.6
    else:
        score = GAMMA_WEIGHT * 0.15  # long-gamma dealers dampen moves, not amplify them
    return round(score, 2), True, profile.profile_shape


def compute_fuel(symbol: str, quote_data: Optional[dict] = None, history: Optional[list] = None,
                  raw_chain: Optional[dict] = None) -> FuelComponents:
    spot = float((quote_data or {}).get("price", 0) or 0)
    ignition, ign_avail, direction = _ignition_score(symbol, quote_data, history)
    ftd_fuel, ftd_avail, on_list = _ftd_fuel_score(symbol)
    sv_fuel, sv_avail = _short_vol_fuel_score(symbol)
    gamma_amp, gamma_avail, gamma_regime = _gamma_amp_score(symbol, raw_chain, spot)
    comp = FuelComponents(
        ignition=ignition, ignition_available=ign_avail,
        ftd_fuel=ftd_fuel, ftd_available=ftd_avail, on_threshold_list=on_list,
        short_vol_fuel=sv_fuel, short_vol_available=sv_avail,
        gamma_amp=gamma_amp, gamma_available=gamma_avail, gamma_regime=gamma_regime,
    )
    comp._direction = direction  # stashed for analyze(); not part of the public dataclass fields
    return comp


def analyze(symbol: str, quote_data: Optional[dict] = None, history: Optional[list] = None,
            raw_chain: Optional[dict] = None) -> dict:
    """On-demand single-symbol wrapper -- same convention as every other
    engine's analyze() in this codebase (druck_engine.py, orb_engine.py)."""
    comp = compute_fuel(symbol, quote_data, history, raw_chain)
    direction = getattr(comp, "_direction", "NEUTRAL")
    action = "BUY" if (comp.composite >= ENTRY_THRESHOLD and direction == "BULLISH") else None
    out = comp.as_dict()
    out["symbol"] = symbol.upper()
    out["direction"] = direction
    out["action"] = action
    out["entry_threshold"] = ENTRY_THRESHOLD
    out["disclosure"] = (
        "No backtest evidence exists for this composite -- see module docstring. "
        "Weights are a transparent starting point, not curve-fit or validated."
    )
    return out
