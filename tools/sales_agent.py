import os
import re
import json
import time
import smtplib
import logging
import threading
from email.message import EmailMessage
from pathlib import Path
from typing import Dict, List, Optional

import requests

try:
    from dotenv import load_dotenv
    _REPO_ROOT = Path(__file__).resolve().parent.parent
    for candidate in (_REPO_ROOT / ".env", _REPO_ROOT.parent / ".env"):
        if candidate.exists():
            load_dotenv(candidate, override=False)
except Exception:
    pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
logger = logging.getLogger("SalesAgent")


_PITCH_RULES = [
    (
        ("option", "gamma", "vega", "theta", "iv ", "implied vol", "0dte", "spx", "iwm"),
        "I noticed {focus} in your work — SqueezeOS exposes institutional gamma-flow and "
        "0DTE scoring (IWM contract scorer, full options sweep detection) over an MCP "
        "endpoint. No subscriptions, you pay per call in RLUSD on XRPL.",
    ),
    (
        ("hft", "low latency", "low-latency", "microsecond", "nanosecond", "perf", "latency"),
        "Saw {focus} in your stack — Engine 7 (Parabolic Flight Path) runs sub-millisecond "
        "on a live Coinbase feed (measured, not theoretical). MCP endpoint, pay-per-call, "
        "no auth handshake to amortize.",
    ),
    (
        ("fractal", "geometric", "base-4", "ema", "matrix", "convergence"),
        "Your {focus} angle lines up with what we run — Base-4 Fractal Convergence "
        "(Engine 6) feeding a recurrent depth transformer over a Neo4j market graph. "
        "Single MCP call returns ranked candidates with the geometric scaffolding intact.",
    ),
    (
        ("backtest", "research", "quant", "alpha", "signal"),
        "Your {focus} workflow is exactly the target — SqueezeOS streams live council "
        "verdicts (multi-engine ensemble) and a ring-buffer of recent signals, so you "
        "skip the broker-API plumbing and go straight to alpha evaluation.",
    ),
    (
        ("ml", "deep", "transformer", "neural", "rnn", "lstm"),
        "If you're doing {focus} on market data, the Recurrent Depth Transformer on top "
        "of our Neo4j MarketGraph might save you a feature pipeline — it returns "
        "process-grouped signals with relevance scores out of the box.",
    ),
    (
        ("crypto", "btc", "eth", "xrpl", "xrp", "defi", "memecoin"),
        "Given your {focus} background — payments are settled on XRP Ledger in RLUSD "
        "(no card flows, no KYC drag on agents). The same MCP surface serves equities "
        "and options intel, useful for cross-asset arbitrage research.",
    ),
    (
        ("agent", "autonomous", "llm", "mcp", "claude", "gpt"),
        "You're already on {focus} — SqueezeOS is shipped as a native MCP server (33 "
        "tools, JSON-RPC 2.0). Drop the URL into your client config and your agent "
        "can self-pay for premium calls via x402 invoices.",
    ),
]

_FALLBACK_BODY = (
    "SqueezeOS is a pay-per-call market intelligence MCP server — institutional "
    "options flow, gamma-walls, and Base-4 Fractal Convergence scans, settled in "
    "RLUSD on XRPL. No subscriptions, no API keys."
)


def _extract_focus(profile: Dict) -> Optional[str]:
    """Return a short noun phrase plucked from name/repo/bio, or None."""
    bio = (profile.get("bio") or "").strip()
    repo = (profile.get("repo") or "").replace("-", " ").replace("_", " ").strip()
    if bio:
        first = re.split(r"[.!?\n]", bio, maxsplit=1)[0].strip()
        if 6 <= len(first) <= 120:
            return first
    if repo:
        return repo
    return None


def _rule_based_pitch(profile: Dict, pricing_url: str) -> str:
    """Deterministic, personalized fallback when no LLM is available."""
    name = profile.get("name") or "there"
    haystack = " ".join(
        str(profile.get(k) or "") for k in ("name", "repo", "bio")
    ).lower()

    chosen_body = None
    matched_keyword = None
    for keywords, template in _PITCH_RULES:
        for kw in keywords:
            if kw in haystack:
                matched_keyword = kw.strip()
                focus = _extract_focus(profile) or matched_keyword
                chosen_body = template.format(focus=focus)
                break
        if chosen_body:
            break

    if not chosen_body:
        focus = _extract_focus(profile)
        if focus:
            chosen_body = f"Saw your work on {focus}. {_FALLBACK_BODY}"
        else:
            chosen_body = _FALLBACK_BODY

    return (
        f"Hey {name},\n\n"
        f"{chosen_body}\n\n"
        f"Pricing + endpoints: {pricing_url}\n"
        f"— SqueezeOS"
    )


class SqueezeOSSalesAgent:
    """
    Automated outreach agent. Generates personalized pitches (LLM if available,
    deterministic rule-based fallback otherwise) and pushes to Discord and/or
    SMTP email.
    """

    def __init__(self):
        self.api_key = os.environ.get("ANTHROPIC_API_KEY")
        self.pricing_url = os.environ.get(
            "SQUEEZEOS_PRICING_URL",
            "https://squeezeos-api.onrender.com/pricing",
        )
        self.github_url = "https://github.com/Timwal78/SqueezeOS"
        self.webhook_url = (
            os.environ.get("DISCORD_WEBHOOK_ALL")
            or os.environ.get("DISCORD_WEBHOOK_PAYMENTS")
        )
        self.smtp_host = os.environ.get("SMTP_HOST")
        self.smtp_port = int(os.environ.get("SMTP_PORT", "587"))
        self.smtp_user = os.environ.get("SMTP_USERNAME")
        self.smtp_pass = os.environ.get("SMTP_PASSWORD")
        self.smtp_from = os.environ.get("SMTP_FROM") or self.smtp_user
        self.email_enabled = bool(
            self.smtp_host and self.smtp_user and self.smtp_pass and self.smtp_from
        )

    def _generate_pitch(self, profile: Dict) -> str:
        """Use Claude when available; deterministic fallback otherwise."""
        if not self.api_key:
            return _rule_based_pitch(profile, self.pricing_url)

        prompt = (
            "You are an elite institutional sales agent for SqueezeOS, a pay-per-call "
            "market-intelligence MCP server (institutional options flow, Base-4 Fractal "
            "Convergence scans, gamma/0DTE intel) settled in RLUSD on XRPL.\n\n"
            f"Write a concise, high-converting, 3-sentence DM to this developer:\n"
            f"Name: {profile.get('name')}\n"
            f"Repo: {profile.get('repo')}\n"
            f"Bio/Repo Focus: {profile.get('bio')}\n\n"
            "Quant-to-quant tone. No marketing fluff. "
            f"End with a call to action pointing to {self.pricing_url}"
        )

        try:
            resp = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-3-haiku-20240307",
                    "max_tokens": 220,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=15,
            )
            data = resp.json()
            content = data.get("content") or []
            if content and isinstance(content, list):
                text = content[0].get("text", "").strip()
                if text:
                    return text
            logger.warning(f"LLM returned no content: {data}")
        except Exception as e:
            logger.error(f"LLM error, falling back to rule-based pitch: {e}")

        return _rule_based_pitch(profile, self.pricing_url)

    def find_leads(self, keyword: str = "algorithmic trading python", limit: int = 5) -> List[Dict]:
        logger.info(f"Searching GitHub for leads using keyword: '{keyword}'…")
        url = (
            "https://api.github.com/search/repositories"
            f"?q={requests.utils.quote(keyword)}&sort=stars&order=desc&per_page={limit}"
        )
        headers = {}
        token = os.environ.get("GITHUB_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"

        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            logger.warning(f"GitHub search failed: {resp.status_code} {resp.text[:200]}")
            return []

        leads: List[Dict] = []
        for repo in resp.json().get("items", []):
            owner = repo.get("owner", {}) or {}
            leads.append(
                {
                    "name": owner.get("login"),
                    "login": owner.get("login"),
                    "repo": repo.get("name"),
                    "bio": repo.get("description"),
                    "url": owner.get("html_url"),
                    "owner_api_url": owner.get("url"),
                }
            )
        return leads

    def _resolve_email(self, lead: Dict) -> Optional[str]:
        """Resolve the lead's public email via GitHub profile, if any."""
        api_url = lead.get("owner_api_url")
        if not api_url:
            return None
        try:
            headers = {}
            token = os.environ.get("GITHUB_TOKEN")
            if token:
                headers["Authorization"] = f"Bearer {token}"
            r = requests.get(api_url, headers=headers, timeout=8)
            if r.status_code != 200:
                return None
            data = r.json() or {}
            email = (data.get("email") or "").strip()
            return email or None
        except Exception as e:
            logger.warning(f"email lookup failed for {lead.get('login')}: {e}")
            return None

    def _send_discord_alert(self, lead: Dict, pitch: str, sent_email: Optional[str]):
        if not self.webhook_url:
            return
        embed = {
            "title": f"New Lead: {lead.get('name')}",
            "description": (
                f"**Repo:** {lead.get('repo')}\n"
                f"**Bio:** {lead.get('bio')}\n"
                f"**Link:** {lead.get('url')}\n"
                f"**Auto-emailed:** {sent_email or 'no public email'}"
            ),
            "color": 65280,
            "fields": [
                {
                    "name": "Generated pitch",
                    "value": f"```text\n{pitch[:1000]}\n```",
                }
            ],
        }
        try:
            requests.post(self.webhook_url, json={"embeds": [embed]}, timeout=5)
        except Exception as e:
            logger.error(f"Discord push failed: {e}")

    def _send_email(self, to_addr: str, lead: Dict, pitch: str) -> bool:
        if not self.email_enabled:
            return False
        msg = EmailMessage()
        repo = lead.get("repo") or "your work"
        msg["Subject"] = f"Re: {repo} — quick note from a quant"
        msg["From"] = self.smtp_from
        msg["To"] = to_addr
        msg.set_content(pitch)
        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=20) as s:
                s.ehlo()
                s.starttls()
                s.login(self.smtp_user, self.smtp_pass)
                s.send_message(msg)
            logger.info(f"Email sent to {to_addr} for {lead.get('login')}")
            return True
        except Exception as e:
            logger.error(f"SMTP send failed for {to_addr}: {e}")
            return False

    def run_campaign(self, keyword: str = "options flow algorithmic trading", limit: int = 3):
        logger.info("Starting Sales Agent campaign…")
        leads = self.find_leads(keyword, limit=limit)
        if not leads:
            logger.info("No leads found.")
            return

        for lead in leads:
            pitch = self._generate_pitch(lead)
            sent_to = None
            email = self._resolve_email(lead)
            if email and self.email_enabled:
                if self._send_email(email, lead, pitch):
                    sent_to = email
            self._send_discord_alert(lead, pitch, sent_to)
            time.sleep(2)


def _daemon_loop():
    agent = SqueezeOSSalesAgent()
    time.sleep(60)
    while True:
        try:
            agent.run_campaign()
        except Exception as e:
            logger.error(f"Sales Agent crashed: {e}")
        time.sleep(86400)


def start_sales_agent():
    t = threading.Thread(target=_daemon_loop, daemon=True, name="sales-agent-daemon")
    t.start()
    logger.info("Autonomous Sales Agent daemon started in background.")


if __name__ == "__main__":
    SqueezeOSSalesAgent().run_campaign()
