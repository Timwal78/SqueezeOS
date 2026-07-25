"""
Paper Trade Ledger Blueprint — /api/paper-trades
===========================================================
GET /api/paper-trades            Free — every system's stats/open positions/
                                  recent closed trades
GET /api/paper-trades/<system>   Free — same, filtered to one system
                                  (e.g. SML_CASCADE, SML_MM_INTEL, SML_BREAKOUT)

Built per operator directive 2026-07-25 ("all paper trades should be
recorded") — see paper_trade_ledger.py's module docstring for the gaps this
closes in iam_executor.py's existing in-memory _positions ledger (no
per-system attribution, resets daily, resets on restart).
"""
import logging

from flask import Blueprint, jsonify, request

from core.legacy import clean_data

logger = logging.getLogger("PAPER-TRADES-BP")

paper_trades_bp = Blueprint("paper_trades", __name__)


@paper_trades_bp.route("", methods=["GET"])
@paper_trades_bp.route("/", methods=["GET"])
def paper_trades_all():
    try:
        import paper_trade_ledger
        limit = int(request.args.get("limit", 100))
        return jsonify(clean_data({"status": "success", **paper_trade_ledger.get_summary(limit=limit)}))
    except Exception as e:
        logger.error(f"[PAPER-TRADES-BP] {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@paper_trades_bp.route("/<system>", methods=["GET"])
def paper_trades_by_system(system: str):
    try:
        import paper_trade_ledger
        limit = int(request.args.get("limit", 100))
        return jsonify(clean_data({"status": "success", **paper_trade_ledger.get_summary(system, limit=limit)}))
    except Exception as e:
        logger.error(f"[PAPER-TRADES-BP] {system}: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
