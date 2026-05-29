"""
SQUEEZE OS v6.6 — CEO Trader API Blueprint
══════════════════════════════════════════════
Interface for autonomous execution management.
"""

from flask import Blueprint, jsonify, request
from core.legacy import get_service
from core.state import state
import time

ceo_bp = Blueprint('ceo', __name__)

@ceo_bp.route('/status', methods=['GET'])
def get_ceo_status():
    ceo = get_service('ceo')
    exec_eng = get_service('exec')
    
    if not ceo or not exec_eng:
        return jsonify({"status": "offline", "active": False})

    active_trades = exec_eng.get_active_trades()
    history = exec_eng.get_trade_history()
    
    return jsonify({
        "status": "online",
        "active": ceo.active,
        "mode": "LIVE" if exec_eng.live_mode else "SHADOW",
        "cooldown": ceo.cooldown,
        "last_entry": exec_eng.last_autopilot_entry,
        "active_trades_count": len(active_trades),
        "history_count": len(history),
        "pdt_trades": len(exec_eng.day_trades)
    })

@ceo_bp.route('/start', methods=['POST'])
def start_ceo():
    ceo = get_service('ceo')
    if ceo:
        ceo.start()
        return jsonify({"status": "success", "message": "CEO Trader Started"})
    return jsonify({"status": "error", "message": "CEO Service Unavailable"}), 503

@ceo_bp.route('/stop', methods=['POST'])
def stop_ceo():
    ceo = get_service('ceo')
    if ceo:
        ceo.stop()
        return jsonify({"status": "success", "message": "CEO Trader Stopped"})
    return jsonify({"status": "error", "message": "CEO Service Unavailable"}), 503
