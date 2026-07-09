"""
Marketing Department — live activity feed.

Real agent runs only. Every entry here comes from an actual completed
step of a real agent (Directory Ranger, Community Scout, Federal Scout,
Content Factory) or the CEO (Campaign Director) that supervises them.
Nothing in this module generates, loops, or fabricates an entry — if
there's no real run to report, GET returns an empty list and callers
must render an honest empty/awaiting-data state, never a fabricated row.

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

_SECRET       = os.environ.get("MARKETING_ACTIVITY_SECRET", "")
_REDIS_URL    = os.environ.get("REDIS_URL", "")
_FEED_KEY     = "marketing:activity"
_LISTINGS_KEY = "marketing:directories:latest"
_FEDERAL_KEY  = "marketing:federal:latest"
_MAX_ENTRIES  = 50

_mem_feed = []       # fallback if Redis unavailable — resets on restart, same as other in-memory stores here
_mem_listings = None
_mem_federal = None


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


@marketing_activity_bp.route("/directories", methods=["POST"])
def post_directories():
    """Store the real result of the most recent Directory Ranger run —
    which platforms are actually listed vs. not, per the live HTTP checks
    it just performed. Overwrites the previous snapshot; there is no
    history here, only "the last real audit result"."""
    if not _SECRET:
        return jsonify({"error": "MARKETING_ACTIVITY_SECRET not configured"}), 503
    if request.headers.get("X-Marketing-Secret", "") != _SECRET:
        return jsonify({"error": "invalid secret"}), 403

    body = request.get_json(silent=True) or {}
    snapshot = {
        "already_listed": body.get("already_listed", []),
        "not_listed":      body.get("not_listed", []),
        "checked_at":      time.time(),
    }

    r = _get_redis()
    if r:
        r.set(_LISTINGS_KEY, json.dumps(snapshot))
    else:
        global _mem_listings
        _mem_listings = snapshot

    return jsonify({"received": True}), 200


@marketing_activity_bp.route("/directories", methods=["GET"])
def get_directories():
    """Return the last real Directory Ranger audit. Empty/null fields mean
    no real audit has run yet — never backfilled with a guess."""
    r = _get_redis()
    if r:
        raw = r.get(_LISTINGS_KEY)
        snapshot = json.loads(raw) if raw else None
    else:
        snapshot = _mem_listings

    if not snapshot:
        return jsonify({"already_listed": [], "not_listed": [], "checked_at": None, "audited": False})

    return jsonify({**snapshot, "audited": True})


@marketing_activity_bp.route("/federal", methods=["POST"])
def post_federal():
    """Store the real result of the most recent Federal Scout run — actual
    opportunities it scored against SML's own federal data endpoints.
    Overwrites the previous snapshot; there is no history here, only
    "the last real scan result"."""
    if not _SECRET:
        return jsonify({"error": "MARKETING_ACTIVITY_SECRET not configured"}), 503
    if request.headers.get("X-Marketing-Secret", "") != _SECRET:
        return jsonify({"error": "invalid secret"}), 403

    body = request.get_json(silent=True) or {}
    snapshot = {
        "opportunities_scanned": body.get("opportunities_scanned", 0),
        "high_relevance":        body.get("high_relevance", []),
        "medium_relevance":      body.get("medium_relevance", []),
        "legislative_intel":     body.get("legislative_intel", []),
        "scanned_at":            time.time(),
    }

    r = _get_redis()
    if r:
        r.set(_FEDERAL_KEY, json.dumps(snapshot))
    else:
        global _mem_federal
        _mem_federal = snapshot

    return jsonify({"received": True}), 200


@marketing_activity_bp.route("/federal", methods=["GET"])
def get_federal():
    """Return the last real Federal Scout scan. Empty/null fields mean no
    real scan has run yet — never backfilled with a guess."""
    r = _get_redis()
    if r:
        raw = r.get(_FEDERAL_KEY)
        snapshot = json.loads(raw) if raw else None
    else:
        snapshot = _mem_federal

    if not snapshot:
        return jsonify({
            "opportunities_scanned": 0, "high_relevance": [], "medium_relevance": [],
            "legislative_intel": [], "scanned_at": None, "scanned": False,
        })

    return jsonify({**snapshot, "scanned": True})
