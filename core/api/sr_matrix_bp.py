"""
SML Support/Resistance Matrix Blueprint — /api/sr-matrix
===========================================================
GET /api/sr-matrix/status    Free — scanner state, params, last signal
GET /api/sr-matrix/<symbol>  Free — on-demand pivot analysis of latest daily bars
                              (503 when insufficient daily data)
"""
import logging

from flask import Blueprint, jsonify

from core.legacy import get_service, clean_data

logger = logging.getLogger("SR-MATRIX-BP")

sr_matrix_bp = Blueprint("sr_matrix", __name__)


@sr_matrix_bp.route("/status", methods=["GET"])
def sr_matrix_status():
    try:
        import sr_matrix_scanner
        return jsonify(clean_data({"status": "success", "scanner": sr_matrix_scanner.status()}))
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@sr_matrix_bp.route("/<symbol>", methods=["GET"])
def sr_matrix_symbol(symbol: str):
    dm = get_service("dm")
    if not dm:
        return jsonify({"status": "error", "message": "DataManager not initialized"}), 503
    try:
        import os
        from sr_matrix_engine import analyze
        bars_limit = int(os.environ.get("SR_MATRIX_BARS_LIMIT", "300"))
        bars = dm.get_bars(symbol.upper(), "1D", bars_limit) or []
        result = analyze(symbol, bars)
        if result.get("status") != "success":
            return jsonify(clean_data({"status": "error", **result})), 503
        return jsonify(clean_data(result))
    except Exception as e:
        logger.error(f"[SR-MATRIX-BP] {symbol}: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
