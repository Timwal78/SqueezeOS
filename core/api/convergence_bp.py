"""
/api/convergence/<symbol>   — Full 5-engine convergence read for one symbol
/api/beastmode              — Scan the universe, return all convergence hits
/api/settlement             — Engine 2 clock status (all active ignitions)
/api/settlement/<symbol>    — Engine 2 clock for one symbol
"""

import logging
import time
from flask import Blueprint, jsonify, request
from core.legacy import get_service, clean_data
from core.convergence_engine import ConvergenceEngine, scan_beastmode_universe, BEASTMODE_UNIVERSE
from core.engine2_settlement import get_clock, stamp_ignition, get_all_active
from core.discord_payload import fire_discord

logger = logging.getLogger("SML.Convergence.API")
convergence_bp = Blueprint("convergence", __name__)

_cache: dict = {}
_CACHE_TTL   = 45   # seconds — convergence is expensive (5 engines + sniper)


def _fetch_bars(dm, symbol: str, limit: int = 400):
    try:
        bars = dm.get_historical_bars(symbol, timeframe="1Day", limit=limit) or []
        if not bars:
            bars = dm.get_historical_bars(symbol, timeframe="1Min", limit=limit) or []
        closes  = [float(b.get("c") or b.get("close",  0)) for b in bars if b.get("c") or b.get("close")]
        volumes = [float(b.get("v") or b.get("volume", 0)) for b in bars if b.get("v") or b.get("volume")]
        return closes, volumes, bars
    except Exception as e:
        logger.warning(f"[Convergence] Bar fetch failed {symbol}: {e}")
        return [], [], []


@convergence_bp.route("/convergence/<symbol>", methods=["GET"])
def convergence_signal(symbol):
    symbol  = symbol.upper().strip()
    now     = time.time()
    sniper  = request.args.get("sniper", "true").lower() != "false"

    cached = _cache.get(symbol)
    if cached and (now - cached["ts"]) < _CACHE_TTL:
        return jsonify(cached["data"])

    dm = get_service("dm")
    if not dm:
        return jsonify({"status": "error", "message": "DataManager unavailable"}), 503

    closes, volumes, bars = _fetch_bars(dm, symbol)
    if len(closes) < 11:
        return jsonify({
            "status": "error", "symbol": symbol,
            "message": f"Insufficient data ({len(closes)} bars)",
        }), 422

    engine = ConvergenceEngine()
    result = engine.analyze(symbol, closes, volumes,
                            bars_with_dates=bars, run_sniper=sniper)

    # Auto-fire Discord on Beastmode or High Convergence
    if result.get("signal") in ("BEASTMODE", "HIGH_CONVERGENCE"):
        sniper_data = result.get("options_sniper") or {}
        trade_type  = sniper_data.get("type", "CALL").lower()
        fire_discord(result, trade_type=trade_type)

    payload = {
        "status":    "success",
        "symbol":    symbol,
        "timestamp": now,
        "bars_used": len(closes),
        "result":    result,
    }

    _cache[symbol] = {"ts": now, "data": clean_data(payload)}
    return jsonify(clean_data(payload))


@convergence_bp.route("/beastmode", methods=["GET"])
def beastmode_scan():
    """Scan the full universe. Only returns HIGH_CONVERGENCE+ signals."""
    dm = get_service("dm")
    if not dm:
        return jsonify({"status": "error", "message": "DataManager unavailable"}), 503

    hits = scan_beastmode_universe({"dm": dm})

    # Fire Discord for any Beastmode hits
    for hit in hits:
        if hit.get("beastmode"):
            sniper_data = hit.get("options_sniper") or {}
            fire_discord(hit, trade_type=sniper_data.get("type", "CALL").lower())

    return jsonify(clean_data({
        "status":        "success",
        "universe":      BEASTMODE_UNIVERSE,
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
