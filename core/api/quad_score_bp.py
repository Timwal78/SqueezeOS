"""
SML Quad-Score Explosive Breakout Finder Blueprint — /api/quad-score
=====================================================================
GET /api/quad-score/status    Free — scanner state, params, last signal
GET /api/quad-score/<symbol>  Free — on-demand analysis of latest daily bars
                               (503 when insufficient daily data — needs
                               ~4+ years of history for the weekly macro
                               regime filter to seed)
"""
import logging

from flask import Blueprint, jsonify

from core.legacy import get_service, clean_data

logger = logging.getLogger("QUAD-SCORE-BP")

quad_score_bp = Blueprint("quad_score", __name__)


@quad_score_bp.route("/status", methods=["GET"])
def quad_score_status():
    try:
        import quad_score_scanner
        return jsonify(clean_data({"status": "success", "scanner": quad_score_scanner.status()}))
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@quad_score_bp.route("/<symbol>", methods=["GET"])
def quad_score_symbol(symbol: str):
    dm = get_service("dm")
    if not dm:
        return jsonify({"status": "error", "message": "DataManager not initialized"}), 503
    try:
        import os
        from quad_score_engine import analyze
        bars_limit = int(os.environ.get("QUAD_SCORE_BARS_LIMIT", "1100"))
        bars = dm.get_bars(symbol.upper(), "1D", bars_limit) or []
        result = analyze(symbol, bars)
        if result.get("status") != "success":
            return jsonify(clean_data({"status": "error", **result})), 503
        return jsonify(clean_data(result))
    except Exception as e:
        logger.error(f"[QUAD-SCORE-BP] {symbol}: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
