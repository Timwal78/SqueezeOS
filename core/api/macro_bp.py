"""
741 Pure Macro Matrix — Internal Regime Engine
===============================================
_compute_regime() is the primary interface — call it directly from server-side code.

The single HTTP route (/api/macro/<symbol>) is secret-gated via X-Macro-Secret header.
It exists ONLY for the Windows Robinhood executor (which can't import Python modules).

Public 741 regime data is a paid product — use GET /api/741macro (x402, 0.04 RLUSD).

Data source: Tradier daily OHLCV — DEVELOPER_MANIFESTO §3 compliant.
Cache: 1 hour per symbol (daily regime is intraday-stable).
"""
from __future__ import annotations

import os
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List

from flask import Blueprint, jsonify, request

logger = logging.getLogger("macro-matrix")

macro_bp = Blueprint("macro", __name__)

# Stack configuration — loaded from env so the methodology stays out of source.
# Set MACRO_STACK_CSV in Render environment variables.
_raw = os.environ.get("MACRO_STACK_CSV", "")
_STACK: List[int] = [int(x) for x in _raw.split(",") if x.strip().isdigit()] if _raw else []
_WARMUP = int(os.environ.get("MACRO_STACK_WARMUP", "50"))
_REQUIRED_BARS = (max(_STACK) + _WARMUP) if _STACK else 0
_CACHE_TTL = 3600
_cache: Dict[str, Dict[str, Any]] = {}


def _compute_regime(symbol: str) -> Dict[str, Any]:
    """
    Compute 741 Pure Macro regime for a symbol.
    Importable directly by server-side code — no HTTP call needed.
    Returns regime + opaque layer values (L1–L5, short to long).
    """
    if not _STACK:
        logger.warning("[741-MACRO] MACRO_STACK_CSV not configured")
        return {"symbol": symbol, "regime": "UNKNOWN", "status": "NOT_CONFIGURED"}

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
    ema_values = [float(close.ewm(span=p, adjust=False).mean().iloc[-1]) for p in _STACK]

    price  = float(close.iloc[-1])
    spread = round((ema_values[0] - ema_values[-1]) / ema_values[-1] * 100, 2) if ema_values[-1] else 0.0

    if all(ema_values[i] > ema_values[i + 1] for i in range(len(ema_values) - 1)):
        regime = "PERFECT_BULLISH_REGIME"
    elif all(ema_values[i] < ema_values[i + 1] for i in range(len(ema_values) - 1)):
        regime = "PERFECT_BEARISH_REGIME"
    else:
        regime = "CONSOLIDATION_CHOP"

    result = {
        "symbol":            symbol,
        "status":            "ok",
        "regime":            regime,
        "price":             round(price, 2),
        "matrix_spread_pct": spread,
        "layers":            {f"L{i + 1}": round(v, 2) for i, v in enumerate(ema_values)},
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
