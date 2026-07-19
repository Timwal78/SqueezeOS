"""
TradingView Webhook — SML Execution Bridge
==========================================
Receives alert POSTs from TradingView Pine scripts and routes them to:
  1. Tradier equity/options orders via iam_executor.execute_async()
  2. Discord beast-channel embed (Robinhood Windows service pickup)
  3. /api/webhooks/tv_pending queue — Robinhood executor polls this

Expected payload (Pine alert message):
  {
    "passphrase": "<value of TV_WEBHOOK_PASSPHRASE env var — set your own, no default>",
    "system":     "SML_Leviathan" | "SML_FTD_Hunter" | "MMLE-BEAST" | "SML_Sniper" | ...,
    "ticker":     "{{ticker}}",
    "action":     "EXECUTE_LONG" | "EXECUTE_SHORT" | "FIRE_LONG" | "FIRE_SHORT",
    "price":      {{close}}
  }

Required env var:
  TV_WEBHOOK_PASSPHRASE — no hardcoded default (this repo is public; a default
  here would be a known credential for a webhook that can place real Tradier
  orders via iam_executor). Unset it and the endpoint returns 503, not 401 —
  fails closed, never falls back to a shared/public secret.

Webhook URL for TradingView alert dialog:
  https://squeezeos-api.onrender.com/api/webhooks/tradingview

Robinhood executor polls:
  GET https://squeezeos-api.onrender.com/api/webhooks/tv_pending
  Returns and clears all signals queued in the last 10 minutes.
"""
import os
import time
import logging
import threading
from collections import deque
from flask import Blueprint, request, jsonify

logger = logging.getLogger("TV-Webhook")
tradingview_webhook_bp = Blueprint("tradingview_webhook", __name__)

def _passphrase() -> str:
    # No hardcoded fallback: this repo is public, so a default here would be a
    # publicly-known credential for a webhook that can place real Tradier orders.
    # Unset TV_WEBHOOK_PASSPHRASE must fail closed, not fail open to a known string.
    return os.environ.get("TV_WEBHOOK_PASSPHRASE", "")

_LONG_ACTIONS  = {"EXECUTE_LONG",  "FIRE_LONG",  "BUY",  "LONG"}
_SHORT_ACTIONS = {"EXECUTE_SHORT", "FIRE_SHORT", "SELL", "SHORT"}

_ACTION_COLORS = {"BUY": 0x00FF88, "SELL": 0xFF4444}

# Pending signal queue for Robinhood executor polling.
# Signals expire after 10 minutes if not picked up.
_TV_QUEUE: deque = deque(maxlen=50)
_TV_QUEUE_LOCK   = threading.Lock()
_TV_SIGNAL_TTL   = 600  # 10 minutes


def _queue_push(sym: str, direction: str, system: str, price: float):
    with _TV_QUEUE_LOCK:
        _TV_QUEUE.append({
            "symbol":    sym,
            "action":    direction,
            "system":    system,
            "price":     price,
            "ts":        time.time(),
            "confidence": 80.0,
        })


def _queue_pop_all() -> list:
    """Return all non-expired signals and clear the queue."""
    now = time.time()
    with _TV_QUEUE_LOCK:
        fresh = [s for s in _TV_QUEUE if now - s["ts"] < _TV_SIGNAL_TTL]
        _TV_QUEUE.clear()
    return fresh


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

        expected = _passphrase()
        if not expected:
            logger.error("[TV-Webhook] TV_WEBHOOK_PASSPHRASE not configured — rejecting all requests")
            return jsonify({"status": "error", "message": "webhook not configured"}), 503

        if payload.get("passphrase") != expected:
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
            "system":                system,
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

        # Push to Robinhood executor polling queue
        _queue_push(ticker, direction, system, price)

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


@tradingview_webhook_bp.route("/tv_pending", methods=["GET"])
def tv_pending():
    """
    Robinhood executor polls this to pick up Pine script signals.
    Returns all pending signals queued since last poll, then clears them.
    Signals expire after 10 minutes if not fetched.
    """
    signals = _queue_pop_all()
    return jsonify({
        "status":  "success",
        "signals": signals,
        "count":   len(signals),
        "ts":      time.time(),
    })
