"""
AEO Suite Stripe webhook — handles Signal ($49/mo) and Sovereign ($149/mo) subscriptions.
Pattern mirrors cascade_bp.py. Webhook registered at POST /api/aeo/stripe/webhook.

Required env vars:
  AEO_STRIPE_SIGNAL_PRICE_ID    — Stripe price ID for Signal tier ($49/mo)
  AEO_STRIPE_SOVEREIGN_PRICE_ID — Stripe price ID for Sovereign tier ($149/mo)
  AEO_STRIPE_WEBHOOK_SECRET     — whsec_... from Stripe dashboard
  STRIPE_SECRET_KEY             — sk_live_... (shared with CASCADE)
  REDIS_URL                     — shared Redis instance
"""

import os
import hashlib
import hmac
import json
import time
import logging

import redis
from flask import Blueprint, request, jsonify

from core.api.aeo_treasury_bp import accrue_usd
from core.stripe_idempotency import already_processed

log = logging.getLogger(__name__)

aeo_stripe_bp = Blueprint("aeo_stripe", __name__)

# Price IDs — set in Render env vars after Stripe products are created
_SIGNAL_PRICE_ID    = os.environ.get("AEO_STRIPE_SIGNAL_PRICE_ID", "")
_SOVEREIGN_PRICE_ID = os.environ.get("AEO_STRIPE_SOVEREIGN_PRICE_ID", "")
_WEBHOOK_SECRET     = os.environ.get("AEO_STRIPE_WEBHOOK_SECRET", "")
_STRIPE_SECRET_KEY  = os.environ.get("STRIPE_SECRET_KEY", "")
_REDIS_URL          = os.environ.get("REDIS_URL", "")

# Redis key prefix for AEO API keys
_KEY_PREFIX = "aeo:apikey:"
_TIER_PREFIX = "aeo:tier:"

# Key TTL — 400 days (covers annual billing buffer)
_KEY_TTL = 60 * 60 * 24 * 400


def _get_redis():
    if not _REDIS_URL:
        return None
    try:
        return redis.from_url(_REDIS_URL, decode_responses=True)
    except Exception as e:
        log.error("AEO Stripe: Redis connect failed: %s", e)
        return None


def _verify_stripe_signature(payload: bytes, sig_header: str, secret: str) -> bool:
    """Verify Stripe webhook signature (HMAC-SHA256)."""
    if not secret or not sig_header:
        return False
    try:
        parts = {k: v for part in sig_header.split(",") for k, v in [part.split("=", 1)]}
        ts = parts.get("t", "")
        v1 = parts.get("v1", "")
        signed_payload = f"{ts}.".encode() + payload
        expected = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, v1)
    except Exception:
        return False


def _tier_for_price(price_id: str) -> str:
    if price_id == _SIGNAL_PRICE_ID:
        return "signal"
    if price_id == _SOVEREIGN_PRICE_ID:
        return "sovereign"
    return ""


def _issue_key(customer_id: str, customer_email: str, tier: str, sub_id: str) -> str:
    """Generate and store an AEO API key in Redis."""
    r = _get_redis()
    if not r:
        raise RuntimeError("Redis unavailable")

    raw = f"aeo-{customer_id}-{sub_id}-{time.time()}"
    api_key = "aeo_" + hashlib.sha256(raw.encode()).hexdigest()[:40]

    r.setex(f"{_KEY_PREFIX}{api_key}", _KEY_TTL, json.dumps({
        "customer_id": customer_id,
        "customer_email": customer_email,
        "tier": tier,
        "subscription_id": sub_id,
        "issued_at": int(time.time()),
    }))
    # Index by customer for revocation
    r.setex(f"{_TIER_PREFIX}{customer_id}", _KEY_TTL, api_key)
    log.info("AEO Stripe: issued %s key for %s (%s)", tier, customer_email, customer_id)
    return api_key


def _revoke_key(customer_id: str) -> bool:
    """Remove AEO API key from Redis on subscription cancellation."""
    r = _get_redis()
    if not r:
        return False
    api_key = r.get(f"{_TIER_PREFIX}{customer_id}")
    if api_key:
        r.delete(f"{_KEY_PREFIX}{api_key}")
        r.delete(f"{_TIER_PREFIX}{customer_id}")
        log.info("AEO Stripe: revoked key for customer %s", customer_id)
        return True
    return False


@aeo_stripe_bp.route("/api/aeo/stripe/webhook", methods=["POST"])
def aeo_stripe_webhook():
    payload    = request.get_data()
    sig_header = request.headers.get("Stripe-Signature", "")

    if not _WEBHOOK_SECRET:
        log.error("AEO Stripe: AEO_STRIPE_WEBHOOK_SECRET not configured")
        return jsonify({"error": "webhook secret not configured"}), 500

    if not _verify_stripe_signature(payload, sig_header, _WEBHOOK_SECRET):
        return jsonify({"error": "invalid signature"}), 400

    try:
        event = json.loads(payload)
    except Exception:
        return jsonify({"error": "invalid JSON"}), 400

    if already_processed(_get_redis(), event.get("id")):
        return jsonify({"received": True}), 200

    event_type = event.get("type", "")
    data_obj   = event.get("data", {}).get("object", {})

    if event_type == "customer.subscription.created":
        _handle_subscription_created(data_obj)

    elif event_type == "customer.subscription.updated":
        # Handle plan upgrades (Signal → Sovereign)
        _handle_subscription_updated(data_obj)

    elif event_type in ("customer.subscription.deleted", "customer.subscription.paused"):
        customer_id = data_obj.get("customer", "")
        if customer_id:
            _revoke_key(customer_id)

    elif event_type in ("invoice.paid", "invoice.payment_succeeded"):
        _handle_invoice_paid(data_obj)

    return jsonify({"received": True}), 200


def _handle_invoice_paid(invoice: dict):
    """Accrue the treasury's 5% cut of a successfully paid subscription invoice."""
    lines = invoice.get("lines", {}).get("data", [])
    price_ids = {li.get("price", {}).get("id", "") for li in lines}
    if not (price_ids & {_SIGNAL_PRICE_ID, _SOVEREIGN_PRICE_ID}):
        return  # not an AEO Suite invoice — ignore

    amount_usd = invoice.get("amount_paid", 0) / 100.0
    if amount_usd <= 0:
        return
    try:
        accrue_usd(amount_usd, source="stripe:aeo")
    except Exception as e:
        log.error("AEO Stripe: treasury accrual failed: %s", e)


def _handle_subscription_created(sub: dict):
    customer_id    = sub.get("customer", "")
    customer_email = sub.get("customer_email") or sub.get("metadata", {}).get("email", "")
    sub_id         = sub.get("id", "")
    items          = sub.get("items", {}).get("data", [])
    price_id       = items[0].get("price", {}).get("id", "") if items else ""
    tier           = _tier_for_price(price_id)

    if not tier:
        log.info("AEO Stripe: unrecognised price %s — ignoring", price_id)
        return

    if not customer_id or not sub_id:
        log.warning("AEO Stripe: missing customer_id or sub_id in subscription.created")
        return

    try:
        _issue_key(customer_id, customer_email, tier, sub_id)
    except Exception as e:
        log.error("AEO Stripe: failed to issue key: %s", e)


def _handle_subscription_updated(sub: dict):
    """Re-issue key on tier upgrade/downgrade."""
    customer_id    = sub.get("customer", "")
    customer_email = sub.get("customer_email") or sub.get("metadata", {}).get("email", "")
    sub_id         = sub.get("id", "")
    items          = sub.get("items", {}).get("data", [])
    price_id       = items[0].get("price", {}).get("id", "") if items else ""
    tier           = _tier_for_price(price_id)

    if not tier or not customer_id:
        return

    _revoke_key(customer_id)
    try:
        _issue_key(customer_id, customer_email, tier, sub_id)
    except Exception as e:
        log.error("AEO Stripe: failed to re-issue key on update: %s", e)


@aeo_stripe_bp.route("/api/aeo/key/validate", methods=["POST"])
def aeo_key_validate():
    """Internal endpoint — validate an AEO API key and return tier. Used by AEO endpoints."""
    api_key = request.json.get("api_key", "") if request.is_json else ""
    if not api_key:
        return jsonify({"valid": False, "error": "missing api_key"}), 400

    r = _get_redis()
    if not r:
        return jsonify({"valid": False, "error": "redis unavailable"}), 503

    record = r.get(f"{_KEY_PREFIX}{api_key}")
    if not record:
        return jsonify({"valid": False}), 401

    try:
        data = json.loads(record)
        return jsonify({"valid": True, "tier": data.get("tier"), "customer_email": data.get("customer_email")})
    except Exception:
        return jsonify({"valid": False}), 500
