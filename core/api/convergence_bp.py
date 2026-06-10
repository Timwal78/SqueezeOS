"""
/api/convergence/<symbol>   — Full 5-engine convergence read for one symbol
/api/beastmode              — Scan the universe, return all convergence hits
/api/settlement             — Engine 2 clock status (all active ignitions)
/api/settlement/<symbol>    — Engine 2 clock for one symbol
"""

import logging
import os
import time
from flask import Blueprint, jsonify, request
from core.legacy import get_service, clean_data
from core.convergence_engine import ConvergenceEngine, scan_beastmode_universe
from core.counsel_agent import generate_ai_counsel
from core.engine2_settlement import get_clock, stamp_ignition, get_all_active
from core.discord_payload import fire_discord

logger = logging.getLogger("SML.Convergence.API")
convergence_bp = Blueprint("convergence", __name__)

# ── Execution cooldown — prevents duplicate orders on rapid calls ────────────
_last_execution: dict = {}   # symbol → epoch
_EXECUTION_COOLDOWN = 300    # 5 minutes between GOD MODE executions per symbol

_BEAST_MAX_SHARES = int(os.environ.get("BEAST_MAX_SHARES", "5"))
_BEAST_MAX_PRICE  = float(os.environ.get("BEAST_MAX_PRICE", "500.0"))  # max order $ value


def _fire_execution(symbol: str, result: dict, dm) -> None:
    """
    Called when GOD MODE + execute_gate confirmed.
    1. Tradier (cloud, 24/7) — equity market order via Tradier API.
    2. Robinhood (Windows executor) — webhook POST to local executor if configured.
    """
    now = time.time()
    last = _last_execution.get(symbol, 0)
    if now - last < _EXECUTION_COOLDOWN:
        logger.info(f"[EXEC] {symbol} GOD_MODE cooldown active — {int(_EXECUTION_COOLDOWN - (now-last))}s remaining")
        return
    _last_execution[symbol] = now

    signal    = result.get("signal", "")
    side      = "buy" if "BULL" in signal or signal in ("BEASTMODE", "GOD_MODE") else "sell"
    sml       = result.get("sml_matrix") or {}
    god_count = sml.get("god_stacked", 0)

    # ── Get current price ────────────────────────────────────────────────────
    try:
        import tradier_api as _t
        q = _t.get_quote(symbol)
        price = float(q.get("last") or q.get("ask") or 0) if q else 0.0
    except Exception:
        price = 0.0

    if price <= 0:
        logger.warning(f"[EXEC] {symbol} could not get live price — aborting execution")
        return

    quantity = max(1, int(_BEAST_MAX_PRICE // price))
    quantity = min(quantity, _BEAST_MAX_SHARES)

    logger.info(f"[EXEC] 🚀 GOD MODE FIRE — {side.upper()} {quantity}x {symbol} @ ${price:.2f} | SET9:{god_count}/6")

    # ── 1. Tradier cloud execution ───────────────────────────────────────────
    try:
        import tradier_api as _t
        tradier_result = _t.place_equity_order(symbol, quantity, side)
        logger.info(f"[EXEC] Tradier result: {tradier_result}")
    except Exception as e:
        logger.error(f"[EXEC] Tradier execution error: {e}")
        tradier_result = {"status": "error", "message": str(e)}

    # ── 2. Robinhood Windows executor webhook ────────────────────────────────
    rh_url = os.environ.get("ROBINHOOD_EXECUTOR_URL", "")
    if rh_url:
        try:
            import json, urllib.request as _ul, hmac as _hmac, hashlib as _hl
            secret = os.environ.get("WEBHOOK_SECRET", "squeezeos-webhook-default-secret")
            webhook_payload = json.dumps({
                "ticker":         symbol,
                "action":         side.upper(),
                "mode":           "equity",
                "sml_matrix":     sml,
                "harmonic_score": sml.get("harmonic_score", 0),
            }).encode()
            sig = "sha256=" + _hmac.new(secret.encode(), webhook_payload, _hl.sha256).hexdigest()
            req = _ul.Request(
                rh_url,
                data=webhook_payload,
                headers={"Content-Type": "application/json", "X-SqueezeOS-Signature": sig},
            )
            with _ul.urlopen(req, timeout=5) as resp:
                logger.info(f"[EXEC] Robinhood executor webhook → {resp.status}")
        except Exception as e:
            logger.warning(f"[EXEC] Robinhood executor webhook failed: {e}")


@convergence_bp.route("/market/scan", methods=["GET"])
def market_scan():
    """Live ticker rotation — reads directly from the state quotes feed (Polygon/Alpaca)."""
    from core.state import state
    with state.lock:
        quotes = dict(state.quotes)
    if not quotes:
        return jsonify({"status": "awaiting_data", "quotes": {},
                        "message": "Live market feed initializing — no data yet"}), 202
    return jsonify({"status": "ok", "quotes": quotes})

_cache: dict = {}
_CACHE_TTL   = 45   # seconds — convergence is expensive (5 engines + sniper)


def _fetch_bars(dm, symbol: str, limit: int = 400, tf: str = "1D"):
    """Fetch live bars from DataManager. Never falls back to fake data."""
    try:
        bars = dm.get_bars(symbol, timeframe=tf, limit=limit) or []
        if not bars and tf == "1D":
            bars = dm.get_bars(symbol, timeframe="1Min", limit=limit) or []
        closes  = [float(b.get("c") or b.get("close",  0)) for b in bars if b.get("c") or b.get("close")]
        volumes = [float(b.get("v") or b.get("volume", 0)) for b in bars if b.get("v") or b.get("volume")]
        return closes, volumes, bars
    except Exception as e:
        logger.warning(f"[Convergence] Bar fetch failed {symbol}: {e}")
        return [], [], []


@convergence_bp.route("/convergence/<symbol>", methods=["GET"])
def convergence_signal(symbol):
    symbol  = symbol.upper().strip()
    run_sniper = request.args.get("sniper", "false").lower() == "true"
    tf = request.args.get("tf", "1D").upper()
    
    # 1. Check Cache
    cache_key = f"{symbol}_{tf}"
    cached = _cache.get(cache_key)
    now = time.time()
    if cached and (now - cached["ts"] < _CACHE_TTL):
        return jsonify(cached["data"])

    dm = get_service("dm")
    if not dm:
        return jsonify({"status": "error", "message": "DataManager not initialized"}), 503

    closes, volumes, bars = _fetch_bars(dm, symbol, tf=tf)
    if len(closes) < 11:
        return jsonify({
            "status": "error", "symbol": symbol,
            "message": f"Insufficient data ({len(closes)} bars)",
        }), 422

    engine = ConvergenceEngine()
    result = engine.analyze(symbol, closes, volumes,
                            bars_with_dates=bars, run_sniper=run_sniper)

    # Add AI Counsel string
    result["ai_counsel"] = generate_ai_counsel(result)

    # Fire Discord on any signal above NEUTRAL
    if result.get("signal") not in ("NEUTRAL", "INSUFFICIENT_DATA"):
        sniper_data = result.get("options_sniper") or {}
        trade_type  = sniper_data.get("type", "CALL").lower()
        fire_discord(result, trade_type=trade_type)

    # ── GOD MODE EXECUTION GATE ──────────────────────────────────────────────
    # Only fires live orders when tier=GOD_MODE AND execute_gate=True.
    # Routes to Tradier (cloud, 24/7) + Robinhood webhook (Windows executor).
    sml = result.get("sml_matrix") or {}
    if sml.get("execute_gate") and sml.get("tier") == "GOD_MODE":
        _fire_execution(symbol, result, dm)


    payload = {
        "status": "success",
        "symbol": symbol,
        "result": result
    }
    _cache[cache_key] = {"ts": now, "data": clean_data(payload)}
    return jsonify(clean_data(payload))


@convergence_bp.route("/beastmode", methods=["GET"])
def beastmode_scan():
    """Scan the full universe. Only returns HIGH_CONVERGENCE+ signals."""
    tf = request.args.get("tf", "1D").upper()
    
    dm = get_service("dm")
    if not dm:
        return jsonify({"status": "error", "message": "DataManager unavailable"}), 503

    hits = scan_beastmode_universe({"dm": dm}, tf=tf)

    # Fire Discord for every convergence hit
    for hit in hits:
        sniper_data = hit.get("options_sniper") or {}
        fire_discord(hit, trade_type=sniper_data.get("type", "CALL").lower())

    return jsonify(clean_data({
        "status":        "success",
        "universe":      "DYNAMIC",
        "hits":          len(hits),
        "signals":       hits,
        "timestamp":     time.time(),
    }))


@convergence_bp.route("/settlement/stamp/<symbol>", methods=["POST"])
def stamp_symbol(symbol):
    """Manually stamp T+0 for a symbol (for testing / manual override)."""
    symbol = symbol.upper().strip()
    clock  = stamp_ignition(symbol)
    return jsonify(clean_data({"status": "success", "clock": clock}))


@convergence_bp.route("/settlement/clocks", methods=["GET"])
def all_clocks():
    """All active Engine 2 clocks."""
    return jsonify(clean_data({
        "status": "success",
        "clocks": get_all_active(),
        "ts":     time.time(),
    }))
