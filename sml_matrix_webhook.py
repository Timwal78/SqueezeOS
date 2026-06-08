"""
SCRIPTMASTER LABS — SML BASE-4 SOVEREIGN HARMONIC MATRIX
TradingView Webhook Bridge v1.0

Receives GOD MODE / APEX SINGULARITY / CRITICAL MASS / CONVERGENCE
alert payloads from TradingView and routes them to:
  → Discord (rich embed with full matrix state)
  → Robinhood MCP (autonomous trade execution when live)
  → SqueezeOS signal cache (live UI display)

Add to server.py:
    from sml_matrix_webhook import register_sml_matrix_routes
    register_sml_matrix_routes(app, cache)

TradingView Alert JSON template:
{
  "source": "SML_BASE4_v6",
  "event": "{{strategy.order.alert_message}}",
  "ticker": "{{ticker}}",
  "interval": "{{interval}}",
  "price": {{close}},
  "total_coiled": <sets_coiled>,
  "harmonic_score": <score>,
  "kp_score": <kp>,
  "macro_bias": "<bias>",
  "vol_regime": "<regime>",
  "compression": "<direction>",
  "bars_in_conv": <bars>,
  "avg_spread": <spread>,
  "atr_pct": <atr_pct>
}
"""
import os
import time
import logging
from datetime import datetime
from typing import Optional, Dict

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# SIGNAL LEVELS — mirrors the Pine Script thresholds
# ─────────────────────────────────────────────────────────────────────────────
SIGNAL_LEVELS = {
    "GOD MODE":          {"color": 0xFFD700, "emoji": "🌟", "priority": 4, "at_here": True},
    "APEX SINGULARITY":  {"color": 0xFFFFFF, "emoji": "🔷", "priority": 3, "at_here": True},
    "CRITICAL MASS":     {"color": 0xFF1493, "emoji": "🔴", "priority": 2, "at_here": False},
    "CONVERGENCE":       {"color": 0x00FF7F, "emoji": "🟢", "priority": 1, "at_here": False},
    "PRIME SIGNAL":      {"color": 0x39FF14, "emoji": "⚡", "priority": 3, "at_here": True},
    "CONVERGENCE RELEASED": {"color": 0x555555, "emoji": "🔓", "priority": 0, "at_here": False},
}


# ─────────────────────────────────────────────────────────────────────────────
# DISCORD EMBED BUILDER
# ─────────────────────────────────────────────────────────────────────────────
class SMLMatrixDiscordFormatter:
    """Builds rich Discord embeds for SML Harmonic Matrix alerts."""

    def build_embed(self, payload: dict) -> dict:
        event         = payload.get("event", "CONVERGENCE").upper()
        ticker        = payload.get("ticker", "?")
        interval      = payload.get("interval", "?")
        price         = payload.get("price", 0)
        total_coiled  = payload.get("total_coiled", 0)
        harmonic_score = payload.get("harmonic_score", 0)
        kp_score      = payload.get("kp_score", 0)
        macro_bias    = payload.get("macro_bias", "?")
        vol_regime    = payload.get("vol_regime", "?")
        compression   = payload.get("compression", "STABLE")
        bars_in_conv  = payload.get("bars_in_conv", 0)
        avg_spread    = payload.get("avg_spread", 0)
        atr_pct       = payload.get("atr_pct", 0)

        # Normalize event name
        level_key = None
        for key in SIGNAL_LEVELS:
            if key in event:
                level_key = key
                break
        level = SIGNAL_LEVELS.get(level_key, SIGNAL_LEVELS["CONVERGENCE"])

        color   = level["color"]
        emoji   = level["emoji"]
        at_here = level["at_here"]

        # Macro bias emoji
        bias_emoji = (
            "🐂" if "BULL" in macro_bias
            else "🐻" if "BEAR" in macro_bias
            else "↔️"
        )

        # Compression direction emoji
        comp_emoji = (
            "🔩" if compression == "TIGHTENING"
            else "💥" if compression == "EXPANDING"
            else "〰️"
        )

        # Vol regime color
        vol_color = (
            "🟢 COMPRESSED — coil loading" if vol_regime == "COMPRESSED"
            else "🔴 EXPANDED — energy releasing" if vol_regime == "EXPANDED"
            else "🟡 NORMAL"
        )

        title = f"{emoji} SML {level_key or event} — {ticker}"

        fields = [
            {"name": "📊 Sets Coiled",      "value": f"**{total_coiled} / 9**",                        "inline": True},
            {"name": "🎯 Harmonic Score",   "value": f"**{harmonic_score:.0f} / 100**",                "inline": True},
            {"name": "⚡ Kinetic Pressure", "value": f"**{kp_score:.0f} / 100**",                     "inline": True},
            {"name": "💲 Price",            "value": f"${price}",                                      "inline": True},
            {"name": "📅 Timeframe",        "value": interval,                                          "inline": True},
            {"name": "⏱ Bars in Conv",      "value": str(bars_in_conv),                                "inline": True},
            {"name": "📐 Avg Spread",       "value": f"{avg_spread:.3f}%",                             "inline": True},
            {"name": "📈 ATR %ile",         "value": f"{atr_pct:.0f}%",                                "inline": True},
            {"name": "🔩 Compression",      "value": f"{comp_emoji} {compression}",                    "inline": True},
            {"name": f"{bias_emoji} Macro Bias",  "value": macro_bias,                                 "inline": True},
            {"name": "💨 Vol Regime",       "value": vol_color,                                         "inline": False},
        ]

        embed = {
            "embeds": [{
                "title":     title,
                "color":     color,
                "fields":    fields,
                "footer":    {"text": f"ScriptMaster Labs SML Matrix v6 | {datetime.now().strftime('%I:%M %p ET')}"},
                "timestamp": datetime.utcnow().isoformat(),
            }]
        }

        if at_here:
            embed["content"] = f"@here {emoji} **SML {level_key} — {ticker} — {interval}**"

        return embed


# ─────────────────────────────────────────────────────────────────────────────
# ROUTE REGISTRATION
# ─────────────────────────────────────────────────────────────────────────────
def register_sml_matrix_routes(app, cache):
    """
    Register all SML Harmonic Matrix webhook routes into the Flask app.

    Usage in server.py:
        from sml_matrix_webhook import register_sml_matrix_routes
        register_sml_matrix_routes(app, cache)
    """
    import requests as req_lib
    from flask import request, jsonify

    formatter = SMLMatrixDiscordFormatter()

    def _post_discord(embed: dict):
        """Fire the alert to all configured SML Matrix Discord webhooks."""
        urls = list(filter(None, [
            os.environ.get("DISCORD_WEBHOOK_SML",   ""),
            os.environ.get("DISCORD_WEBHOOK_BEAST", ""),   # fallback to beast channel
            os.environ.get("DISCORD_WEBHOOK_ALL",   ""),
        ]))

        if not urls:
            logger.warning("[SML MATRIX] No Discord webhooks configured. Set DISCORD_WEBHOOK_SML env var.")
            return

        seen = set()
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                try:
                    r = req_lib.post(url, json=embed, timeout=8)
                    if r.status_code not in (200, 204):
                        logger.warning(f"[SML MATRIX DISCORD] {r.status_code}: {r.text[:120]}")
                    else:
                        logger.info(f"[SML MATRIX DISCORD] Sent: {embed.get('embeds', [{}])[0].get('title', '')}")
                        break   # first successful send, avoid duplicates
                except Exception as e:
                    logger.error(f"[SML MATRIX DISCORD] Post error: {e}")

    def _store_signal(payload: dict, level_key: str):
        """Persist signal to cache for UI display."""
        with cache.lock:
            sig = {
                "source":          "SML_BASE4_v6",
                "event":           level_key,
                "ticker":          payload.get("ticker", "?"),
                "interval":        payload.get("interval", "?"),
                "price":           payload.get("price", 0),
                "total_coiled":    payload.get("total_coiled", 0),
                "harmonic_score":  payload.get("harmonic_score", 0),
                "kp_score":        payload.get("kp_score", 0),
                "macro_bias":      payload.get("macro_bias", "?"),
                "vol_regime":      payload.get("vol_regime", "?"),
                "compression":     payload.get("compression", "STABLE"),
                "bars_in_conv":    payload.get("bars_in_conv", 0),
                "ts":              time.time(),
            }
            if not hasattr(cache, "sml_signals"):
                cache.sml_signals = []
            cache.sml_signals.insert(0, sig)
            cache.sml_signals = cache.sml_signals[:100]   # keep last 100

    # ── /api/webhooks/sml-matrix — Primary TradingView receiver ──────────────
    @app.route("/api/webhooks/sml-matrix", methods=["POST"])
    def sml_matrix_webhook():
        """
        Primary TradingView webhook endpoint for SML Base-4 Harmonic Matrix alerts.

        Expected JSON body from TradingView alert:
        {
          "source": "SML_BASE4_v6",
          "event":  "GOD MODE",         ← or APEX SINGULARITY / CRITICAL MASS / CONVERGENCE / PRIME SIGNAL
          "ticker": "SPY",
          "interval": "15",
          "price": 527.40,
          "total_coiled": 9,
          "harmonic_score": 97,
          "kp_score": 84,
          "macro_bias": "MACRO BULL",
          "vol_regime": "COMPRESSED",
          "compression": "TIGHTENING",
          "bars_in_conv": 12,
          "avg_spread": 0.41,
          "atr_pct": 18
        }
        """
        try:
            payload = request.get_json(force=True, silent=True)
            if not payload:
                return jsonify({"status": "error", "message": "No JSON body"}), 400

            # Validate source
            source = payload.get("source", "")
            if source != "SML_BASE4_v6":
                return jsonify({"status": "ignored", "message": f"Unknown source: {source}"}), 200

            event  = payload.get("event",  "").upper()
            ticker = payload.get("ticker", "").upper().strip()

            if not event:
                return jsonify({"status": "error", "message": "No event specified"}), 400

            # Determine signal level
            level_key = None
            for key in SIGNAL_LEVELS:
                if key in event:
                    level_key = key
                    break

            level_info = SIGNAL_LEVELS.get(level_key, SIGNAL_LEVELS["CONVERGENCE"])
            priority   = level_info["priority"]

            logger.info(f"[SML MATRIX] Received: {ticker} | {level_key or event} | priority={priority}")

            # Cooldown — GOD MODE: no cooldown. Others: 5 min per ticker+event
            if level_key != "GOD MODE":
                cooldown_key = f"sml_{ticker}_{level_key}"
                if hasattr(cache, "can_alert") and not cache.can_alert(cooldown_key, "SML", cooldown=300):
                    logger.info(f"[SML MATRIX] Cooldown active: {cooldown_key}")
                    return jsonify({"status": "cooldown"}), 200

            # Log to cache event log
            if hasattr(cache, "log_event"):
                cache.log_event(f"{level_info['emoji']} SML {level_key}: {ticker} | Score: {payload.get('harmonic_score', 0)}/100")

            # Build and fire Discord embed
            embed = formatter.build_embed(payload)
            _post_discord(embed)

            # Store in signal cache for UI
            _store_signal(payload, level_key or event)

            # ── ROBINHOOD MCP HOOK (placeholder — wire up when Robinhood MCP is live) ──
            # TODO: When Robinhood MCP is connected, insert autonomous execution here.
            # Only fire on GOD MODE + PRIME SIGNAL + APEX SINGULARITY with vol_regime == COMPRESSED
            # Example (pseudocode):
            #   if level_key in ("GOD MODE", "PRIME SIGNAL") and payload.get("vol_regime") == "COMPRESSED":
            #       robinhood_mcp.execute_signal(ticker, payload)

            return jsonify({
                "status":          "ok",
                "event":           level_key or event,
                "ticker":          ticker,
                "harmonic_score":  payload.get("harmonic_score", 0),
                "total_coiled":    payload.get("total_coiled", 0),
                "discord":         "fired",
                "robinhood":       "pending_mcp_connection",
            })

        except Exception as e:
            logger.error(f"[SML MATRIX] Webhook crash: {e}", exc_info=True)
            return jsonify({"status": "error", "message": str(e)}), 500

    # ── /api/webhooks/sml-matrix/signals — UI signal history ─────────────────
    @app.route("/api/webhooks/sml-matrix/signals", methods=["GET"])
    def sml_matrix_signals():
        """Returns the last 100 SML Matrix signals for the live dashboard UI."""
        signals = getattr(cache, "sml_signals", [])
        return jsonify({"status": "ok", "count": len(signals), "data": signals})

    # ── /api/webhooks/sml-matrix/health — Ping endpoint ─────────────────────
    @app.route("/api/webhooks/sml-matrix/health", methods=["GET"])
    def sml_matrix_health():
        """Quick health check — confirms the SML Matrix webhook bridge is live."""
        signals = getattr(cache, "sml_signals", [])
        last    = signals[0] if signals else None
        return jsonify({
            "status":        "live",
            "endpoint":      "/api/webhooks/sml-matrix",
            "version":       "SML_BASE4_v6",
            "total_signals": len(signals),
            "last_signal":   last,
        })

    logger.info("[SML MATRIX] Routes registered: /api/webhooks/sml-matrix | /api/webhooks/sml-matrix/signals | /api/webhooks/sml-matrix/health")
