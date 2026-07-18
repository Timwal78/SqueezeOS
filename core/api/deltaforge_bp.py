"""
ScriptMaster DeltaForge™ — flagship product API — /api/deltaforge

    "Trade the Delta. Catch the Explosion."

Aggressive-but-disciplined convexity trading system: the server-side twin of
indicators/ScriptMaster_DeltaForge_Flagship_v6.pine (v2.1). Detects explosive
breakouts on real Tradier intraday bars, picks the 0.32–0.40-delta contract
via the Delta Explosion Scanner, and hands back ready-to-submit BYOK order
payloads for Tradier and Robinhood.

NON-CUSTODIAL BY DESIGN: this API never sees a broker key and never places an
order. It returns signals and order *payloads*; execution happens on the
customer's machine with their own keys (sdk/deltaforge_client.py).

Framework grounding (documented fully in docs/DELTAFORGE.md):
  - Prospect Theory (Kahneman/Tversky) → asymmetric payoff targeting: capped
    1R risk vs 2R+ targets, breakeven arming (loss-aversion-aware exits).
  - Modern Portfolio Theory / CAPM (Markowitz/Sharpe) → fixed-fraction sizing,
    per-trade risk caps, portfolio position limits.
  - Market microstructure / asset pricing (Fama/Shiller/Hansen) → spread
    penalty + liquidity guards in contract ranking; regime filter (Kaufman ER).
  - Asymmetric information (Akerlof/Spence/Stiglitz) → volume-thrust
    confirmation: only act when volume says somebody knows something.
  - Mental accounting (Thaler) → hard daily loss bucket + circuit breakers,
    enforced client-side in the SDK.

Tiers (keys via Stripe, pattern mirrors trade_desk_stripe_bp):
  scout    — free, no key: signal direction + core metrics.
  operator — paid: full metrics + the ranked 0.32–0.40Δ contract.
  elite    — paid: everything + BYOK order payloads + SSE signal feed.
  Founder: DELTAFORGE_OWNER_KEY env var always validates as elite (permanent,
  free, independent of Stripe/Redis — same owner-bypass pattern as Trade Desk).

Env vars (all optional; endpoint degrades honestly without them):
  DELTAFORGE_OWNER_KEY               — founder's permanent elite key
  DELTAFORGE_STRIPE_OPERATOR_PRICE_ID / DELTAFORGE_STRIPE_ELITE_PRICE_ID
  DELTAFORGE_STRIPE_WEBHOOK_SECRET   — whsec_... (products not yet created —
                                       same "not yet configured" pattern as
                                       Trade Desk; webhook no-ops until set)
  STRIPE_SECRET_KEY, REDIS_URL       — shared with CASCADE/AEO/Trade Desk
  TRADIER_API_KEY                    — required for signals (real bars/greeks)
"""

import os
import json
import time
import hmac
import hashlib
import logging
import threading

import redis
import pandas as pd
from flask import Blueprint, jsonify, request

import tradier_api
from tradier_api import _to_float
from core.legacy import clean_data
from core.state import state
from core.api.delta_explosion_bp import _scan as delta_explosion_scan

log = logging.getLogger("DELTAFORGE")

deltaforge_bp = Blueprint("deltaforge", __name__)

_OWNER_KEY         = os.environ.get("DELTAFORGE_OWNER_KEY", "")
_OPERATOR_PRICE_ID = os.environ.get("DELTAFORGE_STRIPE_OPERATOR_PRICE_ID", "")
_ELITE_PRICE_ID    = os.environ.get("DELTAFORGE_STRIPE_ELITE_PRICE_ID", "")
_WEBHOOK_SECRET    = os.environ.get("DELTAFORGE_STRIPE_WEBHOOK_SECRET", "")
_REDIS_URL         = os.environ.get("REDIS_URL", "")

_KEY_PREFIX  = "deltaforge:apikey:"
_CUST_PREFIX = "deltaforge:cust:"
_KEY_TTL     = 60 * 60 * 24 * 400

_signal_cache: dict = {}
_cache_lock = threading.Lock()
_SIGNAL_TTL = 60  # seconds — one 15-min bar never needs sub-minute recompute

MIN_BARS = 140  # 100-bar z-score window + 20-bar channel + smoothing warmup

# Engine thresholds — identical to the Pine flagship v2.1 defaults.
BREAKOUT_PAD   = 1.001
DIST_BULL      = 0.65
DIST_BEAR      = 0.35
Z_LONG         = 0.5
Z_SHORT        = -0.5
ER_MIN         = 0.30
DEFAULT_AGGR   = 0.85


# ═══════════════════════════════════════════════════════════════════════════
# Signal engine — Python port of ScriptMaster_DeltaForge_Flagship_v6.pine
# ═══════════════════════════════════════════════════════════════════════════

def _compute_signal(bars: list, aggression: float) -> dict:
    """Run DeltaForge v2.1 logic on real bars (oldest first). Pure function."""
    df = pd.DataFrame(bars)
    n = len(df)
    if n < MIN_BARS:
        return {"error": f"insufficient history: {n} bars, need {MIN_BARS}",
                "status": 502}
    c, h, l, v = df["close"], df["high"], df["low"], df["volume"]

    # Prior 20-bar channel (excludes current bar — breakout must be possible)
    ref_high = float(h.iloc[-21:-1].max())
    ref_low  = float(l.iloc[-21:-1].min())
    ch_range = ref_high - ref_low
    last = float(c.iloc[-1])
    distortion = (last - ref_low) / ch_range if ch_range > 0 else 0.5

    # Volatility spike
    std10 = c.rolling(10).std()
    std20 = c.rolling(20).std()
    vol_spike = bool(std10.rolling(5).mean().iloc[-1] > std20.rolling(20).mean().iloc[-1])

    # Momentum thrust (the v2.1 gate — NOT the impossible v1.1 "shift")
    mom5  = last - float(c.iloc[-6])
    mom10 = last - float(c.iloc[-11])
    bull_thrust = mom5 > 0 and mom5 > mom10
    bear_thrust = mom5 < 0 and mom5 < mom10

    # Convexity score → z-score vs its own 100-bar history
    roc5 = c.pct_change(5) * 100.0
    vol_ratio = v / v.rolling(20).mean()
    conv = (roc5 * vol_ratio)
    smoothed = conv.ewm(span=5, adjust=False).mean()
    m100 = float(smoothed.rolling(100).mean().iloc[-1])
    s100 = float(smoothed.rolling(100).std().iloc[-1])
    z = ((float(smoothed.iloc[-1]) - m100) / s100) if s100 > 0 else 0.0
    delta_score = z * aggression

    # Kaufman Efficiency Ratio regime filter
    er_den = float(c.diff().abs().rolling(10).sum().iloc[-1])
    er = abs(last - float(c.iloc[-11])) / er_den if er_den > 0 else 0.0
    regime_ok = er >= ER_MIN

    explosive_bull = vol_spike and bull_thrust and last > ref_high * BREAKOUT_PAD and distortion > DIST_BULL
    explosive_bear = vol_spike and bear_thrust and last < ref_low * (2 - BREAKOUT_PAD) and distortion < DIST_BEAR

    direction = "NONE"
    if explosive_bull and delta_score > Z_LONG and regime_ok:
        direction = "LONG"
    elif explosive_bear and delta_score < Z_SHORT and regime_ok:
        direction = "SHORT"

    return {
        "direction": direction,
        "price": last,
        "metrics": {
            "distortion": round(distortion, 4),
            "delta_score_sigma": round(delta_score, 4),
            "efficiency_ratio": round(er, 4),
            "regime": "TRENDING" if regime_ok else "CHOP",
            "vol_spike": vol_spike,
            "momentum_thrust": "BULL" if bull_thrust else "BEAR" if bear_thrust else "NONE",
            "channel_high": round(ref_high, 4),
            "channel_low": round(ref_low, 4),
            "explosive_bull": explosive_bull,
            "explosive_bear": explosive_bear,
        },
        "bars_used": n,
    }


def _order_payloads(symbol: str, direction: str, contract: dict, spot: float) -> dict:
    """BYOK order payloads. quantity is null on purpose — sizing is a function
    of the CUSTOMER's account equity, which this server never sees. The SDK
    fills quantity from its risk engine before submitting."""
    side_word = "call" if direction == "LONG" else "put"
    limit_price = contract["ask"]  # marketable; SDK may tighten to mid
    return {
        "note": "Payloads only — this API never executes. Fill `quantity` "
                "client-side from your risk engine (see sizing_rule), then "
                "submit with YOUR broker key via sdk/deltaforge_client.py.",
        "sizing_rule": "quantity = floor((account_equity * max_risk_pct) / "
                       "(100 * limit_price)) — risk the premium, never more.",
        "tradier": {
            "endpoint": "POST /v1/accounts/{account_id}/orders",
            "params": {
                "class": "option",
                "symbol": symbol,
                "option_symbol": contract["contract"],
                "side": "buy_to_open",
                "quantity": None,
                "type": "limit",
                "price": limit_price,
                "duration": "day",
            },
        },
        "robinhood": {
            "function": "robin_stocks.robinhood.order_buy_option_limit",
            "kwargs": {
                "positionEffect": "open",
                "creditOrDebit": "debit",
                "price": limit_price,
                "symbol": symbol,
                "quantity": None,
                "expirationDate": contract["expiration"],
                "strike": contract["strike"],
                "optionType": side_word,
                "timeInForce": "gfd",
            },
        },
        "equity_fallback": {
            "tradier": {
                "class": "equity", "symbol": symbol,
                "side": "buy" if direction == "LONG" else "sell_short",
                "quantity": None, "type": "market", "duration": "day",
                "stop_hint": round(spot * (0.97 if direction == "LONG" else 1.03), 2),
            },
        },
    }


# ═══════════════════════════════════════════════════════════════════════════
# Tier resolution (owner key → Redis keys → scout)
# ═══════════════════════════════════════════════════════════════════════════

def _get_redis():
    if not _REDIS_URL:
        return None
    try:
        return redis.from_url(_REDIS_URL, decode_responses=True)
    except Exception as e:
        log.error("DeltaForge: Redis connect failed: %s", e)
        return None


def _resolve_tier(req) -> tuple:
    """Returns (tier, key_source). Founder key always wins, is never stored,
    and works even with Redis down."""
    api_key = req.headers.get("X-DeltaForge-Key") or req.args.get("key") or ""
    if not api_key:
        return "scout", "none"
    if _OWNER_KEY and hmac.compare_digest(api_key, _OWNER_KEY):
        return "elite", "founder"
    r = _get_redis()
    if r:
        try:
            record = r.get(f"{_KEY_PREFIX}{api_key}")
            if record:
                return json.loads(record).get("tier", "scout"), "stripe"
        except Exception as e:
            log.error("DeltaForge: key lookup failed: %s", e)
    return "scout", "invalid"


# ═══════════════════════════════════════════════════════════════════════════
# Routes
# ═══════════════════════════════════════════════════════════════════════════

@deltaforge_bp.route("", methods=["GET"])
@deltaforge_bp.route("/", methods=["GET"])
def deltaforge_root():
    return jsonify({
        "product": "ScriptMaster DeltaForge™",
        "tagline": "Trade the Delta. Catch the Explosion.",
        "what": "Explosive-breakout signals + 0.32-0.40 delta contract selection "
                "+ BYOK order payloads. Non-custodial: your keys never leave "
                "your machine and this API never places an order.",
        "tradier_configured": tradier_api.is_available(),
        "tiers": {
            "scout": "free — signal direction + core metrics",
            "operator": "full metrics + ranked explosion-band contract",
            "elite": "everything + BYOK Tradier/Robinhood order payloads + SSE feed",
        },
        "endpoints": {
            "signal": "GET /api/deltaforge/signal/<symbol> "
                      "[X-DeltaForge-Key header for operator/elite]",
            "contract_scanner": "GET /api/delta-explosion/<symbol>?direction=long|short",
            "key_validate": "POST /api/deltaforge/key/validate {api_key}",
            "sse_feed": "GET /api/events (DELTAFORGE_SIGNAL events)",
        },
        "pine": "indicators/ScriptMaster_DeltaForge_Flagship_v6.pine (v2.1) — "
                "same engine on TradingView",
        "sdk": "sdk/deltaforge_client.py — BYOK execution client "
               "(Tradier + Robinhood), risk engine + circuit breakers included",
        "docs": "docs/DELTAFORGE.md",
    })


@deltaforge_bp.route("/signal/<symbol>", methods=["GET"])
def deltaforge_signal(symbol: str):
    symbol = symbol.upper().strip()
    if not tradier_api.is_available():
        return jsonify({"error": "TRADIER_API_KEY not configured — DeltaForge "
                                 "signals require real market data"}), 503
    try:
        aggression = float(request.args.get("aggression", DEFAULT_AGGR))
    except (TypeError, ValueError):
        return jsonify({"error": "aggression must be a float"}), 400
    if not (0.0 < aggression <= 1.0):
        return jsonify({"error": "aggression must be in (0, 1]"}), 400

    tier, key_source = _resolve_tier(request)

    cache_key = (symbol, round(aggression, 2))
    now = time.time()
    with _cache_lock:
        entry = _signal_cache.get(cache_key)
    if entry and now - entry["ts"] < _SIGNAL_TTL:
        sig = entry["signal"]
    else:
        bars = tradier_api.get_timesales(symbol, interval="15min", days_back=35)
        if not bars:
            return jsonify({"error": f"no intraday bars available for {symbol}"}), 502
        sig = _compute_signal(bars, aggression)
        if "error" in sig:
            return jsonify(clean_data(sig)), sig.pop("status", 502)
        with _cache_lock:
            _signal_cache[cache_key] = {"ts": now, "signal": sig}
        if sig["direction"] != "NONE":
            state.push_terminal("DELTAFORGE_SIGNAL",
                                f"DeltaForge {sig['direction']} on {symbol} @ {sig['price']}",
                                symbol, sig["metrics"]["delta_score_sigma"])

    out = {
        "product": "ScriptMaster DeltaForge™",
        "symbol": symbol,
        "tier": tier,
        "direction": sig["direction"],
        "price": sig["price"],
        "aggression": aggression,
        "interval": "15min",
        "bars_used": sig["bars_used"],
        "ts": int(now),
    }
    if key_source == "invalid":
        out["warning"] = "key not recognized — serving scout tier"

    if tier == "scout":
        out["metrics"] = {k: sig["metrics"][k] for k in
                          ("distortion", "delta_score_sigma", "regime")}
        out["upgrade"] = ("operator unlocks full metrics + the ranked "
                          "0.32-0.40 delta contract; elite adds BYOK order payloads")
        return jsonify(clean_data(out))

    out["metrics"] = sig["metrics"]

    if sig["direction"] in ("LONG", "SHORT"):
        scan = delta_explosion_scan(symbol, "long" if sig["direction"] == "LONG" else "short",
                                    0.32, 0.40, 5, 45)
        if "error" in scan:
            out["contract"] = None
            out["contract_error"] = scan["error"]
        else:
            out["contract"] = scan["best"]
            if tier == "elite":
                out["order_payloads"] = _order_payloads(
                    symbol, sig["direction"], scan["best"], _to_float(scan.get("spot")))
    else:
        out["contract"] = None

    return jsonify(clean_data(out))


@deltaforge_bp.route("/key/validate", methods=["POST"])
def deltaforge_key_validate():
    api_key = request.json.get("api_key", "") if request.is_json else ""
    if not api_key:
        return jsonify({"valid": False, "error": "missing api_key"}), 400
    if _OWNER_KEY and hmac.compare_digest(api_key, _OWNER_KEY):
        return jsonify({"valid": True, "tier": "elite", "customer_email": "founder"})
    r = _get_redis()
    if not r:
        return jsonify({"valid": False, "error": "redis unavailable"}), 503
    record = r.get(f"{_KEY_PREFIX}{api_key}")
    if not record:
        return jsonify({"valid": False}), 401
    try:
        data = json.loads(record)
        return jsonify({"valid": True, "tier": data.get("tier"),
                        "customer_email": data.get("customer_email")})
    except Exception:
        return jsonify({"valid": False}), 500


# ═══════════════════════════════════════════════════════════════════════════
# Stripe webhook — key issuance (mirrors trade_desk_stripe_bp exactly).
# No-ops with a real error until DELTAFORGE_STRIPE_* env vars are configured.
# ═══════════════════════════════════════════════════════════════════════════

def _verify_stripe_signature(payload: bytes, sig_header: str, secret: str) -> bool:
    if not secret or not sig_header:
        return False
    try:
        parts = {k: v for part in sig_header.split(",") for k, v in [part.split("=", 1)]}
        signed = f"{parts.get('t', '')}.".encode() + payload
        expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, parts.get("v1", ""))
    except Exception:
        return False


def _tier_for_price(price_id: str) -> str:
    if price_id and price_id == _OPERATOR_PRICE_ID:
        return "operator"
    if price_id and price_id == _ELITE_PRICE_ID:
        return "elite"
    return ""


def _issue_key(customer_id: str, email: str, tier: str, sub_id: str) -> str:
    r = _get_redis()
    if not r:
        raise RuntimeError("Redis unavailable")
    raw = f"deltaforge-{customer_id}-{sub_id}-{time.time()}"
    api_key = "df_" + hashlib.sha256(raw.encode()).hexdigest()[:40]
    r.setex(f"{_KEY_PREFIX}{api_key}", _KEY_TTL, json.dumps({
        "customer_id": customer_id, "customer_email": email,
        "tier": tier, "subscription_id": sub_id, "issued_at": int(time.time()),
    }))
    r.setex(f"{_CUST_PREFIX}{customer_id}", _KEY_TTL, api_key)
    log.info("DeltaForge Stripe: issued %s key for %s", tier, customer_id)
    return api_key


def _revoke_key(customer_id: str) -> bool:
    r = _get_redis()
    if not r:
        return False
    api_key = r.get(f"{_CUST_PREFIX}{customer_id}")
    if api_key:
        r.delete(f"{_KEY_PREFIX}{api_key}")
        r.delete(f"{_CUST_PREFIX}{customer_id}")
        log.info("DeltaForge Stripe: revoked key for %s", customer_id)
        return True
    return False


def _sub_fields(sub: dict) -> tuple:
    items = sub.get("items", {}).get("data", [])
    price_id = items[0].get("price", {}).get("id", "") if items else ""
    email = sub.get("customer_email") or sub.get("metadata", {}).get("email", "")
    return sub.get("customer", ""), email, sub.get("id", ""), _tier_for_price(price_id)


@deltaforge_bp.route("/stripe/webhook", methods=["POST"])
def deltaforge_stripe_webhook():
    payload = request.get_data()
    if not _WEBHOOK_SECRET:
        log.error("DeltaForge Stripe: DELTAFORGE_STRIPE_WEBHOOK_SECRET not configured")
        return jsonify({"error": "webhook secret not configured"}), 500
    if not _verify_stripe_signature(payload, request.headers.get("Stripe-Signature", ""),
                                    _WEBHOOK_SECRET):
        return jsonify({"error": "invalid signature"}), 400
    try:
        event = json.loads(payload)
    except Exception:
        return jsonify({"error": "invalid JSON"}), 400

    event_type = event.get("type", "")
    obj = event.get("data", {}).get("object", {})

    if event_type == "customer.subscription.created":
        customer_id, email, sub_id, tier = _sub_fields(obj)
        if tier and customer_id and sub_id:
            try:
                _issue_key(customer_id, email, tier, sub_id)
            except Exception as e:
                log.error("DeltaForge Stripe: issue failed: %s", e)
    elif event_type == "customer.subscription.updated":
        customer_id, email, sub_id, tier = _sub_fields(obj)
        if tier and customer_id:
            _revoke_key(customer_id)
            try:
                _issue_key(customer_id, email, tier, sub_id)
            except Exception as e:
                log.error("DeltaForge Stripe: re-issue failed: %s", e)
    elif event_type in ("customer.subscription.deleted", "customer.subscription.paused"):
        if obj.get("customer"):
            _revoke_key(obj["customer"])

    return jsonify({"received": True}), 200
