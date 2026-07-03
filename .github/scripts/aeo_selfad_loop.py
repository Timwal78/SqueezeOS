"""
AEO Self-Advertising Loop — S1 → S2 → S3 → S4

Runs daily via GitHub Actions. Each stage feeds the next.
No external deps beyond `requests`. No LLM calls — pure API polling.

Stage breakdown:
  S1 — Semantic Gap Detector: what demand exists that SML doesn't own yet?
  S2 — P04 Narrative Optimizer: are our discovery docs strong enough to capture it?
  S3 — AgentRank probe: are AI assistants actually citing us for those gaps?
  S4 — AEIN conversion: which AI channel drives the most free→paid conversions?

Output: structured summary printed to GitHub Actions log.
Future: post digest to Discord webhook, write to /api/events/push.
"""

import os
import sys
import json
import time
import datetime
import requests

BASE        = os.environ.get("SQUEEZEOS_BASE", "https://squeezeos-api.onrender.com")
DRY_RUN     = os.environ.get("DRY_RUN", "false").lower() == "true"
TIMEOUT     = 30
RUN_DATE    = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")


def get(path: str, params: dict = None) -> dict | None:
    url = f"{BASE}{path}"
    try:
        r = requests.get(url, params=params, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"  [WARN] GET {path} failed: {e}")
        return None


def post(path: str, body: dict) -> dict | None:
    url = f"{BASE}{path}"
    try:
        r = requests.post(url, json=body, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"  [WARN] POST {path} failed: {e}")
        return None


def section(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def run_s1_semantic_gaps() -> dict:
    section("S1 — Semantic Gap Detector")
    data = get("/api/graph/gaps/")
    if not data:
        print("  No data returned — API may be cold starting")
        return {}

    gaps = data.get("gaps", [])
    total = data.get("total_gaps", len(gaps))
    print(f"  Total unmet demand signals: {total}")
    if gaps:
        print(f"  Top gaps:")
        for g in gaps[:5]:
            label = g.get("query") or g.get("gap") or g.get("label", "unknown")
            count = g.get("mention_count") or g.get("count", 0)
            print(f"    • {label} ({count} mentions)")
    return {"total": total, "top_gaps": [g.get("query") or g.get("gap", "") for g in gaps[:5]]}


def run_s2_narrative_check() -> dict:
    section("S2 — P04 Narrative Optimizer")
    data = get("/api/scriptmaster/narrative")
    if not data:
        print("  No data returned — P04 endpoint may not be active")
        return {}

    score = data.get("score", data.get("narrative_score", "N/A"))
    issues = data.get("issues", [])
    print(f"  Narrative quality score: {score}")
    if issues:
        print(f"  Issues detected ({len(issues)}):")
        for issue in issues[:5]:
            label = issue if isinstance(issue, str) else issue.get("description", str(issue))
            print(f"    ⚠ {label}")
    else:
        print("  No issues detected — docs are well-optimized")
    return {"score": score, "issue_count": len(issues)}


def run_s3_citation_probe() -> dict:
    section("S3 — AgentRank™ Citation Probe")
    data = get("/api/citation-score/")
    if not data:
        print("  No data returned")
        return {}

    services = data.get("services", data.get("scores", {}))
    overall  = data.get("overall_score", data.get("score", "N/A"))
    print(f"  Overall AgentRank™ score: {overall}/100")
    if isinstance(services, dict):
        for svc, score in list(services.items())[:5]:
            print(f"    {svc}: {score}")
    elif isinstance(services, list):
        for item in services[:5]:
            name  = item.get("service", item.get("name", "unknown"))
            score = item.get("score", "N/A")
            print(f"    {name}: {score}")
    return {"overall": overall}


def run_s4_agent_economy() -> dict:
    section("S4 — AEIN™ Agent Economy Intelligence")
    data = get("/x402/agent-economy/")
    if not data:
        print("  No data returned")
        return {}

    conversion = data.get("conversion_rate", data.get("free_to_paid_rate", "N/A"))
    top_agents  = data.get("top_agent_types", data.get("top_types", []))
    total_calls = data.get("total_calls", data.get("total_requests", "N/A"))
    print(f"  Total agent calls tracked: {total_calls}")
    print(f"  Free → paid conversion rate: {conversion}")
    if top_agents:
        print(f"  Top agent types by volume:")
        for agent in (top_agents[:5] if isinstance(top_agents, list) else []):
            if isinstance(agent, dict):
                print(f"    • {agent.get('type', agent.get('name', 'unknown'))}: {agent.get('count', agent.get('calls', ''))}")
            else:
                print(f"    • {agent}")
    return {"conversion": conversion, "top_agents": top_agents[:3] if isinstance(top_agents, list) else []}


def push_summary_to_sse(summary: dict):
    """Push the loop results to the SSE event stream so dashboards see it."""
    if DRY_RUN:
        print("\n  [DRY RUN] Would push summary to /api/events/push")
        return
    post("/api/events/push", {
        "type": "AEO_LOOP_COMPLETE",
        "source": "github-actions",
        "run_date": RUN_DATE,
        "summary": summary,
    })
    print("\n  ✓ Summary pushed to SSE event stream")


def main():
    print(f"\nAEO Self-Advertising Loop — {RUN_DATE}")
    print(f"Target: {BASE}")
    if DRY_RUN:
        print("Mode: DRY RUN — results logged only")

    # Warm up the API (Render free tier may be sleeping)
    print("\nWarming up API...")
    status = get("/api/status")
    if status:
        print(f"  API status: {status.get('status', 'unknown')}")
    else:
        print("  API cold starting — waiting 15s...")
        time.sleep(15)

    s1 = run_s1_semantic_gaps()
    s2 = run_s2_narrative_check()
    s3 = run_s3_citation_probe()
    s4 = run_s4_agent_economy()

    summary = {
        "run_date": RUN_DATE,
        "s1_gaps": s1,
        "s2_narrative": s2,
        "s3_citation": s3,
        "s4_economy": s4,
    }

    section("Loop Complete — Summary")
    print(json.dumps(summary, indent=2))

    push_summary_to_sse(summary)

    # Exit non-zero only on total failure (all stages returned empty)
    if not any([s1, s2, s3, s4]):
        print("\n[ERROR] All stages failed — API may be down")
        sys.exit(1)

    print(f"\n✓ AEO loop complete — {RUN_DATE}\n")


if __name__ == "__main__":
    main()
