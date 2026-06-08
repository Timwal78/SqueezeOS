import os
import json
import hashlib
import requests
import logging
from flask import Blueprint, request, jsonify

logger = logging.getLogger("SqueezeOS-Notary")

notary_bp = Blueprint("notary", __name__)

GHOST_LAYER_URL = os.environ.get("GHOST_LAYER_URL", "http://localhost:4002").rstrip("/")

@notary_bp.route("/decision", methods=["POST"])
def notarize_decision():
    """
    Proxy endpoint for the AI Decision Notary.
    Hashes the decision payload and forwards the X-Payment-Token to the Ghost Layer.
    """
    token = request.headers.get("X-Payment-Token", "")
    payload = request.get_json(silent=True)
    
    if not payload:
        return jsonify({"error": "BAD_REQUEST", "message": "Decision JSON payload is required"}), 400

    # 1. Hash the decision payload deterministically
    payload_str = json.dumps(payload, sort_keys=True)
    decision_hash = hashlib.sha256(payload_str.encode('utf-8')).hexdigest()

    # We augment the payload with the computed hash so Ghost Layer can use it.
    # Ghost Layer expects whatever payload it needs for its mint flow.
    # We will pass the full original payload + the hash.
    proxy_payload = {
        "decision": payload,
        "decision_hash": decision_hash
    }

    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Payment-Token"] = token

    target_url = f"{GHOST_LAYER_URL}/v1/notarize"
    
    try:
        resp = requests.post(target_url, json=proxy_payload, headers=headers, timeout=15)
    except requests.exceptions.RequestException as e:
        logger.error(f"[Notary] Ghost Layer unreachable at {target_url}: {e}")
        return jsonify({"error": "GHOST_LAYER_OFFLINE", "message": "The Ghost Layer is currently unreachable."}), 503

    # Pass the Ghost Layer response back to the client natively
    try:
        resp_json = resp.json()
    except Exception:
        return jsonify({
            "error": "BAD_GATEWAY",
            "message": "Ghost Layer returned an invalid JSON response.",
            "status_code": resp.status_code,
            "raw": resp.text[:200]
        }), 502

    return jsonify(resp_json), resp.status_code
