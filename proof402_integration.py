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
    '/api/council':          '12a0e7a1-6812-4c3f-aa24-de6e3bc12b5a',  # 0.10 RLUSD
    '/api/scan':             '160cf28d-b364-44eb-adbd-2489c5cc2cf8',  # 0.05 RLUSD
    '/api/options':          'c951a374-2424-4064-ab80-35afe8053d29',  # 0.05 RLUSD
    '/api/iwm':              '60f48ce0-6002-4385-9b60-03a0d2bbebab',  # 0.03 RLUSD
    '/api/marketplace/read': 'd1a2b3c4-e001-4c3f-aa24-de6e3bc12b5a',  # 0.02 RLUSD
}


def _verify_token_local(token: str) -> dict:
    """
    Pure CPU verification — zero network, sub-millisecond.
    Mirrors Go server invoice.VerifyToken exactly.
    Returns: {valid, endpoint_id, wallet, invoice_id} on success
             {valid: False, reason: ERR_*}             on failure
    """
    if not PROOF402_SECRET:
        return {'valid': False, 'reason': 'ERR_SECRET_NOT_CONFIGURED'}
    try:
        dot = token.rfind('.')
        if dot < 0:
            return {'valid': False, 'reason': 'ERR_TOKEN_MALFORMED'}
        encoded, sig = token[:dot], token[dot + 1:]

        expected = hmac.new(
            PROOF402_SECRET.encode(), encoded.encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return {'valid': False, 'reason': 'ERR_TOKEN_INVALID'}

        padding = 4 - len(encoded) % 4
        payload = json.loads(
            base64.urlsafe_b64decode(encoded + '=' * padding)
        )
        if int(time.time()) > payload['exp']:
            return {'valid': False, 'reason': 'ERR_TOKEN_EXPIRED', 'expired_at': payload['exp']}

        return {
            'valid':       True,
            'endpoint_id': payload.get('eid'),
            'wallet':      payload.get('wlt', ''),
            'invoice_id':  payload.get('iid'),
        }
    except Exception:
        return {'valid': False, 'reason': 'ERR_TOKEN_MALFORMED'}


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


import logging as _logging
from flask import g as _g

# ── Structured error codes ────────────────────────────────────────────────────
_ERROR_MESSAGES = {
    'ERR_PAYMENT_REQUIRED':     'Payment required — send RLUSD on XRPL to access this endpoint.',
    'ERR_TOKEN_INVALID':        'Token signature verification failed. Token may be tampered or from wrong server.',
    'ERR_TOKEN_EXPIRED':        'Token has expired. Tokens are single-use with a short TTL.',
    'ERR_TOKEN_MALFORMED':      'Token structure is invalid. Expected format: base64payload.hmac_signature',
    'ERR_ENDPOINT_MISMATCH':    'Token was issued for a different endpoint. Each invoice is endpoint-specific.',
    'ERR_WALLET_MISMATCH':      'Token was issued to a different wallet. Tokens are non-transferable.',
    'ERR_SECRET_NOT_CONFIGURED':'Server-side token secret not configured. Contact operator.',
}

# ── Wallet binding enforcement ────────────────────────────────────────────────
# Set ENFORCE_WALLET_BINDING=true in env to reject tokens used by a different
# wallet than the one that paid. Defaults to soft-check (logs mismatch only)
# so existing agents aren't broken during the v2 token rollout.
_ENFORCE_WALLET_BINDING = os.getenv('ENFORCE_WALLET_BINDING', 'false').lower() == 'true'


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

    Wallet binding (v2 tokens):
        Tokens issued after the v2 upgrade encode the paying wallet as 'wlt'.
        If the request also sends X-Agent-Wallet, the decorator verifies they
        match. Set ENFORCE_WALLET_BINDING=true to hard-reject mismatches.
        Pre-v2 tokens (no wlt field) always pass — backward compatible.

    Flask g context (available inside decorated route):
        g.proof402_wallet      — paying wallet address (str, may be empty)
        g.proof402_endpoint_id — verified endpoint UUID
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        path = request.path
        endpoint_id = ENDPOINTS.get(path)
        if not endpoint_id:
            return f(*args, **kwargs)

        token = request.headers.get('X-Payment-Token')
        if token:
            result = _verify_token_local(token)
            if result['valid']:
                if result.get('endpoint_id') != endpoint_id:
                    return jsonify({
                        'error':   'ERR_ENDPOINT_MISMATCH',
                        'message': 'Token was issued for a different endpoint.',
                        'remedy':  f'Obtain a new invoice for {path} at {PROOF402_SERVER}/v1/invoice',
                    }), 401

                token_wallet   = result.get('wallet', '')
                request_wallet = request.headers.get('X-Agent-Wallet', '')

                if token_wallet and request_wallet and token_wallet != request_wallet:
                    _logging.warning(
                        '[402Proof] wallet mismatch — token_wlt=%s request_wlt=%s path=%s',
                        token_wallet, request_wallet, path
                    )
                    if _ENFORCE_WALLET_BINDING:
                        return jsonify({
                            'error':   'ERR_WALLET_MISMATCH',
                            'message': 'Token was issued to a different wallet. Tokens are non-transferable.',
                            'remedy':  'Pay with your own wallet. GET /v1/invoice to start a new payment.',
                        }), 401

                _g.proof402_wallet      = token_wallet
                _g.proof402_endpoint_id = endpoint_id
                return f(*args, **kwargs)

            # Token present but invalid — give the agent the specific reason
            reason = result.get('reason', 'ERR_TOKEN_INVALID')
            resp = {'error': reason, 'message': _ERROR_MESSAGES.get(reason, 'Token rejected.')}
            if reason == 'ERR_TOKEN_EXPIRED':
                resp['expired_at'] = result.get('expired_at')
                resp['remedy'] = f'Token expired. Obtain a fresh invoice at {PROOF402_SERVER}/v1/invoice'
            else:
                resp['remedy'] = f'Obtain a valid token: pay at {PROOF402_SERVER}/v1/invoice, then POST /v1/verify'
            return jsonify(resp), 401

        # No token at all — issue invoice and return 402
        try:
            inv = _issue_invoice(endpoint_id)
        except Exception as e:
            _logging.warning(f'[402Proof] invoice fetch failed: {e} — passing through')
            return f(*args, **kwargs)

        return jsonify({
            'error':   'ERR_PAYMENT_REQUIRED',
            'message': f'This endpoint costs {inv.get("amount", "?")} {inv.get("asset", "RLUSD")}. Pay on XRPL to continue.',
            'invoice': inv,
            'remedy': {
                'step1': f"Send {inv['amount']} {inv['asset']} on XRPL to {inv['pay_to']}",
                'step2': f"Include MemoData: {inv['memo_hex']} in your XRPL payment transaction",
                'step3': f"POST {PROOF402_SERVER}/v1/verify with invoice_id, tx_hash, agent_wallet",
                'step4': 'Retry this request with header: X-Payment-Token: <token>',
            },
            'free_preview': f'/api/preview{path.replace("/api", "", 1)}',
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
