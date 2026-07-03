"""
SML COMMUNITY SCOUT
===================
Sole mission: Monitor developer communities for conversations about MCP servers,
x402 payments, autonomous trading, and squeeze signals — surface engagement
opportunities where SML can add value and gain visibility.

Platforms monitored:
  - Reddit (r/MachineLearning, r/LocalLLaMA, r/algotrading, r/learnmachinelearning,
            r/artificial, r/programming, r/CryptoCurrency, r/xrp)
  - Hacker News (search API)

Output: agent/outputs/scout/YYYY-MM-DD_opportunities.json
        → List of threads ranked by opportunity score with suggested talking points

Env:
  ANTHROPIC_API_KEY  (required)
  REDDIT_CLIENT_ID   (optional — uses public JSON endpoint if not set)
  REDDIT_SECRET      (optional)
"""

import os, sys, json, datetime, re
import requests
import anthropic

ANTH_KEY   = os.environ["ANTHROPIC_API_KEY"]
MODEL      = os.environ.get("DEPT_MODEL", "claude-sonnet-5")
OUTPUT_DIR = os.environ.get("SEO_OUTPUT_DIR", "agent/outputs")

SESSION = requests.Session()
SESSION.headers["User-Agent"] = "SMLCommunityScout/1.0 (agent.scriptmasterlabs.com; monitoring only)"

SUBREDDITS = [
    "MachineLearning", "LocalLLaMA", "algotrading", "learnmachinelearning",
    "artificial", "programming", "CryptoCurrency", "xrp", "AIAgents",
    "SideProject", "startups", "webdev",
]

SEARCH_QUERIES = [
    "MCP server trading",
    "x402 payment protocol",
    "autonomous trading agent",
    "Claude MCP finance",
    "squeeze momentum indicator",
    "XRPL autonomous agent",
    "RLUSD payment",
    "AI agent market data API",
    "institutional signals API",
    "MCP server finance",
    "pay per call AI API",
    "agent micropayment",
]

SML_VALUE_PROPS = {
    "mcp_trading":    "SqueezeOS MCP server at squeezeos-api.onrender.com/mcp — 49 tools for institutional market intelligence",
    "x402":           "x402 protocol implementation: agents pay RLUSD on XRPL, get signed JWT, call premium endpoints — no subscriptions",
    "signals":        "CASCADE ACCUMULATOR: real-time squeeze momentum signals, options flow, dark pool activity via /api/council",
    "federal_data":   "44 x402 endpoints: SEC 10-K, FDA warnings, SBIR grants, NIH grants, FINRA compliance — all pay-per-call",
    "ghost_layer":    "Ghost Layer: private XRPL+Base routing for MEV-resistant transactions",
}


def search_reddit(subreddit: str, query: str, sort: str = "new", limit: int = 10) -> dict:
    try:
        url = f"https://www.reddit.com/r/{subreddit}/search.json"
        params = {"q": query, "sort": sort, "limit": limit, "restrict_sr": "true", "t": "week"}
        r = SESSION.get(url, params=params, timeout=20)
        if r.status_code == 429:
            return {"error": "rate_limited", "posts": []}
        r.raise_for_status()
        data = r.json()
        posts = []
        for child in data.get("data", {}).get("children", []):
            p = child.get("data", {})
            posts.append({
                "id":        p.get("id"),
                "title":     p.get("title", ""),
                "score":     p.get("score", 0),
                "comments":  p.get("num_comments", 0),
                "url":       f"https://reddit.com{p.get('permalink', '')}",
                "selftext":  p.get("selftext", "")[:300],
                "created":   p.get("created_utc"),
                "author":    p.get("author", ""),
            })
        return {"subreddit": subreddit, "query": query, "posts": posts}
    except Exception as e:
        return {"error": str(e)[:100], "posts": []}


def search_hn(query: str, limit: int = 10) -> dict:
    try:
        url = "https://hn.algolia.com/api/v1/search_by_date"
        params = {"query": query, "tags": "story,comment", "numericFilters": "created_at_i>1700000000", "hitsPerPage": limit}
        r = SESSION.get(url, params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
        hits = []
        for h in data.get("hits", []):
            hits.append({
                "objectID":  h.get("objectID"),
                "title":     h.get("title") or h.get("comment_text", "")[:100],
                "points":    h.get("points", 0),
                "comments":  h.get("num_comments", 0),
                "url":       h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}",
                "author":    h.get("author", ""),
            })
        return {"platform": "HackerNews", "query": query, "hits": hits}
    except Exception as e:
        return {"error": str(e)[:100], "hits": []}


TOOLS = [
    {
        "name": "search_reddit",
        "description": "Search a specific subreddit for recent posts matching a query. Returns posts from the past week.",
        "input_schema": {
            "type": "object",
            "properties": {
                "subreddit": {"type": "string"},
                "query":     {"type": "string"},
                "sort":      {"type": "string", "enum": ["new", "hot", "relevance"], "default": "new"},
            },
            "required": ["subreddit", "query"],
        },
    },
    {
        "name": "search_hackernews",
        "description": "Search Hacker News for recent stories and comments matching a query.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "analyze_opportunity",
        "description": "Analyze a specific thread/post and generate a suggested SML talking point. Use for high-scoring opportunities found during search.",
        "input_schema": {
            "type": "object",
            "properties": {
                "platform":     {"type": "string"},
                "url":          {"type": "string"},
                "title":        {"type": "string"},
                "context":      {"type": "string", "description": "Thread body or key excerpt"},
                "opportunity_type": {"type": "string", "enum": ["question_answerable", "product_mention", "problem_match", "announcement_reply"]},
            },
            "required": ["platform", "url", "title", "context", "opportunity_type"],
        },
    },
]


def execute_tool(name: str, inputs: dict) -> str:
    if name == "search_reddit":
        return json.dumps(search_reddit(inputs["subreddit"], inputs["query"], inputs.get("sort", "new")))
    elif name == "search_hackernews":
        return json.dumps(search_hn(inputs["query"]))
    elif name == "analyze_opportunity":
        opp_type = inputs.get("opportunity_type", "question_answerable")
        vp_map = {
            "question_answerable": "x402" if "payment" in inputs.get("title","").lower() else "mcp_trading",
            "product_mention":     "mcp_trading",
            "problem_match":       "signals",
            "announcement_reply":  "federal_data",
        }
        vp_key = vp_map.get(opp_type, "mcp_trading")
        return json.dumps({
            "url":          inputs["url"],
            "title":        inputs["title"],
            "type":         opp_type,
            "talking_point": SML_VALUE_PROPS[vp_key],
            "sml_link":     "https://www.scriptmasterlabs.com/ai-seo-agent-os.html",
            "action":       "engage — add value first, mention SML naturally",
        })
    return json.dumps({"error": f"Unknown tool: {name}"})


def run() -> dict:
    client = anthropic.Anthropic(api_key=ANTH_KEY)
    today  = datetime.date.today().isoformat()

    system = f"""You are the SML Community Scout. Your SOLE job: find developer conversations where Script Master Labs can add genuine value and gain visibility.

Today: {today}

Search queries to run: {json.dumps(SEARCH_QUERIES)}
Subreddits to search: {json.dumps(SUBREDDITS)}
HN: search all queries above

PROCEDURE:
1. Search Reddit: run each query across the most relevant 4-5 subreddits (pick the best subreddit per query based on topic fit — don't search every query in every subreddit).
2. Search HackerNews: run all queries.
3. For any post with score > 10 OR comments > 5 that is relevant, call analyze_opportunity.
4. Deduplicate URLs.
5. Output JSON:

{{
  "date": "{today}",
  "searches_run": <int>,
  "raw_posts_found": <int>,
  "opportunities": [
    {{
      "platform": "Reddit/HN",
      "url": "...",
      "title": "...",
      "score": <int>,
      "comments": <int>,
      "type": "question_answerable|product_mention|problem_match|announcement_reply",
      "talking_point": "...",
      "priority": "HIGH|MEDIUM|LOW"
    }}
  ],
  "top_opportunities": ["<3 URLs ranked by impact>"],
  "keyword_trends": ["<keywords appearing most in found threads>"]
}}

Priority scoring: HIGH if question directly answerable by SML product. MEDIUM if SML is tangentially relevant. LOW if awareness only."""

    messages = [{"role": "user", "content": f"Run the full community intelligence scan for {today}. Search all platforms now."}]
    tool_calls = 0

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
                    print(f"  [SCOUT:{blk.name}] {json.dumps(blk.input)[:80]}")
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

    os.makedirs(f"{OUTPUT_DIR}/scout", exist_ok=True)
    path = f"{OUTPUT_DIR}/scout/{today}_opportunities.json"
    with open(path, "w") as f:
        json.dump(output, f, indent=2)
    opps = output.get("opportunities", [])
    high = [o for o in opps if o.get("priority") == "HIGH"]
    print(f"\n[SCOUT] Opportunities found: {len(opps)} | HIGH priority: {len(high)}")
    if high:
        for o in high[:3]:
            print(f"  → {o.get('title', '')[:70]}")
            print(f"    {o.get('url')}")
    return output


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
