"""
AgentRank™ — Citation Intelligence Engine
==========================================
Tracks when AI assistants, forums, and developer communities cite
ScriptMasterLabs APIs. Probes public sources for mentions of SML services
and computes a citation authority score time-series.

Routes (prefix: /api/citation-score):
  GET  /           → Current scores + recent mentions
  GET  /history    → Full citation event log (last 500)
  POST /probe      → Trigger on-demand probe (async, returns immediately)
  GET  /status     → Probe health, last run, mention counts

Data sources: Reddit public JSON API (no auth), HN Algolia API (no auth).
No synthetic data. All mentions sourced from real HTTP responses.
If a source is unreachable, it is omitted from that probe cycle.
"""

import time
import threading
import logging
import requests
from datetime import datetime, timezone
from flask import Blueprint, jsonify, request
from core.state import state

logger = logging.getLogger("AgentRank")
citation_scout_bp = Blueprint("citation_scout", __name__)

# ── Services we track ────────────────────────────────────────────────────────

_TARGETS = [
    {
        "id": "squeezeos",
        "label": "SqueezeOS",
        "terms": ["squeezeos", "squeeze-os", "squeezeos-api.onrender"],
    },
    {
        "id": "scriptmasterlabs",
        "label": "ScriptMasterLabs",
        "terms": ["scriptmasterlabs", "scriptmaster labs", "script master labs"],
    },
    {
        "id": "ghost-layer",
        "label": "Ghost Layer",
        "terms": ["ghost-layer xrpl", "ghost layer sovereign", "ghost-layer.onrender"],
    },
    {
        "id": "402proof",
        "label": "402Proof",
        "terms": ["402proof", "four02proof", "402 proof xrpl"],
    },
]

# Context queries: do SML products appear in answers to these demand signals?
_CONTEXT_QUERIES = [
    "best API for market intelligence trading",
    "best MCP server financial data",
    "XRPL payment API agents",
    "AI agent market scanner API",
    "squeeze scan API",
]

# ── In-memory storage ─────────────────────────────────────────────────────────

_MAX_EVENTS = 500
_events: list[dict] = []
_events_lock = threading.Lock()

_scores: dict[str, dict] = {
    t["id"]: {
        "mentions_7d": 0,
        "mentions_30d": 0,
        "source_diversity": 0,
        "score": 0,
        "last_seen": None,
    }
    for t in _TARGETS
}
_scores_lock = threading.Lock()

_probe_state = {
    "running": False,
    "last_run_ts": None,
    "last_run_str": "NEVER",
    "next_scheduled": None,
    "total_runs": 0,
    "total_mentions": 0,
}
_probe_lock = threading.Lock()

# ── HTTP helpers ─────────────────────────────────────────────────────────────

_UA = "ScriptMasterLabs-CitationScout/1.0 (AgentRank; https://scriptmasterlabs.com)"
_SESS = requests.Session()
_SESS.headers.update({"User-Agent": _UA})


def _reddit_search(query: str, limit: int = 8) -> list[dict]:
    url = "https://www.reddit.com/search.json"
    try:
        r = _SESS.get(url, params={"q": query, "sort": "new", "limit": limit, "type": "link"}, timeout=10)
        if not r.ok:
            return []
        children = r.json().get("data", {}).get("children", [])
        results = []
        for p in children:
            d = p.get("data", {})
            if not d:
                continue
            results.append({
                "source": "reddit",
                "subreddit": d.get("subreddit", ""),
                "title": d.get("title", ""),
                "url": f"https://reddit.com{d.get('permalink', '')}",
                "score": d.get("score", 0),
                "created_utc": d.get("created_utc", 0),
                "text": (d.get("selftext") or "")[:400],
            })
        return results
    except Exception as e:
        logger.warning(f"[AgentRank] Reddit search error for '{query}': {e}")
        return []


def _hn_search(query: str, limit: int = 5) -> list[dict]:
    url = "https://hn.algolia.com/api/v1/search"
    try:
        r = _SESS.get(url, params={"query": query, "hitsPerPage": limit}, timeout=10)
        if not r.ok:
            return []
        hits = r.json().get("hits", [])
        results = []
        for h in hits:
            results.append({
                "source": "hackernews",
                "title": h.get("title") or h.get("story_title") or "",
                "url": h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID', '')}",
                "score": h.get("points") or 0,
                "created_utc": h.get("created_at_i") or 0,
                "text": ((h.get("comment_text") or h.get("story_text") or ""))[:400],
                "author": h.get("author", ""),
            })
        return results
    except Exception as e:
        logger.warning(f"[AgentRank] HN search error for '{query}': {e}")
        return []


# ── Core probe ────────────────────────────────────────────────────────────────

def _run_probe():
    with _probe_lock:
        if _probe_state["running"]:
            return
        _probe_state["running"] = True

    new_events = []
    mention_counts: dict[str, int] = {t["id"]: 0 for t in _TARGETS}

    try:
        # Brand mention searches
        for target in _TARGETS:
            for term in target["terms"]:
                results = _reddit_search(term, limit=5) + _hn_search(term, limit=3)
                for res in results:
                    res.update({
                        "target_id":    target["id"],
                        "target_label": target["label"],
                        "match_term":   term,
                        "context":      "brand_mention",
                        "probe_ts":     time.time(),
                    })
                    new_events.append(res)
                    mention_counts[target["id"]] += 1
                time.sleep(0.6)

        # Context query searches — check if SML terms appear in results
        for query in _CONTEXT_QUERIES:
            results = _reddit_search(query, limit=5) + _hn_search(query, limit=3)
            for res in results:
                combined = (res.get("title", "") + " " + res.get("text", "") + " " + res.get("url", "")).lower()
                for target in _TARGETS:
                    for term in target["terms"]:
                        if term.lower() in combined:
                            ev = dict(res)
                            ev.update({
                                "target_id":     target["id"],
                                "target_label":  target["label"],
                                "match_term":    term,
                                "context":       "context_query",
                                "context_query": query,
                                "probe_ts":      time.time(),
                            })
                            new_events.append(ev)
                            mention_counts[target["id"]] += 1
            time.sleep(0.6)

        # Commit events
        with _events_lock:
            _events[:0] = new_events
            while len(_events) > _MAX_EVENTS:
                _events.pop()

        # Recompute scores
        now = time.time()
        cutoff_7d  = now - 7  * 86400
        cutoff_30d = now - 30 * 86400

        with _events_lock:
            snapshot = list(_events)

        with _scores_lock:
            for t in _TARGETS:
                tid = t["id"]
                ev7  = [e for e in snapshot if e.get("target_id") == tid and e.get("probe_ts", 0) >= cutoff_7d]
                ev30 = [e for e in snapshot if e.get("target_id") == tid and e.get("probe_ts", 0) >= cutoff_30d]
                src_div = len({e["source"] for e in ev7})
                m7  = len(ev7)
                m30 = len(ev30)
                score = min(100, m7 * 8 + (m30 - m7) * 2 + src_div * 5)
                last_ts = max((e.get("probe_ts", 0) for e in ev30), default=None)
                _scores[tid] = {
                    "mentions_7d":      m7,
                    "mentions_30d":     m30,
                    "source_diversity": src_div,
                    "score":            score,
                    "last_seen": (
                        datetime.fromtimestamp(last_ts, tz=timezone.utc).isoformat()
                        if last_ts else None
                    ),
                }

        total = sum(mention_counts.values())
        with _probe_lock:
            _probe_state["running"]         = False
            _probe_state["last_run_ts"]     = now
            _probe_state["last_run_str"]    = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            _probe_state["total_runs"]     += 1
            _probe_state["total_mentions"] += total

        state.push_terminal("AGENTRANK", f"Citation probe done — {total} mention(s)", extra={"counts": mention_counts})
        logger.info(f"[AgentRank] Probe complete: {total} mentions across {len(new_events)} events")

    except Exception as e:
        logger.error(f"[AgentRank] Probe crashed: {e}")
        with _probe_lock:
            _probe_state["running"] = False


# ── Background scheduler (weekly) ────────────────────────────────────────────

_PROBE_INTERVAL = 7 * 86400


def _probe_scheduler():
    while True:
        next_ts = time.time() + _PROBE_INTERVAL
        with _probe_lock:
            _probe_state["next_scheduled"] = datetime.fromtimestamp(next_ts, tz=timezone.utc).isoformat()
        time.sleep(_PROBE_INTERVAL)
        _run_probe()


def start_citation_scout():
    """Call from app.py (non-serverless only)."""
    def _boot():
        time.sleep(45)  # Let server finish starting
        _run_probe()
        threading.Thread(target=_probe_scheduler, daemon=True, name="citation-scheduler").start()
    threading.Thread(target=_boot, daemon=True, name="citation-boot").start()


# ── Routes ────────────────────────────────────────────────────────────────────

@citation_scout_bp.route("/", methods=["GET"])
def citation_scores():
    """AgentRank™ citation scores for all SML services."""
    with _scores_lock:
        scores_snapshot = dict(_scores)
    with _probe_lock:
        probe_snapshot = dict(_probe_state)
    with _events_lock:
        recent = list(_events[:15])

    ranked = sorted(
        [
            {
                "id":    tid,
                "label": next(t["label"] for t in _TARGETS if t["id"] == tid),
                **v,
            }
            for tid, v in scores_snapshot.items()
        ],
        key=lambda x: -x["score"],
    )

    return jsonify({
        "status":              "success",
        "node":                "AGENTRANK",
        "last_probe":          probe_snapshot["last_run_str"],
        "probe_running":       probe_snapshot["running"],
        "total_probe_runs":    probe_snapshot["total_runs"],
        "total_mentions_ever": probe_snapshot["total_mentions"],
        "scores":              ranked,
        "recent_mentions":     recent,
        "scoring_note":        "0–100. Sources: Reddit public API + HN Algolia. No synthetic data.",
    })


@citation_scout_bp.route("/history", methods=["GET"])
def citation_history():
    """Full citation event log."""
    limit  = min(int(request.args.get("limit", 100)), 500)
    target = request.args.get("target")
    source = request.args.get("source")
    with _events_lock:
        events = list(_events)
    if target:
        events = [e for e in events if e.get("target_id") == target]
    if source:
        events = [e for e in events if e.get("source") == source]
    return jsonify({
        "status":       "success",
        "returned":     min(limit, len(events)),
        "total_stored": len(events),
        "events":       events[:limit],
    })


@citation_scout_bp.route("/probe", methods=["POST"])
def trigger_probe():
    """Trigger an on-demand citation probe (async)."""
    with _probe_lock:
        if _probe_state["running"]:
            return jsonify({"status": "already_running", "message": "Probe already in progress"}), 409
    threading.Thread(target=_run_probe, daemon=True, name="citation-probe-manual").start()
    return jsonify({
        "status":  "dispatched",
        "message": "Citation probe started. Poll GET /api/citation-score for results.",
        "ts":      time.time(),
    })


@citation_scout_bp.route("/status", methods=["GET"])
def citation_status():
    """AgentRank probe health and config."""
    with _probe_lock:
        probe_snapshot = dict(_probe_state)
    with _events_lock:
        total_events = len(_events)
    return jsonify({
        "status":               "success",
        "node":                 "AGENTRANK",
        "probe":                probe_snapshot,
        "total_stored_events":  total_events,
        "targets":              [{"id": t["id"], "label": t["label"], "terms": t["terms"]} for t in _TARGETS],
        "context_queries":      _CONTEXT_QUERIES,
        "probe_interval_hours": _PROBE_INTERVAL // 3600,
    })
