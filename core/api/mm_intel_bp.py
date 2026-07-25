"""
SML Market Maker Intelligence v4 Blueprint — /api/mm-intel
===========================================================
GET /api/mm-intel/status    Free — scanner state, params, last signal
GET /api/mm-intel/<symbol>  Free — on-demand analysis of latest intraday bars
                              (503 when no intraday data available)
"""
import logging

from flask import Blueprint, jsonify

from core.legacy import get_service, clean_data

logger = logging.getLogger("MM-INTEL-BP")

mm_intel_bp = Blueprint("mm_intel", __name__)


@mm_intel_bp.route("/status", methods=["GET"])
def mm_intel_status():
    try:
        import mm_intel_scanner
        return jsonify(clean_data({"status": "success", "scanner": mm_intel_scanner.status()}))
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@mm_intel_bp.route("/<symbol>", methods=["GET"])
def mm_intel_symbol(symbol: str):
    dm = get_service("dm")
    if not dm:
        return jsonify({"status": "error", "message": "DataManager not initialized"}), 503
    try:
        import os
        from mm_intel_engine import analyze
        timeframe = os.environ.get("MM_INTEL_TIMEFRAME", "5MIN")
        bars_limit = int(os.environ.get("MM_INTEL_BARS_LIMIT", "300"))
        bars = dm.get_bars(symbol.upper(), timeframe, bars_limit) or []
        result = analyze(symbol, bars)
        if result.get("status") != "success":
            return jsonify(clean_data({"status": "error", **result})), 503
        return jsonify(clean_data(result))
    except Exception as e:
        logger.error(f"[MM-INTEL-BP] {symbol}: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
