"""
SML SQUEEZE OS — Autopilot Control Blueprint
============================================
GET  /api/autopilot         → full CEO Trader status
POST /api/autopilot/start   → activate sovereign autopilot
POST /api/autopilot/stop    → halt autopilot (leaves open trades untouched)
GET  /api/autopilot/trades  → active + historical trades from ExecutionEngine
"""

from flask import Blueprint, jsonify, request
from core.legacy import get_service
from core.legacy import clean_data

autopilot_bp = Blueprint("autopilot", __name__)


@autopilot_bp.route("/api/autopilot", methods=["GET"])
def autopilot_status():
    ceo  = get_service("ceo")
    exec_eng = get_service("exec")

    if not ceo or not exec_eng:
        return jsonify({"error": "Autopilot services not initialized"}), 503

    return jsonify(clean_data({
        "autopilot": ceo.status,
        "execution": {
            "live_mode":       exec_eng.live_mode,
            "max_order_value": exec_eng.max_order_value,
            "pdt_trades_used": len(exec_eng.day_trades),
            "pdt_limit":       exec_eng.pdt_limit,
        }
    }))


@autopilot_bp.route("/api/autopilot/start", methods=["POST"])
def autopilot_start():
    ceo = get_service("ceo")
    if not ceo:
        return jsonify({"error": "CEO Trader not initialized"}), 503
    if ceo.active:
        return jsonify({"status": "already_running", "message": "Autopilot already active"}), 200
    ceo.start()
    return jsonify({"status": "started", "live_mode": ceo.exec.live_mode})


@autopilot_bp.route("/api/autopilot/stop", methods=["POST"])
def autopilot_stop():
    ceo = get_service("ceo")
    if not ceo:
        return jsonify({"error": "CEO Trader not initialized"}), 503
    ceo.stop()
    return jsonify({"status": "stopped"})


@autopilot_bp.route("/api/autopilot/trades", methods=["GET"])
def autopilot_trades():
    exec_eng = get_service("exec")
    if not exec_eng:
        return jsonify({"error": "Execution engine not initialized"}), 503

    active  = list(exec_eng.get_active_trades().values())
    history = exec_eng.get_trade_history()

    return jsonify(clean_data({
        "active_trades":  active,
        "trade_history":  history[-50:],   # last 50
        "active_count":   len(active),
        "history_count":  len(history),
        "live_mode":      exec_eng.live_mode,
    }))
