"""
SML-DRUCK Blueprint — /api/druck
=================================
GET /api/druck/status    Free — scanner state, params, last signal
GET /api/druck/<symbol>  Free — on-demand DRUCK-LB analysis of latest bars
                         (503 when intraday data unavailable)
"""
import logging

from flask import Blueprint, jsonify

from core.legacy import get_service, clean_data

logger = logging.getLogger("DRUCK-BP")

druck_bp = Blueprint("druck", __name__)


@druck_bp.route("/status", methods=["GET"])
def druck_status():
    try:
        import druck_scanner
        return jsonify(clean_data({"status": "success", "scanner": druck_scanner.status()}))
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@druck_bp.route("/<symbol>", methods=["GET"])
def druck_symbol(symbol: str):
    dm = get_service("dm")
    if not dm:
        return jsonify({"status": "error", "message": "DataManager not initialized"}), 503
    try:
        import os
        from druck_engine import analyze
        tf = os.environ.get("DRUCK_TIMEFRAME", "15MIN")
        bars_limit = int(os.environ.get("DRUCK_BARS_LIMIT", "500"))
        bars = dm.get_bars(symbol.upper(), tf, bars_limit) or []
        result = analyze(symbol, bars)
        if result.get("status") != "success":
            return jsonify(clean_data({"status": "error", **result})), 503
        return jsonify(clean_data(result))
    except Exception as e:
        logger.error(f"[DRUCK-BP] {symbol}: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
