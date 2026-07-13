"""
SML GRANT SCOUT
===============
Discovery + Qualification + Proposal Draft for grant/funding opportunities
matching Script Master Labs' capabilities. This is the "Scout" and "Filter"
half of the Autonomous Grant Agent — the third half, human approval, lives
entirely outside this process (core/api/grants_bp.py + Timothy).

ZERO CUSTODY, ZERO AUTONOMOUS SUBMISSION: this agent never signs a
transaction, never holds a wallet seed, and never submits an application
to a funder. Its only side effect is one HTTP POST that adds a drafted,
scored opportunity to a human-review queue. Approving an item in that
queue does not submit it either — see core/api/grants_bp.py's docstring.

Sources wired today:
  - SBIR / NIH federal grant data via SML's own x402 endpoints (reuses the
    same real, tested integration as federal_scout.py).

Sources NOT yet wired (do not fabricate these — no verified public API
integrated, same "not yet configured" pattern as AWS_MARKETPLACE_* or
TRADE_DESK_STRIPE_*_PRICE_ID elsewhere in this codebase):
  - Gitcoin Grants Stack / Allo Protocol
  - XRPL Grants Program
  - Virtuals Protocol developer/launchpad grants
  - AWS Activate / Google Cloud for Startups credit pools
  Wiring any of these requires first confirming the real, current public
  API endpoint and auth model — do not guess a URL.

Qualification: score_opportunity() mirrors federal_scout's scoring but
requires SML's own >=85 threshold (core/api/grants_bp.py enforces the
final auto-archive cutoff server-side via GRANTS_QUALIFY_THRESHOLD).

Env:
  ANTHROPIC_API_KEY     (required)
  MCP_X402_BASE_URL     (default: https://mcp-x402.onrender.com)
  SQUEEZEOS_BASE_URL    (default: https://squeezeos-api.onrender.com)
  X402_PAYMENT_TOKEN    (optional — if set, calls paid endpoints directly)
  GRANTS_QUEUE_SECRET   (required to push discoveries into the review queue)
"""

import os, sys, json, datetime, re
import requests
import anthropic

from .federal_scout import SML_CAPABILITIES, call_x402_endpoint, call_squeezeos

ANTH_KEY      = os.environ["ANTHROPIC_API_KEY"]
MODEL         = os.environ.get("DEPT_MODEL", "claude-sonnet-5")
SQUEEZEOS     = os.environ.get("SQUEEZEOS_BASE_URL", "https://squeezeos-api.onrender.com")
GRANTS_SECRET = os.environ.get("GRANTS_QUEUE_SECRET", "")
OUTPUT_DIR    = os.environ.get("SEO_OUTPUT_DIR", "agent/outputs")

SESSION = requests.Session()
SESSION.headers["User-Agent"] = "SMLGrantScout/1.0 (agent.scriptmasterlabs.com; SAM UEI G24VZA4RLMK3)"

QUALIFY_KEYWORDS = [
    "ai", "machine learning", "autonomous", "agent", "data", "analytics",
    "fintech", "blockchain", "xrpl", "payment", "trading", "financial",
    "cybersecurity", "software", "api", "infrastructure",
]


def _push_to_queue(record: dict) -> dict:
    if not GRANTS_SECRET:
        return {"error": "GRANTS_QUEUE_SECRET not set — cannot push to review queue"}
    try:
        r = SESSION.post(
            f"{SQUEEZEOS}/api/grants/submit",
            json=record,
            headers={"X-Grants-Secret": GRANTS_SECRET},
            timeout=20,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)[:200]}


TOOLS = [
    {
        "name": "get_sbir_grants",
        "description": "Fetch current SBIR grant opportunities from SML's own x402 federal data endpoint.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_nih_grants",
        "description": "Fetch current NIH grant opportunities from SML's own x402 federal data endpoint.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_market_status",
        "description": "Get live SqueezeOS API metrics to cite as technical proof in a proposal draft.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "score_opportunity",
        "description": "Score a grant opportunity's relevance to SML's capability profile (0-100). Below 85 will be auto-archived by the review queue.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "funder": {"type": "string"},
                "description": {"type": "string"},
            },
            "required": ["title", "funder"],
        },
    },
    {
        "name": "draft_proposal",
        "description": "Assemble a tailored proposal draft (capability statement, milestones, USD/RLUSD budget outline) for a specific opportunity, and push it plus its score into the human-approval review queue. Does NOT submit anything to the funder — this only queues a draft for Timothy to review.",
        "input_schema": {
            "type": "object",
            "properties": {
                "source":              {"type": "string", "description": "e.g. 'SBIR', 'NIH'"},
                "title":               {"type": "string"},
                "funder":              {"type": "string"},
                "program":             {"type": "string"},
                "deadline":            {"type": "string"},
                "funding_amount":      {"type": "string"},
                "url":                 {"type": "string"},
                "qualification_score": {"type": "number"},
                "matched_capabilities": {"type": "array", "items": {"type": "string"}},
                "proposal_markdown":   {"type": "string", "description": "Full drafted proposal body in markdown"},
                "milestones":          {"type": "array", "items": {"type": "string"}},
                "budget_summary":      {"type": "string"},
            },
            "required": ["source", "title", "funder", "qualification_score", "proposal_markdown"],
        },
    },
]


def execute_tool(name: str, inputs: dict) -> str:
    if name == "get_sbir_grants":
        return json.dumps(call_x402_endpoint("/x402/sbir-grants"))
    elif name == "get_nih_grants":
        return json.dumps(call_x402_endpoint("/x402/nih-grants"))
    elif name == "get_market_status":
        return json.dumps(call_squeezeos("/api/status"))
    elif name == "score_opportunity":
        title = inputs.get("title", "").lower()
        desc = inputs.get("description", "").lower()
        score = min(100, sum(8 for k in QUALIFY_KEYWORDS if k in title) + sum(3 for k in QUALIFY_KEYWORDS if k in desc))
        matched = [k for k in QUALIFY_KEYWORDS if k in title or k in desc]
        return json.dumps({
            "title": inputs.get("title"),
            "funder": inputs.get("funder"),
            "score": score,
            "qualifies": score >= 85,
            "matched_keywords": matched,
        })
    elif name == "draft_proposal":
        record = {
            "source":               inputs.get("source", ""),
            "title":                inputs.get("title", ""),
            "funder":               inputs.get("funder", ""),
            "program":              inputs.get("program", ""),
            "deadline":             inputs.get("deadline", "unknown"),
            "funding_amount":       inputs.get("funding_amount", "unknown"),
            "url":                  inputs.get("url", ""),
            "qualification_score":  inputs.get("qualification_score", 0),
            "matched_capabilities": inputs.get("matched_capabilities", []),
            "proposal_draft":       inputs.get("proposal_markdown", ""),
            "milestones":           inputs.get("milestones", []),
            "budget_summary":       inputs.get("budget_summary", ""),
        }
        result = _push_to_queue(record)
        return json.dumps(result)
    return json.dumps({"error": f"Unknown tool: {name}"})


def run() -> dict:
    client = anthropic.Anthropic(api_key=ANTH_KEY)
    today  = datetime.date.today().isoformat()

    system = f"""You are the SML Grant Scout. Find grant/funding opportunities matching Script Master Labs' capabilities and queue tailored proposal drafts for human review. You NEVER submit anything to a funder — your only action tool (draft_proposal) pushes a draft into a review queue that Timothy must approve manually.

Today: {today}

SML Profile:
{json.dumps(SML_CAPABILITIES, indent=2)}

Only wired sources today are SBIR and NIH via SML's own federal data endpoints. Do not invent results for Gitcoin, XRPL Grants, or Virtuals Protocol — those integrations don't exist yet. If asked to consider them, note in your output that they're unwired rather than fabricating any opportunity from them.

PROCEDURE:
1. Call get_sbir_grants and get_nih_grants.
2. Call get_market_status once to have live metrics available for proposal drafts.
3. For each real opportunity returned, call score_opportunity.
4. For every opportunity scoring >=85, call draft_proposal with a real, specific proposal_markdown (capability statement + 3-5 concrete milestones + a USD/RLUSD budget_summary) — this queues it for Timothy's review. Do not call draft_proposal for anything scoring below 85.
5. Output structured JSON:

{{
  "date": "{today}",
  "opportunities_scanned": <int>,
  "queued": [
    {{"title": "...", "funder": "...", "score": <int>, "id": "<opportunity_id from draft_proposal result, if any>"}}
  ],
  "archived_low_score": [{{"title": "...", "score": <int>}}],
  "unwired_sources_note": "Gitcoin/XRPL Grants/Virtuals Protocol are not yet integrated — no fabricated results.",
  "recommended_next_step": "<one concrete action for Timothy>"
}}

If federal endpoints return 402 (payment required), note it and continue with whatever data is available."""

    messages = [{"role": "user", "content": f"Run the grant discovery + qualification + draft cycle for {today}."}]
    tool_calls = 0

    for _ in range(30):
        resp = client.messages.create(model=MODEL, max_tokens=8192, system=system, tools=TOOLS, messages=messages)
        messages.append({"role": "assistant", "content": resp.content})
        if resp.stop_reason == "end_turn":
            break
        if resp.stop_reason == "tool_use":
            results = []
            for blk in resp.content:
                if blk.type == "tool_use":
                    tool_calls += 1
                    print(f"  [GRANT:{blk.name}] {json.dumps(blk.input)[:80]}")
                    results.append({"type": "tool_result", "tool_use_id": blk.id, "content": execute_tool(blk.name, blk.input)})
            messages.append({"role": "user", "content": results})

    final_text = next((b.text for b in resp.content if hasattr(b, "text")), "")
    output = {"date": today, "tool_calls": tool_calls, "raw": final_text}
    m = re.search(r'\{[\s\S]*\}', final_text)
    if m:
        try:
            output.update(json.loads(m.group()))
        except json.JSONDecodeError:
            pass

    os.makedirs(f"{OUTPUT_DIR}/grants", exist_ok=True)
    path = f"{OUTPUT_DIR}/grants/{today}_grant_scan.json"
    with open(path, "w") as f:
        json.dump(output, f, indent=2)
    queued = output.get("queued", [])
    print(f"\n[GRANT SCOUT] Opportunities scanned: {output.get('opportunities_scanned', '?')}")
    print(f"[GRANT SCOUT] Queued for review: {len(queued)}")
    for o in queued[:3]:
        print(f"  → {o.get('title', '')[:60]} [{o.get('funder')}] score={o.get('score')}")
    return output


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
