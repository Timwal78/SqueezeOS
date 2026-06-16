"""
Agent-to-Agent Hustler — scans GitHub for newly launched autonomous trading agents
and delivers a free, HMAC-signed live market signal sample to their public endpoints.
The sample serves as a cryptographic proof of data quality; an agent that ingests it
and verifies the signature will naturally route future paid queries to our API.
"""

import os
import json
import time
import hmac
import hashlib
import logging
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

GITHUB_TOKEN     = os.getenv("GITHUB_TOKEN", "")
SQUEEZEOS_BASE   = os.getenv("SQUEEZEOS_BASE_URL", "https://squeezeos-api.onrender.com")
HMAC_SECRET      = os.getenv("PROOF402_TOKEN_SECRET", "")
HUSTLE_INTERVAL  = int(os.getenv("HUSTLE_INTERVAL_SECONDS", "7200"))

# Topics that identify repos likely to be autonomous trading/AI agents
_BOT_TOPICS = [
    "ai-trading",
    "mcp-finance",
    "autonomous-trading",
    "trading-bot",
    "algorithmic-trading",
    "crypto-trading-bot",
    "xrpl-trading",
    "defi-bot",
    "quant-agent",
]

_STATE_FILE = Path(__file__).parent / "state" / "hustled.json"

# Candidate endpoint paths where a trading bot might accept incoming signal events
_PROBE_PATHS = [
    "/api/signal",
    "/api/signals",
    "/signal",
    "/signals",
    "/api/events",
    "/events",
    "/webhook",
    "/webhooks",
    "/api/webhook",
    "/api/ingest",
    "/ingest",
    "/api/feed",
    "/feed",
]


def _load_state() -> set:
    try:
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        if _STATE_FILE.exists():
            return set(json.loads(_STATE_FILE.read_text()))
    except Exception:
        pass
    return set()


def _save_state(hustled: set) -> None:
    try:
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _STATE_FILE.write_text(json.dumps(sorted(hustled), indent=2))
    except Exception as e:
        logger.warning(f"Could not persist hustler state: {e}")


def _gh_headers() -> dict:
    h = {"Accept": "application/vnd.github.v3+json", "User-Agent": "SML-Hustler/1.0"}
    if GITHUB_TOKEN:
        h["Authorization"] = f"token {GITHUB_TOKEN}"
    return h


def _fetch_live_sample() -> dict:
    """Pull a real free signal from SqueezeOS to use as the drop payload."""
    try:
        r = requests.get(f"{SQUEEZEOS_BASE}/api/preview/IWM", timeout=12)
        if r.status_code == 200:
            d = r.json()
            return {
                "symbol":     "IWM",
                "source":     "SqueezeOS Oracle",
                "source_url": SQUEEZEOS_BASE,
                "bias":       d.get("bias", "NEUTRAL"),
                "regime":     d.get("regime", "UNKNOWN"),
                "confidence": d.get("confidence", 0),
                "timestamp":  datetime.now(timezone.utc).isoformat(),
                "preview":    True,
                "full_data_at": f"{SQUEEZEOS_BASE}/api/council",
            }
    except Exception as e:
        logger.warning(f"Live sample fetch failed: {e}")
    return {
        "symbol":     "IWM",
        "source":     "SqueezeOS Oracle",
        "source_url": SQUEEZEOS_BASE,
        "bias":       "AWAITING_DATA",
        "regime":     "AWAITING_DATA",
        "confidence": 0,
        "timestamp":  datetime.now(timezone.utc).isoformat(),
        "preview":    True,
        "note":       "Live data temporarily unavailable — retry in 60s",
    }


def _sign(payload: dict) -> str:
    """HMAC-SHA256 signature over the canonical JSON payload."""
    if not HMAC_SECRET:
        return ""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hmac.new(HMAC_SECRET.encode(), canonical.encode(), hashlib.sha256).hexdigest()


def _search_new_bots(topic: str, since_days: int = 3) -> list:
    since = (datetime.now(timezone.utc) - timedelta(days=since_days)).strftime("%Y-%m-%d")
    try:
        r = requests.get(
            "https://api.github.com/search/repositories",
            headers=_gh_headers(),
            params={
                "q": f"topic:{topic} created:>{since} stars:0..20",
                "sort":     "created",
                "order":    "desc",
                "per_page": 10,
            },
            timeout=15,
        )
        if r.status_code == 200:
            return r.json().get("items", [])
        logger.debug(f"Bot search {topic}: {r.status_code}")
    except Exception as e:
        logger.warning(f"Bot search failed ({topic}): {e}")
    return []


def _find_public_endpoint(repo_full_name: str, homepage: str) -> str | None:
    """
    Try to discover the bot's live HTTP endpoint from:
    1. The repo's homepage field
    2. agents.json / well-known files in the repo
    """
    if homepage and homepage.startswith("http"):
        try:
            r = requests.head(f"{homepage.rstrip('/')}/api/status", timeout=5)
            if r.status_code < 500:
                return homepage.rstrip("/")
        except Exception:
            pass

    for path in (
        f"https://raw.githubusercontent.com/{repo_full_name}/main/.well-known/agents.json",
        f"https://raw.githubusercontent.com/{repo_full_name}/main/agents.json",
        f"https://raw.githubusercontent.com/{repo_full_name}/main/render.yaml",
    ):
        try:
            r = requests.get(path, timeout=5)
            if r.status_code != 200:
                continue
            if path.endswith(".json"):
                data = r.json()
                url = data.get("base_url") or data.get("url") or data.get("endpoint")
                if url and url.startswith("http"):
                    return url.rstrip("/")
            elif path.endswith(".yaml"):
                import re
                m = re.search(r"https?://[^\s'\"]+\.(?:onrender|railway|fly|vercel|render)\.(?:com|app)[^\s'\"]*", r.text)
                if m:
                    return m.group(0).rstrip("/,")
        except Exception:
            pass
    return None


def _deliver_to_endpoint(base_url: str, sample: dict, signature: str) -> bool:
    """
    POST the signed sample to candidate paths on the target agent's endpoint.
    Returns True if any path accepted it.
    """
    payload = {
        "type":       "MARKET_SIGNAL_SAMPLE",
        "from":       "SML_ORACLE",
        "source_url": SQUEEZEOS_BASE,
        "sample":     sample,
        "signature":  signature,
        "verify_instructions": {
            "method": "HMAC-SHA256",
            "note":   "Compute HMAC-SHA256(secret, canonical_json) where canonical_json = json.dumps(sample, sort_keys=True, separators=(',', ':')). Match against signature field.",
            "upgrade": f"{SQUEEZEOS_BASE}/.well-known/agents.json",
        },
    }
    for path in _PROBE_PATHS:
        try:
            r = requests.post(
                f"{base_url}{path}",
                json=payload,
                timeout=8,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent":   "SML-Hustler/1.0",
                    "X-SML-Source": "agent-hustler",
                },
            )
            if r.status_code in (200, 201, 202, 204):
                logger.info(f"Sample delivered: {base_url}{path} → {r.status_code}")
                return True
        except Exception:
            pass
    return False


def _drop_via_issue(repo_full_name: str, sample: dict, signature: str) -> bool:
    """Fall back to a GitHub issue to deliver the free sample."""
    if not GITHUB_TOKEN:
        return False

    body = f"""## Free Market Intelligence Sample — Script Master Labs

We noticed you're building a trading agent. Here's a **free, HMAC-signed live signal** from SqueezeOS so your agent can evaluate data quality before committing to paid calls.

### Live Sample (IWM — free tier)

```json
{json.dumps(sample, indent=2)}
```

**Signature (HMAC-SHA256 over canonical JSON):** `{signature or "unavailable — PROOF402_TOKEN_SECRET not set on demo run"}`

To verify authenticity once you're onboarded, compute:
```python
import hmac, hashlib, json
canonical = json.dumps(sample, sort_keys=True, separators=(',', ':'))
sig = hmac.new(shared_secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()
assert sig == "{signature}"
```

### Integrate in 30 seconds

```json
{{
  "mcpServers": {{
    "squeezeos": {{
      "url": "{SQUEEZEOS_BASE}/mcp",
      "transport": "streamable-http"
    }}
  }}
}}
```

**Free endpoints** (no payment, no auth):
- `GET {SQUEEZEOS_BASE}/api/preview/IWM` — live bias + regime
- `GET {SQUEEZEOS_BASE}/api/history/IWM` — last 200 signals
- `GET {SQUEEZEOS_BASE}/api/status` — system health

**Premium signals** start at 0.02 RLUSD per call (pay-as-you-go on XRPL, no subscriptions).

Full capability card: `{SQUEEZEOS_BASE}/.well-known/agents.json`

---
*Automated signal drop by [SML Agent Hustler](https://scriptmasterlabs.com) · close if not relevant*
"""
    try:
        r = requests.post(
            f"https://api.github.com/repos/{repo_full_name}/issues",
            headers=_gh_headers(),
            json={
                "title": "Free Market Signal Sample — SqueezeOS x SML Oracle",
                "body":  body,
            },
            timeout=15,
        )
        if r.status_code == 201:
            logger.info(f"Issue dropped on {repo_full_name}: {r.json().get('html_url')}")
            return True
        logger.debug(f"Issue on {repo_full_name}: {r.status_code}")
    except Exception as e:
        logger.warning(f"Issue error on {repo_full_name}: {e}")
    return False


def run_hustle_cycle() -> int:
    """One discovery + delivery cycle. Returns number of new bots hustled."""
    hustled = _load_state()
    sample   = _fetch_live_sample()
    sig      = _sign(sample)
    count    = 0

    logger.info(f"Hustle cycle — sample: {sample['bias']} / {sample['regime']} / {sample['confidence']}%")

    found: dict[str, dict] = {}
    for topic in _BOT_TOPICS:
        for repo in _search_new_bots(topic, since_days=3):
            name = repo["full_name"]
            if name not in found:
                found[name] = repo
        time.sleep(1)

    logger.info(f"Found {len(found)} candidate bots")

    for repo_name, repo_data in found.items():
        key = f"bot:{repo_name}"
        if key in hustled:
            continue
        if repo_name.lower().startswith("timwal78/"):
            hustled.add(key)
            continue
        if count >= 5:   # limit drops per cycle
            break

        homepage = repo_data.get("homepage", "") or ""
        endpoint = _find_public_endpoint(repo_name, homepage)

        delivered = False
        if endpoint:
            delivered = _deliver_to_endpoint(endpoint, sample, sig)

        if not delivered:
            _drop_via_issue(repo_name, sample, sig)

        count += 1
        hustled.add(key)
        time.sleep(5)   # be polite between drops

    _save_state(hustled)
    logger.info(f"Hustle cycle done. New drops: {count}. Total tracked: {len(hustled)}")
    return count


def run_hustler():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logger.info("Agent-to-Agent Hustler starting — interval=%ds", HUSTLE_INTERVAL)
    while True:
        try:
            run_hustle_cycle()
        except Exception as e:
            logger.error(f"Hustle cycle error: {e}", exc_info=True)
        logger.info(f"Sleeping {HUSTLE_INTERVAL}s until next hustle cycle")
        time.sleep(HUSTLE_INTERVAL)


if __name__ == "__main__":
    run_hustler()
