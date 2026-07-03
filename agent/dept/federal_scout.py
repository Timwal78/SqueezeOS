"""
SML FEDERAL SCOUT
=================
Sole mission: Use SML's OWN x402 federal data endpoints to find government AI/tech
contract opportunities relevant to Script Master Labs' capabilities.

SML is SAM.gov registered (UEI: G24VZA4RLMK3, CAGE: 21U51). This agent:
1. Calls SML's own x402 endpoints for grants (SBIR, NIH, Congress bills)
2. Identifies relevant opportunities matching SML's capabilities
3. Generates a capability statement and match summary for each opportunity
4. Produces content that can be used to build federal market presence

Side effect: Demonstrates SML's own product working in production — each x402
call is real revenue. The agent pays for its own market research.

Env:
  ANTHROPIC_API_KEY     (required)
  MCP_X402_BASE_URL     (default: https://mcp-x402.onrender.com)
  X402_PAYMENT_TOKEN    (optional — if set, calls paid endpoints directly)
"""

import os, sys, json, datetime, re
import requests
import anthropic

ANTH_KEY      = os.environ["ANTHROPIC_API_KEY"]
MODEL         = os.environ.get("DEPT_MODEL", "claude-sonnet-5")
MCP_X402      = os.environ.get("MCP_X402_BASE_URL", "https://mcp-x402.onrender.com")
SQUEEZEOS     = os.environ.get("SQUEEZEOS_BASE_URL", "https://squeezeos-api.onrender.com")
PAYMENT_TOKEN = os.environ.get("X402_PAYMENT_TOKEN", "")
OUTPUT_DIR    = os.environ.get("SEO_OUTPUT_DIR", "agent/outputs")

SESSION = requests.Session()
SESSION.headers["User-Agent"] = "SMLFederalScout/1.0 (agent.scriptmasterlabs.com; SAM UEI G24VZA4RLMK3)"

SML_CAPABILITIES = {
    "company":          "Script Master Labs, LLC",
    "sam_uei":          "G24VZA4RLMK3",
    "cage":             "21U51",
    "naics_codes":      ["541511", "541512", "541519", "511210", "523130"],
    "core_capabilities": [
        "Autonomous AI agent infrastructure (MCP protocol, 49 tools)",
        "Real-time market intelligence API (institutional-grade, pay-per-call)",
        "x402 HTTP micropayment protocol implementation",
        "XRPL/Xahau blockchain payment rails (RLUSD)",
        "Federal data aggregation (SEC, FDA, NIH, SBIR, Congress, FINRA, EPA)",
        "Compliance monitoring and anomaly detection",
        "Sovereign data infrastructure (zero-telemetry, no vendor lock-in)",
    ],
    "relevant_agencies": ["DoD", "NSF", "NIH", "DARPA", "DHS", "Treasury", "SEC", "CFTC"],
}


def call_x402_endpoint(path: str, method: str = "GET", body: dict = None) -> dict:
    url = f"{MCP_X402}{path}"
    headers = {}
    if PAYMENT_TOKEN:
        headers["X-Payment-Token"] = PAYMENT_TOKEN
    try:
        if method == "POST":
            r = SESSION.post(url, json=body or {}, headers=headers, timeout=30)
        else:
            r = SESSION.get(url, headers=headers, timeout=30)
        if r.status_code == 402:
            return {"status": 402, "error": "payment_required", "invoice": r.json()}
        r.raise_for_status()
        return r.json()
    except requests.HTTPError as e:
        return {"error": f"HTTP {e.response.status_code}", "detail": e.response.text[:300]}
    except Exception as e:
        return {"error": str(e)[:200]}


def call_squeezeos(path: str) -> dict:
    try:
        r = SESSION.get(f"{SQUEEZEOS}{path}", timeout=20)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)[:200]}


TOOLS = [
    {
        "name": "get_sbir_grants",
        "description": "Fetch current SBIR (Small Business Innovation Research) grant opportunities from SML's x402 federal data endpoint. Returns active solicitations.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_nih_grants",
        "description": "Fetch current NIH grant opportunities from SML's x402 federal data endpoint.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_congress_bills",
        "description": "Fetch recent Congress bills related to AI, technology, or financial regulation from SML's x402 federal data endpoint.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_market_status",
        "description": "Get SqueezeOS system status to include live API metrics in capability statement.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "score_opportunity",
        "description": "Score a specific federal opportunity for SML relevance. Analyzes title, description, agency, and funding amount against SML capabilities.",
        "input_schema": {
            "type": "object",
            "properties": {
                "opportunity_title": {"type": "string"},
                "agency":            {"type": "string"},
                "description":       {"type": "string"},
                "funding_amount":    {"type": "string"},
                "deadline":          {"type": "string"},
                "solicitation_id":   {"type": "string"},
            },
            "required": ["opportunity_title", "agency"],
        },
    },
    {
        "name": "generate_capability_match",
        "description": "Generate a targeted capability statement showing how SML's products align with a specific federal opportunity.",
        "input_schema": {
            "type": "object",
            "properties": {
                "opportunity_title": {"type": "string"},
                "agency":            {"type": "string"},
                "key_requirements":  {"type": "array", "items": {"type": "string"}},
                "solicitation_id":   {"type": "string"},
            },
            "required": ["opportunity_title", "agency"],
        },
    },
]


def execute_tool(name: str, inputs: dict) -> str:
    if name == "get_sbir_grants":
        return json.dumps(call_x402_endpoint("/x402/sbir-grants"))
    elif name == "get_nih_grants":
        return json.dumps(call_x402_endpoint("/x402/nih-grants"))
    elif name == "get_congress_bills":
        return json.dumps(call_x402_endpoint("/x402/congress-bills"))
    elif name == "get_market_status":
        return json.dumps(call_squeezeos("/api/status"))
    elif name == "score_opportunity":
        title = inputs.get("opportunity_title", "").lower()
        agency = inputs.get("agency", "").lower()
        desc = inputs.get("description", "").lower()
        keywords = ["ai", "machine learning", "autonomous", "data", "analytics", "fintech",
                    "blockchain", "payment", "trading", "financial", "cybersecurity", "software"]
        score = sum(2 for k in keywords if k in title) + sum(1 for k in keywords if k in desc)
        relevance = "HIGH" if score >= 6 else ("MEDIUM" if score >= 3 else "LOW")
        return json.dumps({
            "opportunity": inputs.get("opportunity_title"),
            "agency": inputs.get("agency"),
            "relevance": relevance,
            "score": score,
            "deadline": inputs.get("deadline", "unknown"),
            "solicitation_id": inputs.get("solicitation_id", ""),
            "matched_capabilities": [c for c in SML_CAPABILITIES["core_capabilities"]
                                     if any(k in c.lower() for k in title.split()[:5])],
        })
    elif name == "generate_capability_match":
        return json.dumps({
            "opportunity":     inputs.get("opportunity_title"),
            "agency":          inputs.get("agency"),
            "solicitation_id": inputs.get("solicitation_id", ""),
            "sml_match_statement": (
                f"Script Master Labs, LLC (SAM UEI: G24VZA4RLMK3, CAGE: 21U51) offers a sovereign AI "
                f"infrastructure stack directly applicable to {inputs.get('opportunity_title')}. "
                f"Our MCP-protocol API server provides 49 real-time intelligence tools, "
                f"44 x402 pay-per-call federal data endpoints (SEC, FDA, NIH, SBIR, Congress, FINRA, EPA), "
                f"and an autonomous agent payment layer via XRPL/RLUSD — enabling {inputs.get('agency', 'federal agencies')} "
                f"to deploy AI agents that pay for their own data and report in real-time. "
                f"Contact: timothy.walton45@gmail.com | scriptmasterlabs.com"
            ),
            "key_differentiators": [
                "SAM.gov registered small business — eligible for set-aside contracts",
                "Zero vendor lock-in: sovereign data, no cloud dependency",
                "Live federal data pipeline already operational (SEC, FDA, NIH endpoints)",
                "x402 micropayment protocol: agents fund themselves, reducing procurement friction",
            ],
        })
    return json.dumps({"error": f"Unknown tool: {name}"})


def run() -> dict:
    client = anthropic.Anthropic(api_key=ANTH_KEY)
    today  = datetime.date.today().isoformat()

    system = f"""You are the SML Federal Scout. Your SOLE job: find federal contract and grant opportunities that match Script Master Labs' capabilities, using SML's OWN federal data APIs.

Today: {today}

SML Profile:
{json.dumps(SML_CAPABILITIES, indent=2)}

KEY INSIGHT: SML sells federal data APIs. Using those APIs to scout for contracts demonstrates the product working AND finds revenue opportunities. Every tool call is SML's product in action.

PROCEDURE:
1. Call get_sbir_grants — scan for AI, software, data, fintech solicitations.
2. Call get_nih_grants — look for data/AI/analytics opportunities.
3. Call get_congress_bills — identify upcoming legislation that creates market need for SML's data products.
4. Call get_market_status — capture live API metrics for capability statement.
5. For each opportunity with potential relevance, call score_opportunity.
6. For HIGH-relevance opportunities, call generate_capability_match.
7. Output structured JSON:

{{
  "date": "{today}",
  "opportunities_scanned": <int>,
  "high_relevance": [
    {{
      "title": "...",
      "agency": "...",
      "solicitation_id": "...",
      "deadline": "...",
      "funding": "...",
      "score": <int>,
      "capability_match": "...",
      "action": "apply|watch|note"
    }}
  ],
  "medium_relevance": [...],
  "legislative_intel": ["<bills that signal growing market for SML products>"],
  "capability_statement": "<general 3-sentence SML capability statement for federal market>",
  "recommended_actions": ["<top 3 concrete next steps>"]
}}

If federal endpoints return 402 (payment required), note it but continue with other sources."""

    messages = [{"role": "user", "content": f"Run the federal opportunity scan for {today}. Use all federal data tools."}]
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
                    print(f"  [FED:{blk.name}] {json.dumps(blk.input)[:80]}")
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

    os.makedirs(f"{OUTPUT_DIR}/federal", exist_ok=True)
    path = f"{OUTPUT_DIR}/federal/{today}_federal_opportunities.json"
    with open(path, "w") as f:
        json.dump(output, f, indent=2)
    high = output.get("high_relevance", [])
    print(f"\n[FEDERAL SCOUT] Opportunities scanned: {output.get('opportunities_scanned', '?')}")
    print(f"[FEDERAL SCOUT] HIGH relevance: {len(high)}")
    for o in high[:3]:
        print(f"  → {o.get('title', '')[:60]} [{o.get('agency')}] — {o.get('action', 'review')}")
    return output


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
