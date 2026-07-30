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

RSI-CROSS-ABOVE-50 CONFIRMATION (added 2026-07-30, operator directive):
a free-data-only re-implementation of a real 3-tier short-squeeze
screener the operator uses in another app (Ortex short-interest + Unusual
Whales options-flow paid feeds, which the operator explicitly does not
have and does not want to pay for). Ortex/UW have no free equivalent
anywhere in this codebase -- not faked. This composite already covers the
"fuel" side for free (FTD + FINRA short-volume + gamma, real regulatory/
market data). The pasted bot's third tier-2 trigger -- RSI crossing above
50, a real, free momentum-confirmation signal computable from ordinary
daily bars -- is added here as a REQUIRED additional gate on top of the
existing composite/direction check, using the exact same
average-gain/average-loss RSI formula as the operator's pasted reference
implementation (not Wilder's smoothed variant, to match what they're used
to seeing). Requires the scanner to actually pass real daily `history` bars
(previously it did not -- see squeeze_fuel_scanner.py's fetch addition);
fails CLOSED (no BUY) when history is missing or too short to compute RSI,
consistent with this being an added selectivity filter, not a soft hint --
a silent fail-open here would quietly remove the exact protection it was
added for. Earnings-blackout and IV-rank exclusions from the pasted bot ARE
now implemented (see below) -- an earlier version of this docstring said
they weren't, which was wrong; see the "REAL SHORT INTEREST, EARNINGS
BLACKOUT, AND IV RANK" section below for the correction and design.

UNUSUAL OPTIONS FLOW CONFIRMATION (added 2026-07-30, correcting an earlier
error): this was first said to have "no free equivalent" -- wrong.
`options_anomaly_engine.py` is a real, already-live, auto-started engine
(confirmed by the operator posting its Discord alerts) that scans real
Tradier chains every 5 minutes and flags real whale prints (>=$100K
premium), volume/OI surges, IV spikes, and skew breaks via rolling
z-score baselines -- a genuine, free substitute for the pasted bot's
"unusual options flow" trigger. Wired here as a second required gate
(alongside RSI-cross) via `options_anomaly_engine.get_recent_anomaly()`.
Honest limitation, disclosed not hidden: that engine's own scan universe
is independently ranked/capped, so a symbol Squeeze Fuel evaluates may
simply never have been scanned by it recently -- this gate then correctly
reports unavailable/unconfirmed rather than guessing, same fail-closed
convention as RSI.

REAL SHORT INTEREST, EARNINGS BLACKOUT, AND IV RANK (added 2026-07-30,
correcting a second earlier error): the module docstring previously said
none of these had a free source -- also wrong, found on a closer second
search per the operator's "you should be able to build those api" pushback
(same lesson as the options-flow correction above: verify before asserting
a gap is unfillable). All three are now real, wired FAIL-OPEN checks --
deliberately different from RSI/flow's fail-CLOSED design, because these
three are risk-avoidance REFINEMENTS layered on an already multi-gated
signal (composite + direction + RSI + flow), not core confirmations --
requiring perfect coverage on all three would silently regress this
already-rare live-armed signal back toward never firing. Each fails open
(does not block) when its data source is unconfigured/unavailable, and
only blocks when REAL data is present and says the setup is weak:
  - SHORT INTEREST (finra_short_interest_data.py): real bi-monthly
    days-to-cover from FINRA's OAuth2-gated Query API -- NOT zero-config
    like the short-volume file above, requires the operator to register a
    free FINRA Individual Account + Public Credential
    (FINRA_API_CLIENT_ID/SECRET). Blocks only when real data shows
    days-to-cover below SHORT_INTEREST_MIN_DAYS_TO_COVER -- i.e. the
    short-volume proxy's implied fuel isn't backed by real covering
    pressure.
  - EARNINGS BLACKOUT (data_providers.AlphaVantageProvider.get_earnings_calendar()):
    real free Alpha Vantage EARNINGS_CALENDAR endpoint (one call covers
    every symbol, cached ~20h, doesn't burn the 25/day cap). Requires
    ALPHA_VANTAGE_API_KEY. Blocks when within EARNINGS_BLACKOUT_DAYS of a
    real known earnings date.
  - IV RANK (iv_rank_tracker.py): no free historical-options-chain source
    exists anywhere in this codebase (confirmed again here, same gap as
    Gamma Pin/Gamma Ramp/CVD Regime) -- so this self-mines a real rolling
    IV history going forward from gamma_flow_engine's already-computed
    iv_surface_avg, and only blocks once real accumulated history
    (IV_RANK_MIN_HISTORY_DAYS, default 20 real days) shows today's IV
    outside the IV_RANK_EXCLUDE_BELOW/ABOVE band. Reports 'insufficient
    history' honestly, never a fabricated rank, until then.

LIVE-ARMING (2026-07-30, operator directive): armed for real trading via
IAM_PRIMARY_SYSTEM despite zero backtest evidence -- an explicit, informed
decision after the no-evidence status was disclosed plainly (same pattern
as the S/R Zone+Pattern engine's arming). Per operator directive
("set it to 1 buy for now"), squeeze_fuel_scanner.py enforces a real,
self-healing cap on concurrently open Squeeze-Fuel-originated equity
positions (SQUEEZE_FUEL_MAX_OPEN_POSITIONS, default 1) before this engine
will fire a new BUY.
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

RSI_PERIOD = 14
RSI_CROSS_LEVEL = 50.0

FLOW_MAX_AGE_S = 1800  # a real options_anomaly_engine.py anomaly counts as "recent" for 30 min

# Fail-OPEN refinement gates (2026-07-30) -- see module docstring's "REAL
# SHORT INTEREST, EARNINGS BLACKOUT, AND IV RANK" section for the full
# reasoning on why these three are fail-open, unlike RSI/flow above.
SHORT_INTEREST_MIN_DAYS_TO_COVER = 1.0  # real DTC below this -> distrust the short-vol proxy's implied fuel
EARNINGS_BLACKOUT_DAYS = 1              # block within +/- this many days of a real known earnings date
IV_RANK_EXCLUDE_BELOW = 20.0            # too quiet a vol regime to justify a premium bet
IV_RANK_EXCLUDE_ABOVE = 90.0            # IV already rich -- poor risk/reward buying into a likely crush


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
    rsi_value: Optional[float] = None
    rsi_available: bool = False
    rsi_confirmed: bool = False
    flow_available: bool = False
    flow_confirmed: bool = False
    flow_anomaly_type: Optional[str] = None
    flow_severity: Optional[str] = None
    short_interest_available: bool = False
    short_interest_days_to_cover: Optional[float] = None
    short_interest_blocked: bool = False
    earnings_available: bool = False
    earnings_days_away: Optional[int] = None
    earnings_blocked: bool = False
    iv_rank_available: bool = False
    iv_rank_pct: Optional[float] = None
    iv_rank_blocked: bool = False

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
            "rsi_confirmation": {
                "value": round(self.rsi_value, 2) if self.rsi_value is not None else None,
                "available": self.rsi_available, "confirmed": self.rsi_confirmed,
                "period": RSI_PERIOD, "cross_level": RSI_CROSS_LEVEL,
                "note": "required gate, not a score component -- fails CLOSED (blocks BUY) when unavailable",
            },
            "flow_confirmation": {
                "available": self.flow_available, "confirmed": self.flow_confirmed,
                "anomaly_type": self.flow_anomaly_type, "severity": self.flow_severity,
                "max_age_s": FLOW_MAX_AGE_S,
                "note": "required gate from options_anomaly_engine.py's real whale-print/volume-surge/IV-spike "
                        "detection -- fails CLOSED (blocks BUY) when that engine hasn't recently scanned this symbol",
            },
            "short_interest_check": {
                "available": self.short_interest_available, "days_to_cover": self.short_interest_days_to_cover,
                "blocked": self.short_interest_blocked, "min_days_to_cover": SHORT_INTEREST_MIN_DAYS_TO_COVER,
                "note": "real FINRA short-interest refinement -- fails OPEN (never blocks) when "
                        "FINRA_API_CLIENT_ID/SECRET aren't configured; only blocks on real data showing weak DTC",
            },
            "earnings_blackout_check": {
                "available": self.earnings_available, "days_away": self.earnings_days_away,
                "blocked": self.earnings_blocked, "blackout_days": EARNINGS_BLACKOUT_DAYS,
                "note": "real Alpha Vantage earnings-calendar refinement -- fails OPEN when "
                        "ALPHA_VANTAGE_API_KEY isn't configured or the symbol isn't in the calendar",
            },
            "iv_rank_check": {
                "available": self.iv_rank_available, "iv_rank": self.iv_rank_pct,
                "blocked": self.iv_rank_blocked,
                "exclude_below": IV_RANK_EXCLUDE_BELOW, "exclude_above": IV_RANK_EXCLUDE_ABOVE,
                "note": "self-mined IV-rank refinement (no free historical-chain source exists) -- fails OPEN "
                        "until real accumulated history clears IV_RANK_MIN_HISTORY_DAYS, never a fabricated rank",
            },
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


def _bar_close(bar: dict) -> Optional[float]:
    v = bar.get("close")
    if v is None:
        v = bar.get("c")
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _rsi(closes: list, period: int = RSI_PERIOD) -> Optional[float]:
    """Simple average-gain/average-loss RSI (not Wilder's smoothed variant) --
    matches the exact formula in the operator's pasted reference bot, so the
    number means the same thing they're used to seeing elsewhere."""
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    if len(gains) < period:
        return None
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _rsi_confirmation(history: Optional[list]) -> tuple:
    """Returns (confirmed, rsi_now, available). Fresh cross only: RSI was
    below RSI_CROSS_LEVEL on the prior bar and at/above it on the latest bar
    -- same semantics as the pasted reference bot's rsi_crossed_above()."""
    if not history:
        return False, None, False
    closes = [c for c in (_bar_close(b) for b in history) if c is not None]
    if len(closes) < RSI_PERIOD + 2:
        return False, None, False
    rsi_prev = _rsi(closes[:-1])
    rsi_now = _rsi(closes)
    if rsi_prev is None or rsi_now is None:
        return False, None, False
    confirmed = rsi_prev < RSI_CROSS_LEVEL <= rsi_now
    return confirmed, rsi_now, True


def _flow_confirmation(symbol: str) -> tuple:
    """Returns (confirmed, anomaly_type, severity, available). Queries
    options_anomaly_engine.py's real, already-running whale-print/volume-
    surge/IV-spike/skew-break detector for a recent hit on this symbol.
    Direction-agnostic by design (matches the pasted reference bot's own
    "unusual flow" trigger, which also doesn't itself claim direction --
    bullish confirmation comes separately from the ignition score)."""
    try:
        from options_anomaly_engine import get_recent_anomaly
        hit = get_recent_anomaly(symbol, max_age_s=FLOW_MAX_AGE_S)
    except Exception:
        return False, None, None, False
    if not hit:
        return False, None, None, False
    return True, hit.get("anomaly_type"), hit.get("severity"), True


def _short_interest_check(symbol: str) -> tuple:
    """Returns (blocked, days_to_cover, available). Real FINRA short-
    interest data requires the operator to have set up free
    FINRA_API_CLIENT_ID/SECRET -- fails OPEN (never blocks) when
    unconfigured or the symbol isn't found. Only blocks when real data IS
    available and shows weak actual covering pressure (days-to-cover below
    SHORT_INTEREST_MIN_DAYS_TO_COVER) -- a genuine reason to distrust the
    short-volume proxy's implied fuel, not a fabricated exclusion."""
    try:
        from finra_short_interest_data import get_short_interest
        data = get_short_interest(symbol)
    except Exception:
        return False, None, False
    if not data or data.get("days_to_cover") is None:
        return False, None, False
    dtc = data["days_to_cover"]
    return dtc < SHORT_INTEREST_MIN_DAYS_TO_COVER, dtc, True


def _earnings_blackout(symbol: str) -> tuple:
    """Returns (blocked, days_away, available). Real Alpha Vantage
    EARNINGS_CALENDAR requires ALPHA_VANTAGE_API_KEY. Fails OPEN when
    unconfigured or the symbol isn't in the calendar -- a risk-avoidance
    refinement, not a core confirmation; requiring perfect calendar
    coverage would silently regress this already multi-gated signal back
    toward never firing."""
    try:
        from core.legacy import get_service
        dm = get_service("dm")
        if not dm or not getattr(dm, "alphav", None) or not dm.alphav.available:
            return False, None, False
        report_date_raw = dm.alphav.get_earnings_calendar().get(symbol.upper())
        if not report_date_raw:
            return False, None, False
        from datetime import date as _date
        report_date = _date.fromisoformat(report_date_raw)
        days_away = (report_date - _date.today()).days
    except Exception:
        return False, None, False
    return abs(days_away) <= EARNINGS_BLACKOUT_DAYS, days_away, True


def _iv_rank_check(symbol: str, raw_chain: Optional[dict], spot: float) -> tuple:
    """Returns (blocked, iv_rank_pct, available). Feeds today's real ATM IV
    (gamma_flow_engine's already-computed iv_surface_avg -- recomputed here
    via a second calculate_gex_profile() call since _gamma_amp_score()
    doesn't expose its profile object; a harmless re-parse of already-
    in-memory chain data, not a second network call) into
    iv_rank_tracker's self-mining store, then checks whether today's real
    rank falls in an exclusion band. Fails OPEN while real history is
    still accumulating."""
    if not raw_chain or spot <= 0:
        return False, None, False
    try:
        from gamma_flow_engine import calculate_gex_profile
        profile = calculate_gex_profile(raw_chain, spot, symbol)
    except Exception:
        return False, None, False
    iv = getattr(profile, "iv_surface_avg", None) if profile else None
    if not isinstance(iv, (int, float)) or iv <= 0:
        return False, None, False
    try:
        from iv_rank_tracker import record_iv, get_iv_rank
        record_iv(symbol, iv)
        rank = get_iv_rank(symbol)
    except Exception:
        return False, None, False
    if not rank.get("available"):
        return False, None, False
    pct = rank["iv_rank"]
    return (pct < IV_RANK_EXCLUDE_BELOW or pct > IV_RANK_EXCLUDE_ABOVE), pct, True


def compute_fuel(symbol: str, quote_data: Optional[dict] = None, history: Optional[list] = None,
                  raw_chain: Optional[dict] = None) -> FuelComponents:
    spot = float((quote_data or {}).get("price", 0) or 0)
    ignition, ign_avail, direction = _ignition_score(symbol, quote_data, history)
    ftd_fuel, ftd_avail, on_list = _ftd_fuel_score(symbol)
    sv_fuel, sv_avail = _short_vol_fuel_score(symbol)
    gamma_amp, gamma_avail, gamma_regime = _gamma_amp_score(symbol, raw_chain, spot)
    rsi_confirmed, rsi_value, rsi_avail = _rsi_confirmation(history)
    flow_confirmed, flow_type, flow_sev, flow_avail = _flow_confirmation(symbol)
    si_blocked, si_dtc, si_avail = _short_interest_check(symbol)
    earn_blocked, earn_days, earn_avail = _earnings_blackout(symbol)
    iv_blocked, iv_pct, iv_avail = _iv_rank_check(symbol, raw_chain, spot)
    comp = FuelComponents(
        ignition=ignition, ignition_available=ign_avail,
        ftd_fuel=ftd_fuel, ftd_available=ftd_avail, on_threshold_list=on_list,
        short_vol_fuel=sv_fuel, short_vol_available=sv_avail,
        gamma_amp=gamma_amp, gamma_available=gamma_avail, gamma_regime=gamma_regime,
        rsi_value=rsi_value, rsi_available=rsi_avail, rsi_confirmed=rsi_confirmed,
        flow_available=flow_avail, flow_confirmed=flow_confirmed,
        flow_anomaly_type=flow_type, flow_severity=flow_sev,
        short_interest_available=si_avail, short_interest_days_to_cover=si_dtc, short_interest_blocked=si_blocked,
        earnings_available=earn_avail, earnings_days_away=earn_days, earnings_blocked=earn_blocked,
        iv_rank_available=iv_avail, iv_rank_pct=iv_pct, iv_rank_blocked=iv_blocked,
    )
    comp._direction = direction  # stashed for analyze(); not part of the public dataclass fields
    return comp


def analyze(symbol: str, quote_data: Optional[dict] = None, history: Optional[list] = None,
            raw_chain: Optional[dict] = None) -> dict:
    """On-demand single-symbol wrapper -- same convention as every other
    engine's analyze() in this codebase (druck_engine.py, orb_engine.py)."""
    comp = compute_fuel(symbol, quote_data, history, raw_chain)
    direction = getattr(comp, "_direction", "NEUTRAL")
    action = "BUY" if (comp.composite >= ENTRY_THRESHOLD and direction == "BULLISH"
                        and comp.rsi_confirmed and comp.flow_confirmed
                        and not comp.short_interest_blocked
                        and not comp.earnings_blocked
                        and not comp.iv_rank_blocked) else None
    out = comp.as_dict()
    out["symbol"] = symbol.upper()
    out["direction"] = direction
    out["action"] = action
    out["entry_threshold"] = ENTRY_THRESHOLD
    out["disclosure"] = (
        "No backtest evidence exists for this composite -- see module docstring. "
        "Weights are a transparent starting point, not curve-fit or validated. "
        "RSI-cross-above-50 and real options-flow-anomaly confirmation are both "
        "required gates (fail closed without real data). Short-interest, "
        "earnings-blackout, and IV-rank are real refinement gates layered on "
        "top (fail open without real data -- see module docstring)."
    )
    return out
