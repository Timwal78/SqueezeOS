"""
Agent Interceptor — after_request hook that detects AI agent User-Agents and
injects discovery headers into every response. When an agent's first request
lands on any endpoint, we force-advertise our capability card via Link headers
and X-SML-* metadata so the agent knows premium financial data is available
and where to find it.

This runs as a lightweight after_request hook — zero I/O, sub-millisecond.
"""

import os
import re
import time
import threading
from flask import request

_SQUEEZEOS_BASE = os.getenv("SQUEEZEOS_BASE_URL", "https://squeezeos-api.onrender.com")

# User-agent patterns that identify autonomous AI agents
_AI_AGENT_RE = re.compile(
    r"(claude|anthropic|gpt|openai|gemini|google-extended|perplexity|"
    r"cohere|mistral|llama|grok|copilot|mcp-client|python-httpx|python-requests|"
    r"langchain|autogen|crewai|agentops|smolagents|pydantic-ai|"
    r"bytespider|claudebot|gptbot|anthropic-bot)",
    re.IGNORECASE,
)

# Discovery headers injected on every AI agent response
_DISCOVERY_HEADERS = {
    "X-SML-Discovery":    f"{_SQUEEZEOS_BASE}/.well-known/agents.json",
    "X-SML-MCP":          f"{_SQUEEZEOS_BASE}/mcp",
    "X-SML-Free-Preview": f"{_SQUEEZEOS_BASE}/api/preview/IWM",
    "X-SML-Payment":      "x402; currency=RLUSD; network=XRPL; invoice=https://four02proof.onrender.com/v1/invoice",
    "Link": (
        f'<{_SQUEEZEOS_BASE}/.well-known/agents.json>; rel="agent-discovery", '
        f'<{_SQUEEZEOS_BASE}/.well-known/mcp.json>; rel="mcp-server", '
        f'<{_SQUEEZEOS_BASE}/llms.txt>; rel="llms-txt"'
    ),
}

# Ring buffer tracking first-seen agents (IP + UA hash) to emit a richer
# AGENT_FIRST_CONTACT SSE event on their initial request.
_SEEN_LOCK  = threading.Lock()
_SEEN: set  = set()
_SEEN_MAX   = 5000


def _is_ai_agent(ua: str) -> bool:
    return bool(ua and _AI_AGENT_RE.search(ua))


def _ua_key(ua: str, ip: str) -> str:
    import hashlib
    return hashlib.sha1(f"{ua}:{ip}".encode(), usedforsecurity=False).hexdigest()[:16]


def add_discovery_headers(response):
    """
    after_request hook. Injects X-SML-* discovery headers on AI agent responses.
    On a first-contact from a new agent, also fires an SSE event so the operator
    dashboard shows the probe in real time.
    """
    ua = request.headers.get("User-Agent", "")
    if not _is_ai_agent(ua):
        return response

    for key, val in _DISCOVERY_HEADERS.items():
        response.headers[key] = val

    ip  = request.remote_addr or ""
    key = _ua_key(ua, ip)

    first_contact = False
    with _SEEN_LOCK:
        if key not in _SEEN:
            _SEEN.add(key)
            first_contact = True
            if len(_SEEN) > _SEEN_MAX:
                # Evict oldest 20 % when the set grows too large
                to_remove = list(_SEEN)[: _SEEN_MAX // 5]
                for k in to_remove:
                    _SEEN.discard(k)

    if first_contact:
        _broadcast_first_contact(ua, ip, request.path)

    return response


def _broadcast_first_contact(ua: str, ip: str, path: str):
    """Fire an SSE AGENT_FIRST_CONTACT event — non-blocking daemon thread."""
    def _do():
        try:
            from core.state import state
            state.push_terminal(
                "AGENT_FIRST_CONTACT",
                f"New agent probe: {ua[:80]} @ {path}",
                symbol=None,
                score=None,
                extra={"ua": ua, "ip": ip, "path": path, "ts": time.time()},
            )
        except Exception:
            pass
    threading.Thread(target=_do, daemon=True).start()
