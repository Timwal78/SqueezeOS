"""
SML Sovereign Squeeze Finder Blueprint — /api/sovereign-squeeze
===========================================================
GET /api/sovereign-squeeze/status    Free — scanner state, params, last signal
GET /api/sovereign-squeeze/<symbol>  Free — on-demand analysis of latest daily bars
                                      (503 when insufficient daily data)
"""
import logging

from flask import Blueprint, jsonify

from core.legacy import get_service, clean_data

logger = logging.getLogger("SOVEREIGN-SQZ-BP")

sovereign_squeeze_bp = Blueprint("sovereign_squeeze", __name__)


@sovereign_squeeze_bp.route("/status", methods=["GET"])
def sovereign_squeeze_status():
    try:
        import sovereign_squeeze_scanner
        return jsonify(clean_data({"status": "success", "scanner": sovereign_squeeze_scanner.status()}))
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@sovereign_squeeze_bp.route("/<symbol>", methods=["GET"])
def sovereign_squeeze_symbol(symbol: str):
    dm = get_service("dm")
    if not dm:
        return jsonify({"status": "error", "message": "DataManager not initialized"}), 503
    try:
        import os
        from sovereign_squeeze_engine import analyze
        bars_limit = int(os.environ.get("SOVEREIGN_SQZ_BARS_LIMIT", "300"))
        bars = dm.get_bars(symbol.upper(), "1D", bars_limit) or []
        result = analyze(symbol, bars)
        if result.get("status") != "success":
            return jsonify(clean_data({"status": "error", **result})), 503
        return jsonify(clean_data(result))
    except Exception as e:
        logger.error(f"[SOVEREIGN-SQZ-BP] {symbol}: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
