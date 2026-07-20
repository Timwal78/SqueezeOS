"""
Regression test for the undefined-variable crash in mcp_bp.py's _dispatch()
agent_economy branch (2026-07-20, found by background audit agent).

_dispatch() defines `payment_token`/`agent_wallet` at the top of the function
(from args or request headers), but the "agent_economy" tool's view="report"
branch referenced undefined names `token`/`wallet` instead — every other
branch in this same function correctly uses `payment_token`/`agent_wallet`
(confirmed via a full pyflakes pass on the file after the fix, which found
no other undefined names). Any agent calling the paid (0.25 RLUSD)
"agent_economy" tool with view="report" hit an unhandled NameError -> 500,
regardless of whether they'd actually paid.

This drives the real, unmodified _dispatch() end-to-end (only the outbound
_proxy() HTTP call is mocked) and proves the report view now works with a
real token, and still degrades to the normal ERR_PAYMENT_REQUIRED response
(not a crash) without one.
"""

import json
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.api.mcp_bp import _dispatch  # noqa: E402


def test_agent_economy_report_without_token_returns_payment_required_not_a_crash():
    result = _dispatch("agent_economy", {"view": "report"}, {})
    text = result["content"][0]["text"]
    payload = json.loads(text)
    assert payload["error"] == "ERR_PAYMENT_REQUIRED", payload
    print(f"PASS: no token -> clean ERR_PAYMENT_REQUIRED, not a NameError crash — {payload['error']}")


def test_agent_economy_report_with_token_no_longer_crashes_and_forwards_it():
    with patch("core.api.mcp_bp._proxy") as mock_proxy:
        mock_proxy.return_value = {"status": 200, "json": {"ok": True}}
        result = _dispatch(
            "agent_economy",
            {"view": "report", "payment_token": "REAL_JWT_TOKEN", "agent_wallet": "rXRPLADDR"},
            {},
        )

    assert mock_proxy.called, "agent_economy report must actually reach _proxy(), not crash before it"
    call_args, call_kwargs = mock_proxy.call_args
    assert "agent-economy/report" in call_args[1], call_args
    headers = call_kwargs.get("headers") or {}
    assert headers.get("X-Payment-Token") == "REAL_JWT_TOKEN", headers
    assert headers.get("X-Agent-Wallet") == "rXRPLADDR", headers
    print(f"PASS: real payment_token/agent_wallet correctly forwarded — headers={headers}")


def test_agent_economy_leaderboard_view_unaffected_no_token_needed():
    """Sanity: the other agent_economy views never touched the broken
    token/wallet names — must keep working exactly as before."""
    with patch("core.api.mcp_bp._proxy") as mock_proxy:
        mock_proxy.return_value = {"status": 200, "json": {"ok": True}}
        _dispatch("agent_economy", {"view": "leaderboard"}, {})
    assert mock_proxy.called
    print("PASS: leaderboard view (no token required) still works unaffected")


if __name__ == "__main__":
    test_agent_economy_report_without_token_returns_payment_required_not_a_crash()
    test_agent_economy_report_with_token_no_longer_crashes_and_forwards_it()
    test_agent_economy_leaderboard_view_unaffected_no_token_needed()
    print("\nAll regression tests passed.")
