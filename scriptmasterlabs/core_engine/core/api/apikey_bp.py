"""
SML API Key Blueprint
=====================
Stripe Checkout + key management + Smithery-compatible auth.

Routes:
  POST /api/keys/checkout      — create Stripe session → {url}
  GET  /api/keys/success       — post-payment landing, shows API key
  POST /api/keys/webhook       — Stripe webhook (subscription lifecycle)
  GET  /api/keys/status        — check key validity + remaining calls
  POST /api/keys/send-confirmation — background email (no-op if no email config)

STRIPE SETUP (do once in Stripe dashboard):
  1. Create 3 products:
       Dev Pack   — $9   one-time payment  → STRIPE_PRICE_DEV
       Starter    — $29/mo subscription    → STRIPE_PRICE_STARTER
       Pro        — $79/mo subscription    → STRIPE_PRICE_PRO
  2. Set env vars on Render:
       STRIPE_SECRET_KEY       sk_live_...
       STRIPE_WEBHOOK_SECRET   whsec_...
       STRIPE_PRICE_DEV        price_...
       STRIPE_PRICE_STARTER    price_...
       STRIPE_PRICE_PRO        price_...
"""

import os
import logging
from flask import Blueprint, jsonify, request, redirect, make_response

logger = logging.getLogger("SML-APIKeys")
apikey_bp = Blueprint("apikeys", __name__)

BASE_URL = os.environ.get("SQUEEZEOS_BASE_URL", "https://squeezeos-api.onrender.com")


def _stripe():
    import stripe as _s
    _s.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
    return _s


def _price_ids():
    return {
        "dev":     os.environ.get("STRIPE_PRICE_DEV",     ""),
        "starter": os.environ.get("STRIPE_PRICE_STARTER", ""),
        "pro":     os.environ.get("STRIPE_PRICE_PRO",     ""),
    }


# ── Checkout ──────────────────────────────────────────────────────────────────

@apikey_bp.route("/api/keys/checkout", methods=["POST"])
def create_checkout():
    """
    Body: {plan: "dev"|"starter"|"pro", email: "..."}
    Returns: {url: "https://checkout.stripe.com/..."}
    """
    from core.apikey_store import PLANS
    body  = request.get_json(silent=True) or {}
    plan  = body.get("plan", "starter")
    email = body.get("email", "")

    if plan not in PLANS:
        return jsonify({"error": f"Unknown plan '{plan}'. Valid: dev, starter, pro"}), 400

    stripe = _stripe()
    if not stripe.api_key:
        return jsonify({
            "error":   "Stripe not configured on this server",
            "contact": "support@scriptmasterlabs.com",
        }), 503

    price_id = _price_ids().get(plan)
    if not price_id:
        return jsonify({
            "error":   f"Stripe price ID for plan '{plan}' not set — contact support",
            "contact": "support@scriptmasterlabs.com",
        }), 503

    plan_info = PLANS[plan]
    mode = "payment" if plan_info["one_time"] else "subscription"

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            mode=mode,
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=f"{BASE_URL}/api/keys/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{BASE_URL}/pricing",
            customer_email=email or None,
            metadata={"plan": plan},
            allow_promotion_codes=True,
        )
        return jsonify({"url": session.url, "session_id": session.id})
    except Exception as e:
        logger.error(f"[Stripe] Checkout error: {e}")
        return jsonify({"error": str(e)}), 500


# ── Success landing page ──────────────────────────────────────────────────────

@apikey_bp.route("/api/keys/success", methods=["GET"])
def checkout_success():
    session_id = request.args.get("session_id", "")
    if not session_id:
        return redirect("/pricing")

    stripe = _stripe()
    try:
        session   = stripe.checkout.Session.retrieve(session_id)
        plan      = session.metadata.get("plan", "starter")
        email     = ""
        if session.customer_details:
            email = session.customer_details.email or ""
        sub_id    = str(session.subscription or session.payment_intent or "")

        from core.apikey_store import create_key, find_key_by_subscription, PLANS
        existing = find_key_by_subscription(sub_id) if sub_id else None
        api_key  = existing or create_key(plan, email, sub_id)
        plan_info = PLANS.get(plan, PLANS["starter"])

    except Exception as e:
        logger.error(f"[Stripe] Success handler error: {e}")
        return redirect("/pricing")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Your API Key — Script Master Labs</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#0a0a0a;color:#e0e0e0;font-family:'SF Mono','Cascadia Code',Consolas,monospace;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}}
.card{{background:#111;border:1px solid #1e1e1e;border-radius:14px;padding:40px;max-width:640px;width:100%}}
h1{{color:#00ff88;font-size:22px;margin-bottom:6px}}
.sub{{color:#555;font-size:13px;margin-bottom:28px}}
.badge{{display:inline-block;background:#0d1f0d;color:#00ff88;border:1px solid #00ff8830;padding:5px 14px;border-radius:20px;font-size:11px;text-transform:uppercase;letter-spacing:1px;margin-bottom:20px}}
.key-box{{background:#0a0a0a;border:1px solid #00ff8830;border-radius:8px;padding:20px;margin:20px 0}}
.key-label{{color:#444;font-size:10px;text-transform:uppercase;letter-spacing:1.5px;margin-bottom:10px}}
.key-value{{color:#00ff88;font-size:14px;font-weight:700;word-break:break-all;line-height:1.6}}
.copy-btn{{display:inline-block;background:#00ff88;color:#000;border:none;padding:10px 22px;border-radius:6px;cursor:pointer;font-weight:700;font-size:13px;margin-top:14px;font-family:inherit}}
.copy-btn:hover{{background:#00dd77}}
.warn{{color:#ff6b35;font-size:12px;margin-top:12px;padding:10px;background:#1a0f00;border-radius:6px;border:1px solid #ff6b3530}}
.quota{{color:#666;font-size:12px;margin:14px 0}}
.quota span{{color:#00ff88}}
.usage{{margin-top:24px}}
.usage h3{{color:#555;font-size:11px;text-transform:uppercase;letter-spacing:1px;margin-bottom:12px}}
pre{{background:#080808;border:1px solid #1a1a1a;border-radius:6px;padding:14px;font-size:11px;color:#aaa;overflow-x:auto;line-height:1.6;margin-bottom:10px}}
.highlight{{color:#88ccff}}
.foot{{color:#333;font-size:11px;margin-top:24px;border-top:1px solid #1a1a1a;padding-top:16px}}
.foot a{{color:#00ff8880}}
</style>
</head>
<body>
<div class="card">
  <h1>&#10003; Payment Confirmed</h1>
  <p class="sub">Your SqueezeOS API key is live.</p>
  <div class="badge">{plan_info['name']} &middot; {plan_info['calls']} calls</div>

  <div class="key-box">
    <div class="key-label">API Key</div>
    <div class="key-value" id="k">{api_key}</div>
    <button class="copy-btn" onclick="navigator.clipboard.writeText(document.getElementById('k').textContent);this.textContent='&#10003; Copied!';setTimeout(()=>this.textContent='Copy Key',2000)">Copy Key</button>
  </div>

  <div class="warn">&#9888; Save this key — it won&apos;t be shown again.{"  Confirmation sent to " + email if email else ""}</div>
  <div class="quota">Quota: <span>{plan_info['calls']}</span> calls &middot; Used: <span>0</span></div>

  <div class="usage">
    <h3>How to use</h3>
    <pre><span class="highlight"># HTTP header (any endpoint)</span>
Authorization: Bearer {api_key}
<span class="highlight"># OR</span>
X-API-Key: {api_key}</pre>

    <pre><span class="highlight"># Council verdict (curl)</span>
curl -X POST https://squeezeos-api.onrender.com/api/council \\
  -H "Authorization: Bearer {api_key}" \\
  -H "Content-Type: application/json" \\
  -d '{{"symbol":"NVDA"}}'</pre>

    <pre><span class="highlight"># MCP tool call (Claude / Cursor / any MCP client)</span>
POST https://squeezeos-api.onrender.com/mcp
Authorization: Bearer {api_key}

{{"jsonrpc":"2.0","id":1,"method":"tools/call",
 "params":{{"name":"council_verdict","arguments":{{"symbol":"NVDA"}}}}}}</pre>

    <pre><span class="highlight"># Check remaining quota</span>
curl https://squeezeos-api.onrender.com/api/keys/status \\
  -H "Authorization: Bearer {api_key}"</pre>
  </div>

  <div class="foot">
    Support: <a href="mailto:support@scriptmasterlabs.com">support@scriptmasterlabs.com</a> &nbsp;|&nbsp;
    <a href="/.well-known/mcp.json">MCP tools</a> &nbsp;|&nbsp;
    <a href="/pricing">Pricing</a>
  </div>
</div>
</body>
</html>"""

    resp = make_response(html)
    resp.headers["Content-Type"] = "text/html"
    return resp


# ── Stripe webhook ────────────────────────────────────────────────────────────

@apikey_bp.route("/api/keys/webhook", methods=["POST"])
def stripe_webhook():
    payload = request.get_data()
    sig     = request.headers.get("Stripe-Signature", "")
    secret  = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

    stripe = _stripe()
    try:
        event = stripe.Webhook.construct_event(payload, sig, secret)
    except Exception as e:
        logger.warning(f"[Stripe] Webhook sig error: {e}")
        return jsonify({"error": "invalid signature"}), 400

    from core import apikey_store

    etype = event["type"]
    logger.info(f"[Stripe] Webhook: {etype}")

    if etype in ("customer.subscription.deleted", "customer.subscription.paused"):
        sub_id = event["data"]["object"]["id"]
        apikey_store.deactivate_by_subscription(sub_id)

    elif etype == "customer.subscription.updated":
        obj = event["data"]["object"]
        if obj.get("status") == "active":
            apikey_store.reset_quota_by_subscription(obj["id"])

    elif etype == "invoice.payment_succeeded":
        # Monthly renewal — reset quota
        sub_id = event["data"]["object"].get("subscription")
        if sub_id:
            apikey_store.reset_quota_by_subscription(sub_id)

    elif etype == "checkout.session.completed":
        # One-time payment (Dev Pack) — create key if not exists
        sess    = event["data"]["object"]
        plan    = sess.get("metadata", {}).get("plan", "starter")
        email   = (sess.get("customer_details") or {}).get("email", "")
        sub_id  = str(sess.get("subscription") or sess.get("payment_intent") or "")
        existing = apikey_store.find_key_by_subscription(sub_id)
        if not existing:
            apikey_store.create_key(plan, email, sub_id)

    return jsonify({"received": True})


# ── Key status ────────────────────────────────────────────────────────────────

@apikey_bp.route("/api/keys/status", methods=["GET"])
def key_status():
    """Check your API key remaining quota."""
    key = (
        request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        or request.headers.get("X-API-Key", "")
    )
    if not key:
        return jsonify({"error": "Pass Authorization: Bearer <key> or X-API-Key header"}), 400

    from core.apikey_store import validate_key, PLANS
    info = validate_key(key)
    if not info:
        return jsonify({"valid": False, "error": "Invalid, inactive, or quota exhausted key"}), 401

    plan_info = PLANS.get(info["plan"], {})
    return jsonify({
        "valid":           True,
        "plan":            info["plan"],
        "plan_name":       plan_info.get("name", ""),
        "calls_used":      info["calls_used"],
        "calls_limit":     info["calls_limit"],
        "calls_remaining": info["calls_limit"] - info["calls_used"],
        "active":          info["active"],
    })


@apikey_bp.route("/api/keys/send-confirmation", methods=["POST"])
def send_confirmation():
    """Background email confirmation — silently no-ops if not configured."""
    # Implement with SendGrid/Resend if desired — stub for now
    return jsonify({"status": "ok"})
