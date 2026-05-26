"""
GET /api/ema/<symbol>
====================
Returns the full SML Proprietary EMA Suite output for any symbol.

Engine 1: Tesla Sequence (1-24-578-963) — price elastic stretch
Engine 3: Lucas/Phi² Sequence (11-47-123-321) — dark-pool volume accumulation
"""

import logging
import time
from flask import Blueprint, jsonify, request
from core.legacy import get_service, clean_data
from core.proprietary_ema_engine import run_proprietary_suite

logger = logging.getLogger("SML.PropEMA.API")
proprietary_ema_bp = Blueprint("proprietary_ema", __name__)

_cache: dict = {}
_CACHE_TTL = 60  # seconds


def _fetch_bars(dm, symbol: str, limit: int = 400):
    """Pull historical bars; return (closes, volumes) or ([], [])."""
    try:
        bars = dm.get_historical_bars(symbol, timeframe="1Day", limit=limit)
        if not bars:
            bars = dm.get_historical_bars(symbol, timeframe="1Min", limit=limit)
        if not bars:
            return [], []
        closes  = [float(b.get("c") or b.get("close",  0)) for b in bars if b.get("c") or b.get("close")]
        volumes = [float(b.get("v") or b.get("volume", 0)) for b in bars if b.get("v") or b.get("volume")]
        return closes, volumes
    except Exception as e:
        logger.warning(f"[PropEMA] Bar fetch failed for {symbol}: {e}")
        return [], []


@proprietary_ema_bp.route("/ema/<symbol>", methods=["GET"])
def proprietary_ema_signal(symbol):
    symbol = symbol.upper().strip()
    now = time.time()

    cached = _cache.get(symbol)
    if cached and (now - cached["ts"]) < _CACHE_TTL:
        return jsonify(cached["data"])

    dm = get_service("dm")
    if not dm:
        return jsonify({"status": "error", "message": "DataManager unavailable"}), 503

    closes, volumes = _fetch_bars(dm, symbol)

    if len(closes) < 11:
        return jsonify({
            "status":  "error",
            "symbol":  symbol,
            "message": f"Insufficient price history ({len(closes)} bars). Need ≥11.",
        }), 422

    result = run_proprietary_suite(closes, volumes, symbol=symbol)

    payload = {
        "status":    "success",
        "symbol":    symbol,
        "timestamp": now,
        "bars_used": len(closes),
        "ema_suite": result,
        "meta": {
            "engine_1": "Tesla Sequence 1-24-578-963 — Price Elastic Stretch",
            "engine_3": "Lucas Phi² Sequence 11-47-123-321 — Dark-Pool Volume Accumulation",
        },
    }

    _cache[symbol] = {"ts": now, "data": clean_data(payload)}
    return jsonify(clean_data(payload))
