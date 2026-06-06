"""
x402_flask.py — Protocol-compliant x402 paywall for the SqueezeOS Flask API.
Real x402 wire protocol (HTTP 402 -> accepts -> X-PAYMENT -> facilitator /verify+/settle)
on USDC over Base. Makes endpoints payable by any x402 agent and discoverable in the
x402 Bazaar when routed through the CDP facilitator.

Dual-rail 402 body: every payment-required response advertises BOTH rails so that
- Standard x402 / Base / USDC agents pick the EVM entry and pay via facilitator.
- RLUSD / XRPL agents pick the XRPL entry and pay via the 402Proof invoice flow
  (POST /v1/invoice → pay on XRPL → POST /v1/verify → retry with X-Payment-Token).
"""

import os
import json
import base64
import requests
from functools import wraps
from flask import request, jsonify, make_response

X402_VERSION = 1

NETWORK      = os.environ.get("X402_NETWORK", "base-sepolia")
PAY_TO       = os.environ.get("X402_PAY_TO", "0x4e14B249D9A4c9c9352D780eCEB508A8eB7a7700")
FACILITATOR  = os.environ.get("X402_FACILITATOR", "https://x402.org/facilitator").rstrip("/")
MAX_TIMEOUT  = int(os.environ.get("X402_MAX_TIMEOUT", "120"))

# ── RLUSD on XRPL rail (proprietary 402Proof flow) ──
RLUSD_ISSUER  = os.environ.get("RLUSD_ISSUER",  "rMxCKbEDwqr76QuheSUMdEGf4B9xJ8m5De")
PROOF402_BASE = os.environ.get("PROOF402_SERVER_URL", "https://four02proof.onrender.com").rstrip("/")

USDC = {
    "base":         {"asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
                     "extra": {"name": "USD Coin", "version": "2"}},
    "base-sepolia": {"asset": "0x036CbD53842c5426634e7929541eC2318f3dCF7e",
                     "extra": {"name": "USDC", "version": "2"}},
}

DISCOVERY = []


def _usdc_atomic(price_usdc: str) -> str:
    return str(int(round(float(price_usdc) * 1_000_000)))


def _payment_requirements(price_usdc: str, description: str, resource: str) -> dict:
    cfg = USDC.get(NETWORK, USDC["base-sepolia"])
    return {
        "scheme": "exact",
        "network": NETWORK,
        "maxAmountRequired": _usdc_atomic(price_usdc),
        "resource": resource,
        "description": description,
        "mimeType": "application/json",
        "payTo": PAY_TO,
        "maxTimeoutSeconds": MAX_TIMEOUT,
        "asset": cfg["asset"],
        "extra": cfg["extra"],
    }


def _rlusd_requirements(price_rlusd: str, description: str, resource: str) -> dict:
    """
    XRPL/RLUSD entry for the 402 `accepts` array.

    Not native x402 (XRPL has no x402 facilitator), so agents that match this
    entry use the 402Proof invoice/verify flow declared under `extra.flow`.
    Endpoint UUID is looked up by path so the agent can POST it straight to
    /v1/invoice without an extra discovery round-trip.
    """
    try:
        from proof402_integration import ENDPOINTS as _RLUSD_ENDPOINTS
    except Exception:
        _RLUSD_ENDPOINTS = {}

    from urllib.parse import urlparse
    path = urlparse(resource).path or ""
    endpoint_id = _RLUSD_ENDPOINTS.get(path, "")

    return {
        "scheme": "xrpl-invoice",
        "network": "xrpl",
        "maxAmountRequired": str(price_rlusd),
        "resource": resource,
        "description": description,
        "mimeType": "application/json",
        "payTo": os.environ.get("XRPL_PAY_TO", "rUJhaK2ibfTFVdAn8m9jMCcJQ1xo6FmNPZ"),
        "maxTimeoutSeconds": MAX_TIMEOUT,
        "asset": "RLUSD",
        "extra": {
            "name": "Ripple USD",
            "issuer": RLUSD_ISSUER,
            "endpointId": endpoint_id,
            "invoiceEndpoint": f"{PROOF402_BASE}/v1/invoice",
            "verifyEndpoint":  f"{PROOF402_BASE}/v1/verify",
            "tokenHeader":     "X-Payment-Token",
            "walletHeader":    "X-Agent-Wallet",
            "flow": [
                f"1. POST {PROOF402_BASE}/v1/invoice {{\"endpoint_id\":\"{endpoint_id}\"}} → {{pay_to, amount, memo_hex}}",
                "2. Send RLUSD on XRPL to pay_to with memo_hex as MemoData",
                f"3. POST {PROOF402_BASE}/v1/verify {{invoice_id, tx_hash, agent_wallet}} → access_token (1h TTL)",
                f"4. Retry {path} with X-Payment-Token: <access_token> and X-Agent-Wallet: <rWALLET>",
            ],
        },
    }


def _402(requirements: dict, reason: str = ""):
    accepts = [requirements]
    rlusd = _rlusd_requirements(
        price_rlusd=str(float(requirements["maxAmountRequired"]) / 1_000_000),
        description=requirements["description"],
        resource=requirements["resource"],
    )
    accepts.append(rlusd)
    body = {"x402Version": X402_VERSION, "accepts": accepts, "error": reason}
    resp = make_response(jsonify(body), 402)
    resp.headers["Content-Type"] = "application/json"
    return resp


def _facilitator(path: str, payment_payload: dict, requirements: dict) -> dict:
    r = requests.post(
        f"{FACILITATOR}{path}",
        json={"x402Version": X402_VERSION,
              "paymentPayload": payment_payload,
              "paymentRequirements": requirements},
        timeout=30,
    )
    try:
        return r.json()
    except Exception:
        return {"isValid": False, "success": False, "invalidReason": f"facilitator {r.status_code}"}


def x402_guard(price_usdc: str, description: str, discoverable: bool = True):
    def decorator(fn):
        if discoverable:
            DISCOVERY.append({"price_usdc": price_usdc, "description": description, "fn": fn.__name__})

        @wraps(fn)
        def wrapper(*args, **kwargs):
            resource = request.base_url
            reqs = _payment_requirements(price_usdc, description, resource)

            header = request.headers.get("X-PAYMENT")
            if not header:
                return _402(reqs, "payment required")

            try:
                payment_payload = json.loads(base64.b64decode(header))
            except Exception:
                return _402(reqs, "malformed X-PAYMENT header")

            verify = _facilitator("/verify", payment_payload, reqs)
            if not verify.get("isValid", False):
                return _402(reqs, f"invalid payment: {verify.get('invalidReason', 'unknown')}")

            result = fn(*args, **kwargs)

            settle = _facilitator("/settle", payment_payload, reqs)
            resp = make_response(result)
            if settle.get("success", False):
                resp.headers["X-PAYMENT-RESPONSE"] = base64.b64encode(
                    json.dumps(settle).encode()).decode()
            return resp
        return wrapper
    return decorator


def register_x402_discovery(app):
    @app.route("/.well-known/x402")
    def _x402_discovery():
        cfg = USDC.get(NETWORK, USDC["base-sepolia"])
        return jsonify({
            "x402Version": X402_VERSION,
            "operator": "ScriptMasterLabs",
            "discoverable": True,
            "rails": [
                {
                    "name": "Base / USDC (x402 standard)",
                    "network": NETWORK,
                    "asset": cfg["asset"],
                    "assetSymbol": "USDC",
                    "payTo": PAY_TO,
                    "facilitator": FACILITATOR,
                    "scheme": "exact",
                },
                {
                    "name": "XRPL / RLUSD (402Proof invoice flow)",
                    "network": "xrpl",
                    "asset": "RLUSD",
                    "assetIssuer": RLUSD_ISSUER,
                    "invoiceEndpoint": f"{PROOF402_BASE}/v1/invoice",
                    "verifyEndpoint":  f"{PROOF402_BASE}/v1/verify",
                    "scheme": "xrpl-invoice",
                },
            ],
            "resources": [
                {"path": d["fn"],
                 "price": {"amount": d["price_usdc"], "assets": ["USDC", "RLUSD"]},
                 "description": d["description"]}
                for d in DISCOVERY
            ],
        })
    return app
