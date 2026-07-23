"""
CIE Blueprint — /api/cie
========================
GET /api/cie/status              Free — scanner state, params, last signal
GET /api/cie/<symbol>            Free — on-demand CIE analysis on Daily bars
GET /api/cie/<symbol>?tf=1W      Free — same, on Weekly bars (aggregated)
                                  (503 when bar data unavailable)
"""
import logging
import os

from flask import Blueprint, jsonify, request

from core.legacy import get_service, clean_data

logger = logging.getLogger("CIE-BP")

cie_bp = Blueprint("cie", __name__)


@cie_bp.route("/status", methods=["GET"])
def cie_status():
    try:
        import cie_scanner
        return jsonify(clean_data({"status": "success", "scanner": cie_scanner.status()}))
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@cie_bp.route("/<symbol>", methods=["GET"])
def cie_symbol(symbol: str):
    dm = get_service("dm")
    if not dm:
        return jsonify({"status": "error", "message": "DataManager not initialized"}), 503
    try:
        from datetime import date

        from cycle_intelligence_engine import analyze, CIE_CONFIG
        from core.ftd_data import get_store
        from cie_scanner import _aggregate_weekly

        tf = request.args.get("tf", os.environ.get("CIE_TIMEFRAME", "1D")).strip().upper()
        bars_limit = int(os.environ.get("CIE_BARS_LIMIT", "300"))
        daily = dm.get_bars(symbol.upper(), "1D", bars_limit) or []
        if not daily:
            return jsonify({"status": "error", "message": "no daily bars available"}), 503
        bars = _aggregate_weekly(daily) if tf == "1W" else daily
        if len(bars) < 30:
            return jsonify({"status": "error", "message": f"only {len(bars)} {tf} bars — too few"}), 503

        store = get_store()
        recs = store.series_for(symbol.upper(), limit=180)
        if recs:
            window_max = max(r.fail_shares for r in recs) or 1
            float_proxy = max(1, round(window_max / CIE_CONFIG["sett_ftd_high_pct"]))
            ftd_recs = [(r.settlement_date, r.fail_shares, float_proxy) for r in recs]
        else:
            ftd_recs = []
        on_list = store.is_on_threshold_list(symbol.upper())
        since = store.threshold_entry_date(symbol.upper()) if on_list else None

        result = analyze(symbol.upper(), bars, ftd_records=ftd_recs, on_threshold_list=on_list,
                          threshold_since=since, today=date.today())
        if result.get("status") != "success":
            return jsonify(clean_data({"status": "error", **result})), 503
        result["timeframe"] = tf
        return jsonify(clean_data(result))
    except Exception as e:
        logger.error(f"[CIE-BP] {symbol}: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
