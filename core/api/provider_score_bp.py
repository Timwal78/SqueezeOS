"""
ARGUS Provider Score™ — API Provider Quality Intelligence
=========================================================
Exposes SqueezeOS / ScriptMasterLabs standing as an API provider to AI agents.
Computes an AgentPageRank™ score (0–850) from live traffic data captured by
the existing agent_analytics middleware. No synthetic data — every metric
derives from real inbound requests since the last server start.

Routes (prefix: /x402/provider-score):
  GET  /            → Overall provider score card
  GET  /breakdown   → Detailed metric breakdown per agent type
  GET  /trend       → Hourly request trend for last 24h
  GET  /leaderboard → Top contributing agent wallets (truncated for privacy)

Score methodology:
  - Volume component (0–300): log10(total_agent_requests + 1) * 60
  - Diversity component (0–200): unique agent type count * 30
  - Conversion component (0–200): paid / total * 200
  - Repeat rate (0–150): multi-visit wallets / total wallets * 150
"""

import time
import math
import threading
from collections import defaultdict
from datetime import datetime, timezone
from flask import Blueprint, jsonify, request

from core.api.agent_analytics import (
    _log, _log_lock,
    _counters, _counters_lock,
    _window_entries,
)

provider_score_bp = Blueprint("provider_score", __name__)

_SCORE_VERSION = "1.0"


def _compute_score(entries_24h: list[dict], all_counters: dict) -> dict:
    """Derive AgentPageRank™ from real traffic data."""
    # Filter out infrastructure healthchecks and human browsers
    agents = [e for e in entries_24h
              if e["agent_type"] not in ("human",)
              and e["stage"] != "INFRA_HEALTHCHECK"]

    total      = len(agents)
    paid       = sum(1 for e in agents if e["paid"])
    wallets    = {e["wallet"] for e in agents if e["wallet"]}
    types      = {e["agent_type"] for e in agents}

    # Repeat wallets: wallets that appear more than once
    wallet_counts: dict[str, int] = defaultdict(int)
    for e in agents:
        if e["wallet"]:
            wallet_counts[e["wallet"]] += 1
    repeat_wallets = sum(1 for c in wallet_counts.values() if c > 1)

    # Volume component: 0–300
    vol_score = min(300, math.log10(max(total, 1) + 1) * 80)

    # Diversity component: 0–200 (up to ~7 types for full score)
    div_score = min(200, len(types) * 30)

    # Conversion: paid / total * 200
    conv_score = (paid / total * 200) if total > 0 else 0

    # Repeat rate: multi-visit wallets / total wallets * 150
    repeat_score = (repeat_wallets / len(wallets) * 150) if wallets else 0

    total_score = round(vol_score + div_score + conv_score + repeat_score)

    # All-time stats from counters
    with _counters_lock:
        all_time_total   = _counters["total"]
        all_time_paid    = _counters["paid"]
        unique_wallets   = len(_counters["wallets"])
        top_types_all    = dict(sorted(_counters["by_type"].items(), key=lambda x: -x[1])[:10])

    return {
        "score":             total_score,
        "score_max":         850,
        "score_version":     _SCORE_VERSION,
        "grade":             _grade(total_score),
        "components": {
            "volume":     round(vol_score),
            "diversity":  round(div_score),
            "conversion": round(conv_score),
            "repeat_rate": round(repeat_score),
        },
        "24h_metrics": {
            "total_agent_requests": total,
            "paid_requests":        paid,
            "unique_wallets":       len(wallets),
            "unique_agent_types":   len(types),
            "repeat_wallets":       repeat_wallets,
            "conversion_pct":       round(paid / total * 100, 2) if total else None,
        },
        "all_time_metrics": {
            "total_requests":  all_time_total,
            "paid_requests":   all_time_paid,
            "unique_wallets":  unique_wallets,
            "top_agent_types": top_types_all,
        },
    }


def _grade(score: int) -> str:
    if score >= 750: return "S — SOVEREIGN"
    if score >= 600: return "A — INSTITUTIONAL"
    if score >= 450: return "B — ESTABLISHED"
    if score >= 300: return "C — EMERGING"
    if score >= 150: return "D — EARLY"
    return "F — UNRANKED"


# ── Routes ────────────────────────────────────────────────────────────────────

@provider_score_bp.route("/", methods=["GET"])
def provider_score():
    """AgentPageRank™ score card for this provider."""
    entries_24h = _window_entries(24)
    with _counters_lock:
        counters_snapshot = {
            "total":   _counters["total"],
            "paid":    _counters["paid"],
            "wallets": set(_counters["wallets"]),
            "by_type": dict(_counters["by_type"]),
        }
    data = _compute_score(entries_24h, counters_snapshot)
    data.update({
        "provider":       "ScriptMasterLabs / SqueezeOS",
        "provider_url":   "https://squeezeos-api.onrender.com",
        "generated_at":   datetime.now(timezone.utc).isoformat(),
        "methodology":    "Live traffic only. No synthetic data. Resets on server restart.",
    })
    return jsonify({"status": "success", **data})


@provider_score_bp.route("/breakdown", methods=["GET"])
def provider_breakdown():
    """Per-agent-type traffic breakdown for the last N hours."""
    hours = min(int(request.args.get("hours", 24)), 720)
    entries = _window_entries(hours)
    agents = [e for e in entries
              if e["agent_type"] not in ("human",)
              and e["stage"] != "INFRA_HEALTHCHECK"]

    by_type: dict[str, dict] = defaultdict(lambda: {"requests": 0, "paid": 0, "wallets": set()})
    for e in agents:
        t = e["agent_type"]
        by_type[t]["requests"] += 1
        if e["paid"]:
            by_type[t]["paid"] += 1
        if e["wallet"]:
            by_type[t]["wallets"].add(e["wallet"])

    breakdown = sorted(
        [
            {
                "agent_type":    t,
                "requests":      v["requests"],
                "paid":          v["paid"],
                "unique_wallets": len(v["wallets"]),
                "conversion_pct": round(v["paid"] / v["requests"] * 100, 1) if v["requests"] else 0,
            }
            for t, v in by_type.items()
        ],
        key=lambda x: -x["requests"],
    )

    return jsonify({
        "status":       "success",
        "window_hours": hours,
        "breakdown":    breakdown,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    })


@provider_score_bp.route("/trend", methods=["GET"])
def provider_trend():
    """Hourly request trend for last 24h (agent traffic only)."""
    entries_24h = _window_entries(24)
    now = time.time()

    # Build 24 hourly buckets
    buckets: list[dict] = []
    for h in range(23, -1, -1):
        bucket_start = now - (h + 1) * 3600
        bucket_end   = now - h * 3600
        hour_entries = [
            e for e in entries_24h
            if bucket_start <= e["epoch"] < bucket_end
            and e["agent_type"] not in ("human",)
            and e["stage"] != "INFRA_HEALTHCHECK"
        ]
        label = datetime.fromtimestamp(bucket_end, tz=timezone.utc).strftime("%H:00")
        buckets.append({
            "hour":    label,
            "requests": len(hour_entries),
            "paid":     sum(1 for e in hour_entries if e["paid"]),
        })

    return jsonify({
        "status":       "success",
        "window":       "last_24h",
        "buckets":      buckets,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    })


@provider_score_bp.route("/leaderboard", methods=["GET"])
def provider_leaderboard():
    """Top AI agent wallets by paid request volume (wallets truncated for privacy)."""
    hours = min(int(request.args.get("hours", 168)), 720)
    entries = _window_entries(hours)

    wallet_stats: dict[str, dict] = defaultdict(lambda: {
        "requests": 0, "paid": 0, "agent_type": "unknown", "last_seen": ""
    })
    for e in entries:
        if not e["wallet"] or e["agent_type"] == "human":
            continue
        w = e["wallet"]
        wallet_stats[w]["requests"] += 1
        if e["paid"]:
            wallet_stats[w]["paid"] += 1
        wallet_stats[w]["agent_type"] = e["agent_type"]
        wallet_stats[w]["last_seen"]  = e["ts"]

    ranked = sorted(wallet_stats.items(), key=lambda x: (-x[1]["paid"], -x[1]["requests"]))[:20]
    return jsonify({
        "status":       "success",
        "window_hours": hours,
        "leaderboard": [
            {
                "wallet_masked": w[:6] + "..." + w[-4:] if len(w) > 10 else "****",
                **stats,
            }
            for w, stats in ranked
        ],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    })
