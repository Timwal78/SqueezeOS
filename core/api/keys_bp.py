import os
import json
import logging
import uuid
import secrets
from flask import Blueprint, request, jsonify, redirect, render_template_string
import stripe
import redis

logger = logging.getLogger("SqueezeOS-Keys")
keys_bp = Blueprint('keys', __name__)

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY")
webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET")

# Connect to Redis
redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
try:
    r = redis.from_url(redis_url, decode_responses=True)
except Exception as e:
    logger.error(f"Failed to connect to Redis: {e}")
    r = None

# Pricing IDs from env
PRICES = {
    "dev": os.environ.get("STRIPE_PRICE_DEV"),
    "starter": os.environ.get("STRIPE_PRICE_STARTER"),
    "pro": os.environ.get("STRIPE_PRICE_PRO"),
}

PRICING_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>SqueezeOS API Pricing</title>
    <style>
        body { font-family: -apple-system, sans-serif; background: #0a0a0a; color: #fff; padding: 50px; text-align: center; }
        .grid { display: flex; justify-content: center; gap: 20px; margin-top: 40px; }
        .card { background: #1a1a1a; padding: 30px; border-radius: 8px; width: 300px; border: 1px solid #333; }
        .price { font-size: 2em; margin: 20px 0; color: #f39c12; }
        .btn { display: inline-block; background: #e67e22; color: #fff; text-decoration: none; padding: 10px 20px; border-radius: 4px; font-weight: bold; }
        .btn:hover { background: #d35400; }
    </style>
</head>
<body>
    <h1>SqueezeOS API</h1>
    <p>Unlock premium AI agent endpoints.</p>
    <div class="grid">
        <div class="card">
            <h2>Dev Pack</h2>
            <div class="price">$9.00</div>
            <p>One-time payment for testing and development.</p>
            <a class="btn" href="/api/keys/checkout?plan=dev">Buy Now</a>
        </div>
        <div class="card">
            <h2>Starter</h2>
            <div class="price">$29.00 / mo</div>
            <p>Perfect for solo agents.</p>
            <a class="btn" href="/api/keys/checkout?plan=starter">Subscribe</a>
        </div>
        <div class="card">
            <h2>Pro</h2>
            <div class="price">$79.00 / mo</div>
            <p>Institutional grade volume.</p>
            <a class="btn" href="/api/keys/checkout?plan=pro">Subscribe</a>
        </div>
    </div>
</body>
</html>
"""

SUCCESS_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Payment Successful</title>
    <style>
        body { font-family: monospace; background: #0a0a0a; color: #0f0; padding: 50px; text-align: center; }
        .key-box { background: #1a1a1a; padding: 20px; border: 1px solid #0f0; display: inline-block; margin-top: 20px; font-size: 1.5em; letter-spacing: 2px; }
        p { font-size: 1.2em; color: #fff; }
    </style>
</head>
<body>
    <h1>✅ Payment Successful</h1>
    <p>Here is your SqueezeOS API Key. Keep it secret.</p>
    <div class="key-box">{{ api_key }}</div>
    <p style="margin-top:40px; color:#aaa;">Pass this via <code>X-API-KEY: {{ api_key }}</code> or <code>Authorization: Bearer {{ api_key }}</code>.</p>
</body>
</html>
"""

@keys_bp.route('/pricing', methods=['GET'])
def pricing():
    return render_template_string(PRICING_HTML)


@keys_bp.route('/api/keys/checkout', methods=['GET'])
def checkout():
    if not stripe.api_key:
        return "Stripe is not configured on this server.", 500

    plan = request.args.get('plan')
    price_id = PRICES.get(plan)
    if not price_id:
        return "Invalid plan selected or missing Stripe Price ID.", 400

    # Generate the future API key and store it in client_reference_id
    new_api_key = f"sml_live_{secrets.token_hex(16)}"

    mode = "payment" if plan == "dev" else "subscription"

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price': price_id,
                'quantity': 1,
            }],
            mode=mode,
            client_reference_id=new_api_key,
            success_url=request.host_url.rstrip('/') + "/api/keys/success?session_id={CHECKOUT_SESSION_ID}",
            cancel_url=request.host_url.rstrip('/') + "/pricing",
        )
        return redirect(session.url, code=303)
    except Exception as e:
        logger.error(f"Stripe error: {e}")
        return str(e), 500


@keys_bp.route('/api/keys/success', methods=['GET'])
def success():
    session_id = request.args.get('session_id')
    if not session_id:
        return "Missing session_id", 400

    try:
        session = stripe.checkout.Session.retrieve(session_id)
        api_key = session.client_reference_id
        if not api_key:
            return "No API key found for this session.", 404
        return render_template_string(SUCCESS_HTML, api_key=api_key)
    except Exception as e:
        return str(e), 500


@keys_bp.route('/api/keys/webhook', methods=['POST'])
def webhook():
    payload = request.data
    sig_header = request.headers.get('Stripe-Signature')

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except ValueError as e:
        return 'Invalid payload', 400
    except stripe.error.SignatureVerificationError as e:
        return 'Invalid signature', 400

    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        api_key = session.get('client_reference_id')
        customer_email = session.get('customer_details', {}).get('email', 'unknown')
        plan_type = session.get('mode') # payment or subscription

        if api_key and r:
            data = {
                "active": True,
                "email": customer_email,
                "type": plan_type,
                "created": event['created']
            }
            # Store in Redis
            r.set(f"apikey:{api_key}", json.dumps(data))
            logger.info(f"Provisioned new API key for {customer_email}")

            # Send Discord Alert for Stripe Payment
            webhook_url = os.environ.get("DISCORD_WEBHOOK_PAYMENTS")
            if webhook_url:
                try:
                    amount = session.get('amount_total', 0) / 100
                    payload = {
                        "embeds": [{
                            "title": f"💳 NEW CUSTOMER PAYMENT — ${amount:.2f}",
                            "description": f"**Customer**: {customer_email}\n**Plan**: {plan_type.upper()}",
                            "color": 0x00FF88
                        }]
                    }
                    import requests
                    requests.post(webhook_url, json=payload, timeout=5)
                except Exception as e:
                    logger.error(f"Failed to post Stripe payment to Discord: {e}")

    elif event['type'] in ['customer.subscription.deleted', 'customer.subscription.canceled']:
        # Note: In a full system, you would look up the API key by customer ID and disable it.
        # For MVP, we can handle deletions manually or query Redis.
        pass

    return jsonify(success=True)


@keys_bp.route('/api/keys/status', methods=['GET'])
def status():
    """Check if an API key is valid"""
    auth_header = request.headers.get('Authorization', '')
    bearer = auth_header.split('Bearer ')[-1].strip() if 'Bearer ' in auth_header else ''
    api_key = request.headers.get('X-API-Key') or bearer
    
    if not api_key:
        return jsonify({"error": "Missing API Key"}), 401

    if not r:
        return jsonify({"error": "Redis not available"}), 500

    data = r.get(f"apikey:{api_key}")
    if data:
        return jsonify(json.loads(data))
    
    return jsonify({"error": "Invalid or expired key"}), 404
