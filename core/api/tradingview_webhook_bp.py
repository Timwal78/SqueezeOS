"""
TradingView Webhook — SML Execution Bridge
==========================================
Receives alert POSTs from TradingView Pine scripts and routes them to:
  1. Tradier equity/options orders via iam_executor.execute_async()
  2. Discord beast-channel embed (Robinhood Windows service pickup)

Expected payload (Pine alert message):
  {
    "passphrase": "SQUEEZE_AUTH_992",
    "system":     "SML_Leviathan" | "SML_FTD_Hunter" | "MMLE-BEAST" | ...,
    "ticker":     "{{ticker}}",
    "action":     "EXECUTE_LONG" | "EXECUTE_SHORT" | "FIRE_LONG" | "FIRE_SHORT",
    "price":      {{close}}
  }

Webhook URL for TradingView alert dialog:
  https://squeezeos-api.onrender.com/api/webhooks/tradingview
"""
import os
import time
import logging
import threading
from flask import Blueprint, request, jsonify

logger = logging.getLogger("TV-Webhook")
tradingview_webhook_bp = Blueprint("tradingview_webhook", __name__)

AUTH_PASSPHRASE = os.environ.get("TV_WEBHOOK_PASSPHRASE", "SQUEEZE_AUTH_992")

_LONG_ACTIONS  = {"EXECUTE_LONG",  "FIRE_LONG",  "BUY",  "LONG"}
_SHORT_ACTIONS = {"EXECUTE_SHORT", "FIRE_SHORT", "SELL", "SHORT"}

_ACTION_COLORS = {"BUY": 0x00FF88, "SELL": 0xFF4444}


def _fire_discord(sym: str, direction: str, system: str, price: float, result: dict):
    """Post trade alert to beast channel — fire-and-forget."""
    try:
        from discord_alerts import DiscordAlerts
        d = DiscordAlerts()
        url = d.webhook_beast or d.webhook_all
        if not url:
            return
        color  = _ACTION_COLORS.get(direction, 0xAAAAAA)
        mode   = "📋 PAPER" if result.get("paper") else "🔴 LIVE"
        placed = result.get("placed") or result.get("paper")
        status = "✅ EXECUTED" if placed else (f"❌ {result.get('error','')}" if result.get("error") else "⏭️ GATED")
        payload = {"embeds": [{"title": f"⚡ TV SIGNAL — {direction} {sym}",
            "color": color,
            "fields": [
                {"name": "System",  "value": system,              "inline": True},
                {"name": "Action",  "value": f"**{direction}**",  "inline": True},
                {"name": "Price",   "value": f"${price:.2f}",     "inline": True},
                {"name": "Mode",    "value": mode,                "inline": True},
                {"name": "Status",  "value": status,              "inline": True},
            ],
            "footer": {"text": "ScriptMaster Labs | TradingView Bridge | SqueezeOS"},
            "timestamp": __import__("datetime").datetime.utcnow().isoformat(),
        }]}
        d._post(url, payload)
    except Exception as e:
        logger.warning(f"[TV-Webhook] Discord failed for {sym}: {e}")


@tradingview_webhook_bp.route("/tradingview", methods=["POST"])
def catch_tv_webhook():
    try:
        payload = request.get_json(force=True) or {}

        if payload.get("passphrase") != AUTH_PASSPHRASE:
            logger.warning(f"[TV-Webhook] Unauthorized attempt from {request.remote_addr}")
            return jsonify({"status": "error", "message": "Unauthorized"}), 401

        ticker = (payload.get("ticker") or payload.get("symbol") or "").upper().strip()
        action = (payload.get("action") or "").upper().strip()
        system = payload.get("system") or payload.get("engine") or "TradingView"
        price  = float(payload.get("price") or 0.0)

        if not ticker:
            return jsonify({"status": "error", "message": "ticker required"}), 400

        if action in _LONG_ACTIONS:
            direction = "BUY"
        elif action in _SHORT_ACTIONS:
            direction = "SELL"
        else:
            logger.info(f"[TV-Webhook] {ticker} action={action} — not directional, skipping")
            return jsonify({"status": "skipped", "reason": f"non-directional action: {action}"}), 200

        logger.info(f"[TV-Webhook] {system} → {direction} {ticker} @ ${price:.2f}")

        resolution = {
            "action":                direction,
            "rationale":             f"{system} TradingView signal: {action}",
            "vehicle":               ticker,
            "resolution_confidence": 80.0,
            "invalidation":          "",
            "review_trigger":        "",
        }

        exec_result = {}
        try:
            from iam_executor import execute_async
            execute_async(ticker, resolution, "NEAR_TERM", 80.0, price)
            exec_result = {"queued": True}
        except Exception as e:
            logger.error(f"[TV-Webhook] iam_executor error for {ticker}: {e}")
            exec_result = {"error": str(e)}

        threading.Thread(
            target=_fire_discord,
            args=(ticker, direction, system, price, exec_result),
            daemon=True,
            name=f"tv-discord-{ticker}",
        ).start()

        return jsonify({
            "status":    "success",
            "symbol":    ticker,
            "direction": direction,
            "system":    system,
            "price":     price,
            "execution": exec_result,
        }), 200

    except Exception as e:
        logger.error(f"[TV-Webhook] Processing error: {e}")
        return jsonify({"status": "error", "message": "Internal error"}), 500
