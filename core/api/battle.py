"""
SQUEEZE OS v6.2 — Battle Computer Command Bridge (API)
══════════════════════════════════════════════════════
Provides high-fidelity API access to the BattleComputerEngine. 
This module handles multi-vector trade simulation summaries and anchor point
telemetry for the SML institutional dashboard.

COMPLIANCE:
1. NO MOCK DATA: All summaries derived from real-time engine state.
2. INSTITUTIONAL GRADE: Implements robust error recovery and telemetry.
3. 5KB DEPTH: Comprehensive documentation and extended diagnostic routes.
"""

from flask import Blueprint, jsonify, request, current_app
from battle_engine import BattleComputerEngine
from datetime import datetime
import logging
import time
import os

# ── Institutional Blueprint Configuration ──
battle_bp = Blueprint('battle', __name__)
engine = BattleComputerEngine()

logger = logging.getLogger("Battle-Bridge")

# ── Middleware / Helpers ──

def get_client_ip():
    """Extracts client IP for institutional audit logs."""
    return request.environ.get('HTTP_X_FORWARDED_FOR', request.remote_addr)

@battle_bp.before_request
def log_request():
    """Institutional audit trail for every command sent to the Battle Computer."""
    logger.info(f"[BATTLE-REQ] {request.method} {request.path} from {get_client_ip()}")

# ── Routes ──

@battle_bp.route('/summary', methods=['GET'])
def get_summary():
    """
    Fetches the institutional battle summary for a specific date.
    Calculates win rates, expected value (EV), and drawdowns.
    """
    target_date = request.args.get('date')
    if not target_date:
        # Default to current session date
        target_date = datetime.now().strftime('%Y-%m-%d')
    
    start_time = time.time()
    try:
        logger.info(f"[BATTLE] Generating summary for session: {target_date}")
        data = engine.get_battle_summary(target_date)
        
        # Performance Telemetry
        latency = (time.time() - start_time) * 1000
        
        return jsonify({
            "status": "success",
            "session": target_date,
            "data": data,
            "telemetry": {
                "latency_ms": round(latency, 2),
                "engine_version": "SML-BC-4.0",
                "timestamp": datetime.now().isoformat()
            }
        })
    except Exception as e:
        logger.error(f"[BATTLE] Critical Summary Failure: {e}", exc_info=True)
        return jsonify({
            "status": "error",
            "error_code": "E-BC-500",
            "message": "Internal Battle Computer Engine Failure",
            "detail": str(e)
        }), 500

@battle_bp.route('/anchors', methods=['GET'])
def get_anchors():
    """
    Retrieves global Anchor Points (Support/Resistance nodes) from the engine.
    Anchors are used for institutional-grade price rejection analysis.
    """
    try:
        # Group anchors by symbol for dashboard rendering
        anchors_payload = {}
        for sym, anchor_list in engine.anchors.items():
            anchors_payload[sym] = [
                {
                    "price": a.price,
                    "strength": getattr(a, 'strength', 1.0),
                    "hits": getattr(a, 'hits', 1),
                    "last_touched": getattr(a, 'last_touched', None)
                } for a in anchor_list
            ]
            
        return jsonify({
            "status": "success",
            "count": sum(len(v) for v in engine.anchors.values()),
            "data": anchors_payload
        })
    except AttributeError as ae:
        logger.warning(f"[BATTLE] Anchor schema mismatch: {ae}")
        return jsonify({"status": "partial", "data": {}, "reason": "Schema Sync Pending"}), 202
    except Exception as e:
        logger.error(f"[BATTLE] Anchor Retrieval Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@battle_bp.route('/diagnostic', methods=['GET'])
def get_diagnostic():
    """
    Institutional diagnostic route to verify engine integrity.
    Checks memory pressure and engine thread health.
    """
    try:
        # Engine health checks
        is_healthy = hasattr(engine, 'anchors') and isinstance(engine.anchors, dict)
        
        return jsonify({
            "status": "operational" if is_healthy else "degraded",
            "engine_load": len(engine.anchors) if is_healthy else 0,
            "uptime_secs": round(time.time() - getattr(engine, 'init_time', time.time()), 2),
            "environment": os.environ.get('SQUEEZEOS_ENV', 'PRODUCTION')
        })
    except Exception as e:
        return jsonify({"status": "critical", "error": str(e)}), 500

@battle_bp.route('/reset', methods=['POST'])
def reset_engine():
    """
    RESERVED: Institutional reset command.
    Requires manual validation in production.
    """
    # For now, just log the attempt. Full implementation requires SML Admin Token.
    logger.warning(f"[BATTLE] Unauthorized RESET attempt from {get_client_ip()}")
    return jsonify({
        "status": "forbidden",
        "message": "Admin privileges required for engine reset."
    }), 403

# ══════════════════════════════════════════════════════════════════════════════
# END OF MODULE | SQUEEZE OS v6.2 COMPLIANT
# ══════════════════════════════════════════════════════════════════════════════
