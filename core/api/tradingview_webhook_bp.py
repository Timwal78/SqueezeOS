import logging
from flask import Blueprint, request, jsonify
from core.nexus402_bridge import notarize_execution
import core.discord_payload as discord

logger = logging.getLogger("TradingView-Webhook")
tradingview_webhook_bp = Blueprint('tradingview_webhook', __name__)

# Hardcoded institutional security key
AUTH_PASSPHRASE = "SQUEEZE_AUTH_992"

@tradingview_webhook_bp.route('/tradingview', methods=['POST'])
def catch_tv_webhook():
    try:
        # 1. Parse Inbound JSON
        payload = request.get_json(force=True)
        
        # 2. Security Gatekeeper
        if payload.get("passphrase") != AUTH_PASSPHRASE:
            logger.warning(f"UNAUTHORIZED WEBHOOK ATTEMPT: {request.remote_addr}")
            return jsonify({"status": "error", "message": "Unauthorized"}), 401

        # 3. Extract Execution Metrics
        ticker = payload.get("ticker", "UNKNOWN")
        action = payload.get("action", "").upper()
        comment = payload.get("comment", "")
        price = payload.get("price", "0.0")

        # 4. Extract x402 Fee Tier from the Comment String (e.g., "x402_SET_4_LONG")
        # Default to Set 1 if it's an exhaust exit or malformed
        set_level = 1 
        if "x402_SET_" in comment:
            try:
                # Splits the string and grabs the number between SET_ and _LONG/_SHORT
                set_level = int(comment.split("_")[2])
            except Exception as e:
                logger.error(f"Failed to parse x402 tier from comment: {comment}. Defaulting to Set 1.")

        # 5. Route to Ghost Layer for Notarization & Execution
        logger.info(f"ROUTING EXECUTION: {ticker} | Action: {action} | Tier: SET_{set_level}")
        
        # We need to adapt this to nexus402_bridge.notarize_execution signature
        # notarize_execution(symbol, directive, qty, limit_price, reason, dynamic_discount)
        qty = 100
        try:
            limit_price = float(price)
        except ValueError:
            limit_price = 0.0
            
        execution_status = notarize_execution(
            symbol=ticker, 
            directive=action, 
            qty=qty, 
            limit_price=limit_price, 
            reason=f"x402_SET_{set_level}", 
            dynamic_discount=0.0
        )

        # 6. Fire Discord Telemetry
        cert_id = execution_status.get('certificate_id') if execution_status else "FAILED"
        alert_msg = f"**[SqueezeOS EXECUTION]**\nTicker: `{ticker}`\nAction: `{action}`\nx402 Tier: `SET_{set_level}`\nPrice: `${price}`\nStatus: `{cert_id}`"
        discord.send_message(alert_msg)

        return jsonify({"status": "success", "tier_routed": set_level}), 200

    except Exception as e:
        logger.error(f"Webhook Processing Failure: {str(e)}")
        return jsonify({"status": "error", "message": "Internal processing error"}), 500
