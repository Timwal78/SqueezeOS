"""
402Proof middleware integration for api_v2.py (SqueezeOS V2).
Add this to your Flask app to gate premium endpoints behind RLUSD payment.
"""

import os
import hmac
import hashlib
import base64
import json
import time
from functools import wraps
from flask import request, jsonify

# ── Config (set these in your .env / environment) ────────────────────────────
PROOF402_SERVER     = os.getenv('PROOF402_SERVER_URL', 'https://four02proof.onrender.com')
PROOF402_SECRET     = os.getenv('PROOF402_TOKEN_SECRET', '')  # same as Render TOKEN_SECRET

# ── Endpoint IDs (registered in 402Proof dashboard) ──────────────────────────
ENDPOINTS = {
    '/api/council': '12a0e7a1-6812-4c3f-aa24-de6e3bc12b5a',  # 0.10 RLUSD
    '/api/scan':    '160cf28d-b364-44eb-adbd-2489c5cc2cf8',  # 0.05 RLUSD
    '/api/options': 'c951a374-2424-4064-ab80-35afe8053d29',  # 0.05 RLUSD
    '/api/iwm':     '60f48ce0-6002-4385-9b60-03a0d2bbebab',  # 0.03 RLUSD
}


def _verify_token_local(token: str) -> dict:
    """
    Pure CPU verification — zero network, sub-millisecond.
    Mirrors Go server invoice.VerifyToken exactly.
    """
    if not PROOF402_SECRET:
        return {'valid': False}
    try:
        dot = token.rfind('.')
        if dot < 0:
            return {'valid': False}
        encoded, sig = token[:dot], token[dot + 1:]

        expected = hmac.new(
            PROOF402_SECRET.encode(), encoded.encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return {'valid': False}

        padding = 4 - len(encoded) % 4
        payload = json.loads(
            base64.urlsafe_b64decode(encoded + '=' * padding)
        )
        if int(time.time()) > payload['exp']:
            return {'valid': False}

        return {
            'valid':       True,
            'endpoint_id': payload.get('eid'),
            'wallet':      payload.get('wlt', ''),  # bound paying wallet (empty on pre-v2 tokens)
            'invoice_id':  payload.get('iid'),
        }
    except Exception:
        return {'valid': False}


def _issue_invoice(endpoint_id: str) -> dict:
    """Request a fresh payment invoice from 402Proof server."""
    import urllib.request
    data = json.dumps({'endpoint_id': endpoint_id}).encode()
    req = urllib.request.Request(
        f'{PROOF402_SERVER}/v1/invoice',
        data=data,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    with urllib.request.urlopen(req, timeout=8) as resp:
        return json.loads(resp.read())


def require_payment(f):
    """
    Flask decorator — gates any route behind 402Proof RLUSD payment.

    Usage:
        @app.route('/api/council', methods=['POST'])
        @require_payment
        def council():
            ...

    Agent flow:
        1. Agent hits endpoint → gets 402 + invoice
        2. Agent pays RLUSD on XRPL with memo_hex
        3. Agent calls four02proof.onrender.com/v1/verify → gets access_token
        4. Agent retries with X-Payment-Token header → passes through
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        path = request.path
        endpoint_id = ENDPOINTS.get(path)
        if not endpoint_id:
            # No 402Proof config for this path — pass through
            return f(*args, **kwargs)

        token = request.headers.get('X-Payment-Token')
        if token:
            result = _verify_token_local(token)
            if result['valid'] and result.get('endpoint_id') == endpoint_id:
                return f(*args, **kwargs)

        # No valid token — issue invoice and return 402
        try:
            inv = _issue_invoice(endpoint_id)
        except Exception as e:
            # 402Proof unreachable — fail open so SqueezeOS stays up
            import logging
            logging.warning(f'[402Proof] invoice fetch failed: {e} — passing through')
            return f(*args, **kwargs)

        return jsonify({
            'error': 'Payment Required',
            'invoice': inv,
            'instructions': {
                'step1': f"Send {inv['amount']} {inv['asset']} on XRPL to {inv['pay_to']}",
                'step2': f"Include MemoData: {inv['memo_hex']} in your XRPL payment",
                'step3': f"POST {PROOF402_SERVER}/v1/verify with invoice_id, tx_hash, agent_wallet",
                'step4': 'Retry with header: X-Payment-Token: <token>',
            },
        }), 402

    return decorated


# ── Usage — drop into api_v2.py ───────────────────────────────────────────────
#
# from proof402_integration import require_payment
#
# @app.route('/api/council', methods=['POST'])
# @require_payment
# def council_verdict():
#     ...
#
# @app.route('/api/scan', methods=['GET','POST'])
# @require_payment
# def scan():
#     ...
#
# @app.route('/api/options', methods=['GET','POST'])
# @require_payment
# def options():
#     ...
#
# @app.route('/api/iwm', methods=['GET','POST'])
# @require_payment
# def iwm():
#     ...
#
# Add to .env on your SqueezeOS V2 machine:
#   PROOF402_SERVER_URL=https://four02proof.onrender.com
#   PROOF402_TOKEN_SECRET=0d38159d1867b684d71dc65be255782839ae894bb3b43796f129365b63dbda84
#
# NOTE: @require_payment fails OPEN — if 402Proof is unreachable, the route
# still serves so SqueezeOS never goes down because of the payment layer.
