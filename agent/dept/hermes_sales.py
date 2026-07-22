"""
SML HERMES SALES AGENT
======================
Sole mission: sell the Agent Economy OS — the @scriptmasterlabs/mcp-x402
MCP server + x402 pay-per-call endpoints — around the clock. Runs every 4h
with the rest of the marketing department (6x/day = 24/7 coverage), so
there is always a fresh pass over the funnel while Timothy sleeps.

What it actually does each run (all real, nothing fabricated):
  1. STOREFRONT CHECK — live HTTP checks that the funnel is sellable right
     now: mcp-x402 gateway up, npm package resolvable on the public
     registry, Hermes landing page reachable, SqueezeOS API healthy.
     A dead storefront is reported as-is — pitching a broken funnel is
     worse than pitching nothing.
  2. LEAD GEN — searches real Reddit/HN conversations (reusing Community
     Scout's tested search functions) with buying-intent queries: people
     asking how to monetize an MCP server, let agents pay for APIs, run an
     autonomous business, etc.
  3. PITCH DRAFTING — for each qualified lead, drafts a personalized,
     value-first reply via Claude and POSTs it to the /api/outreach review
     queue for Timothy's approval.

ZERO AUTO-POSTING: this agent never posts to Reddit, HN, X, or anywhere
else. Its only side effect is the HTTP POST into the human-review queue
(core/api/outreach_bp.py). Approving a pitch there does not post it either
— posting stays manual. Same reasons Directory Ranger never auto-submits:
platform ToS, spam risk, and brand safety.

Env:
  ANTHROPIC_API_KEY      (required)
  OUTREACH_QUEUE_SECRET  (required to push pitches into the review queue)
  SQUEEZEOS_BASE_URL     (default: https://squeezeos-api.onrender.com)
  MCP_X402_BASE_URL      (default: https://mcp-x402.onrender.com)
"""

import os, sys, json, datetime, re
import requests
import anthropic

from .community_scout import search_reddit, search_hn

ANTH_KEY        = os.environ["ANTHROPIC_API_KEY"]
MODEL           = os.environ.get("DEPT_MODEL", "claude-sonnet-5")
SQUEEZEOS       = os.environ.get("SQUEEZEOS_BASE_URL", "https://squeezeos-api.onrender.com")
MCP_X402        = os.environ.get("MCP_X402_BASE_URL", "https://mcp-x402.onrender.com")
OUTREACH_SECRET = os.environ.get("OUTREACH_QUEUE_SECRET", "")
OUTPUT_DIR      = os.environ.get("SEO_OUTPUT_DIR", "agent/outputs")

SESSION = requests.Session()
SESSION.headers["User-Agent"] = "SMLHermesSales/1.0 (agent.scriptmasterlabs.com; drafts only, never auto-posts)"

# Buying-intent queries — people with the PROBLEM the Agent Economy OS solves,
# not just people discussing the topic (that's Community Scout's beat).
LEAD_QUERIES = [
    "monetize MCP server",
    "charge for MCP tool calls",
    "AI agent pay for API",
    "agent wallet payments",
    "x402 protocol",
    "HTTP 402 micropayments",
    "autonomous agent business",
    "AI agent run online store",
    "agent pays per call API",
    "sell API access to AI agents",
    "MCP server billing",
    "AI agent financial data API",
]

LEAD_SUBREDDITS = [
    "AIAgents", "LocalLLaMA", "SideProject", "startups", "webdev",
    "programming", "algotrading", "artificial", "indiehackers",
]

# What we sell — real, live surface only. Prices come from
# SML_Portfolio/mcp-x402/src/server/registry/pricing.ts (advertised == charged,
# enforced by that repo's pricing-drift test). Do not invent tools or prices.
OFFER = {
    "install":       "npx @scriptmasterlabs/mcp-x402  (MIT-licensed, one-liner into Claude Desktop/Code or Cursor)",
    "free_hook":     "sml_discover, sml_status, squeezeos_preview, proof_credit_score, agentcard_lookup — all $0.00, instant value with zero wallet setup",
    "pay_per_call":  "premium tools are x402 pay-per-call in USDC (Base/XRPL/Solana): leviathan_signal $0.05, squeezeos_council $0.10, xmit_edgar_decode $0.02, crawl_paid_fetch $0.005, federal data endpoints $0.02-0.03",
    "marketplace":   "nexus_agent_hire — agents hire other agents through the SML marketplace",
    "credit_bureau": "Agent Credit Bureau: FICO-style 300-850 scores for agent wallets — agents build financial reputation by paying reliably",
    "landing":       "https://www.scriptmasterlabs.com/hermes",
    "npm":           "https://www.npmjs.com/package/@scriptmasterlabs/mcp-x402",
}


# ── Storefront check — live HTTP, real results only ─────────────────────────

def check_storefront() -> dict:
    """Verify every link in the funnel a prospect would actually hit.
    Each check reports its real outcome; nothing is assumed up."""
    checks = {}

    def _check(name: str, url: str, ok_codes=(200,)) -> None:
        try:
            r = SESSION.get(url, timeout=20)
            checks[name] = {"url": url, "http": r.status_code, "ok": r.status_code in ok_codes}
        except Exception as e:
            checks[name] = {"url": url, "ok": False, "error": str(e)[:120]}

    _check("mcp_x402_gateway", f"{MCP_X402}/health")
    _check("squeezeos_api", f"{SQUEEZEOS}/api/status")
    _check("hermes_landing_page", "https://www.scriptmasterlabs.com/hermes")
    _check("npm_package", "https://registry.npmjs.org/@scriptmasterlabs/mcp-x402")

    checks["all_ok"] = all(v.get("ok") for k, v in checks.items() if isinstance(v, dict))
    return checks


def _push_pitch(record: dict) -> dict:
    if not OUTREACH_SECRET:
        return {"error": "OUTREACH_QUEUE_SECRET not set — cannot push to review queue"}
    try:
        r = SESSION.post(
            f"{SQUEEZEOS}/api/outreach/submit",
            json=record,
            headers={"X-Outreach-Secret": OUTREACH_SECRET},
            timeout=20,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)[:200]}


TOOLS = [
    {
        "name": "search_reddit",
        "description": "Search a subreddit for recent posts matching a buying-intent query (past week).",
        "input_schema": {
            "type": "object",
            "properties": {
                "subreddit": {"type": "string"},
                "query":     {"type": "string"},
            },
            "required": ["subreddit", "query"],
        },
    },
    {
        "name": "search_hackernews",
        "description": "Search Hacker News for recent stories/comments matching a buying-intent query.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
    {
        "name": "queue_pitch",
        "description": (
            "Queue a drafted pitch for a qualified lead into the human-review queue. "
            "Does NOT post anything anywhere — Timothy reviews, approves, and posts manually. "
            "Only queue leads with genuine buying intent (score 0-100; below the server "
            "threshold gets auto-archived). The pitch must lead with value for the thread, "
            "reference only real tools/prices from the offer sheet, and never promise returns."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "platform":       {"type": "string", "enum": ["Reddit", "HackerNews"]},
                "lead_title":     {"type": "string"},
                "lead_url":       {"type": "string"},
                "lead_context":   {"type": "string", "description": "What the person is actually asking for / struggling with"},
                "product":        {"type": "string", "description": "Which part of the Agent Economy OS fits, e.g. 'mcp-x402 npm', 'x402 pay-per-call', 'Agent Credit Bureau'"},
                "pitch_markdown": {"type": "string", "description": "The full drafted reply, ready to paste"},
                "lead_score":     {"type": "number", "description": "0-100 buying-intent score"},
            },
            "required": ["platform", "lead_title", "lead_url", "pitch_markdown", "lead_score"],
        },
    },
]


def execute_tool(name: str, inputs: dict) -> str:
    if name == "search_reddit":
        return json.dumps(search_reddit(inputs["subreddit"], inputs["query"]))
    elif name == "search_hackernews":
        return json.dumps(search_hn(inputs["query"]))
    elif name == "queue_pitch":
        return json.dumps(_push_pitch(inputs))
    return json.dumps({"error": f"Unknown tool: {name}"})


def run() -> dict:
    today = datetime.date.today().isoformat()

    # 1. Storefront first — if the funnel is down, that IS the finding.
    storefront = check_storefront()
    print(f"[HERMES] Storefront check: {'ALL OK' if storefront.get('all_ok') else 'ISSUES FOUND'}")
    for k, v in storefront.items():
        if isinstance(v, dict) and not v.get("ok"):
            print(f"  ✗ {k}: {v.get('error', v.get('http'))}")

    client = anthropic.Anthropic(api_key=ANTH_KEY)

    system = f"""You are the SML Hermes Sales Agent. Your SOLE job: find people with genuine buying intent for the Agent Economy OS and draft the pitch that closes them. You draft — a human posts. Never claim anything will be auto-posted.

Today: {today}

THE OFFER (real surface only — never invent tools, prices, or results):
{json.dumps(OFFER, indent=2)}

Storefront status right now (from live checks this run):
{json.dumps(storefront, indent=2)}

LEAD QUERIES: {json.dumps(LEAD_QUERIES)}
SUBREDDITS: {json.dumps(LEAD_SUBREDDITS)}

PROCEDURE:
1. Run each lead query on HN, and on the 2-3 best-fit subreddits (don't search every query everywhere).
2. Qualify: a lead is someone with the PROBLEM we solve (monetizing an MCP server, letting an agent pay for data, building an autonomous business) — not just topical chatter. Score buying intent 0-100.
3. For each lead scoring >= 60, call queue_pitch with a drafted reply that:
   - Leads with a genuinely useful answer to their actual question
   - Mentions the relevant SML piece naturally, with the real price
   - Includes at most one link (landing page or npm)
   - NEVER promises profits, win rates, or "guaranteed" anything
   - Discloses affiliation plainly (e.g. "I build this")
4. If the storefront check shows a broken link, do NOT queue pitches that point at the broken piece — report it instead.
5. Finish with JSON:

{{
  "date": "{today}",
  "storefront_ok": {json.dumps(bool(storefront.get('all_ok')))},
  "searches_run": <int>,
  "leads_found": <int>,
  "pitches_queued": <int>,
  "pitches": [{{"url": "...", "title": "...", "score": <int>, "product": "..."}}],
  "storefront_issues": ["<only real issues from the check above>"]
}}"""

    messages = [{"role": "user", "content": f"Run the full sales pass for {today}. Find leads and queue pitches now."}]
    tool_calls = 0
    resp = None

    for _ in range(50):
        resp = client.messages.create(model=MODEL, max_tokens=8192, system=system, tools=TOOLS, messages=messages)
        messages.append({"role": "assistant", "content": resp.content})
        if resp.stop_reason == "end_turn":
            break
        if resp.stop_reason == "tool_use":
            results = []
            for blk in resp.content:
                if blk.type == "tool_use":
                    tool_calls += 1
                    print(f"  [HERMES:{blk.name}] {json.dumps(blk.input)[:80]}")
                    results.append({"type": "tool_result", "tool_use_id": blk.id, "content": execute_tool(blk.name, blk.input)})
            messages.append({"role": "user", "content": results})

    final_text = next((b.text for b in resp.content if hasattr(b, "text")), "") if resp else ""
    output = {"date": today, "tool_calls": tool_calls, "storefront": storefront, "raw": final_text}
    m = re.search(r'\{[\s\S]*\}', final_text)
    if m:
        try:
            output.update(json.loads(m.group()))
        except json.JSONDecodeError:
            pass

    os.makedirs(f"{OUTPUT_DIR}/sales", exist_ok=True)
    path = f"{OUTPUT_DIR}/sales/{today}_sales_pass.json"
    with open(path, "w") as f:
        json.dump(output, f, indent=2)

    queued = output.get("pitches_queued", 0)
    print(f"\n[HERMES] Leads: {output.get('leads_found', '?')} | Pitches queued for review: {queued}")
    return output


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
