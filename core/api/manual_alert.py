"""
SML MANUAL-TRADE ALERT
Fires a copy-paste-ready Discord alert when GOD MODE confirms, so the trade
can be placed BY HAND on Robinhood. No autonomous execution — human in the loop.

This is the safe path: the system finds and grades the setup, you pull the
trigger on your own account. Built for the trader who keeps execution manual
on real-money accounts (the right call for Robinhood).

(c) Script Master Labs LLC
"""
import os
import logging
import requests

logger = logging.getLogger("ManualAlert")

# Your buying power for position-size suggestions (manual account, e.g. Robinhood)
MANUAL_ACCOUNT_BP = float(os.environ.get("MANUAL_ACCOUNT_BUYING_POWER", "2100.0"))
# Max % of buying power to suggest per trade (risk discipline)
MAX_BP_PER_TRADE_PCT = float(os.environ.get("MANUAL_MAX_BP_PCT", "20.0"))

GREEN = 0x39FF14
GOLD  = 0xFFD700
PINK  = 0xFF1493


def _suggest_size(price: float, is_option: bool) -> str:
    """Suggest a conservative position size for the manual account."""
    if price <= 0:
        return "Size manually — no live price."
    budget = MANUAL_ACCOUNT_BP * (MAX_BP_PER_TRADE_PCT / 100.0)
    if is_option:
        contract_cost = price * 100  # options priced per share, 100/contract
        contracts = int(budget // contract_cost) if contract_cost > 0 else 0
        if contracts < 1:
            return f"⚠️ 1 contract (~${contract_cost:.0f}) exceeds {MAX_BP_PER_TRADE_PCT:.0f}% of BP — consider skipping or sizing down."
        return f"~{contracts} contract(s) (~${contracts * contract_cost:.0f}, ≤{MAX_BP_PER_TRADE_PCT:.0f}% of ${MANUAL_ACCOUNT_BP:.0f} BP)"
    else:
        shares = int(budget // price) if price > 0 else 0
        return f"~{shares} share(s) (~${shares * price:.0f}, ≤{MAX_BP_PER_TRADE_PCT:.0f}% of ${MANUAL_ACCOUNT_BP:.0f} BP)"


def fire_manual_alert(result: dict) -> bool:
    """
    Build and POST a manual-execution Discord alert for a GOD MODE signal.
    Returns True on success. Routes to DISCORD_WEBHOOK_BEAST (or _ALL).
    """
    url = (os.environ.get("DISCORD_WEBHOOK_MANUAL")
           or os.environ.get("DISCORD_WEBHOOK_BEAST")
           or os.environ.get("DISCORD_WEBHOOK_ALL") or "")
    if not url:
        logger.warning("[ManualAlert] No webhook configured")
        return False

    symbol = result.get("symbol", "?")
    signal = result.get("signal", "")
    sml    = result.get("sml_matrix") or {}
    sniper = result.get("options_sniper") or {}
    has_option = bool(sniper) and not sniper.get("error")

    side = "BUY CALL" if ("BULL" in signal or signal in ("GOD_MODE", "BEASTMODE", "DUAL_GRID_LOCK")) else "BUY PUT"
    if not has_option:
        # equity fallback
        side = "BUY" if "BULL" in signal or "BUY" in side else "SELL/SHORT"

    fields = []
    fields.append({"name": "🎯 Signal", "value": f"**{signal}** · GOD MODE confirmed", "inline": True})
    fields.append({"name": "📊 Convergence", "value": f"{sml.get('god_stacked', '?')}/6 stacked", "inline": True})

    if has_option:
        strike = sniper.get("strike")
        exp    = sniper.get("expiration")
        premium = sniper.get("premium") or sniper.get("ask") or 0
        delta  = sniper.get("delta")
        fields.append({"name": "📝 Contract", "value": f"**{symbol} {strike} {sniper.get('type','CALL')}**\nExp: {exp}", "inline": False})
        fields.append({"name": "💵 Premium", "value": f"${premium} (bid {sniper.get('bid')}/ask {sniper.get('ask')})", "inline": True})
        fields.append({"name": "📐 Delta", "value": f"{delta}", "inline": True})
        fields.append({"name": "📦 Suggested size", "value": _suggest_size(float(premium or 0), is_option=True), "inline": False})
        fields.append({"name": "🛡️ Risk plan", "value": "Target: +50–100% premium · Stop: −30–40% premium · Exit by 2 PM ET (0DTE/theta)", "inline": False})
    else:
        price = 0.0
        try:
            price = float(result.get("price") or sml.get("price") or 0)
        except (TypeError, ValueError):
            price = 0.0
        fields.append({"name": "📝 Equity", "value": f"**{side} {symbol}**" + (f" @ ~${price:.2f}" if price else ""), "inline": False})
        fields.append({"name": "📦 Suggested size", "value": _suggest_size(price, is_option=False), "inline": False})

    fields.append({"name": "✋ MANUAL EXECUTION", "value": "Place this on **Robinhood** yourself. This alert does **not** auto-trade. Verify the contract + price before submitting.", "inline": False})

    is_test = bool(result.get("is_test"))
    embed = {
        "title": (f"🧪 TEST ALERT — {symbol} — NOT A REAL SIGNAL (sample data)" if is_test
                  else f"🔫 GOD MODE — {symbol} — TRADE NOW (manual)"),
        "color": (PINK if is_test else GOLD),
        "fields": fields,
        "footer": {"text": ("SML Manual Alert · TEST — fabricated sample data, do not trade on this" if is_test
                             else "SML Manual Alert · You pull the trigger · Not financial advice")},
    }
    payload = {"embeds": [embed]}
    if os.environ.get("DISCORD_MANUAL_MENTION"):
        payload["content"] = os.environ.get("DISCORD_MANUAL_MENTION")  # e.g. "@everyone" or a role ping

    try:
        resp = requests.post(url, json=payload, timeout=8)
        ok = resp.status_code in (200, 204)
        if ok:
            logger.info(f"[ManualAlert] Fired for {symbol}")
        else:
            logger.warning(f"[ManualAlert] Non-200: {resp.status_code} {resp.text[:150]}")
        return ok
    except Exception as e:
        logger.error(f"[ManualAlert] POST failed: {e}")
        return False
