"""
Marketing Department — live activity feed.

Real agent runs only. Every entry here comes from an actual completed
step of a real agent (Directory Ranger, Community Scout, Federal Scout,
Content Factory) or the CEO (Campaign Director) that supervises them.
Nothing in this module generates, loops, or fabricates an entry — if
there's no real run to report, GET returns an empty list and callers
must render an honest empty/awaiting-data state, never placeholder rows.

Write access requires MARKETING_ACTIVITY_SECRET so this feed can't be
spammed with fake entries by anyone who finds the endpoint — the entire
point of this feed is that every line in it is verifiably a real event.

Env vars:
  MARKETING_ACTIVITY_SECRET — shared secret for POST /api/marketing/activity.
                              If unset, POST is disabled (503) — matches the
                              graceful-degradation pattern used elsewhere in
                              this codebase (e.g. AEO_TREASURY_XRPL_ADDRESS).
  REDIS_URL                 — shared Redis instance
"""

import os
import json
import time
import logging

import redis
from flask import Blueprint, request, jsonify

log = logging.getLogger("SqueezeOS-MarketingActivity")
marketing_activity_bp = Blueprint("marketing_activity", __name__)

_SECRET     = os.environ.get("MARKETING_ACTIVITY_SECRET", "")
_REDIS_URL  = os.environ.get("REDIS_URL", "")
_FEED_KEY   = "marketing:activity"
_MAX_ENTRIES = 50

_mem_feed = []  # fallback if Redis unavailable — resets on restart, same as other in-memory stores here


def _get_redis():
    if not _REDIS_URL:
        return None
    try:
        return redis.from_url(_REDIS_URL, decode_responses=True)
    except Exception as e:
        log.error("Marketing activity: Redis connect failed: %s", e)
        return None


@marketing_activity_bp.route("/activity", methods=["POST"])
def post_activity():
    if not _SECRET:
        return jsonify({"error": "MARKETING_ACTIVITY_SECRET not configured"}), 503

    if request.headers.get("X-Marketing-Secret", "") != _SECRET:
        return jsonify({"error": "invalid secret"}), 403

    body   = request.get_json(silent=True) or {}
    agent  = (body.get("agent") or "").strip()[:60]
    action = (body.get("action") or "").strip()[:400]
    status = (body.get("status") or "info").strip()[:20]  # info | success | error

    if not agent or not action:
        return jsonify({"error": "agent and action are required"}), 400

    entry = {"agent": agent, "action": action, "status": status, "ts": time.time()}

    r = _get_redis()
    if r:
        r.lpush(_FEED_KEY, json.dumps(entry))
        r.ltrim(_FEED_KEY, 0, _MAX_ENTRIES - 1)
    else:
        _mem_feed.insert(0, entry)
        del _mem_feed[_MAX_ENTRIES:]

    return jsonify({"received": True}), 200


@marketing_activity_bp.route("/activity", methods=["GET"])
def get_activity():
    limit = min(int(request.args.get("limit", 20) or 20), _MAX_ENTRIES)

    r = _get_redis()
    if r:
        raw     = r.lrange(_FEED_KEY, 0, limit - 1)
        entries = [json.loads(x) for x in raw]
    else:
        entries = _mem_feed[:limit]

    last_run_by_agent = {}
    for e in entries:
        if e["agent"] not in last_run_by_agent:
            last_run_by_agent[e["agent"]] = e["ts"]

    return jsonify({
        "entries": entries,
        "count": len(entries),
        "last_run_by_agent": last_run_by_agent,
    })
