"""
SqueezeOS Remote Config — Live Feature Flag Store
═══════════════════════════════════════════════════
Flags live in Redis so any executor anywhere reads the latest state
without touching the Windows machine or redeploying Render.

GET  /api/config          — public, returns all current flags
POST /api/config          — protected by X-API-Key: OWNER_API_KEY
POST /api/config/reset    — restore defaults (protected)

Redis key: squeezeos:feature_flags  (JSON blob)
Falls back to env vars / hardcoded defaults if Redis is unavailable.
"""

import os
import json
import logging
import time
from flask import Blueprint, jsonify, request

logger = logging.getLogger("SqueezeOS-Config")
config_bp = Blueprint("config", __name__)

_REDIS_KEY   = "squeezeos:feature_flags"
_OWNER_KEY   = os.environ.get("OWNER_API_KEY", "")

# Canonical defaults — the baseline every new deployment starts with
_DEFAULTS: dict = {
    "OPTIONS_ENABLED":    False,
    "EQUITY_ENABLED":     True,
    "PAPER_MODE":         False,
    "PDT_SHIELD":         True,
    "MAX_EQUITY_SHARES":  5,
    "MAX_CONTRACTS":      1,
    "CIRCUIT_BREAKER":    True,
    "MAX_DAILY_LOSS_USD": 500.0,
    "KILL_SWITCH":        False,
}


def _get_redis():
    """Return Redis client or None if unavailable."""
    try:
        import redis
        url = os.environ.get("REDIS_URL")
        if not url:
            return None
        r = redis.from_url(url, decode_responses=True, socket_timeout=3)
        r.ping()
        return r
    except Exception as e:
        logger.warning(f"[CONFIG] Redis unavailable: {e}")
        return None


def _read_flags() -> dict:
    """Read flags from Redis. Falls back to env-patched defaults."""
    r = _get_redis()
    if r:
        try:
            raw = r.get(_REDIS_KEY)
            if raw:
                stored = json.loads(raw)
                # Merge: defaults fill in any keys added after last write
                return {**_DEFAULTS, **stored}
        except Exception as e:
            logger.error(f"[CONFIG] Redis read error: {e}")

    # Env-var fallback — lets local .env still override when Redis is down
    flags = dict(_DEFAULTS)
    flags["OPTIONS_ENABLED"]    = os.environ.get("OPTIONS_ENABLED", "false").lower() == "true"
    flags["EQUITY_ENABLED"]     = os.environ.get("EQUITY_ENABLED", "true").lower() == "true"
    flags["PAPER_MODE"]         = os.environ.get("ROBINHOOD_PAPER_MODE", "false").lower() == "true"
    flags["PDT_SHIELD"]         = os.environ.get("PDT_SHIELD_ENABLED", "true").lower() == "true"
    flags["KILL_SWITCH"]        = os.environ.get("KILL_SWITCH", "false").lower() == "true"
    return flags


def _write_flags(flags: dict) -> bool:
    r = _get_redis()
    if not r:
        logger.error("[CONFIG] Cannot persist flags — Redis unavailable")
        return False
    try:
        r.set(_REDIS_KEY, json.dumps(flags))
        logger.info(f"[CONFIG] Flags updated: {flags}")
        return True
    except Exception as e:
        logger.error(f"[CONFIG] Redis write error: {e}")
        return False


def _auth(req) -> bool:
    if not _OWNER_KEY:
        logger.warning("[CONFIG] OWNER_API_KEY not set — blocking all writes")
        return False
    return req.headers.get("X-API-Key", "") == _OWNER_KEY


# ── Routes ────────────────────────────────────────────────────────────────────

@config_bp.route("/config", methods=["GET"])
def get_config():
    flags = _read_flags()
    return jsonify({
        "status":    "ok",
        "flags":     flags,
        "source":    "redis" if _get_redis() else "env_fallback",
        "ts":        time.time(),
        "note":      "POST /api/config with X-API-Key header to update flags",
    })


@config_bp.route("/config", methods=["POST"])
def set_config():
    if not _auth(request):
        return jsonify({"error": "unauthorized", "hint": "X-API-Key header required"}), 401

    body = request.get_json(silent=True) or {}
    if not body:
        return jsonify({"error": "JSON body required"}), 400

    # Validate — only accept known flag keys
    unknown = [k for k in body if k not in _DEFAULTS]
    if unknown:
        return jsonify({
            "error":   "unknown_flags",
            "unknown": unknown,
            "valid":   list(_DEFAULTS.keys()),
        }), 400

    # Type-coerce to match defaults schema
    current = _read_flags()
    for key, val in body.items():
        expected_type = type(_DEFAULTS[key])
        if expected_type == bool:
            if isinstance(val, str):
                val = val.lower() in ("true", "1", "yes")
            current[key] = bool(val)
        elif expected_type == int:
            current[key] = int(val)
        elif expected_type == float:
            current[key] = float(val)
        else:
            current[key] = val

    ok = _write_flags(current)
    if not ok:
        return jsonify({"error": "redis_unavailable", "flags": current}), 503

    return jsonify({
        "status": "updated",
        "flags":  current,
        "ts":     time.time(),
    })


@config_bp.route("/config/reset", methods=["POST"])
def reset_config():
    if not _auth(request):
        return jsonify({"error": "unauthorized"}), 401

    ok = _write_flags(dict(_DEFAULTS))
    return jsonify({
        "status": "reset_to_defaults" if ok else "redis_unavailable",
        "flags":  _DEFAULTS,
    }), 200 if ok else 503
