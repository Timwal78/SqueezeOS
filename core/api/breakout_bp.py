"""
SML Breakout Blueprint — /api/breakout
========================================
GET /api/breakout/status    Free — scanner state, params, last signal
GET /api/breakout/<symbol>  Free — on-demand breakout analysis of latest daily bars
                             (503 when insufficient daily data)
"""
import logging

from flask import Blueprint, jsonify

from core.legacy import get_service, clean_data

logger = logging.getLogger("BREAKOUT-BP")

breakout_bp = Blueprint("breakout", __name__)


@breakout_bp.route("/status", methods=["GET"])
def breakout_status():
    try:
        import breakout_scanner
        return jsonify(clean_data({"status": "success", "scanner": breakout_scanner.status()}))
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@breakout_bp.route("/<symbol>", methods=["GET"])
def breakout_symbol(symbol: str):
    dm = get_service("dm")
    if not dm:
        return jsonify({"status": "error", "message": "DataManager not initialized"}), 503
    try:
        import os
        from breakout_engine import analyze
        bars_limit = int(os.environ.get("BREAKOUT_BARS_LIMIT", "300"))
        bars = dm.get_bars(symbol.upper(), "1D", bars_limit) or []
        result = analyze(symbol, bars)
        if result.get("status") != "success":
            return jsonify(clean_data({"status": "error", **result})), 503
        return jsonify(clean_data(result))
    except Exception as e:
        logger.error(f"[BREAKOUT-BP] {symbol}: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
