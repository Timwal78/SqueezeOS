"""
IAM — Inevitable Action Model API
====================================
Markets move not by belief, but by necessity.
IAM trades the necessity.

Endpoints:
  GET  /api/iam/<symbol>         — Full IAM resolution (PAID 0.05 RLUSD): obligation committee
                                   + Truth Layer + mandatory action. Internal AMM parameters redacted.
  GET  /api/iam/truth/<symbol>   — Truth Layer only: neutral obligation state, no action (FREE)
  POST /api/iam/stress-test      — Multi-symbol system stress survey (FREE, up to 5 symbols)

Proprietary boundary:
  _redact_obligation() strips raw_stress and detail from every analyst block
  before serialization. The AMM invariant curve and internal thresholds are
  never exposed to callers — only the output signals (pressure, direction, label).
"""

import sys
import os
import time
import logging
from flask import Blueprint, jsonify, request
from core.legacy import get_service, clean_data
import core.signal_history as signal_history

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from x402_flask import x402_guard

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


def _redact_obligation(block: dict) -> dict:
    """Strip AMM curve inputs and calculation detail from analyst output at API boundary."""
    return {k: v for k, v in block.items() if k not in ("raw_stress", "detail")}


@iam_bp.route("/<symbol>", methods=["GET"])
@x402_guard(
    price_usdc="0.05",
    description=(
        "IAM Full Resolution — mandatory action the market is forced to take. "
        "Obligation committee (5 independent analysts) + Truth Layer + Action Resolution Oracle. "
        "Returns: action BUY/SELL/HOLD, rationale, vehicle, invalidation, review trigger, "
        "per-analyst obligation pressure (0-100%), and total system stress. "
        "Internal AMM parameters redacted."
    ),
)
def iam_resolve(symbol):
    """
    Full IAM resolution — PAID endpoint (0.05 RLUSD).

    Returns:
      - truth_layer: neutral obligation pressure vector (no direction)
      - obligation_committee: per-analyst pressure, direction, label (internals redacted)
      - resolution: mandatory action + rationale + vehicle + invalidation + review trigger
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

    # Redact proprietary internals at API boundary — only signals pass through
    redacted_committee = {
        name: _redact_obligation(block)
        for name, block in result.get("obligation_committee", {}).items()
    }

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
        "iam": {
            **{k: v for k, v in result.items() if k != "obligation_committee"},
            "obligation_committee": redacted_committee,
        },
    })

    _IAM_CACHE[f"resolve_{sym}"] = {"ts": now, "data": response}
    return jsonify(response)


@iam_bp.route("/truth/<symbol>", methods=["GET"])
def iam_truth(symbol):
    """
    Truth Layer only — FREE endpoint.

    Neutral obligation state: no action resolution, no internal parameters.

    Returns the canonical Truth Layer output from the IAM specification:
      NEXT REQUIRED ACTION:
      • Volatility Release: 0-100%
      • Liquidity Refill:   0-100%
      • Dealer Hedge:       0-100%
      • Mean Reversion Pull: 0-100%
      • Structural Pressure: 0-100%
      • Directional Bias:   NONE  ← always NONE at this stage
      • Time Window:        DORMANT / DEVELOPING / NEAR_TERM / IMMEDIATE
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

    response = clean_data({
        "status":    "success",
        "cached":    False,
        "iam_truth": result,
        "upgrade": {
            "full_resolution": f"/api/iam/{sym}",
            "price_rlusd":     "0.05",
            "includes":        [
                "mandatory action (BUY/SELL/HOLD)",
                "obligation committee breakdown",
                "rationale",
                "vehicle",
                "invalidation condition",
                "review trigger",
                "resolution confidence",
            ],
            "gateway": "https://four02proof.onrender.com",
        },
    })
    _IAM_CACHE[f"truth_{sym}"] = {"ts": now, "data": response}
    return jsonify(response)


@iam_bp.route("/stress-test", methods=["POST"])
def iam_stress_test():
    """
    Multi-symbol system stress survey — FREE endpoint.

    POST body: {"symbols": ["IWM", "SPY", "GME"]}  (max 5)
    Returns obligation stress ranked by total system stress descending.
    """
    body    = request.get_json(silent=True) or {}
    symbols = body.get("symbols", [])

    if not symbols or not isinstance(symbols, list):
        return jsonify({"status": "error", "message": "symbols array required"}), 400

    symbols = [s.upper().strip() for s in symbols[:5]]

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
        "upgrade": {
            "full_resolution": "/api/iam/<symbol>",
            "price_rlusd":     "0.05",
            "gateway":         "https://four02proof.onrender.com",
        },
    }))
