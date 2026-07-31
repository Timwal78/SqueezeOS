"""
Position Manager status — free, read-only.

  GET /api/positions/managed          — full exit-manager state
  GET /api/positions/managed/<symbol> — one tracked position

Exists so "what is the desk actually holding, and what will close it?" is
answerable without reading logs. Returns real registry state only — an empty
`tracked` map means nothing is currently being managed, and is reported as
exactly that rather than being filled in with invented rows.
"""

from flask import Blueprint, jsonify

position_manager_bp = Blueprint("position_manager_bp", __name__)


@position_manager_bp.route("", methods=["GET"])
@position_manager_bp.route("/", methods=["GET"])
def managed_status():
    try:
        import position_manager
        return jsonify(position_manager.status()), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 503


@position_manager_bp.route("/<symbol>", methods=["GET"])
def managed_symbol(symbol: str):
    try:
        import position_manager
        key = symbol.upper().strip()
        tracked = position_manager.tracked()
        pos = tracked.get(key)
        if not pos:
            # Also match by underlying so /api/positions/managed/SPY finds an
            # SPY option tracked under its OCC symbol.
            matches = {k: v for k, v in tracked.items() if v.get("underlying") == key}
            if not matches:
                return jsonify({"status": "not_tracked", "symbol": key}), 404
            return jsonify({"status": "ok", "symbol": key, "positions": matches}), 200
        return jsonify({"status": "ok", "symbol": key, "positions": {key: pos}}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 503
