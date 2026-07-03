"""
SML AI SEO Business Orchestrator
=================================
Coordinates 7 specialist Claude agents using LIVE SML endpoints.
Each agent role calls real SqueezeOS / Superpower APIs — no mock data, ever.

Produces:
  - Daily executive briefing for operator Timothy
  - Market intelligence snapshot (oracle + RDT + council)
  - SEO content draft (titles, meta, H2s) from Beastmode protocol intel
  - Mission log from active Superpower protocols (P01/P02/P03)

Agent Squad roles (concepts — all run as Claude tool calls):
  1. Backend Architect  → system health + uptime check
  2. AI Engineer        → RDT multi-symbol rankings
  3. Growth Hacker      → highest-conviction oracle signals
  4. Reality Checker    → council verdict validation
  5. Content Creator    → Beastmode AI brief + SEO draft
  6. Rapid Prototyper   → trigger & poll SEO protocols
  7. Agents Orchestrator→ final executive briefing

Environment:
  ANTHROPIC_API_KEY     — Claude API key (required)
  SQUEEZEOS_BASE_URL    — default: https://squeezeos-api.onrender.com
  SEO_TARGET_KEYWORDS   — comma-separated override (optional)
  SEO_SLACK_WEBHOOK     — Slack webhook for briefing delivery (optional)
  SEO_OUTPUT_DIR        — output directory override (optional)
  RUN_ONCE              — set to "true" (always true when run via GH Actions)
"""

import os
import sys
import json
import time
import datetime
import re
import logging
import requests
import anthropic

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("SML-SEO-Orchestrator")

# ── Config ────────────────────────────────────────────────────────────────────
SQUEEZEOS      = os.environ.get("SQUEEZEOS_BASE_URL", "https://squeezeos-api.onrender.com")
ANTHROPIC_KEY  = os.environ["ANTHROPIC_API_KEY"]
SLACK_WEBHOOK  = os.environ.get("SEO_SLACK_WEBHOOK", "")
OUTPUT_DIR     = os.environ.get("SEO_OUTPUT_DIR", "agent/outputs")
MODEL          = os.environ.get("SEO_MODEL", "claude-sonnet-5")
DEFAULT_SYMBOLS = ["IWM", "SPY", "QQQ", "NVDA", "MSTR"]
TARGET_KEYWORDS = [k.strip() for k in os.environ.get(
    "SEO_TARGET_KEYWORDS",
    "AI SEO agent OS,autonomous trading intelligence,x402 payment protocol,"
    "MCP server trading,institutional market signals,squeeze momentum scanner",
).split(",") if k.strip()]

SESSION = requests.Session()
SESSION.headers["User-Agent"] = "SML-SEO-Orchestrator/1.0 (agent.scriptmasterlabs.com)"

# ── Tool Definitions ──────────────────────────────────────────────────────────
TOOLS = [
    {
        "name": "system_health",
        "description": (
            "Check SqueezeOS API system health: uptime, active engines, scan universe size, "
            "service versions, and live data feed status."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "market_oracle",
        "description": (
            "Get the Oracle directive for a symbol or all active symbols. Returns BUY/HOLD/SELL/SHIELD "
            "directive with confidence score and regime label (ALPHA_EXPANSION / MACRO_COLLAPSE / NEUTRAL / SHIELD). "
            "Leave symbol empty for the full batch."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Ticker symbol (e.g. IWM, SPY, NVDA). Empty = all active symbols.",
                }
            },
            "required": [],
        },
    },
    {
        "name": "signal_preview",
        "description": (
            "Get a free signal preview for a symbol: bias direction, regime, momentum score, "
            "and key indicator readings. 15-minute cache."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Ticker symbol"}
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "rdt_rankings",
        "description": (
            "Get RecurrentDepthTransformer multi-symbol ranked signals. Recursive what-if scoring "
            "across the full scan universe — returns ranked list of tickers by composite signal strength."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "demo_council",
        "description": (
            "Get the IWM Institutional Wisdom Matrix council verdict (free demo endpoint, 5-minute cache). "
            "Shows multi-engine consensus: squeeze, options flow, regime, whale activity."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "beastmode_status",
        "description": (
            "Get Superpower (Beastmode) protocol status: which SEO protocols are active (P01 Authority Signaling, "
            "P02 Visual Saturation, P03 Sentiment Exploitation) and the last run summary."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "beastmode_brief",
        "description": (
            "Get the AI-generated Beastmode brief: mission posture, active protocol signals, "
            "top Reddit intelligence targets, and recommended SEO actions."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "launch_seo_protocol",
        "description": (
            "Launch a Superpower SEO protocol in the background. "
            "P01 = Authority Signaling (Reddit thread targeting). "
            "P02 = Visual Saturation (infographic brief generation). "
            "P03 = Sentiment Exploitation (SaaS-fatigue thread recon, use query param). "
            "Returns immediately — results appear in mission_log within ~30 seconds."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "protocol": {
                    "type": "string",
                    "enum": ["P01", "P02", "P03"],
                    "description": "Protocol to launch",
                },
                "query": {
                    "type": "string",
                    "description": "For P03 only: sentiment search query (e.g. 'SaaS fatigue subscription cancellation')",
                },
            },
            "required": ["protocol"],
        },
    },
    {
        "name": "mission_log",
        "description": (
            "Retrieve the last 50 Superpower mission log entries — results from P01/P02/P03 protocol runs. "
            "Use after launch_seo_protocol to check results."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "signal_history",
        "description": (
            "Get recent signal history ring buffer from SqueezeOS (last 200 signals across all symbols, "
            "or per-symbol). Use to identify trending patterns and signal frequency."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Optional ticker symbol. Empty = all recent signals.",
                }
            },
            "required": [],
        },
    },
]

# ── Tool Executors ─────────────────────────────────────────────────────────────

def _get(path: str, timeout: int = 30) -> dict:
    url = f"{SQUEEZEOS}{path}"
    r = SESSION.get(url, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _post(path: str, body: dict, timeout: int = 30) -> dict:
    url = f"{SQUEEZEOS}{path}"
    r = SESSION.post(url, json=body, timeout=timeout)
    r.raise_for_status()
    return r.json()


def execute_tool(name: str, inputs: dict) -> str:
    """Route tool calls to live SML endpoints. Returns JSON string."""
    try:
        if name == "system_health":
            return json.dumps(_get("/api/status"), indent=2)

        elif name == "market_oracle":
            sym = inputs.get("symbol", "").strip().upper()
            path = f"/api/oracle/{sym}" if sym else "/api/oracle"
            return json.dumps(_get(path), indent=2)

        elif name == "signal_preview":
            sym = inputs["symbol"].strip().upper()
            return json.dumps(_get(f"/api/preview/{sym}"), indent=2)

        elif name == "rdt_rankings":
            return json.dumps(_get("/api/graph/rdt"), indent=2)

        elif name == "demo_council":
            return json.dumps(_get("/api/demo/council"), indent=2)

        elif name == "beastmode_status":
            return json.dumps(_get("/api/scriptmaster/status"), indent=2)

        elif name == "beastmode_brief":
            return json.dumps(_get("/api/scriptmaster/ai_brief"), indent=2)

        elif name == "launch_seo_protocol":
            protocol = inputs.get("protocol", "P01").upper()
            params = {}
            if protocol == "P03" and inputs.get("query"):
                params["query"] = inputs["query"]
            result = _post("/api/scriptmaster/run_protocol", {"protocol": protocol, "params": params})
            return json.dumps(result, indent=2)

        elif name == "mission_log":
            return json.dumps(_get("/api/scriptmaster/mission_log"), indent=2)

        elif name == "signal_history":
            sym = inputs.get("symbol", "").strip().upper()
            path = f"/api/history/{sym}" if sym else "/api/history"
            return json.dumps(_get(path), indent=2)

        else:
            return json.dumps({"error": f"Unknown tool: {name}"})

    except requests.HTTPError as e:
        status = e.response.status_code if e.response else "?"
        body = e.response.text[:400] if e.response else str(e)
        logger.warning(f"[TOOL:{name}] HTTP {status}: {body}")
        return json.dumps({"error": f"HTTP {status}", "detail": body})
    except requests.Timeout:
        logger.warning(f"[TOOL:{name}] Timeout after 30s")
        return json.dumps({"error": "upstream_timeout"})
    except Exception as exc:
        logger.error(f"[TOOL:{name}] {exc}")
        return json.dumps({"error": str(exc)})


# ── Agentic Loop ───────────────────────────────────────────────────────────────

def run_orchestrator() -> dict:
    """
    Run the 7-agent SEO business orchestrator via Claude tool-use loop.
    Returns structured output dict.
    """
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    today  = datetime.date.today().isoformat()
    now    = datetime.datetime.utcnow().strftime("%H:%M UTC")
    keywords_str = ", ".join(f'"{k}"' for k in TARGET_KEYWORDS)

    system_prompt = f"""You are the SML AI SEO Business Orchestrator — the master coordinator of 7 specialist AI agents running on top of the Script Master Labs sovereign data infrastructure at squeezeos-api.onrender.com.

Today: {today} {now}

Your 7 specialist agents and their responsibilities:
1. **Backend Architect** — Verifies system health, confirms all engines are live
2. **AI Engineer** — Pulls RDT multi-symbol rankings + signal history for technical depth
3. **Growth Hacker** — Identifies highest-conviction oracle signals for content angles
4. **Reality Checker** — Validates data with IWM council verdict, cross-checks signals
5. **Rapid Prototyper** — Launches Beastmode SEO protocols and polls mission log
6. **Content Creator** — Synthesizes all findings into SEO content targeting: {keywords_str}
7. **Agents Orchestrator** — Composes final executive briefing for operator Timothy

CRITICAL RULES (no exceptions):
- Call EVERY relevant tool. Never synthesize without gathering live data first.
- If a tool returns an error, report it as "Awaiting Data" — never invent substitute values.
- All signal values, confidence scores, regimes, and market data must come verbatim from API responses.
- Launch at least ONE Beastmode protocol (P01, P02, or P03), then wait briefly and poll mission_log.

After gathering data, produce this exact JSON structure (and nothing else after the JSON):

{{
  "date": "{today}",
  "system_status": {{
    "api_live": true/false,
    "engines_active": <from /api/status>,
    "scan_universe": <from /api/status>,
    "uptime": "<string>"
  }},
  "market_intel": {{
    "top_signals": [
      {{"symbol": "...", "directive": "...", "confidence": ..., "regime": "..."}}
    ],
    "rdt_top_ranked": ["..."],
    "council_verdict": "...",
    "regime_summary": "..."
  }},
  "seo_intel": {{
    "protocols_launched": ["P01"|"P02"|"P03"],
    "mission_entries": <count>,
    "reddit_targets_found": <count or "unavailable">,
    "content_angles": ["...", "..."]
  }},
  "content_draft": {{
    "title": "...",
    "meta_description": "...",
    "h2_sections": ["...", "...", "..."],
    "cta": "..."
  }},
  "executive_briefing": "3-5 sentence briefing for Timothy covering today's market posture, top signal, SEO protocol status, and recommended next action.",
  "tool_calls_made": <int>
}}"""

    user_message = (
        f"Run the full SML AI SEO business orchestration cycle for {today}.\n\n"
        "PHASE 1 (Backend Architect + AI Engineer): Check system health. Pull RDT rankings and signal history.\n"
        "PHASE 2 (Growth Hacker + Reality Checker): Get oracle directives for IWM, SPY, NVDA. Get IWM council verdict. Identify top signals.\n"
        "PHASE 3 (Rapid Prototyper): Check Beastmode status. Launch P01 (Authority Signaling). "
        "After launching, poll mission_log.\n"
        "PHASE 4 (Content Creator): Get Beastmode AI brief. Synthesize SEO content draft.\n"
        "PHASE 5 (Agents Orchestrator): Compose final structured JSON output.\n\n"
        "Begin with Phase 1 tool calls now."
    )

    messages = [{"role": "user", "content": user_message}]
    tool_calls_total = 0
    max_iterations = 15

    logger.info(f"Starting SEO orchestration run — {today} {now}")
    logger.info(f"Model: {MODEL} | Endpoint: {SQUEEZEOS}")

    for iteration in range(max_iterations):
        response = client.messages.create(
            model=MODEL,
            max_tokens=8192,
            system=system_prompt,
            tools=TOOLS,
            messages=messages,
        )
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            logger.info(f"Orchestrator completed — {iteration + 1} iterations, {tool_calls_total} tool calls")
            break

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    tool_calls_total += 1
                    input_preview = json.dumps(block.input)[:80]
                    logger.info(f"  [{block.name}] {input_preview}")
                    result_str = execute_tool(block.name, block.input)
                    logger.info(f"    → {result_str[:120]}...")
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_str,
                    })
            messages.append({"role": "user", "content": tool_results})

    # Extract final text
    final_text = ""
    for block in response.content:
        if hasattr(block, "text"):
            final_text = block.text
            break

    # Parse structured JSON output
    output = {
        "date": today,
        "tool_calls_made": tool_calls_total,
        "raw": final_text,
    }
    json_match = re.search(r'\{[\s\S]*\}', final_text)
    if json_match:
        try:
            parsed = json.loads(json_match.group())
            output.update(parsed)
        except json.JSONDecodeError:
            logger.warning("Could not parse structured JSON from response")

    return output


# ── Output & Delivery ──────────────────────────────────────────────────────────

def save_output(result: dict) -> str:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR, f"seo_briefing_{result['date']}.json")
    with open(path, "w") as f:
        json.dump(result, f, indent=2)
    logger.info(f"Output saved: {path}")
    return path


def post_to_slack(result: dict) -> None:
    if not SLACK_WEBHOOK:
        return
    briefing = result.get("executive_briefing", "No briefing generated.")
    draft    = result.get("content_draft", {})
    intel    = result.get("market_intel", {})
    top      = intel.get("top_signals", [])
    top_str  = " | ".join(
        f"{s['symbol']}: {s['directive']} ({s.get('confidence', '?')}%)"
        for s in top[:3]
    ) if top else "Awaiting Data"

    payload = {
        "text": (
            f"*SML SEO Orchestrator — {result['date']}*\n"
            f">{briefing}\n\n"
            f"*Top Signals:* {top_str}\n"
            f"*SEO Title Draft:* {draft.get('title', 'N/A')}\n"
            f"*Tool calls:* {result.get('tool_calls_made', '?')}"
        )
    }
    try:
        r = requests.post(SLACK_WEBHOOK, json=payload, timeout=10)
        r.raise_for_status()
        logger.info("Briefing posted to Slack")
    except Exception as e:
        logger.warning(f"Slack delivery failed: {e}")


def print_summary(result: dict) -> None:
    print("\n" + "=" * 65)
    print("  SML AI SEO ORCHESTRATOR — DAILY BRIEFING")
    print("=" * 65)

    sys_s = result.get("system_status", {})
    print(f"\n[Backend Architect] System: live={sys_s.get('api_live', '?')} | "
          f"engines={sys_s.get('engines_active', '?')} | "
          f"universe={sys_s.get('scan_universe', '?')}")

    intel = result.get("market_intel", {})
    top   = intel.get("top_signals", [])
    if top:
        print(f"\n[Growth Hacker] Top Signals:")
        for s in top[:5]:
            print(f"  {s['symbol']:6} {s['directive']:20} {s.get('confidence', '?')}% — {s.get('regime', '?')}")
    print(f"\n[Reality Checker] Council: {intel.get('council_verdict', 'Awaiting Data')}")
    print(f"  Regime: {intel.get('regime_summary', 'Awaiting Data')}")

    seo = result.get("seo_intel", {})
    print(f"\n[Rapid Prototyper] Protocols launched: {seo.get('protocols_launched', [])}")
    print(f"  Mission entries: {seo.get('mission_entries', 0)} | "
          f"Reddit targets: {seo.get('reddit_targets_found', 'unavailable')}")

    draft = result.get("content_draft", {})
    print(f"\n[Content Creator] SEO Draft:")
    print(f"  Title: {draft.get('title', 'N/A')}")
    print(f"  Meta:  {draft.get('meta_description', 'N/A')}")

    print(f"\n[Agents Orchestrator] Executive Briefing:")
    print(f"  {result.get('executive_briefing', 'No briefing generated.')}")
    print(f"\nTool calls made: {result.get('tool_calls_made', '?')}")
    print("=" * 65 + "\n")


# ── Entry Point ────────────────────────────────────────────────────────────────

def main() -> int:
    try:
        result    = run_orchestrator()
        save_path = save_output(result)
        print_summary(result)
        post_to_slack(result)
        logger.info(f"Run complete — {save_path}")
        return 0
    except KeyError as e:
        if "ANTHROPIC_API_KEY" in str(e):
            logger.error("ANTHROPIC_API_KEY not set")
        else:
            logger.error(f"Missing env var: {e}")
        return 1
    except Exception as e:
        logger.error(f"Orchestrator failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
