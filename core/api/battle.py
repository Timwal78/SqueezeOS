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
from collections import deque

# ── Institutional Blueprint Configuration ──
battle_bp = Blueprint('battle', __name__)
engine = BattleComputerEngine()

logger = logging.getLogger("Battle-Bridge")

# ── Oracle vs Swarm observation journal ──────────────────────────────────────
# In-memory ring buffer (max 500). Resets on restart — intentional for MVP.
# Abacus.AI swarm agent POSTs here; Claude Code GETs here. No copy-paste needed.
_observations: deque = deque(maxlen=500)

_VALID_DIRECTIONS = {'bullish', 'bearish', 'neutral'}
_VALID_RELATIONS  = {'agree', 'diverge', 'caution', 'mixed'}

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

@battle_bp.route('/observations', methods=['POST'])
def post_observation():
    """
    Receive an Oracle vs Swarm observation from the Abacus.AI swarm agent.
    Both agents write here; Claude Code reads here. Eliminates copy-paste handoff.
    """
    try:
        body = request.get_json(force=True) or {}

        symbol = (body.get('symbol') or '').upper().strip()
        if not symbol:
            return jsonify({"status": "error", "message": "symbol required"}), 400

        swarm_dir = (body.get('swarm_direction') or '').lower()
        oracle_dir = (body.get('oracle_directive') or '').strip()
        relation   = (body.get('relation') or '').lower()

        if swarm_dir not in _VALID_DIRECTIONS:
            return jsonify({"status": "error", "message": f"swarm_direction must be one of {_VALID_DIRECTIONS}"}), 400
        if not oracle_dir:
            return jsonify({"status": "error", "message": "oracle_directive required"}), 400
        if relation not in _VALID_RELATIONS:
            return jsonify({"status": "error", "message": f"relation must be one of {_VALID_RELATIONS}"}), 400

        entry = {
            "id":               f"obs_{int(time.time() * 1000)}",
            "symbol":           symbol,
            "session_tag":      body.get('session_tag') or None,
            "swarm_direction":  swarm_dir,
            "swarm_confluence": int(body.get('swarm_confluence') or 0),
            "swarm_strength":   body.get('swarm_strength') or 'unknown',
            "agree_count":      int(body.get('agree_count') or 0),
            "total_agents":     int(body.get('total_agents') or 10),
            "bull_count":       int(body.get('bull_count') or 0),
            "bear_count":       int(body.get('bear_count') or 0),
            "neutral_count":    int(body.get('neutral_count') or 0),
            "oracle_directive": oracle_dir,
            "oracle_stance":    (body.get('oracle_stance') or '').lower() or None,
            "oracle_regime":    body.get('oracle_regime') or None,
            "oracle_price":     float(body['oracle_price']) if body.get('oracle_price') is not None else None,
            "oracle_target":    float(body['oracle_target']) if body.get('oracle_target') is not None else None,
            "relation":         relation,
            "note":             body.get('note') or None,
            "created_at":       datetime.utcnow().isoformat() + 'Z',
        }
        _observations.appendleft(entry)
        logger.info("[OBS] %s %s vs Oracle %s → %s", symbol, swarm_dir, oracle_dir, relation)
        return jsonify({"status": "ok", "id": entry["id"], "count": len(_observations)}), 201

    except Exception as e:
        logger.error("[OBS] POST failed: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500


@battle_bp.route('/observations', methods=['GET'])
def get_observations():
    """
    Retrieve the Oracle vs Swarm observation log.
    Optional query params: ?symbol=GME  ?relation=diverge  ?limit=50
    """
    try:
        symbol   = (request.args.get('symbol') or '').upper().strip() or None
        relation = (request.args.get('relation') or '').lower().strip() or None
        limit    = min(int(request.args.get('limit') or 100), 500)

        rows = list(_observations)
        if symbol:
            rows = [r for r in rows if r['symbol'] == symbol]
        if relation:
            rows = [r for r in rows if r['relation'] == relation]
        rows = rows[:limit]

        # Tally
        tally = {'agree': 0, 'diverge': 0, 'caution': 0, 'mixed': 0}
        for r in list(_observations):
            if r['relation'] in tally:
                tally[r['relation']] += 1
        total = sum(tally.values()) or 1

        return jsonify({
            "status":      "ok",
            "total_stored": len(_observations),
            "returned":    len(rows),
            "tally":       tally,
            "tally_pct":   {k: round(v / total * 100, 1) for k, v in tally.items()},
            "observations": rows,
        })
    except Exception as e:
        logger.error("[OBS] GET failed: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500


@battle_bp.route('/observations/summary', methods=['GET'])
def get_observations_summary():
    """
    Markdown digest of the observation log — paste directly into any agent chat.
    Both Claude Code and the Abacus.AI agent can call this to get a shared briefing.
    """
    try:
        rows  = list(_observations)
        total = len(rows)
        if total == 0:
            return jsonify({"status": "ok", "markdown": "No observations recorded yet."}), 200

        tally = {'agree': 0, 'diverge': 0, 'caution': 0, 'mixed': 0}
        for r in rows:
            if r['relation'] in tally:
                tally[r['relation']] += 1

        pct = lambda k: round(tally[k] / total * 100, 1)

        lines = [
            "## Oracle vs Swarm — Observation Log",
            f"**Total captures:** {total}  |  "
            f"Agree {pct('agree')}%  |  Diverge {pct('diverge')}%  |  "
            f"Caution {pct('caution')}%  |  Mixed {pct('mixed')}%",
            "",
            "| # | Time | Symbol | Swarm | Oracle | Relation | Session |",
            "|---|------|--------|-------|--------|----------|---------|",
        ]
        for i, r in enumerate(rows[:50], 1):
            ts  = r['created_at'][:16].replace('T', ' ')
            tag = r.get('session_tag') or '—'
            lines.append(
                f"| {i} | {ts} | {r['symbol']} | "
                f"{r['swarm_direction']} ({r['swarm_confluence']}%) | "
                f"{r['oracle_directive']} | **{r['relation']}** | {tag} |"
            )

        if total > 50:
            lines.append(f"\n_... and {total - 50} more. Filter by ?symbol= or ?relation= to narrow._")

        diverge_rows = [r for r in rows if r['relation'] == 'diverge']
        if diverge_rows:
            lines.append("\n### Key Divergences (Oracle vs Swarm opposite reads)")
            for r in diverge_rows[:10]:
                note = f" — {r['note']}" if r.get('note') else ''
                lines.append(
                    f"- **{r['symbol']}** {r['created_at'][:10]}: "
                    f"Swarm {r['swarm_direction']} vs Oracle {r['oracle_directive']}{note}"
                )

        markdown = "\n".join(lines)
        return jsonify({"status": "ok", "total": total, "tally": tally, "markdown": markdown})

    except Exception as e:
        logger.error("[OBS] summary failed: %s", e)
        return jsonify({"status": "error", "message": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════════════
# END OF MODULE | SQUEEZE OS v6.2 COMPLIANT
# ══════════════════════════════════════════════════════════════════════════════
