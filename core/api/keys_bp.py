import os
import json
import logging
import uuid
import secrets
from flask import Blueprint, request, jsonify, redirect, render_template_string
import stripe
import redis

from core.stripe_idempotency import already_processed

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
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SqueezeOS | Institutional API</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;500;800&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg: #050505;
            --surface: rgba(20, 20, 20, 0.6);
            --border: rgba(255, 255, 255, 0.1);
            --accent: #00FF88;
            --accent-glow: rgba(0, 255, 136, 0.3);
            --text-primary: #FFFFFF;
            --text-secondary: #888888;
        }
        body { 
            font-family: 'Inter', sans-serif; 
            background: var(--bg); 
            color: var(--text-primary); 
            margin: 0; 
            padding: 0; 
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            align-items: center;
            background-image: radial-gradient(circle at 50% 0%, rgba(0, 255, 136, 0.05) 0%, transparent 50%);
        }
        header {
            text-align: center;
            margin: 80px 0 40px 0;
            animation: fadeIn 1s ease-out;
        }
        h1 {
            font-size: 3rem;
            font-weight: 800;
            margin: 0;
            letter-spacing: -1px;
            background: linear-gradient(to right, #fff, #888);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .subtitle {
            color: var(--accent);
            font-size: 1.1rem;
            text-transform: uppercase;
            letter-spacing: 2px;
            margin-top: 10px;
        }
        .grid { 
            display: flex; 
            justify-content: center; 
            gap: 30px; 
            flex-wrap: wrap;
            max-width: 1200px;
            padding: 20px;
        }
        .card { 
            background: var(--surface);
            backdrop-filter: blur(10px);
            padding: 40px 30px; 
            border-radius: 16px; 
            width: 320px; 
            border: 1px solid var(--border); 
            transition: all 0.3s ease;
            position: relative;
            overflow: hidden;
            text-align: left;
        }
        .card:hover {
            transform: translateY(-5px);
            border-color: rgba(255,255,255,0.3);
            box-shadow: 0 10px 30px rgba(0,0,0,0.5);
        }
        .card::before {
            content: '';
            position: absolute;
            top: 0; left: 0; right: 0; height: 3px;
            background: linear-gradient(90deg, transparent, var(--accent), transparent);
            opacity: 0;
            transition: opacity 0.3s ease;
        }
        .card:hover::before { opacity: 1; }
        .card-header {
            font-size: 1.5rem;
            font-weight: 500;
            margin-bottom: 15px;
        }
        .price { 
            font-size: 2.5rem; 
            font-weight: 800;
            margin: 20px 0; 
            color: #fff; 
        }
        .price span {
            font-size: 1rem;
            color: var(--text-secondary);
            font-weight: 300;
        }
        .features {
            list-style: none;
            padding: 0;
            margin: 30px 0;
            color: var(--text-secondary);
            font-size: 0.95rem;
        }
        .features li {
            margin-bottom: 12px;
            display: flex;
            align-items: center;
        }
        .features li::before {
            content: '✓';
            color: var(--accent);
            margin-right: 10px;
            font-weight: bold;
        }
        .btn { 
            display: block; 
            text-align: center;
            background: transparent; 
            color: #fff; 
            text-decoration: none; 
            padding: 15px; 
            border-radius: 8px; 
            font-weight: 500; 
            border: 1px solid var(--border);
            transition: all 0.2s ease;
        }
        .btn:hover { 
            background: rgba(255,255,255,0.05);
            border-color: #fff;
        }
        .btn.primary {
            background: var(--text-primary);
            color: #000;
            border: none;
        }
        .btn.primary:hover {
            background: var(--accent);
            box-shadow: 0 0 20px var(--accent-glow);
        }
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(20px); }
            to { opacity: 1; transform: translateY(0); }
        }
    </style>
</head>
<body>
    <header>
        <h1>SqueezeOS API</h1>
        <div class="subtitle">Institutional Grade Data Endpoints</div>
    </header>
    <div class="grid">
        <div class="card">
            <div class="card-header">Dev Pack</div>
            <div class="price">$9<span> / one-time</span></div>
            <ul class="features">
                <li>Perfect for MVP testing</li>
                <li>Full Stigmergy access</li>
                <li>Standard latency</li>
            </ul>
            <a class="btn" href="/api/keys/checkout?plan=dev">Buy Now</a>
        </div>
        <div class="card" style="border-color: var(--accent);">
            <div class="card-header">Starter</div>
            <div class="price">$29<span> / mo</span></div>
            <ul class="features">
                <li>Solo algorithmic traders</li>
                <li>Real-time flow streams</li>
                <li>Priority queueing</li>
            </ul>
            <a class="btn primary" href="/api/keys/checkout?plan=starter">Subscribe</a>
        </div>
        <div class="card">
            <div class="card-header">Institutional</div>
            <div class="price">$79<span> / mo</span></div>
            <ul class="features">
                <li>Hedge funds & dark pools</li>
                <li>Uncapped volume</li>
                <li>Direct server interconnect</li>
            </ul>
            <a class="btn" href="/api/keys/checkout?plan=pro">Subscribe</a>
        </div>
    </div>
</body>
</html>
"""

SUCCESS_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>SqueezeOS | Key Provisioned</title>
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&family=Inter:wght@300;500;800&display=swap" rel="stylesheet">
    <style>
        body { 
            font-family: 'Inter', sans-serif; 
            background: #050505; 
            color: #fff; 
            padding: 0; 
            margin: 0;
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 100vh;
        }
        .container {
            background: rgba(20, 20, 20, 0.8);
            border: 1px solid rgba(0, 255, 136, 0.3);
            border-radius: 16px;
            padding: 50px;
            text-align: center;
            max-width: 600px;
            box-shadow: 0 0 50px rgba(0, 255, 136, 0.05);
            animation: pulse 2s infinite;
        }
        h1 {
            color: #00FF88;
            margin-top: 0;
            font-weight: 800;
        }
        p {
            color: #888;
            font-size: 1.1rem;
            margin-bottom: 40px;
        }
        .key-box { 
            background: #000; 
            padding: 20px; 
            border: 1px dashed #555; 
            border-radius: 8px;
            display: inline-block; 
            font-size: 1.2rem; 
            font-family: 'JetBrains Mono', monospace;
            color: #00FF88;
            letter-spacing: 1px;
            margin-bottom: 30px;
        }
        .code-block {
            background: #111;
            padding: 15px;
            border-radius: 6px;
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.9rem;
            color: #aaa;
            text-align: left;
        }
        .code-block span { color: #fff; }
        @keyframes pulse {
            0% { box-shadow: 0 0 30px rgba(0, 255, 136, 0.02); }
            50% { box-shadow: 0 0 50px rgba(0, 255, 136, 0.1); }
            100% { box-shadow: 0 0 30px rgba(0, 255, 136, 0.02); }
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>ACCESS GRANTED</h1>
        <p>Your SqueezeOS API credentials have been provisioned.</p>
        <div class="key-box">{{ api_key }}</div>
        
        <div class="code-block">
            # Pass via Headers<br>
            <span>X-API-KEY</span>: {{ api_key }}<br><br>
            # Or Bearer Auth<br>
            <span>Authorization</span>: Bearer {{ api_key }}
        </div>
    </div>
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
        logger.error("Stripe checkout session error", exc_info=True)
        return jsonify({"error": "internal error creating checkout session"}), 500


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
        logger.error("Stripe session retrieval error", exc_info=True)
        return jsonify({"error": "internal error retrieving session"}), 500


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

    if already_processed(r, event.get('id')):
        return jsonify(success=True)

    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        api_key = session.get('client_reference_id')
        customer_email = session.get('customer_details', {}).get('email', 'unknown')
        customer_id = session.get('customer')
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
            # Reverse index by Stripe customer ID so a later subscription.deleted
            # event (which only carries the customer ID, not client_reference_id)
            # can find and revoke this key.
            if customer_id:
                r.set(f"customer:{customer_id}", api_key)
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
        subscription = event['data']['object']
        customer_id = subscription.get('customer')
        if customer_id and r:
            api_key = r.get(f"customer:{customer_id}")
            if api_key:
                r.delete(f"apikey:{api_key}")
                r.delete(f"customer:{customer_id}")
                logger.info(f"Revoked API key for cancelled customer {customer_id}")
            else:
                logger.warning(f"No API key found to revoke for cancelled customer {customer_id}")
        else:
            logger.warning("subscription cancellation event missing customer id or Redis unavailable")

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
