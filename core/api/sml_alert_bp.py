"""
SML Sovereign Harmonic Matrix v7.0 — Alert Receiver & Signal Store

Receives TradingView webhook alerts from the SML BASE-4 SOVEREIGN HARMONIC MATRIX v7.0
Pine Script indicator. Stores signal state per symbol with 30-min TTL and serves it to
the Robinhood executor (tools/robinhood_executor_sml.py).

Signal hierarchy (strongest → weakest):
  FULL_SPECTRUM       conviction=100  9/9 sets converged
  PRIME_INSTITUTIONAL conviction=90   Full MTF stack aligned
  APEX_SINGULARITY    conviction=80   7+ sets converged
  PRIME_SIGNAL        conviction=75   Apex + compressed volatility
  CRITICAL_MASS       conviction=55   5+ sets converged
  MTF_STACK           conviction=40   Multi-timeframe confirmed
  CONVERGENCE         conviction=30   3+ sets converged
  RELEASED            conviction=0    Convergence broken → EXIT

Endpoints (all free — no x402 gate):
  GET  /api/sml/info            Endpoint discovery + integration guide
  POST /api/sml/alert           TradingView webhook ingest
  GET  /api/sml/signal/{symbol} Current signal for a symbol (executor poll)
  GET  /api/sml/signals         All active signals
  POST /api/sml/trade           Executor posts completed trades here
  GET  /api/sml/trades          View recent trade history (last 100)

TradingView webhook setup:
  URL:  https://squeezeos-api.onrender.com/api/sml/alert?secret=<SML_WEBHOOK_SECRET>
  Body: {"ticker":"{{ticker}}","interval":"{{interval}}","message":"{{strategy.order.alert_message}}","time":"{{time}}"}
"""

from __future__ import annotations

import hmac
import logging
import os
import re
import time

from flask import Blueprint, jsonify, request

logger = logging.getLogger("SML-Alert")

sml_alert_bp = Blueprint("sml_alert", __name__)

_SIGNAL_TTL = 1800.0  # 30-minute expiry per signal

# In-memory store: symbol → signal entry dict
_signals: dict = {}

# Signal patterns ordered strongest-first so the first match wins
_SIGNAL_PATTERNS: list[tuple] = [
    (re.compile(r"FULL SPECTRUM CONVERGENCE"),  "FULL_SPECTRUM",        100, "ENTER_MAX"),
    (re.compile(r"PRIME INSTITUTIONAL SETUP"),  "PRIME_INSTITUTIONAL",   90, "ENTER_FULL"),
    (re.compile(r"APEX SINGULARITY"),           "APEX_SINGULARITY",      80, "ENTER"),
    (re.compile(r"PRIME SIGNAL"),               "PRIME_SIGNAL",          75, "ENTER"),
    (re.compile(r"CRITICAL MASS CONVERGENCE"),  "CRITICAL_MASS",         55, "PREPARE"),
    (re.compile(r"MTF STACK CONFIRMED"),        "MTF_STACK",             40, "WATCH"),
    (re.compile(r"MULTI-FRAME CONVERGENCE"),    "CONVERGENCE",           30, "WATCH"),
    (re.compile(r"CONVERGENCE RELEASED"),       "RELEASED",               0, "EXIT"),
]

_SYMBOL_RE = re.compile(r"—\s+([A-Z]{1,10})\s+\d+\s+\[SML")


def _parse_signal(message: str) -> dict | None:
    for pattern, signal_type, conviction, action in _SIGNAL_PATTERNS:
        if pattern.search(message):
            return {"signal_type": signal_type, "conviction": conviction, "action": action}
    return None


def _parse_symbol(message: str) -> str | None:
    m = _SYMBOL_RE.search(message)
    return m.group(1) if m else None


def _purge_expired():
    now = time.time()
    stale = [s for s, v in _signals.items() if v["expires_at"] < now]
    for s in stale:
        del _signals[s]


# ─────────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────────

@sml_alert_bp.route("/info", methods=["GET"])
def sml_info():
    return jsonify({
        "name": "SML Sovereign Harmonic Matrix — Signal API",
        "version": "7.0",
        "description": (
            "TradingView webhook receiver for the SML BASE-4 SOVEREIGN HARMONIC MATRIX v7.0 "
            "Pine Script indicator. Signals are stored with a 30-min TTL and served to the "
            "Robinhood executor at GET /api/sml/signal/{symbol}."
        ),
        "signal_hierarchy": [
            {"type": "FULL_SPECTRUM",       "label": "Full Spectrum Convergence (9/9 sets)", "conviction": 100, "action": "ENTER_MAX"},
            {"type": "PRIME_INSTITUTIONAL", "label": "Prime Institutional Setup",            "conviction": 90,  "action": "ENTER_FULL"},
            {"type": "APEX_SINGULARITY",    "label": "Apex Singularity (7+ sets)",           "conviction": 80,  "action": "ENTER"},
            {"type": "PRIME_SIGNAL",        "label": "Prime Signal (Apex + Compressed Vol)", "conviction": 75,  "action": "ENTER"},
            {"type": "CRITICAL_MASS",       "label": "Critical Mass (5+ sets)",              "conviction": 55,  "action": "PREPARE"},
            {"type": "MTF_STACK",           "label": "MTF Stack Confirmed",                  "conviction": 40,  "action": "WATCH"},
            {"type": "CONVERGENCE",         "label": "Multi-Frame Convergence (3+ sets)",    "conviction": 30,  "action": "WATCH"},
            {"type": "RELEASED",            "label": "Convergence Released",                 "conviction": 0,   "action": "EXIT"},
        ],
        "endpoints": {
            "ingest":  "POST /api/sml/alert",
            "signal":  "GET  /api/sml/signal/{symbol}",
            "all":     "GET  /api/sml/signals",
        },
        "tradingview_webhook": {
            "url": "https://squeezeos-api.onrender.com/api/sml/alert?secret=<SML_WEBHOOK_SECRET>",
            "body": '{"ticker":"{{ticker}}","interval":"{{interval}}","message":"{{strategy.order.alert_message}}","time":"{{time}}"}',
            "auth_env_var": "SML_WEBHOOK_SECRET",
            "note": "Leave SML_WEBHOOK_SECRET unset to accept all inbound alerts (dev mode).",
        },
        "active_signals": len(_signals),
        "ttl_seconds": _SIGNAL_TTL,
    })


@sml_alert_bp.route("/alert", methods=["POST"])
@sml_alert_bp.route("/alert/", methods=["POST"])
def ingest_alert():
    """TradingView webhook receiver. Optional auth via SML_WEBHOOK_SECRET query param."""
    secret_env = os.environ.get("SML_WEBHOOK_SECRET", "").strip()
    if secret_env:
        provided = request.args.get("secret", "").strip()
        if not hmac.compare_digest(provided, secret_env):
            return jsonify({"error": "Unauthorized"}), 401

    body = request.get_json(silent=True) or {}

    # Fallback: accept plain-text body (some TradingView plans send raw message string)
    if not body:
        raw = request.get_data(as_text=True).strip()
        body = {"message": raw} if raw else {}

    message = (body.get("message") or body.get("alert_message") or "").strip()
    if not message:
        return jsonify({"error": "No message field in payload"}), 400

    symbol = (
        body.get("ticker") or
        body.get("symbol") or
        _parse_symbol(message) or
        "UNKNOWN"
    ).upper().strip()

    timeframe = str(body.get("interval", ""))

    parsed = _parse_signal(message)
    if not parsed:
        logger.warning("[SML] Unrecognized alert for %s: %s", symbol, message)
        return jsonify({"error": "Unrecognized SML signal format", "raw": message}), 422

    now = time.time()
    entry = {
        "symbol":      symbol,
        "signal_type": parsed["signal_type"],
        "conviction":  parsed["conviction"],
        "action":      parsed["action"],
        "timeframe":   timeframe,
        "received_at": now,
        "expires_at":  now + _SIGNAL_TTL,
        "raw":         message,
    }
    _signals[symbol] = entry
    _purge_expired()

    logger.info("[SML] %s → %s (conviction=%d)", symbol, parsed["signal_type"], parsed["conviction"])
    return jsonify({
        "status":           "accepted",
        "symbol":           symbol,
        "signal_type":      parsed["signal_type"],
        "conviction":       parsed["conviction"],
        "action":           parsed["action"],
        "expires_in_seconds": _SIGNAL_TTL,
    })


@sml_alert_bp.route("/signal/<symbol>", methods=["GET"])
def get_signal(symbol: str):
    _purge_expired()
    sym   = symbol.upper().strip()
    entry = _signals.get(sym)
    if not entry:
        return jsonify({
            "symbol":      sym,
            "signal_type": "NONE",
            "conviction":  0,
            "action":      "WATCH",
            "active":      False,
            "expires_at":  None,
        })
    return jsonify({
        **entry,
        "active":               True,
        "ttl_remaining_seconds": round(max(0.0, entry["expires_at"] - time.time()), 1),
    })


@sml_alert_bp.route("/signals", methods=["GET"])
def get_all_signals():
    _purge_expired()
    now    = time.time()
    result = [
        {**v, "active": True, "ttl_remaining_seconds": round(max(0.0, v["expires_at"] - now), 1)}
        for v in sorted(_signals.values(), key=lambda x: x["conviction"], reverse=True)
    ]
    return jsonify({"count": len(result), "signals": result, "ts": now})


# ─────────────────────────────────────────────────────────────────────────────
# Trade log — executor POSTs completed trades here; operators GET to review
# ─────────────────────────────────────────────────────────────────────────────

_trades: list[dict] = []   # ring buffer, capped at 100 entries
_MAX_TRADES = 100


@sml_alert_bp.route("/trade", methods=["POST"])
def record_trade():
    """
    Executor posts a completed trade record here.
    Optional auth via SML_WEBHOOK_SECRET (same secret as /alert).
    """
    secret_env = os.environ.get("SML_WEBHOOK_SECRET", "").strip()
    if secret_env:
        provided = request.args.get("secret", "").strip()
        if not hmac.compare_digest(provided, secret_env):
            return jsonify({"error": "Unauthorized"}), 401

    body = request.get_json(silent=True) or {}
    if not body.get("symbol") or not body.get("action"):
        return jsonify({"error": "symbol and action required"}), 400

    entry = {
        "symbol":              body.get("symbol", "").upper(),
        "action":              body.get("action", "").upper(),   # BUY / EXIT / BUY_CALL / BUY_PUT
        "asset_type":          body.get("asset_type", "equity"), # equity / call / put
        "signal_type":         body.get("signal_type", ""),
        "combined_conviction": body.get("combined_conviction", 0),
        "sqz_bias":            body.get("sqz_bias", ""),
        "dollars":             body.get("dollars", 0),
        "shares":              body.get("shares", 0),
        "price":               body.get("price", 0),
        "pnl":                 body.get("pnl"),
        "mode":                body.get("mode", "paper"),        # paper / live
        # options fields (populated when asset_type != equity)
        "strike":              body.get("strike"),
        "expiry":              body.get("expiry"),
        "option_type":         body.get("option_type"),
        "contracts":           body.get("contracts"),
        "ts":                  body.get("ts", time.time()),
    }
    _trades.append(entry)
    if len(_trades) > _MAX_TRADES:
        del _trades[0]

    logger.info("[SML-Trade] %s %s %s | conviction=%s | mode=%s",
                entry["action"], entry["symbol"], entry["asset_type"],
                entry["combined_conviction"], entry["mode"])
    return jsonify({"status": "recorded", "total_logged": len(_trades)})


@sml_alert_bp.route("/trades", methods=["GET"])
def get_trades():
    """View recent trade history — last 100 entries, newest first."""
    limit  = min(int(request.args.get("limit", 50)), _MAX_TRADES)
    symbol = request.args.get("symbol", "").upper()
    trades = list(reversed(_trades))
    if symbol:
        trades = [t for t in trades if t["symbol"] == symbol]
    trades = trades[:limit]

    # Simple P&L summary
    pnl_list  = [t["pnl"] for t in _trades if t.get("pnl") is not None]
    total_pnl = round(sum(pnl_list), 2) if pnl_list else None

    return jsonify({
        "count":      len(trades),
        "total_pnl":  total_pnl,
        "trades":     trades,
        "ts":         time.time(),
    })
