"""
Delta Explosion Scanner — /api/delta-explosion

Operator directive (Timothy, 2026-07-18): delta .32–.40 contracts are the
sweet spot for explosive plays — enough delta to participate, cheap enough
to keep the convexity. This endpoint takes an underlying + direction, pulls
the REAL Tradier options chain (greeks included), filters to contracts whose
delta magnitude sits inside the explosion band, and ranks them by
convexity-per-premium-dollar with liquidity guards.

Prime Directive compliance: no delta is ever estimated, interpolated, or
fabricated. If Tradier is unavailable, has no key, or returns no greeks,
the endpoint returns a real error — never a made-up contract.

Ranking (every component is included in the response so the math is
auditable):
    gamma_per_dollar = gamma / mid        # convexity per premium dollar
    spread_pct       = (ask - bid) / mid  # execution cost proxy
    explosion_score  = gamma_per_dollar / (1 + 10 * spread_pct)

Routes:
    GET /api/delta-explosion            → usage + availability status
    GET /api/delta-explosion/<symbol>   → ranked contracts
        ?direction=long|short   (default long:  calls; short: puts)
        ?delta_min=0.32         (delta magnitude band, defaults per the
        ?delta_max=0.40          operator's .32–.40 directive)
        ?dte_min=5&dte_max=45   (expiration window in days)
"""

import os
import time
import logging
import threading
from flask import Blueprint, jsonify, request

import tradier_api
from tradier_api import _convert_contract, _dte_for, _to_float
from core.legacy import clean_data

logger = logging.getLogger("DELTA-EXPLOSION")

delta_explosion_bp = Blueprint("delta_explosion", __name__)

_cache: dict = {}
_cache_lock = threading.Lock()
_CACHE_TTL = 120  # seconds — chains move fast but not per-request fast

DEFAULT_DELTA_MIN = 0.32
DEFAULT_DELTA_MAX = 0.40
DEFAULT_DTE_MIN = 5
DEFAULT_DTE_MAX = 45


def _scan(symbol: str, direction: str, delta_min: float, delta_max: float,
          dte_min: int, dte_max: int) -> dict:
    """Fetch + filter + rank. Returns a dict with either 'error' or results."""
    quote = tradier_api.get_quote(symbol)
    if not quote:
        return {"error": f"no quote available for {symbol}", "status": 502}
    spot = _to_float(quote.get("last") or quote.get("close") or quote.get("bid"))

    expirations = [e for e in tradier_api.get_expirations(symbol)
                   if dte_min <= _dte_for(e) <= dte_max]
    if not expirations:
        return {"error": f"no option expirations for {symbol} within {dte_min}-{dte_max} DTE",
                "status": 404}

    want_type = "CALL" if direction == "long" else "PUT"
    matches = []
    for exp in expirations:
        for raw in tradier_api.get_chain(symbol, exp, greeks=True):
            c = _convert_contract(raw)
            if c["putCall"] != want_type:
                continue
            # Tradier put deltas are negative; band is on magnitude.
            delta_mag = abs(c["delta"])
            if not (delta_min <= delta_mag <= delta_max):
                continue
            bid, ask = c["bid"], c["ask"]
            mid = (bid + ask) / 2.0
            if bid <= 0 or mid <= 0:
                continue  # no real market on this contract
            oi, vol = c["openInterest"], c["totalVolume"]
            if oi <= 0 and vol <= 0:
                continue  # dead contract — unfillable at shown prices
            spread_pct = (ask - bid) / mid
            gamma_per_dollar = c["gamma"] / mid if c["gamma"] > 0 else 0.0
            matches.append({
                "contract":         c["symbol"],
                "type":             want_type,
                "strike":           c["strikePrice"],
                "expiration":       c["expirationDate"],
                "dte":              _dte_for(c["expirationDate"] or exp),
                "delta":            c["delta"],
                "gamma":            c["gamma"],
                "theta":            c["theta"],
                "iv_pct":           c["volatility"],
                "bid":              bid,
                "ask":              ask,
                "mid":              round(mid, 4),
                "spread_pct":       round(spread_pct, 4),
                "open_interest":    oi,
                "volume":           vol,
                "gamma_per_dollar": round(gamma_per_dollar, 6),
                "explosion_score":  round(gamma_per_dollar / (1.0 + 10.0 * spread_pct), 6),
            })

    if not matches:
        return {"error": f"no {want_type} contracts with |delta| in "
                         f"[{delta_min}, {delta_max}] and a live market found "
                         f"for {symbol} within {dte_min}-{dte_max} DTE",
                "status": 404}

    matches.sort(key=lambda m: m["explosion_score"], reverse=True)
    return {
        "symbol": symbol,
        "spot": spot,
        "direction": direction,
        "delta_band": [delta_min, delta_max],
        "dte_window": [dte_min, dte_max],
        "count": len(matches),
        "best": matches[0],
        "contracts": matches,
        "ranking": "explosion_score = (gamma/mid) / (1 + 10*spread_pct)",
        "provider": f"tradier:{os.environ.get('TRADIER_ENV') or 'sandbox'}",
        "ts": int(time.time()),
    }


@delta_explosion_bp.route("", methods=["GET"])
@delta_explosion_bp.route("/", methods=["GET"])
def delta_explosion_root():
    return jsonify({
        "product": "Delta Explosion Scanner",
        "tradier_configured": tradier_api.is_available(),
        "usage": "GET /api/delta-explosion/<symbol>?direction=long|short"
                 "&delta_min=0.32&delta_max=0.40&dte_min=5&dte_max=45",
        "default_delta_band": [DEFAULT_DELTA_MIN, DEFAULT_DELTA_MAX],
        "note": "Real Tradier greeks only — returns an error when live data "
                "is unavailable, never an estimated contract.",
    })


@delta_explosion_bp.route("/<symbol>", methods=["GET"])
def delta_explosion_scan(symbol: str):
    symbol = symbol.upper().strip()
    if not tradier_api.is_available():
        return jsonify({"error": "TRADIER_API_KEY not configured — Delta "
                                 "Explosion needs live Tradier greeks"}), 503

    direction = (request.args.get("direction") or "long").lower()
    if direction not in ("long", "short"):
        return jsonify({"error": "direction must be 'long' or 'short'"}), 400
    try:
        delta_min = float(request.args.get("delta_min", DEFAULT_DELTA_MIN))
        delta_max = float(request.args.get("delta_max", DEFAULT_DELTA_MAX))
        dte_min = int(request.args.get("dte_min", DEFAULT_DTE_MIN))
        dte_max = int(request.args.get("dte_max", DEFAULT_DTE_MAX))
    except (TypeError, ValueError):
        return jsonify({"error": "delta_min/delta_max must be floats, "
                                 "dte_min/dte_max must be ints"}), 400
    if not (0.0 < delta_min < delta_max <= 1.0):
        return jsonify({"error": "need 0 < delta_min < delta_max <= 1"}), 400
    if not (0 <= dte_min <= dte_max):
        return jsonify({"error": "need 0 <= dte_min <= dte_max"}), 400

    key = (symbol, direction, delta_min, delta_max, dte_min, dte_max)
    now = time.time()
    with _cache_lock:
        entry = _cache.get(key)
        if entry and now - entry["ts"] < _CACHE_TTL:
            return jsonify(entry["payload"]), entry["code"]

    result = _scan(symbol, direction, delta_min, delta_max, dte_min, dte_max)
    code = result.pop("status", 200) if "error" in result else 200
    payload = clean_data(result)
    with _cache_lock:
        _cache[key] = {"ts": now, "payload": payload, "code": code}
    if code == 200:
        logger.info(f"[DELTA-EXPLOSION] {symbol} {direction} → "
                    f"{result['count']} contracts, best {result['best']['contract']}")
    return jsonify(payload), code
