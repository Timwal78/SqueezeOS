"""
Gap-to-Build Proposal Queue — human-approval review queue.
════════════════════════════════════════════════════════════
Closes the loop on the Semantic Gap Detector (core/api/gap_detector_bp.py,
GET /api/graph/gaps): that engine finds real unmet developer demand from
Reddit/HN, but nothing previously acted on what it found. This blueprint
stores build proposals that agent/dept/gap_synthesist.py has drafted for
the highest-intensity uncovered gaps — a technical spec (proposed route,
what it extends, effort estimate) plus the real demand evidence it was
drafted from.

ZERO CUSTODY, ZERO AUTO-DEPLOY: nothing here writes code, opens a PR, or
merges anything. Approving a proposal only flips its status to
"approved_to_build" — actually building it remains a separate, ordinary
dev task for a human (or an agent explicitly asked to do it) to pick up.
Same operator-approval pattern as core/api/grants_bp.py.

Each proposal carries an `evidence_hash` — a SHA-256 digest over its gap
topic, source evidence, and proposed spec, computed at submit time. This
is an integrity check anyone can recompute to confirm the record hasn't
been altered after logging — it is NOT a zero-knowledge proof of anything,
and nothing in this codebase claims otherwise.

  GET  /api/gap-proposals                    — browse queued proposals (free)
  GET  /api/gap-proposals/queue              — filter by status (default: pending_review)
  GET  /api/gap-proposals/<id>               — full detail incl. drafted spec + evidence_hash
  POST /api/gap-proposals/submit             — gap_synthesist.py pushes a new proposal (requires secret)
  POST /api/gap-proposals/<id>/approve       — mark approved-to-build (requires secret; does NOT write or deploy code)
  POST /api/gap-proposals/<id>/reject        — mark rejected with a reason (requires secret)

Qualification threshold: score >= GAP_PROPOSALS_QUALIFY_THRESHOLD (default 60)
queues for review; anything below is auto-archived so low-confidence gaps
never cost Timothy a review cycle.

Env:
  GAP_PROPOSALS_QUEUE_SECRET      — shared secret for POST routes. Unset => writes
                                     disabled (503), same graceful-degradation
                                     pattern as GRANTS_QUEUE_SECRET.
  GAP_PROPOSALS_QUALIFY_THRESHOLD — auto-archive cutoff, default 60.

In-memory store — resets on restart. Same MVP pattern as _futures/
_contracts/_listings/_jobs/_queue elsewhere in this codebase.
"""

import os
import time
import uuid
import hashlib
import json
import logging
from flask import Blueprint, jsonify, request

logger = logging.getLogger("SqueezeOS-GapProposals")
gap_proposals_bp = Blueprint("gap_proposals", __name__)

_SECRET    = os.environ.get("GAP_PROPOSALS_QUEUE_SECRET", "")
_THRESHOLD = float(os.environ.get("GAP_PROPOSALS_QUALIFY_THRESHOLD", 60))
_MAX_ITEMS = 300

_queue: dict = {}  # proposal_id -> record

_VALID_STATUSES = frozenset({"pending_review", "approved_to_build", "rejected", "archived"})


def _require_secret():
    if not _SECRET:
        return jsonify({"error": "GAP_PROPOSALS_QUEUE_SECRET not configured"}), 503
    if request.headers.get("X-Gap-Proposals-Secret", "") != _SECRET:
        return jsonify({"error": "invalid secret"}), 403
    return None


def _evidence_hash(gap_topic: str, source_evidence: list, spec_markdown: str) -> str:
    """SHA-256 integrity digest — an honest checksum, not a ZK proof. Lets
    anyone independently recompute and confirm a proposal record wasn't
    altered after it was logged."""
    canonical = json.dumps(
        {"gap_topic": gap_topic, "source_evidence": source_evidence, "spec_markdown": spec_markdown},
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _summary(rec: dict) -> dict:
    return {
        "id":               rec["id"],
        "gap_topic":        rec["gap_topic"],
        "proposed_route":   rec.get("proposed_route", ""),
        "extends":          rec.get("extends", ""),
        "effort_estimate":  rec.get("effort_estimate", "unknown"),
        "build_score":      rec["build_score"],
        "status":           rec["status"],
        "discovered_at":    rec["discovered_at"],
    }


@gap_proposals_bp.route("", methods=["GET"])
@gap_proposals_bp.route("/", methods=["GET"])
def browse():
    items = sorted(_queue.values(), key=lambda r: -r["discovered_at"])
    return jsonify({
        "count":     len(items),
        "proposals": [_summary(r) for r in items[:100]],
        "ts":        time.time(),
    })


@gap_proposals_bp.route("/queue", methods=["GET"])
def view_queue():
    status = request.args.get("status", "pending_review")
    if status not in _VALID_STATUSES:
        return jsonify({"error": "ERR_INVALID_STATUS", "valid": sorted(_VALID_STATUSES)}), 400
    items = sorted(
        (r for r in _queue.values() if r["status"] == status),
        key=lambda r: -r["discovered_at"],
    )
    return jsonify({
        "status":    status,
        "count":     len(items),
        "proposals": [_summary(r) for r in items],
        "ts":        time.time(),
    })


@gap_proposals_bp.route("/<proposal_id>", methods=["GET"])
def detail(proposal_id):
    rec = _queue.get(proposal_id)
    if not rec:
        return jsonify({"error": "ERR_NOT_FOUND"}), 404
    return jsonify(rec)


@gap_proposals_bp.route("/submit", methods=["POST"])
def submit():
    err = _require_secret()
    if err:
        return err

    body = request.get_json(silent=True) or {}
    gap_topic = (body.get("gap_topic") or "").strip()
    spec_markdown = (body.get("spec_markdown") or "").strip()
    score = body.get("build_score")
    source_evidence = body.get("source_evidence", [])

    if not gap_topic or not spec_markdown:
        return jsonify({"error": "gap_topic and spec_markdown are required"}), 400
    if not isinstance(score, (int, float)):
        return jsonify({"error": "build_score (number) is required"}), 400
    if not isinstance(source_evidence, list):
        return jsonify({"error": "source_evidence must be a list"}), 400

    if len(_queue) >= _MAX_ITEMS:
        oldest = min(_queue.keys(), key=lambda k: _queue[k]["discovered_at"])
        _queue.pop(oldest, None)

    proposal_id = str(uuid.uuid4())
    status = "pending_review" if score >= _THRESHOLD else "archived"
    source_evidence = source_evidence[:10]

    _queue[proposal_id] = {
        "id":               proposal_id,
        "gap_topic":        gap_topic[:300],
        "gap_intensity":    body.get("gap_intensity", 0),
        "proposed_route":   (body.get("proposed_route") or "").strip()[:200],
        "extends":          (body.get("extends") or "").strip()[:300],
        "spec_markdown":    spec_markdown[:20000],
        "effort_estimate":  (body.get("effort_estimate") or "unknown").strip()[:100],
        "build_score":      score,
        "source_evidence":  source_evidence,
        "evidence_hash":    _evidence_hash(gap_topic, source_evidence, spec_markdown),
        "status":           status,
        "review_note":      None,
        "discovered_at":    time.time(),
        "decided_at":       None,
    }

    logger.info("[GAP-PROPOSALS] Queued %s score=%s status=%s", gap_topic[:60], score, status)

    return jsonify({
        "id":     proposal_id,
        "status": status,
        "note": (
            "Auto-archived — below build-worthiness threshold."
            if status == "archived" else
            "Queued for human review. Approving does NOT write or deploy any code — "
            "building it out remains a separate task for Timothy or an agent he explicitly assigns."
        ),
    }), 201


@gap_proposals_bp.route("/<proposal_id>/approve", methods=["POST"])
def approve(proposal_id):
    err = _require_secret()
    if err:
        return err
    rec = _queue.get(proposal_id)
    if not rec:
        return jsonify({"error": "ERR_NOT_FOUND"}), 404
    if rec["status"] != "pending_review":
        return jsonify({"error": "ERR_NOT_PENDING", "current_status": rec["status"]}), 409

    rec["status"] = "approved_to_build"
    rec["decided_at"] = time.time()

    logger.info("[GAP-PROPOSALS] Approved %s (%s)", rec["gap_topic"][:60], proposal_id[:8])

    return jsonify({
        "id": proposal_id,
        "status": "approved_to_build",
        "note": (
            "Marked approved-to-build. No code has been written or deployed — "
            "use spec_markdown as the starting brief for the actual dev task."
        ),
    })


@gap_proposals_bp.route("/<proposal_id>/reject", methods=["POST"])
def reject(proposal_id):
    err = _require_secret()
    if err:
        return err
    rec = _queue.get(proposal_id)
    if not rec:
        return jsonify({"error": "ERR_NOT_FOUND"}), 404
    if rec["status"] != "pending_review":
        return jsonify({"error": "ERR_NOT_PENDING", "current_status": rec["status"]}), 409

    body = request.get_json(silent=True) or {}
    rec["status"] = "rejected"
    rec["review_note"] = (body.get("reason") or "").strip()[:500]
    rec["decided_at"] = time.time()

    logger.info("[GAP-PROPOSALS] Rejected %s (%s)", rec["gap_topic"][:60], proposal_id[:8])

    return jsonify({"id": proposal_id, "status": "rejected"})
