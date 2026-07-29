"""
SML Squeeze Fuel Blueprint — /api/squeeze-fuel
===========================================================
GET /api/squeeze-fuel/status    Free — scanner state, params, last signal
GET /api/squeeze-fuel/<symbol>  Free — on-demand composite read using the
                                 live quote (state.quotes) + an optional
                                 live Tradier option chain. 503 if the
                                 symbol has no live quote yet.
"""
import logging

from flask import Blueprint, jsonify

from core.legacy import clean_data

logger = logging.getLogger("SQUEEZE-FUEL-BP")

squeeze_fuel_bp = Blueprint("squeeze_fuel", __name__)


@squeeze_fuel_bp.route("/status", methods=["GET"])
def squeeze_fuel_status():
    try:
        import squeeze_fuel_scanner
        return jsonify(clean_data({"status": "success", "scanner": squeeze_fuel_scanner.status()}))
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@squeeze_fuel_bp.route("/<symbol>", methods=["GET"])
def squeeze_fuel_symbol(symbol: str):
    try:
        from core.state import state
        from squeeze_fuel_engine import analyze

        sym = symbol.upper()
        with state.lock:
            quote = dict(state.quotes.get(sym, {}))
        if not quote:
            return jsonify({"status": "error",
                            "message": f"No live quote for {sym} yet (market scanner warming up)"}), 503

        raw_chain = None
        try:
            import tradier_api
            raw_chain = tradier_api.get_option_chain_schwab_format(sym)
        except Exception:
            pass

        result = analyze(sym, quote_data=quote, raw_chain=raw_chain)
        return jsonify(clean_data({"status": "success", **result}))
    except Exception as e:
        logger.error(f"[SQUEEZE-FUEL-BP] {symbol}: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
