"""
IAM — Inevitable Action Model API
====================================
Markets move not by belief, but by necessity.
IAM trades the necessity.

Endpoints:
  GET  /api/iam/<symbol>         — Full IAM resolution: obligation committee + Truth Layer + mandatory action
  GET  /api/iam/truth/<symbol>   — Truth Layer only: neutral obligation state, no action (free)
  POST /api/iam/stress-test      — Multi-symbol system stress survey (free, up to 5 symbols)
"""

import time
import logging
from flask import Blueprint, jsonify, request
from core.legacy import get_service, clean_data
import core.signal_history as signal_history

logger = logging.getLogger("IAM-BP")
iam_bp = Blueprint("iam", __name__)

_IAM_CACHE: dict = {}
_IAM_TTL = 45


def _get_iam_engine():
    from iam_engine import IAMEngine
    services = {
        "dm":            get_service("dm"),
        "whale_stalker": get_service("whale_stalker"),
    }
    return IAMEngine(services)


@iam_bp.route("/<symbol>", methods=["GET"])
def iam_resolve(symbol):
    """
    Full IAM resolution for a symbol.

    Returns:
      - truth_layer: neutral obligation pressure vector (no direction)
      - obligation_committee: per-analyst breakdown (5 independent specialists)
      - resolution: mandatory action, rationale, vehicle, invalidation, review trigger
    """
    sym = symbol.upper().strip()
    now = time.time()

    cached = _IAM_CACHE.get(f"resolve_{sym}")
    if cached and (now - cached["ts"]) < _IAM_TTL:
        return jsonify({"status": "success", "cached": True, **cached["data"]})

    try:
        engine = _get_iam_engine()
        result = engine.resolve(sym)
    except Exception as e:
        logger.error(f"[IAM-BP] Resolve error for {sym}: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

    if "error" in result:
        return jsonify({"status": "error", **result}), 503

    # Record to signal history
    try:
        signal_history.record(sym, "IAM_RESOLUTION", {
            "action":     result["resolution"]["action"],
            "stress":     result["truth_layer"]["total_system_stress"],
            "window":     result["truth_layer"]["time_window"],
            "confidence": result["resolution"]["resolution_confidence"],
        })
    except Exception:
        pass

    response = clean_data({
        "status":  "success",
        "cached":  False,
        "iam":     result,
    })

    _IAM_CACHE[f"resolve_{sym}"] = {"ts": now, "data": response}
    return jsonify(response)


@iam_bp.route("/truth/<symbol>", methods=["GET"])
def iam_truth(symbol):
    """
    Truth Layer only — neutral obligation state, no action resolution.

    Useful for dashboards that want to display raw obligation pressures
    without committing to a directional interpretation.

    Returns the canonical Truth Layer output from the IAM pitch deck:
      NEXT REQUIRED ACTION:
      • Volatility Release: 87%
      • Liquidity Refill: 74%
      • Directional Bias: NONE   ← always NONE at this stage
      • Time Window: IMMEDIATE
    """
    sym = symbol.upper().strip()
    now = time.time()

    cached = _IAM_CACHE.get(f"truth_{sym}")
    if cached and (now - cached["ts"]) < _IAM_TTL:
        return jsonify({"status": "success", "cached": True, **cached["data"]})

    try:
        engine = _get_iam_engine()
        result = engine.truth_only(sym)
    except Exception as e:
        logger.error(f"[IAM-BP] Truth error for {sym}: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

    response = clean_data({"status": "success", "cached": False, "iam_truth": result})
    _IAM_CACHE[f"truth_{sym}"] = {"ts": now, "data": response}
    return jsonify(response)


@iam_bp.route("/stress-test", methods=["POST"])
def iam_stress_test():
    """
    Multi-symbol system stress survey.

    POST body: {"symbols": ["IWM", "SPY", "GME"]}  (max 5)
    Returns obligation stress ranked by total system stress descending.
    """
    body    = request.get_json(silent=True) or {}
    symbols = body.get("symbols", [])

    if not symbols or not isinstance(symbols, list):
        return jsonify({"status": "error", "message": "symbols array required"}), 400

    symbols = [s.upper().strip() for s in symbols[:5]]  # hard cap at 5

    engine  = _get_iam_engine()
    results = []

    for sym in symbols:
        try:
            r = engine.truth_only(sym)
            results.append({
                "symbol":               sym,
                "total_system_stress":  r["next_required_action"]["total_system_stress"],
                "time_window":          r["next_required_action"]["time_window"],
                "volatility_release":   r["next_required_action"]["volatility_release"],
                "liquidity_refill":     r["next_required_action"]["liquidity_refill"],
                "dealer_hedge":         r["next_required_action"]["dealer_hedge"],
                "mean_reversion_pull":  r["next_required_action"]["mean_reversion_pull"],
                "structural_pressure":  r["next_required_action"]["structural_pressure"],
                "data_quality":         r["next_required_action"]["data_quality"],
            })
        except Exception as e:
            results.append({"symbol": sym, "error": str(e)})

    results.sort(key=lambda x: x.get("total_system_stress", 0), reverse=True)

    return jsonify(clean_data({
        "status":    "success",
        "symbols":   results,
        "ranked_by": "total_system_stress",
        "timestamp": time.time(),
    }))
