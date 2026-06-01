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
import threading
from functools import wraps
from flask import request, jsonify

# ── Discord payment notification (lazy singleton) ─────────────────────────────
_discord_alerts = None

def _get_discord():
    global _discord_alerts
    if _discord_alerts is None:
        try:
            from discord_alerts import DiscordAlerts
            _discord_alerts = DiscordAlerts()
        except Exception:
            pass
    return _discord_alerts

# ── Endpoint prices (for Discord notification) ────────────────────────────────
_PAYMENT_PRICES = {
    '/api/council':           0.10,
    '/api/scan':              0.05,
    '/api/options':           0.05,
    '/api/iwm':               0.03,
    '/api/marketplace/read':  0.02,
}

def _fire_payment_discord(wallet: str, path: str, tier: int) -> None:
    """Non-blocking: fire Discord payment alert in a daemon thread."""
    price = _PAYMENT_PRICES.get(path, 0.0)
    if not price:
        return
    da = _get_discord()
    if not da:
        return
    threading.Thread(
        target=da.fire_payment_alert,
        args=(wallet, path, price, tier),
        daemon=True,
    ).start()

# ── Config (set these in your .env / environment) ────────────────────────────
PROOF402_SERVER     = os.getenv('PROOF402_SERVER_URL', 'https://four02proof.onrender.com')
PROOF402_SECRET     = os.getenv('PROOF402_TOKEN_SECRET', '')  # same as Render TOKEN_SECRET
OWNER_API_KEY       = os.getenv('OWNER_API_KEY', '')          # set this to bypass payment as owner

# ── Endpoint IDs (registered in 402Proof dashboard) ──────────────────────────
ENDPOINTS = {
    '/api/council':          '12a0e7a1-6812-4c3f-aa24-de6e3bc12b5a',  # 0.10 RLUSD
    '/api/scan':             '160cf28d-b364-44eb-adbd-2489c5cc2cf8',  # 0.05 RLUSD
    '/api/options':          'c951a374-2424-4064-ab80-35afe8053d29',  # 0.05 RLUSD
    '/api/iwm':              '60f48ce0-6002-4385-9b60-03a0d2bbebab',  # 0.03 RLUSD
    '/api/marketplace/read': 'd1a2b3c4-e001-4c3f-aa24-de6e3bc12b5a',  # 0.02 RLUSD
    # Oracle routes use path params so payment is verified inline in oracle_data_bp.py:
    # '/api/oracle/latest/<feed>'  → ORACLE_READ_ENDPOINT_ID   e7f8a9b0-...  0.02 RLUSD
    # '/api/oracle/query'          → ORACLE_READ_ENDPOINT_ID   e7f8a9b0-...  0.02 RLUSD
    # '/api/oracle/stream'         → ORACLE_STREAM_ENDPOINT_ID f8a9b0c1-...  0.05 RLUSD
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
            'tier':        payload.get('tier', None),   # ECHOLOCK tier if 402Proof embeds it
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
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


import logging as _logging
from flask import g as _g

# ── ECHOLOCK-402 behavioral tier engine ──────────────────────────────────────
try:
    from core import echolock as _echolock
    _ECHOLOCK = True
except ImportError:
    _echolock = None  # type: ignore[assignment]
    _ECHOLOCK = False

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


def verify_token_for_echolock(token: str) -> dict:
    """Public shim: verify token and return {valid, wallet, tier} for ECHOLOCK use."""
    r = _verify_token_local(token)
    return {'valid': r.get('valid', False), 'wallet': r.get('wallet', ''), 'tier': r.get('tier')}


def _apply_entropy(result, tier: int, seed: str):
    """Compress a successful Flask JSON response to the depth earned by tier."""
    if not _ECHOLOCK or tier >= 4:
        return result
    try:
        # Only intercept plain 200 Response objects (all premium routes return jsonify(...))
        if hasattr(result, 'get_data') and getattr(result, 'status_code', None) == 200:
            import json as _j
            raw = _j.loads(result.get_data(as_text=True))
            compressed = _echolock.compress(raw, tier, seed)
            return jsonify(compressed)
    except Exception:
        pass
    return result


def require_payment(f):
    """
    Flask decorator — gates any route behind payment.

    Auth priority (checked in order):
      1. X-Owner-Key header  — server owner bypass (OWNER_API_KEY env var)
      2. Authorization: Bearer sml_live_... OR X-API-Key: sml_live_...
         → SML API key (Stripe-issued, consumed from quota)
      3. X-Payment-Token header → x402 RLUSD per-call token (legacy/agent flow)
      4. No token → HTTP 402 + invoice

    Flask g context (available inside decorated route):
        g.proof402_wallet      — paying wallet or 'APIKEY:<plan>'
        g.proof402_endpoint_id — verified endpoint UUID
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        path = request.path
        endpoint_id = ENDPOINTS.get(path)
        if not endpoint_id:
            return f(*args, **kwargs)

        # ── Check 1: Owner bypass ─────────────────────────────────────────────
        if OWNER_API_KEY and request.headers.get('X-Owner-Key') == OWNER_API_KEY:
            _g.proof402_wallet      = 'OWNER'
            _g.proof402_endpoint_id = endpoint_id
            return f(*args, **kwargs)

        # ── Check 2: SML API Key (Stripe-issued) ──────────────────────────────
        _raw_auth = request.headers.get('Authorization', '')
        _api_key  = (
            _raw_auth.removeprefix('Bearer ').strip()
            if _raw_auth.startswith('Bearer sml_live_')
            else request.headers.get('X-API-Key', '')
        )
        if _api_key and _api_key.startswith('sml_live_'):
            try:
                from core.apikey_store import consume_call, validate_key
                if validate_key(_api_key):
                    if consume_call(_api_key):
                        _g.proof402_wallet      = f'APIKEY:{_api_key[:16]}...'
                        _g.proof402_endpoint_id = endpoint_id
                        return f(*args, **kwargs)
                    else:
                        return jsonify({
                            'error':   'ERR_QUOTA_EXHAUSTED',
                            'message': 'API key quota exhausted.',
                            'remedy':  'Upgrade your plan at https://squeezeos-api.onrender.com/pricing',
                        }), 402
                else:
                    return jsonify({
                        'error':   'ERR_API_KEY_INVALID',
                        'message': 'Invalid, inactive, or unknown API key.',
                        'remedy':  'Get a key at https://squeezeos-api.onrender.com/pricing',
                    }), 401
            except ImportError:
                pass  # apikey_store not loaded — fall through to x402

        # ── Check 3: x402 payment token ───────────────────────────────────────
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

                # ECHOLOCK: record access and derive behavioral tier
                if _ECHOLOCK:
                    _echolock.record_access(token_wallet, path)
                    import hashlib as _hl
                    _tier = _echolock.get_tier(token_wallet, jwt_tier=result.get('tier'))
                    _seed = _hl.sha256(f'{token_wallet}:{path}'.encode()).hexdigest()[:32]
                    _g.echolock_tier = _tier
                    _g.echolock_seed = _seed
                    _fire_payment_discord(token_wallet, path, _tier)
                    return _apply_entropy(f(*args, **kwargs), _tier, _seed)

                _fire_payment_discord(token_wallet, path, 2)
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
