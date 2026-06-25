"""
SML Sovereign Signal Suite — proprietary-clean signal endpoints.

PROPRIETARY DATA POLICY (non-negotiable, permanent):
  ALL outputs are directional labels ONLY.
  No EMA values, crossover levels, spreads, price data, raw indicator
  readings, or numeric indicator output may ever appear in any response
  from this module — not in error messages, not in debug fields, not ever.
  The underlying engines remain black-box.

Routes (all under /api/signals/ prefix):
  GET /api/signals/info                — free catalog, no auth
  GET /api/signals/741/<symbol>        — 0.02 RLUSD
  GET /api/signals/365/<symbol>        — 0.03 RLUSD
  GET /api/signals/triplelock/<symbol> — 0.05 RLUSD
  GET/POST /api/signals/full/<symbol>  — 0.10 RLUSD

Payment: X-Payment-Token (RLUSD) OR X-API-Key (sml_live_*) OR X-Owner-Key
"""

import os
import time
import logging
from flask import Blueprint, jsonify, make_response, request

from core.legacy import clean_data, get_service

logger = logging.getLogger("SML-Signals")

signal_products_bp = Blueprint("signal_products", __name__)

# ── Endpoint UUIDs (must match proof402_integration.ENDPOINTS) ───────────────
_ENDPOINT_IDS = {
    "/api/signals/741":        "e5f6a7b8-c9d0-1234-5678-901234567890",
    "/api/signals/365":        "f6a7b8c9-d0e1-2345-6789-012345678901",
    "/api/signals/triplelock": "a7b8c9d0-e1f2-3456-789a-123456789012",
    "/api/signals/full":       "b8c9d0e1-f2a3-4567-89ab-234567890123",
}

_PRICES = {
    "/api/signals/741":        0.02,
    "/api/signals/365":        0.03,
    "/api/signals/triplelock": 0.05,
    "/api/signals/full":       0.10,
}

# ── Proprietary output label maps ─────────────────────────────────────────────
_741_LABELS = {
    "PERFECT_BULLISH_REGIME": "BULLISH HIGHWAY",
    "PERFECT_BEARISH_REGIME": "BEARISH HIGHWAY",
    "CONSOLIDATION_CHOP":     "CONSOLIDATION",
}

# ── Per-route in-memory caches ────────────────────────────────────────────────
_cache_741:  dict = {}
_cache_365:  dict = {}
_cache_tl:   dict = {}
_cache_full: dict = {}

_TTL_741  = 60
_TTL_365  = 300   # 365-EMA moves slowly — 5-min cache
_TTL_TL   = 60
_TTL_FULL = 60


# ── Inline payment gate ───────────────────────────────────────────────────────

def _check_payment(base_path: str):
    """
    Returns (authorized: bool, http_response_or_None).
    Priority: owner/agent env key → sml_live_* Redis key → RLUSD token → 402.
    Mirrors the logic in proof402_integration.require_payment exactly.
    """
    from proof402_integration import (
        ENDPOINTS, OWNER_API_KEY, PROOF402_SERVER,
        _verify_token_local, _issue_invoice,
    )

    endpoint_id = ENDPOINTS.get(base_path) or _ENDPOINT_IDS.get(base_path, "")

    # 1. Static env keys (owner, operator, agent CSV)
    auth_header = request.headers.get("Authorization", "")
    bearer = auth_header.split("Bearer ")[-1].strip() if "Bearer " in auth_header else ""
    passed_key = (
        request.headers.get("X-Owner-Key", "")
        or request.headers.get("X-API-Key", "")
        or bearer
    )

    if passed_key:
        agent_keys = [
            k.strip()
            for k in os.getenv("AGENT_API_KEYS", "").split(",")
            if k.strip()
        ]
        valid_keys = [
            k for k in [os.getenv("OPERATOR_API_KEY"), OWNER_API_KEY] if k
        ] + agent_keys
        if passed_key in valid_keys:
            return True, None

        # 2. Stripe sml_live_* keys (Redis)
        if passed_key.startswith("sml_live_"):
            try:
                import redis as _redis
                import json as _json
                r = _redis.from_url(
                    os.getenv("REDIS_URL", "redis://localhost:6379"),
                    decode_responses=True,
                )
                raw = r.get(f"apikey:{passed_key}")
                if raw:
                    kd = _json.loads(raw)
                    if kd.get("active"):
                        return True, None
            except Exception as e:
                logger.debug("[SIG-PAY] Redis lookup: %s", e)

    # 3. RLUSD payment token
    token = (
        request.headers.get("X-Payment-Token", "")
        or request.args.get("payment_token", "")
    )
    if token:
        result = _verify_token_local(token)
        if result.get("valid"):
            token_eid = result.get("endpoint_id", "")
            if token_eid and endpoint_id and token_eid != endpoint_id:
                return False, make_response(jsonify({
                    "error":   "ERR_ENDPOINT_MISMATCH",
                    "message": "Token was issued for a different endpoint.",
                    "remedy":  (
                        f"POST {PROOF402_SERVER}/v1/invoice "
                        f"{{\"endpoint_id\": \"{endpoint_id}\"}} to get a token for {base_path}."
                    ),
                }), 401)
            return True, None

    # 4. Issue 402
    price = _PRICES.get(base_path, 0.05)
    try:
        invoice = _issue_invoice(endpoint_id) if endpoint_id else {}
    except Exception:
        invoice = {}

    return False, make_response(jsonify({
        "error":    "ERR_PAYMENT_REQUIRED",
        "endpoint": base_path,
        "required": f"{price} RLUSD",
        "accepts":  [{
            "protocol":    "x402",
            "network":     "XRPL",
            "asset":       "RLUSD",
            "amount":      str(price),
            "endpoint_id": endpoint_id,
            "pay_to":      invoice.get("pay_to", ""),
            "memo_hex":    invoice.get("memo_hex", ""),
            "invoice_id":  invoice.get("invoice_id", ""),
        }],
        "instructions": {
            "step1": (
                f"POST {PROOF402_SERVER}/v1/invoice "
                f"{{\"endpoint_id\": \"{endpoint_id}\"}}"
            ),
            "step2": "pay RLUSD on XRPL to pay_to with MemoData=memo_hex",
            "step3": "POST /v1/verify with invoice_id + tx_hash → receive payment_token",
            "step4": f"retry {base_path} with X-Payment-Token: <payment_token>",
        },
        "free_preview": "/api/signals/info",
    }), 402)


# ── Signal computation — labels only, no raw values ──────────────────────────

def _get_741_signal(symbol: str) -> dict:
    """741 matrix alignment → BULLISH HIGHWAY | BEARISH HIGHWAY | CONSOLIDATION."""
    try:
        from core.api.macro741_bp import _calculate_matrix_stack, MACRO_PERIODS
        if not MACRO_PERIODS:
            return {
                "error":   "741_MACRO_UNCONFIGURED",
                "message": "MACRO_STACK_CSV not set on this server.",
            }

        raw = _calculate_matrix_stack(symbol)
        if "error" in raw:
            return {"error": raw["error"], "message": raw.get("message", "")}

        alignment = raw.get("structural_alignment", "CONSOLIDATION_CHOP")
        return {
            "symbol":        symbol,
            "signal":        _741_LABELS.get(alignment, "CONSOLIDATION"),
            "squeeze_alert": bool(raw.get("squeeze_alert", False)),
            "source":        "sml_741_matrix",
        }
    except Exception as e:
        logger.warning("[SIG-741] %s: %s", symbol, e)
        return {"error": "SIGNAL_UNAVAILABLE", "message": "741 matrix unavailable."}


def _get_365_signal(symbol: str) -> dict:
    """365-day EMA anchor → ABOVE | BELOW. No raw EMA value surfaced."""
    from core.api.macro741_bp import _compute_ema

    # Tradier (preferred)
    try:
        from tradier_api import get_history_df
        df = get_history_df(symbol, days=600, interval="daily")
        if df is not None and len(df) >= 370:
            closes = df["Close"].dropna().tolist()
            ema365 = _compute_ema(closes, 365)
            if ema365 is not None:
                return {
                    "symbol": symbol,
                    "signal": "ABOVE" if closes[-1] > ema365 else "BELOW",
                    "source": "ema_365_daily_tradier",
                }
    except Exception as e:
        logger.debug("[SIG-365] tradier: %s", e)

    # Alpaca fallback
    try:
        from data_providers import AlpacaProvider
        alp = AlpacaProvider()
        if not alp.available:
            return {"error": "DATA_UNAVAILABLE", "message": "No data source available."}
        bars = alp.get_historical_bars(symbol, timeframe="1Day", limit=600)
        if not bars or len(bars) < 370:
            return {
                "error":   "INSUFFICIENT_HISTORY",
                "message": f"Need ≥370 daily bars; got {len(bars) if bars else 0}.",
            }
        closes = [
            float(b.get("c") or b.get("close", 0))
            for b in bars
            if b.get("c") or b.get("close")
        ]
        ema365 = _compute_ema(closes, 365)
        if ema365 is None:
            return {"error": "EMA_COMPUTE_FAILED", "message": "Insufficient bars for 365-EMA."}
        return {
            "symbol": symbol,
            "signal": "ABOVE" if closes[-1] > ema365 else "BELOW",
            "source": "ema_365_daily_alpaca",
        }
    except Exception as e:
        logger.warning("[SIG-365] %s: %s", symbol, e)
        return {"error": "SIGNAL_UNAVAILABLE", "message": "365-EMA unavailable."}


def _get_tl_signal(symbol: str) -> dict:
    """Triple Lock consensus → LOCKED BULL | LOCKED BEAR | FORMING | UNLOCKED."""
    try:
        from core.api.triple_lock_bp import _build_verdict, _fetch_bars, MIN_BARS
        dm = get_service("dm")
        if not dm:
            return {"error": "DATA_UNAVAILABLE", "message": "Data manager not running."}

        closes, volumes = _fetch_bars(dm, symbol)
        if len(closes) < MIN_BARS:
            return {
                "error":   "INSUFFICIENT_DATA",
                "message": f"Need ≥{MIN_BARS} bars; got {len(closes)}.",
            }

        verdict   = _build_verdict(symbol, closes, volumes)
        directive = verdict.get("directive", "NO_TRIPLE_LOCK")
        consensus = verdict.get("consensus", "NEUTRAL")

        if directive == "TRIPLE_LOCK_BULL":
            label = "LOCKED BULL"
        elif directive == "TRIPLE_LOCK_BEAR":
            label = "LOCKED BEAR"
        elif consensus in ("BULLISH", "BEARISH"):
            label = "FORMING"
        else:
            label = "UNLOCKED"

        return {"symbol": symbol, "signal": label, "source": "sml_triple_lock"}

    except Exception as e:
        logger.warning("[SIG-TL] %s: %s", symbol, e)
        return {"error": "SIGNAL_UNAVAILABLE", "message": "Triple Lock unavailable."}


def _sovereign_verdict(sig741: dict, sig365: dict, sigtl: dict) -> str:
    """Combine three directional labels → SOVEREIGN BULL | SOVEREIGN BEAR | TRANSITIONAL | STANDBY."""
    bull = [
        sig741.get("signal") == "BULLISH HIGHWAY",
        sig365.get("signal") == "ABOVE",
        sigtl.get("signal")  == "LOCKED BULL",
    ]
    bear = [
        sig741.get("signal") == "BEARISH HIGHWAY",
        sig365.get("signal") == "BELOW",
        sigtl.get("signal")  == "LOCKED BEAR",
    ]
    if sum(bull) >= 3:
        return "SOVEREIGN BULL"
    if sum(bear) >= 3:
        return "SOVEREIGN BEAR"
    if sum(bull) >= 2 or sum(bear) >= 2:
        return "TRANSITIONAL"
    return "STANDBY"


# ── Routes ─────────────────────────────────────────────────────────────────────

@signal_products_bp.route("/info")
def signals_info():
    return jsonify({
        "name":        "SML Sovereign Signal Suite",
        "description": (
            "Directional signal labels only. No EMA values, price levels, "
            "or raw indicator readings are ever returned."
        ),
        "signals": [
            {
                "endpoint":    "/api/signals/741/<symbol>",
                "cost":        "0.02 RLUSD",
                "labels":      ["BULLISH HIGHWAY", "BEARISH HIGHWAY", "CONSOLIDATION"],
                "description": "Multi-layer macro EMA structural alignment.",
                "endpoint_id": _ENDPOINT_IDS["/api/signals/741"],
            },
            {
                "endpoint":    "/api/signals/365/<symbol>",
                "cost":        "0.03 RLUSD",
                "labels":      ["ABOVE", "BELOW"],
                "description": "Price position relative to 365-day EMA anchor.",
                "endpoint_id": _ENDPOINT_IDS["/api/signals/365"],
            },
            {
                "endpoint":    "/api/signals/triplelock/<symbol>",
                "cost":        "0.05 RLUSD",
                "labels":      ["LOCKED BULL", "LOCKED BEAR", "FORMING", "UNLOCKED"],
                "description": "SML Triple Lock three-engine consensus.",
                "endpoint_id": _ENDPOINT_IDS["/api/signals/triplelock"],
            },
            {
                "endpoint":    "/api/signals/full/<symbol>",
                "cost":        "0.10 RLUSD",
                "labels":      ["SOVEREIGN BULL", "SOVEREIGN BEAR", "TRANSITIONAL", "STANDBY"],
                "description": "All three signals combined into one sovereign verdict.",
                "endpoint_id": _ENDPOINT_IDS["/api/signals/full"],
            },
        ],
        "payment_flow": [
            "POST https://four02proof.onrender.com/v1/invoice with {\"endpoint_id\": \"<id>\"}",
            "Pay RLUSD on XRPL to pay_to with MemoData=memo_hex",
            "POST /v1/verify with invoice_id + tx_hash → receive payment_token",
            "Retry with X-Payment-Token: <payment_token>",
        ],
    })


@signal_products_bp.route("/741/<symbol>")
def signal_741(symbol: str):
    symbol = symbol.upper()
    authorized, err_resp = _check_payment("/api/signals/741")
    if not authorized:
        return err_resp

    now = time.time()
    cached = _cache_741.get(symbol)
    if cached and (now - cached["ts"]) < _TTL_741:
        return jsonify(cached["data"])

    result = _get_741_signal(symbol)
    if "error" not in result:
        _cache_741[symbol] = {"data": result, "ts": now}
    return jsonify(clean_data(result))


@signal_products_bp.route("/365/<symbol>")
def signal_365(symbol: str):
    symbol = symbol.upper()
    authorized, err_resp = _check_payment("/api/signals/365")
    if not authorized:
        return err_resp

    now = time.time()
    cached = _cache_365.get(symbol)
    if cached and (now - cached["ts"]) < _TTL_365:
        return jsonify(cached["data"])

    result = _get_365_signal(symbol)
    if "error" not in result:
        _cache_365[symbol] = {"data": result, "ts": now}
    return jsonify(clean_data(result))


@signal_products_bp.route("/triplelock/<symbol>")
def signal_triplelock(symbol: str):
    symbol = symbol.upper()
    authorized, err_resp = _check_payment("/api/signals/triplelock")
    if not authorized:
        return err_resp

    now = time.time()
    cached = _cache_tl.get(symbol)
    if cached and (now - cached["ts"]) < _TTL_TL:
        return jsonify(cached["data"])

    result = _get_tl_signal(symbol)
    if "error" not in result:
        _cache_tl[symbol] = {"data": result, "ts": now}
    return jsonify(clean_data(result))


@signal_products_bp.route("/full/<symbol>", methods=["GET", "POST"])
def signal_full(symbol: str):
    symbol = symbol.upper()
    authorized, err_resp = _check_payment("/api/signals/full")
    if not authorized:
        return err_resp

    now = time.time()
    cached = _cache_full.get(symbol)
    if cached and (now - cached["ts"]) < _TTL_FULL:
        return jsonify(cached["data"])

    sig741 = _get_741_signal(symbol)
    sig365 = _get_365_signal(symbol)
    sigtl  = _get_tl_signal(symbol)

    verdict = _sovereign_verdict(sig741, sig365, sigtl)

    # Strict proprietary policy: only directional labels, squeeze_alert bool, ts
    result = {
        "symbol":        symbol,
        "verdict":       verdict,
        "signals": {
            "741":        sig741.get("signal", "UNAVAILABLE"),
            "365":        sig365.get("signal", "UNAVAILABLE"),
            "triplelock": sigtl.get("signal", "UNAVAILABLE"),
        },
        "squeeze_alert": sig741.get("squeeze_alert", False),
        "source":        "sml_sovereign_stack",
        "ts":            now,
    }

    all_ok = "error" not in sig741 and "error" not in sig365 and "error" not in sigtl
    if all_ok:
        _cache_full[symbol] = {"data": result, "ts": now}

    # SSE broadcast on high-conviction sovereign reads
    if verdict in ("SOVEREIGN BULL", "SOVEREIGN BEAR"):
        try:
            import core.app as _core_app
            _broadcast = getattr(_core_app, "_broadcast_sse_global", None)
            if _broadcast:
                _broadcast({
                    "type":          verdict.replace(" ", "_"),
                    "symbol":        symbol,
                    "signals":       result["signals"],
                    "squeeze_alert": result["squeeze_alert"],
                    "ts":            now,
                })
        except Exception:
            pass

    return jsonify(clean_data(result))
