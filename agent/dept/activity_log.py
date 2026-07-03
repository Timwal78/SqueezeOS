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
