"""
ScriptMaster Labs — Beastmode Intelligence Node
═══════════════════════════════════════════════════════════════════════════
Orchestrates Beastmode SEO & Signal Reconnaissance operations.

Protocols:
  01 - Authority Signaling   : Backlink recon from niche neuro-communities
  02 - Visual Saturation     : Infographic automation pipeline
  03 - Sentiment Exploitation: SaaS Fatigue monitoring

API Routes (prefix: /api/scriptmaster):
  GET  /status               → Current mission state + graphify node count
  POST /run_protocol         → Dispatch a specific protocol (01,02,03)
  GET  /mission_log          → Last N operations
  POST /ingest_intel         → Ingest scraped social intel for AI processing

Author: ScriptMasterLabs™ / SqueezeOS Pro
"""

import os
import time
import json
import logging
import threading
import requests
from datetime import datetime
from flask import Blueprint, jsonify, request
from core.state import state

logger = logging.getLogger("ScriptMaster-Beastmode")
scriptmaster_bp = Blueprint("scriptmaster", __name__)

# ── System Prompt (loaded from pack) ────────────────────────────────────────
_PROMPT_PATH = os.path.join(os.path.dirname(__file__), "scriptmaster", "system_prompt.txt")
_SYSTEM_PROMPT = ""
if os.path.exists(_PROMPT_PATH):
    with open(_PROMPT_PATH, "r", encoding="utf-8") as f:
        _SYSTEM_PROMPT = f.read().strip()

# ── Mission Log (in-memory ring buffer) ─────────────────────────────────────
_MISSION_LOG = []
_LOG_LOCK = threading.Lock()
_MAX_LOG = 50

def _log_mission(protocol: str, action: str, result: str, tokens_used: int = 0):
    entry = {
        "ts": time.time(),
        "ts_str": datetime.now().strftime("%H:%M:%S"),
        "protocol": protocol,
        "action": action,
        "result": result,
        "tokens": tokens_used,
    }
    with _LOG_LOCK:
        _MISSION_LOG.insert(0, entry)
        if len(_MISSION_LOG) > _MAX_LOG:
            _MISSION_LOG.pop()
    # Push to SqueezeOS terminal feed
    state.push_terminal("BEAST", f"[SML-{protocol}] {action}: {result}", extra=entry)

# ── PROTOCOL ENGINES ────────────────────────────────────────────────────────

def _run_protocol_01_authority_signaling(target_subreddits=None):
    """
    Protocol 01: Authority Signaling
    Monitors neurodivergent communities for pain-point discussions that
    ScriptMasterLabs products directly solve.
    """
    subreddits = target_subreddits or ["ADHD", "neurodivergent", "productivity", "LifeProTips"]
    results = []
    headers = {"User-Agent": "ScriptMasterLabs-ReconBot/1.0"}

    for sub in subreddits[:3]:  # Rate-limit to 3 per run
        try:
            url = f"https://www.reddit.com/r/{sub}/search.json?q=executive+dysfunction+OR+SaaS+fatigue+OR+planner&sort=new&limit=5"
            r = requests.get(url, headers=headers, timeout=8)
            if r.ok:
                posts = r.json().get("data", {}).get("children", [])
                for p in posts[:2]:
                    post = p.get("data", {})
                    results.append({
                        "subreddit": sub,
                        "title": post.get("title", ""),
                        "score": post.get("score", 0),
                        "url": f"https://reddit.com{post.get('permalink', '')}",
                        "pain_point": True  # Flag for AI triage
                    })
        except Exception as e:
            logger.warning(f"[P01] Recon failed for r/{sub}: {e}")

    _log_mission("P01", "Authority Signaling", f"Found {len(results)} targets", tokens_used=0)
    return results


def _run_protocol_02_visual_saturation(ai_client=None):
    """
    Protocol 02: Visual Saturation
    Generates content briefs for Full Shield infographic creation.
    """
    topics = [
        "NeuroSpark SOP: Executive Dysfunction Override Protocol",
        "MasterSheets: The Zero-Subscription Productivity Stack",
        "Blood Oath Chronicles: Tactical Fiction for AuDHD Minds",
    ]
    briefs = []
    for topic in topics:
        briefs.append({
            "topic": topic,
            "format": "Pinterest-optimized vertical infographic",
            "style": "Full Shield — jet-black, neon accent, high-contrast",
            "cta": "scriptmasterlabs.com",
            "status": "QUEUED"
        })

    _log_mission("P02", "Visual Saturation", f"{len(briefs)} infographic briefs generated")
    return briefs


def _run_protocol_04_api_narrative_optimizer():
    """
    Protocol 04: API Narrative Optimizer
    Analyzes existing MCP tool descriptions and API endpoint copy for
    AI-discoverability gaps. Rewrites descriptions using AutoGEO-style
    preference signals: clarity, specificity, action-first language.
    Reads the live openapi.json and .well-known/mcp.json manifests.
    No AI model required — pure heuristic pass identifies weak copy.
    """
    import os as _os
    results = []
    weak_patterns = [
        ("Returns", "Action-first: use 'Get' or 'Fetch' instead of 'Returns'"),
        ("This endpoint", "Remove meta-reference — describe what it does directly"),
        ("function that", "Remove implementation language — describe the value, not the code"),
        ("data about", "Too vague — specify what data (e.g. 'real-time bid/ask quotes for')"),
        ("various", "Too vague — enumerate what it includes"),
        ("information", "Weak noun — replace with specific data type"),
    ]

    # Scan llms.txt for description quality
    llms_path = _os.path.join(_os.path.dirname(__file__), "..", "..", "llms.txt")
    llms_path = _os.path.abspath(llms_path)
    if _os.path.exists(llms_path):
        with open(llms_path, "r", encoding="utf-8") as f:
            llms_content = f.read()
        for pattern, advice in weak_patterns:
            count = llms_content.lower().count(pattern.lower())
            if count > 0:
                results.append({
                    "file":    "llms.txt",
                    "pattern": pattern,
                    "count":   count,
                    "advice":  advice,
                    "priority": "HIGH" if count > 2 else "MEDIUM",
                })

    # Scan .well-known/mcp.json tool descriptions
    mcp_path = _os.path.join(_os.path.dirname(__file__), "..", "..", ".well-known", "mcp.json")
    mcp_path = _os.path.abspath(mcp_path)
    if _os.path.exists(mcp_path):
        try:
            with open(mcp_path, "r", encoding="utf-8") as f:
                mcp_data = json.load(f)
            tools = mcp_data.get("tools", [])
            for tool in tools:
                desc = tool.get("description", "")
                name = tool.get("name", "?")
                for pattern, advice in weak_patterns:
                    if pattern.lower() in desc.lower():
                        results.append({
                            "file":    "mcp.json",
                            "tool":    name,
                            "pattern": pattern,
                            "advice":  advice,
                            "current_desc": desc[:120],
                            "priority": "HIGH",
                        })
        except Exception as e:
            results.append({"file": "mcp.json", "error": str(e)})

    issues = len(results)
    _log_mission("P04", "API Narrative Optimizer", f"Found {issues} copy quality issue(s)", tokens_used=0)
    return results


def _run_protocol_03_sentiment_exploitation(query="SaaS fatigue subscription cancellation"):
    """
    Protocol 03: Sentiment Exploitation
    Identifies SaaS fatigue discussions and prepares positioning responses.
    """
    results = []
    headers = {"User-Agent": "ScriptMasterLabs-SentinelBot/1.0"}
    subs = ["Productivity", "nosurf", "digitalnomad", "Entrepreneur"]

    for sub in subs[:2]:
        try:
            url = f"https://www.reddit.com/r/{sub}/search.json?q={query}&sort=new&limit=5"
            r = requests.get(url, headers=headers, timeout=8)
            if r.ok:
                posts = r.json().get("data", {}).get("children", [])
                for p in posts[:3]:
                    post = p.get("data", {})
                    results.append({
                        "subreddit": sub,
                        "title": post.get("title", ""),
                        "score": post.get("score", 0),
                        "url": f"https://reddit.com{post.get('permalink', '')}",
                        "sentiment": "SAAS_FATIGUE"
                    })
        except Exception as e:
            logger.warning(f"[P03] Sentiment recon failed for r/{sub}: {e}")

    _log_mission("P03", "Sentiment Exploitation", f"Found {len(results)} SaaS-fatigue threads")
    return results


# ── API ROUTES ───────────────────────────────────────────────────────────────

@scriptmaster_bp.route("/status", methods=["GET"])
def get_status():
    """Returns current Beastmode node health and mission log summary."""
    with _LOG_LOCK:
        log_snapshot = list(_MISSION_LOG[:10])

    protocols_active = {
        "P01_authority_signaling": True,
        "P02_visual_saturation": True,
        "P03_sentiment_exploitation": True,
        "P04_api_narrative_optimizer": True,
    }
    last_run = log_snapshot[0]["ts_str"] if log_snapshot else "NEVER"

    return jsonify({
        "status": "success",
        "node": "SCRIPTMASTER-BEASTMODE",
        "system_prompt_loaded": bool(_SYSTEM_PROMPT),
        "protocols_active": protocols_active,
        "last_run": last_run,
        "total_missions": len(_MISSION_LOG),
        "log": log_snapshot,
        "targets": [
            "NeuroSpark: SOP Manual",
            "MasterSheets: Zero Subscription Tracker",
            "Blood Oath Chronicles (Fiction Series)",
        ]
    })


@scriptmaster_bp.route("/run_protocol", methods=["POST"])
def run_protocol():
    """
    Dispatch a specific Beastmode protocol.
    Body: { "protocol": "P01" | "P02" | "P03", "params": {} }
    """
    data = request.json or {}
    protocol = data.get("protocol", "P01").upper()
    params = data.get("params", {})

    def _run_async():
        if protocol == "P01":
            _run_protocol_01_authority_signaling(params.get("subreddits"))
        elif protocol == "P02":
            _run_protocol_02_visual_saturation()
        elif protocol == "P03":
            _run_protocol_03_sentiment_exploitation(params.get("query", "SaaS fatigue"))
        elif protocol == "P04":
            _run_protocol_04_api_narrative_optimizer()
        else:
            _log_mission("??", "Unknown Protocol", f"No handler for {protocol}")

    threading.Thread(target=_run_async, daemon=True).start()

    return jsonify({
        "status": "success",
        "message": f"Protocol {protocol} dispatched",
        "ts": time.time()
    })


@scriptmaster_bp.route("/narrative", methods=["GET"])
def get_narrative_report():
    """
    P04 API Narrative Optimizer — synchronous report.
    Returns copy quality issues found in llms.txt and mcp.json manifests.
    No AI model required. Free endpoint.
    """
    results = _run_protocol_04_api_narrative_optimizer()
    high    = [r for r in results if r.get("priority") == "HIGH"]
    medium  = [r for r in results if r.get("priority") == "MEDIUM"]
    return jsonify({
        "status":        "success",
        "node":          "P04-API-NARRATIVE-OPTIMIZER",
        "total_issues":  len(results),
        "high_priority": len(high),
        "issues":        results,
        "scoring_note":  "Issues ranked HIGH when copy pattern appears in MCP tool descriptions (AI agents read these). Fixing HIGH issues directly improves AI discoverability.",
    })


@scriptmaster_bp.route("/mission_log", methods=["GET"])
def get_mission_log():
    """Returns the last N mission log entries."""
    limit = int(request.args.get("limit", 20))
    with _LOG_LOCK:
        log = list(_MISSION_LOG[:limit])
    return jsonify({"status": "success", "log": log, "total": len(_MISSION_LOG)})


@scriptmaster_bp.route("/ingest_intel", methods=["POST"])
def ingest_intel():
    """
    Ingest raw scraped text → AI analysis → structured signal.
    Body: { "text": "...", "source": "reddit|twitter|web" }
    """
    data = request.json or {}
    text = data.get("text", "").strip()
    source = data.get("source", "unknown")

    if not text:
        return jsonify({"status": "error", "message": "No text provided"}), 400

    try:
        import openai
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return jsonify({"status": "error", "message": "OPENAI_API_KEY not set"}), 500

        client = openai.OpenAI(api_key=api_key)
        sys_prompt = _SYSTEM_PROMPT or "You are the ScriptMasterLabs Orchestrator. Extract tactical intel."

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": f"SOURCE: {source}\n\nINTEL:\n{text}\n\nExtract: pain_point, positioning_opportunity, recommended_product, urgency_score (0-10). Return JSON."}
            ],
            response_format={"type": "json_object"},
            max_tokens=500
        )

        analysis = json.loads(response.choices[0].message.content)
        tokens = response.usage.total_tokens if response.usage else 0

        _log_mission("AI", f"Intel from {source}", f"urgency={analysis.get('urgency_score','?')}", tokens_used=tokens)

        return jsonify({
            "status": "success",
            "analysis": analysis,
            "tokens_used": tokens,
            "source": source
        })

    except Exception as e:
        logger.error(f"[SML] Intel ingestion failed: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@scriptmaster_bp.route("/ai_brief", methods=["GET"])
def get_ai_brief():
    """
    Generates a Beastmode Commander Brief using the loaded system prompt + current intel.
    """
    try:
        import openai
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return jsonify({"status": "error", "message": "OPENAI_API_KEY not set"}), 500

        with _LOG_LOCK:
            recent_log = list(_MISSION_LOG[:10])

        client = openai.OpenAI(api_key=api_key)
        prompt = f"""
{_SYSTEM_PROMPT}

CURRENT MISSION LOG (last 10 operations):
{json.dumps(recent_log, indent=2)}

Provide a "Beastmode Status Brief" covering:
1. Mission posture (which protocols are generating signals)
2. Top 3 actionable opportunities from the log
3. Recommended next move for maximum SEO velocity
"""
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are the ScriptMasterLabs Institutional AI. Be decisive and tactical."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=800
        )
        brief = response.choices[0].message.content
        tokens = response.usage.total_tokens if response.usage else 0
        _log_mission("AI", "Beastmode Brief Generated", f"{tokens} tokens consumed", tokens_used=tokens)

        return jsonify({"status": "success", "brief": brief, "tokens_used": tokens})

    except Exception as e:
        logger.error(f"[SML] Brief generation failed: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
