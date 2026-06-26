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
    '/api/741macro':          0.04,
    '/api/signals/741':        0.02,
    '/api/signals/365':        0.03,
    '/api/signals/triplelock': 0.05,
    '/api/signals/full':       0.10,
    '/api/cascade/signal':     0.25,
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
    '/api/741macro':         'f3a7c891-2d54-4b8e-9a1f-6c3d8e5f7b2a',  # 0.04 RLUSD
    # Sovereign Signal Suite — labels only, no raw values
    '/api/signals/741':        'e5f6a7b8-c9d0-1234-5678-901234567890',  # 0.02 RLUSD
    '/api/signals/365':        'f6a7b8c9-d0e1-2345-6789-012345678901',  # 0.03 RLUSD
    '/api/signals/triplelock': 'a7b8c9d0-e1f2-3456-789a-123456789012',  # 0.05 RLUSD
    '/api/signals/full':       'b8c9d0e1-f2a3-4567-89ab-234567890123',  # 0.10 RLUSD
    # CASCADE ACCUMULATOR — execution tier
    '/api/cascade/signal':     'c4sc4de1-8f2a-4b3e-9c1d-5e6f7a8b9c0d',  # 0.25 RLUSD
    # Oracle routes use path params so payment is verified inline in oracle_data_bp.py:
    # '/api/oracle/latest/<feed>'  → ORACLE_READ_ENDPOINT_ID   e7f8a9b0-...  0.02 RLUSD
    # '/api/oracle/query'          → ORACLE_READ_ENDPOINT_ID   e7f8a9b0-...  0.02 RLUSD
    # '/api/oracle/stream'         → ORACLE_STREAM_ENDPOINT_ID f8a9b0c1-...  0.05 RLUSD
}


_FREE_PREVIEW_BY_PATH = {
    '/api/council':          '/api/demo/council',
    '/api/scan':             '/api/preview/IWM',
    '/api/options':          '/api/preview/IWM',
    '/api/iwm':              '/api/demo/council',
    '/api/marketplace/read': '/api/marketplace',
    '/api/741macro':         '/api/preview/IWM',
    '/api/signals/741':        '/api/signals/info',
    '/api/signals/365':        '/api/signals/info',
    '/api/signals/triplelock': '/api/signals/info',
    '/api/signals/full':       '/api/signals/info',
    '/api/cascade/signal':     '/api/cascade/info',
}


def _free_preview_for(path: str) -> str:
    """Return a real free-tier URL agents can hit without paying, or empty string."""
    return _FREE_PREVIEW_BY_PATH.get(path, '')


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

        # API Key bypass (for human devs who paid via Stripe)
        # Accepts standard 'Authorization: Bearer <key>' or 'X-API-Key: <key>' or 'X-Owner-Key: <key>'
        auth_header = request.headers.get('Authorization', '')
        bearer_key = auth_header.split('Bearer ')[-1].strip() if 'Bearer ' in auth_header else ''
        passed_key = request.headers.get('X-Owner-Key') or request.headers.get('X-API-Key') or bearer_key
        
        # Load single master keys plus any dynamically provisioned agent keys (comma-separated)
        agent_keys_str = os.getenv('AGENT_API_KEYS', '')
        agent_keys = [k.strip() for k in agent_keys_str.split(',') if k.strip()]
        valid_keys = [k for k in [os.getenv('OPERATOR_API_KEY'), OWNER_API_KEY] if k] + agent_keys
        
        if passed_key and passed_key in valid_keys:
            _g.proof402_wallet      = 'API_KEY_USER'
            _g.proof402_endpoint_id = endpoint_id
            return f(*args, **kwargs)

        # Check automated Stripe API Keys in Redis
        if passed_key and passed_key.startswith('sml_live_'):
            try:
                import redis, json
                redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
                r = redis.from_url(redis_url, decode_responses=True)
                data = r.get(f"apikey:{passed_key}")
                if data:
                    key_data = json.loads(data)
                    if key_data.get('active'):
                        _g.proof402_wallet      = f'STRIPE_USER'
                        _g.proof402_endpoint_id = endpoint_id
                        return f(*args, **kwargs)
            except Exception as e:
                _logging.error(f"Redis API Key lookup failed: {e}")

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
                    # Mask wallet addresses in logs: show first-6...last-4 only
                    _mask = lambda w: f"{w[:6]}...{w[-4:]}" if len(w) > 10 else "***"
                    _logging.warning(
                        '[402Proof] wallet mismatch — token_wlt=%s request_wlt=%s path=%s',
                        _mask(token_wallet), _mask(request_wallet), path
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
            _logging.error(f'[402Proof] invoice fetch failed: {e} — payment gate CLOSED (503)')
            return jsonify({
                'error': 'ERR_PAYMENT_GATE_UNAVAILABLE',
                'message': 'Payment gateway temporarily unavailable. Cannot issue invoice. Retry later.',
                'retry_after': 30,
            }), 503

        _base = os.getenv('SQUEEZEOS_BASE_URL', 'https://squeezeos-api.onrender.com')
        free_preview = _free_preview_for(path)
        body = {
            # ── x402 standard fields (Coinbase CDP / AP2 compatible) ─────────
            'x402Version': 1,
            'error': 'X402',
            'accepts': [{
                'scheme':            'exact',
                'network':           'xrpl',
                'maxAmountRequired': str(inv.get('amount', '0')),
                'asset':             inv.get('asset', 'RLUSD'),
                'resource':          f"{_base}{path}",
                'description':       f"SqueezeOS — {path.strip('/').replace('/', ' ').title()}",
                'mimeType':          'application/json',
                'payTo':             inv.get('pay_to', ''),
                'maxTimeoutSeconds': 300,
                'extra': {
                    'memo_hex':   inv.get('memo_hex', ''),
                    'invoice_id': inv.get('invoice_id', ''),
                    'verify_at':  f"{PROOF402_SERVER}/v1/verify",
                },
            }],
            # ── SML-native fields (backward compatible) ───────────────────────
            'message': f'This endpoint costs {inv.get("amount", "?")} {inv.get("asset", "RLUSD")}. Pay on XRPL to continue.',
            'invoice': inv,
            'remedy': {
                'step1': f"Send {inv['amount']} {inv['asset']} on XRPL to {inv['pay_to']}",
                'step2': f"Include MemoData: {inv['memo_hex']} in your XRPL payment transaction",
                'step3': f"POST {PROOF402_SERVER}/v1/verify with invoice_id, tx_hash, agent_wallet",
                'step4': 'Retry this request with header: X-Payment-Token: <token>',
            },
            # ── Agent discovery (new agents that hit a premium endpoint first) ─
            'discovery': {
                'agents_json': f"{_base}/.well-known/agents.json",
                'mcp_json':    f"{_base}/.well-known/mcp.json",
                'mcp_endpoint': f"{_base}/mcp",
                'llms_txt':    f"{_base}/llms.txt",
                'free_endpoints': [
                    f"{_base}/api/preview/IWM",
                    f"{_base}/api/history/IWM",
                    f"{_base}/api/status",
                    f"{_base}/api/demo",
                ],
                'note': 'Try the free endpoints above before purchasing. They require no payment or auth.',
            },
        }
        if free_preview:
            body['free_preview'] = free_preview
        return jsonify(body), 402

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
#   PROOF402_TOKEN_SECRET=<set this to the value configured on the 402Proof server; rotate with `openssl rand -hex 32` and apply the SAME value on both services — never commit the real secret>

#
# NOTE: @require_payment fails OPEN — if 402Proof is unreachable, the route
# still serves so SqueezeOS never goes down because of the payment layer.
