"""
SQUEEZE OS — CEO Trader API Blueprint
All mutating routes require X-Owner-Key header matching OWNER_API_KEY env var.
Read-only routes (status, council-arm GET) require no auth.
"""

import os
import time
from flask import Blueprint, jsonify, request
from core.legacy import get_service
from core.state import state

ceo_bp = Blueprint('ceo', __name__)

_OWNER_KEY = os.environ.get('OWNER_API_KEY', '')


def _reload_owner_key():
    """Re-read env in case .env was loaded after module import."""
    global _OWNER_KEY
    _OWNER_KEY = os.environ.get('OWNER_API_KEY', '')


def _owner_required():
    _reload_owner_key()
    if not _OWNER_KEY:
        return False, (jsonify({
            "status": "error",
            "error": "ERR_OWNER_KEY_NOT_CONFIGURED",
            "message": "OWNER_API_KEY env var is not set. Edit .env and restart the server.",
        }), 503)
    if request.headers.get('X-Owner-Key') != _OWNER_KEY:
        return False, (jsonify({
            "status": "error",
            "error": "ERR_NOT_AUTHORIZED",
            "message": "X-Owner-Key header missing or invalid.",
            "remedy": "Set X-Owner-Key: <your OWNER_API_KEY> in your request headers.",
        }), 401)
    return True, None


# ── /api/ceo/status ───────────────────────────────────────────────────────────

@ceo_bp.route('/status', methods=['GET'])
def get_ceo_status():
    """Full CEO Trader state — machine-readable. No auth required."""
    ceo      = get_service('ceo')
    exec_eng = get_service('exec')

    if not ceo or not exec_eng:
        return jsonify({
            "status": "offline",
            "active": False,
            "council_armed": getattr(state, 'council_arm_enabled', False),
            "live_mode": False,
        })

    now            = time.time()
    active_trades  = exec_eng.get_active_trades()
    history        = exec_eng.get_trade_history()
    cooldown_secs  = float(os.environ.get('AUTOPILOT_COOLDOWN_SECONDS', '300'))
    last_entry     = getattr(exec_eng, 'last_autopilot_entry', 0.0)
    conf_floor     = int(os.environ.get('AUTOPILOT_MIN_CONFIDENCE', '82'))

    pending = 0
    try:
        with state.lock:
            pending = len([
                v for v in getattr(state, 'council_verdicts', [])
                if (now - v.get('ts', 0)) < 90
                and v.get('confidence', 0) >= conf_floor
                and v.get('bias', '').upper() in ('BULLISH', 'BEARISH')
            ])
    except Exception:
        pass

    broker_name = type(getattr(exec_eng, 'broker', None)).__name__ \
                  if getattr(exec_eng, 'broker', None) else 'none'

    return jsonify({
        "status":                    "online",
        "active":                    ceo.active,
        "mode":                      "LIVE" if exec_eng.live_mode else "SHADOW",
        "council_armed":             getattr(state, 'council_arm_enabled', False),
        "council_confidence_floor":  conf_floor,
        "broker":                    broker_name,
        "cooldown_seconds":          cooldown_secs,
        "cooldown_remaining":        max(0, round(cooldown_secs - (now - last_entry))),
        "last_entry_ts":             last_entry,
        "active_trades_count":       len(active_trades),
        "active_trades":             active_trades,
        "history_count":             len(history),
        "pdt_trades_used":           len(getattr(exec_eng, 'day_trades', [])),
        "pdt_trades_remaining":      max(0, getattr(exec_eng, 'pdt_limit', 3) - len(getattr(exec_eng, 'day_trades', []))),
        "max_order_value":           getattr(exec_eng, 'max_order_value', 500),
        "pending_council_verdicts":  pending,
    })


# ── /api/ceo/start ────────────────────────────────────────────────────────────

@ceo_bp.route('/start', methods=['POST'])
def start_ceo():
    ok, err = _owner_required()
    if not ok:
        return err
    ceo = get_service('ceo')
    if ceo:
        ceo.start()
        return jsonify({"status": "success", "message": "CEO Trader started"})
    return jsonify({"status": "error", "message": "CEO service unavailable"}), 503


# ── /api/ceo/stop ─────────────────────────────────────────────────────────────

@ceo_bp.route('/stop', methods=['POST'])
def stop_ceo():
    ok, err = _owner_required()
    if not ok:
        return err
    ceo = get_service('ceo')
    if ceo:
        ceo.stop()
        return jsonify({"status": "success", "message": "CEO Trader stopped"})
    return jsonify({"status": "error", "message": "CEO service unavailable"}), 503


# ── /api/ceo/council-arm ─────────────────────────────────────────────────────

@ceo_bp.route('/council-arm', methods=['GET'])
def council_arm_status():
    """Read arm state. No auth required."""
    exec_eng = get_service('exec')
    ceo      = get_service('ceo')
    floor    = int(os.environ.get('AUTOPILOT_MIN_CONFIDENCE', '82'))
    broker   = type(getattr(exec_eng, 'broker', None)).__name__ \
               if exec_eng and getattr(exec_eng, 'broker', None) else 'none'
    return jsonify({
        "council_armed":    getattr(state, 'council_arm_enabled', False),
        "live_mode":        exec_eng.live_mode if exec_eng else False,
        "confidence_floor": floor,
        "broker":           broker,
        "ceo_active":       ceo.active if ceo else False,
        "pdt_remaining":    max(0, getattr(exec_eng, 'pdt_limit', 3) - len(getattr(exec_eng, 'day_trades', []))) if exec_eng else None,
    })


@ceo_bp.route('/council-arm', methods=['POST'])
def council_arm():
    """
    ARM or DISARM council-driven auto-execution on Tradier.
    Auth: X-Owner-Key header required.

    Body:
        {"armed": true}                    — engage
        {"armed": false}                   — disengage
        {"armed": true, "confidence_floor": 80}  — override floor (50-99)

    Errors:
        401  ERR_NOT_AUTHORIZED
        400  ERR_NOT_LIVE    — TRADIER_LIVE not set
        400  ERR_NO_BROKER   — broker not connected
        503  ERR_SERVICE_UNAVAILABLE
    """
    ok, err = _owner_required()
    if not ok:
        return err

    ceo      = get_service('ceo')
    exec_eng = get_service('exec')

    if not ceo or not exec_eng:
        return jsonify({
            "status": "error",
            "error": "ERR_SERVICE_UNAVAILABLE",
            "message": "CEO Trader or Execution Engine is offline.",
        }), 503

    body   = request.get_json(silent=True) or {}
    armed  = bool(body.get('armed', False))

    # Optional confidence override — written to env so CEO Trader picks it up
    floor_override = body.get('confidence_floor')
    if floor_override is not None:
        try:
            os.environ['AUTOPILOT_MIN_CONFIDENCE'] = str(max(50, min(99, int(floor_override))))
        except (ValueError, TypeError):
            pass

    if armed:
        if not exec_eng.live_mode:
            return jsonify({
                "status": "error",
                "error": "ERR_NOT_LIVE",
                "message": "TRADIER_LIVE=true is not set. Execution engine is in SHADOW mode.",
                "remedy": "Add TRADIER_LIVE=true to your .env file and restart the server.",
            }), 400

        broker = getattr(exec_eng, 'broker', None)
        if not broker or not getattr(broker, 'available', False):
            return jsonify({
                "status": "error",
                "error": "ERR_NO_BROKER",
                "message": "No live broker connected. Tradier is not available.",
                "remedy": "Set TRADIER_PRODUCTION_API_KEY and TRADIER_PRODUCTION_ACCOUNT in .env, restart.",
            }), 400

        if not ceo.active:
            ceo.start()

    state.council_arm_enabled = armed
    floor = int(os.environ.get('AUTOPILOT_MIN_CONFIDENCE', '82'))
    broker_name = type(getattr(exec_eng, 'broker', None)).__name__ \
                  if getattr(exec_eng, 'broker', None) else 'none'

    msg = (f"COUNCIL ARM ENGAGED — auto-executing on {broker_name} "
           f"at {floor}%+ confidence") if armed \
          else "COUNCIL ARM DISARMED — manual trading only"

    state.push_terminal('SYSTEM', msg)

    # Broadcast arm-state change over SSE
    arm_evt = {
        'type':             'COUNCIL_ARM_CHANGED',
        'armed':            armed,
        'confidence_floor': floor,
        'live_mode':        exec_eng.live_mode,
        'broker':           broker_name,
        'ts':               time.time(),
        'msg':              msg,
    }
    try:
        from core.state import sse_queues
        for q in sse_queues:
            try:
                q.put_nowait(arm_evt)
            except Exception:
                pass
    except Exception:
        pass

    return jsonify({
        "status":           "success",
        "council_armed":    armed,
        "live_mode":        exec_eng.live_mode,
        "ceo_active":       ceo.active,
        "confidence_floor": floor,
        "broker":           broker_name,
        "message":          msg,
    })
