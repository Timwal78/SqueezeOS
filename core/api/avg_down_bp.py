"""
SML Avg-Down Engine — Flask Blueprint
/api/avg-down/status     GET  Engine health + config (no EMA periods exposed)
/api/avg-down/positions  GET  All open virtual positions
/api/avg-down/signals    GET  Recent signal log (ENTER/ADD/EXIT/STOP)
/api/avg-down/<symbol>   GET  Position + latest signal for a single symbol
"""

from flask import Blueprint, jsonify, request
from core.legacy import clean_data

avg_down_bp = Blueprint("avg_down", __name__)


def _get_engine():
    try:
        import avg_down_engine as e
        return e
    except ImportError:
        return None


@avg_down_bp.route("/status", methods=["GET"])
def avg_down_status():
    e = _get_engine()
    if not e:
        return jsonify({"status": "unavailable", "error": "avg_down_engine not loaded"}), 503
    return jsonify(clean_data(e.get_status()))


@avg_down_bp.route("/positions", methods=["GET"])
def avg_down_positions():
    e = _get_engine()
    if not e:
        return jsonify({"status": "unavailable", "error": "avg_down_engine not loaded"}), 503
    return jsonify(clean_data({"positions": e.get_positions(), "count": len(e.get_positions())}))


@avg_down_bp.route("/signals", methods=["GET"])
def avg_down_signals():
    e = _get_engine()
    if not e:
        return jsonify({"status": "unavailable", "error": "avg_down_engine not loaded"}), 503
    limit = min(int(request.args.get("limit", 50)), 200)
    sigs = e.get_signals(limit)
    return jsonify(clean_data({"signals": sigs, "count": len(sigs)}))


@avg_down_bp.route("/<symbol>", methods=["GET"])
def avg_down_symbol(symbol):
    e = _get_engine()
    if not e:
        return jsonify({"status": "unavailable", "error": "avg_down_engine not loaded"}), 503
    sym = symbol.upper().strip()
    positions = {p["symbol"]: p for p in e.get_positions()}
    signals = [s for s in e.get_signals(200) if s.get("symbol") == sym]
    return jsonify(clean_data({
        "symbol":   sym,
        "position": positions.get(sym),
        "signals":  signals[:10],
    }))
