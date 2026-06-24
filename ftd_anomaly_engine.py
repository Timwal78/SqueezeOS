"""
ShortSqueeze Swarm — FTD/Reg SHO Anomaly Detection Engine
═══════════════════════════════════════════════════════════
Background daemon that watches the FTD data store for:
  * NEW_THRESHOLD_LIST_ENTRY — symbol newly appears on SEC Reg SHO threshold list
  * FTD_SPIKE                — latest FTD fail_shares >= 2.0x rolling-window avg

Each detection fires:
  1. A free Discord alert (teaser — symbol + anomaly type + spike ratio, no thesis)
  2. An in-memory record appended to the public free feed at GET /api/ftd/alerts

Full descriptive detail (T+21/T+35 markers, notional, threshold history) stays
behind the existing paid /api/ftd/cycle/<symbol> endpoint (0.05 RLUSD).

Compliance: descriptive only. No "squeeze imminent" language. Per AGENT_LAW §1,
this engine only fires on data already present in the FTD store — it does not
fetch or fabricate anything new.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from datetime import datetime
from typing import Deque, Dict, List, Optional

logger = logging.getLogger("SqueezeOS-FTD-Anomaly")

SCAN_INTERVAL_S = 900          # 15 min between scans
SPIKE_THRESHOLD = 2.0           # fail_shares >= 2x rolling avg
FEED_MAXLEN = 100                # public feed keeps last 100 alerts

# Per-symbol Discord cooldown — prevents re-alerting the same spike every cycle.
# Default 24h; override with FTD_ALERT_COOLDOWN_S env var.
import os as _os
_ALERT_COOLDOWN_S = int(_os.environ.get("FTD_ALERT_COOLDOWN_S", str(86400)))
_alert_cooldown: Dict[str, float] = {}  # symbol_type → last-alert epoch

_feed: Deque[dict] = deque(maxlen=FEED_MAXLEN)
_feed_lock = threading.RLock()

# tracks symbols already on the threshold list as of last scan, so we can
# detect *new* entries only
_known_threshold_symbols: set = set()
_known_init = False


def get_feed(limit: int = 25) -> List[dict]:
    """Return the most recent N alerts (newest first)."""
    with _feed_lock:
        items = list(_feed)[-limit:]
    items.reverse()
    return items


def _push(alert: dict) -> None:
    with _feed_lock:
        _feed.append(alert)


def _can_alert(symbol: str, atype: str) -> bool:
    """Return True if the per-symbol cooldown has expired."""
    key = f"{symbol}_{atype}"
    last = _alert_cooldown.get(key, 0)
    return (time.time() - last) >= _ALERT_COOLDOWN_S


def _mark_alert(symbol: str, atype: str) -> None:
    _alert_cooldown[f"{symbol}_{atype}"] = time.time()


def _fire_discord(discord, alert: dict) -> None:
    if not discord or not getattr(discord, "enabled", False):
        return
    try:
        atype = alert["anomaly_type"]
        symbol = alert["symbol"]
        severity_colors = {
            "NEW_THRESHOLD_LIST_ENTRY": 0xFF8C00,
            "FTD_SPIKE": 0xFF0000,
        }
        atype_emoji = {
            "NEW_THRESHOLD_LIST_ENTRY": "📋",
            "FTD_SPIKE": "📈",
        }
        color = severity_colors.get(atype, 0x00BFFF)
        emoji = atype_emoji.get(atype, "🔍")

        fields = [
            {"name": "Symbol", "value": f"**{symbol}**", "inline": True},
            {"name": "Anomaly", "value": atype.replace("_", " "), "inline": True},
        ]
        if alert.get("spike_ratio") is not None:
            fields.append({"name": "Spike Ratio", "value": f"{alert['spike_ratio']:.2f}x", "inline": True})
        if alert.get("entry_date"):
            fields.append({"name": "Threshold Entry", "value": alert["entry_date"], "inline": True})

        fields.append({
            "name": "Detail",
            "value": f"Full settlement-cycle data: `/api/ftd/cycle/{symbol}` (0.05 RLUSD)",
            "inline": False,
        })

        embed = {
            "embeds": [{
                "title": f"{emoji} SHORTSQUEEZE SWARM — {symbol}",
                "description": (
                    "Public SEC Reg SHO data anomaly detected. Descriptive feed only — "
                    "not a trade signal."
                ),
                "color": color,
                "fields": fields,
                "footer": {"text": f"ShortSqueeze Swarm | FTD channel | {datetime.now().strftime('%I:%M %p ET')}"},
                "timestamp": datetime.utcnow().isoformat(),
            }]
        }

        # Route to dedicated FTD channel first; never fall back to the main channel
        url = _os.environ.get("DISCORD_WEBHOOK_FTD", "")
        if not url:
            logger.debug("[FTD-ANOMALY] DISCORD_WEBHOOK_FTD not set — alert suppressed")
            return
        discord._post(url, embed)
    except Exception as e:
        logger.warning("[FTD-ANOMALY] discord post failed: %s", e)


def _scan_once(discord=None) -> None:
    global _known_init
    from core.ftd_data import get_store

    store = get_store()
    status = store.status()
    if not status.get("available"):
        return

    now_iso = datetime.utcnow().isoformat()

    # ── NEW_THRESHOLD_LIST_ENTRY ────────────────────────────────────────
    entries = store.threshold_list()
    current_symbols = {e["symbol"] for e in entries}

    if not _known_init:
        # First scan: seed without firing alerts for the entire existing list
        _known_threshold_symbols.clear()
        _known_threshold_symbols.update(current_symbols)
        _known_init = True
    else:
        new_symbols = current_symbols - _known_threshold_symbols
        for entry in entries:
            sym = entry["symbol"]
            if sym not in new_symbols:
                continue
            if not _can_alert(sym, "NEW_THRESHOLD_LIST_ENTRY"):
                continue
            alert = {
                "symbol": sym,
                "anomaly_type": "NEW_THRESHOLD_LIST_ENTRY",
                "entry_date": entry.get("entry_date"),
                "company": entry.get("company"),
                "spike_ratio": None,
                "ts": now_iso,
            }
            _push(alert)
            _fire_discord(discord, alert)
            _mark_alert(sym, "NEW_THRESHOLD_LIST_ENTRY")
            logger.info("[FTD-ANOMALY] NEW_THRESHOLD_LIST_ENTRY %s", sym)
        _known_threshold_symbols.clear()
        _known_threshold_symbols.update(current_symbols)

    # ── FTD_SPIKE ────────────────────────────────────────────────────────
    with store._lock:
        symbols = list(store._by_symbol.keys())

    for sym in symbols:
        ratio = store.latest_ratio(sym)
        if not ratio:
            continue
        pct = ratio.get("rank_percentile", 0)
        latest_fails = ratio["latest"]["fail_shares"]
        avg = ratio.get("window_avg_fails") or 0
        if avg <= 0:
            continue
        spike = latest_fails / avg
        if spike < SPIKE_THRESHOLD:
            continue
        # only alert on the 95th+ percentile reading to avoid noise
        if pct < 0.95:
            continue
        # skip if this symbol already alerted within the cooldown window
        if not _can_alert(sym, "FTD_SPIKE"):
            continue

        alert = {
            "symbol": sym,
            "anomaly_type": "FTD_SPIKE",
            "entry_date": None,
            "company": None,
            "spike_ratio": round(spike, 2),
            "settlement_date": ratio["latest"]["settlement_date"],
            "ts": now_iso,
        }
        _push(alert)
        _fire_discord(discord, alert)
        _mark_alert(sym, "FTD_SPIKE")
        logger.info("[FTD-ANOMALY] FTD_SPIKE %s ratio=%.2f", sym, spike)


def _loop(discord=None) -> None:
    # Give the FTD pollers time to warm up on first boot
    time.sleep(60)
    while True:
        try:
            _scan_once(discord)
        except Exception as e:
            logger.warning("[FTD-ANOMALY] scan error: %s", e)
        time.sleep(SCAN_INTERVAL_S)


_thread: Optional[threading.Thread] = None


def start_ftd_anomaly_engine(discord=None) -> None:
    """Start the FTD anomaly daemon. Idempotent."""
    global _thread
    if _thread and _thread.is_alive():
        return
    _thread = threading.Thread(target=_loop, args=(discord,), daemon=True, name="ftd-anomaly")
    _thread.start()
    logger.info("[FTD-ANOMALY] ShortSqueeze Swarm engine started (interval=%ds)", SCAN_INTERVAL_S)
