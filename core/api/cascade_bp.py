"""
CASCADE ACCUMULATOR — Flask Blueprint
Institutional systematic position-building engine. ScriptMaster Labs.

Routes (all at /api/cascade/...):
  GET  /status           Free  — engine health + CASCADE ACCUMULATOR branding
  GET  /info             Free  — product description + tier pricing
  POST /signal           x402  — full cascade directive (0.25 RLUSD per call)
  POST /stripe/checkout  Free  — create Stripe checkout session ($149/mo)
  POST /stripe/webhook   Free  — Stripe event handler (subscription lifecycle)
  GET  /stripe/success   Free  — post-payment confirmation page
"""

import os
import uuid
import json
import time
import logging

from flask import Blueprint, request, jsonify, redirect
from core.legacy import clean_data
from proof402_integration import require_payment

logger = logging.getLogger("CASCADE")

cascade_bp = Blueprint("cascade", __name__)

_BASE  = os.environ.get("SQUEEZEOS_BASE_URL", "https://squeezeos-api.onrender.com")
_SITE  = "https://www.scriptmasterlabs.com"

_STRIPE_SECRET_KEY     = os.environ.get("STRIPE_SECRET_KEY", "")
_STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
_CASCADE_PRICE_ID      = os.environ.get("CASCADE_STRIPE_PRICE_ID", "")
_REDIS_URL             = os.environ.get("REDIS_URL", "redis://localhost:6379")

_SIGNAL_COLORS = {
    "ENTER": "#00CC44",
    "ADD":   "#00AAFF",
    "EXIT":  "#FFB300",
    "STOP":  "#FF3B3B",
}

_DIRECTION_TEXT = {
    "ACCUMULATE": "Accumulate — price dropping through EMA layers, building cost basis",
    "PYRAMID":    "Pyramid — price breaking above EMA layers, scale into the move",
    "EXIT":       "Exit — recovery target reached, realize gains",
    "STOP":       "Stop — anchor layer broken, protect capital immediately",
    "NEUTRAL":    "Neutral — no actionable signal at this time",
}


def _get_engine():
    try:
        import avg_down_engine as e
        return e
    except ImportError:
        return None


def _get_redis():
    try:
        import redis
        return redis.from_url(_REDIS_URL, decode_responses=True)
    except Exception:
        return None


def _cascade_mode(sig_type: str) -> str:
    if sig_type in ("ENTER", "ADD"):
        return "ACCUMULATE"
    if sig_type == "PYRAMID":
        return "PYRAMID"
    if sig_type == "EXIT":
        return "EXIT"
    if sig_type == "STOP":
        return "STOP"
    return "NEUTRAL"


# ── Free: engine status ───────────────────────────────────────────────────────

@cascade_bp.route("/status", methods=["GET"])
def cascade_status():
    e = _get_engine()
    if not e:
        return jsonify({
            "product": "CASCADE ACCUMULATOR",
            "status":  "unavailable",
            "error":   "engine not loaded",
        }), 503
    status = e.get_status()
    status["product"]    = "CASCADE ACCUMULATOR"
    status["version"]    = "1.0.0"
    status["tier"]       = "execution"
    status["asset_class"] = "crypto"
    status["payment"]    = {"x402": "0.25 RLUSD/call", "stripe": "$149/mo"}
    return jsonify(clean_data(status))


# ── Free: product info ────────────────────────────────────────────────────────

@cascade_bp.route("/info", methods=["GET"])
def cascade_info():
    return jsonify({
        "product":     "CASCADE ACCUMULATOR",
        "by":          "ScriptMaster Labs",
        "description": (
            "Institutional systematic position-building engine. "
            "Generates ENTER, ADD, EXIT, and STOP directives based on a "
            "proprietary multi-layer EMA ribbon. Operates in both ACCUMULATE "
            "(downside averaging) and PYRAMID (upside scaling) modes. "
            "Crypto-native. AI-agent compatible via x402 micropayment."
        ),
        "modes": {
            "ACCUMULATE": "Price drops through EMA layers — average down with controlled tranches",
            "PYRAMID":    "Price breaks above EMA layers — scale into a winning position",
            "EXIT":       "Recovery target hit — close position, realize gains",
            "STOP":       "Anchor layer broken — hard stop, protect capital",
        },
        "asset_class":     "crypto (equities + options tiers launching soon)",
        "pricing": {
            "ai_agents":      "0.25 RLUSD per call via x402 on XRP Ledger",
            "humans_monthly": "$149/mo via Stripe — unlimited calls",
        },
        "signals":          ["ENTER", "ADD", "EXIT", "STOP"],
        "stripe_checkout":  f"{_BASE}/api/cascade/stripe/checkout",
        "x402_invoice":     "https://four02proof.onrender.com/v1/invoice",
        "mcp_tool":         "cascade_accumulator",
    })


# ── Premium: full cascade directive (x402 gated at 0.25 RLUSD) ───────────────

@cascade_bp.route("/signal", methods=["POST", "GET"])
@require_payment
def cascade_signal():
    e = _get_engine()
    if not e:
        return jsonify({"error": "CASCADE ACCUMULATOR engine unavailable"}), 503

    if request.is_json:
        symbol = (request.json or {}).get("symbol", "")
    else:
        symbol = request.args.get("symbol", request.form.get("symbol", ""))

    if not symbol:
        return jsonify({"error": "symbol is required"}), 400

    symbol = symbol.upper().strip()

    positions   = {p["symbol"]: p for p in e.get_positions()}
    all_signals = [s for s in e.get_signals(200) if s.get("symbol") == symbol]
    latest      = all_signals[0] if all_signals else None
    position    = positions.get(symbol)

    if not latest and not position:
        return jsonify(clean_data({
            "product":   "CASCADE ACCUMULATOR",
            "symbol":    symbol,
            "directive": "NEUTRAL",
            "cascade_mode": "NEUTRAL",
            "direction": _DIRECTION_TEXT["NEUTRAL"],
            "message":   "No active cascade signal for this symbol. Engine is monitoring.",
        }))

    sig_type    = (latest or {}).get("type", "NEUTRAL")
    sig_data    = (latest or {}).get("data", {})
    mode        = _cascade_mode(sig_type)

    return jsonify(clean_data({
        "product":        "CASCADE ACCUMULATOR",
        "symbol":         symbol,
        "directive":      sig_type,
        "cascade_mode":   mode,
        "direction":      _DIRECTION_TEXT.get(mode, "Neutral"),
        "signal_color":   _SIGNAL_COLORS.get(sig_type, "#888888"),
        "position":       position or {},
        "signal_data":    sig_data,
        "recent_signals": all_signals[:5],
        "asset_class":    "crypto",
        "timestamp":      time.time(),
        "powered_by":     "ScriptMaster Labs — CASCADE ACCUMULATOR v1.0",
    }))


# ── Stripe: create checkout session ──────────────────────────────────────────

@cascade_bp.route("/stripe/checkout", methods=["POST"])
def cascade_stripe_checkout():
    if not _STRIPE_SECRET_KEY:
        return jsonify({"error": "Stripe not configured on this server"}), 503
    if not _CASCADE_PRICE_ID:
        return jsonify({"error": "CASCADE Stripe price ID not configured — set CASCADE_STRIPE_PRICE_ID"}), 503
    try:
        import stripe
        stripe.api_key = _STRIPE_SECRET_KEY
        data  = request.json or {}
        email = data.get("email", "")

        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            mode="subscription",
            line_items=[{"price": _CASCADE_PRICE_ID, "quantity": 1}],
            success_url=(
                f"{_BASE}/api/cascade/stripe/success?session_id={{CHECKOUT_SESSION_ID}}"
            ),
            cancel_url=_SITE,
            customer_email=email or None,
            metadata={"product": "CASCADE_ACCUMULATOR", "tier": "human_monthly"},
        )
        return jsonify({"checkout_url": session.url, "session_id": session.id})
    except Exception as exc:
        logger.error("Stripe checkout error: %s", exc)
        return jsonify({"error": str(exc)}), 500


# ── Stripe: webhook handler ───────────────────────────────────────────────────

@cascade_bp.route("/stripe/webhook", methods=["POST"])
def cascade_stripe_webhook():
    if not _STRIPE_SECRET_KEY or not _STRIPE_WEBHOOK_SECRET:
        return jsonify({"error": "Stripe not configured"}), 503
    try:
        import stripe
        stripe.api_key = _STRIPE_SECRET_KEY
        payload    = request.get_data()
        sig_header = request.headers.get("Stripe-Signature", "")
        event = stripe.Webhook.construct_event(payload, sig_header, _STRIPE_WEBHOOK_SECRET)
    except Exception as exc:
        logger.warning("Stripe webhook validation failed: %s", exc)
        return jsonify({"error": "invalid signature"}), 400

    if event["type"] == "checkout.session.completed":
        session  = event["data"]["object"]
        customer = session.get("customer_email") or session.get("customer", "unknown")
        sub_id   = session.get("subscription", "")
        api_key  = f"sml_live_cascade_{uuid.uuid4().hex[:24]}"
        r = _get_redis()
        if r:
            r.set(f"apikey:{api_key}", json.dumps({
                "active":   True,
                "product":  "CASCADE_ACCUMULATOR",
                "tier":     "human_monthly",
                "customer": customer,
                "sub_id":   sub_id,
                "created":  int(time.time()),
            }))
            logger.info("CASCADE key issued for %s", customer)
        else:
            logger.error("Redis unavailable — CASCADE key NOT stored for %s", customer)

    elif event["type"] in ("customer.subscription.deleted", "customer.subscription.paused"):
        logger.info("CASCADE subscription ended: %s", event["data"]["object"].get("id"))

    return jsonify({"received": True})


# ── Stripe: success confirmation page ────────────────────────────────────────

@cascade_bp.route("/stripe/success", methods=["GET"])
def cascade_stripe_success():
    session_id = request.args.get("session_id", "")
    if not _STRIPE_SECRET_KEY or not session_id:
        return redirect(f"{_SITE}?cascade_success=1")
    try:
        import stripe
        stripe.api_key = _STRIPE_SECRET_KEY
        session = stripe.checkout.Session.retrieve(session_id)
        email   = session.get("customer_email") or "your account"
        return (
            "<html><head><meta charset='UTF-8'>"
            "<style>body{font-family:monospace;background:#050507;color:#00f0ff;"
            "padding:60px;max-width:700px;margin:0 auto;}</style></head><body>"
            "<h1>CASCADE ACCUMULATOR</h1>"
            "<h2 style='color:#00ff66'>Access Granted</h2>"
            f"<p>Subscription active for <strong>{email}</strong>.</p>"
            "<p>Your API key has been issued. Use header:<br>"
            "<code style='background:#0a0a1e;padding:8px;display:block;margin:12px 0'>"
            "Authorization: Bearer sml_live_cascade_...</code></p>"
            "<p>Key delivery via email is coming soon. In the meantime contact "
            f"<a href='mailto:scriptmasterlabs@gmail.com' style='color:#00f0ff'>"
            "scriptmasterlabs@gmail.com</a> with your confirmation.</p>"
            f"<p><a href='{_SITE}' style='color:#00f0ff'>Return to ScriptMaster Labs &rarr;</a></p>"
            "</body></html>"
        )
    except Exception:
        return redirect(f"{_SITE}?cascade_success=1")
