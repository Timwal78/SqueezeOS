"""
741 Pure Macro Matrix — Internal Regime Engine
===============================================
_compute_regime() is the primary interface — call it directly from server-side code.

The single HTTP route (/api/macro/<symbol>) is secret-gated via X-Macro-Secret header.
It exists ONLY for the Windows Robinhood executor (which can't import Python modules).

Public 741 regime data is a paid product — use GET /api/741macro (x402, 0.04 RLUSD).

Data source: Tradier daily OHLCV — DEVELOPER_MANIFESTO §3 compliant.
Cache: 1 hour per symbol (daily EMAs are intraday-stable).
"""
from __future__ import annotations

import os
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict

from flask import Blueprint, jsonify, request

logger = logging.getLogger("macro-matrix")

macro_bp = Blueprint("macro", __name__)

MACRO_PERIODS  = [30, 60, 90, 120, 741]
_REQUIRED_BARS = 791          # 741 + 50 warmup buffer
_CACHE_TTL     = 3600         # 1 hour — daily EMAs don't shift intraday
_cache: Dict[str, Dict[str, Any]] = {}


def _compute_regime(symbol: str) -> Dict[str, Any]:
    """
    Compute 741 Pure Macro regime for a symbol.
    Importable directly by server-side code — no HTTP call needed.
    Returns regime + all 5 EMA layers.
    """
    cached = _cache.get(symbol)
    if cached and time.time() - cached["ts"] < _CACHE_TTL:
        return cached["data"]

    try:
        from tradier_api import get_history_df
        df = get_history_df(symbol, days=_REQUIRED_BARS + 60)
    except Exception as e:
        logger.warning(f"[741-MACRO] {symbol} data fetch error: {e}")
        return {"symbol": symbol, "regime": "UNKNOWN", "status": "DATA_ERROR"}

    if df is None or len(df) < _REQUIRED_BARS:
        return {
            "symbol": symbol,
            "regime": "INSUFFICIENT_DATA",
            "status": "INSUFFICIENT_DATA",
            "bars": int(len(df)) if df is not None else 0,
        }

    close = df["Close"].astype(float)
    emas  = {p: float(close.ewm(span=p, adjust=False).mean().iloc[-1])
             for p in MACRO_PERIODS}

    e30, e60, e90, e120, e741 = (emas[p] for p in MACRO_PERIODS)
    price  = float(close.iloc[-1])
    spread = round((e30 - e741) / e741 * 100, 2) if e741 else 0.0

    if   e30 > e60 > e90 > e120 > e741:
        regime = "PERFECT_BULLISH_REGIME"
    elif e30 < e60 < e90 < e120 < e741:
        regime = "PERFECT_BEARISH_REGIME"
    else:
        regime = "CONSOLIDATION_CHOP"

    result = {
        "symbol":            symbol,
        "status":            "ok",
        "regime":            regime,
        "price":             round(price, 2),
        "matrix_spread_pct": spread,
        "layers":            {f"EMA_{p}": round(emas[p], 2) for p in MACRO_PERIODS},
        "timestamp":         datetime.now(timezone.utc).isoformat(),
    }
    _cache[symbol] = {"ts": time.time(), "data": result}
    logger.info(f"[741-MACRO] {symbol} → {regime} (spread={spread:+.1f}%)")
    return result


_SECRET = os.environ.get("MACRO_GATE_SECRET", "")


@macro_bp.route("/macro/<symbol>", methods=["GET"])
def macro_single(symbol: str):
    """Internal executor gate — requires X-Macro-Secret header. Not a public product."""
    if not _SECRET or request.headers.get("X-Macro-Secret") != _SECRET:
        return jsonify({"error": "unauthorized"}), 403
    result = _compute_regime(symbol.upper().strip())
    return jsonify({"status": "success", **result})
