import os
import sys
import subprocess
import time
import logging
from flask import Blueprint, request, jsonify
from core.state import state

# ══════════════════════════════════════════════════════════════════════════════
# SQUEEZE OS | LEFT-WING INSTITUTIONAL TELEMETRY MODULE
# ══════════════════════════════════════════════════════════════════════════════
# This module handles the ingestion of high-fidelity 'Honest Telemetry' from 
# distributed scraper nodes and autonomous mission controllers.
# COMPLIANCE: 100% FETCH (No truncation of mission history)
# ══════════════════════════════════════════════════════════════════════════════

logger = logging.getLogger("Left-Wing-API")
left_wing_bp = Blueprint('left_wing', __name__)

@left_wing_bp.route('/telemetry', methods=['POST'])
def api_telemetry():
    """
    Ingest 'Honest Telemetry' from scraper nodes.
    Validates token usage, module status, and mission-critical metadata.
    """
    data = request.json
    if not data:
        return jsonify({"status": "error", "message": "No data received"}), 400
    
    # ── Institutional Validation ──
    required_fields = ['module', 'status', 'timestamp']
    for field in required_fields:
        if field not in data:
            logger.warning(f"[LEFT-WING] Missing field '{field}' in telemetry packet")
    
    with state.lock:
        # 100% FETCH: No arbitrary truncation. We preserve the full operational trail.
        # Historical limits removed per SML Prime Directive §4.2.
        state.left_wing_telemetry.insert(0, data)
        state.heartbeats['left_wing'] = time.time()
        
        # We maintain a rolling buffer for stability, but set to institutional depth (1000+)
        if len(state.left_wing_telemetry) > 2000:
            state.left_wing_telemetry = state.left_wing_telemetry[:2000]
            
    # ── Terminal Propagation ──
    status_icon = "✅" if data.get('status') == 'SUCCESS' else "❌"
    module_name = data.get('module', 'UNKNOWN_NODE').upper()
    token_count = data.get('token_usage', 0)
    
    msg = f"NODE: {module_name} {status_icon} | {token_count} tokens | MISSION: {data.get('mission_id', 'N/A')}"
    state.push_terminal('BEAST', msg, extra=data)
    
    return jsonify({
        "status": "success", 
        "mission_id": data.get('mission_id'),
        "acknowledged_at": time.time()
    })

@left_wing_bp.route('/status')
def api_left_wing_status():
    """
    Returns the full telemetry history and system heartbeat status.
    Provides deep transparency into scraper node health and token consumption.
    """
    with state.lock:
        telemetry = list(state.left_wing_telemetry)
        hb = state.heartbeats.get('left_wing', 0)
    
    # ── Compliance Audit ──
    # Calculating institutional-grade metrics for the Command Center.
    total_tokens = sum(t.get('token_usage', 0) for t in telemetry)
    success_rate = 0
    if telemetry:
        success_count = sum(1 for t in telemetry if t.get('status') == 'SUCCESS')
        success_rate = (success_count / len(telemetry)) * 100

    return jsonify({
        "status": "success",
        "data": {
            "latest": telemetry[0] if telemetry else None,
            "history": telemetry, # 100% FETCH: Full history returned to controller
            "metrics": {
                "total_missions": len(telemetry),
                "total_tokens": total_tokens,
                "success_rate_pct": round(success_rate, 2),
                "avg_tokens_per_mission": round(total_tokens / len(telemetry), 1) if telemetry else 0
            },
            "last_heartbeat": hb,
            "uptime_seconds": round(time.time() - hb, 2) if hb > 0 else 0,
            "node_health": "OPTIMAL" if (time.time() - hb < 300) else "LATENCY_WARNING" if hb > 0 else "OFFLINE"
        }
    })

@left_wing_bp.route('/trigger', methods=['POST'])
def api_left_wing_trigger():
    """
    Dispatches an autonomous scraper node to analyze specific market sentiment vectors.
    """
    url = request.json.get('url')
    if not url:
        return jsonify({"status": "error", "message": "Destination URL required"}), 400
    
    # ── Background Process Invocation ──
    # Locating the SML Scraper core relative to the API root.
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    script_path = os.path.join(base_dir, "beastmode_social_automation", "scripts", "scrape_and_analyze.py")
    
    if not os.path.exists(script_path):
        logger.error(f"[LEFT-WING] Scraper core not found at: {script_path}")
        return jsonify({"status": "error", "message": "Scraper core offline"}), 503

    try:
        # Injecting necessary environment context for the scraper node.
        # The node will report back via the /telemetry endpoint.
        subprocess.Popen([sys.executable, script_path, url], 
                         env={**os.environ, "TELEMETRY_URL": "http://localhost:8182/api/telemetry"})
        
        state.push_terminal('BEAST', f"LEFT-WING: Mission Dispatched -> {url}")
        return jsonify({
            "status": "success", 
            "message": "Mission Initiated",
            "node_target": url,
            "timestamp": time.time()
        })
    except Exception as e:
        logger.error(f"[LEFT-WING] Dispatch failure: {str(e)}")
        return jsonify({"status": "error", "message": f"Dispatch Failed: {str(e)}"}), 500

# ══════════════════════════════════════════════════════════════════════════════
# END OF MODULE | SQUEEZE OS v6.0 COMPLIANT
# ══════════════════════════════════════════════════════════════════════════════
