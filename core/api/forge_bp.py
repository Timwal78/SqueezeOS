"""
forge_bp.py — Stellar Forge growth engine, exposed as a Flask blueprint.

FEATURE-FLAGGED. Registered in core/app.py only when STELLAR_FORGE_ENABLED=true,
so it ships dormant until you flip it on deliberately (after Postgres exists and
the payout wallet is decided). This is the "deployable the moment infra exists"
surface.

Routes (prefix /api/forge):
  POST /register            free; rate-limited per source IP (sybil step 3)
  POST /settle              verifies the x402 token inline; accrues fee + rebates
  GET  /earnings/<wallet>   free; accrued vs withdrawable
  GET  /quote/<wallet>      free; loyalty tier + fee/routing/fusion perks
  POST /route               enqueue inference at loyalty priority (needs upstream)
  POST /payout              OWNER-gated; settles accrued rebates on-chain (idempotent)

Config (env):
  STELLAR_FORGE_ENABLED      "true" to register the blueprint at all
  STELLAR_FORGE_DB           SQLite path or Postgres DSN (durable ledger)
  STELLAR_FORGE_UPSTREAM_URL optional inference backend for /route
  STELLAR_FORGE_LIVE_PAYOUTS "true" to use the real XRPLSubmitter (else dry-run)
  OWNER_API_KEY              bearer for /payout (reuses the platform owner key)
  AGENT_XRPL_SEED            the already-funded protocol wallet (for live payouts)

Storage and verification are the real economy modules — no demo data.
"""

from __future__ import annotations

import os
import time
import logging

from flask import Blueprint, request, jsonify

logger = logging.getLogger("SqueezeOS-Forge")
forge_bp = Blueprint("forge", __name__)

# ── Lazy singleton — built on first use so registration is cheap ─────────────
_forge: dict | None = None


def _build_forge() -> dict:
    """Construct the economy engine graph from env. Real backends only."""
    from stellar_forge.economy import (
        Store, Proof402Client, LoyaltyResolver, ReferralEngine, GrowthEngine,
        RegistrationRateLimiter, EarnEligibility, PayoutRunner,
        DryRunSubmitter,
    )
    store = Store(os.environ.get("STELLAR_FORGE_DB", ":memory:"))
    client = Proof402Client()
    loyalty = LoyaltyResolver(client)
    rate_limiter = RegistrationRateLimiter(store)
    referrals = ReferralEngine(store, rate_limiter=rate_limiter)
    eligibility = EarnEligibility(store, loyalty)
    growth = GrowthEngine(store, loyalty, referrals, eligibility=eligibility)

    if os.environ.get("STELLAR_FORGE_LIVE_PAYOUTS", "").lower() == "true":
        from stellar_forge.economy import XRPLSubmitter
        submitter = XRPLSubmitter()           # reads AGENT_XRPL_SEED + RLUSD_ISSUER
    else:
        submitter = DryRunSubmitter()
    payouts = PayoutRunner(store, submitter=submitter, eligibility=eligibility)

    # Optional priority-routing gateway in front of a pluggable upstream.
    router = None
    upstream = os.environ.get("STELLAR_FORGE_UPSTREAM_URL", "")
    if upstream:
        import urllib.request, json as _json
        from stellar_forge.gateway import PriorityRouter

        def _handler(payload: dict):
            data = _json.dumps(payload).encode()
            req = urllib.request.Request(
                upstream, data=data, method="POST",
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                return _json.loads(resp.read())

        router = PriorityRouter(_handler, workers=int(os.environ.get("STELLAR_FORGE_WORKERS", "4")))

    return {"store": store, "loyalty": loyalty, "referrals": referrals,
            "growth": growth, "payouts": payouts, "router": router}


def _get() -> dict:
    global _forge
    if _forge is None:
        _forge = _build_forge()
    return _forge


def _source_key() -> str:
    """Best-effort client identifier for rate limiting (proxy-aware)."""
    fwd = request.headers.get("X-Forwarded-For", "")
    return (fwd.split(",")[0].strip() if fwd else request.remote_addr or "unknown")


# ── Routes ───────────────────────────────────────────────────────────────────
@forge_bp.route("/register", methods=["POST"])
def register():
    from stellar_forge.economy import RateLimitExceeded
    body = request.get_json(silent=True) or {}
    wallet = (body.get("wallet") or "").strip()
    if not wallet:
        return jsonify({"error": "wallet required"}), 400
    try:
        res = _get()["referrals"].register(
            wallet, referrer_code=body.get("referrer_code"), source=_source_key())
        return jsonify(res), 200
    except RateLimitExceeded as e:
        return jsonify({"error": "rate_limited", "detail": str(e)}), 429
    except ValueError as e:
        return jsonify({"error": "invalid", "detail": str(e)}), 400


@forge_bp.route("/settle", methods=["POST"])
def settle():
    body = request.get_json(silent=True) or {}
    token = request.headers.get("X-Payment-Token") or body.get("payment_token")
    if not token:
        return jsonify({"error": "X-Payment-Token required"}), 402
    sid = (body.get("settlement_id") or "").strip()
    kind = (body.get("kind") or "").strip()
    amount = body.get("amount_rlusd")
    if not sid or not kind or amount is None:
        return jsonify({"error": "settlement_id, kind, amount_rlusd required"}), 400
    try:
        receipt = _get()["growth"].finalize_settlement(sid, kind, float(amount), token)
        return jsonify(receipt.to_dict()), 200
    except PermissionError as e:
        return jsonify({"error": "payment_rejected", "detail": str(e)}), 402
    except ValueError as e:
        return jsonify({"error": "invalid", "detail": str(e)}), 400


@forge_bp.route("/earnings/<wallet>", methods=["GET"])
def earnings(wallet: str):
    return jsonify(_get()["growth"].earnings(wallet)), 200


@forge_bp.route("/quote/<wallet>", methods=["GET"])
def quote(wallet: str):
    tier, info = _get()["loyalty"].resolve(wallet)
    return jsonify({
        "wallet": wallet, "tier": tier.name,
        "fee_discount_bps": tier.fee_discount_bps,
        "routing_priority": tier.routing_priority,
        "fusion_discount_bps": tier.fusion_discount_bps,
        "bureau": info,
    }), 200


@forge_bp.route("/route", methods=["POST"])
def route():
    forge = _get()
    router = forge["router"]
    if router is None:
        # Repo convention: 503, never fake an inference result.
        return jsonify({"error": "no_upstream",
                        "detail": "set STELLAR_FORGE_UPSTREAM_URL to enable routing"}), 503
    body = request.get_json(silent=True) or {}
    wallet = (body.get("wallet") or "").strip()
    payload = body.get("payload") or {}
    rid = body.get("request_id") or f"r-{int(time.time()*1000)}"
    tier, _ = forge["loyalty"].resolve(wallet)
    ticket = router.submit(rid, payload, priority=tier.routing_priority)
    try:
        result = ticket.wait(timeout=float(os.environ.get("STELLAR_FORGE_ROUTE_TIMEOUT", "60")))
    except TimeoutError:
        return jsonify({"error": "timeout", "tier": tier.name}), 504
    return jsonify({"request_id": rid, "tier": tier.name,
                    "queue_wait_ms": ticket.queue_wait_ms, "result": result}), 200


@forge_bp.route("/payout", methods=["POST"])
def payout():
    owner_key = os.environ.get("OWNER_API_KEY", "")
    supplied = request.headers.get("X-Owner-Key", "")
    if not owner_key or supplied != owner_key:
        return jsonify({"error": "forbidden"}), 403
    body = request.get_json(silent=True) or {}
    account = (body.get("account") or "").strip()
    dest = (body.get("dest_wallet") or "").strip()
    if not account or not dest:
        return jsonify({"error": "account and dest_wallet required"}), 400
    res = _get()["payouts"].pay(account, dest)
    return jsonify({
        "account": res.account, "amount_rlusd": res.amount_rlusd,
        "state": res.state, "tx_hash": res.tx_hash, "reason": res.reason,
    }), 200
