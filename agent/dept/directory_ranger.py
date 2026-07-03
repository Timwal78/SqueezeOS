"""
SML DIRECTORY RANGER
====================
Sole mission: Get Script Master Labs listed everywhere AI devs and agents look for tools.

Checks 25+ AI tool directories, developer marketplaces, and MCP registries.
For each unlisted platform, generates a ready-to-submit listing package.
Output: agent/outputs/listings/YYYY-MM-DD_directory_report.json

Env:
  ANTHROPIC_API_KEY   (required)
  SQUEEZEOS_BASE_URL  (default: https://squeezeos-api.onrender.com)
"""

import os, sys, json, datetime, re, time
import requests
import anthropic

SQUEEZEOS    = os.environ.get("SQUEEZEOS_BASE_URL", "https://squeezeos-api.onrender.com")
ANTH_KEY     = os.environ["ANTHROPIC_API_KEY"]
MODEL        = os.environ.get("DEPT_MODEL", "claude-sonnet-5")
OUTPUT_DIR   = os.environ.get("SEO_OUTPUT_DIR", "agent/outputs")
SESSION      = requests.Session()
SESSION.headers["User-Agent"] = "SMLDirectoryRanger/1.0 (agent.scriptmasterlabs.com)"

# ── Directory targets ──────────────────────────────────────────────────────────
DIRECTORIES = [
    # MCP-specific
    {"name": "Smithery.ai",       "check_url": "https://registry.smithery.ai/servers?q=squeezeos",         "category": "mcp"},
    {"name": "Glama.ai MCP",      "check_url": "https://glama.ai/mcp/servers?search=squeezeos",            "category": "mcp"},
    {"name": "mcp.run",           "check_url": "https://mcp.run/search?q=squeezeos",                       "category": "mcp"},
    {"name": "mcp.so (MCP Hub)",  "check_url": "https://mcp.so/search?q=squeezeos",                        "category": "mcp"},
    {"name": "PulseMCP",          "check_url": "https://www.pulsemcp.com/servers?search=squeezeos",         "category": "mcp"},
    # AI tools
    {"name": "There's An AI",     "check_url": "https://theresanaiforthat.com/search/?q=scriptmasterlabs", "category": "ai_tool"},
    {"name": "Futurepedia",       "check_url": "https://www.futurepedia.io/search?query=scriptmasterlabs", "category": "ai_tool"},
    {"name": "Toolify.ai",        "check_url": "https://www.toolify.ai/search/scriptmasterlabs",           "category": "ai_tool"},
    {"name": "AI Top Tools",      "check_url": "https://aitoptools.com/?s=scriptmasterlabs",                "category": "ai_tool"},
    {"name": "OpenTools.ai",      "check_url": "https://opentools.ai/search?query=squeezeos",              "category": "ai_tool"},
    # Developer / API directories
    {"name": "RapidAPI",          "check_url": "https://rapidapi.com/search/squeezeos",                    "category": "api"},
    {"name": "public-apis.io",    "check_url": "https://public-apis.io/search?q=squeezeos",                "category": "api"},
    {"name": "APILayer",          "check_url": "https://apilayer.com/search?q=scriptmasterlabs",           "category": "api"},
    # Package registries
    {"name": "npmjs",             "check_url": "https://www.npmjs.com/search?q=squeezeos",                 "category": "package"},
    {"name": "PyPI",              "check_url": "https://pypi.org/search/?q=squeezeos",                     "category": "package"},
    # GitHub lists
    {"name": "awesome-mcp-servers", "check_url": "https://raw.githubusercontent.com/punkpeye/awesome-mcp-servers/main/README.md", "category": "github"},
    {"name": "awesome-ai-agents",   "check_url": "https://raw.githubusercontent.com/e2b-dev/awesome-ai-agents/main/README.md",    "category": "github"},
    # Crypto / DeFi / fintech
    {"name": "DeFi Llama Tools", "check_url": "https://defillama.com/tools",                               "category": "defi"},
    {"name": "CoinGecko Apps",   "check_url": "https://www.coingecko.com/en/categories/tools",             "category": "defi"},
    # Enterprise / Gov
    {"name": "G2 Software",      "check_url": "https://www.g2.com/search#q=scriptmasterlabs",              "category": "enterprise"},
    {"name": "ProductHunt",      "check_url": "https://www.producthunt.com/search?q=scriptmasterlabs",     "category": "enterprise"},
    {"name": "AlternativeTo",    "check_url": "https://alternativeto.net/browse/search/?q=squeezeos",      "category": "enterprise"},
]

SML_PROFILE = {
    "company":     "Script Master Labs, LLC",
    "sam_uei":     "G24VZA4RLMK3",
    "cage":        "21U51",
    "website":     "https://www.scriptmasterlabs.com",
    "mcp_url":     "https://squeezeos-api.onrender.com/mcp",
    "tagline":     "Institutional-grade AI trading intelligence & autonomous agent infrastructure — pay-per-call via x402",
    "description": (
        "Script Master Labs provides a sovereign AI infrastructure stack for autonomous agents and developers: "
        "44 x402 pay-per-call API endpoints (SEC filings, FDA warnings, federal grants, compliance, market signals), "
        "a 49-tool MCP server (SqueezeOS) for real-time institutional market intelligence, "
        "Ghost Layer (private XRP routing), RLUSD Rails (Xahau remittance), "
        "and a CASCADE ACCUMULATOR for institutional squeeze signal delivery. "
        "No subscriptions — agents pay RLUSD micropayments on XRPL and receive signed JWTs."
    ),
    "categories":  ["MCP Server", "Trading Intelligence", "x402 Protocol", "AI Agent Infrastructure", "Financial Data API"],
    "pricing":     "Pay-per-call via x402 (RLUSD on XRPL). From 0.02–0.25 RLUSD/call.",
    "github":      "https://github.com/timwal78/squeezeos",
    "keywords":    ["MCP", "x402", "trading signals", "institutional", "autonomous agents", "XRPL", "RLUSD", "squeeze scanner"],
}


def check_listing(url: str, search_terms: list[str] = None, timeout: int = 15) -> dict:
    terms = search_terms or ["scriptmasterlabs", "squeezeos", "script master labs"]
    try:
        r = SESSION.get(url, timeout=timeout, allow_redirects=True)
        body = r.text.lower()
        found = any(t.lower() in body for t in terms)
        return {"listed": found, "status": r.status_code, "error": None}
    except requests.Timeout:
        return {"listed": False, "status": None, "error": "timeout"}
    except Exception as e:
        return {"listed": False, "status": None, "error": str(e)[:100]}


TOOLS = [
    {
        "name": "check_directory",
        "description": "Check whether Script Master Labs / SqueezeOS is currently listed on a specific directory platform. Returns listed=true/false.",
        "input_schema": {
            "type": "object",
            "properties": {
                "platform_name": {"type": "string"},
                "check_url":     {"type": "string"},
            },
            "required": ["platform_name", "check_url"],
        },
    },
    {
        "name": "generate_listing_package",
        "description": "Generate a complete, ready-to-submit listing package for a specific platform. Tailored to that platform's format and audience.",
        "input_schema": {
            "type": "object",
            "properties": {
                "platform_name": {"type": "string", "description": "Name of the directory/marketplace"},
                "platform_category": {"type": "string", "enum": ["mcp", "ai_tool", "api", "package", "github", "defi", "enterprise"]},
                "max_description_chars": {"type": "integer", "description": "Character limit for description field (use 500 if unknown)"},
            },
            "required": ["platform_name", "platform_category"],
        },
    },
    {
        "name": "get_squeezeos_status",
        "description": "Get live SqueezeOS system status to populate listing with accurate current data.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
]


def execute_tool(name: str, inputs: dict) -> str:
    if name == "check_directory":
        result = check_listing(inputs["check_url"])
        return json.dumps({**result, "platform": inputs["platform_name"]})

    elif name == "generate_listing_package":
        platform = inputs["platform_name"]
        cat      = inputs.get("platform_category", "ai_tool")
        limit    = inputs.get("max_description_chars", 500)
        pkg = {
            "platform":         platform,
            "category":         cat,
            "name":             "SqueezeOS — AI Trading Intelligence MCP Server",
            "short_tagline":    SML_PROFILE["tagline"],
            "description":      SML_PROFILE["description"][:limit],
            "website":          SML_PROFILE["website"],
            "mcp_endpoint":     SML_PROFILE["mcp_url"],
            "categories":       SML_PROFILE["categories"],
            "pricing_model":    "Pay-per-call (x402)",
            "pricing_detail":   SML_PROFILE["pricing"],
            "github":           SML_PROFILE["github"],
            "logo_url":         "https://www.scriptmasterlabs.com/SML-Logo-300x150.png",
            "keywords":         SML_PROFILE["keywords"],
        }
        if cat == "mcp":
            pkg["mcp_config"] = {
                "mcpServers": {
                    "squeezeos": {
                        "url": SML_PROFILE["mcp_url"],
                        "transport": "streamable-http"
                    }
                }
            }
        return json.dumps(pkg, indent=2)

    elif name == "get_squeezeos_status":
        try:
            r = SESSION.get(f"{SQUEEZEOS}/api/status", timeout=15)
            r.raise_for_status()
            return json.dumps(r.json(), indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)})

    return json.dumps({"error": f"Unknown tool: {name}"})


def run() -> dict:
    client  = anthropic.Anthropic(api_key=ANTH_KEY)
    today   = datetime.date.today().isoformat()
    dirs_json = json.dumps(DIRECTORIES, indent=2)

    system = f"""You are the SML Directory Ranger. Your SOLE job: get Script Master Labs listed on every relevant platform.

Today: {today}
SML Profile:
{json.dumps(SML_PROFILE, indent=2)}

Platforms to check ({len(DIRECTORIES)} total):
{dirs_json}

PROCEDURE:
1. Call check_directory for EVERY platform in the list — do not skip any.
2. Call get_squeezeos_status once to get live metrics.
3. For each UNLISTED platform, call generate_listing_package immediately.
4. After checking all platforms, output a JSON report with this structure:

{{
  "date": "{today}",
  "total_checked": <int>,
  "already_listed": ["platform1", ...],
  "not_listed": ["platform2", ...],
  "check_errors": {{"platform": "error reason"}},
  "packages_generated": <int>,
  "submission_packages": {{
    "platform_name": {{ ...full listing package... }}
  }},
  "priority_submissions": ["<3 highest-priority platforms to submit to first>"],
  "squeezeos_live_metrics": {{...}}
}}

Do NOT skip any platform. Check all {len(DIRECTORIES)} before finalizing."""

    messages = [{"role": "user", "content": f"Run the full directory listing audit for {today}. Check all {len(DIRECTORIES)} platforms now."}]
    tool_calls = 0

    for _ in range(40):
        resp = client.messages.create(model=MODEL, max_tokens=8192, system=system, tools=TOOLS, messages=messages)
        messages.append({"role": "assistant", "content": resp.content})

        if resp.stop_reason == "end_turn":
            break
        if resp.stop_reason == "tool_use":
            results = []
            for blk in resp.content:
                if blk.type == "tool_use":
                    tool_calls += 1
                    print(f"  [RANGER:{blk.name}] {json.dumps(blk.input)[:80]}")
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

    os.makedirs(f"{OUTPUT_DIR}/listings", exist_ok=True)
    path = f"{OUTPUT_DIR}/listings/{today}_directory_report.json"
    with open(path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\n[RANGER] Report saved: {path}")
    not_listed = output.get("not_listed", [])
    print(f"[RANGER] Listed: {len(output.get('already_listed', []))} | Not listed: {len(not_listed)} | Packages generated: {output.get('packages_generated', 0)}")
    if not_listed:
        print(f"[RANGER] Priority submissions: {output.get('priority_submissions', not_listed[:3])}")
    return output


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
