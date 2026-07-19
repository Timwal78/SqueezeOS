"""
ORB v6 BEASTMODE Blueprint — /api/orb
=====================================
GET /api/orb/status    Free — scanner state, params, last signal
GET /api/orb/<symbol>  Free — on-demand ORB+MM analysis of latest intraday
                       bars (503 when intraday data unavailable)
"""
import logging

from flask import Blueprint, jsonify

from core.legacy import get_service, clean_data

logger = logging.getLogger("ORB-BP")

orb_bp = Blueprint("orb", __name__)


@orb_bp.route("/status", methods=["GET"])
def orb_status():
    try:
        import orb_scanner
        return jsonify(clean_data({"status": "success", "scanner": orb_scanner.status()}))
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@orb_bp.route("/<symbol>", methods=["GET"])
def orb_symbol(symbol: str):
    dm = get_service("dm")
    if not dm:
        return jsonify({"status": "error", "message": "DataManager not initialized"}), 503
    try:
        import os
        from orb_engine import analyze
        tf = os.environ.get("ORB_TIMEFRAME", "5MIN")
        bars = dm.get_bars(symbol.upper(), tf, 400) or []
        result = analyze(symbol, bars)
        if result.get("status") != "success":
            return jsonify(clean_data({"status": "error", **result})), 503
        return jsonify(clean_data(result))
    except Exception as e:
        logger.error(f"[ORB-BP] {symbol}: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
