"""VAPL Blueprint — trust discovery + VC verification for SqueezeOS.

Routes:
  GET  /.well-known/vapl.json   Provenance Soul manifest (discovery)
  GET  /api/vapl/soul           Public soul info (DID + public key)
  POST /api/vapl/verify         Verify any VAPL VC offline
  GET  /api/vapl/reputation     Compute reputation score for a DID
"""
from __future__ import annotations

import json

from flask import Blueprint, jsonify, request

from core.vapl.soul_manager import get_soul
from core.vapl.credentials import verify_vc
from core.vapl.reputation import compute_reputation_score
from core.vapl.discovery import generate_provenance_soul_manifest

vapl_bp = Blueprint("vapl", __name__)

_CAPABILITIES = [
    "CouncilVerdict", "SqueezeOSScan", "OptionsFlowFetch",
    "IWMScoreFetch", "MCPToolCall", "AlphaMeshContribution",
]


@vapl_bp.route("/.well-known/vapl.json")
def vapl_manifest():
    soul = get_soul()
    manifest = generate_provenance_soul_manifest(
        did=soul.did,
        public_key_multibase=soul.public_key_multibase,
        credentials=[],
        capabilities=_CAPABILITIES,
        trusted_issuers=[soul.did],
    )
    manifest["service"] = "SqueezeOS"
    manifest["endpoint"] = "https://squeezeos-api.onrender.com"
    manifest["registry"] = "https://vapl-registry.onrender.com"
    manifest["vcHeadersEmitted"] = True
    manifest["vcHeader"] = "X-VAPL-VC"
    resp = jsonify(manifest)
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp


@vapl_bp.route("/api/vapl/soul")
def soul_info():
    soul = get_soul()
    return jsonify({
        "did": soul.did,
        "verificationMethod": soul.verification_method_id,
        "publicKeyMultibase": soul.public_key_multibase,
        "service": "SqueezeOS",
        "endpoint": "https://squeezeos-api.onrender.com",
        "capabilities": _CAPABILITIES,
    })


@vapl_bp.route("/api/vapl/verify", methods=["POST"])
def verify_credential():
    body = request.get_json(silent=True) or {}
    credential = body.get("credential")
    trusted_issuers = body.get("trustedIssuers")

    if not credential:
        return jsonify({"error": "credential required"}), 400

    result = verify_vc(credential, trusted_issuers=trusted_issuers)
    return jsonify(result)


@vapl_bp.route("/api/vapl/reputation")
def reputation():
    did = request.args.get("did")
    if not did:
        return jsonify({"error": "did query param required"}), 400

    raw = request.args.get("credentials", "[]")
    try:
        credentials = json.loads(raw)
    except Exception:
        return jsonify({"error": "credentials must be a JSON array"}), 400

    score = compute_reputation_score(credentials, did)
    return jsonify({"did": did, "reputation": score})
