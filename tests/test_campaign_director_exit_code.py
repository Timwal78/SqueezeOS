"""
Regression test for campaign_director.py's always-0 exit code
(2026-07-20, found by background audit agent).

run() always returned a truthy dict (it always contains at least "date"),
so `sys.exit(0 if run() else 1)` in the __main__ block could never signal
failure via process exit code — even when every specialist agent failed.
Note the real production path (.github/workflows/marketing-daily.yml) calls
`campaign_director.run()` directly via `python -c "..."`, not via __main__,
so this was low-impact in practice; it still matters for anyone running
`python agent/dept/campaign_director.py` manually to sanity-check things.

Fixed by having run() attach a real, deterministic `failed_agents` list
(already computed from agent_results — the same list post_activity's error
message already used) onto the returned report, and having __main__ check
that instead of the dict's own truthiness.

This drives the real, unmodified run() end-to-end with only its network/file
dependencies mocked (Claude API, Slack post, activity-feed post, disk I/O).
"""

import json
import os
import sys
from unittest.mock import MagicMock, patch

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agent.dept.campaign_director as cd  # noqa: E402


def _mock_run(agent_results: dict, report_extra: dict = None):
    report = {"date": "2026-07-20", "health": "GREEN", **(report_extra or {})}
    return (
        patch.object(cd, "get_squeezeos_status", return_value={}),
        patch.object(cd, "run_all_agents", return_value=agent_results),
        patch.object(cd, "synthesize_report", return_value=dict(report)),
        patch.object(cd, "post_activity"),
        patch.object(cd, "post_slack"),
        patch.object(cd.os, "makedirs"),
        patch("builtins.open", MagicMock()),
        patch.object(cd.json, "dump"),
    )


def test_failed_agents_is_empty_when_every_specialist_succeeds():
    agent_results = {
        "directory_ranger": {"already_listed": [], "not_listed": []},
        "community_scout":  {"opportunities": []},
    }
    patches = _mock_run(agent_results)
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7]:
        report = cd.run()

    assert report["failed_agents"] == [], report
    print("PASS: no real failures -> failed_agents is empty")


def test_failed_agents_reflects_real_specialist_errors():
    agent_results = {
        "directory_ranger": {"already_listed": []},
        "community_scout":  {"error": "connection timeout"},
        "federal_scout":    {"error": "API 500"},
        "grant_scout":      {"queued": []},
    }
    patches = _mock_run(agent_results)
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7]:
        report = cd.run()

    assert set(report["failed_agents"]) == {"community_scout", "federal_scout"}, report
    print(f"PASS: real specialist failures correctly surfaced — {report['failed_agents']}")


def test_exit_code_decision_is_now_based_on_real_failures_not_dict_truthiness():
    """Documents the exact bug: the report dict is ALWAYS truthy (it always
    has at least "date"), so `sys.exit(0 if run() else 1)` could never fire
    even with every specialist failing. The fix's real decision point is
    `report.get("failed_agents")`, which this proves is meaningful now."""
    agent_results_all_failed = {
        "directory_ranger": {"error": "boom"},
        "community_scout":  {"error": "boom"},
    }
    patches = _mock_run(agent_results_all_failed)
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7]:
        report = cd.run()

    assert bool(report), "the dict itself is (as before) always truthy — this is exactly why the old check was broken"
    assert report.get("failed_agents"), "but the new field must reflect the real total failure"
    exit_code = 1 if report.get("failed_agents") else 0
    assert exit_code == 1, "the real exit-code decision must now be 1 on total specialist failure"
    print(f"PASS: exit-code decision correctly derived from real failures, not dict truthiness — failed_agents={report['failed_agents']}")


if __name__ == "__main__":
    test_failed_agents_is_empty_when_every_specialist_succeeds()
    test_failed_agents_reflects_real_specialist_errors()
    test_exit_code_decision_is_now_based_on_real_failures_not_dict_truthiness()
    print("\nAll regression tests passed.")
