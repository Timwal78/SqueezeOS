"""
SqueezeOS Convergence Engine — The Logic Gate
=============================================
Runs the full proprietary engine cascade against live data and evaluates
the Beastmode trigger: a multi-engine convergence lock across five
independent market dimensions.

Beastmode fires only when all five engines align:
  E1: Price elasticity / macro stretch detector
  E5: Macro frequency / momentum ignition filter
  E3: Dark-pool volume kinetics detector
  E2: Settlement-clock window (kill zone)
  E4: Temporal correlation against historical pivot

Phase 3 — Options Sniper:
  When convergence is achieved → Tradier API scan for short-DTE contracts
  in a high-leverage delta band.

Internal parameters (periods, thresholds, pivot dates, lookback windows,
DTE/delta ranges) are proprietary.
"""

import os
import time
import logging
import requests
from datetime import date, timedelta
from typing import List, Optional

from core.proprietary_ema_engine import _Engine1, _Engine3, _ema, _tail, redact_engine_block as _redact
from core.engine2_settlement import get_clock, stamp_ignition
from core.engine4_temporal_mirror import Engine4_TemporalMirror
from core.engine5_gann_macro import Engine5_GannMacro
from core.engine6_base4_matrix import Engine6_Base4Matrix, redact_engine6_block
import core.harmonic_matrix_engine as _harmonic
import core.grid369_engine as _grid369
from core.engine7_parabolic import Engine7_Parabolic, redact_engine7_block
from core.state import state

logger = logging.getLogger("SML.Convergence")

from core.state import state
from core.api.market_scanner import MANDATORY_TICKERS
from core.legacy import get_service


# ── Tradier Options Sniper ────────────────────────────────────────────────────

def _tradier_headers():
    key = os.environ.get("TRADIER_API_KEY", "").strip()
    if not key:
        return None
    return {"Authorization": f"Bearer {key}", "Accept": "application/json"}


def _tradier_base():
    env = os.environ.get("TRADIER_ENV", "sandbox").lower()
    return "https://api.tradier.com/v1" if env == "production" else "https://sandbox.tradier.com/v1"


def scan_options(symbol: str, trade_type: str = "call", current_price: float = 0.0) -> dict:
    """
    Snipe the 0-14 DTE option with delta closest to 0.40 center.
    Returns the exact contract: strike, expiry, delta, premium.
    Never returns fake or synthetic data — returns error dict if API unavailable.
    """
    headers = _tradier_headers()
    if not headers:
        return {"error": "TRADIER_API_KEY not configured — live options data unavailable"}
    base    = _tradier_base()
    today   = date.today()
    max_exp = today + timedelta(days=14)

    try:
        # Step 1: Get available expirations
        exp_resp = requests.get(
            f"{base}/markets/options/expirations",
            params={"symbol": symbol, "includeAllRoots": "true"},
            headers=headers, timeout=10,
        )
        if exp_resp.status_code != 200:
            return {"error": f"Tradier expirations returned HTTP {exp_resp.status_code}"}

        _exp_json = exp_resp.json() or {}
        _expirations = _exp_json.get("expirations") or {}
        raw_exps = _expirations.get("date", []) or []
        if isinstance(raw_exps, str):
            raw_exps = [raw_exps]

        valid_exps = [e for e in raw_exps if e >= today.isoformat()]
        
        if symbol.upper() == "IWM" and valid_exps:
            # Mandate 0DTE for IWM (the absolute nearest available expiration)
            valid_exps = [valid_exps[0]]
        else:
            # Default 0-14 DTE for all other symbols
            valid_exps = [e for e in valid_exps if e <= max_exp.isoformat()]

        if not valid_exps:
            return {"error": "No expirations in 0-14 DTE window"}

        # Step 2: Scan each expiration for the optimal delta
        best: Optional[dict] = None
        best_delta_dist = float("inf")

        for exp in valid_exps:
            try:
                chain_resp = requests.get(
                    f"{base}/markets/options/chains",
                    params={"symbol": symbol, "expiration": exp, "greeks": "true"},
                    headers=headers, timeout=10,
                )
                if chain_resp.status_code != 200:
                    continue

                _chain_json = chain_resp.json() or {}
                _opts_wrap = _chain_json.get("options") or {}
                options = _opts_wrap.get("option", []) or []
                if isinstance(options, dict):
                    options = [options]

                for opt in options:
                    if (opt.get("option_type") or "").lower() != trade_type.lower():
                        continue
                    greeks = opt.get("greeks") or {}
                    delta_raw = greeks.get("delta")
                    if delta_raw is None:
                        continue
                    delta = abs(float(delta_raw))
                    if 0.35 <= delta <= 0.45:
                        dist = abs(delta - 0.40)
                        if dist < best_delta_dist:
                            best_delta_dist = dist
                            best = opt
            except Exception as e:
                logger.warning(f"[Sniper] Chain error {exp}: {e}")
                continue

        if not best:
            return {"error": "No contract in 0.35-0.45 delta range across 0-14 DTE"}

        greeks = best.get("greeks") or {}
        return {
            "symbol":        symbol,
            "type":          trade_type.upper(),
            "strike":        best.get("strike"),
            "expiration":    best.get("expiration_date"),
            "delta":         round(float(greeks.get("delta", 0) or 0), 4),
            "gamma":         round(float(greeks.get("gamma", 0) or 0), 6),
            "theta":         round(float(greeks.get("theta", 0) or 0), 4),
            "iv":            round(float(greeks.get("mid_iv", 0) or 0), 4),
            "premium":       best.get("last") or best.get("ask"),
            "bid":           best.get("bid"),
            "ask":           best.get("ask"),
            "volume":        best.get("volume"),
            "open_interest": best.get("open_interest"),
            "description":   best.get("description"),
        }

    except Exception as e:
        logger.error(f"[Sniper] Fatal error for {symbol}: {e}")
        return {"error": f"Options scan failed: {e}"}


# ── Convergence Engine ────────────────────────────────────────────────────────

class ConvergenceEngine:
    """
    The Logic Gate. Runs all 5 engines and evaluates Beastmode convergence.
    Auto-stamps Engine 2 ignition when E3 + E1 suppression are detected.
    """

    def analyze(self,
                symbol: str,
                closes: List[float],
                volumes: Optional[List[float]] = None,
                bars_with_dates: Optional[list] = None,
                run_sniper: bool = True) -> dict:

        ts = time.time()
        symbol = symbol.upper()

        if len(closes) < 11:
            return {"symbol": symbol, "signal": "INSUFFICIENT_DATA", "beastmode": False}

        # ── Run all 5 engines ─────────────────────────────────────
        e1 = _Engine1().analyze(closes)
        e3 = _Engine3().analyze(volumes) if volumes and len(volumes) >= 11 \
             else {"engine": 3, "signal": "NO_VOLUME_DATA", "score_contrib": 0}
        e4 = Engine4_TemporalMirror().analyze(closes, bars_with_dates)
        e5 = Engine5_GannMacro().analyze(closes)
        e6 = Engine6_Base4Matrix().analyze(closes)
        
        # ── Temporal Validation Layer (TTL Buffer) ──
        e3_sig = e3.get("signal")
        if e3_sig in ("DARK_POOL_CEILING_BREACH", "DISTRIBUTION"):
            state.update_engine3_buffer(symbol, e3_sig)

        # Bifurcated APEX SINGULARITY trigger with 250ms Temporal Decay Window
        e6_bull_locked = e6.get("signal") in ("FRACTAL_LOCK_BULL", "GOD_MODE_BULL")
        e3_breach_active = state.check_engine3_buffer(symbol, "DARK_POOL_CEILING_BREACH", ttl=0.250)
        
        e6_bear_locked = e6.get("signal") in ("FRACTAL_LOCK_BEAR", "GOD_MODE_BEAR")
        e3_dist_active = state.check_engine3_buffer(symbol, "DISTRIBUTION", ttl=0.250)
        
        is_singularity = (e6_bull_locked and e3_breach_active) or (e6_bear_locked and e3_dist_active)
        e7 = Engine7_Parabolic().analyze(closes, is_singularity)

        # Auto-stamp E2 if E3 volume fires + E1 suppressed
        e3_firing   = e3.get("signal") in ("DARK_POOL_CEILING_BREACH", "DARK_POOL_ACCUMULATION", "PHI_IGNITION")
        e1_suppress = e1.get("suppressed", False) or e1.get("signal") in ("SUPPRESSED", "COMPRESSION", "BEAR_STRETCH")

        if e3_firing and e1_suppress:
            stamp_ignition(symbol)     # idempotent

        e2 = get_clock(symbol)

        # ── Logic Gate — Beastmode conditions ────────────────────
        gate = {
            "e1_price_suppressed":   e1_suppress or e1.get("bear_stack", False),
            "e5_gann_curl":          e5.get("gann_confirmation", False) or e5.get("signal") in ("GANN_IGNITION", "GANN_CURL_CONFIRMED"),
            "e3_volume_firing":      e3_firing,
            "e2_kill_zone":          e2.get("in_kill_zone", False),
            "e4_temporal_aligned":   e4.get("aligned", False),
            "e6_fractal_lock":       e6.get("signal") in ("FRACTAL_LOCK_BULL", "FRACTAL_LOCK_BEAR", "GOD_MODE_BULL", "GOD_MODE_BEAR"),
        }

        # Lie detector (E1 suppressed + E3 exploding = dark-pool accumulation)
        lie_detector = gate["e1_price_suppressed"] and gate["e3_volume_firing"]

        active_count = sum(1 for v in gate.values() if v)
        beastmode    = active_count == 5

        # ── Composite score ───────────────────────────────────────
        raw_score = (
            e1.get("score_contrib", 0) +
            e3.get("score_contrib", 0) +
            e4.get("score_contrib", 0) +
            e5.get("score_contrib", 0) +
            e2.get("score_contrib", 0) +
            e6.get("score_contrib", 0) +
            e7.get("score_contrib", 0)
        )
        composite = max(0, min(100, 50 + raw_score))

        # ── Signal label ─────────────────────────────────────────
        is_god_mode = e6.get("signal") in ("GOD_MODE_BULL", "GOD_MODE_BEAR")
        is_apex = e7.get("signal") in ("QUADRATIC_LAUNCH_BULL", "QUADRATIC_LAUNCH_BEAR")
        
        if is_apex:
            signal = "APEX_SINGULARITY"
            beastmode = True
            
            # Spin up the high-frequency Engine 7 tracker in the background
            Engine7_Parabolic.launch_tracking_thread(symbol)
            
        elif is_god_mode:
            signal = "GOD_MODE"
            beastmode = True
        elif beastmode:
            signal = "BEASTMODE"
        elif e6.get("signal") in ("FRACTAL_LOCK_BULL", "FRACTAL_LOCK_BEAR"):
            signal = "FRACTAL_LOCK"
        elif active_count >= 4:
            signal = "HIGH_CONVERGENCE"
        elif active_count >= 3:
            signal = "CONVERGENCE"
        elif lie_detector:
            signal = "LIE_DETECTOR_ACTIVE"
        elif active_count >= 2:
            signal = "PARTIAL_ALIGNMENT"
        else:
            signal = "NEUTRAL"

        # ── Options Sniper (Phase 3) ──────────────────────────────
        sniper_result = None
        if run_sniper:
            trade_type = "call" if not e1.get("bear_stack") else "put"
            sniper_result = scan_options(symbol, trade_type, current_price=closes[-1])

        # ── SML Harmonic Matrix — Proprietary Ranked Engine (Grid 1) ────────────
        try:
            sml_data = _harmonic.analyze(closes)
        except Exception as e:
            import traceback
            logger.error(f"[SML] {symbol} harmonic matrix error: {e}\n{traceback.format_exc()}")
            sml_data = {"error": str(e), "matrix": {}}

        # ── Grid 369 — Proprietary 3×3 Anchor Matrix (Grid 2) ────────────────
        try:
            god_stacked_g1 = sml_data.get("god_stacked", 0)
            grid369_data   = _grid369.analyze(closes, grid1_god_stacked=god_stacked_g1)
        except Exception as e:
            import traceback
            logger.error(f"[Grid369] {symbol} error: {e}\n{traceback.format_exc()}")
            grid369_data = {"error": str(e), "grid": {}}

        # Elevate signal to DUAL_GRID_LOCK when both grids confirm
        if grid369_data.get("dual_grid_lock"):
            signal    = "DUAL_GRID_LOCK"
            beastmode = True
            logger.info(f"[DUAL_GRID_LOCK] {symbol} — Grid 1 GOD_MODE + Grid 2 Base-9 all stacked")

        result = {
            "symbol":            symbol,
            "timestamp":         ts,
            "signal":            signal,
            "beastmode":         beastmode,
            "active_conditions": active_count,
            "total_conditions":  5,
            "composite_score":   composite,
            "lie_detector":      lie_detector,
            "gate": {
                "e1_price_suppressed": {"active": gate["e1_price_suppressed"], "signal": e1.get("signal")},
                "e5_gann_curl":        {"active": gate["e5_gann_curl"],        "signal": e5.get("signal")},
                "e3_volume_firing":    {"active": gate["e3_volume_firing"],    "signal": e3.get("signal")},
                "e2_kill_zone":        {"active": gate["e2_kill_zone"],        "status": e2.get("status")},
                "e4_temporal_aligned": {"active": gate["e4_temporal_aligned"], "signal": e4.get("signal")},
                "e6_fractal_lock":     {"active": gate["e6_fractal_lock"],     "signal": e6.get("signal")},
                "e7_parabolic_flight": {"active": is_apex,                     "signal": e7.get("signal")},
            },
            "engines": {
                "e1": _redact(e1),
                "e2": _redact(e2),
                "e3": _redact(e3),
                "e4": _redact(e4),
                "e5": _redact(e5),
                "e6": redact_engine6_block(e6),
                "e7": redact_engine7_block(e7),
            },
            "sml_matrix": sml_data,
            "grid369":    grid369_data,
        }

        if sniper_result:
            result["options_sniper"] = sniper_result

        return result


# ── Multi-symbol Beastmode scan ───────────────────────────────────────────────

def scan_beastmode_universe(services: dict, tf: str = "1D", on_progress=None) -> list:
    """
    Scan all symbols in BEASTMODE_UNIVERSE.
    Returns only symbols with HIGH_CONVERGENCE or BEASTMODE signals.

    on_progress(sorted_hits_so_far, done_count, total_count) is called after
    every symbol so callers (e.g. the background cache refresher) can release
    results incrementally instead of waiting for the full scan to finish.
    """
    dm = services.get("dm")
    if not dm:
        return []

    engine = ConvergenceEngine()
    hits   = []

    # Dynamically build universe from the live market state
    with state.lock:
        quotes = state.quotes
    
    # Sort dynamic quotes by volume ratio
    active_syms = sorted(quotes.keys(), key=lambda s: quotes[s].get("volRatio", 0), reverse=True)
    
    # Take the top 150 most active tickers, plus our mandatory focus (memory-bounded)
    universe = list(set(MANDATORY_TICKERS + active_syms[:150]))  # trimmed from 500 to fit 512MB instance
    
    total = len(universe)
    for idx, symbol in enumerate(universe, 1):
        try:
            if hasattr(dm, "get_bars"):
                bars = dm.get_bars(symbol, timeframe=tf, limit=250) or []
                if not bars and tf == "1D":
                    bars = dm.get_bars(symbol, timeframe="1Min", limit=250) or []
            else:
                bars = dm.get_historical_bars(symbol, timeframe=tf, limit=250) or []
            closes  = [float(b.get("c") or b.get("close", 0)) for b in bars if b.get("c") or b.get("close")]
            volumes = [float(b.get("v") or b.get("volume", 0)) for b in bars if b.get("v") or b.get("volume")]

            if len(closes) < 11:
                continue

            result = engine.analyze(symbol, closes, volumes, bars_with_dates=bars, run_sniper=True)
            highest_stacks = result.get("sml_matrix", {}).get("highest_stacked_set", 0)

            if highest_stacks >= 4 or symbol in MANDATORY_TICKERS:
                # Store the stack count on the top level for easy frontend access
                result["highest_stacked_set"] = highest_stacks
                hits.append(result)
        except Exception as e:
            logger.warning(f"[Convergence] {symbol} scan error: {e}")

        if on_progress:
            try:
                sorted_so_far = sorted(hits, key=lambda x: (x.get("highest_stacked_set", 0), x.get("composite_score", 0)), reverse=True)
                on_progress(sorted_so_far, idx, total)
            except Exception as _pe:
                logger.warning(f"[Convergence] on_progress callback error: {_pe}")

    # Sort strictly by highest stacked sets (9 down to 4), then by composite score
    return sorted(hits, key=lambda x: (x.get("highest_stacked_set", 0), x.get("composite_score", 0)), reverse=True)
