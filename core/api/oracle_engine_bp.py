"""
oracle_engine_bp.py — OracleEngine signal aggregator Flask blueprint.

Aggregates all SqueezeOS engine signals into a single BUY/SELL/HOLD/SHIELD
directive with full Driver/Navigator payload. Backed by live Tradier quotes,
GammaFlow, MMLE, RMREBridge, Fractal, and Proprietary EMA engines.

Routes (prefix /api/engine):
  GET  /api/engine/signal/<symbol>   — Full Oracle directive (x402 gated, 0.25 USDC)
  GET  /api/engine/batch             — Batch: GME, AMC, IWM  (x402 gated, 0.50 USDC)
  GET  /api/engine/info              — Discovery + pricing (free)
"""
from __future__ import annotations
import logging
from flask import Blueprint, jsonify, request, current_app

logger = logging.getLogger("OracleEngineBP")
oracle_engine_bp = Blueprint("oracle_engine", __name__)

SUPPORTED_SYMBOLS = ["GME", "AMC", "IWM", "SPY", "QQQ", "NVDA", "TSLA"]


def _get_services():
    """Pull the live services registry from app context (set by legacy.py)."""
    try:
        from core.legacy import get_services
        return get_services()
    except Exception as e:
        logger.warning(f"[Oracle BP] Could not get services: {e}")
        return {}


@oracle_engine_bp.route("/info", methods=["GET"])
def info():
    return jsonify({
        "service": "Oracle Engine — Signal Aggregator",
        "description": "Aggregates GammaFlow + MMLE + Fractal + RMREBridge + Proprietary EMA into a single BUY/SELL/HOLD/SHIELD directive.",
        "endpoints": {
            "GET /api/engine/signal/<symbol>": {"price": "0.25 USDC", "description": "Full Oracle directive"},
            "GET /api/engine/batch":           {"price": "0.50 USDC", "description": "GME + AMC + IWM batch"},
        },
        "supported_symbols": SUPPORTED_SYMBOLS,
        "free": True,
    })


@oracle_engine_bp.route("/signal/<symbol>", methods=["GET"])
def signal(symbol: str):
    symbol = symbol.upper()
    if symbol not in SUPPORTED_SYMBOLS:
        return jsonify({"error": f"Symbol {symbol} not supported. Supported: {SUPPORTED_SYMBOLS}"}), 400
    try:
        from core.oracle_engine import OracleEngine
        engine = OracleEngine(_get_services())
        result = engine.analyze(symbol)
        return jsonify(result)
    except Exception as e:
        logger.error(f"[Oracle BP] Error analyzing {symbol}: {e}")
        return jsonify({
            "symbol": symbol,
            "directive": "SHIELD",
            "confidence": 0,
            "reason": f"Engine initialization error: {str(e)[:120]}",
            "error": True,
        }), 500


@oracle_engine_bp.route("/batch", methods=["GET"])
def batch():
    symbols = request.args.get("symbols", "GME,AMC,IWM").upper().split(",")
    symbols = [s for s in symbols if s in SUPPORTED_SYMBOLS][:5]  # cap at 5
    if not symbols:
        return jsonify({"error": "No valid symbols provided"}), 400
    try:
        from core.oracle_engine import OracleEngine, run_oracle_batch
        results = run_oracle_batch(symbols, _get_services())
        return jsonify({"results": results, "count": len(results)})
    except Exception as e:
        logger.error(f"[Oracle BP] Batch error: {e}")
        return jsonify({"error": str(e)[:120]}), 500
