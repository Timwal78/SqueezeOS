"""
Regression test for the fabricated earned_rlusd in agent/sml_agent.py
(2026-07-20, found by background audit agent).

POST /api/marketplace/list (core/api/marketplace_bp.py) is a FREE endpoint —
only POST /api/marketplace/read actually charges 0.02 RLUSD and credits the
seller (90% share, tracked server-side in _seller_stats / SQLite). Yet
list_brief() used to call pnl.record_earn(BRIEF_PRICE) unconditionally right
after every free listing POST succeeded, regardless of whether any agent
ever paid to read the thesis. spent_rlusd (real XRPL payments) was accurate,
but earned_rlusd/net_rlusd was fictitious revenue invented at listing time.

Fixed by: (1) list_brief() now calls pnl.record_listing() — a real,
unfakeable count of listings made, touching only `listings`, never `earned`;
(2) a new refresh_earnings() pulls the REAL, server-tracked lifetime seller
balance from GET /api/marketplace/balance/<wallet> and overwrites
pnl.earned with that authoritative figure.

This drives the real, unmodified PnL class and list_brief()/refresh_earnings()
functions — only the outbound HTTP calls are mocked.
"""

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agent.sml_agent as sml_agent  # noqa: E402


def test_listing_a_brief_no_longer_fabricates_earned_revenue():
    sml_agent.pnl.earned = 0.0
    sml_agent.pnl.listings = 0
    sml_agent.AGENT_ADDR = "rTESTADDR"

    fake_resp = MagicMock()
    fake_resp.json.return_value = {"listing_id": "abc123"}
    fake_resp.raise_for_status.return_value = None

    with patch.object(sml_agent.requests, "post", return_value=fake_resp) as mock_post:
        listing_id = sml_agent.list_brief({"top_picks": ["IWM"], "market_thesis": "test thesis here long enough"})

    assert listing_id == "abc123"
    assert mock_post.called
    assert sml_agent.pnl.listings == 1, "a real listing must still be counted"
    assert sml_agent.pnl.earned == 0.0, (
        f"listing a free brief must NOT fabricate earned revenue — earned={sml_agent.pnl.earned}"
    )
    print(f"PASS: listing a brief no longer fabricates earned_rlusd — listings={sml_agent.pnl.listings}, earned={sml_agent.pnl.earned}")


def test_refresh_earnings_pulls_the_real_server_tracked_balance():
    sml_agent.pnl.earned = 0.0
    sml_agent.AGENT_ADDR = "rTESTADDR"

    fake_resp = MagicMock()
    fake_resp.json.return_value = {
        "wallet": "rTESTADDR", "balance_rlusd": 0.09, "paid_out_rlusd": 0.0,
        "revenue_rlusd": 0.18, "sale_count": 10, "seller_share": "90%",
    }
    fake_resp.raise_for_status.return_value = None

    with patch.object(sml_agent.requests, "get", return_value=fake_resp) as mock_get:
        sml_agent.refresh_earnings()

    assert mock_get.called
    called_url = mock_get.call_args[0][0]
    assert "marketplace/balance/rTESTADDR" in called_url, called_url
    assert sml_agent.pnl.earned == 0.18, (
        f"earned must be set to the real server-tracked revenue_rlusd — got {sml_agent.pnl.earned}"
    )
    print(f"PASS: refresh_earnings() pulls the real balance — earned={sml_agent.pnl.earned}")


def test_refresh_earnings_overwrites_not_accumulates_stale_local_value():
    """The server figure is cumulative — a second refresh must SET, not add on
    top of, any stale local value (guards against re-introducing double-counting)."""
    sml_agent.pnl.earned = 5.0  # stale/wrong local value from before this fix
    sml_agent.AGENT_ADDR = "rTESTADDR"

    fake_resp = MagicMock()
    fake_resp.json.return_value = {"revenue_rlusd": 0.34}
    fake_resp.raise_for_status.return_value = None

    with patch.object(sml_agent.requests, "get", return_value=fake_resp):
        sml_agent.refresh_earnings()

    assert sml_agent.pnl.earned == 0.34, sml_agent.pnl.earned
    print(f"PASS: refresh_earnings() overwrites stale local earned instead of accumulating on top — earned={sml_agent.pnl.earned}")


def test_refresh_earnings_is_a_noop_without_agent_address_configured():
    sml_agent.pnl.earned = 0.0
    sml_agent.AGENT_ADDR = ""

    with patch.object(sml_agent.requests, "get") as mock_get:
        sml_agent.refresh_earnings()

    assert not mock_get.called, "must not attempt a real HTTP call with no agent wallet configured"
    print("PASS: refresh_earnings() is a real no-op (no fabricated network call) without AGENT_ADDR")


def test_refresh_earnings_network_failure_does_not_crash_or_fabricate():
    sml_agent.pnl.earned = 0.0
    sml_agent.AGENT_ADDR = "rTESTADDR"

    with patch.object(sml_agent.requests, "get", side_effect=ConnectionError("boom")):
        sml_agent.refresh_earnings()  # must not raise

    assert sml_agent.pnl.earned == 0.0, "a failed refresh must leave earned unchanged, never fabricate a value"
    print("PASS: a real network failure during refresh does not crash and does not fabricate a value")


if __name__ == "__main__":
    test_listing_a_brief_no_longer_fabricates_earned_revenue()
    test_refresh_earnings_pulls_the_real_server_tracked_balance()
    test_refresh_earnings_overwrites_not_accumulates_stale_local_value()
    test_refresh_earnings_is_a_noop_without_agent_address_configured()
    test_refresh_earnings_network_failure_does_not_crash_or_fabricate()
    print("\nAll regression tests passed.")
