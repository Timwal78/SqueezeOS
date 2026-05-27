"""
SqueezeOS Convergence Engine — The Logic Gate
=============================================
Runs all 5 engines simultaneously against live data and evaluates
the Beastmode trigger: a multi-engine convergence lock.

Beastmode fires ONLY when all 5 conditions are true:
  E1: Price elastically suppressed below 578/963 (Engine 1 SUPPRESSED)
  E5: 42 EMA curling toward 369 macro frequency (Engine 5 GANN_IGNITION)
  E3: Volume geometrically exploding through 123/321 baselines (Engine 3)
  E2: Settlement clock in 72-hour Kill Zone (T+13 or C+35) (Engine 2)
  E4: Live price ≥70% correlated with Feb-22 mirror projection (Engine 4)

Phase 3 — Options Sniper:
  Microsecond convergence is achieved → Tradier API scan
  Filter: 0–14 DTE | Delta: 0.35–0.45 | Type: Call (default)
"""

import os
import time
import logging
import requests
from datetime import date, timedelta
from typing import List, Optional

from core.proprietary_ema_engine import Engine1_TeslaStretch, Engine3_LucasPhi
from core.engine2_settlement import get_clock, stamp_ignition
from core.engine4_temporal_mirror import Engine4_TemporalMirror
from core.engine5_gann_macro import Engine5_GannMacro
from core.proprietary_ema_engine import _ema, _tail

logger = logging.getLogger("SML.Convergence")

# Monitored universe
BEASTMODE_UNIVERSE = ["GME", "AMC", "MSTR", "PLTR", "HOOD", "IWM", "SPY", "QQQ", "NVDA", "TSLA"]


# ── Tradier Options Sniper ────────────────────────────────────────────────────

def _tradier_headers():
    key = os.environ.get("TRADIER_API_KEY", "").strip()
    if not key:
        return None
    return {"Authorization": f"Bearer {key}", "Accept": "application/json"}


def _tradier_base():
    env = os.environ.get("TRADIER_ENV", "sandbox").lower()
    return "https://api.tradier.com/v1" if env == "production" else "https://sandbox.tradier.com/v1"


def scan_options(symbol: str, trade_type: str = "call") -> dict:
    """
    Snipe the 0-14 DTE option with delta closest to 0.40 center.
    Returns the exact contract: strike, expiry, delta, premium.
    """
    headers = _tradier_headers()
    if not headers:
        return {"error": "TRADIER_API_KEY not configured"}

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
            return {"error": f"Expirations unavailable ({exp_resp.status_code})"}

        raw_exps = exp_resp.json().get("expirations", {}).get("date", []) or []
        if isinstance(raw_exps, str):
            raw_exps = [raw_exps]

        valid_exps = [e for e in raw_exps
                      if today.isoformat() <= e <= max_exp.isoformat()]

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

                options = chain_resp.json().get("options", {}).get("option", []) or []
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
        return {"error": str(e)}


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
        e1 = Engine1_TeslaStretch().analyze(closes)
        e3 = Engine3_LucasPhi().analyze(volumes) if volumes and len(volumes) >= 11 \
             else {"engine": 3, "signal": "NO_VOLUME_DATA", "score_contrib": 0}
        e4 = Engine4_TemporalMirror().analyze(closes, bars_with_dates)
        e5 = Engine5_GannMacro().analyze(closes)

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
            e2.get("score_contrib", 0)
        )
        composite = max(0, min(100, 50 + raw_score))

        # ── Signal label ─────────────────────────────────────────
        if beastmode:
            signal = "BEASTMODE"
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
        if run_sniper and (beastmode or active_count >= 4):
            trade_type = "call" if not e1.get("bear_stack") else "put"
            sniper_result = scan_options(symbol, trade_type)

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
            },
            "engines": {
                "e1": e1,
                "e2": e2,
                "e3": e3,
                "e4": e4,
                "e5": e5,
            },
        }

        if sniper_result:
            result["options_sniper"] = sniper_result

        return result


# ── Multi-symbol Beastmode scan ───────────────────────────────────────────────

def scan_beastmode_universe(services: dict) -> list:
    """
    Scan all symbols in BEASTMODE_UNIVERSE.
    Returns only symbols with HIGH_CONVERGENCE or BEASTMODE signals.
    """
    dm = services.get("dm")
    if not dm:
        return []

    engine = ConvergenceEngine()
    hits   = []

    for symbol in BEASTMODE_UNIVERSE:
        try:
            bars    = dm.get_historical_bars(symbol, timeframe="1Day", limit=400) or []
            closes  = [float(b.get("c") or b.get("close", 0)) for b in bars if b.get("c") or b.get("close")]
            volumes = [float(b.get("v") or b.get("volume", 0)) for b in bars if b.get("v") or b.get("volume")]

            if len(closes) < 11:
                continue

            result = engine.analyze(symbol, closes, volumes, bars_with_dates=bars, run_sniper=True)
            if result.get("signal") in ("BEASTMODE", "HIGH_CONVERGENCE", "LIE_DETECTOR_ACTIVE"):
                hits.append(result)
        except Exception as e:
            logger.warning(f"[Convergence] {symbol} scan error: {e}")

    return sorted(hits, key=lambda x: x.get("composite_score", 0), reverse=True)
