"""
Agent Economy Intelligence Network™ (AEIN)
==========================================
ComScore for AI agent commerce. Exposes aggregate intelligence on which
AI agents are transacting, what they're buying, and macro traffic patterns.

Public summary is free — it's a discoverability signal that tells the AI
ecosystem what SqueezeOS looks like from the outside. Detailed report is
premium (0.25 RLUSD via x402 — uses existing proof402 payment decorator).

All metrics derive from the live agent_analytics ring buffer. No synthetic
data. Metrics reset on server restart (in-memory, intentional MVP design).

Routes (prefix: /x402/agent-economy):
  GET  /              → Free public summary
  GET  /report        → Premium detailed intelligence report (0.25 RLUSD)
  GET  /leaderboard   → Top AI agent types by request volume (public)
  GET  /heatmap       → 24×7 hourly traffic matrix (public)
"""

import math
import time
from collections import defaultdict
from datetime import datetime, timezone
from flask import Blueprint, jsonify, request

from core.api.agent_analytics import _window_entries, _counters, _counters_lock
from proof402_integration import require_payment

agent_economy_bp = Blueprint("agent_economy", __name__)

# Endpoint UUID for premium report (register in proof402_integration as needed)
_AEIN_ENDPOINT_ID = "c8d9e0f1-a2b3-4c5d-6e7f-890123456789"
_AEIN_PRICE       = 0.25  # RLUSD


def _build_summary(hours: int = 24) -> dict:
    entries = _window_entries(hours)
    agents  = [e for e in entries
               if e["agent_type"] not in ("human",)
               and e["stage"] != "INFRA_HEALTHCHECK"]

    total        = len(agents)
    paid         = sum(1 for e in agents if e["paid"])
    wallets      = {e["wallet"] for e in agents if e["wallet"]}
    type_counts: dict[str, int]  = defaultdict(int)
    stage_counts: dict[str, int] = defaultdict(int)
    path_counts:  dict[str, int] = defaultdict(int)

    for e in agents:
        type_counts[e["agent_type"]]  += 1
        stage_counts[e["stage"]]      += 1
        path_counts[e["path"]]        += 1

    top_types = sorted(type_counts.items(), key=lambda x: -x[1])[:8]
    top_paths = sorted(path_counts.items(), key=lambda x: -x[1])[:10]

    with _counters_lock:
        all_time_total  = _counters["total"]
        all_time_paid   = _counters["paid"]
        all_time_wallets = len(_counters["wallets"])

    return {
        "window_hours":           hours,
        "total_agent_requests":   total,
        "paid_requests":          paid,
        "unique_wallets":         len(wallets),
        "conversion_pct":         round(paid / total * 100, 2) if total else None,
        "unique_agent_types":     len(type_counts),
        "agent_type_distribution": dict(top_types),
        "funnel": {
            "DISCOVERED":      stage_counts.get("DISCOVERED", 0),
            "FREE_TRIAL":      stage_counts.get("FREE_TRIAL", 0),
            "INVOICED":        stage_counts.get("INVOICED", 0),
            "CONVERTED":       stage_counts.get("CONVERTED", 0),
        },
        "top_endpoints":          dict(top_paths),
        "all_time": {
            "total_requests":  all_time_total,
            "paid_requests":   all_time_paid,
            "unique_wallets":  all_time_wallets,
        },
    }


def _build_heatmap() -> list[dict]:
    """24×7 hourly traffic matrix for last week."""
    now     = time.time()
    entries = _window_entries(168)  # 7 days
    agents  = [e for e in entries
               if e["agent_type"] not in ("human",)
               and e["stage"] != "INFRA_HEALTHCHECK"]

    # Build 7 * 24 buckets: day_of_week × hour_of_day
    matrix: dict[tuple[int, int], int] = defaultdict(int)
    for e in agents:
        dt = datetime.fromtimestamp(e["epoch"], tz=timezone.utc)
        matrix[(dt.weekday(), dt.hour)] += 1

    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    rows = []
    for dow in range(7):
        row = {"day": days[dow], "hours": {}}
        for hr in range(24):
            row["hours"][str(hr).zfill(2)] = matrix.get((dow, hr), 0)
        rows.append(row)
    return rows


# ── Routes ────────────────────────────────────────────────────────────────────

@agent_economy_bp.route("/", methods=["GET"])
def economy_summary():
    """Free public summary of AI agent economy activity on this provider."""
    hours = min(int(request.args.get("hours", 24)), 168)
    summary = _build_summary(hours)
    return jsonify({
        "status":    "success",
        "node":      "AEIN",
        "provider":  "ScriptMasterLabs / SqueezeOS",
        "note":      "Free summary. For full intelligence report with hourly heatmap and wallet-level analytics, call GET /x402/agent-economy/report (0.25 RLUSD via x402).",
        **summary,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    })


@agent_economy_bp.route("/report", methods=["GET"])
@require_payment(_AEIN_ENDPOINT_ID)
def economy_report():
    """
    Premium AEIN Report — full AI agent commerce intelligence.
    0.25 RLUSD via x402. Includes heatmap, wallet leaderboard, anomaly flags.
    """
    hours   = min(int(request.args.get("hours", 168)), 720)
    summary = _build_summary(hours)
    heatmap = _build_heatmap()

    # Wallet leaderboard
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

    wallet_ranked = sorted(wallet_stats.items(), key=lambda x: (-x[1]["paid"], -x[1]["requests"]))[:20]

    # Anomaly flags — simple heuristic
    anomalies = []
    conv = summary.get("conversion_pct") or 0
    if conv > 60:
        anomalies.append({"flag": "HIGH_CONVERSION", "value": conv, "note": "Unusually high conversion rate"})
    if conv < 2 and summary["total_agent_requests"] > 100:
        anomalies.append({"flag": "LOW_CONVERSION", "value": conv, "note": "High traffic, low monetization — review pricing or UX"})
    disc = summary["funnel"].get("DISCOVERED", 0)
    free = summary["funnel"].get("FREE_TRIAL", 0)
    if disc > 0 and free / max(disc, 1) < 0.1:
        anomalies.append({"flag": "DISCOVERY_DROPOFF", "value": round(free / disc * 100, 1), "note": "Agents discover but don't try free endpoints — check llms.txt and well-known manifests"})

    return jsonify({
        "status":   "success",
        "node":     "AEIN-PREMIUM",
        "provider": "ScriptMasterLabs / SqueezeOS",
        **summary,
        "heatmap":  heatmap,
        "wallet_leaderboard": [
            {
                "wallet_masked": w[:6] + "..." + w[-4:] if len(w) > 10 else "****",
                **stats,
            }
            for w, stats in wallet_ranked
        ],
        "anomaly_flags": anomalies,
        "generated_at":  datetime.now(timezone.utc).isoformat(),
    })


@agent_economy_bp.route("/leaderboard", methods=["GET"])
def economy_leaderboard():
    """Top AI agent types by request volume — free public view."""
    hours = min(int(request.args.get("hours", 24)), 168)
    entries = _window_entries(hours)
    agents  = [e for e in entries
               if e["agent_type"] not in ("human",)
               and e["stage"] != "INFRA_HEALTHCHECK"]

    type_stats: dict[str, dict] = defaultdict(lambda: {"requests": 0, "paid": 0})
    for e in agents:
        t = e["agent_type"]
        type_stats[t]["requests"] += 1
        if e["paid"]:
            type_stats[t]["paid"] += 1

    ranked = sorted(
        [{"agent_type": t, **v, "conversion_pct": round(v["paid"] / v["requests"] * 100, 1) if v["requests"] else 0}
         for t, v in type_stats.items()],
        key=lambda x: -x["requests"],
    )

    return jsonify({
        "status":       "success",
        "window_hours": hours,
        "leaderboard":  ranked,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    })


@agent_economy_bp.route("/heatmap", methods=["GET"])
def economy_heatmap():
    """24×7 hourly AI agent traffic heatmap for last 7 days — free."""
    heatmap = _build_heatmap()
    return jsonify({
        "status":       "success",
        "window":       "last_7_days",
        "matrix":       heatmap,
        "note":         "Rows=day of week, columns=UTC hour. Values=agent request count.",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    })
