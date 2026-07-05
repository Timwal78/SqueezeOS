"""
SML Vault Engine — Flask Blueprint
/api/vault/status     GET  Engine health + config (zero-custody, own-account only)
/api/vault/positions  GET  All open virtual positions
/api/vault/signals    GET  Recent signal log (ENTER/ADD/EXIT/HARD_STOP/STOP)
/api/vault/<symbol>   GET  Position + latest signal for a single pair
"""

from flask import Blueprint, jsonify, request
from core.legacy import clean_data

vault_bp = Blueprint("vault", __name__)


def _get_engine():
    try:
        import sml_vault_engine as e
        return e
    except ImportError:
        return None


@vault_bp.route("/status", methods=["GET"])
def vault_status():
    e = _get_engine()
    if not e:
        return jsonify({"status": "unavailable", "error": "sml_vault_engine not loaded"}), 503
    return jsonify(clean_data(e.get_status()))


@vault_bp.route("/positions", methods=["GET"])
def vault_positions():
    e = _get_engine()
    if not e:
        return jsonify({"status": "unavailable", "error": "sml_vault_engine not loaded"}), 503
    return jsonify(clean_data({"positions": e.get_positions(), "count": len(e.get_positions())}))


@vault_bp.route("/signals", methods=["GET"])
def vault_signals():
    e = _get_engine()
    if not e:
        return jsonify({"status": "unavailable", "error": "sml_vault_engine not loaded"}), 503
    limit = min(int(request.args.get("limit", 50)), 200)
    sigs = e.get_signals(limit)
    return jsonify(clean_data({"signals": sigs, "count": len(sigs)}))


@vault_bp.route("/<symbol>", methods=["GET"])
def vault_symbol(symbol):
    e = _get_engine()
    if not e:
        return jsonify({"status": "unavailable", "error": "sml_vault_engine not loaded"}), 503
    sym = symbol.upper().strip()
    positions = {p["symbol"]: p for p in e.get_positions()}
    signals = [s for s in e.get_signals(200) if s.get("symbol") == sym]
    return jsonify(clean_data({
        "symbol": sym,
        "position": positions.get(sym),
        "signals": signals[:10],
    }))
