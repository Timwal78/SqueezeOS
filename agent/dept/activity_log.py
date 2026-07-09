"""
Shared helper — post a real activity event to the live marketing feed
(core/api/marketing_activity_bp.py). Best-effort: a feed outage must never
break the actual work an agent is doing, so failures are swallowed.

Env:
  SQUEEZEOS_BASE_URL        (default: https://squeezeos-api.onrender.com)
  MARKETING_ACTIVITY_SECRET (required for the POST to succeed server-side)
"""

import os
import requests

_SQUEEZEOS = os.environ.get("SQUEEZEOS_BASE_URL", "https://squeezeos-api.onrender.com").rstrip("/")
_SECRET    = os.environ.get("MARKETING_ACTIVITY_SECRET", "")


def post_activity(agent: str, action: str, status: str = "info") -> None:
    if not _SECRET:
        return
    try:
        requests.post(
            f"{_SQUEEZEOS}/api/marketing/activity",
            json={"agent": agent, "action": action, "status": status},
            headers={"X-Marketing-Secret": _SECRET},
            timeout=10,
        )
    except Exception:
        pass  # non-critical — never let feed logging break a real agent run


def post_directory_snapshot(already_listed: list, not_listed: list) -> None:
    """Publish the real result of a Directory Ranger run so the public
    dashboard can show actual per-directory status instead of a guess."""
    if not _SECRET:
        return
    try:
        requests.post(
            f"{_SQUEEZEOS}/api/marketing/directories",
            json={"already_listed": already_listed, "not_listed": not_listed},
            headers={"X-Marketing-Secret": _SECRET},
            timeout=10,
        )
    except Exception:
        pass


def post_federal_snapshot(opportunities_scanned: int, high_relevance: list,
                           medium_relevance: list, legislative_intel: list) -> None:
    """Publish the real result of a Federal Scout run so the public dashboard
    can show actual scored opportunities instead of a guess."""
    if not _SECRET:
        return
    try:
        requests.post(
            f"{_SQUEEZEOS}/api/marketing/federal",
            json={
                "opportunities_scanned": opportunities_scanned,
                "high_relevance": high_relevance,
                "medium_relevance": medium_relevance,
                "legislative_intel": legislative_intel,
            },
            headers={"X-Marketing-Secret": _SECRET},
            timeout=10,
        )
    except Exception:
        pass
