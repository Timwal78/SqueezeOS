"""
741 Pure Macro Matrix — Regime Scanner
=======================================
Computes EMAs [30, 60, 90, 120, 741] on daily bars to classify macro regime.

  PERFECT_BULLISH_REGIME  — full stack stacked bullish; institutional highway
  PERFECT_BEARISH_REGIME  — full stack stacked bearish; avoid longs
  CONSOLIDATION_CHOP      — mixed/neutral; watch for coil + breakout

Data source: Tradier daily OHLCV — DEVELOPER_MANIFESTO §3 compliant.
Cache: 1 hour per symbol (daily EMAs are intraday-stable).

Endpoints:
  GET /api/macro             → batch scan of live universe
  GET /api/macro/<symbol>    → single-symbol regime check
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict

from flask import Blueprint, jsonify

logger = logging.getLogger("macro-matrix")

macro_bp = Blueprint("macro", __name__)

MACRO_PERIODS  = [30, 60, 90, 120, 741]
_REQUIRED_BARS = 791          # 741 + 50 warmup buffer
_CACHE_TTL     = 3600         # 1 hour — daily EMAs don't shift intraday
_cache: Dict[str, Dict[str, Any]] = {}


def _compute_regime(symbol: str) -> Dict[str, Any]:
    """Fetch daily bars from Tradier and compute 741 Pure Macro regime."""
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


@macro_bp.route("/macro", methods=["GET"])
@macro_bp.route("/macro/", methods=["GET"])
def macro_batch():
    from core.state import state
    from core.oracle_engine import ORACLE_SYMBOLS
    symbols = list(state.quotes.keys()) if state.quotes else ORACLE_SYMBOLS
    regimes = {sym: _compute_regime(sym) for sym in symbols}
    summary = {
        "PERFECT_BULLISH_REGIME":  [s for s, r in regimes.items() if r["regime"] == "PERFECT_BULLISH_REGIME"],
        "PERFECT_BEARISH_REGIME":  [s for s, r in regimes.items() if r["regime"] == "PERFECT_BEARISH_REGIME"],
        "CONSOLIDATION_CHOP":      [s for s, r in regimes.items() if r["regime"] == "CONSOLIDATION_CHOP"],
    }
    return jsonify({
        "status":         "success",
        "universe_size":  len(symbols),
        "summary":        summary,
        "regimes":        regimes,
        "timestamp":      datetime.now(timezone.utc).isoformat(),
    })


@macro_bp.route("/macro/<symbol>", methods=["GET"])
def macro_single(symbol: str):
    result = _compute_regime(symbol.upper().strip())
    return jsonify({"status": "success", **result})
