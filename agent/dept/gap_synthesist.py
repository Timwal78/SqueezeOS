"""
SML GAP SYNTHESIST
===================
Closes the loop on the Semantic Gap Detector (core/api/gap_detector_bp.py,
GET /api/graph/gaps): that engine already finds real unmet developer demand
from Reddit/HN and clusters it by topic — but until now nothing acted on
what it found. This agent reads those real gap clusters, scores which ones
are plausible for SML to actually build well, and drafts a concrete
technical spec for the strongest candidates. This is the "Scout" and
"Draft" half — the other half, human approval, lives entirely outside this
process (core/api/gap_proposals_bp.py + Timothy).

ZERO CUSTODY, ZERO AUTO-DEPLOY: this agent never writes application code,
never opens a pull request, and never merges anything. Its only side
effect is one HTTP POST that adds a drafted spec to a human-review queue.
Approving an item in that queue does not deploy it either — it stays a
proposal until a human (or an agent explicitly assigned the follow-up
task) picks it up as ordinary dev work.

Source wired today:
  - core/api/gap_detector_bp.py's live gap leaderboard (GET /api/graph/gaps),
    itself sourced from real Reddit + HN searches. No synthetic gaps.

SEO/AEO/GEO technical-issue scanning is now built as a separate specialist
(agent/dept/seo_gap_scout.py, added 2026-07-21 per Timothy's explicit ask)
— it crawls sites directly over HTTP rather than duplicating the live
AEO/GEO Intelligence Suite's citation-tracking surface (aeo_stripe_bp.py,
citation_scout_bp.py), which is a different problem (technical page health
vs. AI-citation authority). Still NOT built: any "malicious agent skill"
guardrail — this codebase doesn't host a third-party agent-skill
marketplace, so the "fake skill / mutable payload" attack model from
recent research has no real target here to guard. Do not build without a
fresh, explicit ask.

Env:
  ANTHROPIC_API_KEY            (required)
  SQUEEZEOS_BASE_URL           (default: https://squeezeos-api.onrender.com)
  GAP_PROPOSALS_QUEUE_SECRET   (required to push drafts into the review queue)
"""

import os, sys, json, datetime, re
import requests
import anthropic

ANTH_KEY       = os.environ["ANTHROPIC_API_KEY"]
MODEL          = os.environ.get("DEPT_MODEL", "claude-sonnet-5")
SQUEEZEOS      = os.environ.get("SQUEEZEOS_BASE_URL", "https://squeezeos-api.onrender.com").rstrip("/")
QUEUE_SECRET   = os.environ.get("GAP_PROPOSALS_QUEUE_SECRET", "")
OUTPUT_DIR     = os.environ.get("SEO_OUTPUT_DIR", "agent/outputs")

SESSION = requests.Session()
SESSION.headers["User-Agent"] = "SMLGapSynthesist/1.0 (agent.scriptmasterlabs.com)"

# Mirrors gap_detector_bp.py's own capability list — used again here so the
# LLM's build-worthiness score has the same ground truth the detector used
# to decide "covered vs gap" in the first place.
SML_CAPABILITIES = [
    "squeeze scan", "market scanner", "options flow", "market intelligence",
    "iwm 0dte", "xrpl payment", "mcp tools trading", "ai council",
    "signal history", "futures signal", "settlement contract",
    "oracle directive", "gamma wall", "delta neutral", "fractal cascade",
    "neo4j market graph", "flask blueprint api", "x402 micropayment",
]


def call_squeezeos(path: str) -> dict:
    try:
        r = SESSION.get(f"{SQUEEZEOS}{path}", timeout=20)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)[:200]}


def _push_to_queue(record: dict) -> dict:
    if not QUEUE_SECRET:
        return {"error": "GAP_PROPOSALS_QUEUE_SECRET not set — cannot push to review queue"}
    try:
        r = SESSION.post(
            f"{SQUEEZEOS}/api/gap-proposals/submit",
            json=record,
            headers={"X-Gap-Proposals-Secret": QUEUE_SECRET},
            timeout=20,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)[:200]}


TOOLS = [
    {
        "name": "get_gap_leaderboard",
        "description": "Fetch the current ranked demand-gap leaderboard from SML's own live Semantic Gap Detector (real Reddit/HN developer-demand signals, already deployed).",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_market_status",
        "description": "Get live SqueezeOS API status to cite as technical proof of existing capability in a spec.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "score_gap",
        "description": "Score a demand gap's build-worthiness for SML (0-100): how well it fits SML's existing stack/skills vs. how novel/risky it would be to build. Below 60 will be auto-archived by the review queue.",
        "input_schema": {
            "type": "object",
            "properties": {
                "topic": {"type": "string"},
                "example_posts": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["topic"],
        },
    },
    {
        "name": "draft_build_proposal",
        "description": "Assemble a concrete technical build spec (proposed route/module, what existing SML capability it would extend, effort estimate) for one demand gap, and push it plus its score into the human-approval review queue. Does NOT write, open a PR, or deploy any code — only queues a draft for Timothy to review.",
        "input_schema": {
            "type": "object",
            "properties": {
                "gap_topic":       {"type": "string"},
                "gap_intensity":   {"type": "number", "description": "gap_intensity value from get_gap_leaderboard for this topic"},
                "proposed_route":  {"type": "string", "description": "e.g. '/api/whatever-new-thing'"},
                "extends":         {"type": "string", "description": "which existing module/blueprint this would build on, if any"},
                "effort_estimate": {"type": "string", "description": "e.g. 'small — single new blueprint, no new external deps'"},
                "build_score":     {"type": "number"},
                "source_evidence": {"type": "array", "items": {"type": "string"}, "description": "example post titles/URLs this is drafted from"},
                "spec_markdown":   {"type": "string", "description": "Full technical spec in markdown: problem, proposed endpoint(s)/data model, what it reuses from the existing codebase, open questions for Timothy"},
            },
            "required": ["gap_topic", "build_score", "spec_markdown"],
        },
    },
]


def execute_tool(name: str, inputs: dict) -> str:
    if name == "get_gap_leaderboard":
        return json.dumps(call_squeezeos("/api/graph/gaps"))
    elif name == "get_market_status":
        return json.dumps(call_squeezeos("/api/status"))
    elif name == "score_gap":
        topic = inputs.get("topic", "").lower()
        posts = " ".join(inputs.get("example_posts", [])).lower()
        combined = topic + " " + posts
        overlap = sum(1 for c in SML_CAPABILITIES if any(w in combined for w in c.split()))
        score = min(100, overlap * 12 + (15 if "api" in combined else 0))
        return json.dumps({
            "topic": inputs.get("topic"),
            "score": score,
            "build_worthy": score >= 60,
            "capability_overlap": overlap,
        })
    elif name == "draft_build_proposal":
        record = {
            "gap_topic":       inputs.get("gap_topic", ""),
            "gap_intensity":   inputs.get("gap_intensity", 0),
            "proposed_route":  inputs.get("proposed_route", ""),
            "extends":         inputs.get("extends", ""),
            "effort_estimate": inputs.get("effort_estimate", "unknown"),
            "build_score":     inputs.get("build_score", 0),
            "source_evidence": inputs.get("source_evidence", []),
            "spec_markdown":   inputs.get("spec_markdown", ""),
        }
        result = _push_to_queue(record)
        return json.dumps(result)
    return json.dumps({"error": f"Unknown tool: {name}"})


def run() -> dict:
    client = anthropic.Anthropic(api_key=ANTH_KEY)
    today  = datetime.date.today().isoformat()

    system = f"""You are the SML Gap Synthesist. Your job is to read SML's already-live Semantic Gap Detector output (real unmet developer demand from Reddit/HN) and draft concrete, honest build specs for the gaps most worth SML actually building. You NEVER write, open a PR for, or deploy any code — your only action tool (draft_build_proposal) pushes a spec into a review queue that Timothy must approve manually, and approval still doesn't deploy anything.

Today: {today}

SML's existing capability surface (for judging fit, not for you to re-describe):
{json.dumps(SML_CAPABILITIES, indent=2)}

PROCEDURE:
1. Call get_gap_leaderboard to see today's real, ranked demand gaps.
2. Call get_market_status once to have live system facts available to cite in specs.
3. For each gap in the leaderboard that is NOT already covered_by_sml and has gap_intensity > 0, call score_gap.
4. For every gap scoring >=60, call draft_build_proposal with a real, specific spec_markdown: state the problem in the gap's own terms (cite the example posts), propose a concrete Flask blueprint/route that would address it, name what existing module it would extend or reuse (be honest if the answer is "nothing, this would be new"), give an honest effort estimate, and list open questions Timothy would need to decide before this gets built (e.g. does it need a new paid data source, a new env var, a pricing decision). Do not call draft_build_proposal for anything scoring below 60, and do not fabricate a gap that isn't in the real leaderboard.
5. If the leaderboard is empty or all gaps are already covered_by_sml, say so plainly — do not invent a gap to fill the report.
6. Output structured JSON:

{{
  "date": "{today}",
  "gaps_scanned": <int>,
  "queued": [
    {{"topic": "...", "score": <int>, "id": "<proposal_id from draft_build_proposal result, if any>"}}
  ],
  "archived_low_score": [{{"topic": "...", "score": <int>}}],
  "recommended_next_step": "<one concrete action for Timothy>"
}}"""

    messages = [{"role": "user", "content": f"Run the gap review + scoring + draft cycle for {today}."}]
    tool_calls = 0
    resp = None

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
                    print(f"  [GAP:{blk.name}] {json.dumps(blk.input)[:80]}")
                    results.append({"type": "tool_result", "tool_use_id": blk.id, "content": execute_tool(blk.name, blk.input)})
            messages.append({"role": "user", "content": results})

    final_text = next((b.text for b in resp.content if hasattr(b, "text")), "") if resp else ""
    output = {"date": today, "tool_calls": tool_calls, "raw": final_text}
    m = re.search(r'\{[\s\S]*\}', final_text)
    if m:
        try:
            output.update(json.loads(m.group()))
        except json.JSONDecodeError:
            pass

    os.makedirs(f"{OUTPUT_DIR}/gap_proposals", exist_ok=True)
    path = f"{OUTPUT_DIR}/gap_proposals/{today}_gap_scan.json"
    with open(path, "w") as f:
        json.dump(output, f, indent=2)
    queued = output.get("queued", [])
    print(f"\n[GAP SYNTHESIST] Gaps scanned: {output.get('gaps_scanned', '?')}")
    print(f"[GAP SYNTHESIST] Queued for review: {len(queued)}")
    for q in queued[:3]:
        print(f"  → {q.get('topic', '')[:60]} score={q.get('score')}")
    return output


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
