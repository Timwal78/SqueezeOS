"""
SML CAMPAIGN DIRECTOR
=====================
Sole mission: Run all marketing department agents, aggregate KPIs, and post
a weekly campaign status report to Slack.

This is the department head — it does not do original research but coordinates
all specialist agents and synthesizes their outputs into an executive report.

Schedule: Weekly (Mondays at 08:00 ET)

Env:
  ANTHROPIC_API_KEY    (required)
  SEO_SLACK_WEBHOOK    (optional — Slack delivery)
  SEO_OUTPUT_DIR       (default: agent/outputs)
"""

import os, sys, json, datetime, glob, re
import requests
import anthropic

from . import directory_ranger, community_scout, federal_scout

ANTH_KEY      = os.environ["ANTHROPIC_API_KEY"]
MODEL         = os.environ.get("DEPT_MODEL", "claude-sonnet-5")
SLACK_WEBHOOK = os.environ.get("SEO_SLACK_WEBHOOK", "")
OUTPUT_DIR    = os.environ.get("SEO_OUTPUT_DIR", "agent/outputs")
SQUEEZEOS     = os.environ.get("SQUEEZEOS_BASE_URL", "https://squeezeos-api.onrender.com")

SESSION = requests.Session()
SESSION.headers["User-Agent"] = "SMLCampaignDirector/1.0 (agent.scriptmasterlabs.com)"


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


def run_all_agents() -> dict:
    """Run all department agents and collect outputs."""
    today = datetime.date.today().isoformat()
    results = {}

    print("\n[DIRECTOR] === SML MARKETING CAMPAIGN RUN ===")
    print(f"[DIRECTOR] Date: {today}\n")

    print("[DIRECTOR] Starting Directory Ranger...")
    try:
        results["directory_ranger"] = directory_ranger.run()
    except Exception as e:
        results["directory_ranger"] = {"error": str(e)}
        print(f"[DIRECTOR] Directory Ranger failed: {e}")

    print("\n[DIRECTOR] Starting Community Scout...")
    try:
        results["community_scout"] = community_scout.run()
    except Exception as e:
        results["community_scout"] = {"error": str(e)}
        print(f"[DIRECTOR] Community Scout failed: {e}")

    print("\n[DIRECTOR] Starting Federal Scout...")
    try:
        results["federal_scout"] = federal_scout.run()
    except Exception as e:
        results["federal_scout"] = {"error": str(e)}
        print(f"[DIRECTOR] Federal Scout failed: {e}")

    return results


def synthesize_report(agent_results: dict, api_status: dict) -> dict:
    client = anthropic.Anthropic(api_key=ANTH_KEY)
    today  = datetime.date.today().isoformat()

    # Load historical outputs for trend data
    hist_listings  = load_recent_output("listings")
    hist_scout     = load_recent_output("scout")
    hist_federal   = load_recent_output("federal")
    hist_content   = load_recent_output("content")

    context = {
        "date":           today,
        "agent_results":  agent_results,
        "api_status":     api_status,
        "historical": {
            "listing_runs":  len(hist_listings),
            "scout_runs":    len(hist_scout),
            "federal_runs":  len(hist_federal),
            "content_pages": len(hist_content),
        },
    }

    prompt = f"""You are the SML Campaign Director. Synthesize this week's marketing department outputs into an executive report.

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
    "api_engines_live": <from status>
  }},
  "wins_this_week": ["<concrete achievement>", ...],
  "top_actions_next_week": [
    {{"action": "...", "agent": "...", "priority": "HIGH|MEDIUM"}}
  ],
  "listings_to_submit": ["<platform>", ...],
  "top_community_threads": ["<url>", ...],
  "federal_opportunities": ["<title + agency>", ...],
  "health": "GREEN|YELLOW|RED"
}}"""

    resp = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    final_text = resp.content[0].text if resp.content else ""
    report = {"date": today, "raw": final_text}
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
    print(f"\n[DIRECTOR] Campaign report saved: {path}")

    slack_text = format_slack_report(report)
    print("\n" + "="*60)
    print(slack_text)
    print("="*60)
    post_slack(slack_text)

    return report


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
