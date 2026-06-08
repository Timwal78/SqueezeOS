"""
Agent Credit Bureau client.

Single source of truth for fetching FICO-style reputation scores (300-850)
from the 402Proof Agent Credit Bureau. Used by:

  - stigmergy_engine — discount dream pool rent for high-rep agents
  - futures_bp       — discount platform fee on settled futures for high-rep winners
  - (future)         — discount marketplace read fees, hiring escrow, etc.

Design:
  - One in-memory TTL cache (default 300s). Same wallet hit repeatedly across
    requests doesn't re-call the bureau every time.
  - Failure-closed: any bureau error / offline returns score=0 → 0% discount.
    Agents never get a free ride from a degraded bureau, but they also
    don't get blocked.
  - Pure-stdlib HTTP. No requests dep here — this module is imported by the
    engine which runs in the request hot path.

The discount curve is deliberately gentle:
    300-499  →  0%   (default — unproven agent)
    500-599  →  5%
    600-699  →  10%
    700-799  →  15%
    800-850  →  20%  (max)

Never goes above 20% — the platform always retains at least 80% of its
quoted fee from the highest-rep agents, so the operator's margin floor
is mathematically guaranteed.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request

logger = logging.getLogger("SqueezeOS-Bureau")

PROOF402_BASE = os.environ.get("PROOF402_SERVER_URL", "https://four02proof.onrender.com").rstrip("/")
BUREAU_CACHE_TTL = int(os.environ.get("BUREAU_CACHE_TTL_S", "300"))
BUREAU_TIMEOUT = float(os.environ.get("BUREAU_TIMEOUT_S", "3.0"))
MAX_REP_DISCOUNT = 0.20

_cache: dict[str, tuple[float, int]] = {}  # wallet -> (expires_at, score)
_cache_lock = threading.Lock()


def _fetch_score(wallet: str) -> int:
    """Hit 402Proof bureau. Returns 0 on any failure path."""
    url = f"{PROOF402_BASE}/v1/bureau/score/{wallet}"
    req = urllib.request.Request(url, headers={"User-Agent": "SqueezeOS-Bureau/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=BUREAU_TIMEOUT) as resp:
            data = json.loads(resp.read())
        score = int(data.get("score", 0))
        if 300 <= score <= 850:
            return score
        return 0
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, TimeoutError, OSError) as e:
        logger.debug("bureau lookup %s failed: %s", wallet[:12] if wallet else "?", e)
        return 0


def score_for(wallet: str) -> int:
    """Get bureau score for a wallet. Cached, failure-closed.

    Returns 0 if the wallet is empty, unknown, or the bureau is offline.
    A score of 0 always maps to 0% discount in `rep_discount_pct`."""
    if not wallet:
        return 0
    now = time.time()
    with _cache_lock:
        entry = _cache.get(wallet)
        if entry and entry[0] > now:
            return entry[1]

    score = _fetch_score(wallet)

    with _cache_lock:
        _cache[wallet] = (now + BUREAU_CACHE_TTL, score)
    return score


def rep_discount_pct(score: int) -> float:
    """Map a bureau score (0 or 300-850) to a fee discount in [0.0, 0.20].

    Buckets are intentionally coarse so agents have a clear progression
    path: every 100-point bump gives them another 5% off."""
    if score < 500:
        return 0.0
    if score < 600:
        return 0.05
    if score < 700:
        return 0.10
    if score < 800:
        return 0.15
    return MAX_REP_DISCOUNT


def discount_for_wallet(wallet: str) -> tuple[float, int]:
    """Convenience: returns (discount_pct, score). Discount in [0.0, 0.20]."""
    s = score_for(wallet)
    return rep_discount_pct(s), s
