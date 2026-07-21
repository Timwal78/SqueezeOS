"""
Trade Desk Stripe webhook — handles Trader ($19/mo) and Pro ($49/mo) subscriptions
for the swarmagentsintelligence.scriptmasterlabs.com dashboard (built externally on Abacus.AI;
this repo only provides the billing backend it calls). Pattern mirrors aeo_stripe_bp.py.
Webhook registered at POST /api/trade-desk/stripe/webhook.

Required env vars:
  TRADE_DESK_STRIPE_TRADER_PRICE_ID — Stripe price ID for Trader tier ($19/mo)
  TRADE_DESK_STRIPE_PRO_PRICE_ID    — Stripe price ID for Pro tier ($49/mo)
  TRADE_DESK_STRIPE_WEBHOOK_SECRET  — whsec_... from Stripe dashboard
  STRIPE_SECRET_KEY                 — sk_live_... (shared with CASCADE/AEO)
  REDIS_URL                         — shared Redis instance

Optional:
  TRADE_DESK_OWNER_KEY — a private static key (not tied to Stripe/Redis at
  all) that always validates as tier=pro. Set this and use it as the
  dashboard's stored api_key to guarantee the operator's own account never
  gets locked out by Stripe/tier-gating bugs on the dashboard side. Unset
  by default — no bypass exists until this is explicitly configured.
"""

import os
import hashlib
import hmac
import json
import time
import logging

import redis
from flask import Blueprint, request, jsonify

from core.stripe_idempotency import already_processed

log = logging.getLogger(__name__)

trade_desk_stripe_bp = Blueprint("trade_desk_stripe", __name__)

# Price IDs — set in Render env vars after Stripe products are created
_TRADER_PRICE_ID = os.environ.get("TRADE_DESK_STRIPE_TRADER_PRICE_ID", "")
_PRO_PRICE_ID    = os.environ.get("TRADE_DESK_STRIPE_PRO_PRICE_ID", "")
_WEBHOOK_SECRET  = os.environ.get("TRADE_DESK_STRIPE_WEBHOOK_SECRET", "")
_REDIS_URL       = os.environ.get("REDIS_URL", "")
_OWNER_KEY       = os.environ.get("TRADE_DESK_OWNER_KEY", "")

# Redis key prefix for Trade Desk API keys
_KEY_PREFIX  = "tradedesk:apikey:"
_TIER_PREFIX = "tradedesk:tier:"

# Key TTL — 400 days (covers annual billing buffer)
_KEY_TTL = 60 * 60 * 24 * 400


def _get_redis():
    if not _REDIS_URL:
        return None
    try:
        return redis.from_url(_REDIS_URL, decode_responses=True)
    except Exception as e:
        log.error("Trade Desk Stripe: Redis connect failed: %s", e)
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
    if price_id == _TRADER_PRICE_ID:
        return "trader"
    if price_id == _PRO_PRICE_ID:
        return "pro"
    return ""


def _issue_key(customer_id: str, customer_email: str, tier: str, sub_id: str) -> str:
    """Generate and store a Trade Desk API key in Redis."""
    r = _get_redis()
    if not r:
        raise RuntimeError("Redis unavailable")

    raw = f"tradedesk-{customer_id}-{sub_id}-{time.time()}"
    api_key = "td_" + hashlib.sha256(raw.encode()).hexdigest()[:40]

    r.setex(f"{_KEY_PREFIX}{api_key}", _KEY_TTL, json.dumps({
        "customer_id": customer_id,
        "customer_email": customer_email,
        "tier": tier,
        "subscription_id": sub_id,
        "issued_at": int(time.time()),
    }))
    # Index by customer for revocation
    r.setex(f"{_TIER_PREFIX}{customer_id}", _KEY_TTL, api_key)
    log.info("Trade Desk Stripe: issued %s key for %s (%s)", tier, customer_email, customer_id)
    return api_key


def _revoke_key(customer_id: str) -> bool:
    """Remove Trade Desk API key from Redis on subscription cancellation."""
    r = _get_redis()
    if not r:
        return False
    api_key = r.get(f"{_TIER_PREFIX}{customer_id}")
    if api_key:
        r.delete(f"{_KEY_PREFIX}{api_key}")
        r.delete(f"{_TIER_PREFIX}{customer_id}")
        log.info("Trade Desk Stripe: revoked key for customer %s", customer_id)
        return True
    return False


@trade_desk_stripe_bp.route("/api/trade-desk/stripe/webhook", methods=["POST"])
def trade_desk_stripe_webhook():
    payload    = request.get_data()
    sig_header = request.headers.get("Stripe-Signature", "")

    if not _WEBHOOK_SECRET:
        log.error("Trade Desk Stripe: TRADE_DESK_STRIPE_WEBHOOK_SECRET not configured")
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
        # Handle plan upgrades (Trader -> Pro) or downgrades
        _handle_subscription_updated(data_obj)

    elif event_type in ("customer.subscription.deleted", "customer.subscription.paused"):
        customer_id = data_obj.get("customer", "")
        if customer_id:
            _revoke_key(customer_id)

    return jsonify({"received": True}), 200


def _handle_subscription_created(sub: dict):
    customer_id    = sub.get("customer", "")
    customer_email = sub.get("customer_email") or sub.get("metadata", {}).get("email", "")
    sub_id         = sub.get("id", "")
    items          = sub.get("items", {}).get("data", [])
    price_id       = items[0].get("price", {}).get("id", "") if items else ""
    tier           = _tier_for_price(price_id)

    if not tier:
        log.info("Trade Desk Stripe: unrecognised price %s — ignoring", price_id)
        return

    if not customer_id or not sub_id:
        log.warning("Trade Desk Stripe: missing customer_id or sub_id in subscription.created")
        return

    try:
        _issue_key(customer_id, customer_email, tier, sub_id)
    except Exception as e:
        log.error("Trade Desk Stripe: failed to issue key: %s", e)


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
        log.error("Trade Desk Stripe: failed to re-issue key on update: %s", e)


@trade_desk_stripe_bp.route("/api/trade-desk/key/validate", methods=["POST"])
def trade_desk_key_validate():
    """Public endpoint — the Abacus.AI dashboard calls this to check a customer's
    tier before unlocking gated pages (Battle Computer, Oracle Journal, Pine Signals, etc.)."""
    api_key = request.json.get("api_key", "") if request.is_json else ""
    if not api_key:
        return jsonify({"valid": False, "error": "missing api_key"}), 400

    # Owner bypass — independent of Stripe/Redis, so the operator's own account
    # can never be locked out by a dashboard-side tier-gating bug. No-op unless
    # TRADE_DESK_OWNER_KEY is explicitly set.
    if _OWNER_KEY and hmac.compare_digest(api_key, _OWNER_KEY):
        return jsonify({"valid": True, "tier": "pro", "customer_email": "owner"})

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
