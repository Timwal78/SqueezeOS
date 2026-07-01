"""
passport_bp.py — Agent Passport: one unified profile per wallet address.

Aggregates every wallet-keyed reputation/history source already live across
SqueezeOS into a single response. Adds no new data stores and no new scoring
logic of its own -- it is strictly a read-through aggregator over the real
in-memory stores and live 402Proof credit bureau that already exist.

Route: GET /api/passport/<wallet>

Design for easy extension: SECTIONS is a list of (name, fetch_fn) pairs.
fetch_fn takes the wallet string and returns a JSON-serializable dict, or
raises. Each section runs independently and failures are isolated -- one
broken source never takes down the rest of the passport, and a failed
section is reported as {"status": "unavailable"}, never fabricated data
(Sovereign Data Policy Section 4: no fallback to invented values).

To add a new section later: write a fetch_fn, append it to SECTIONS below.
Nothing else in this file needs to change.
"""

import logging
import time

from flask import Blueprint, jsonify

from core.legacy import clean_data
from proof402_integration import fetch_credit_bureau_score

logger = logging.getLogger("PassportBP")
passport_bp = Blueprint("passport", __name__)


def _section_trust(wallet: str) -> dict:
    from core.api.ccs_bp import _get_wallet_trust, _composite_trust
    ledger = _get_wallet_trust(wallet)
    bureau_score = fetch_credit_bureau_score(wallet)
    return {
        "ccs_score": ledger["ccs_score"],
        "reputation_tier": ledger["reputation_tier"],
        "validations_submitted": ledger["validations_submitted"],
        "content_blocked": ledger["content_blocked"],
        "content_passed": ledger["content_passed"],
        "agent_credit_bureau_score": bureau_score,
        "composite_trust": _composite_trust(ledger["ccs_score"], bureau_score),
        "first_seen": ledger["first_seen"],
        "last_seen": ledger["last_seen"],
    }


def _section_marketplace(wallet: str) -> dict:
    from core.api.marketplace_bp import _seller_stats, SELLER_SHARE
    st = _seller_stats.get(wallet)
    if not st:
        return {"balance_rlusd": 0.0, "sale_count": 0, "message": "No sales recorded for this wallet yet."}
    return {
        "balance_rlusd": st["balance_rlusd"],
        "paid_out_rlusd": st["paid_out_rlusd"],
        "revenue_rlusd": st["revenue_rlusd"],
        "sale_count": st["sale_count"],
        "seller_share": f"{int(SELLER_SHARE * 100)}%",
    }


def _section_futures(wallet: str) -> dict:
    from core.api.futures_bp import _futures, _leaderboard, _lock
    with _lock:
        results = [f for f in _futures.values()
                   if f["creator_wallet"] == wallet or f["taker_wallet"] == wallet]
    return {
        "count": len(results),
        "stats": _leaderboard.get(wallet, {}),
    }


def _section_settlement(wallet: str) -> dict:
    from core.api.settlement_bp import _contracts, _lock
    with _lock:
        results = [c for c in _contracts.values()
                   if c["creator_wallet"] == wallet or c["counterparty"] == wallet]
    return {"count": len(results)}


def _section_hiring(wallet: str) -> dict:
    from core.api.hiring_bp import _jobs, _rep
    posted = [j for j in _jobs.values() if j['poster'] == wallet]
    executed = [j for j in _jobs.values() if j.get('executor') == wallet]
    return {
        "reputation": _rep(wallet),
        "posted": {
            "count": len(posted),
            "filled": sum(1 for j in posted if j['status'] == 'CONFIRMED'),
        },
        "executed": {
            "count": len(executed),
            "completed": sum(1 for j in executed if j['status'] == 'CONFIRMED'),
            "disputed": sum(1 for j in executed if j['status'] == 'DISPUTED'),
        },
    }


# Registry of passport sections. Append here to extend -- nothing else
# in this file needs to change to add a new data source.
SECTIONS = [
    ("trust", _section_trust),
    ("marketplace", _section_marketplace),
    ("futures", _section_futures),
    ("settlement", _section_settlement),
    ("hiring", _section_hiring),
]


@passport_bp.route("/<wallet>", methods=["GET"])
def passport(wallet: str):
    wallet = wallet.strip()
    if not wallet:
        return jsonify({"error": "WALLET_REQUIRED"}), 400

    sections = {}
    for name, fetch_fn in SECTIONS:
        try:
            sections[name] = fetch_fn(wallet)
        except Exception as e:
            logger.warning("[PASSPORT] section '%s' failed for %s: %s", name, wallet, e)
            sections[name] = {"status": "unavailable"}

    return jsonify(clean_data({
        "wallet": wallet,
        **sections,
        "source_note": (
            "Every section above is a live read-through of an existing SqueezeOS store "
            "or the 402Proof credit bureau -- nothing here is estimated or fabricated. "
            "A section reading {'status': 'unavailable'} means that source could not be "
            "reached, not that the wallet has no activity."
        ),
        "ts": time.time(),
    }))


@passport_bp.route("/info", methods=["GET"])
def info():
    return jsonify({
        "endpoint": "/api/passport/<wallet>",
        "description": "Unified agent profile: trust score, marketplace earnings, futures/settlement/hiring history.",
        "sections": [name for name, _ in SECTIONS],
        "free": True,
    })
