"""
Semantic Gap Detector™ — Demand Intelligence Engine
====================================================
Crawls public developer forums for "I need an API for X" demand signals.
Cross-references against known SML/SqueezeOS capabilities to surface
high-demand / zero-supply market opportunities.

The system probes Reddit and Hacker News for posts expressing unmet
API/data needs, clusters them by topic, and scores demand intensity.
No synthetic data. All signals from real HTTP responses.

Routes (prefix: /api/graph/gaps):
  GET  /          → Current demand gap leaderboard
  GET  /raw       → Raw demand signal events (last 200)
  POST /scan      → Trigger on-demand scan (async)
  GET  /status    → Scan health + configuration
"""

import re
import time
import threading
import logging
import requests
from collections import defaultdict
from datetime import datetime, timezone
from flask import Blueprint, jsonify, request
from core.state import state

logger = logging.getLogger("GapDetector")
gap_detector_bp = Blueprint("gap_detector", __name__)

# ── Search queries that surface unmet API demand ──────────────────────────────

_DEMAND_QUERIES = [
    # Explicit need expressions
    "I need an API for",
    "looking for API that",
    "is there an API to",
    "need API for market data",
    "need API financial signals",
    "trading signal API alternatives",
    "MCP server financial",
    "agent API trading",
    # SML adjacent searches (what competitors cover / don't cover)
    "squeeze scan API",
    "options flow API free",
    "XRPL API developer",
    "crypto signal API python",
    "real-time market scanner API",
]

# Known SML/SqueezeOS capabilities — used to flag covered vs gap
_SML_CAPABILITIES = {
    "squeeze scan",
    "market scanner",
    "options flow",
    "market intelligence",
    "iwm 0dte",
    "xrpl payment",
    "mcp tools trading",
    "ai council",
    "signal history",
    "futures signal",
    "settlement contract",
    "oracle directive",
    "gamma wall",
    "delta neutral",
    "fractal cascade",
    "neo4j market graph",
}

# ── Storage ───────────────────────────────────────────────────────────────────

_MAX_SIGNALS = 200
_signals: list[dict] = []
_signals_lock = threading.Lock()

_gap_clusters: dict[str, dict] = {}
_clusters_lock = threading.Lock()

_scan_state = {
    "running":        False,
    "last_run_ts":    None,
    "last_run_str":   "NEVER",
    "next_scheduled": None,
    "total_runs":     0,
    "signals_found":  0,
}
_scan_lock = threading.Lock()

# ── HTTP helpers ──────────────────────────────────────────────────────────────

_UA = "ScriptMasterLabs-GapDetector/1.0 (SemanticGapIntelligence; https://scriptmasterlabs.com)"
_SESS = requests.Session()
_SESS.headers.update({"User-Agent": _UA})

_NEED_PATTERN = re.compile(
    r"(need|looking for|want|require|find|searching for).{0,30}(api|endpoint|data feed|service|tool)",
    re.IGNORECASE,
)


def _extract_demand_topic(title: str, text: str) -> str:
    """Pull the core topic from a demand signal post."""
    combined = title + " " + text
    # Strip common filler
    topic = re.sub(r"https?://\S+", "", combined)
    topic = re.sub(r"[^\w\s/-]", " ", topic)
    topic = " ".join(topic.split()[:12])
    return topic.strip()


def _covered_by_sml(title: str, text: str) -> bool:
    combined = (title + " " + text).lower()
    return any(cap in combined for cap in _SML_CAPABILITIES)


def _reddit_demand_search(query: str, limit: int = 10) -> list[dict]:
    url = "https://www.reddit.com/search.json"
    try:
        r = _SESS.get(
            url,
            params={"q": query, "sort": "new", "limit": limit, "type": "link"},
            timeout=10,
        )
        if not r.ok:
            return []
        children = r.json().get("data", {}).get("children", [])
        results = []
        for p in children:
            d = p.get("data", {})
            if not d:
                continue
            title = d.get("title", "")
            text  = d.get("selftext", "") or ""
            combined = title + " " + text
            if not _NEED_PATTERN.search(combined) and "api" not in combined.lower():
                continue
            results.append({
                "source":       "reddit",
                "subreddit":    d.get("subreddit", ""),
                "title":        title,
                "url":          f"https://reddit.com{d.get('permalink', '')}",
                "upvotes":      d.get("score", 0),
                "created_utc":  d.get("created_utc", 0),
                "text":         text[:400],
                "search_query": query,
            })
        return results
    except Exception as e:
        logger.warning(f"[GapDetector] Reddit search error '{query}': {e}")
        return []


def _hn_demand_search(query: str, limit: int = 5) -> list[dict]:
    url = "https://hn.algolia.com/api/v1/search"
    try:
        r = _SESS.get(url, params={"query": query, "hitsPerPage": limit}, timeout=10)
        if not r.ok:
            return []
        hits = r.json().get("hits", [])
        results = []
        for h in hits:
            title = h.get("title") or h.get("story_title") or ""
            text  = h.get("comment_text") or h.get("story_text") or ""
            combined = title + " " + text
            if not _NEED_PATTERN.search(combined) and "api" not in combined.lower():
                continue
            results.append({
                "source":       "hackernews",
                "title":        title,
                "url":          h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID', '')}",
                "upvotes":      h.get("points") or 0,
                "created_utc":  h.get("created_at_i") or 0,
                "text":         text[:400],
                "search_query": query,
            })
        return results
    except Exception as e:
        logger.warning(f"[GapDetector] HN search error '{query}': {e}")
        return []


# ── Core scan ─────────────────────────────────────────────────────────────────

def _run_scan():
    with _scan_lock:
        if _scan_state["running"]:
            return
        _scan_state["running"] = True

    new_signals = []

    try:
        for query in _DEMAND_QUERIES:
            results = _reddit_demand_search(query, limit=8) + _hn_demand_search(query, limit=5)
            for res in results:
                topic   = _extract_demand_topic(res["title"], res["text"])
                covered = _covered_by_sml(res["title"], res["text"])
                res.update({
                    "demand_topic":   topic,
                    "covered_by_sml": covered,
                    "gap_score":      0 if covered else max(1, res.get("upvotes", 1)),
                    "scan_ts":        time.time(),
                })
                new_signals.append(res)
            time.sleep(0.7)

        # Commit
        with _signals_lock:
            _signals[:0] = new_signals
            while len(_signals) > _MAX_SIGNALS:
                _signals.pop()

        # Cluster gaps (group by rough keyword matching)
        with _signals_lock:
            snapshot = list(_signals)

        clusters: dict[str, dict] = defaultdict(lambda: {
            "demand_count": 0,
            "total_upvotes": 0,
            "covered": False,
            "examples": [],
        })
        for s in snapshot:
            if s["covered_by_sml"]:
                continue
            # Rough topic key from first 3 words
            key = " ".join(s["demand_topic"].lower().split()[:3])
            clusters[key]["demand_count"]  += 1
            clusters[key]["total_upvotes"] += s.get("upvotes", 0)
            if len(clusters[key]["examples"]) < 3:
                clusters[key]["examples"].append(s["title"])

        with _clusters_lock:
            _gap_clusters.clear()
            _gap_clusters.update(dict(clusters))

        total = len(new_signals)
        gaps  = sum(1 for s in new_signals if not s["covered_by_sml"])
        now   = time.time()

        with _scan_lock:
            _scan_state["running"]       = False
            _scan_state["last_run_ts"]   = now
            _scan_state["last_run_str"]  = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            _scan_state["total_runs"]   += 1
            _scan_state["signals_found"] = total

        state.push_terminal(
            "GAPDETECTOR",
            f"Semantic gap scan done — {total} signals, {gaps} uncovered gaps",
            extra={"signals": total, "gaps": gaps},
        )
        logger.info(f"[GapDetector] Scan complete: {total} signals, {gaps} gaps")

    except Exception as e:
        logger.error(f"[GapDetector] Scan crashed: {e}")
        with _scan_lock:
            _scan_state["running"] = False


# ── Background scheduler (every 6h) ──────────────────────────────────────────

_SCAN_INTERVAL = 6 * 3600


def _scan_scheduler():
    while True:
        next_ts = time.time() + _SCAN_INTERVAL
        with _scan_lock:
            _scan_state["next_scheduled"] = datetime.fromtimestamp(next_ts, tz=timezone.utc).isoformat()
        time.sleep(_SCAN_INTERVAL)
        _run_scan()


def start_gap_detector():
    """Call from app.py (non-serverless only)."""
    def _boot():
        time.sleep(60)
        _run_scan()
        threading.Thread(target=_scan_scheduler, daemon=True, name="gap-detector-scheduler").start()
    threading.Thread(target=_boot, daemon=True, name="gap-detector-boot").start()


# ── Routes ────────────────────────────────────────────────────────────────────

@gap_detector_bp.route("/", methods=["GET"])
def gap_leaderboard():
    """Ranked demand gaps — topics with high unmet demand."""
    with _clusters_lock:
        clusters_snapshot = dict(_gap_clusters)
    with _scan_lock:
        scan_snapshot = dict(_scan_state)

    ranked = sorted(
        [
            {
                "topic":          topic,
                "demand_count":   data["demand_count"],
                "total_upvotes":  data["total_upvotes"],
                "gap_intensity":  data["demand_count"] * 3 + data["total_upvotes"],
                "covered_by_sml": data["covered"],
                "example_posts":  data["examples"],
            }
            for topic, data in clusters_snapshot.items()
        ],
        key=lambda x: -x["gap_intensity"],
    )[:25]

    return jsonify({
        "status":       "success",
        "node":         "SEMANTIC-GAP-DETECTOR",
        "last_scan":    scan_snapshot["last_run_str"],
        "scan_running": scan_snapshot["running"],
        "total_gaps":   len(ranked),
        "gaps":         ranked,
        "note":         "Gaps = unmet developer demand not covered by existing SML products.",
    })


@gap_detector_bp.route("/raw", methods=["GET"])
def gap_raw():
    """Raw demand signal events."""
    limit       = min(int(request.args.get("limit", 100)), 200)
    gaps_only   = request.args.get("gaps_only", "false").lower() == "true"
    with _signals_lock:
        signals = list(_signals)
    if gaps_only:
        signals = [s for s in signals if not s["covered_by_sml"]]
    return jsonify({
        "status":       "success",
        "returned":     min(limit, len(signals)),
        "total_stored": len(signals),
        "signals":      signals[:limit],
    })


@gap_detector_bp.route("/scan", methods=["POST"])
def trigger_scan():
    """Trigger on-demand semantic gap scan (async)."""
    with _scan_lock:
        if _scan_state["running"]:
            return jsonify({"status": "already_running", "message": "Scan already in progress"}), 409
    threading.Thread(target=_run_scan, daemon=True, name="gap-scan-manual").start()
    return jsonify({
        "status":  "dispatched",
        "message": "Semantic gap scan started. Poll GET /api/graph/gaps for results.",
        "ts":      time.time(),
    })


@gap_detector_bp.route("/status", methods=["GET"])
def gap_status():
    """Scan health and configuration."""
    with _scan_lock:
        scan_snapshot = dict(_scan_state)
    with _signals_lock:
        total_signals = len(_signals)
    return jsonify({
        "status":              "success",
        "node":                "SEMANTIC-GAP-DETECTOR",
        "scan":                scan_snapshot,
        "total_stored_signals": total_signals,
        "demand_queries":      _DEMAND_QUERIES,
        "sml_capabilities":    sorted(_SML_CAPABILITIES),
        "scan_interval_hours": _SCAN_INTERVAL // 3600,
    })
