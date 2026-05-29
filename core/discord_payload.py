"""
Discord Webhook Payload Builder — SqueezeOS Beastmode Alerts
=============================================================
Institutional-grade embeds for private Discord servers.
Color scheme:
  Calls  → Neon Green  #00ff66  (0x00ff66)
  Puts   → Neon Red    #ff0055  (0xff0055)
  Info   → Neon Blue   #00aaff  (0x00aaff)
  Watch  → Neon Orange #ff8800  (0xff8800)
"""

import os
import logging
import requests
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("SML.Discord")

# Discord embed colors
COLOR_CALL   = 0x00ff66   # Neon Green
COLOR_PUT    = 0xff0055   # Neon Red
COLOR_INFO   = 0x00aaff   # Neon Blue
COLOR_WATCH  = 0xff8800   # Neon Orange
COLOR_BEAST  = 0x9900ff   # Purple — full Beastmode

# Engine status icons
_ENGINE_ICONS = {True: "🟢", False: "⚫"}
_SIGNAL_ICONS = {
    "BEASTMODE":             "⚡",
    "HIGH_CONVERGENCE":      "🔥",
    "CONVERGENCE":           "📡",
    "LIE_DETECTOR_ACTIVE":   "🎯",
    "PARTIAL_ALIGNMENT":     "👁",
    "NEUTRAL":               "—",
}


def _status_block(gate: dict) -> str:
    """Build the 5-engine status grid."""
    labels = {
        "e1_price_suppressed":   "E1 · Price Suppressed",
        "e5_gann_curl":          "E5 · Gann 42→369 Curl",
        "e3_volume_firing":      "E3 · Volume Void Breach",
        "e2_kill_zone":          "E2 · Kill Zone Active",
        "e4_temporal_aligned":   "E4 · Mirror Aligned (≥70%)",
    }
    lines = []
    for key, label in labels.items():
        entry  = gate.get(key, {})
        active = entry.get("active", False) if isinstance(entry, dict) else bool(entry)
        detail = entry.get("signal") or entry.get("status") or "" if isinstance(entry, dict) else ""
        icon   = _ENGINE_ICONS[active]
        lines.append(f"{icon} **{label}**" + (f" — `{detail}`" if detail else ""))
    return "\n".join(lines)


def build_beastmode_embed(convergence_result: dict,
                          trade_type: Optional[str] = None) -> dict:
    """
    Build a complete Discord embed payload for a Beastmode / High-Convergence signal.
    Returns the raw dict ready for `requests.post(webhook_url, json=payload)`.
    """
    symbol  = convergence_result.get("symbol", "???").upper()
    signal  = convergence_result.get("signal", "NEUTRAL")
    beast   = convergence_result.get("beastmode", False)
    active  = convergence_result.get("active_conditions", 0)
    total   = convergence_result.get("total_conditions", 5)
    score   = convergence_result.get("composite_score", 0)
    lie_det = convergence_result.get("lie_detector", False)
    gate    = convergence_result.get("gate", {})
    sniper  = convergence_result.get("options_sniper") or {}
    e2      = (convergence_result.get("engines") or {}).get("e2", {})
    e4      = (convergence_result.get("engines") or {}).get("e4", {})

    # Color selection
    if beast:
        color = COLOR_BEAST
    elif trade_type == "put":
        color = COLOR_PUT
    elif active >= 4:
        color = COLOR_CALL
    elif lie_det:
        color = COLOR_WATCH
    else:
        color = COLOR_INFO

    sig_icon  = _SIGNAL_ICONS.get(signal, "📡")
    title_str = f"{sig_icon} {signal} — {symbol}"
    if beast:
        title_str = f"⚡ BEASTMODE LOCKED — {symbol} ⚡"

    # Engine status block
    engine_status = _status_block(gate)

    # Kill Zone countdown
    kz_str = "—"
    if e2.get("in_kill_zone"):
        t13_left = e2.get("t13_trading_days_left", "?")
        c35_left = e2.get("c35_calendar_days_left", "?")
        kz_str = f"🔴 T+13: **{t13_left}d** remaining | C+35: **{c35_left}d** remaining"
    elif e2.get("status") == "COUNTING":
        c35_left = e2.get("c35_calendar_days_left", "?")
        kz_str = f"🟡 Counting — C+35 in **{c35_left} cal days**"

    # Mirror correlation
    mirror_str = f"r = **{round(e4.get('correlation', 0), 3)}** (threshold 0.70)"

    # Options sniper block
    if sniper and not sniper.get("error"):
        sniper_str   = f"**{sniper.get('type', 'CALL')} {sniper.get('strike')}** exp {sniper.get('expiration')}"
        delta_str    = str(round(abs(sniper.get("delta", 0)), 4))
        premium_str  = f"${sniper.get('premium', '?')}"
        sniper_error = None
    else:
        sniper_str   = "Awaiting convergence"
        delta_str    = "—"
        premium_str  = "—"
        sniper_error = sniper.get("error") if sniper else None

    fields = [
        {
            "name":   "⚙️ Engine Status Matrix",
            "value":  engine_status,
            "inline": False,
        },
        {
            "name":   "🔥 Convergence Score",
            "value":  f"**{score}/100** | {active}/{total} engines active",
            "inline": True,
        },
        {
            "name":   "🕵️ Lie Detector",
            "value":  "**ACTIVE** — Dark pool accumulating" if lie_det else "Standby",
            "inline": True,
        },
        {
            "name":   "⏱️ Settlement Clock (E2)",
            "value":  kz_str,
            "inline": False,
        },
        {
            "name":   "🪞 Temporal Mirror (E4)",
            "value":  mirror_str,
            "inline": True,
        },
    ]

    # Options sniper fields (only when data available)
    if sniper and not sniper.get("error"):
        fields += [
            {
                "name":   "🎯 Options Sniper — Contract",
                "value":  sniper_str,
                "inline": False,
            },
            {
                "name":   "Δ Delta",
                "value":  delta_str,
                "inline": True,
            },
            {
                "name":   "💰 Premium",
                "value":  premium_str,
                "inline": True,
            },
            {
                "name":   "📊 OI / Volume",
                "value":  f"{sniper.get('open_interest', '?')} / {sniper.get('volume', '?')}",
                "inline": True,
            },
        ]
    elif sniper_error:
        fields.append({
            "name":   "⚠️ Options Sniper",
            "value":  f"`{sniper_error}`",
            "inline": False,
        })

    embed = {
        "title":       title_str,
        "color":       color,
        "description": (
            f"**{symbol}** — ScriptMaster Labs convergence lock\n"
            f"Engines: {active}/{total} · Signal: `{signal}`"
        ),
        "fields":    fields,
        "footer":    {
            "text": "ScriptMaster Labs | SqueezeOS Convergence Engine | squeezeos-api.onrender.com"
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    return {"embeds": [embed]}


def fire_discord(convergence_result: dict,
                 webhook_url: Optional[str] = None,
                 trade_type: Optional[str] = None) -> bool:
    """
    Build and POST the embed to Discord.
    webhook_url falls back to DISCORD_WEBHOOK_ALL env var.
    Returns True on success.
    """
    url = webhook_url or os.environ.get("DISCORD_WEBHOOK_ALL", "")
    if not url:
        logger.warning("[Discord] No webhook URL configured (DISCORD_WEBHOOK_ALL)")
        return False

    payload = build_beastmode_embed(convergence_result, trade_type)
    try:
        resp = requests.post(url, json=payload, timeout=8)
        if resp.status_code in (200, 204):
            logger.info(f"[Discord] Fired for {convergence_result.get('symbol')} — {resp.status_code}")
            return True
        logger.warning(f"[Discord] Non-200 response: {resp.status_code} {resp.text[:200]}")
        return False
    except Exception as e:
        logger.error(f"[Discord] POST failed: {e}")
        return False
