"""
SqueezeOS Robinhood Trading MCP — Discovery Client
═══════════════════════════════════════════════════
Robinhood shipped an official "Trading MCP" for agentic trading
(announced alongside the Robinhood Chain mainnet launch, July 2026).
It is reachable, per Robinhood's own support docs, at:

    https://agent.robinhood.com/mcp/trading

That page (and /agentic-trading/) returned HTTP 403 to automated
fetches at the time this file was written, so the exact tool names
and JSON schemas below are UNVERIFIED — third-party blog posts quote
names like get_accounts / place_equity_order, but none of that has
been confirmed against Robinhood's own documentation or a live
tools/list response.

Per the operator's explicit instruction, this module does NOT hardcode
those unverified names as executable logic. Instead it does the one
thing that's actually trustworthy: ask the live MCP server what it
supports, via the protocol's own self-description (`initialize` then
`tools/list`), and report exactly what comes back. Nothing here places
an order, reads a position, or assumes any tool exists.

This file is intentionally NOT imported by core/app.py or by the live
tools/robinhood_executor_sml.py. It does nothing until someone runs it
directly, and even then it only runs if explicitly enabled.

Required to do anything at all:
  ROBINHOOD_MCP_ENABLED=true
  ROBINHOOD_MCP_URL      (defaults to https://agent.robinhood.com/mcp/trading)
  ROBINHOOD_MCP_TOKEN    OAuth bearer token from completing Robinhood's own
                         agent-connection flow. This module has no OAuth
                         flow of its own — Robinhood's login/consent screen
                         is not something a backend script can drive, so
                         that token has to be obtained interactively by the
                         account holder first.

Usage:
    python tools/robinhood_mcp_executor.py
"""

import json
import os
import sys
import urllib.request
import urllib.error

ROBINHOOD_MCP_ENABLED = os.environ.get("ROBINHOOD_MCP_ENABLED", "false").lower() == "true"
ROBINHOOD_MCP_URL = os.environ.get("ROBINHOOD_MCP_URL", "https://agent.robinhood.com/mcp/trading")
ROBINHOOD_MCP_TOKEN = os.environ.get("ROBINHOOD_MCP_TOKEN", "")


class DiscoveryError(Exception):
    pass


def _rpc(method: str, params: dict | None = None, req_id: int = 1) -> dict:
    """Raw JSON-RPC 2.0 call against the Robinhood Trading MCP endpoint."""
    payload = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        payload["params"] = params
    data = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if ROBINHOOD_MCP_TOKEN:
        headers["Authorization"] = f"Bearer {ROBINHOOD_MCP_TOKEN}"
    req = urllib.request.Request(ROBINHOOD_MCP_URL, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read()
    except urllib.error.HTTPError as e:
        raise DiscoveryError(f"HTTP {e.code} from {ROBINHOOD_MCP_URL}: {e.read()[:500]!r}") from e
    except urllib.error.URLError as e:
        raise DiscoveryError(f"Could not reach {ROBINHOOD_MCP_URL}: {e}") from e
    try:
        return json.loads(body)
    except json.JSONDecodeError as e:
        raise DiscoveryError(f"Non-JSON response from {ROBINHOOD_MCP_URL}: {body[:500]!r}") from e


def discover() -> dict:
    """
    Ask the live MCP server what it actually supports.
    Returns the raw initialize + tools/list responses, unmodified.
    Raises DiscoveryError with a clear reason if anything fails —
    including a 401/403, which is the expected result until
    ROBINHOOD_MCP_TOKEN holds a real token from Robinhood's own
    agent-connection flow.
    """
    init_resp = _rpc("initialize", {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "squeezeos-discovery", "version": "0.1.0"},
    }, req_id=1)
    if "error" in init_resp:
        raise DiscoveryError(f"initialize failed: {init_resp['error']}")

    tools_resp = _rpc("tools/list", {}, req_id=2)
    if "error" in tools_resp:
        raise DiscoveryError(f"tools/list failed: {tools_resp['error']}")

    return {"initialize": init_resp, "tools_list": tools_resp}


def main():
    if not ROBINHOOD_MCP_ENABLED:
        print("[robinhood-mcp-discovery] ROBINHOOD_MCP_ENABLED is not 'true' — nothing to do. "
              "Set it, plus ROBINHOOD_MCP_TOKEN (from Robinhood's own agent-connection flow), to run discovery.")
        return 0

    if not ROBINHOOD_MCP_TOKEN:
        print("[robinhood-mcp-discovery] ROBINHOOD_MCP_ENABLED=true but ROBINHOOD_MCP_TOKEN is empty. "
              "That token can only come from completing Robinhood's own OAuth/consent flow as the "
              "account holder — this script cannot obtain it. Aborting before making any request.")
        return 1

    print(f"[robinhood-mcp-discovery] Querying {ROBINHOOD_MCP_URL} ...")
    try:
        result = discover()
    except DiscoveryError as e:
        print(f"[robinhood-mcp-discovery] FAILED: {e}")
        return 1

    print("[robinhood-mcp-discovery] initialize response:")
    print(json.dumps(result["initialize"], indent=2))
    print("[robinhood-mcp-discovery] tools/list response (the real, current schema — "
          "use THIS, not any blog post, to decide what an execution client can safely call):")
    print(json.dumps(result["tools_list"], indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
