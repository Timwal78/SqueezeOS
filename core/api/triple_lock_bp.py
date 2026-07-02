"""
TRIPLE_LOCK_VERDICT — the rarest premium signal SqueezeOS publishes.

Only returns BULL/BEAR when all three proprietary engines align across three
independent market dimensions:

  Engine 1 (PRICE — macro stretch)     → bull_stack OR bear_stack
  Engine 3 (VOLUME — dark-pool kinetics) → mirror_lock_bull OR mirror_lock_bear
  Engine 4 (PRICE — ribbon harmonics)   → BULL_FAN_EXPANSION/BULL_STACK
                                          OR BEAR_FAN_EXPANSION/BEAR_STACK

The flag lives at `core/proprietary_ema_engine.py:399-404`. It already exists
in `run_proprietary_suite` and feeds the OracleEngine — but until now it was
never surfaced as its own paid endpoint. This is that endpoint.

Why a separate tier:
  - Council (0.10 RLUSD) returns a verdict on every call.
  - Triple-Lock (0.25 RLUSD) returns BULL or BEAR only when max-conviction
    is firing. Most of the time it returns NO_TRIPLE_LOCK with the failing
    engine — that's still actionable (tells agents NOT to take max-size
    positions right now).
  - The signal is intentionally rare. Rarity is the product. Agents that
    only fire on TRIPLE_LOCK_BULL/BEAR get the highest expected-value setup
    the suite can identify.

Routes:
  GET  /api/triple-lock/info            — free discovery + tier description
  GET  /api/triple-lock/demo            — free, IWM only, 5-min cache (eval)
  POST /api/triple-lock                 — 0.25 RLUSD, any symbol
  GET  /api/triple-lock                 — same as POST, query-string variant

Internal engine parameters stay proprietary at every boundary via
`redact_suite_output`.
"""

import logging
import time

from flask import Blueprint, jsonify, request

from core.legacy import clean_data, get_service
from core.proprietary_ema_engine import redact_suite_output, run_proprietary_suite
# SML fix: was gated by x402_guard alone (Coinbase/USDC only) — agents.json
# never even listed an RLUSD endpoint_id for this route, so the documented
# RLUSD/XRPL rail never worked here. dual_payment accepts both.
from proof402_integration import dual_payment

logger = logging.getLogger("SqueezeOS-TripleLock")
triple_lock_bp = Blueprint("triple_lock", __name__)

# Paid endpoint cache — 60s per (symbol). Triple-lock is a slow-moving regime
# read; back-to-back queries on the same ticker hit the cache and are free.
_cache: dict = {}
_CACHE_TTL = 60

# Free demo cache — 5 min, IWM only (mirrors /api/demo).
_demo_cache: dict = {"ts": 0.0, "data": None}
_DEMO_CACHE_TTL = 300

MIN_BARS = 11  # engine 3 requires ≥ 11 volume bars


def _fetch_bars(dm, symbol: str, limit: int = 400):
    """Pull (closes, volumes). Returns ([], []) on any failure path."""
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
        logger.warning(f"[TRIPLE_LOCK] bar fetch failed for {symbol}: {e}")
        return [], []


def _build_verdict(symbol: str, closes: list, volumes: list) -> dict:
    """Run the proprietary suite, isolate the triple-lock determination, and
    redact internal engine params. Always returns a structured payload —
    NO_TRIPLE_LOCK is itself an actionable signal."""
    suite = run_proprietary_suite(closes, volumes, symbol=symbol)
    consensus = suite.get("consensus", "NEUTRAL")
    bull = bool(suite.get("triple_lock_bull"))
    bear = bool(suite.get("triple_lock_bear"))

    if bull:
        directive = "TRIPLE_LOCK_BULL"
        bias = "BULLISH"
        confidence = 95  # max conviction by construction — all 3 engines agree
        thesis = (
            f"{symbol}: max-conviction long. PRICE macro-stack + VOLUME mirror-lock + "
            "ribbon fan-expansion all aligned bullish. This is the rarest setup the suite "
            "publishes — historical hit rate justifies max position sizing within risk caps."
        )
    elif bear:
        directive = "TRIPLE_LOCK_BEAR"
        bias = "BEARISH"
        confidence = 95
        thesis = (
            f"{symbol}: max-conviction short. PRICE macro-stack + VOLUME mirror-lock + "
            "ribbon fan-expansion all aligned bearish. Rarest setup the suite publishes — "
            "consider max-size short or full long exit + protective hedges."
        )
    else:
        directive = "NO_TRIPLE_LOCK"
        bias = "WAIT"
        confidence = 0
        # Report which engine(s) blocked the lock so the agent knows what to watch.
        blocking = []
        e1 = suite.get("engine_1", {})
        e3 = suite.get("engine_3", {})
        e4 = suite.get("engine_4", {})
        if not (e1.get("bull_stack") or e1.get("bear_stack")):
            blocking.append("engine_1_not_stacked")
        if not (e3.get("mirror_lock_bull") or e3.get("mirror_lock_bear")):
            blocking.append("engine_3_no_mirror_lock")
        e4_sig = e4.get("signal", "")
        if e4_sig not in ("BULL_FAN_EXPANSION", "BULL_STACK", "BEAR_FAN_EXPANSION", "BEAR_STACK"):
            blocking.append("engine_4_not_strong")
        thesis = (
            f"{symbol}: max-conviction signal NOT firing. Current consensus={consensus}. "
            f"Engines blocking triple lock: {', '.join(blocking) if blocking else 'all firing but directions conflict'}. "
            "Do NOT max-size on this symbol right now — wait for full alignment."
        )

    return {
        "symbol":        symbol,
        "directive":     directive,
        "bias":          bias,
        "confidence":    confidence,
        "consensus":     consensus,
        "triple_lock_bull": bull,
        "triple_lock_bear": bear,
        "thesis":        thesis,
        "engines":       redact_suite_output(suite),
        "timestamp":     time.time(),
    }


# ── Routes ───────────────────────────────────────────────────────────────────


@triple_lock_bp.route("/info", methods=["GET"])
def info():
    """Free discovery: what this tier is and what triggers it."""
    return jsonify({
        "tier":              "TRIPLE_LOCK_VERDICT",
        "price_rlusd":       0.25,
        "fires_on":          ["TRIPLE_LOCK_BULL", "TRIPLE_LOCK_BEAR"],
        "always_returns":    "NO_TRIPLE_LOCK with blocking engine when lock is not firing",
        "engines_required":  3,
        "dimensions":        ["PRICE_STRETCH", "VOLUME_KINETICS", "PRICE_RIBBON"],
        "rarity":            "Highest-conviction signal in the SqueezeOS suite. Most calls return NO_TRIPLE_LOCK by design.",
        "use_case":          "Max-size institutional sizing. Only fires when all three proprietary engines agree on direction across three independent market dimensions.",
        "demo_endpoint":     "/api/triple-lock/demo (free, IWM only, 5-min cache)",
        "paid_endpoint":     "/api/triple-lock (any symbol)",
    })


@triple_lock_bp.route("/demo", methods=["GET"])
def demo():
    """Free preview of TRIPLE_LOCK_VERDICT, scoped to IWM. 5-minute cache.

    Same response shape as the paid endpoint. Use this to validate the
    integration and signal quality before committing 0.25 RLUSD/call on
    arbitrary symbols."""
    now = time.time()
    if _demo_cache["data"] and (now - _demo_cache["ts"]) < _DEMO_CACHE_TTL:
        return jsonify(_demo_cache["data"])

    dm = get_service("dm")
    if not dm:
        return jsonify({"status": "error", "message": "DataManager unavailable"}), 503

    closes, volumes = _fetch_bars(dm, "IWM")
    if len(closes) < MIN_BARS:
        return jsonify({
            "status":  "error",
            "symbol":  "IWM",
            "message": f"Insufficient price history ({len(closes)} bars). Need ≥{MIN_BARS}.",
        }), 422

    verdict = _build_verdict("IWM", closes, volumes)
    payload = clean_data({"status": "success", "tier": "DEMO", **verdict})
    _demo_cache["ts"] = now
    _demo_cache["data"] = payload
    return jsonify(payload)


@triple_lock_bp.route("", methods=["POST", "GET"])
@triple_lock_bp.route("/", methods=["POST", "GET"])
@dual_payment(price_usdc="0.25", description="TRIPLE_LOCK_VERDICT — the rarest premium signal in the SqueezeOS suite. Returns BULL or BEAR only when all three proprietary engines (PRICE stretch + VOLUME dark-pool kinetics + PRICE ribbon harmonics) agree on direction. When the lock is not firing, returns NO_TRIPLE_LOCK with the blocking engine identified — itself an actionable 'do not max-size' signal. 60-second per-symbol cache. Use POST body {symbol: 'TSLA'} or GET ?symbol=TSLA.")
def triple_lock():
    body = request.get_json(silent=True) or {}
    symbol = (body.get("symbol") or request.args.get("symbol") or "IWM").upper().strip()
    now = time.time()

    cached = _cache.get(symbol)
    if cached and (now - cached["ts"]) < _CACHE_TTL:
        return jsonify(cached["data"])

    dm = get_service("dm")
    if not dm:
        return jsonify({"status": "error", "message": "DataManager unavailable"}), 503

    closes, volumes = _fetch_bars(dm, symbol)
    if len(closes) < MIN_BARS:
        return jsonify({
            "status":  "error",
            "symbol":  symbol,
            "message": f"Insufficient price history ({len(closes)} bars). Need ≥{MIN_BARS}.",
        }), 422

    verdict = _build_verdict(symbol, closes, volumes)
    payload = clean_data({"status": "success", "tier": "TRIPLE_LOCK_VERDICT", **verdict})
    _cache[symbol] = {"ts": now, "data": payload}

    # Broadcast every actual lock fire so SSE subscribers can react in real time.
    if verdict["directive"] in ("TRIPLE_LOCK_BULL", "TRIPLE_LOCK_BEAR"):
        try:
            import core.signal_history as sh
            sh.record(symbol, "TRIPLE_LOCK_VERDICT", {
                "directive":  verdict["directive"],
                "bias":       verdict["bias"],
                "confidence": verdict["confidence"],
            })
        except Exception as e:
            logger.warning(f"[TRIPLE_LOCK] history record error: {e}")

        try:
            import core.app as _app
            broadcast = getattr(_app, "_broadcast_sse_global", None)
            if broadcast:
                broadcast({
                    "type":      "TRIPLE_LOCK_FIRED",
                    "symbol":    symbol,
                    "directive": verdict["directive"],
                    "ts":        now,
                })
        except Exception:
            pass

        logger.info(
            f"[TRIPLE_LOCK] {verdict['directive']} {symbol} consensus={verdict['consensus']}"
        )

    return jsonify(payload)
