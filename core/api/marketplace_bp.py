"""
Alpha Mesh — Agent-to-Agent Intelligence Bazaar (SqueezeOS Peer Signal Marketplace)
═══════════════════════════════════════════════════════════════════════════════════
Agents publish their own market signals; other agents pay to read them.
Zero custody — sellers keep 90% of each read fee, SqueezeOS takes 10%.

  GET  /api/marketplace                — browse listings (free)
  GET  /api/marketplace/preview/<id>   — symbol + bias + confidence (free)
  POST /api/marketplace/read           — full signal (0.02 RLUSD via x402; 90% to seller)
  POST /api/marketplace/list           — publish a signal (free to list)
  GET  /api/marketplace/balance/<wallet> — accrued seller earnings (Alpha Mesh)
  GET  /api/marketplace/leaderboard    — top sellers by sale count (free)
  DELETE /api/marketplace/<id>         — delete own listing (wallet auth)

Seller rewards (zero custody):
  Each sale → 90% of 0.02 RLUSD accrues to seller balance (Alpha Mesh)
  Each sale → seller Credit Bureau score boost (+2 pts, up to +50 lifetime)
  Top sellers featured on leaderboard
  Score 600+ → qualify for Relay Node (40% bulk discount on own buys)

Why free to list:
  Supply-side participation maximized. Revenue comes from readers, not sellers.
"""

import os
import sys
import time
import uuid
import logging
from flask import Blueprint, jsonify, request
import core.signal_history as signal_history

# proof402_integration lives at repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from proof402_integration import require_payment

logger = logging.getLogger("SqueezeOS-Marketplace")
marketplace_bp = Blueprint('marketplace', __name__)

# ── Storage ───────────────────────────────────────────────────────────────────
_listings:     dict = {}   # listing_id -> listing dict
_seller_stats: dict = {}   # wallet -> {sale_count, listing_count, revenue_rlusd}

_MAX_LISTINGS   = 500   # global cap — evict oldest on overflow
_MAX_PER_SELLER = 10    # active listings per wallet

_VALID_BIASES = frozenset({"BULLISH", "BEARISH", "NEUTRAL", "HOLD", "BUY", "SELL"})
_VALID_TYPES  = frozenset({"SQUEEZE", "OPTIONS", "BREAKOUT", "REVERSAL", "TREND", "CUSTOM"})


def _stat(wallet: str) -> dict:
    if wallet not in _seller_stats:
        _seller_stats[wallet] = {
            "sale_count": 0, "listing_count": 0, "revenue_rlusd": 0.0,
            "balance_rlusd": 0.0, "paid_out_rlusd": 0.0,
        }
    return _seller_stats[wallet]


# Alpha Mesh revenue split — seller keeps 90%, platform takes 10%
SELLER_SHARE = 0.90
READ_PRICE_RLUSD = 0.02
SELLER_CUT_RLUSD = round(READ_PRICE_RLUSD * SELLER_SHARE, 4)


# ── Browse ────────────────────────────────────────────────────────────────────

@marketplace_bp.route('', methods=['GET'])
@marketplace_bp.route('/', methods=['GET'])
def browse():
    now        = time.time()
    page       = max(1, int(request.args.get('page', 1)))
    per_page   = min(50, int(request.args.get('per_page', 20)))
    sym_filter = request.args.get('symbol', '').upper()
    bias_filter= request.args.get('bias', '').upper()

    # Expire stale listings on read
    for l in _listings.values():
        if l['active'] and now > l['expires_at']:
            l['active'] = False

    active = [
        l for l in _listings.values()
        if l['active']
        and (not sym_filter  or l['symbol'] == sym_filter)
        and (not bias_filter or l['bias']   == bias_filter)
    ]
    active.sort(key=lambda x: (-x['confidence'], -x['listed_at']))
    total  = len(active)
    start  = (page - 1) * per_page
    chunk  = active[start:start + per_page]

    return jsonify({
        "total":    total,
        "page":     page,
        "per_page": per_page,
        "listings": [
            {
                "listing_id":       l["listing_id"],
                "symbol":           l["symbol"],
                "signal_type":      l["signal_type"],
                "bias":             l["bias"],
                "confidence":       l["confidence"],
                "timeframe":        l["timeframe"],
                "seller":           l["wallet"][:12] + "…",
                "sale_count":       l["sale_count"],
                "listed_at":        l["listed_at"],
                "expires_at":       l["expires_at"],
                "read_price_rlusd": "0.02",
            }
            for l in chunk
        ],
        "read_endpoint":  "POST /api/marketplace/read (0.02 RLUSD x402)",
        "list_endpoint":  "POST /api/marketplace/list (free)",
        "ts": now,
    })


# ── Free preview ──────────────────────────────────────────────────────────────

@marketplace_bp.route('/preview/<listing_id>', methods=['GET'])
def preview(listing_id):
    l = _listings.get(listing_id)
    if not l or not l['active']:
        return jsonify({"error": "ERR_LISTING_NOT_FOUND", "message": "Listing not found"}), 404
    if time.time() > l['expires_at']:
        l['active'] = False
        return jsonify({"error": "ERR_LISTING_EXPIRED", "message": "Listing has expired"}), 410

    seller_sales = _stat(l['wallet'])['sale_count']
    return jsonify({
        "listing_id":     listing_id,
        "symbol":         l["symbol"],
        "bias":           l["bias"],
        "confidence":     l["confidence"],
        "signal_type":    l["signal_type"],
        "timeframe":      l["timeframe"],
        "seller_sales":   seller_sales,
        "sale_count":     l["sale_count"],
        "listed_at":      l["listed_at"],
        "preview":        True,
        "upgrade": {
            "full_signal": "POST /api/marketplace/read",
            "includes":    ["thesis", "entry", "target", "stop", "seller_track_record"],
            "price_rlusd": "0.02",
        },
    })


# ── Full read — gated by x402 (0.02 RLUSD) ───────────────────────────────────

@marketplace_bp.route('/read', methods=['POST'])
@require_payment
def read():
    body       = request.get_json(silent=True) or {}
    listing_id = (body.get('listing_id') or '').strip()
    if not listing_id:
        return jsonify({
            "error":   "ERR_LISTING_ID_REQUIRED",
            "message": "listing_id required in POST body",
        }), 400

    l = _listings.get(listing_id)
    if not l or not l['active']:
        return jsonify({"error": "ERR_LISTING_NOT_FOUND", "message": "Listing not found"}), 404
    if time.time() > l['expires_at']:
        l['active'] = False
        return jsonify({"error": "ERR_LISTING_EXPIRED", "message": "Listing has expired"}), 410

    # Record sale + credit seller (Alpha Mesh: 90% of read fee accrues to seller)
    l['sale_count'] += 1
    st = _stat(l['wallet'])
    st['sale_count']      += 1
    st['revenue_rlusd']    = round(st['revenue_rlusd'] + READ_PRICE_RLUSD, 4)
    st['balance_rlusd']    = round(st['balance_rlusd'] + SELLER_CUT_RLUSD, 4)

    # Bureau score bonus: +2 per sale, up to +50 lifetime
    score_bonus = min(st['sale_count'] * 2, 50)

    logger.info(f"[MARKET] Sale: {listing_id[:8]} {l['symbol']} buyer={request.headers.get('X-Agent-Wallet','?')[:12]}")

    return jsonify({
        "listing_id":      listing_id,
        "symbol":          l["symbol"],
        "bias":            l["bias"],
        "confidence":      l["confidence"],
        "signal_type":     l["signal_type"],
        "timeframe":       l["timeframe"],
        "thesis":          l["thesis"],
        "entry":           l.get("entry"),
        "target":          l.get("target"),
        "stop":            l.get("stop"),
        "seller_wallet":   l["wallet"],
        "seller_sales":    st["sale_count"],
        "seller_score_bonus": score_bonus,
        "seller_cut_rlusd": SELLER_CUT_RLUSD,
        "seller_balance_rlusd": st["balance_rlusd"],
        "platform_fee_rlusd": round(READ_PRICE_RLUSD - SELLER_CUT_RLUSD, 4),
        "listed_at":       l["listed_at"],
        "expires_at":      l["expires_at"],
        "verified_by":     "SqueezeOS Marketplace — payment verified, seller wallet on record",
        "ts":              time.time(),
    })


# ── List a signal (free) ──────────────────────────────────────────────────────

@marketplace_bp.route('/list', methods=['POST'])
def list_signal():
    body        = request.get_json(silent=True) or {}
    wallet      = (body.get('wallet') or '').strip()
    symbol      = (body.get('symbol') or '').strip().upper()
    bias        = (body.get('bias')   or '').strip().upper()
    confidence  = body.get('confidence', 50)
    thesis      = (body.get('thesis') or '').strip()
    signal_type = (body.get('signal_type') or 'CUSTOM').strip().upper()
    timeframe   = (body.get('timeframe') or '1D').strip().upper()
    ttl_hours   = min(168, max(1, int(body.get('ttl_hours', 24))))

    if not wallet or not wallet.startswith('r') or len(wallet) < 25:
        return jsonify({"error": "ERR_INVALID_WALLET", "message": "Valid XRPL wallet required"}), 400
    if not symbol or len(symbol) > 10:
        return jsonify({"error": "ERR_INVALID_SYMBOL", "message": "Valid ticker symbol required (max 10 chars)"}), 400
    if bias not in _VALID_BIASES:
        return jsonify({
            "error":   "ERR_INVALID_BIAS",
            "message": f"bias must be one of: {', '.join(sorted(_VALID_BIASES))}",
        }), 400
    if not isinstance(confidence, (int, float)) or not (0 <= confidence <= 100):
        return jsonify({"error": "ERR_INVALID_CONFIDENCE", "message": "confidence must be 0-100"}), 400
    if not thesis or len(thesis) < 20:
        return jsonify({"error": "ERR_THESIS_TOO_SHORT", "message": "thesis must be at least 20 characters"}), 400
    if signal_type not in _VALID_TYPES:
        signal_type = 'CUSTOM'
    thesis = thesis[:1000]

    # Per-seller cap
    seller_active = [l for l in _listings.values() if l['wallet'] == wallet and l['active']]
    if len(seller_active) >= _MAX_PER_SELLER:
        return jsonify({
            "error":   "ERR_LISTING_LIMIT",
            "message": f"Max {_MAX_PER_SELLER} active listings per wallet. Delete one first.",
        }), 429

    # Global cap — evict oldest
    if len(_listings) >= _MAX_LISTINGS:
        oldest_id = min(_listings.keys(), key=lambda k: _listings[k]['listed_at'])
        _listings.pop(oldest_id, None)

    listing_id = str(uuid.uuid4())
    now = time.time()
    _listings[listing_id] = {
        "listing_id":  listing_id,
        "wallet":      wallet,
        "symbol":      symbol,
        "bias":        bias,
        "confidence":  float(confidence),
        "signal_type": signal_type,
        "timeframe":   timeframe,
        "thesis":      thesis,
        "entry":       body.get("entry"),
        "target":      body.get("target"),
        "stop":        body.get("stop"),
        "listed_at":   now,
        "expires_at":  now + ttl_hours * 3600,
        "sale_count":  0,
        "active":      True,
    }

    st = _stat(wallet)
    st['listing_count'] += 1

    logger.info(f"[MARKET] Listed {listing_id[:8]} {symbol} {bias} conf={confidence} by {wallet[:12]}…")

    signal_history.record(symbol, 'MARKETPLACE_LISTING', {
        "listing_id": listing_id,
        "bias":       bias,
        "confidence": float(confidence),
        "signal_type": signal_type,
        "seller":     wallet[:12] + "…",
    })

    return jsonify({
        "listing_id":       listing_id,
        "status":           "LISTED",
        "symbol":           symbol,
        "bias":             bias,
        "confidence":       float(confidence),
        "expires_at":       now + ttl_hours * 3600,
        "read_price_rlusd": "0.02",
        "preview_url":      f"/api/marketplace/preview/{listing_id}",
        "earn": {
            "per_sale":   "Credit Bureau score +2 pts per sale (up to +50 lifetime)",
            "leaderboard":"Top sellers at /api/marketplace/leaderboard",
            "relay_path": "Score 600+ → relay node (40% bulk discount on your own signal buys)",
        },
    }), 201


@marketplace_bp.route('/balance/<wallet>', methods=['GET'])
def balance(wallet):
    """Alpha Mesh — accrued seller earnings (90% of each /read sale)."""
    st = _seller_stats.get(wallet)
    if not st:
        return jsonify({
            "wallet": wallet,
            "balance_rlusd": 0.0,
            "sale_count": 0,
            "message": "No sales recorded for this wallet yet.",
            "ts": time.time(),
        })
    return jsonify({
        "wallet":          wallet,
        "balance_rlusd":   st["balance_rlusd"],
        "paid_out_rlusd":  st["paid_out_rlusd"],
        "revenue_rlusd":   st["revenue_rlusd"],
        "sale_count":      st["sale_count"],
        "seller_share":    f"{int(SELLER_SHARE*100)}%",
        "payout_note": (
            "Balance accrues from Alpha Mesh signal sales (90% of each "
            "0.02 RLUSD read). Payout rail: contact ScriptMasterLabs@gmail.com "
            "for manual XRPL settlement until automated payout batches go live."
        ),
        "ts": time.time(),
    })


# ── Leaderboard ───────────────────────────────────────────────────────────────

@marketplace_bp.route('/leaderboard', methods=['GET'])
def leaderboard():
    ranked = sorted(
        [(w, s) for w, s in _seller_stats.items() if s['sale_count'] > 0],
        key=lambda x: -x[1]['sale_count']
    )[:20]
    return jsonify({
        "leaderboard": [
            {
                "rank":          i + 1,
                "wallet":        w[:12] + "…",
                "sale_count":    s['sale_count'],
                "listing_count": s['listing_count'],
                "score_bonus":   min(s['sale_count'] * 2, 50),
            }
            for i, (w, s) in enumerate(ranked)
        ],
        "ts": time.time(),
    })


# ── Delete ────────────────────────────────────────────────────────────────────

@marketplace_bp.route('/<listing_id>', methods=['DELETE'])
def delete_listing(listing_id):
    l = _listings.get(listing_id)
    if not l:
        return jsonify({"error": "ERR_LISTING_NOT_FOUND"}), 404
    body   = request.get_json(silent=True) or {}
    wallet = (body.get('wallet') or '').strip()
    if wallet != l['wallet']:
        return jsonify({"error": "ERR_UNAUTHORIZED", "message": "wallet does not match listing owner"}), 403
    l['active'] = False
    return jsonify({"status": "DELETED", "listing_id": listing_id})
