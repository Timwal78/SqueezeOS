"""
Decision Notary — SqueezeOS → Ghost Layer Xahau bridge.

When an agent makes a high-conviction call from SqueezeOS (council verdict,
oracle directive, RDT ranking), they can have it minted as a Xahau URIToken
for permanent, tamper-evident proof. Useful for:

  • EU AI Act audit trails for autonomous trading bots
  • Provable "we called it first" timestamps for signal marketplaces
  • Cryptographic receipts for marketplace listings that get challenged

Architecture (zero custody):

       agent
         │  POST /api/notary/notarize  + X-Payment-Token (paid to Ghost Layer)
         ▼
    SqueezeOS  ─── canonicalizes verdict ──►  Ghost Layer  ──►  Xahau URITokenMint
         │                                         │
         └───────  combined receipt  ◄─────────────┘

SqueezeOS never touches the agent's payment — the X-Payment-Token is verified
upstream by Ghost Layer against ITS treasury. SqueezeOS just shapes the
payload so the verdict gets notarized in canonical form (same fields, same
ordering) every time. The Xahau tx hash and certificate flow back unmodified.

  GET  /api/notary/info       — discovery: three notary tiers + prices
  POST /api/notary/notarize   — proxy a verdict to Ghost Layer for minting
  POST /api/notary/quote      — canonicalize a verdict; return decision_hash preview

Mandate: SqueezeOS DOES NOT CUSTODY funds. The payment is between the agent
and Ghost Layer; SqueezeOS is a translation/canonicalization layer only.
"""

import hashlib
import json
import logging
import os
import time

import requests
from flask import Blueprint, jsonify, request

from core.legacy import clean_data

logger = logging.getLogger("SqueezeOS-Notary")
notary_bp = Blueprint("notary", __name__)

GHOST_LAYER_BASE = os.environ.get("GHOST_LAYER_BASE_URL", "https://ghost-layer.onrender.com").rstrip("/")
NOTARY_FORWARD_TIMEOUT = float(os.environ.get("NOTARY_FORWARD_TIMEOUT_S", "20"))

# Tier prices come from Ghost Layer's x402 registry (`/v1/notarize`).
# Mirrored here for `/api/notary/info` so agents can discover prices
# without round-tripping through a 402 challenge.
_TIERS = {
    "decision.notarize":           {"base_price_rlusd": 0.001, "name": "Standard",  "includes": "URIToken + memo"},
    "decision.notarize.certified": {"base_price_rlusd": 0.010, "name": "Certified", "includes": "Standard + Ed25519 certificate"},
    "decision.notarize.sovereign": {"base_price_rlusd": 0.050, "name": "Sovereign", "includes": "Certified + SOVEREIGN grade"},
}


def _err(msg: str, code: int = 400):
    return jsonify({"error": msg}), code


def _canonical_payload(verdict: dict, symbol: str = "", source: str = "") -> dict:
    """Build a stable, ordered payload for notarization. Same inputs → same hash.

    Field order matters: Xahau memo bytes are hashed downstream. We freeze
    the field set so future verifiers can reproduce the exact hash from the
    Xahau memo without ambiguity."""
    return {
        "schema":     "squeezeos.verdict.v1",
        "source":     source or "squeezeos",
        "symbol":     symbol.upper(),
        "verdict":    verdict,
        "issued_at":  int(time.time()),
    }


def _preview_hash(payload: dict) -> str:
    """Reproduces Ghost Layer's hash construction so the agent can verify
    the certificate matches what they expected to be notarized. Ghost
    Layer uses SHA-512 first 32 bytes of the canonicalized memo JSON."""
    memo_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha512(memo_bytes).hexdigest()[:64]


@notary_bp.route("/info", methods=["GET"])
def info():
    """Discovery: what notarization tiers are available and how much they cost."""
    return jsonify({
        "ghost_layer": GHOST_LAYER_BASE,
        "notarize_endpoint": f"{GHOST_LAYER_BASE}/v1/notarize",
        "tiers": _TIERS,
        "loyalty_discounts": {
            "BRONZE":   "0%",
            "SILVER":   "5%",
            "GOLD":     "10%",
            "PLATINUM": "20%",
            "DIAMOND":  "30%",
        },
        "settlement_chain": "Xahau",
        "proof_format":     "URIToken + signed Ed25519 certificate",
        "custody":          "zero — Ghost Layer mints, SqueezeOS never touches funds",
        "ts":               time.time(),
    })


@notary_bp.route("/quote", methods=["POST"])
def quote():
    """Preview the decision_hash for a verdict before paying to mint.

    Lets an agent confirm what exact bytes would be notarized. Doesn't
    talk to Ghost Layer; pure local canonicalization.

    Body:
      symbol         str   — ticker the verdict applies to
      verdict        dict  — the council/oracle output to notarize
      source         str?  — defaults to "squeezeos"
    """
    body = request.get_json(silent=True) or {}
    verdict = body.get("verdict")
    if not isinstance(verdict, dict) or not verdict:
        return _err("verdict (object) required")
    symbol = (body.get("symbol") or "").strip()
    if not symbol:
        return _err("symbol required")

    payload = _canonical_payload(verdict, symbol=symbol, source=body.get("source", ""))
    return jsonify(clean_data({
        "decision_hash_preview": _preview_hash(payload),
        "canonical_payload":     payload,
        "note": "This is a preview; the on-chain hash is computed by Ghost Layer at mint time.",
    }))


@notary_bp.route("/notarize", methods=["POST"])
def notarize():
    """
    Proxy a SqueezeOS verdict to Ghost Layer's /v1/notarize for Xahau minting.

    The agent's X-Payment-Token header is forwarded unchanged — Ghost Layer
    is the sole verifier. If the header is missing, the agent gets back
    Ghost Layer's 402 challenge directly (with the invoice). SqueezeOS
    NEVER inspects or stores payment tokens.

    Body:
      symbol         str   — ticker the verdict applies to (required)
      verdict        dict  — the verdict object to notarize (required)
      source         str?  — origin tag (default "squeezeos")
      model          str?  — model identifier for the certificate
      agent_wallet   str?  — defaults to the token's wallet
      endpoint       str?  — context tag for the certificate

    Returns:
      Ghost Layer's response unchanged on success (xahau_tx, decision_hash,
      certificate?). On 402, the X-Payment-Required invoice header is
      relayed in the JSON body as `payment_required`.
    """
    body = request.get_json(silent=True) or {}
    verdict = body.get("verdict")
    if not isinstance(verdict, dict) or not verdict:
        return _err("verdict (object) required")
    symbol = (body.get("symbol") or "").strip()
    if not symbol:
        return _err("symbol required")

    payload = _canonical_payload(verdict, symbol=symbol, source=body.get("source", ""))

    forward_body = {
        "payload":      payload,
        "model":        body.get("model", ""),
        "agent_wallet": body.get("agent_wallet", ""),
        "endpoint":     body.get("endpoint", "/api/notary/notarize"),
    }

    headers = {"Content-Type": "application/json"}
    token = request.headers.get("X-Payment-Token", "")
    if token:
        headers["X-Payment-Token"] = token

    try:
        resp = requests.post(
            f"{GHOST_LAYER_BASE}/v1/notarize",
            json=forward_body,
            headers=headers,
            timeout=NOTARY_FORWARD_TIMEOUT,
        )
    except requests.RequestException as e:
        logger.error("ghost-layer notarize unreachable: %s", e)
        return _err(f"ghost layer unreachable: {e}", 503)

    try:
        upstream = resp.json()
    except ValueError:
        upstream = {"raw": resp.text[:500]}

    if resp.status_code == 402:
        invoice_header = resp.headers.get("X-Payment-Required", "")
        return jsonify({
            "payment_required": True,
            "invoice":          upstream,
            "invoice_header":   invoice_header,
            "ghost_layer":      f"{GHOST_LAYER_BASE}/v1/notarize",
            "hint":             "Pay the invoice on XRPL, then resubmit with X-Payment-Token header.",
        }), 402

    if resp.status_code >= 400:
        logger.warning("notarize upstream %s: %s", resp.status_code, str(upstream)[:200])
        return jsonify({"error": "ghost_layer_error", "status": resp.status_code, "detail": upstream}), resp.status_code

    logger.info(
        "[NOTARY] minted symbol=%s xahau_tx=%s",
        symbol,
        str(upstream.get("xahau_tx", ""))[:16],
    )
    return jsonify(clean_data({
        "status":       "notarized",
        "symbol":       symbol,
        "ghost_layer":  upstream,
        "ts":           time.time(),
    }))
