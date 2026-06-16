"""
Registry Broadcaster — continuously monitors GitHub for new AI registries,
agent directories, and llms.txt aggregators, then auto-submits SqueezeOS
capability cards. Runs as a Render worker service.
"""

import os
import json
import time
import logging
import hashlib
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

GITHUB_TOKEN      = os.getenv("GITHUB_TOKEN", "")
SQUEEZEOS_BASE    = os.getenv("SQUEEZEOS_BASE_URL", "https://squeezeos-api.onrender.com")
BROADCAST_INTERVAL = int(os.getenv("BROADCAST_INTERVAL_SECONDS", "3600"))

# Topics that indicate a repo is a registry/directory that wants submissions
_REGISTRY_TOPICS = [
    "mcp-registry",
    "mcp-server-list",
    "agent-directory",
    "agent-registry",
    "llms-txt-directory",
    "ai-agent-hub",
    "mcp-hub",
    "agent-network",
]

# Known registries that explicitly accept server submissions via issues/PRs.
# Each entry is tried once, then persisted to avoid re-spamming.
_KNOWN_REGISTRIES = [
    {
        "id":   "punkpeye/awesome-mcp-servers",
        "type": "github_issue",
        "title": "Add: SqueezeOS — Institutional Market Intelligence MCP Server",
    },
    {
        "id":   "modelcontextprotocol/servers",
        "type": "github_issue",
        "title": "Add SqueezeOS to MCP server list",
    },
    {
        "id":   "appcypher/awesome-mcp-servers",
        "type": "github_issue",
        "title": "Add SqueezeOS — pay-per-call market intelligence MCP server",
    },
]

_STATE_FILE = Path(__file__).parent / "state" / "submitted.json"


def _load_state() -> set:
    try:
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        if _STATE_FILE.exists():
            return set(json.loads(_STATE_FILE.read_text()))
    except Exception:
        pass
    return set()


def _save_state(submitted: set) -> None:
    try:
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _STATE_FILE.write_text(json.dumps(sorted(submitted), indent=2))
    except Exception as e:
        logger.warning(f"Could not persist broadcaster state: {e}")


def _gh_headers() -> dict:
    h = {"Accept": "application/vnd.github.v3+json", "User-Agent": "SML-Broadcaster/1.0"}
    if GITHUB_TOKEN:
        h["Authorization"] = f"token {GITHUB_TOKEN}"
    return h


def _capability_card() -> dict:
    return {
        "name":        "SqueezeOS — Market Intelligence by Script Master Labs",
        "version":     "5.0.0",
        "description": (
            "Institutional-grade AI market intelligence exposed as an MCP server. "
            "Squeeze scanner, options flow, AI council verdicts, IWM 0DTE scoring. "
            "Pay-per-call via RLUSD on XRPL. No subscriptions, no API keys."
        ),
        "url":          SQUEEZEOS_BASE,
        "mcp_endpoint": f"{SQUEEZEOS_BASE}/mcp",
        "transport":    "streamable-http",
        "protocol":     "2024-11-05",
        "discovery": {
            "agents_json": f"{SQUEEZEOS_BASE}/.well-known/agents.json",
            "mcp_json":    f"{SQUEEZEOS_BASE}/.well-known/mcp.json",
            "openapi":     f"{SQUEEZEOS_BASE}/.well-known/openapi.json",
            "llms_txt":    f"{SQUEEZEOS_BASE}/llms.txt",
            "server_json": f"{SQUEEZEOS_BASE}/.well-known/server.json",
        },
        "payment": {
            "protocol": "x402",
            "currency": "RLUSD",
            "network":  "XRPL",
            "invoice":  "https://four02proof.onrender.com/v1/invoice",
        },
        "free_tools":  ["get_signal_preview", "get_signal_history", "get_market_status", "sse_stream"],
        "paid_tools":  ["council_verdict", "market_scan", "options_intelligence", "iwm_odte_score"],
        "categories":  ["finance", "trading", "market-intelligence"],
        "tags":        ["squeeze", "options-flow", "RLUSD", "XRPL", "x402"],
        "repository":  "https://github.com/timwal78/squeezeos",
        "submitted_at": datetime.now(timezone.utc).isoformat(),
    }


def _issue_body(card: dict) -> str:
    return f"""## Add SqueezeOS — Institutional Market Intelligence MCP Server

**MCP Endpoint:** `{card["mcp_endpoint"]}`
**Transport:** streamable-HTTP (MCP protocol `{card["protocol"]}`)
**Payment:** x402/RLUSD on XRPL — pay-per-call, no subscriptions, no API keys

### What it does

SqueezeOS is an institutional-grade AI trading intelligence platform exposed natively as an MCP server. Agents pay RLUSD on the XRP Ledger and receive a signed JWT granting access. Zero custody, zero KYC.

**Free tools (no payment required):**
- `get_signal_preview` — live bias + regime for any symbol (15-min cache)
- `get_signal_history` — last 200 signals per symbol, ring-buffered
- `get_market_status` — system health, active universe, uptime
- SSE stream — real-time `SQUEEZE_ALERT`, `COUNCIL_VERDICT`, `OPTIONS_SWEEP` events

**Premium tools (micropayments via RLUSD):**
- `council_verdict` — multi-engine AI verdict for any symbol (0.10 RLUSD)
- `market_scan` — full $1–$50 squeeze scanner (0.05 RLUSD)
- `options_intelligence` — institutional options flow (0.05 RLUSD)
- `iwm_odte_score` — IWM 0DTE contract scorer (0.03 RLUSD)

**MCP client config:**
```json
{{
  "mcpServers": {{
    "squeezeos": {{
      "url": "{card["mcp_endpoint"]}",
      "transport": "streamable-http"
    }}
  }}
}}
```

**Discovery:**
- `agents.json`: {card["discovery"]["agents_json"]}
- `mcp.json`:    {card["discovery"]["mcp_json"]}
- `llms.txt`:    {card["discovery"]["llms_txt"]}

**Repository:** {card["repository"]}

---
*Auto-submitted by SML Registry Broadcaster · {card["submitted_at"]}*
"""


def _search_github(topic: str, since_days: int = 7) -> list:
    since = (datetime.now(timezone.utc) - timedelta(days=since_days)).strftime("%Y-%m-%d")
    try:
        resp = requests.get(
            "https://api.github.com/search/repositories",
            headers=_gh_headers(),
            params={"q": f"topic:{topic} created:>{since}", "sort": "created", "order": "desc", "per_page": 10},
            timeout=15,
        )
        if resp.status_code == 200:
            return resp.json().get("items", [])
        logger.debug(f"GitHub search {topic}: {resp.status_code}")
    except Exception as e:
        logger.warning(f"GitHub search failed ({topic}): {e}")
    return []


def _try_api_submission(homepage: str, card: dict) -> bool:
    """Try to POST the capability card to a registry's submission API."""
    for path in ("/api/submit", "/api/servers", "/submit", "/register"):
        try:
            r = requests.post(
                f"{homepage.rstrip('/')}{path}",
                json=card,
                timeout=8,
                headers={"Content-Type": "application/json", "User-Agent": "SML-Broadcaster/1.0"},
            )
            if r.status_code in (200, 201, 202):
                logger.info(f"API submission accepted: {homepage}{path} → {r.status_code}")
                return True
        except Exception:
            pass
    return False


def _open_issue(repo: str, title: str, body: str) -> bool:
    if not GITHUB_TOKEN:
        logger.debug(f"Skipping issue on {repo}: no GITHUB_TOKEN")
        return False
    try:
        r = requests.post(
            f"https://api.github.com/repos/{repo}/issues",
            headers=_gh_headers(),
            json={"title": title, "body": body},
            timeout=15,
        )
        if r.status_code == 201:
            logger.info(f"Issue opened on {repo}: {r.json().get('html_url')}")
            return True
        # 410 = gone, 404 = not found, 403 = forbidden — log and skip
        logger.debug(f"Issue on {repo}: {r.status_code}")
    except Exception as e:
        logger.warning(f"Issue error on {repo}: {e}")
    return False


def run_broadcast_cycle() -> int:
    """One discovery + submission cycle. Returns number of new submissions made."""
    submitted = _load_state()
    card      = _capability_card()
    body      = _issue_body(card)
    count     = 0

    # ── 1. Hit known stable registries (once each) ────────────────────────────
    for target in _KNOWN_REGISTRIES:
        key = f"known:{target['id']}"
        if key in submitted:
            continue
        if target["type"] == "github_issue":
            if _open_issue(target["id"], target["title"], body):
                count += 1
        submitted.add(key)
        time.sleep(2)

    # ── 2. Discover new registries via GitHub topic search ───────────────────
    found: dict[str, dict] = {}
    for topic in _REGISTRY_TOPICS:
        for repo in _search_github(topic, since_days=7):
            name = repo["full_name"]
            if name not in found:
                found[name] = repo
        time.sleep(1)   # respect GitHub rate limit

    logger.info(f"Discovered {len(found)} candidate repos this cycle")

    for repo_name, repo_data in found.items():
        key = f"repo:{repo_name}"
        if key in submitted:
            continue
        if repo_name.lower().startswith("timwal78/"):
            submitted.add(key)
            continue
        # Stop at 8 new submissions per cycle to stay well inside GitHub rate limits
        if count >= 8:
            break

        # Try API first (for repos that have a live submission endpoint)
        homepage = repo_data.get("homepage", "")
        submitted_ok = False
        if homepage and homepage.startswith("http"):
            submitted_ok = _try_api_submission(homepage, card)

        # Fall back to GitHub issue if the repo looks like a registry/directory
        if not submitted_ok:
            desc = (repo_data.get("description") or "").lower()
            is_directory = any(
                kw in desc
                for kw in ("registry", "directory", "list of", "awesome", "catalog", "hub")
            )
            if is_directory:
                title = "Add: SqueezeOS — Institutional Market Intelligence MCP Server"
                _open_issue(repo_name, title, body)
                count += 1

        submitted.add(key)
        time.sleep(3)

    _save_state(submitted)
    logger.info(f"Broadcast cycle done. New submissions: {count}. Total tracked: {len(submitted)}")
    return count


def run_broadcaster():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logger.info("Registry Broadcaster starting — interval=%ds", BROADCAST_INTERVAL)
    while True:
        try:
            run_broadcast_cycle()
        except Exception as e:
            logger.error(f"Broadcast cycle error: {e}", exc_info=True)
        logger.info(f"Sleeping {BROADCAST_INTERVAL}s until next broadcast cycle")
        time.sleep(BROADCAST_INTERVAL)


if __name__ == "__main__":
    run_broadcaster()
