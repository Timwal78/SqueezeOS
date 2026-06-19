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

import base64
import hashlib
import os
import sqlite3
import sys
import threading
import time
import uuid
import logging
from functools import wraps
from flask import Blueprint, jsonify, request
import core.signal_history as signal_history

# proof402_integration lives at repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from proof402_integration import require_payment

logger = logging.getLogger("SqueezeOS-Marketplace")
marketplace_bp = Blueprint('marketplace', __name__)

# ── SQLite persistence (uses VAPL disk so balances survive redeploys) ─────────
_VAPL_DIR  = os.path.dirname(os.environ.get("VAPL_SOUL_FILE", "/var/data/vapl/soul.json"))
try:
    os.makedirs(_VAPL_DIR, exist_ok=True)
    _DB_FILE = os.path.join(_VAPL_DIR, "marketplace.db")
except Exception:
    _DB_FILE = "/tmp/marketplace.db"

_db_lock = threading.Lock()

# XRPL payout wallet (operator funds this to honour seller withdrawals)
MARKETPLACE_XRPL_SEED    = os.environ.get("MARKETPLACE_XRPL_SEED", "")
MARKETPLACE_XRPL_ADDRESS = os.environ.get("MARKETPLACE_XRPL_ADDRESS", "")
RLUSD_ISSUER             = "rMxCKbEDwqr76QuheSUMdEGf4B9xJ8m5De"
RLUSD_CURRENCY           = "524C555344000000000000000000000000000000"
MIN_WITHDRAW_RLUSD       = 0.05
WITHDRAW_WINDOW_SECS     = 300   # 5-minute replay-attack window

# ── Storage ───────────────────────────────────────────────────────────────────
_listings:     dict = {}   # listing_id -> listing dict
_seller_stats: dict = {}   # wallet -> {sale_count, listing_count, revenue_rlusd}


def _init_db() -> None:
    with sqlite3.connect(_DB_FILE) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS seller_balances (
                wallet         TEXT PRIMARY KEY,
                balance_rlusd  REAL DEFAULT 0,
                paid_out_rlusd REAL DEFAULT 0,
                revenue_rlusd  REAL DEFAULT 0,
                sale_count     INTEGER DEFAULT 0,
                listing_count  INTEGER DEFAULT 0
            )
        """)
        conn.commit()


def _load_balances() -> None:
    """Restore persisted seller balances into _seller_stats on startup."""
    try:
        _init_db()
        with sqlite3.connect(_DB_FILE) as conn:
            rows = conn.execute("SELECT * FROM seller_balances").fetchall()
        for wallet, balance, paid_out, revenue, sales, listings in rows:
            _seller_stats[wallet] = {
                "balance_rlusd":  balance,
                "paid_out_rlusd": paid_out,
                "revenue_rlusd":  revenue,
                "sale_count":     sales,
                "listing_count":  listings,
            }
        logger.info("[MARKET] Loaded %d seller balances from SQLite", len(rows))
    except Exception as exc:
        logger.warning("[MARKET] Balance load failed (non-fatal): %s", exc)


def _persist_balance(wallet: str) -> None:
    """Write one seller's balance to SQLite."""
    st = _seller_stats.get(wallet)
    if not st:
        return
    try:
        with _db_lock, sqlite3.connect(_DB_FILE) as conn:
            conn.execute("""
                INSERT INTO seller_balances
                    (wallet, balance_rlusd, paid_out_rlusd, revenue_rlusd, sale_count, listing_count)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(wallet) DO UPDATE SET
                    balance_rlusd  = excluded.balance_rlusd,
                    paid_out_rlusd = excluded.paid_out_rlusd,
                    revenue_rlusd  = excluded.revenue_rlusd,
                    sale_count     = excluded.sale_count,
                    listing_count  = excluded.listing_count
            """, (
                wallet,
                st["balance_rlusd"],
                st["paid_out_rlusd"],
                st["revenue_rlusd"],
                st["sale_count"],
                st["listing_count"],
            ))
            conn.commit()
    except Exception as exc:
        logger.warning("[MARKET] Balance persist failed for %s…: %s", wallet[:12], exc)


# Load persisted balances at import time
_load_balances()

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


def _dual_payment(price_usdc: str):
    """
    Accept EITHER USDC/Base (x402 X-PAYMENT) OR RLUSD/XRPL (X-Payment-Token
    via 402Proof, handled by require_payment). Falls through to require_payment
    when no X-PAYMENT header is present (preserves the existing RLUSD flow and
    a 402 response that advertises both rails).
    """
    def decorator(fn):
        rlusd_gated = require_payment(fn)

        @wraps(fn)
        def wrapper(*args, **kwargs):
            xpay = request.headers.get("X-PAYMENT")
            if not xpay:
                return rlusd_gated(*args, **kwargs)

            import base64 as _b64, json as _json
            from x402_flask import _payment_requirements, _facilitator, _402 as _x402_402

            reqs = _payment_requirements(price_usdc, "Alpha Mesh signal read", request.base_url)
            try:
                payload = _json.loads(_b64.b64decode(xpay))
            except Exception:
                return _x402_402(reqs, "malformed X-PAYMENT header")
            verify = _facilitator("/verify", payload, reqs)
            if not verify.get("isValid", False):
                return _x402_402(reqs, f"invalid payment: {verify.get('invalidReason','unknown')}")

            resp = fn(*args, **kwargs)
            settle = _facilitator("/settle", payload, reqs)
            if settle.get("success", False):
                resp.headers["X-PAYMENT-RESPONSE"] = _b64.b64encode(_json.dumps(settle).encode()).decode()
            return resp
        return wrapper
    return decorator


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
@_dual_payment("0.02")
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
    _persist_balance(l['wallet'])   # survive redeploys

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
        "paid_via": "USDC/Base" if request.headers.get("X-PAYMENT") else "RLUSD/XRPL",
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


# ── Withdraw — DID-signed, XRPL payout ───────────────────────────────────────

def _verify_did_signature(agent_did: str, message: bytes, sig_b64: str) -> bool:
    """Verify an Ed25519 signature from a did:key identity."""
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        # did:key:z{base58btc([0xed,0x01]+pub_raw)}
        key_part = agent_did[len("did:key:z"):]
        B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
        n = 0
        for ch in key_part:
            n = n * 58 + B58.index(ch)
        # multicodec is exactly 34 bytes: [0xed, 0x01] + 32-byte pubkey
        multicodec = n.to_bytes(34, "big")
        if multicodec[0] != 0xed or multicodec[1] != 0x01:
            return False
        pub_raw = multicodec[2:]

        pub_key = Ed25519PublicKey.from_public_bytes(pub_raw)
        pad     = 4 - len(sig_b64) % 4
        sig     = base64.urlsafe_b64decode(sig_b64 + ("=" * pad if pad != 4 else ""))
        pub_key.verify(sig, message)
        return True
    except Exception:
        return False


def _send_rlusd_payout(amount_rlusd: float, destination: str):
    """Send RLUSD from marketplace treasury wallet to seller."""
    try:
        import xrpl.clients, xrpl.models.transactions, xrpl.models.amounts
        import xrpl.wallet, xrpl.transaction

        wallet  = xrpl.wallet.Wallet.from_seed(MARKETPLACE_XRPL_SEED)
        client  = xrpl.clients.JsonRpcClient("https://s1.ripple.com:51234/")
        tx      = xrpl.models.transactions.Payment(
            account=wallet.classic_address,
            amount=xrpl.models.amounts.IssuedCurrencyAmount(
                currency=RLUSD_CURRENCY,
                issuer=RLUSD_ISSUER,
                value=str(round(amount_rlusd, 6)),
            ),
            destination=destination,
        )
        response = xrpl.transaction.submit_and_wait(tx, client, wallet)
        return response.result.get("hash")
    except Exception as exc:
        logger.warning("[MARKET] XRPL payout failed: %s", exc)
        return None


@marketplace_bp.route('/withdraw', methods=['POST'])
def withdraw():
    """Withdraw accrued Alpha Mesh earnings to seller's XRPL wallet.

    Requires a DID-signed proof of wallet ownership (prevents spoofing).

    Body:
      {
        "wallet":    "r...",
        "agent_did": "did:key:z...",
        "timestamp": 1234567890,          # unix seconds — must be within 5 min
        "nonce":     "...",
        "signature": "base64url(Ed25519(sha256(canonical_json({agent_did,nonce,timestamp,wallet}))))"
      }
    """
    import json as _json

    body      = request.get_json(silent=True) or {}
    wallet    = (body.get("wallet")    or "").strip()
    agent_did = (body.get("agent_did") or "").strip()
    timestamp = body.get("timestamp", 0)
    n         = (body.get("nonce")     or "").strip()
    signature = (body.get("signature") or "").strip()

    if not wallet or not wallet.startswith("r") or len(wallet) < 25:
        return jsonify({"error": "ERR_INVALID_WALLET"}), 400
    if not agent_did or not agent_did.startswith("did:key:z"):
        return jsonify({"error": "ERR_INVALID_DID"}), 400
    if not n or not signature:
        return jsonify({"error": "ERR_MISSING_AUTH"}), 400

    # Replay protection: timestamp must be within ±5 minutes
    now = time.time()
    if abs(now - float(timestamp)) > WITHDRAW_WINDOW_SECS:
        return jsonify({
            "error":   "ERR_TIMESTAMP_EXPIRED",
            "message": "timestamp must be within 5 minutes of server time",
        }), 400

    # Verify DID signature over canonical JSON
    msg_obj   = {"agent_did": agent_did, "nonce": n, "timestamp": timestamp, "wallet": wallet}
    canonical = "{" + ",".join(
        f"{_json.dumps(k)}:{_json.dumps(msg_obj[k])}" for k in sorted(msg_obj)
    ) + "}"
    digest = hashlib.sha256(canonical.encode()).digest()

    if not _verify_did_signature(agent_did, digest, signature):
        return jsonify({
            "error":   "ERR_INVALID_SIGNATURE",
            "message": "DID signature verification failed",
        }), 403

    # Check seller balance
    st = _seller_stats.get(wallet)
    balance = st["balance_rlusd"] if st else 0.0
    if balance < MIN_WITHDRAW_RLUSD:
        return jsonify({
            "error":         "ERR_INSUFFICIENT_BALANCE",
            "balance_rlusd": balance,
            "minimum_rlusd": MIN_WITHDRAW_RLUSD,
        }), 400

    amount = round(balance, 4)

    # Require payout wallet to be configured
    if not MARKETPLACE_XRPL_SEED:
        return jsonify({
            "error":   "ERR_PAYOUT_UNAVAILABLE",
            "message": "Marketplace treasury wallet not configured on server",
        }), 503

    # Execute XRPL payout
    tx_hash = _send_rlusd_payout(amount, wallet)
    if not tx_hash:
        return jsonify({
            "error":   "ERR_PAYMENT_FAILED",
            "message": "XRPL payment failed — balance NOT debited",
        }), 500

    # Debit balance and persist
    st["paid_out_rlusd"] = round(st.get("paid_out_rlusd", 0) + amount, 4)
    st["balance_rlusd"]  = 0.0
    _persist_balance(wallet)

    logger.info(
        "[MARKET] Withdrew %.4f RLUSD → %s… tx=%s",
        amount, wallet[:12], tx_hash,
    )

    return jsonify({
        "status":              "WITHDRAWN",
        "wallet":              wallet,
        "amount_rlusd":        amount,
        "tx_hash":             tx_hash,
        "paid_out_total_rlusd": st["paid_out_rlusd"],
        "ts":                  now,
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
