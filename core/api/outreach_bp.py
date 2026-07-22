"""
Outreach Pitch Queue — human-approval review queue for the Hermes Sales Agent.
═══════════════════════════════════════════════════════════════════════════════
The Hermes Sales Agent (agent/dept/hermes_sales.py) works the Agent Economy OS
funnel around the clock: it finds real buying-intent conversations (Reddit/HN),
verifies the storefront is actually sellable right now (live HTTP checks), and
drafts a personalized pitch for each qualified lead. Those drafted pitches land
here for Timothy's review.

ZERO AUTO-POSTING: nothing here (or in the sales agent) posts to Reddit, HN,
X, or anywhere else. Approving a pitch only flips its status to
"approved_to_send" — actually posting the reply stays a manual human step
(platform ToS + brand safety; same reason Directory Ranger never auto-submits
listings). Same operator-approval pattern as core/api/grants_bp.py and
core/api/gap_proposals_bp.py.

  GET  /api/outreach                — browse queued pitches (free, read-only)
  GET  /api/outreach/queue          — filter by status (default: pending_review)
  GET  /api/outreach/<id>           — full detail incl. drafted pitch text
  POST /api/outreach/submit         — hermes_sales.py pushes a new pitch (requires secret)
  POST /api/outreach/<id>/approve   — mark approved-to-send (requires secret; does NOT post anything)
  POST /api/outreach/<id>/reject    — mark rejected with a reason (requires secret)

Qualification threshold: lead_score >= OUTREACH_QUALIFY_THRESHOLD (default 60)
queues for review; anything below is auto-archived so weak leads never cost
Timothy a review cycle.

Env:
  OUTREACH_QUEUE_SECRET      — shared secret for POST routes. Unset => writes
                                disabled (503), same graceful-degradation
                                pattern as GRANTS_QUEUE_SECRET.
  OUTREACH_QUALIFY_THRESHOLD — auto-archive cutoff, default 60.

In-memory store — resets on restart. Same MVP pattern as _futures/
_contracts/_listings/_jobs/_queue elsewhere in this codebase.
"""

import os
import time
import uuid
import logging
from flask import Blueprint, jsonify, request

logger = logging.getLogger("SqueezeOS-Outreach")
outreach_bp = Blueprint("outreach", __name__)

_SECRET    = os.environ.get("OUTREACH_QUEUE_SECRET", "")
_THRESHOLD = float(os.environ.get("OUTREACH_QUALIFY_THRESHOLD", 60))
_MAX_ITEMS = 300

_queue: dict = {}  # pitch_id -> record

_VALID_STATUSES = frozenset({"pending_review", "approved_to_send", "rejected", "archived"})


def _require_secret():
    if not _SECRET:
        return jsonify({"error": "OUTREACH_QUEUE_SECRET not configured"}), 503
    if request.headers.get("X-Outreach-Secret", "") != _SECRET:
        return jsonify({"error": "invalid secret"}), 403
    return None


def _summary(rec: dict) -> dict:
    return {
        "id":            rec["id"],
        "platform":      rec["platform"],
        "lead_title":    rec["lead_title"],
        "lead_url":      rec["lead_url"],
        "product":       rec.get("product", ""),
        "lead_score":    rec["lead_score"],
        "status":        rec["status"],
        "discovered_at": rec["discovered_at"],
    }


@outreach_bp.route("", methods=["GET"])
@outreach_bp.route("/", methods=["GET"])
def browse():
    items = sorted(_queue.values(), key=lambda r: -r["discovered_at"])
    return jsonify({
        "count":   len(items),
        "pitches": [_summary(r) for r in items[:100]],
        "ts":      time.time(),
    })


@outreach_bp.route("/queue", methods=["GET"])
def view_queue():
    status = request.args.get("status", "pending_review")
    if status not in _VALID_STATUSES:
        return jsonify({"error": "ERR_INVALID_STATUS", "valid": sorted(_VALID_STATUSES)}), 400
    items = sorted(
        (r for r in _queue.values() if r["status"] == status),
        key=lambda r: -r["discovered_at"],
    )
    return jsonify({
        "status":  status,
        "count":   len(items),
        "pitches": [_summary(r) for r in items],
        "ts":      time.time(),
    })


@outreach_bp.route("/<pitch_id>", methods=["GET"])
def detail(pitch_id):
    rec = _queue.get(pitch_id)
    if not rec:
        return jsonify({"error": "ERR_NOT_FOUND"}), 404
    return jsonify(rec)


@outreach_bp.route("/submit", methods=["POST"])
def submit():
    err = _require_secret()
    if err:
        return err

    body = request.get_json(silent=True) or {}
    platform       = (body.get("platform") or "").strip()
    lead_title     = (body.get("lead_title") or "").strip()
    lead_url       = (body.get("lead_url") or "").strip()
    pitch_markdown = (body.get("pitch_markdown") or "").strip()
    score          = body.get("lead_score")

    if not platform or not lead_title or not lead_url or not pitch_markdown:
        return jsonify({"error": "platform, lead_title, lead_url, and pitch_markdown are required"}), 400
    if not isinstance(score, (int, float)):
        return jsonify({"error": "lead_score (number) is required"}), 400

    # Dedup: one pitch per lead URL — the sales agent runs every 4h and will
    # keep rediscovering the same hot threads.
    for rec in _queue.values():
        if rec["lead_url"] == lead_url and rec["status"] in ("pending_review", "approved_to_send"):
            return jsonify({"id": rec["id"], "status": rec["status"], "note": "duplicate lead_url — already queued"}), 200

    if len(_queue) >= _MAX_ITEMS:
        oldest = min(_queue.keys(), key=lambda k: _queue[k]["discovered_at"])
        _queue.pop(oldest, None)

    pitch_id = str(uuid.uuid4())
    status = "pending_review" if score >= _THRESHOLD else "archived"

    _queue[pitch_id] = {
        "id":             pitch_id,
        "platform":       platform[:50],
        "lead_title":     lead_title[:300],
        "lead_url":       lead_url[:500],
        "lead_context":   (body.get("lead_context") or "").strip()[:2000],
        "product":        (body.get("product") or "").strip()[:100],
        "pitch_markdown": pitch_markdown[:10000],
        "lead_score":     score,
        "status":         status,
        "review_note":    None,
        "discovered_at":  time.time(),
        "decided_at":     None,
    }

    logger.info("[OUTREACH] Queued %s score=%s status=%s", lead_title[:60], score, status)

    return jsonify({
        "id":     pitch_id,
        "status": status,
        "note": (
            "Auto-archived — below lead-score threshold."
            if status == "archived" else
            "Queued for human review. Approving does NOT post anything anywhere — "
            "posting the reply remains a manual step for Timothy."
        ),
    }), 201


@outreach_bp.route("/<pitch_id>/approve", methods=["POST"])
def approve(pitch_id):
    err = _require_secret()
    if err:
        return err
    rec = _queue.get(pitch_id)
    if not rec:
        return jsonify({"error": "ERR_NOT_FOUND"}), 404
    if rec["status"] != "pending_review":
        return jsonify({"error": "ERR_NOT_PENDING", "current_status": rec["status"]}), 409

    rec["status"] = "approved_to_send"
    rec["decided_at"] = time.time()

    logger.info("[OUTREACH] Approved %s (%s)", rec["lead_title"][:60], pitch_id[:8])

    return jsonify({
        "id": pitch_id,
        "status": "approved_to_send",
        "note": (
            "Marked approved-to-send. Nothing has been posted — copy pitch_markdown "
            "and post it manually on the lead's thread."
        ),
    })


@outreach_bp.route("/<pitch_id>/reject", methods=["POST"])
def reject(pitch_id):
    err = _require_secret()
    if err:
        return err
    rec = _queue.get(pitch_id)
    if not rec:
        return jsonify({"error": "ERR_NOT_FOUND"}), 404
    if rec["status"] != "pending_review":
        return jsonify({"error": "ERR_NOT_PENDING", "current_status": rec["status"]}), 409

    body = request.get_json(silent=True) or {}
    rec["status"] = "rejected"
    rec["review_note"] = (body.get("reason") or "").strip()[:500]
    rec["decided_at"] = time.time()

    logger.info("[OUTREACH] Rejected %s (%s)", rec["lead_title"][:60], pitch_id[:8])

    return jsonify({"id": pitch_id, "status": "rejected"})
