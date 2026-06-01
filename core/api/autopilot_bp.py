"""
SML SQUEEZE OS — Autopilot Control Blueprint
============================================
GET  /api/autopilot                        → full CEO Trader status
POST /api/autopilot/start                  → activate sovereign autopilot (auth required)
POST /api/autopilot/stop                   → halt autopilot (auth required)
GET  /api/autopilot/trades                 → active + historical trades
POST /api/autopilot/circuit-breaker/reset  → reset circuit breaker after daily halt (auth required)

Auth: X-Operator-Key header must match OPERATOR_API_KEY env var.
"""

import os
from flask import Blueprint, jsonify, request
from core.legacy import get_service
from core.legacy import clean_data

autopilot_bp = Blueprint("autopilot", __name__)


def _require_operator():
    """Returns (ok, error_response). ok=True means auth passed."""
    server_key = os.environ.get("OPERATOR_API_KEY", "")
    if not server_key:
        return False, (jsonify({"error": "OPERATOR_API_KEY not configured on server"}), 503)
    provided = request.headers.get("X-Operator-Key", "")
    if not provided:
        return False, (jsonify({"error": "X-Operator-Key header required"}), 401)
    if provided != server_key:
        return False, (jsonify({"error": "Invalid operator key"}), 403)
    return True, None


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
    ok, err = _require_operator()
    if not ok:
        return err
    ceo = get_service("ceo")
    if not ceo:
        return jsonify({"error": "CEO Trader not initialized"}), 503
    if ceo.active:
        return jsonify({"status": "already_running", "message": "Autopilot already active",
                        "live_mode": ceo.exec.live_mode}), 200
    ceo.start()
    return jsonify({"status": "started", "live_mode": ceo.exec.live_mode,
                    "message": "Sovereign Autopilot is now ONLINE"})


@autopilot_bp.route("/api/autopilot/stop", methods=["POST"])
def autopilot_stop():
    ok, err = _require_operator()
    if not ok:
        return err
    ceo = get_service("ceo")
    if not ceo:
        return jsonify({"error": "CEO Trader not initialized"}), 503
    ceo.stop()
    return jsonify({"status": "stopped", "message": "Autopilot halted — open positions untouched"})


@autopilot_bp.route("/api/autopilot/circuit-breaker/reset", methods=["POST"])
def circuit_breaker_reset():
    ok, err = _require_operator()
    if not ok:
        return err
    ceo = get_service("ceo")
    exec_eng = get_service("exec")
    if not ceo or not exec_eng:
        return jsonify({"error": "Autopilot services not initialized"}), 503
    prev_state = getattr(exec_eng, "circuit_breaker_tripped", False)
    exec_eng.circuit_breaker_tripped = False
    exec_eng.daily_pnl = 0.0
    exec_eng.daily_trade_count = 0
    return jsonify(clean_data({
        "status":         "reset",
        "previous_state": "TRIPPED" if prev_state else "NORMAL",
        "daily_pnl":      exec_eng.daily_pnl,
        "message":        "Circuit breaker reset. Autopilot may resume on next scan cycle.",
    }))


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
