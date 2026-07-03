"""
AEO Treasury — revenue accrual ledger + autonomous agent hiring trigger.

Tracks a 5% cut of AEO Suite revenue (Stripe subscriptions + any RLUSD x402
calls) as a bookkeeping ledger. This is accounting only — it does NOT move
real funds. Stripe settles in USD to your bank account; there is no
automatic USD→RLUSD conversion here. RLUSD amounts from x402 calls are
already on-chain, but this module does not touch a private key.

When the ledger crosses AEO_TREASURY_HIRE_THRESHOLD_RLUSD, it posts a real
job to the existing zero-custody hiring board (core/api/hiring_bp.py) using
the treasury's public XRPL address. That board never holds funds either —
payment happens wallet-to-wallet directly between poster and executor when
the job is confirmed. So funding the treasury wallet with real RLUSD before
it can actually pay out a hired agent is still a manual step.

Required env var to activate hire-posting (optional — degrades gracefully
without it, exactly like MARKETPLACE_XRPL_SEED in marketplace_bp.py):
  AEO_TREASURY_XRPL_ADDRESS       — public XRPL address, no seed needed
  AEO_TREASURY_HIRE_THRESHOLD_RLUSD — default 25.0
"""

import os
import time
import json
import logging

import redis
import requests
from flask import Blueprint, jsonify

log = logging.getLogger("SqueezeOS-AEOTreasury")
aeo_treasury_bp = Blueprint("aeo_treasury", __name__)

_TREASURY_CUT              = 0.05
_TREASURY_ADDRESS          = os.environ.get("AEO_TREASURY_XRPL_ADDRESS", "")
_HIRE_THRESHOLD_RLUSD       = float(os.environ.get("AEO_TREASURY_HIRE_THRESHOLD_RLUSD", "25.0"))
_SQUEEZEOS_BASE            = os.environ.get("SQUEEZEOS_BASE_URL", "https://squeezeos-api.onrender.com").rstrip("/")
_REDIS_URL                 = os.environ.get("REDIS_URL", "")

_LEDGER_KEY   = "aeo:treasury:ledger"
_HIRES_KEY    = "aeo:treasury:hires"

# In-memory fallback if Redis is unavailable — matches other in-memory
# stores in this codebase; resets on restart, Redis is the durable path.
_mem_ledger = {"accrued_rlusd": 0.0, "lifetime_rlusd": 0.0}
_mem_hires  = []


def _get_redis():
    if not _REDIS_URL:
        return None
    try:
        return redis.from_url(_REDIS_URL, decode_responses=True)
    except Exception as e:
        log.error("AEO Treasury: Redis connect failed: %s", e)
        return None


def _load_ledger(r):
    if r:
        raw = r.get(_LEDGER_KEY)
        if raw:
            return json.loads(raw)
        return {"accrued_rlusd": 0.0, "lifetime_rlusd": 0.0}
    return _mem_ledger


def _save_ledger(r, ledger):
    if r:
        r.set(_LEDGER_KEY, json.dumps(ledger))
    else:
        _mem_ledger.update(ledger)


def _append_hire_record(r, record):
    if r:
        r.lpush(_HIRES_KEY, json.dumps(record))
        r.ltrim(_HIRES_KEY, 0, 49)
    else:
        _mem_hires.insert(0, record)
        del _mem_hires[50:]


def _recent_hires(r, limit=10):
    if r:
        raw = r.lrange(_HIRES_KEY, 0, limit - 1)
        return [json.loads(x) for x in raw]
    return _mem_hires[:limit]


def accrue_usd(gross_amount_usd: float, source: str = "stripe"):
    """Record the treasury's 5% cut of a USD payment (Stripe subscriptions).

    Tracks RLUSD 1:1 against USD for bookkeeping purposes only — RLUSD is
    a USD-pegged stablecoin, but this is an accounting approximation, not
    a live FX rate or a real conversion.
    """
    _accrue(gross_amount_usd * _TREASURY_CUT, source)


def accrue_rlusd(gross_amount_rlusd: float, source: str = "x402"):
    """Record the treasury's 5% cut of a real on-chain RLUSD payment."""
    _accrue(gross_amount_rlusd * _TREASURY_CUT, source)


def _accrue(cut_rlusd: float, source: str):
    if cut_rlusd <= 0:
        return
    r = _get_redis()
    ledger = _load_ledger(r)
    ledger["accrued_rlusd"] = round(ledger.get("accrued_rlusd", 0.0) + cut_rlusd, 6)
    ledger["lifetime_rlusd"] = round(ledger.get("lifetime_rlusd", 0.0) + cut_rlusd, 6)
    _save_ledger(r, ledger)
    log.info("AEO Treasury: accrued %.4f RLUSD from %s (balance now %.4f)",
              cut_rlusd, source, ledger["accrued_rlusd"])

    if ledger["accrued_rlusd"] >= _HIRE_THRESHOLD_RLUSD:
        _maybe_trigger_hire(r, ledger)


def _maybe_trigger_hire(r, ledger):
    if not _TREASURY_ADDRESS:
        log.info("AEO Treasury: threshold crossed (%.4f RLUSD) but "
                  "AEO_TREASURY_XRPL_ADDRESS not set — skipping auto-hire",
                  ledger["accrued_rlusd"])
        return

    bounty = _HIRE_THRESHOLD_RLUSD
    job_body = {
        "wallet":         _TREASURY_ADDRESS,
        "payment_wallet": _TREASURY_ADDRESS,
        "job_type":       "RESEARCH",
        "description":    (
            "AEO Treasury auto-hire: capability gap detected by the S1->S4 "
            "self-advertising loop. Analyze the current top semantic gaps "
            "(GET /api/graph/gaps/) and propose a concrete narrative or "
            "integration fix to close the highest-value gap."
        ),
        "bounty_rlusd":   bounty,
        "deadline_hours": 72,
    }
    try:
        resp = requests.post(f"{_SQUEEZEOS_BASE}/api/hiring/post", json=job_body, timeout=15)
        resp.raise_for_status()
        job = resp.json()
    except Exception as e:
        log.error("AEO Treasury: auto-hire POST failed: %s", e)
        return

    ledger["accrued_rlusd"] = round(ledger["accrued_rlusd"] - bounty, 6)
    _save_ledger(r, ledger)
    _append_hire_record(r, {
        "job_id": job.get("job_id") or job.get("job", {}).get("job_id"),
        "bounty_rlusd": bounty,
        "posted_at": time.time(),
    })
    log.info("AEO Treasury: auto-hire posted, bounty=%.4f RLUSD, remaining balance=%.4f",
              bounty, ledger["accrued_rlusd"])


@aeo_treasury_bp.route("/treasury", methods=["GET"])
def treasury_status():
    r = _get_redis()
    ledger = _load_ledger(r)
    return jsonify({
        "accrued_rlusd":            ledger.get("accrued_rlusd", 0.0),
        "lifetime_rlusd":           ledger.get("lifetime_rlusd", 0.0),
        "hire_threshold_rlusd":     _HIRE_THRESHOLD_RLUSD,
        "treasury_wallet_configured": bool(_TREASURY_ADDRESS),
        "treasury_wallet":          _TREASURY_ADDRESS[:8] + "…" if _TREASURY_ADDRESS else None,
        "auto_hires":               _recent_hires(r),
        "note": (
            "This is a revenue-share bookkeeping ledger, not a live wallet balance. "
            "Stripe revenue is USD and requires a manual conversion/transfer into the "
            "treasury XRPL wallet — nothing here moves real funds automatically."
        ),
    })
