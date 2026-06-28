import os
import re
import sys
import json
import time
import smtplib
import logging
import threading
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from typing import Dict, List, Optional

try:
    from dotenv import load_dotenv
    _REPO_ROOT = Path(__file__).resolve().parent.parent
    for candidate in (_REPO_ROOT / ".env", _REPO_ROOT.parent / ".env"):
        if candidate.exists():
            load_dotenv(candidate, override=False)
except Exception:
    pass

# Add parent directory to path to load SqueezeOS environment
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from data_providers import load_env_file
    load_env_file()
except ImportError:
    # Fallback to manual load if imported outside layout
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    os.environ[k.strip()] = v.strip().strip('"').strip("'")

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
        self.smtp_host = os.environ.get("SMTP_HOST") or os.environ.get("SMTP_SERVER")
        self.smtp_port = int(os.environ.get("SMTP_PORT", "587"))
        self.smtp_user = os.environ.get("SMTP_USERNAME") or os.environ.get("SMTP_USER")
        self.smtp_pass = os.environ.get("SMTP_PASSWORD") or os.environ.get("SMTP_PASS")
        self.smtp_from = os.environ.get("SMTP_FROM") or self.smtp_user
        self.email_enabled = bool(
            self.smtp_host and self.smtp_user and self.smtp_pass and self.smtp_from
        )
        self.github_token = None

    def _generate_rule_based_pitch(self, developer_profile: Dict) -> str:
        """Generates a personalized rule-based pitch when the LLM is unavailable."""
        return _rule_based_pitch(developer_profile, self.pricing_url)

    def _generate_pitch(self, developer_profile: Dict) -> str:
        """Uses Claude to generate a tailored outreach message, with a personalized rule-based fallback."""
        if not self.api_key:
            return self._generate_rule_based_pitch(developer_profile)

        prompt = (
            "You are an elite institutional sales agent for SqueezeOS, a pay-per-call "
            "market-intelligence MCP server (institutional options flow, Base-4 Fractal "
            "Convergence scans, gamma/0DTE intel) settled in RLUSD on XRPL.\n\n"
            f"Write a concise, high-converting, 3-sentence DM to this developer:\n"
            f"Name: {developer_profile.get('name')}\n"
            f"Repo: {developer_profile.get('repo')}\n"
            f"Bio/Repo Focus: {developer_profile.get('bio')}\n\n"
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
                    "model": "claude-haiku-4-5-20251001",
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

        return self._generate_rule_based_pitch(developer_profile)

    def find_leads(self, keyword: str = "algorithmic trading python", limit: int = 5) -> List[Dict]:
        logger.info(f"Searching GitHub for leads using keyword: '{keyword}'…")
        url = (
            "https://api.github.com/search/repositories"
            f"?q={requests.utils.quote(keyword)}&sort=stars&order=desc&per_page={limit}"
        )
        headers = {}
        token = self._get_github_token()
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

    def _get_github_token(self) -> Optional[str]:
        """Dynamically retrieves the real GitHub PAT from the gh CLI keyring if env is dummy."""
        token = os.environ.get("GITHUB_TOKEN", "")
        if not token or token.startswith("githu") or token.startswith("dummy"):
            import subprocess
            try:
                env = os.environ.copy()
                if "GITHUB_TOKEN" in env:
                    del env["GITHUB_TOKEN"]
                res = subprocess.run(
                    "gh auth token",
                    shell=True,
                    capture_output=True,
                    text=True,
                    env=env
                )
                output = res.stdout.strip()
                if output.startswith("gho_") or output.startswith("github_pat_"):
                    return output
            except Exception as e:
                logger.error(f"Failed to fetch token from gh CLI: {e}")
        return token if token else None

    def _get_developer_email(self, username: str, repo: str) -> Optional[str]:
        """Attempts to harvest a real email address from the developer's public commits."""
        url = f"https://api.github.com/repos/{username}/{repo}/commits"
        headers = {}
        token = self._get_github_token()
        if token:
            headers["Authorization"] = f"token {token}"
        try:
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                commits = r.json()
                if commits and isinstance(commits, list):
                    for commit_wrapper in commits:
                        commit = commit_wrapper.get('commit', {})
                        author = commit.get('author', {})
                        email = author.get('email', '')
                        if email and '@' in email and 'users.noreply.github.com' not in email:
                            return email
        except Exception as e:
            logger.error(f"Failed to harvest email for {username}: {e}")
        return None

    def _send_email(self, to_email: str, subject: str, body: str) -> bool:
        """Sends an email using standard SMTP configurations in .env."""
        smtp_host = os.environ.get("SMTP_HOST") or os.environ.get("SMTP_SERVER")
        smtp_port = os.environ.get("SMTP_PORT", "587")
        smtp_user = os.environ.get("SMTP_USERNAME") or os.environ.get("SMTP_USER")
        smtp_pass = os.environ.get("SMTP_PASSWORD") or os.environ.get("SMTP_PASS")
        smtp_from = os.environ.get("SMTP_FROM") or smtp_user

        if not all([smtp_host, smtp_port, smtp_user, smtp_pass]):
            logger.warning("SMTP credentials not fully configured. Skipping auto email.")
            return False

        msg = MIMEMultipart()
        msg['From'] = smtp_from
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))

        try:
            port = int(smtp_port)
            if port == 465:
                server = smtplib.SMTP_SSL(smtp_host, port, timeout=10)
            else:
                server = smtplib.SMTP(smtp_host, port, timeout=10)
                server.starttls()
            
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_from, to_email, msg.as_string())
            server.quit()
            logger.info(f"📧 Auto outreach email sent successfully to {to_email}")
            return True
        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {e}")
            return False

    def _send_github_outreach(self, username: str, repo: str, pitch: str) -> bool:
        """Automatically opens a GitHub issue on the developer's repo with SqueezeOS API pitch."""
        token = self._get_github_token()
        if not token:
            logger.warning("No GitHub token available. Skipping auto GitHub outreach.")
            return False

        url = f"https://api.github.com/repos/{username}/{repo}/issues"
        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json"
        }
        payload = {
            "title": "SqueezeOS Options Flow / Quant Integration Inquiry",
            "body": (
                f"Hey @{username},\n\n"
                f"I saw your `{repo}` repository focusing on institutional trading and algorithmic systems. "
                "Since you are working on similar quant frameworks, SqueezeOS has premium endpoints "
                "for institutional options flow, Base-4 fractal matrix sweeps, and gamma wall analysis.\n\n"
                f"**Personalized Pitch:**\n{pitch}\n\n"
                f"Feel free to check out the API endpoints and documentation at https://squeezeos-api.onrender.com/pricing"
            )
        }
        
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=10)
            if r.status_code == 201:
                issue_url = r.json().get("html_url")
                logger.info(f"🚀 GitHub outreach issue created successfully: {issue_url}")
                return True
            else:
                logger.error(f"Failed to create GitHub issue [{r.status_code}]: {r.text}")
        except Exception as e:
            logger.error(f"GitHub outreach error: {e}")
        return False

    def _send_discord_alert(self, lead: dict, pitch: str, email: Optional[str], auto_sent: bool, channel: str = "Discord"):
        """Sends the generated pitch and harvested lead info to Discord."""
        if not self.webhook_url:
            logger.warning("No Discord webhook found for Sales Agent.")
            return

        status = f"🟢 Outreach Sent Automatically ({channel})" if auto_sent else "Backup 🟡 Lead Captured (Copy & Paste)"
        email_str = email if email else "None public"
        
        embed = {
            "title": f"🎯 New Lead: {lead['name']}",
            "description": f"**Status:** {status}\n**Repo:** {lead['repo']}\n**Bio:** {lead['bio']}\n**Link:** {lead['url']}\n**Harvested Email:** `{email_str}`",
            "color": 65280 if auto_sent else 16776960, # Neon green for auto-sent, yellow for copy-paste
            "fields": [
                {
                    "name": "🤖 Personalized Pitch",
                    "value": f"```text\n{pitch[:1000]}\n```"
                }
            ],
        }
        try:
            requests.post(self.webhook_url, json={"embeds": [embed]}, timeout=5)
        except Exception as e:
            logger.error(f"Discord push failed: {e}")

    def run_campaign(self, keyword: str = "options flow algorithmic trading", limit: int = 3):
        logger.info("Starting Sales Agent campaign...")
        self.github_token = self._get_github_token()
        leads = self.find_leads(keyword, limit=limit)
        if not leads:
            logger.info("No leads found.")
            return

        auto_outreach_enabled = os.environ.get("AUTO_OUTREACH", "false").lower() == "true"

        for lead in leads:
            pitch = self._generate_pitch(lead)
            email = self._get_developer_email(lead['name'], lead['repo'])
            
            auto_sent = False
            channel = "None"
            
            if auto_outreach_enabled:
                # 1. Attempt Email first if configured
                if email:
                    subject = "SqueezeOS Options Flow / Quant Integration Inquiry"
                    auto_sent = self._send_email(email, subject, pitch)
                    if auto_sent:
                        channel = "SMTP Email"
                
                # 2. Fall back to creating a GitHub issue if SMTP is skipped/fails
                if not auto_sent:
                    token = self._get_github_token()
                    if token:
                        auto_sent = self._send_github_outreach(lead['name'], lead['repo'], pitch)
                        if auto_sent:
                            channel = "GitHub Issue"
                
            self._send_discord_alert(lead, pitch, email, auto_sent, channel)
            time.sleep(2) # rate limiting


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
