"""
SML S/R Zone + Candlestick Pattern Blueprint — /api/sr-zone-pattern
===========================================================
GET /api/sr-zone-pattern/status    Free — scanner state, params, last signal
GET /api/sr-zone-pattern/<symbol>  Free — on-demand zone+pattern analysis of
                                     latest daily bars (503 when insufficient
                                     daily data)
"""
import logging

from flask import Blueprint, jsonify

from core.legacy import get_service, clean_data

logger = logging.getLogger("SR-ZONE-PATTERN-BP")

sr_zone_pattern_bp = Blueprint("sr_zone_pattern", __name__)


@sr_zone_pattern_bp.route("/status", methods=["GET"])
def sr_zone_pattern_status():
    try:
        import sr_zone_pattern_scanner
        return jsonify(clean_data({"status": "success", "scanner": sr_zone_pattern_scanner.status()}))
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@sr_zone_pattern_bp.route("/<symbol>", methods=["GET"])
def sr_zone_pattern_symbol(symbol: str):
    dm = get_service("dm")
    if not dm:
        return jsonify({"status": "error", "message": "DataManager not initialized"}), 503
    try:
        import os
        from sr_zone_pattern_engine import analyze
        bars_limit = int(os.environ.get("SR_ZONE_PATTERN_BARS_LIMIT", "300"))
        bars = dm.get_bars(symbol.upper(), "1D", bars_limit) or []
        result = analyze(symbol, bars)
        if result.get("status") != "success":
            return jsonify(clean_data({"status": "error", **result})), 503
        return jsonify(clean_data(result))
    except Exception as e:
        logger.error(f"[SR-ZONE-PATTERN-BP] {symbol}: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
