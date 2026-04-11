"""
SQUEEZEOS BEAST PRO — Webhook Receiver + Options Killer
Receives signals from BEAST PRO v2.0 PineScript webhook.
→ Grabs live options chain from Schwab
→ Selects the BEST contract (strike, expiry, Greeks)
→ Posts a killer Discord alert with full actionable detail

Add to server.py:
    from beast_webhook import register_beast_routes
    register_beast_routes(app, cache)
"""
import os
import time
import logging
import math
from datetime import datetime, timedelta
from typing import Optional, Dict, List

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# BEAST CONTRACT SELECTOR — picks the best option from the Schwab chain
# ──────────────────────────────────────────────────────────────────────────────
class BeastContractSelector:
    """
    Institutional-grade option contract selection — tuned for sub-$25 stocks.
    Targets:
      - Liquid strikes (high OI, tight spread)
      - Sweet delta range 0.30–0.60 (directional, affordable on cheap underlyings)
      - 7–45 DTE (enough time, not too slow)
      - At-ask aggressive order flow preferred
      - Option price sweet spot: $0.10–$5 (realistic for sub-$25 stocks)
    FAVORITES (AMC, GME) are always processed regardless of price.
    """

    def select(self, chain_data: dict, action: str, payload: dict) -> Optional[Dict]:
        """
        action: "CALL" or "PUT"
        Returns best contract dict or None.
        """
        opt_type = "CALL" if action == "CALL" else "PUT"
        activities = chain_data.get("unusual_activity", [])
        underlying = chain_data.get("underlying_price", 0)

        # Pull the full chain, not just unusual — we need to score ALL contracts
        raw_map   = chain_data.get("_raw_calls" if opt_type == "CALL" else "_raw_puts", [])

        candidates = []

        # Sub-$25 stocks have wider percentage swings, so use 20% ATM window
        # (vs 15% for large-caps) to catch realistic strikes.
        atm_window = 0.20

        # Primary: use unusual activity hits that match direction
        for c in activities:
            ctype = c.get("type", "")
            if ctype != opt_type:
                continue
            dte    = c.get("days_to_expiry", 0)
            delta  = abs(c.get("delta", 0))
            iv     = c.get("implied_volatility", 0)
            vol    = c.get("volume", 0)
            oi     = c.get("open_interest", 1)
            price  = c.get("price", 0)
            strike = c.get("strike", 0)
            score  = c.get("unusual_score", 0)

            # Law 2: 100% FETCH — Removed strike distance boundary, price ceilings, and DTE boundaries.
            # Scoring rather than filtering.

            # Score the contract
            fit = 0

            # Width-aware ATM distance check for cheap underlyings
            if underlying > 0:
                dist_pct = abs(strike - underlying) / underlying
                if dist_pct <= atm_window:
                    fit += 10

            # Delta sweetspot 0.35–0.65
            if 0.35 <= delta <= 0.65:
                fit += 30
            elif 0.20 <= delta < 0.35 or 0.65 < delta <= 0.80:
                fit += 15

            # DTE sweetspot 14–30
            if 14 <= dte <= 30:
                fit += 25
            elif 7 <= dte < 14 or 30 < dte <= 45:
                fit += 15
            elif dte <= 7:
                fit += 5    # lottos: low fit but still usable

            # Liquidity
            if oi >= 1000:
                fit += 20
            elif oi >= 500:
                fit += 12
            elif oi >= 100:
                fit += 5

            # Price range — for sub-$25 underlyings options are cheap.
            # Primary sweet zone: $0.10–$5. Secondary: $5–$10.
            if 0.10 <= price <= 5.0:
                fit += 20    # Best bang for money on cheap stocks
            elif 5.0 < price <= 10.0:
                fit += 10
            elif 10.0 < price <= 20.0:
                fit += 5
            # Options over $20 on a sub-$25 stock = deep ITM junk, no bonus

            # Unusual activity bonus
            fit += min(score // 10, 15)

            candidates.append({**c, "_fit": fit})

        if not candidates:
            return None

        best = max(candidates, key=lambda x: x["_fit"])
        return best


# ──────────────────────────────────────────────────────────────────────────────
# DISCORD BEAST EMBED BUILDER
# ──────────────────────────────────────────────────────────────────────────────
class BeastDiscordFormatter:

    COLORS = {
        "MEGA_CALL":  0x00FFFF,   # Neon Cyan
        "MEGA_PUT":   0xFF00CD,   # Neon Pink
        "CALL":       0x00FF00,   # Neon Lime
        "PUT":        0xFF2828,   # Neon Red
        "GHOST":      0x00BFFF,
        "SWEEP":      0xFFD700,
        "BOS":        0xA64DFF,
        "OB":         0xFF8C00,
    }

    def build_signal_embed(self, payload: dict, contract: Optional[dict]) -> dict:
        action    = payload.get("action", "CALL")
        is_mega   = payload.get("mega", False)
        sym       = payload.get("ticker", "?")
        price     = payload.get("price", 0)
        score     = payload.get("score", 0)
        grade     = payload.get("grade", "")
        rr        = payload.get("rr", "?")
        target    = payload.get("target", "?")
        stop      = payload.get("stop", "?")
        trend     = payload.get("trend", "?")
        squeeze   = payload.get("squeeze", "NONE")
        mtf       = payload.get("mtf_label", "?")
        hv        = payload.get("hv", "?")
        hv_rank   = payload.get("hv_rank", "?")
        ghost     = payload.get("ghost", False)
        sweep     = payload.get("sweep", "NONE")
        bos       = payload.get("bos", "NONE")
        sess      = payload.get("session", "—")
        risk_on   = payload.get("risk_on", True)
        vwap_band = payload.get("vwap_band", "?")
        fvg       = payload.get("fvg", "NONE")
        vol_r     = payload.get("vol_ratio", 1.0)
        ob        = payload.get("ob", "NONE")
        tf        = payload.get("tf", "")

        # Title
        if is_mega:
            title_emoji = "🔥 MEGA"
            color_key   = f"MEGA_{action}"
        else:
            title_emoji = "⚡"
            color_key   = action

        color  = self.COLORS.get(color_key, 0xFFFFFF)
        dir_emoji = "🟢" if action == "CALL" else "🔴"
        title  = f"{title_emoji} {dir_emoji} BEAST {action} — {sym}"

        # Smart Money flags
        smc_flags = []
        if ghost:           smc_flags.append("👻 Ghost Print")
        if sweep != "NONE": smc_flags.append(f"💧 Liq Sweep ({sweep})")
        if bos  != "NONE":  smc_flags.append(f"⚡ BOS {bos}")
        if fvg  != "NONE":  smc_flags.append(f"📦 FVG {fvg}")
        if ob   != "NONE":  smc_flags.append(f"🏦 OB {ob}")
        smc_line = " · ".join(smc_flags) if smc_flags else "—"

        # Build contract block
        if contract:
            strike   = contract.get("strike", 0)
            exp_fmt  = contract.get("expiry_formatted", "?")
            dte      = contract.get("days_to_expiry", 0)
            c_price  = contract.get("price", 0)
            c_vol    = contract.get("volume", 0)
            c_oi     = contract.get("open_interest", 0)
            c_iv     = contract.get("implied_volatility", 0)
            c_delta  = contract.get("delta", 0)
            c_prem   = contract.get("premium", 0)
            c_score  = contract.get("unusual_score", 0)
            c_label  = contract.get("sweep_label", action)
            c_sent   = contract.get("sentiment", "NEUTRAL")
            vol_oi   = contract.get("vol_oi_ratio", 0)

            # Actionable trade line
            trade_line = (
                f"**BUY {sym} ${strike:.2f} "
                f"{action} exp {exp_fmt} ({dte} DTE)**"
            )
            c_iv_pct   = f"{c_iv:.0%}" if c_iv > 0 else "—"
            c_delta_s  = f"{c_delta:.3f}" if c_delta != 0 else "—"

            contract_fields = [
                {"name": "🎯 TRADE",    "value": trade_line,        "inline": False},
                {"name": "Strike",      "value": f"${strike:.2f}",  "inline": True},
                {"name": "Expiry",      "value": f"{exp_fmt} ({dte}d)", "inline": True},
                {"name": "Option Price","value": f"${c_price:.2f}", "inline": True},
                {"name": "📊 Volume",   "value": f"{c_vol:,}",      "inline": True},
                {"name": "OI",          "value": f"{c_oi:,}",       "inline": True},
                {"name": "Vol/OI",      "value": f"{vol_oi:.1f}x",  "inline": True},
                {"name": "IV",          "value": c_iv_pct,          "inline": True},
                {"name": "Δ Delta",     "value": c_delta_s,         "inline": True},
                {"name": "💰 Premium",  "value": f"${c_prem:,.0f}", "inline": True},
                {"name": "Flow Label",  "value": c_label,           "inline": True},
                {"name": "Sentiment",   "value": c_sent,            "inline": True},
                {"name": "Flow Score",  "value": f"{c_score}/100",  "inline": True},
            ]
        else:
            contract_fields = [
                {"name": "⚠️ Options Chain",
                 "value": "No liquid contract found — check manually or wait for Schwab chain.",
                 "inline": False}
            ]

        fields = [
            # Chart Signal Block
            {"name": "Beast Score",      "value": f"**{score}/100** — {grade}", "inline": True},
            {"name": "Price",            "value": f"${price}",                  "inline": True},
            {"name": "TF",               "value": tf,                           "inline": True},
            {"name": "📈 Target",        "value": f"${target}",                 "inline": True},
            {"name": "🛑 Stop",          "value": f"${stop}",                   "inline": True},
            {"name": "R:R",              "value": f"{rr}R",                     "inline": True},
            {"name": "Daily Trend",      "value": trend,                        "inline": True},
            {"name": "Squeeze",          "value": squeeze,                      "inline": True},
            {"name": "VWAP Band",        "value": vwap_band,                    "inline": True},
            {"name": "MTF",              "value": mtf,                          "inline": True},
            {"name": "HV",               "value": f"{hv} (Rank: {hv_rank}%)",  "inline": True},
            {"name": "Vol×",             "value": f"{vol_r}x",                  "inline": True},
            {"name": "Session",          "value": sess,                         "inline": True},
            {"name": "Risk Env",         "value": "✅ RISK ON" if risk_on else "🚫 RISK OFF", "inline": True},
            {"name": "SMC Flags",        "value": smc_line,                     "inline": False},
        ] + contract_fields

        embed = {
            "embeds": [{
                "title": title,
                "color": color,
                "fields": fields,
                "footer": {
                    "text": f"SqueezeOS BEAST PRO v2.0 | {datetime.now().strftime('%I:%M %p ET')}"
                },
                "timestamp": datetime.utcnow().isoformat(),
            }]
        }

        # Add @here mention for mega signals
        if is_mega:
            embed["content"] = "@here 🔥 **MEGA BEAST SIGNAL — LOOK NOW**"

        return embed

    def build_event_embed(self, payload: dict) -> Optional[dict]:
        """Lightweight embeds for ghost / sweep / BOS / OB events."""
        event  = payload.get("event", "")
        sym    = payload.get("ticker", "?")
        price  = payload.get("price", 0)
        score  = payload.get("score", 0)

        if event == "GHOST_PRINT":
            vol_r = payload.get("vol_ratio", 0)
            return {"embeds": [{
                "title": f"👻 GHOST PRINT — {sym}",
                "description": (
                    f"High-volume doji/absorption at **${price}**\n"
                    f"Vol Ratio: **{vol_r}x** | Score: **{score}**\n"
                    f"*Smart money absorbing — breakout likely.*"
                ),
                "color": 0x00BFFF,
                "footer": {"text": f"SqueezeOS BEAST PRO | {datetime.now().strftime('%I:%M %p ET')}"}
            }]}

        elif event == "LIQ_SWEEP":
            side = payload.get("side", "?")
            return {"embeds": [{
                "title": f"💧 LIQUIDITY SWEEP {side} — {sym}",
                "description": (
                    f"Price swept prior {side} liquidity at **${price}** then reclaimed.\n"
                    f"Score: **{score}**\n"
                    f"*Classic stop-hunt. Reversal / continuation setup loading.*"
                ),
                "color": 0xFFD700,
                "footer": {"text": f"SqueezeOS BEAST PRO | {datetime.now().strftime('%I:%M %p ET')}"}
            }]}

        elif event == "BOS":
            direction = payload.get("dir", "?")
            return {"embeds": [{
                "title": f"⚡ MARKET STRUCTURE BREAK {direction} — {sym}",
                "description": (
                    f"Break of Structure confirmed at **${price}**\n"
                    f"Score: **{score}**\n"
                    f"*Institutional confirmation of trend change.*"
                ),
                "color": 0xA64DFF,
                "footer": {"text": f"SqueezeOS BEAST PRO | {datetime.now().strftime('%I:%M %p ET')}"}
            }]}

        elif event == "OB_TOUCH":
            side = payload.get("side", "?")
            return {"embeds": [{
                "title": f"🏦 ORDER BLOCK TOUCH {side} — {sym}",
                "description": (
                    f"Price returning to institutional {side} Order Block at **${price}**\n"
                    f"Score: **{score}**\n"
                    f"*High probability reaction zone — watch for reversal.*"
                ),
                "color": 0xFF8C00,
                "footer": {"text": f"SqueezeOS BEAST PRO | {datetime.now().strftime('%I:%M %p ET')}"}
            }]}

        return None


# ──────────────────────────────────────────────────────────────────────────────
# ROUTE REGISTRATION
# ──────────────────────────────────────────────────────────────────────────────
def register_beast_routes(app, cache):
    """
    Call this from server.py after app is created.
    Usage:
        from beast_webhook import register_beast_routes
        register_beast_routes(app, cache)
    """
    import requests as req_lib
    from flask import request, jsonify

    selector  = BeastContractSelector()
    formatter = BeastDiscordFormatter()

    def _post_discord(embed: dict):
        """Fire to all configured Beast webhooks."""
        urls = list(filter(None, [
            os.environ.get("DISCORD_WEBHOOK_BEAST", ""),
            os.environ.get("DISCORD_WEBHOOK_FLOW",  ""),
            os.environ.get("DISCORD_WEBHOOK_ALL",   ""),
        ]))

        # Warn if no webhooks configured
        if not urls:
            logger.warning("[BEAST DISCORD] No Discord webhooks configured. Set DISCORD_WEBHOOK_BEAST, DISCORD_WEBHOOK_FLOW, or DISCORD_WEBHOOK_ALL environment variables.")
            return

        # Deduplicate
        seen = set()
        success = False
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                try:
                    r = req_lib.post(url, json=embed, timeout=8)
                    if r.status_code not in (200, 204):
                        logger.warning(f"[BEAST DISCORD] {r.status_code}: {r.text[:120]}")
                    else:
                        logger.info(f"[BEAST DISCORD] Sent: {embed.get('embeds', [{}])[0].get('title', '')}")
                        success = True
                        break  # send to first working URL only to avoid duplicates
                except Exception as e:
                    logger.error(f"[BEAST DISCORD] Post error: {e}")

        if not success and urls:
            logger.error(f"[BEAST DISCORD] Failed to post to any of {len(urls)} configured webhook(s)")

    @app.route("/api/beast", methods=["POST"])
    def beast_webhook():
        """
        Receives JSON from BEAST PRO v2.0 PineScript alert.
        Supports:
          - action = CALL / PUT  → full options lookup + Discord killer alert
          - event  = GHOST_PRINT / LIQ_SWEEP / BOS / OB_TOUCH → lightweight event alert
        """
        try:
            payload = request.get_json(force=True, silent=True)
            if not payload:
                return jsonify({"status": "error", "message": "No JSON body"}), 400

            source = payload.get("source", "")
            if source != "BEAST_PRO_v2":
                return jsonify({"status": "ignored", "message": "Unknown source"}), 200

            sym    = payload.get("ticker", "").upper().strip()
            action = payload.get("action", "").upper()
            event  = payload.get("event",  "").upper()

            if not sym:
                return jsonify({"status": "error", "message": "No ticker"}), 400

            # Law 2: 100% FETCH — Purged price ceiling.
            # No ticker left behind.
            BEAST_FAVORITES = set(os.environ.get("BEAST_FAVORITES", "AMC,GME").split(","))
            signal_price = float(payload.get("price", 0))
            BEAST_MAX_PRICE = float(os.environ.get("BEAST_MAX_PRICE", "25.0"))
            
            # Removed skipping logic for price ceiling

            logger.info(f"[BEAST] Received: {sym} | action={action} | event={event}")
            cache.log_event(f"🔥 BEAST SIGNAL: {sym} {action or event}")

            # ── Event Alerts (non-directional) ────────────────────────────────
            if event and not action:
                embed = formatter.build_event_embed(payload)
                if embed:
                    _post_discord(embed)
                return jsonify({"status": "ok", "mode": "event", "event": event})

            # ── Directional Signal: CALL or PUT ───────────────────────────────
            if action not in ("CALL", "PUT"):
                return jsonify({"status": "ignored", "reason": "no action"}), 200

            # Cooldown check (avoid spam — 5 min per ticker+action)
            cooldown_key = f"beast_{sym}_{action}"
            if not cache.can_alert(cooldown_key, "BEAST", cooldown=300):
                logger.info(f"[BEAST] Cooldown active: {cooldown_key}")
                return jsonify({"status": "cooldown"}), 200

            # Fetch live options chain from Schwab
            contract = None
            chain    = None
            try:
                from options_service import OptionsProService
                opts_svc = OptionsProService()
                chain = opts_svc.get_options_chain(sym)
                if chain and chain.get("unusual_activity"):
                    contract = selector.select(chain, action, payload)
                    if contract:
                        logger.info(
                            f"[BEAST] Best contract: {sym} "
                            f"${contract['strike']} {contract['type']} "
                            f"exp {contract.get('expiry_formatted','?')} "
                            f"@ ${contract['price']:.2f} | "
                            f"fit-score={contract.get('_fit',0)}"
                        )
                    else:
                        logger.warning(f"[BEAST] No qualifying contract found for {sym} {action}")
                else:
                    logger.warning(f"[BEAST] Empty or missing options chain for {sym}")
            except ImportError:
                logger.error("[BEAST] options_service module not found. Make sure it is installed.")
            except Exception as e:
                logger.error(f"[BEAST] Options chain error for {sym}: {e}")
                # Continue without contract data rather than failing completely

            # Build and fire Discord embed
            embed = formatter.build_signal_embed(payload, contract)
            _post_discord(embed)

            # Store signal in cache so the UI can display it
            with cache.lock:
                beast_sig = {
                    "symbol":   sym,
                    "action":   action,
                    "is_mega":  payload.get("mega", False),
                    "price":    payload.get("price", 0),
                    "score":    payload.get("score", 0),
                    "grade":    payload.get("grade", ""),
                    "contract": contract,
                    "ts":       time.time(),
                }
                if not hasattr(cache, "beast_signals"):
                    cache.beast_signals = []
                cache.beast_signals.insert(0, beast_sig)
                # Law 2: 100% FETCH — Removed history limit

            return jsonify({
                "status":   "ok",
                "symbol":   sym,
                "action":   action,
                "contract": contract,
                "discord":  "fired",
            })

        except Exception as e:
            logger.error(f"[BEAST] Webhook crash: {e}", exc_info=True)
            return jsonify({"status": "error", "message": str(e)}), 500

    @app.route("/api/beast/signals", methods=["GET"])
    def get_beast_signals():
        """Returns the last 20 BEAST PRO signals (for UI display)."""
        signals = getattr(cache, "beast_signals", [])
        return jsonify({"status": "ok", "data": signals})

    logger.info("[BEAST] Beast PRO webhook routes registered: /api/beast | /api/beast/signals")
