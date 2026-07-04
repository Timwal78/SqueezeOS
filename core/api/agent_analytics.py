"""
Agent Traffic Analytics — Script Master Labs
Tracks every AI agent interaction: discovery → free trial → invoice → payment → premium.
Ring buffer, zero external deps, zero performance cost on hot paths.
"""

import re
import time
import threading
from collections import defaultdict
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify

analytics_bp = Blueprint("agent_analytics", __name__)

# ── Agent classifier ──────────────────────────────────────────────────────────

_UA_PATTERNS = [
    (re.compile(r"claude|anthropic",        re.I), "claude"),
    (re.compile(r"gpt|openai|chatgpt",      re.I), "gpt"),
    (re.compile(r"gemini|google-extended",  re.I), "gemini"),
    (re.compile(r"grok|x\.ai",             re.I), "grok"),
    (re.compile(r"cohere",                  re.I), "cohere"),
    (re.compile(r"mistral",                re.I), "mistral"),
    (re.compile(r"llama|meta-ai",          re.I), "llama"),
    (re.compile(r"mcp[-/ ]",               re.I), "mcp-client"),
    (re.compile(r"python-requests|httpx|aiohttp|requests/", re.I), "python-bot"),
    (re.compile(r"^curl/",                 re.I), "curl"),
    (re.compile(r"node-fetch|axios|got/",  re.I), "node-bot"),
    (re.compile(r"go-http-client",         re.I), "go-bot"),
    (re.compile(r"java|okhttp",            re.I), "java-bot"),
    (re.compile(r"Mozilla/5\.0.*(Chrome|Firefox|Safari|Edge)", re.I), "human"),
]

def _classify_agent(ua: str) -> str:
    if not ua:
        return "headless"
    for pattern, label in _UA_PATTERNS:
        if pattern.search(ua):
            return label
    return "unknown-bot"

# ── Funnel stages ─────────────────────────────────────────────────────────────

_DISCOVERY_PATHS = frozenset({
    "/llms.txt", "/robots.txt", "/openapi.json",
    "/.well-known/mcp.json", "/.well-known/openapi.json",
    "/.well-known/agents.json", "/.well-known/ai-plugin.json",
    "/.well-known/server.json", "/.well-known/x402",
})

_FREE_PREFIXES = (
    "/api/demo", "/api/preview", "/api/history",
    "/api/marketplace", "/api/hiring",
    "/api/relay/nodes", "/api/events",
)

# /api/status is Render's health-check target (render.yaml) and the
# keepalive.yml cron's ping target, not a business signal -- it dwarfs real
# agent traffic and was inflating FREE_TRIAL counts with self-pings. Staged
# separately and excluded from agent/funnel aggregates below, but still
# recorded in raw all-time/top-path counters for transparency.
_INFRA_HEALTHCHECK_PATHS = frozenset({"/api/status"})

_PREMIUM_PREFIXES = (
    "/api/council", "/api/scan", "/api/options",
    "/api/iwm", "/api/futures", "/api/settlement",
)

# /mcp is a single JSON-RPC URL that every tool call -- free or paid -- goes
# through, so path-prefix staging alone can't see past it: every /mcp hit
# fell into OTHER regardless of what was actually called. These mirror the
# real free_tools/paid_tools split in .well-known/mcp.json (kept in sync
# with core/api/mcp_bp.py's _TOOLS list).
_MCP_PROTOCOL_METHODS = frozenset({"initialize", "tools/list", "ping"})

_MCP_FREE_TOOLS = frozenset({
    "demo_council", "signal_preview", "signal_history", "get_invoice", "verify_payment",
    "bureau_public_score", "marketplace_browse", "marketplace_list_signal",
    "hiring_browse_jobs", "hiring_post_job", "system_status", "futures_create",
    "futures_take", "futures_browse", "futures_leaderboard", "settlement_create",
    "settlement_browse", "settlement_trigger", "convergence_check", "autopilot_status",
    "autopilot_trades", "autopilot_start", "autopilot_stop", "circuit_breaker_reset",
    "beastmode_scan", "proprietary_ema_signal", "oracle_feeds", "iam_truth",
    "ccs_info", "ccs_score", "ccs_report", "ccs_leaderboard", "ccs_stats", "post_to_slack",
    "citation_score", "narrative_optimize", "provider_score", "semantic_gaps",
})

_MCP_PAID_TOOLS = frozenset({
    "council_verdict", "market_scan", "options_intelligence", "iwm_odte",
    "marketplace_read_signal", "oracle_query", "iam_resolve", "ccs_validate",
    "sovereign_741", "sovereign_365", "macro_741_scan", "sovereign_triplelock", "sovereign_full",
})

# agent_economy is dual-tier on a single tool name: public summary is free,
# the "report" view costs 0.25 RLUSD (mcp.json's paid_tools entry for it
# carries an extra "view": "report" field marking the paid argument value).
_MCP_DUAL_TIER_TOOLS = {"agent_economy": "report"}

def _funnel_stage(path: str, status: int, has_token: bool,
                  mcp_method: str = "", mcp_tool: str = "", mcp_view: str = "") -> str:
    if path in _INFRA_HEALTHCHECK_PATHS:
        return "INFRA_HEALTHCHECK"
    if path in _DISCOVERY_PATHS:
        return "DISCOVERED"
    if path == "/mcp":
        if mcp_method != "tools/call":
            # initialize / tools/list / ping / notifications/* -- protocol
            # handshake, not a business action.
            return "DISCOVERED"
        if mcp_tool in _MCP_DUAL_TIER_TOOLS:
            if has_token:
                return "CONVERTED"
            if mcp_view == _MCP_DUAL_TIER_TOOLS[mcp_tool]:
                return "PREMIUM_ATTEMPT"
            return "FREE_TRIAL"
        if mcp_tool in _MCP_PAID_TOOLS:
            return "CONVERTED" if has_token else "PREMIUM_ATTEMPT"
        if mcp_tool in _MCP_FREE_TOOLS:
            return "FREE_TRIAL"
        return "OTHER"
    if status == 402:
        return "INVOICED"
    if has_token and any(path.startswith(p) for p in _PREMIUM_PREFIXES):
        return "CONVERTED"
    if any(path.startswith(p) for p in _PREMIUM_PREFIXES):
        return "PREMIUM_ATTEMPT"
    if any(path.startswith(p) for p in _FREE_PREFIXES):
        return "FREE_TRIAL"
    return "OTHER"

# ── Ring buffer storage ───────────────────────────────────────────────────────

_MAX_ENTRIES  = 10_000
_log: list[dict] = []
_log_lock = threading.Lock()

# Counters for fast aggregate queries (no full scan needed)
_counters = {
    "total":      0,
    "by_type":    defaultdict(int),
    "by_stage":   defaultdict(int),
    "by_path":    defaultdict(int),
    "by_status":  defaultdict(int),
    "paid":       0,
    "wallets":    set(),
}
_counters_lock = threading.Lock()

def record_request(path: str, method: str, status: int, ua: str,
                   ip: str, wallet: str, has_token: bool, ms: float,
                   mcp_method: str = "", mcp_tool: str = "", mcp_view: str = "") -> None:
    agent_type = _classify_agent(ua)
    stage      = _funnel_stage(path, status, has_token, mcp_method, mcp_tool, mcp_view)

    entry = {
        "ts":         datetime.now(timezone.utc).isoformat(),
        "epoch":      time.time(),
        "agent_type": agent_type,
        "stage":      stage,
        "path":       path,
        "method":     method,
        "status":     status,
        "ua":         ua[:120],
        "ip":         ip,
        "wallet":     wallet,
        "paid":       has_token,
        "ms":         round(ms, 1),
        "mcp_method": mcp_method,
        "mcp_tool":   mcp_tool,
        "mcp_view":   mcp_view,
    }

    with _log_lock:
        _log.append(entry)
        if len(_log) > _MAX_ENTRIES:
            _log.pop(0)

    with _counters_lock:
        _counters["total"] += 1
        _counters["by_type"][agent_type] += 1
        _counters["by_stage"][stage] += 1
        _counters["by_path"][path] += 1
        _counters["by_status"][str(status)] += 1
        if has_token:
            _counters["paid"] += 1
        if wallet:
            _counters["wallets"].add(wallet)

# ── Middleware hook (called from app.py after_request) ───────────────────────

_request_start_times: dict = {}
_start_lock = threading.Lock()

def before_analytics():
    with _start_lock:
        _request_start_times[id(request._get_current_object())] = time.time()

def after_analytics(response):
    req_id = id(request._get_current_object())
    with _start_lock:
        start = _request_start_times.pop(req_id, time.time())
    ms = (time.time() - start) * 1000

    path       = request.path
    ua         = request.headers.get("User-Agent", "")
    ip         = request.headers.get("X-Forwarded-For", request.remote_addr or "")
    wallet     = request.headers.get("X-Agent-Wallet", "")
    has_token  = bool(request.headers.get("X-Payment-Token"))

    # Skip static assets and internal paths
    if any(path.endswith(ext) for ext in (".js", ".css", ".png", ".ico", ".map")):
        return response
    if path.startswith("/_"):
        return response

    mcp_method = ""
    mcp_tool   = ""
    mcp_view   = ""
    if path == "/mcp":
        body = request.get_json(silent=True) or {}
        mcp_method = body.get("method") or ""
        params = body.get("params") or {}
        arguments = params.get("arguments") or {}
        if mcp_method == "tools/call":
            mcp_tool = params.get("name") or ""
            mcp_view = arguments.get("view") or ""
        # mcp_bp.py's _dispatch() accepts payment_token via JSON-RPC args as
        # well as the X-Payment-Token header -- only checking the header
        # here would misclassify args-based payments as PREMIUM_ATTEMPT.
        if not has_token:
            has_token = bool(arguments.get("payment_token"))
        if not wallet:
            wallet = arguments.get("agent_wallet") or ""

    record_request(path, request.method, response.status_code,
                   ua, ip, wallet, has_token, ms, mcp_method, mcp_tool, mcp_view)
    return response

# ── Analytics endpoints ───────────────────────────────────────────────────────

def _window_entries(hours: int) -> list[dict]:
    cutoff = time.time() - (hours * 3600)
    with _log_lock:
        return [e for e in _log if e["epoch"] >= cutoff]

@analytics_bp.route("/api/analytics/agents")
def agent_dashboard():
    """Full agent traffic analytics — last 24h breakdown."""
    entries_24h = _window_entries(24)
    entries_7d  = _window_entries(168)

    # Type breakdown 24h
    type_24h: dict[str, int] = defaultdict(int)
    stage_24h: dict[str, int] = defaultdict(int)
    path_24h: dict[str, int]  = defaultdict(int)
    paid_24h  = 0
    wallets_24h: set = set()

    for e in entries_24h:
        t = e["agent_type"]
        if t != "human" and e["stage"] != "INFRA_HEALTHCHECK":
            type_24h[t] += 1
            stage_24h[e["stage"]] += 1
            path_24h[e["path"]] += 1
            if e["paid"]:
                paid_24h += 1
            if e["wallet"]:
                wallets_24h.add(e["wallet"])

    # Funnel conversion rates 24h (agent requests only)
    total_agents_24h = sum(type_24h.values())
    funnel = {
        "DISCOVERED":      stage_24h.get("DISCOVERED", 0),
        "FREE_TRIAL":      stage_24h.get("FREE_TRIAL", 0),
        "INVOICED":        stage_24h.get("INVOICED", 0),
        "PREMIUM_ATTEMPT": stage_24h.get("PREMIUM_ATTEMPT", 0),
        "CONVERTED":       stage_24h.get("CONVERTED", 0),
    }

    disc = funnel["DISCOVERED"]
    free = funnel["FREE_TRIAL"]

    with _counters_lock:
        total_all_time = _counters["total"]
        paid_all_time  = _counters["paid"]
        unique_wallets = len(_counters["wallets"])
        top_types_all  = sorted(_counters["by_type"].items(), key=lambda x: -x[1])[:10]
        top_paths_all  = sorted(_counters["by_path"].items(),  key=lambda x: -x[1])[:10]

    return jsonify({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "all_time": {
            "total_requests":   total_all_time,
            "paid_requests":    paid_all_time,
            "unique_wallets":   unique_wallets,
            "top_agent_types":  dict(top_types_all),
            "top_paths":        dict(top_paths_all),
        },
        "last_24h": {
            "total_agent_requests": total_agents_24h,
            "paid_requests":        paid_24h,
            "unique_wallets":       len(wallets_24h),
            "by_agent_type":        dict(sorted(type_24h.items(), key=lambda x: -x[1])),
            "top_paths":            dict(sorted(path_24h.items(), key=lambda x: -x[1])[:10]),
        },
        "last_7d": {
            "total_agent_requests": sum(1 for e in entries_7d if e["agent_type"] != "human" and e["stage"] != "INFRA_HEALTHCHECK"),
            "paid_requests":        sum(1 for e in entries_7d if e["paid"]),
            "unique_wallets":       len({e["wallet"] for e in entries_7d if e["wallet"]}),
        },
        "funnel_24h": {
            **funnel,
            # None (not 0 or an inflated %) when the denominator is actually
            # zero -- a fabricated ratio like "30100%" is worse than admitting
            # the rate is undefined with no discovery/free/invoice events yet.
            "discovery_to_free_pct":     round(funnel["FREE_TRIAL"] / disc * 100, 1) if disc else None,
            "free_to_invoice_pct":        round(funnel["INVOICED"] / free * 100, 1) if free else None,
            "invoice_to_convert_pct":     round(funnel["CONVERTED"] / funnel["INVOICED"] * 100, 1) if funnel["INVOICED"] else None,
            "overall_conversion_pct":     round(funnel["CONVERTED"] / total_agents_24h * 100, 2) if total_agents_24h else None,
        },
        "shortlist_analysis": {
            "description": "Agents that hit free/preview endpoints but never paid",
            "dropped_at_free": max(0, funnel["FREE_TRIAL"] - funnel["INVOICED"] - funnel["CONVERTED"]),
            "dropped_at_invoice": max(0, funnel["INVOICED"] - funnel["CONVERTED"]),
            "note": "High drop at FREE_TRIAL = improve upgrade prompts. High drop at INVOICED = friction in payment flow.",
        },
    })


@analytics_bp.route("/api/analytics/agents/live")
def agent_live():
    """Last 50 agent requests — real-time feed."""
    with _log_lock:
        recent = [e for e in reversed(_log[-200:])
                  if e["agent_type"] != "human" and e["stage"] != "INFRA_HEALTHCHECK"][:50]
    return jsonify({
        "requests": recent,
        "count":    len(recent),
        "ts":       time.time(),
    })


@analytics_bp.route("/api/analytics/agents/funnel")
def agent_funnel():
    """Conversion funnel for the last N hours (default 24)."""
    hours = min(int(request.args.get("hours", 24)), 720)
    entries = _window_entries(hours)

    funnel: dict[str, int] = defaultdict(int)
    by_type: dict[str, int] = defaultdict(int)
    for e in entries:
        if e["agent_type"] == "human" or e["stage"] == "INFRA_HEALTHCHECK":
            continue
        funnel[e["stage"]] += 1
        by_type[e["agent_type"]] += 1

    ordered = ["DISCOVERED", "FREE_TRIAL", "INVOICED", "PREMIUM_ATTEMPT", "CONVERTED"]
    return jsonify({
        "window_hours": hours,
        "funnel":  {k: funnel.get(k, 0) for k in ordered},
        "by_type": dict(sorted(by_type.items(), key=lambda x: -x[1])),
        "ts":      time.time(),
    })


@analytics_bp.route("/api/analytics/agents/leaderboard")
def agent_leaderboard():
    """Top agents by activity and conversion."""
    hours = min(int(request.args.get("hours", 168)), 720)
    entries = _window_entries(hours)

    wallet_stats: dict[str, dict] = defaultdict(lambda: {
        "requests": 0, "paid": 0, "agent_type": "unknown", "last_seen": ""
    })
    for e in entries:
        if not e["wallet"]:
            continue
        w = e["wallet"]
        wallet_stats[w]["requests"] += 1
        if e["paid"]:
            wallet_stats[w]["paid"] += 1
        wallet_stats[w]["agent_type"] = e["agent_type"]
        wallet_stats[w]["last_seen"]  = e["ts"]

    ranked = sorted(wallet_stats.items(), key=lambda x: (-x[1]["paid"], -x[1]["requests"]))[:20]
    return jsonify({
        "window_hours": hours,
        "leaderboard": [
            {"wallet": w[:8] + "..." + w[-4:], **stats}
            for w, stats in ranked
        ],
        "ts": time.time(),
    })
