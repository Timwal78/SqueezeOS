"""
Autonomous Grant Agent — human-approval queue.
════════════════════════════════════════════════
Zero custody, zero autonomous submission. This blueprint stores grant/
funding opportunities that agent/dept/grant_scout.py has discovered,
scored against SML's capability profile, and drafted a proposal for.
Nothing here ever submits an application to a funder, signs a
transaction, or moves funds — every item sits in the queue until
Timothy explicitly approves or rejects it.

  GET  /api/grants                 — browse queued opportunities (free)
  GET  /api/grants/queue           — filter by status (default: pending_review)
  GET  /api/grants/<id>            — full detail incl. drafted proposal
  POST /api/grants/submit          — grant_scout.py pushes a new discovery (requires secret)
  POST /api/grants/<id>/approve    — mark ready-to-submit (requires secret; does NOT submit anywhere)
  POST /api/grants/<id>/reject     — mark rejected with a reason (requires secret)

Qualification threshold: score >= GRANTS_QUALIFY_THRESHOLD (default 85)
queues for review; anything below is auto-archived so low-confidence
matches never waste a human review cycle.

Env:
  GRANTS_QUEUE_SECRET      — shared secret for POST routes. Unset => writes
                              disabled (503), same graceful-degradation
                              pattern as MARKETING_ACTIVITY_SECRET.
  GRANTS_QUALIFY_THRESHOLD — auto-archive cutoff, default 85.

In-memory store — resets on restart. Same MVP pattern as _futures/
_contracts/_listings/_jobs elsewhere in this codebase.
"""

import time
import uuid
import logging
from flask import Blueprint, jsonify, request

logger = logging.getLogger("SqueezeOS-Grants")
grants_bp = Blueprint("grants", __name__)

import os

_SECRET     = os.environ.get("GRANTS_QUEUE_SECRET", "")
_THRESHOLD  = float(os.environ.get("GRANTS_QUALIFY_THRESHOLD", 85))
_MAX_ITEMS  = 300

_queue: dict = {}  # opportunity_id -> record

_VALID_STATUSES = frozenset({"pending_review", "approved", "rejected", "archived"})


def _require_secret():
    if not _SECRET:
        return jsonify({"error": "GRANTS_QUEUE_SECRET not configured"}), 503
    if request.headers.get("X-Grants-Secret", "") != _SECRET:
        return jsonify({"error": "invalid secret"}), 403
    return None


def _summary(rec: dict) -> dict:
    return {
        "id":                 rec["id"],
        "source":             rec["source"],
        "title":              rec["title"],
        "funder":             rec["funder"],
        "deadline":           rec.get("deadline", "unknown"),
        "funding_amount":     rec.get("funding_amount", "unknown"),
        "qualification_score": rec["qualification_score"],
        "status":             rec["status"],
        "discovered_at":      rec["discovered_at"],
    }


@grants_bp.route("", methods=["GET"])
@grants_bp.route("/", methods=["GET"])
def browse():
    items = sorted(_queue.values(), key=lambda r: -r["discovered_at"])
    return jsonify({
        "count": len(items),
        "opportunities": [_summary(r) for r in items[:100]],
        "ts": time.time(),
    })


@grants_bp.route("/queue", methods=["GET"])
def view_queue():
    status = request.args.get("status", "pending_review")
    if status not in _VALID_STATUSES:
        return jsonify({"error": "ERR_INVALID_STATUS", "valid": sorted(_VALID_STATUSES)}), 400
    items = sorted(
        (r for r in _queue.values() if r["status"] == status),
        key=lambda r: -r["discovered_at"],
    )
    return jsonify({
        "status": status,
        "count": len(items),
        "opportunities": [_summary(r) for r in items],
        "ts": time.time(),
    })


@grants_bp.route("/<opportunity_id>", methods=["GET"])
def detail(opportunity_id):
    rec = _queue.get(opportunity_id)
    if not rec:
        return jsonify({"error": "ERR_NOT_FOUND"}), 404
    return jsonify(rec)


@grants_bp.route("/submit", methods=["POST"])
def submit():
    err = _require_secret()
    if err:
        return err

    body = request.get_json(silent=True) or {}
    title = (body.get("title") or "").strip()
    funder = (body.get("funder") or "").strip()
    source = (body.get("source") or "").strip()
    score = body.get("qualification_score")

    if not title or not funder or not source:
        return jsonify({"error": "title, funder, and source are required"}), 400
    if not isinstance(score, (int, float)):
        return jsonify({"error": "qualification_score (number) is required"}), 400

    if len(_queue) >= _MAX_ITEMS:
        oldest = min(_queue.keys(), key=lambda k: _queue[k]["discovered_at"])
        _queue.pop(oldest, None)

    opportunity_id = str(uuid.uuid4())
    status = "pending_review" if score >= _THRESHOLD else "archived"

    _queue[opportunity_id] = {
        "id":                   opportunity_id,
        "source":               source,
        "title":                title[:300],
        "funder":                funder[:200],
        "program":              (body.get("program") or "").strip()[:200],
        "deadline":             (body.get("deadline") or "unknown").strip()[:100],
        "funding_amount":       (body.get("funding_amount") or "unknown").strip()[:100],
        "url":                  (body.get("url") or "").strip()[:500],
        "qualification_score":  score,
        "matched_capabilities": body.get("matched_capabilities", [])[:20],
        "proposal_draft":       (body.get("proposal_draft") or "").strip()[:20000],
        "milestones":           body.get("milestones", [])[:20],
        "budget_summary":       (body.get("budget_summary") or "").strip()[:2000],
        "status":               status,
        "review_note":          None,
        "discovered_at":        time.time(),
        "decided_at":           None,
    }

    logger.info("[GRANTS] Queued %s (%s) score=%s status=%s", title[:60], source, score, status)

    return jsonify({
        "id":     opportunity_id,
        "status": status,
        "note": (
            "Auto-archived — below qualification threshold."
            if status == "archived" else
            "Queued for human review. Approving does NOT submit anything to the funder — "
            "that remains a manual step for Timothy."
        ),
    }), 201


@grants_bp.route("/<opportunity_id>/approve", methods=["POST"])
def approve(opportunity_id):
    err = _require_secret()
    if err:
        return err
    rec = _queue.get(opportunity_id)
    if not rec:
        return jsonify({"error": "ERR_NOT_FOUND"}), 404
    if rec["status"] != "pending_review":
        return jsonify({"error": "ERR_NOT_PENDING", "current_status": rec["status"]}), 409

    rec["status"] = "approved"
    rec["decided_at"] = time.time()

    logger.info("[GRANTS] Approved %s (%s)", rec["title"][:60], opportunity_id[:8])

    return jsonify({
        "id": opportunity_id,
        "status": "approved",
        "note": (
            "Marked approved. SqueezeOS has not submitted anything and never will — "
            "no signing key exists here. Use the drafted proposal_draft to submit manually "
            "on the funder's portal."
        ),
    })


@grants_bp.route("/<opportunity_id>/reject", methods=["POST"])
def reject(opportunity_id):
    err = _require_secret()
    if err:
        return err
    rec = _queue.get(opportunity_id)
    if not rec:
        return jsonify({"error": "ERR_NOT_FOUND"}), 404
    if rec["status"] != "pending_review":
        return jsonify({"error": "ERR_NOT_PENDING", "current_status": rec["status"]}), 409

    body = request.get_json(silent=True) or {}
    rec["status"] = "rejected"
    rec["review_note"] = (body.get("reason") or "").strip()[:500]
    rec["decided_at"] = time.time()

    logger.info("[GRANTS] Rejected %s (%s)", rec["title"][:60], opportunity_id[:8])

    return jsonify({"id": opportunity_id, "status": "rejected"})
