"""
Truth Engine — /api/truth

Independently queries 2+ live market data providers for the same symbol
(Tradier, Alpaca, Polygon — the same providers data_providers.py already
talks to in production) and returns a consensus price with a real variance
figure computed across whichever providers actually responded.

No hardcoded prices, no simulated consensus. If fewer than 2 providers
respond, this returns a single-source result and says so explicitly in
`consensus_method` — it does not fabricate a second opinion. If zero
providers respond, it returns 503, per the repo's "no demo data" rule.

Every response is HMAC-SHA256 signed with PROOF402_TOKEN_SECRET (the same
secret already used to sign 402Proof payment tokens) so a caller can verify
the payload wasn't altered after this server produced it. This does not
prove the underlying market price is correct — no signature can — it proves
this server is the one that computed this exact consensus at this exact time.
"""
import os
import time
import hmac
import hashlib
import json

from flask import Blueprint, jsonify, request

from core.legacy import get_service
from proof402_integration import dual_payment

truth_bp = Blueprint('truth_bp', __name__)

# Path param route (/api/truth/verify/<symbol>) so this can't be a static key
# in proof402_integration.ENDPOINTS — same reason iam_bp.py passes its own
# rlusd_endpoint_id explicitly to dual_payment() instead of relying on the
# path-keyed lookup. Also registered in proof402_integration._PAYMENT_PRICES
# (for Discord payment alerts) and mirrored in mcp_bp.py's tool registry.
TRUTH_ENDPOINT_ID = "d20a9662-7a64-4b71-8efa-23b72dc994f3"  # 0.02 RLUSD

_TRUTH_SECRET = os.getenv('PROOF402_TOKEN_SECRET', '')


def _sign(payload: dict) -> str:
    """HMAC-SHA256 over canonical JSON. Returns '' if no secret configured
    (caller must treat unsigned responses as unverifiable, not invalid)."""
    if not _TRUTH_SECRET:
        return ''
    canonical = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()
    return hmac.new(_TRUTH_SECRET.encode(), canonical, hashlib.sha256).hexdigest()


def _query_providers(dm, symbol: str) -> list:
    """Query each provider independently (not the DataManager fallback chain,
    which stops at the first hit) so we get real multi-source agreement/
    disagreement instead of a single price relabeled three ways."""
    readings = []

    if dm.tradier.available:
        try:
            q = dm.tradier.get_quotes([symbol]).get(symbol)
            if q and q.get('price'):
                readings.append({'source': 'tradier', 'price': q['price'], 'timestamp': time.time()})
        except Exception:
            pass

    if dm.alpaca.available:
        try:
            q = dm.alpaca.get_snapshots([symbol]).get(symbol)
            if q and q.get('price'):
                readings.append({'source': 'alpaca', 'price': q['price'], 'timestamp': time.time()})
        except Exception:
            pass

    if dm.polygon.available:
        try:
            q = dm.polygon.get_quotes_batch([symbol]).get(symbol)
            if q and q.get('price'):
                readings.append({'source': 'polygon', 'price': q['price'], 'timestamp': time.time()})
        except Exception:
            pass

    return readings


@truth_bp.route('/verify/<symbol>', methods=['GET'])
@dual_payment(
    price_usdc="0.02",
    description=(
        "Truth Engine — live multi-provider price consensus with a real "
        "measured variance/confidence score and an HMAC-SHA256 proof hash. "
        "Not a single relabeled quote: queries Tradier, Alpaca, and Polygon "
        "independently and reports actual agreement between them."
    ),
    rlusd_endpoint_id=TRUTH_ENDPOINT_ID,
)
def verify(symbol: str):
    symbol = symbol.upper().strip()
    if not symbol.isalnum():
        return jsonify({'error': 'ERR_INVALID_SYMBOL', 'message': 'Symbol must be alphanumeric'}), 400

    dm = get_service('dm')
    if dm is None:
        return jsonify({'error': 'ERR_SERVICE_UNAVAILABLE', 'message': 'DataManager not initialized'}), 503

    readings = _query_providers(dm, symbol)

    if not readings:
        return jsonify({
            'error': 'ERR_NO_LIVE_DATA',
            'message': f'No provider returned live data for {symbol}. Not returning a fabricated price.',
        }), 503

    prices = [r['price'] for r in readings]
    mean_price = sum(prices) / len(prices)

    if len(readings) >= 2:
        variance = sum((p - mean_price) ** 2 for p in prices) / len(prices)
        spread_pct = (max(prices) - min(prices)) / mean_price * 100 if mean_price else 0
        consensus_method = f'{len(readings)}-source-mean'
        # Confidence degrades as sources disagree; this is a real function of
        # measured spread, not a fixed number.
        confidence = round(max(0.0, 1.0 - (spread_pct / 5.0)), 4)
    else:
        variance = 0.0
        spread_pct = 0.0
        consensus_method = 'single-source-unverified'
        confidence = 0.5  # explicitly marked down — no second source to confirm

    body = {
        'symbol': symbol,
        'consensus_price': round(mean_price, 4),
        'consensus_method': consensus_method,
        'sources': readings,
        'source_count': len(readings),
        'variance': round(variance, 6),
        'spread_pct': round(spread_pct, 4),
        'confidence': confidence,
        'verified_at': time.time(),
    }
    body['proof_hash'] = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(',', ':')).encode()
    ).hexdigest()
    signature = _sign(body)

    return jsonify({
        **body,
        'signature': signature,
        'signature_algo': 'HMAC-SHA256' if signature else None,
        'signature_note': (
            'Verifiable with PROOF402_TOKEN_SECRET.' if signature
            else 'PROOF402_TOKEN_SECRET not configured on this server — response is unsigned.'
        ),
    })


@truth_bp.route('/providers', methods=['GET'])
def providers():
    """
    Free, unpaid — which live sources are actually configured right now, plus
    the per-tier breakdown of the most recent universe discovery run. A key can
    be configured (true below) while its API calls still fail — last_discovery
    shows what each tier actually contributed and the last error if it didn't.
    """
    dm = get_service('dm')
    if dm is None:
        return jsonify({'error': 'ERR_SERVICE_UNAVAILABLE'}), 503
    status = dm.provider_status()
    status['last_discovery'] = getattr(dm, 'last_discovery', None)
    return jsonify(status)
