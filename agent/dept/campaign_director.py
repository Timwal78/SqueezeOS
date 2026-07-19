"""
SML CAMPAIGN DIRECTOR — the CEO of the marketing department.

Runs every specialist agent, verifies each one actually produced real
output (not just "didn't crash"), reports honest progress to the public
activity feed as it goes, and synthesizes everything into an executive
report. If a specialist fails, that failure is reported as-is — it is
never papered over or replaced with a fabricated success.

Specialists supervised (each does one job only):
  - Directory Ranger  — checks 24 real directories, generates listing packages
  - Community Scout   — finds real Reddit/HN developer conversations
  - Federal Scout      — finds real federal contract opportunities
  - Grant Scout        — finds/scores/drafts grant proposals, queues them for
                          Timothy's manual approval (zero custody, never
                          submits or signs anything on its own)
  - Gap Synthesist      — reads the live Semantic Gap Detector's real demand
                          gaps and drafts build specs, queues them for
                          Timothy's manual approval (zero custody, never
                          writes or deploys code on its own)

Schedule: Daily (see .github/workflows/marketing-daily.yml)

Env:
  ANTHROPIC_API_KEY          (required)
  SEO_SLACK_WEBHOOK          (optional — Slack delivery)
  SEO_OUTPUT_DIR             (default: agent/outputs)
  MARKETING_ACTIVITY_SECRET  (required to publish to the live activity feed)
"""

import os, sys, json, datetime, glob, re
import requests
import anthropic

from . import directory_ranger, community_scout, federal_scout, grant_scout, gap_synthesist
from .activity_log import post_activity, post_directory_snapshot, post_federal_snapshot

ANTH_KEY      = os.environ["ANTHROPIC_API_KEY"]
MODEL         = os.environ.get("DEPT_MODEL", "claude-sonnet-5")
SLACK_WEBHOOK = os.environ.get("SEO_SLACK_WEBHOOK", "")
OUTPUT_DIR    = os.environ.get("SEO_OUTPUT_DIR", "agent/outputs")
SQUEEZEOS     = os.environ.get("SQUEEZEOS_BASE_URL", "https://squeezeos-api.onrender.com")

SESSION = requests.Session()
SESSION.headers["User-Agent"] = "SMLCampaignDirector/1.0 (agent.scriptmasterlabs.com)"

CEO_LABEL = "CEO (Campaign Director)"


def load_recent_output(subdir: str, pattern: str = "*.json", days: int = 7) -> list[dict]:
    cutoff = datetime.date.today() - datetime.timedelta(days=days)
    results = []
    for path in glob.glob(f"{OUTPUT_DIR}/{subdir}/{pattern}"):
        try:
            with open(path) as f:
                data = json.load(f)
            date_str = data.get("date", "")
            if date_str and date_str >= cutoff.isoformat():
                results.append(data)
        except Exception:
            pass
    return results


def get_squeezeos_status() -> dict:
    try:
        r = SESSION.get(f"{SQUEEZEOS}/api/status", timeout=20)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)[:100]}


def post_slack(text: str) -> None:
    if not SLACK_WEBHOOK:
        return
    try:
        r = requests.post(SLACK_WEBHOOK, json={"text": text}, timeout=10)
        r.raise_for_status()
        print("[DIRECTOR] Slack report delivered")
    except Exception as e:
        print(f"[DIRECTOR] Slack failed: {e}")


def _dispatch(agent_key: str, agent_label: str, task_desc: str, run_fn, summarize_fn) -> dict:
    """Assign one specialist's task, run it, verify the result, and report
    the real outcome to the live activity feed — success or failure, exactly
    as it happened. No result here is ever invented."""
    print(f"\n[CEO] Assigning to {agent_label}: {task_desc}")
    post_activity(CEO_LABEL, f"Assigned to {agent_label}: {task_desc}")

    try:
        result = run_fn()
        if not isinstance(result, dict) or result.get("error"):
            reason = result.get("error", "returned no usable output") if isinstance(result, dict) else "returned no usable output"
            print(f"[CEO] {agent_label} did not complete cleanly: {reason}")
            post_activity(agent_label, f"Run failed: {reason}", status="error")
            return {"error": reason}
        summary = summarize_fn(result)
        print(f"[CEO] {agent_label} completed: {summary}")
        post_activity(agent_label, f"Completed: {summary}", status="success")
        return result
    except Exception as e:
        reason = str(e)[:200]
        print(f"[CEO] {agent_label} failed: {reason}")
        post_activity(agent_label, f"Run failed: {reason}", status="error")
        return {"error": reason}


def run_all_agents() -> dict:
    """Run all department agents and collect outputs."""
    today = datetime.date.today().isoformat()
    results = {}

    print("\n[CEO] === SML MARKETING CAMPAIGN RUN ===")
    print(f"[CEO] Date: {today}\n")
    post_activity(CEO_LABEL, f"Starting daily campaign run for {today}")

    results["directory_ranger"] = _dispatch(
        "directory_ranger", "Directory Ranger",
        "audit all 24 tracked directories and package listings for any gaps",
        directory_ranger.run,
        lambda r: f"{len(r.get('already_listed', []))}/24 directories confirmed listed, "
                  f"{len(r.get('not_listed', []))} unlisted, "
                  f"{r.get('packages_generated', 0)} new submission packages generated",
    )
    if not results["directory_ranger"].get("error"):
        post_directory_snapshot(
            results["directory_ranger"].get("already_listed", []),
            results["directory_ranger"].get("not_listed", []),
        )

    results["community_scout"] = _dispatch(
        "community_scout", "Community Scout",
        "scan developer communities for real conversations about SML's products",
        community_scout.run,
        lambda r: f"{len(r.get('opportunities', []))} opportunities found across monitored channels, "
                  f"{len(r.get('top_opportunities', []))} flagged as top priority",
    )

    results["federal_scout"] = _dispatch(
        "federal_scout", "Federal Scout",
        "identify federal contract opportunities matching SML's SAM registration",
        federal_scout.run,
        lambda r: f"{len(r.get('high_relevance', []))} high-relevance federal opportunities identified",
    )
    if not results["federal_scout"].get("error"):
        post_federal_snapshot(
            results["federal_scout"].get("opportunities_scanned", 0),
            results["federal_scout"].get("high_relevance", []),
            results["federal_scout"].get("medium_relevance", []),
            results["federal_scout"].get("legislative_intel", []),
        )

    results["grant_scout"] = _dispatch(
        "grant_scout", "Grant Scout",
        "discover and qualify grant opportunities, queue drafted proposals for manual approval",
        grant_scout.run,
        lambda r: f"{len(r.get('queued', []))} opportunities queued for review "
                  f"(pending Timothy's approval — none submitted), "
                  f"{len(r.get('archived_low_score', []))} auto-archived below threshold",
    )

    results["gap_synthesist"] = _dispatch(
        "gap_synthesist", "Gap Synthesist",
        "review the live Semantic Gap Detector's real demand gaps and draft build specs for the strongest ones",
        gap_synthesist.run,
        lambda r: f"{len(r.get('queued', []))} build proposals queued for review "
                  f"(pending Timothy's approval — nothing built or deployed), "
                  f"{len(r.get('archived_low_score', []))} auto-archived below threshold",
    )

    return results


def synthesize_report(agent_results: dict, api_status: dict) -> dict:
    client = anthropic.Anthropic(api_key=ANTH_KEY)
    today  = datetime.date.today().isoformat()

    # Load historical outputs for trend data
    hist_listings  = load_recent_output("listings")
    hist_scout     = load_recent_output("scout")
    hist_federal   = load_recent_output("federal")
    hist_content   = load_recent_output("content")
    hist_grants    = load_recent_output("grants")
    hist_gaps      = load_recent_output("gap_proposals")

    context = {
        "date":           today,
        "agent_results":  agent_results,
        "api_status":     api_status,
        "historical": {
            "listing_runs":  len(hist_listings),
            "scout_runs":    len(hist_scout),
            "federal_runs":  len(hist_federal),
            "content_pages": len(hist_content),
            "grant_runs":    len(hist_grants),
            "gap_proposal_runs": len(hist_gaps),
        },
    }

    prompt = f"""You are the SML Campaign Director. Synthesize today's marketing department outputs into an executive report.

Data:
{json.dumps(context, indent=2, default=str)[:6000]}

Produce a JSON campaign report:
{{
  "date": "{today}",
  "week_summary": "2-3 sentence executive summary for Timothy",
  "kpis": {{
    "directories_listed_in": <count from ranger>,
    "directories_not_listed": <count>,
    "new_submission_packages": <count>,
    "community_opportunities": <count>,
    "high_priority_opportunities": <count>,
    "federal_opportunities": <count>,
    "content_pages_generated": <count>,
    "api_engines_live": <from status>,
    "grants_pending_review": <count from grant_scout.queued>,
    "gap_proposals_pending_review": <count from gap_synthesist.queued>
  }},
  "wins_this_week": ["<concrete achievement>", ...],
  "top_actions_next_week": [
    {{"action": "...", "agent": "...", "priority": "HIGH|MEDIUM"}}
  ],
  "listings_to_submit": ["<platform>", ...],
  "top_community_threads": ["<url>", ...],
  "federal_opportunities": ["<title + agency>", ...],
  "grants_awaiting_approval": ["<title + funder>", ...],
  "gap_proposals_awaiting_approval": ["<gap topic>", ...],
  "health": "GREEN|YELLOW|RED"
}}"""

    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        final_text = resp.content[0].text if resp.content else ""
    except anthropic.APIError as e:
        # Claude unavailable (low credit balance, rate limit, etc). Per-specialist
        # results above are still real and already reported — only the executive
        # summary is unavailable. Skip cleanly rather than crashing the whole run.
        print(f"[CEO] Report synthesis unavailable — Claude API error: {e}")
        final_text = ""

    report = {"date": today, "raw": final_text}
    if not final_text:
        report["health"] = "UNKNOWN"
        report["week_summary"] = "Executive summary unavailable this run — Claude API error (see agent results below for real per-agent status)."
        return report

    m = re.search(r'\{[\s\S]*\}', final_text)
    if m:
        try:
            report.update(json.loads(m.group()))
        except json.JSONDecodeError:
            pass
    return report


def format_slack_report(report: dict) -> str:
    health_emoji = {"GREEN": "🟢", "YELLOW": "🟡", "RED": "🔴"}.get(report.get("health", "YELLOW"), "🟡")
    kpis = report.get("kpis", {})
    wins = "\n".join(f"  ✅ {w}" for w in report.get("wins_this_week", [])[:4])
    actions = "\n".join(
        f"  {'🔥' if a.get('priority')=='HIGH' else '📌'} [{a.get('agent','?')}] {a.get('action','')}"
        for a in report.get("top_actions_next_week", [])[:5]
    )
    listings = ", ".join(report.get("listings_to_submit", [])[:5]) or "None pending"

    return (
        f"{health_emoji} *SML Marketing Campaign — {report.get('date')}*\n\n"
        f">{report.get('week_summary', 'No summary generated.')}\n\n"
        f"*KPIs:*\n"
        f"  📂 Directories listed: {kpis.get('directories_listed_in','?')} / {int(kpis.get('directories_listed_in',0)) + int(kpis.get('directories_not_listed',0)) or '?'} checked\n"
        f"  🎯 Community opps: {kpis.get('community_opportunities','?')} ({kpis.get('high_priority_opportunities','?')} HIGH)\n"
        f"  🏛️ Federal opps: {kpis.get('federal_opportunities','?')}\n"
        f"  💰 Grants awaiting your approval: {kpis.get('grants_pending_review','?')}\n"
        f"  🧩 Gap-to-build proposals awaiting your approval: {kpis.get('gap_proposals_pending_review','?')}\n"
        f"  📄 Content pages: {kpis.get('content_pages_generated','?')}\n"
        f"  ⚡ API engines live: {kpis.get('api_engines_live','?')}\n\n"
        f"*This week's wins:*\n{wins or '  None recorded'}\n\n"
        f"*Next actions:*\n{actions or '  None'}\n\n"
        f"*Submit listings to:* {listings}"
    )


def run() -> dict:
    today  = datetime.date.today().isoformat()
    status = get_squeezeos_status()
    agent_results = run_all_agents()
    report = synthesize_report(agent_results, status)

    os.makedirs(f"{OUTPUT_DIR}/campaign", exist_ok=True)
    path = f"{OUTPUT_DIR}/campaign/{today}_campaign_report.json"
    with open(path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\n[CEO] Campaign report saved: {path}")

    failures = [k for k, v in agent_results.items() if isinstance(v, dict) and v.get("error")]
    if failures:
        post_activity(CEO_LABEL, f"Run complete with issues — failed: {', '.join(failures)}", status="error")
    else:
        post_activity(CEO_LABEL, f"Run complete — health: {report.get('health', 'UNKNOWN')}. {report.get('week_summary', '')}".strip(), status="success")

    slack_text = format_slack_report(report)
    print("\n" + "="*60)
    print(slack_text)
    print("="*60)
    post_slack(slack_text)

    return report


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
