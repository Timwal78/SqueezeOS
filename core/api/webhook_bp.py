"""
SqueezeOS Webhook Subscription System
═══════════════════════════════════════
Agents register a URL; SqueezeOS POSTs signal events in real-time.
No polling required — event-driven architecture for autonomous agents.

  POST   /api/webhooks/subscribe        — register a webhook
  DELETE /api/webhooks/subscribe/<id>   — unsubscribe
  GET    /api/webhooks/subscriptions    — list (requires X-API-Key header)
  POST   /api/webhooks/test/<id>        — send test ping

Delivery:
  POST body = JSON event
  X-SqueezeOS-Signature: sha256=HMAC-SHA256(WEBHOOK_SECRET, raw_body)
  Retry: 3 attempts, exponential backoff (2s, 4s, 8s)
  Auto-deactivate after 10 consecutive delivery failures

Loyalty integration:
  Subscribers who include their wallet address get bonus loyalty points
  recorded in 402Proof for webhook engagement (tracked server-side).
"""

import os
import time
import uuid
import hmac
import json
import hashlib
import logging
import threading
import queue
import requests
from flask import Blueprint, jsonify, request
from core.state import sse_queues

logger = logging.getLogger("SqueezeOS-Webhooks")
webhook_bp = Blueprint("webhooks", __name__)

_WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "squeezeos-webhook-default-secret")
_API_KEY        = os.environ.get("SEED_MERCHANT_API_KEY", "sml-402proof-api-key-scriptmasterlabs-2026")
_MAX_FAILURES   = 10

# ── Subscription store ────────────────────────────────────────────────────────
_subs_lock = threading.Lock()
_subscriptions: dict = {}   # id -> subscription dict

# ── Delivery queue ────────────────────────────────────────────────────────────
_delivery_q: queue.Queue = queue.Queue(maxsize=2000)

# ── Deliverable event types ───────────────────────────────────────────────────
_DELIVERABLE = frozenset({
    "SQUEEZE_ALERT", "OPTIONS_SWEEP", "COUNCIL_VERDICT",
    "AGENT_PAY", "AGENT_PROBE",
})


# ── Internal helpers ──────────────────────────────────────────────────────────

def _sign(body_bytes: bytes) -> str:
    return "sha256=" + hmac.new(_WEBHOOK_SECRET.encode(), body_bytes, hashlib.sha256).hexdigest()


def _matches(sub: dict, event: dict) -> bool:
    f = sub.get("filters", {})

    symbols = f.get("symbols", [])
    if symbols and event.get("symbol", "").upper() not in symbols:
        return False

    event_types = f.get("event_types", [])
    if event_types and event.get("type") not in event_types:
        return False

    min_score = f.get("min_score", 0)
    if min_score and event.get("score", 100) < min_score:
        return False

    min_confidence = f.get("min_confidence", 0)
    if min_confidence and event.get("confidence", 100) < min_confidence:
        return False

    return True


def _deliver_one(sub: dict, event: dict):
    url = sub["url"]
    payload = {**event, "subscription_id": sub["id"], "delivered_at": time.time()}
    body = json.dumps(payload, default=str).encode()
    sig = _sign(body)
    headers = {
        "Content-Type":            "application/json",
        "X-SqueezeOS-Signature":   sig,
        "X-SqueezeOS-Event":       event.get("type", "SIGNAL"),
        "User-Agent":              "SqueezeOS-Webhook/1.0",
    }

    for attempt, delay in enumerate([2, 4, 8], 1):
        try:
            r = requests.post(url, data=body, headers=headers, timeout=10)
            if r.status_code < 500:
                with _subs_lock:
                    if sub["id"] in _subscriptions:
                        s = _subscriptions[sub["id"]]
                        s["delivery_count"] += 1
                        s["consecutive_failures"] = 0
                        s["last_delivery"] = time.time()
                return
        except Exception as e:
            logger.warning(f"[WEBHOOK] attempt {attempt} failed → {url}: {e}")
        if attempt < 3:
            time.sleep(delay)

    with _subs_lock:
        if sub["id"] in _subscriptions:
            s = _subscriptions[sub["id"]]
            s["failure_count"] += 1
            s["consecutive_failures"] = s.get("consecutive_failures", 0) + 1
            if s["consecutive_failures"] >= _MAX_FAILURES:
                s["active"] = False
                logger.warning(f"[WEBHOOK] auto-deactivated {sub['id'][:8]} after {_MAX_FAILURES} failures")


def _delivery_worker():
    while True:
        try:
            event = _delivery_q.get(timeout=1)
        except queue.Empty:
            continue
        with _subs_lock:
            active = [s for s in _subscriptions.values() if s.get("active")]
        for sub in active:
            if _matches(sub, event):
                threading.Thread(
                    target=_deliver_one,
                    args=(sub, event),
                    daemon=True,
                    name=f"whook-{sub['id'][:8]}"
                ).start()


def _sse_tap_worker():
    tap_q: queue.Queue = queue.Queue(maxsize=1000)
    sse_queues.append(tap_q)
    logger.info("[WEBHOOK] SSE tap listening")
    while True:
        try:
            event = tap_q.get(timeout=5)
            if event.get("type") in _DELIVERABLE:
                try:
                    _delivery_q.put_nowait(event)
                except queue.Full:
                    logger.warning("[WEBHOOK] delivery queue full — dropping event")
        except queue.Empty:
            continue
        except Exception as e:
            logger.error(f"[WEBHOOK] SSE tap error: {e}")


def start_webhook_engine():
    threading.Thread(target=_delivery_worker, daemon=True, name="Webhook-Delivery").start()
    threading.Thread(target=_sse_tap_worker,  daemon=True, name="Webhook-SSE-Tap").start()
    logger.info("[WEBHOOK] Engine started — delivery + SSE tap active")


# ── API routes ────────────────────────────────────────────────────────────────

@webhook_bp.route('/subscribe', methods=['POST'])
def subscribe():
    body = request.get_json(silent=True)
    if not body or not body.get("url"):
        return jsonify({"error": "url required"}), 400

    url = str(body["url"]).strip()
    if not url.startswith(("http://", "https://")):
        return jsonify({"error": "url must begin with http:// or https://"}), 400

    raw_filters = body.get("filters", {}) or {}
    filters = {}
    if isinstance(raw_filters.get("symbols"), list):
        filters["symbols"] = [str(s).upper()[:10] for s in raw_filters["symbols"][:20]]
    if isinstance(raw_filters.get("event_types"), list):
        valid_types = list(_DELIVERABLE)
        filters["event_types"] = [
            t for t in raw_filters["event_types"][:10] if t in valid_types
        ]
    if isinstance(raw_filters.get("min_score"), (int, float)):
        filters["min_score"] = max(0, min(100, float(raw_filters["min_score"])))
    if isinstance(raw_filters.get("min_confidence"), (int, float)):
        filters["min_confidence"] = max(0, min(100, float(raw_filters["min_confidence"])))

    sub_id = str(uuid.uuid4())
    sub = {
        "id":                   sub_id,
        "url":                  url,
        "wallet":               str(body.get("wallet", ""))[:64],
        "filters":              filters,
        "created_at":           time.time(),
        "active":               True,
        "delivery_count":       0,
        "failure_count":        0,
        "consecutive_failures": 0,
        "last_delivery":        None,
    }
    with _subs_lock:
        _subscriptions[sub_id] = sub

    logger.info(f"[WEBHOOK] subscribed {sub_id[:8]} → {url}")
    return jsonify({
        "id":             sub_id,
        "status":         "subscribed",
        "url":            url,
        "filters":        filters,
        "signing_header": "X-SqueezeOS-Signature",
        "signing_algo":   "sha256-hmac",
        "note":           "Contact admin for WEBHOOK_SECRET to verify signatures",
        "loyalty":        "Include your XRPL wallet in 'wallet' field to earn loyalty points per delivery",
    }), 201


@webhook_bp.route('/subscribe/<sub_id>', methods=['DELETE'])
def unsubscribe(sub_id):
    with _subs_lock:
        sub = _subscriptions.pop(sub_id, None)
    if not sub:
        return jsonify({"error": "subscription not found"}), 404
    logger.info(f"[WEBHOOK] unsubscribed {sub_id[:8]}")
    return jsonify({"id": sub_id, "status": "unsubscribed"})


@webhook_bp.route('/subscriptions', methods=['GET'])
def list_subscriptions():
    if request.headers.get("X-API-Key", "") != _API_KEY:
        return jsonify({"error": "unauthorized"}), 401
    with _subs_lock:
        subs = list(_subscriptions.values())
    return jsonify({
        "count":         len(subs),
        "active":        sum(1 for s in subs if s["active"]),
        "subscriptions": subs,
    })


@webhook_bp.route('/test/<sub_id>', methods=['POST'])
def test_webhook(sub_id):
    with _subs_lock:
        sub = _subscriptions.get(sub_id)
    if not sub:
        return jsonify({"error": "subscription not found"}), 404
    test_event = {
        "type":    "WEBHOOK_TEST",
        "symbol":  "IWM",
        "score":   85,
        "message": "SqueezeOS webhook delivery test — system nominal",
        "ts":      time.time(),
    }
    threading.Thread(target=_deliver_one, args=(sub, test_event), daemon=True).start()
    return jsonify({"id": sub_id, "status": "test_queued", "event": test_event})
