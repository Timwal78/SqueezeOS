"""
Signal Relay Mesh — Node Registry
===================================
Relay nodes are agents that resell SqueezeOS signals to downstream agents
at a self-set markup. They access signals at bulk-discount rates (40% off
standard pricing) and keep the spread.

SqueezeOS earns 60% per transaction via relay nodes while gaining
distribution it otherwise wouldn't reach.  No custody at any point —
relay nodes pay SqueezeOS directly via x402, collect from their own
downstream agents however they choose.

Relay Endpoint IDs (bulk discount via 402Proof):
  council : b2r1e1a4-c001-4c3f-aa24-de6e3bc12b5a  — 0.06 RLUSD
  scan    : b2r1e1a4-c002-4c3f-aa24-de6e3bc12b5a  — 0.03 RLUSD
  options : b2r1e1a4-c003-4c3f-aa24-de6e3bc12b5a  — 0.03 RLUSD
  iwm     : b2r1e1a4-c004-4c3f-aa24-de6e3bc12b5a  — 0.018 RLUSD
"""

import os
import time
import uuid
import json
import logging
import urllib.request
from flask import Blueprint, jsonify, request

logger = logging.getLogger("SqueezeOS-Relay")
relay_bp = Blueprint('relay', __name__)

_BUREAU_URL  = os.environ.get('PROOF402_SERVER_URL', 'https://four02proof.onrender.com')
_MIN_SCORE   = 600   # minimum Credit Bureau score to become a relay node

# ── Relay Node Registry (in-memory, survives Railway crashes, resets on deploy)
_registry: dict[str, dict] = {}

# Bulk-discount endpoint IDs seeded in 402Proof — relay nodes use these
RELAY_ENDPOINTS = {
    "council": {
        "id":    "b2r1e1a4-c001-4c3f-aa24-de6e3bc12b5a",
        "price": "0.06",
        "label": "AI Council Verdict (relay bulk)",
        "standard_price": "0.10",
        "discount_pct":   40,
    },
    "scan": {
        "id":    "b2r1e1a4-c002-4c3f-aa24-de6e3bc12b5a",
        "price": "0.03",
        "label": "Market Scan (relay bulk)",
        "standard_price": "0.05",
        "discount_pct":   40,
    },
    "options": {
        "id":    "b2r1e1a4-c003-4c3f-aa24-de6e3bc12b5a",
        "price": "0.03",
        "label": "Options Intelligence (relay bulk)",
        "standard_price": "0.05",
        "discount_pct":   40,
    },
    "iwm": {
        "id":    "b2r1e1a4-c004-4c3f-aa24-de6e3bc12b5a",
        "price": "0.018",
        "label": "IWM 0DTE (relay bulk)",
        "standard_price": "0.03",
        "discount_pct":   40,
    },
}


def _bureau_score(wallet: str) -> dict:
    """Fetch credit bureau score from 402Proof. Returns score dict or {'offline': True}."""
    try:
        url = f"{_BUREAU_URL}/v1/bureau/score/{wallet}"
        req = urllib.request.Request(url, headers={"User-Agent": "SqueezeOS-Relay/2.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except Exception as e:
        logger.warning(f"[RELAY] Bureau offline during registration check: {e}")
        return {"offline": True}


@relay_bp.route('/register', methods=['POST'])
def register():
    """
    Register as a relay node. Requires Credit Bureau score >= 600.
    Body: { wallet, markup_bps, relay_url (opt), description (opt) }

    Credit Bureau score >= 600 requires roughly 10 payments (~1.5 RLUSD lifetime spend).
    Build score by paying for signals through SqueezeOS standard endpoints first.
    """
    body = request.get_json(silent=True) or {}
    wallet = (body.get('wallet') or '').strip()
    markup_bps = body.get('markup_bps', 1000)  # default 10%
    relay_url   = (body.get('relay_url') or '').strip()
    description = (body.get('description') or '')[:200]

    if not wallet:
        return jsonify({"error": "ERR_WALLET_REQUIRED", "message": "wallet field required"}), 400
    if not wallet.startswith('r') or len(wallet) < 25:
        return jsonify({"error": "ERR_INVALID_WALLET", "message": "invalid XRPL wallet address"}), 400
    if not isinstance(markup_bps, int) or not (100 <= markup_bps <= 10000):
        return jsonify({
            "error":   "ERR_INVALID_MARKUP",
            "message": "markup_bps must be 100–10000 (1%–100%)",
        }), 400

    # ── Credit Bureau gate ────────────────────────────────────────────────────
    bureau = _bureau_score(wallet)
    bureau_verified = not bureau.get("offline")

    if bureau_verified:
        score = bureau.get("score", 300)
        grade = bureau.get("grade", "D")
        if score < _MIN_SCORE:
            return jsonify({
                "error":          "ERR_SCORE_TOO_LOW",
                "message":        f"Relay node registration requires Credit Bureau score ≥ {_MIN_SCORE}. Your score: {score} ({grade}).",
                "current_score":  score,
                "current_grade":  grade,
                "required_score": _MIN_SCORE,
                "remedy": {
                    "build_score":  "Make RLUSD payments through SqueezeOS to increase your score (~10 payments to qualify)",
                    "check_score":  f"{_BUREAU_URL}/v1/bureau/score/{wallet}",
                    "full_report":  f"{_BUREAU_URL}/v1/bureau/report/{wallet}",
                    "standard_api": "https://squeezeos-terminal.vercel.app/api/council",
                },
            }), 403
    else:
        score, grade = None, None
        logger.warning(f"[RELAY] Bureau offline — registering {wallet[:12]} without score gate")

    relay_id = str(uuid.uuid4())[:8]
    _registry[wallet] = {
        "relay_id":       relay_id,
        "wallet":         wallet,
        "markup_bps":     markup_bps,
        "relay_url":      relay_url,
        "description":    description,
        "registered_at":  time.time(),
        "active":         True,
        "bureau_score":   score,
        "bureau_grade":   grade,
        "bureau_verified": bureau_verified,
    }

    logger.info(f"[RELAY] New node: {wallet[:12]}… markup={markup_bps}bps score={score}")

    return jsonify({
        "status":         "REGISTERED",
        "relay_id":       relay_id,
        "wallet":         wallet,
        "markup_bps":     markup_bps,
        "bureau_score":   score,
        "bureau_verified": bureau_verified,
        "bulk_endpoints": RELAY_ENDPOINTS,
        "note": (
            "Use bulk endpoint IDs above when calling POST /v1/invoice at "
            "four02proof.onrender.com. These IDs grant 40% discount rates "
            "exclusively to registered relay nodes. Sell to downstream agents "
            "at your own markup — the spread is yours."
        ),
    }), 201


@relay_bp.route('/nodes', methods=['GET'])
def list_nodes():
    """Public relay node directory — agents use this to discover relay options."""
    nodes = [
        {
            "relay_id":   n["relay_id"],
            "wallet":     n["wallet"],
            "markup_bps": n["markup_bps"],
            "relay_url":  n["relay_url"],
            "description": n["description"],
            "since":      n["registered_at"],
        }
        for n in _registry.values()
        if n.get("active")
    ]
    nodes.sort(key=lambda x: x["markup_bps"])  # cheapest relay first
    return jsonify({
        "nodes":      nodes,
        "count":      len(nodes),
        "endpoints":  RELAY_ENDPOINTS,
        "ts":         time.time(),
    })


@relay_bp.route('/verify/<wallet>', methods=['GET'])
def verify_node(wallet):
    """Free check — is this wallet a registered relay node?"""
    node = _registry.get(wallet)
    if not node or not node.get("active"):
        return jsonify({"wallet": wallet, "is_relay": False})
    return jsonify({
        "wallet":     wallet,
        "is_relay":   True,
        "relay_id":   node["relay_id"],
        "markup_bps": node["markup_bps"],
    })


@relay_bp.route('/unregister', methods=['POST'])
def unregister():
    """Remove a relay node from the registry."""
    body = request.get_json(silent=True) or {}
    wallet = (body.get('wallet') or '').strip()
    if not wallet or wallet not in _registry:
        return jsonify({"error": "relay node not found"}), 404
    _registry[wallet]["active"] = False
    return jsonify({"status": "UNREGISTERED", "wallet": wallet})


@relay_bp.route('/endpoints', methods=['GET'])
def relay_endpoints():
    """Machine-readable bulk endpoint IDs and discount pricing for relay nodes."""
    return jsonify({
        "endpoints":  RELAY_ENDPOINTS,
        "discount":   "40% off standard pricing for registered relay nodes",
        "gateway":    "https://four02proof.onrender.com",
        "register_at": "/api/relay/register",
    })
