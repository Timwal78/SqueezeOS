"""
SML Gamma Pin Blueprint — /api/gamma-pin
===========================================================
GET /api/gamma-pin/status    Free — scanner state, params, last signal
GET /api/gamma-pin/<symbol>  Free — on-demand pin-risk read from a live
                              Tradier options chain (503 without
                              TRADIER_API_KEY / no chain data)
"""
import logging

from flask import Blueprint, jsonify

from core.legacy import clean_data

logger = logging.getLogger("GAMMA-PIN-BP")

gamma_pin_bp = Blueprint("gamma_pin", __name__)


@gamma_pin_bp.route("/status", methods=["GET"])
def gamma_pin_status():
    try:
        import gamma_pin_scanner
        return jsonify(clean_data({"status": "success", "scanner": gamma_pin_scanner.status()}))
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@gamma_pin_bp.route("/<symbol>", methods=["GET"])
def gamma_pin_symbol(symbol: str):
    try:
        import tradier_api
        from gamma_flow_engine import calculate_gex_profile, detect_pin_risk

        raw_chain = tradier_api.get_option_chain_schwab_format(symbol.upper())
        if not raw_chain:
            return jsonify({"status": "error",
                            "message": "No Tradier option chain available (TRADIER_API_KEY required)"}), 503

        spot = float(raw_chain.get("underlyingPrice") or 0.0)
        if spot <= 0:
            return jsonify({"status": "error", "message": "No underlying price in chain"}), 503

        profile = calculate_gex_profile(raw_chain, spot, symbol.upper())
        if not profile:
            return jsonify({"status": "error", "message": "Could not build GEX profile from chain"}), 503

        pin = detect_pin_risk(raw_chain, profile)
        return jsonify(clean_data({
            "status": "success",
            "symbol": symbol.upper(),
            "spot": spot,
            "profile_shape": profile.profile_shape,
            "zero_gamma_line": profile.zero_gamma_line,
            "max_oi_strike": profile.max_oi_strike,
            "pin_risk": pin,
            "disclosure": "No historical backtest exists for this constraint — "
                           "no historical options-chain data source is reachable "
                           "from this codebase. Direction is a disclosed proxy "
                           "(sign of max_oi_strike - spot), not a validated edge.",
        }))
    except Exception as e:
        logger.error(f"[GAMMA-PIN-BP] {symbol}: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
