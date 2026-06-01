"""
NW Liquidity Sweeps Webhook — TradingView → SqueezeOS → Discord
POST /api/nwliq/signal  receives the JSON alert() payload from the Pine Script.

TradingView setup:
  1. Load the NW Liquidity Sweeps indicator
  2. Create ONE alert → Condition: "Any alert() function call"
  3. Webhook URL: https://squeezeos-api.onrender.com/api/nwliq/signal

Required env var:
  DISCORD_WEBHOOK_NW=https://discord.com/api/webhooks/...
"""
import os
import time
import logging
import requests
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify

logger = logging.getLogger("NW-Liq")
nw_liq_bp = Blueprint("nw_liq", __name__)

_COLORS = {
    "buy":  0x00FF88,
    "sell": 0xFF2828,
    "hold": 0xFFD700,
}

_ICONS = {
    "buy":  "🟢",
    "sell": "🔴",
    "hold": "🟡",
}

_cooldowns: dict = {}
_COOLDOWN_SECS = 60


def _within_cooldown(key: str) -> bool:
    now = time.time()
    last = _cooldowns.get(key, 0)
    if now - last < _COOLDOWN_SECS:
        return True
    _cooldowns[key] = now
    return False


def _post_discord(embed: dict) -> bool:
    url = os.environ.get("DISCORD_WEBHOOK_NW", "")
    if not url:
        logger.warning("[NW-Liq] DISCORD_WEBHOOK_NW not set — signal dropped")
        return False
    try:
        r = requests.post(url, json=embed, timeout=8)
        if r.status_code in (200, 204):
            title = embed.get("embeds", [{}])[0].get("title", "")
            logger.info(f"[NW-Liq] Posted: {title}")
            return True
        logger.warning(f"[NW-Liq] Discord {r.status_code}: {r.text[:120]}")
        return False
    except Exception as e:
        logger.error(f"[NW-Liq] Discord post error: {e}")
        return False


def _dots(n: int) -> str:
    n = max(0, min(6, int(n)))
    return "●" * n + "○" * (6 - n)


def _fp(v) -> str:
    if v is None or v == 0:
        return "—"
    try:
        fv = float(v)
        return f"{fv:,.4f}" if fv < 1 else f"{fv:,.2f}"
    except (TypeError, ValueError):
        return str(v)


def _build_embed(p: dict) -> dict:
    action = p.get("action", "hold").lower()
    sig    = p.get("signal", "Unknown Signal")
    ticker = p.get("ticker", "?")
    exch   = p.get("exchange", "")
    tf     = p.get("timeframe", "")
    price  = p.get("price", 0)
    nw     = p.get("nw", 0)
    atr    = p.get("atr", 0)
    tgt    = p.get("target", 0)
    stp    = p.get("stop", 0)
    rr     = p.get("rr", 0)
    cb     = int(float(p.get("confluence_bull", 0)))
    cr     = int(float(p.get("confluence_bear", 0)))
    vp     = float(p.get("vpin", 0))
    vr     = p.get("vpin_regime", "—")
    ofi    = p.get("ofi", "—").upper()
    expl   = p.get("explanation", "—")[:1024]

    color  = _COLORS.get(action, 0xFFFFFF)
    icon   = _ICONS.get(action, "⚪")
    sym_str = f"{exch}:{ticker}" if exch else ticker
    title  = f"{icon} {action.upper()} — {sym_str}  [{sig}]"

    rr_str = f"{float(rr):.2f}R" if rr and float(rr) > 0 else "—"

    fields = [
        {"name": "Signal",        "value": f"**{sig}**",                    "inline": True},
        {"name": "Timeframe",     "value": tf or "—",                       "inline": True},
        {"name": "Price",         "value": f"**{_fp(price)}**",             "inline": True},
        {"name": "🎯 Target",     "value": _fp(tgt),                        "inline": True},
        {"name": "🛑 Stop",       "value": _fp(stp),                        "inline": True},
        {"name": "R:R",           "value": rr_str,                          "inline": True},
        {"name": "NW Regression", "value": _fp(nw),                         "inline": True},
        {"name": "ATR",           "value": _fp(atr),                        "inline": True},
        {"name": "OFI",           "value": ofi,                             "inline": True},
        {"name": "VPIN",          "value": f"{vp:.3f}  **{vr}**",          "inline": True},
        {"name": "🟢 Bull Score", "value": f"{cb}/6  {_dots(cb)}",         "inline": True},
        {"name": "🔴 Bear Score", "value": f"{cr}/6  {_dots(cr)}",         "inline": True},
        {"name": "📝 Analysis",   "value": expl,                            "inline": False},
    ]

    return {
        "embeds": [{
            "title":  title,
            "color":  color,
            "fields": fields,
            "footer": {
                "text": (
                    f"SqueezeOS  •  NW Liquidity Sweeps  •  "
                    f"{datetime.now(timezone.utc).strftime('%H:%M UTC')}"
                )
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }]
    }


@nw_liq_bp.route("/signal", methods=["POST"])
def nw_signal():
    """
    Receives JSON from the NW Liquidity Sweeps Pine Script alert() call.
    Expected fields: ticker, exchange, timeframe, action, signal, price, nw, atr,
                     target, stop, rr, confluence_bull, confluence_bear,
                     vpin, vpin_regime, ofi, explanation
    """
    try:
        payload = request.get_json(force=True, silent=True)
        if not payload:
            return jsonify({"status": "error", "msg": "No JSON body"}), 400

        ticker = payload.get("ticker", "").upper().strip()
        sig    = payload.get("signal", "")
        action = payload.get("action", "").lower()

        if not ticker:
            return jsonify({"status": "error", "msg": "Missing ticker"}), 400
        if action not in ("buy", "sell", "hold"):
            return jsonify({"status": "error", "msg": f"Invalid action: {action}"}), 400

        cooldown_key = f"nw_{ticker}_{sig}"
        if _within_cooldown(cooldown_key):
            logger.info(f"[NW-Liq] Cooldown active: {cooldown_key}")
            return jsonify({"status": "cooldown"}), 200

        logger.info(f"[NW-Liq] {ticker} | {action.upper()} | {sig}")

        embed   = _build_embed(payload)
        success = _post_discord(embed)

        return jsonify({
            "status":  "ok",
            "ticker":  ticker,
            "action":  action,
            "signal":  sig,
            "discord": "sent" if success else "failed",
        })

    except Exception as e:
        logger.error(f"[NW-Liq] Crash: {e}", exc_info=True)
        return jsonify({"status": "error", "msg": str(e)}), 500


@nw_liq_bp.route("/status", methods=["GET"])
def nw_status():
    """Health check — confirms the NW Liquidity webhook is live."""
    configured = bool(os.environ.get("DISCORD_WEBHOOK_NW", ""))
    return jsonify({
        "status":     "ok",
        "endpoint":   "/api/nwliq/signal",
        "discord":    "configured" if configured else "missing DISCORD_WEBHOOK_NW",
        "cooldown_s": _COOLDOWN_SECS,
        "active_cooldowns": len(_cooldowns),
    })
