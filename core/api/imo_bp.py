"""
SML-IMO Blueprint — /api/imo
============================
GET /api/imo/status    Free — scanner state, params, last signal
GET /api/imo/<symbol>  Free — on-demand IMO analysis of the latest bar
                       (real bars via DataManager; 503 when data missing)
"""
import logging

from flask import Blueprint, jsonify

from core.legacy import get_service, clean_data

logger = logging.getLogger("IMO-BP")

imo_bp = Blueprint("imo", __name__)


@imo_bp.route("/status", methods=["GET"])
def imo_status():
    try:
        import imo_scanner
        return jsonify(clean_data({"status": "success", "scanner": imo_scanner.status()}))
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@imo_bp.route("/<symbol>", methods=["GET"])
def imo_symbol(symbol: str):
    dm = get_service("dm")
    if not dm:
        return jsonify({"status": "error", "message": "DataManager not initialized"}), 503
    try:
        from imo_engine import analyze
        bars = dm.get_bars(symbol.upper(), "1D", 420) or []
        result = analyze(symbol, bars)
        if result.get("status") != "success":
            return jsonify(clean_data({"status": "error", **result})), 503
        return jsonify(clean_data(result))
    except Exception as e:
        logger.error(f"[IMO-BP] {symbol}: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
