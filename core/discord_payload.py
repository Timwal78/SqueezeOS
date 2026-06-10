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
    # DUAL GRID LOCK — highest signal in the system
    "DUAL_GRID_LOCK":            "💎",
    # Harmonic Matrix tier signals (new ranked engine)
    "APEX_SINGULARITY":          "💎",
    "GOD_MODE":                  "⚡",
    "GOD_MODE_BULL":             "⚡",
    "GOD_MODE_BEAR":             "🔻",
    "INSTITUTIONAL_CONVERGENCE": "🏛️",
    "FRACTAL_LOCK":              "🔒",
    "FRACTAL_LOCK_BULL":         "🔒",
    "FRACTAL_LOCK_BEAR":         "🔒",
    "PRIME_CONVERGENCE":         "🔥",
    "PRIME_ALIGNMENT":           "🔥",
    "PRIME_PARTIAL":             "📡",
    "WATCH_ACTIVE":              "👁",
    "WATCH_PARTIAL":             "👁",
    # Legacy engine signals
    "BEASTMODE":                 "⚡",
    "HIGH_CONVERGENCE":          "🔥",
    "CONVERGENCE":               "📡",
    "LIE_DETECTOR_ACTIVE":       "🎯",
    "PARTIAL_ALIGNMENT":         "👁",
    "NEUTRAL":                   "—",
}


def _status_block(gate: dict) -> str:
    """Build the 5-engine status grid."""
    labels = {
        "e1_price_suppressed":   "E1 · Price Suppressed",
        "e5_gann_curl":          "E5 · Macro Frequency Curl",
        "e3_volume_firing":      "E3 · Volume Void Breach",
        "e2_kill_zone":          "E2 · Kill Zone Active",
        "e4_temporal_aligned":   "E4 · Temporal Correlation (≥threshold)",
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

    # Harmonic Matrix tier data (new ranked engine)
    sml          = convergence_result.get("sml_matrix") or {}
    matrix_tier  = sml.get("tier", "NONE")
    god_stacked  = sml.get("god_stacked", 0)
    execute_gate = sml.get("execute_gate", False)
    harm_score   = sml.get("harmonic_score", 0)

    # Color selection — GOD_MODE always gets purple beast color
    is_god      = matrix_tier == "GOD_MODE" or signal in ("GOD_MODE", "GOD_MODE_BULL", "APEX_SINGULARITY", "INSTITUTIONAL_CONVERGENCE", "DUAL_GRID_LOCK")
    dual_lock   = signal == "DUAL_GRID_LOCK"
    grid369     = convergence_result.get("grid369") or {}
    base9_count = grid369.get("base9_stacked", 0)

    if execute_gate or is_god:
        color = COLOR_BEAST    # Purple — institutional GOD_MODE
    elif beast:
        color = COLOR_BEAST
    elif trade_type == "put":
        color = COLOR_PUT
    elif active >= 4 or matrix_tier == "PRIME":
        color = COLOR_CALL
    elif lie_det:
        color = COLOR_WATCH
    else:
        color = COLOR_INFO

    sig_icon  = _SIGNAL_ICONS.get(signal, "📡")
    title_str = f"{sig_icon} {signal} — {symbol}"
    if dual_lock:
        title_str = f"💎 DUAL GRID LOCK — {symbol} 💎 [GRID1 + GRID2 CONFIRMED]"
    elif execute_gate and matrix_tier == "GOD_MODE":
        title_str = f"⚡ GOD MODE EXECUTE — {symbol} ⚡ [{god_stacked}/6 SET9 STACKED]"
    elif beast:
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

    # Apex Anchor Matrix / Dual Lock field
    if dual_lock:
        grid369_val = (
            f"💎 **DUAL GRID LOCK ACHIEVED**\n"
            f"Grid 1 GOD_MODE: {god_stacked}/6 SET9 stacked\n"
            f"Grid 2 Base-9: {base9_count}/3 configs stacked\n"
            f"**Two independent methodologies — same sequence confirmed.**"
        )
    elif base9_count > 0:
        grid369_val = f"◆ Grid 2 active — Base-9: **{base9_count}/3** stacked | Base-6: {grid369.get('base6_stacked',0)}/3 | Base-3: {grid369.get('base3_stacked',0)}/3"
    else:
        grid369_val = f"Scanning — Base-9: 0/3 | Base-6: {grid369.get('base6_stacked',0)}/3 | Base-3: {grid369.get('base3_stacked',0)}/3"

    # Harmonic Matrix field
    if matrix_tier and matrix_tier != "NONE":
        tier_display = {
            "GOD_MODE": f"⚡ **GOD MODE** — {god_stacked}/6 SET9 stacked | Harmonic: {harm_score}",
            "PRIME":    f"◆ **PRIME** — {sml.get('prime_stacked',0)} SET6 stacked | Harmonic: {harm_score}",
            "WATCH":    f"● **WATCH** — {sml.get('watch_stacked',0)} SET3 stacked",
        }
        matrix_field_val = tier_display.get(matrix_tier, matrix_tier)
        if execute_gate:
            matrix_field_val += "\n🏛️ **EXECUTE GATE OPEN — INSTITUTIONAL CONFIRMED**"
    else:
        matrix_field_val = "Scanning — insufficient data"

    fields = [
        {
            "name":   "💎 APEX ANCHOR MATRIX",
            "value":  grid369_val,
            "inline": False,
        },
        {
            "name":   "🏛️ SML Harmonic Matrix (Grid 1)",
            "value":  matrix_field_val,
            "inline": False,
        },
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
            "name":   "🪞 Temporal Correlation (E4)",
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
    # Route GOD_MODE signals to DISCORD_WEBHOOK_BEAST if available
    signal = convergence_result.get("signal", "")
    sml    = convergence_result.get("sml_matrix") or {}
    is_god = sml.get("tier") == "GOD_MODE" or sml.get("execute_gate") or \
             signal in ("GOD_MODE", "GOD_MODE_BULL", "APEX_SINGULARITY", "INSTITUTIONAL_CONVERGENCE")

    if not webhook_url:
        if is_god:
            webhook_url = (os.environ.get("DISCORD_WEBHOOK_BEAST") or
                           os.environ.get("DISCORD_WEBHOOK_ALL") or "")
        else:
            webhook_url = os.environ.get("DISCORD_WEBHOOK_ALL", "")
    url = webhook_url

    if not url:
        logger.warning("[Discord] No webhook URL configured — set DISCORD_WEBHOOK_ALL or DISCORD_WEBHOOK_BEAST")
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
