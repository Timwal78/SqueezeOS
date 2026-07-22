"""
Outreach pitch queue (core/api/outreach_bp.py) — unit tests against the real
blueprint with a bare Flask app (no live server needed, unlike the
integration tests in this directory).

Covers: secret gating (unset -> 503, wrong -> 403), submit + auto-archive
threshold, lead_url dedup, approve/reject state machine, and the guarantee
that approve does not change anything except status/decided_at (no posting
side effects exist to test — the blueprint has no outbound HTTP at all,
which is the point).

Run: python -m pytest tests/test_outreach_queue.py -q
"""

import importlib
import os
import sys

import pytest
from flask import Flask

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def make_app(secret: str | None, threshold: str | None = None):
    if secret is None:
        os.environ.pop("OUTREACH_QUEUE_SECRET", None)
    else:
        os.environ["OUTREACH_QUEUE_SECRET"] = secret
    if threshold is None:
        os.environ.pop("OUTREACH_QUALIFY_THRESHOLD", None)
    else:
        os.environ["OUTREACH_QUALIFY_THRESHOLD"] = threshold

    import core.api.outreach_bp as mod
    importlib.reload(mod)  # module reads env at import time

    app = Flask(__name__)
    app.register_blueprint(mod.outreach_bp, url_prefix="/api/outreach")
    return app.test_client()


PITCH = {
    "platform": "Reddit",
    "lead_title": "How do I charge AI agents for my MCP server?",
    "lead_url": "https://reddit.com/r/AIAgents/comments/test123",
    "lead_context": "OP built an MCP server and wants per-call billing",
    "product": "mcp-x402 npm",
    "pitch_markdown": "You can wrap tools with x402...",
    "lead_score": 85,
}


def test_writes_disabled_without_secret():
    c = make_app(secret=None)
    r = c.post("/api/outreach/submit", json=PITCH)
    assert r.status_code == 503
    # reads stay public
    assert c.get("/api/outreach").status_code == 200


def test_wrong_secret_rejected():
    c = make_app(secret="s3cret")
    r = c.post("/api/outreach/submit", json=PITCH, headers={"X-Outreach-Secret": "nope"})
    assert r.status_code == 403


def test_submit_queue_approve_flow():
    c = make_app(secret="s3cret")
    h = {"X-Outreach-Secret": "s3cret"}

    r = c.post("/api/outreach/submit", json=PITCH, headers=h)
    assert r.status_code == 201
    body = r.get_json()
    assert body["status"] == "pending_review"
    pid = body["id"]

    q = c.get("/api/outreach/queue").get_json()
    assert q["count"] == 1
    assert q["pitches"][0]["id"] == pid

    r = c.post(f"/api/outreach/{pid}/approve", headers=h)
    assert r.status_code == 200
    assert r.get_json()["status"] == "approved_to_send"

    # approving twice is a 409, not a silent success
    assert c.post(f"/api/outreach/{pid}/approve", headers=h).status_code == 409

    detail = c.get(f"/api/outreach/{pid}").get_json()
    assert detail["status"] == "approved_to_send"
    assert detail["pitch_markdown"] == PITCH["pitch_markdown"]
    assert detail["decided_at"] is not None


def test_low_score_auto_archived():
    c = make_app(secret="s3cret")
    h = {"X-Outreach-Secret": "s3cret"}
    weak = dict(PITCH, lead_score=20, lead_url="https://reddit.com/r/AIAgents/comments/weak1")
    r = c.post("/api/outreach/submit", json=weak, headers=h)
    assert r.status_code == 201
    assert r.get_json()["status"] == "archived"
    # archived items never show in the default pending_review queue
    assert c.get("/api/outreach/queue").get_json()["count"] == 0


def test_duplicate_lead_url_not_requeued():
    c = make_app(secret="s3cret")
    h = {"X-Outreach-Secret": "s3cret"}
    first = c.post("/api/outreach/submit", json=PITCH, headers=h).get_json()
    dup = c.post("/api/outreach/submit", json=PITCH, headers=h)
    assert dup.status_code == 200
    assert dup.get_json()["id"] == first["id"]
    assert c.get("/api/outreach/queue").get_json()["count"] == 1


def test_reject_records_reason():
    c = make_app(secret="s3cret")
    h = {"X-Outreach-Secret": "s3cret"}
    pid = c.post("/api/outreach/submit", json=PITCH, headers=h).get_json()["id"]
    r = c.post(f"/api/outreach/{pid}/reject", json={"reason": "off-brand"}, headers=h)
    assert r.status_code == 200
    assert c.get(f"/api/outreach/{pid}").get_json()["review_note"] == "off-brand"


def test_missing_fields_rejected():
    c = make_app(secret="s3cret")
    h = {"X-Outreach-Secret": "s3cret"}
    r = c.post("/api/outreach/submit", json={"platform": "Reddit"}, headers=h)
    assert r.status_code == 400


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
