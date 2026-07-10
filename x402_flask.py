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
import time
import json
import base64
import secrets
import requests
from functools import wraps
from urllib.parse import urlparse
from flask import request, jsonify, make_response

X402_VERSION = 2

# ── PRODUCTION FIX (2026-07-10) ──────────────────────────────────────────
# Was defaulting to base-sepolia (TESTNET) against x402.org/facilitator, a
# community facilitator whose own discovery catalog is explicitly NOT the
# Coinbase CDP Bazaar (confirmed in CDP docs: x402.org/facilitator/discovery
# is a separate testnet-only index). Result: zero possible real revenue on
# this rail, and zero chance of Bazaar/Agent.market listing, regardless of
# demand. Now defaults to Base MAINNET routed through CDP's real facilitator,
# with CDP JWT auth attached so /verify and /settle actually authenticate.
NETWORK      = os.environ.get("X402_NETWORK", "base")
PAY_TO       = os.environ.get("X402_PAY_TO", "0x4e14B249D9A4c9c9352D780eCEB508A8eB7a7700")
FACILITATOR  = os.environ.get("X402_FACILITATOR", "https://api.cdp.coinbase.com/platform/v2/x402").rstrip("/")
MAX_TIMEOUT  = int(os.environ.get("X402_MAX_TIMEOUT", "120"))

# ── CDP API key auth (required by api.cdp.coinbase.com; x402.org/facilitator
#    didn't need this, which is part of why it was easy to leave misconfigured) ──
CDP_API_KEY_ID     = os.environ.get("CDP_API_KEY_ID", "")
CDP_API_KEY_SECRET = os.environ.get("CDP_API_KEY_SECRET", "")  # PEM EC private key, \n-escaped
_CDP_HOST          = urlparse(FACILITATOR).netloc or "api.cdp.coinbase.com"


def _cdp_jwt(method: str, path: str) -> "str | None":
    """
    Build a CDP Bearer JWT per Coinbase's documented JWT auth scheme:
    ES256, 2-minute expiry, kid+nonce headers, sub/iss/nbf/exp/uri claims.
    Returns None (no auth header) if CDP creds aren't configured yet, so a
    misconfigured deploy fails loudly via a 401 from CDP instead of silently
    hitting an unauthenticated testnet facilitator like before.
    """
    if not CDP_API_KEY_ID or not CDP_API_KEY_SECRET:
        return None
    try:
        import jwt as _pyjwt
        from cryptography.hazmat.primitives import serialization
        private_key = serialization.load_pem_private_key(
            CDP_API_KEY_SECRET.encode("utf-8"), password=None
        )
        now = int(time.time())
        payload = {
            "sub": CDP_API_KEY_ID,
            "iss": "cdp",
            "nbf": now,
            "exp": now + 120,
            "uri": f"{method} {_CDP_HOST}{path}",
        }
        return _pyjwt.encode(
            payload, private_key, algorithm="ES256",
            headers={"kid": CDP_API_KEY_ID, "nonce": secrets.token_hex()},
        )
    except Exception as e:
        import logging
        logging.error(f"[x402] CDP JWT build failed, request will be unauthenticated: {e}")
        return None

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
    cfg = USDC.get(NETWORK, USDC["base"])
    units = _usdc_atomic(price_usdc)
    return {
        "scheme": "exact",
        "network": NETWORK,
        # x402 v2 wants both: `amount` is the field the validator checks;
        # `maxAmountRequired` is kept because our own facilitator chain
        # settles off it. Confirmed against a live sibling deployment
        # (SML_Portfolio/mcp-x402) whose engineering notes record this
        # exact validator requirement — not a guess.
        "amount": units,
        "maxAmountRequired": units,
        "resource": resource,
        "description": description,
        "mimeType": "application/json",
        "payTo": PAY_TO,
        "maxTimeoutSeconds": MAX_TIMEOUT,
        "asset": cfg["asset"],
        "extra": cfg["extra"],
    }


def _rlusd_requirements(price_rlusd: str, description: str, resource: str) -> "dict | None":
    """
    XRPL/RLUSD entry for the 402 `accepts` array.

    Not native x402 (XRPL has no x402 facilitator), so agents that match this
    entry use the 402Proof invoice/verify flow declared under `extra.flow`.
    Endpoint UUID is looked up by path so the agent can POST it straight to
    /v1/invoice without an extra discovery round-trip.

    SML fix: previously fell back to a hardcoded wallet
    (rUJhaK2ibfTFVdAn8m9jMCcJQ1xo6FmNPZ) nobody on the team recognized or
    held the key to when XRPL_PAY_TO wasn't set — a real risk, since a
    naive x402 client can pay the top-level `payTo` field directly without
    following the documented invoice/verify flow. Returns None instead so
    the caller omits this rail entirely rather than ever advertising an
    unconfigured/unrecognized wallet as a place to send real money.
    """
    xrpl_pay_to = os.environ.get("XRPL_PAY_TO", "")
    if not xrpl_pay_to:
        return None

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
        "amount": str(price_rlusd),
        "maxAmountRequired": str(price_rlusd),
        "resource": resource,
        "description": description,
        "mimeType": "application/json",
        "payTo": xrpl_pay_to,
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
    if rlusd is not None:
        accepts.append(rlusd)
    body = {
        "x402Version": X402_VERSION,
        "error": reason,
        # v2 top-level `resource` is an OBJECT, not the plain string each
        # accept entry still carries for backward compat. Missing this was
        # confirmed (via the sibling mcp-x402 deployment's own debugging
        # history) to make x402scan/Bazaar discovery reject the response
        # outright rather than just flag it as outdated.
        "resource": {
            "url": requirements["resource"],
            "description": requirements["description"],
            "mimeType": requirements["mimeType"],
        },
        "accepts": accepts,
    }
    resp = make_response(jsonify(body), 402)
    resp.headers["Content-Type"] = "application/json"
    return resp


def _facilitator(path: str, payment_payload: dict, requirements: dict) -> dict:
    headers = {}
    token = _cdp_jwt("POST", f"{urlparse(FACILITATOR).path}{path}")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    body = {"x402Version": X402_VERSION,
            "paymentPayload": payment_payload,
            "paymentRequirements": requirements}

    # Bazaar discovery extension: CDP indexes a route the first time /settle
    # succeeds for it AND the settle call carries this metadata blob. Omitting
    # it means real mainnet payments could clear fine while the route stays
    # invisible to Agent.market forever — a second, quieter way to look "paid
    # up" but never get discovered.
    if path == "/settle":
        body["extensions"] = {
            "bazaar": {
                "discoverable": True,
                "resource": requirements["resource"],
                "description": requirements["description"],
                "outputSchema": {"type": "object", "properties": {}},
            }
        }

    r = requests.post(f"{FACILITATOR}{path}", json=body, headers=headers, timeout=30)
    try:
        return r.json()
    except Exception:
        return {"isValid": False, "success": False, "invalidReason": f"facilitator {r.status_code}: {r.text[:200]}"}


def x402_guard(price_usdc: str, description: str, discoverable: bool = True):
    def decorator(fn):
        if discoverable:
            DISCOVERY.append({"price_usdc": price_usdc, "description": description, "fn": fn.__name__})

        @wraps(fn)
        def wrapper(*args, **kwargs):
            resource = request.base_url
            reqs = _payment_requirements(price_usdc, description, resource)

            # ── Operator/agent key bypass ──
            # Mirrors proof402_integration.require_payment's bypass exactly:
            # a request carrying a valid OPERATOR_API_KEY / OWNER_API_KEY / one
            # of AGENT_API_KEYS skips on-chain x402 settlement. Needed for
            # agents (e.g. LEVIATHAN) that already collected payment upstream
            # via ACP and are calling this route as an authorized backend, not
            # as a paying end-user — this decorator previously had no such
            # bypass, so every ACP-resold job routed through it 402'd even
            # after the buyer had already paid LEVIATHAN.
            auth_header = request.headers.get("Authorization", "")
            bearer_key = auth_header.split("Bearer ")[-1].strip() if "Bearer " in auth_header else ""
            passed_key = (
                request.headers.get("X-Owner-Key")
                or request.headers.get("X-API-Key")
                or bearer_key
            )
            agent_keys = [k.strip() for k in os.environ.get("AGENT_API_KEYS", "").split(",") if k.strip()]
            valid_keys = [k for k in [os.environ.get("OPERATOR_API_KEY"), os.environ.get("OWNER_API_KEY")] if k] + agent_keys
            if passed_key and passed_key in valid_keys:
                return fn(*args, **kwargs)

            # ── AP2 mandate gate (Google Agent Payments Protocol) ──
            # Modes via env AP2_MODE: "off" | "optional" (default) | "required"
            ap2_mode = os.environ.get("AP2_MODE", "optional").lower()
            if ap2_mode != "off":
                try:
                    from ap2_mandate import verify_mandate, mandate_from_request
                    mandate = mandate_from_request(request.headers)
                    if mandate is not None:
                        verdict = verify_mandate(mandate, {
                            "resource": resource,
                            "amountAtomicUSDC": int(reqs["maxAmountRequired"]),
                            "payTo": PAY_TO,
                            "trustedIssuers": json.loads(os.environ.get("AP2_TRUSTED_ISSUERS", "{}")),
                        })
                        if not verdict["valid"]:
                            return _402(reqs, f"AP2 mandate invalid: {verdict['reason']}")
                    elif ap2_mode == "required":
                        return _402(reqs, "AP2 mandate required: send X-AP2-MANDATE header (base64 VC bundle)")
                except ImportError:
                    pass  # ap2 module unavailable — fall through to pure x402

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
                # SML fix: the RLUSD rail (proof402_integration.require_payment)
                # has always fired a Discord payment alert on success — this
                # Coinbase/USDC rail never did, so a real settled payment left
                # zero trace anywhere except the on-chain transfer itself. An
                # $8 USDC payment surfaced with no record in Discord or the
                # in-memory analytics funnel (which also resets on every
                # redeploy) before this was caught.
                try:
                    from proof402_integration import _fire_payment_discord
                    payer = (
                        settle.get("payer")
                        or payment_payload.get("payload", {}).get("authorization", {}).get("from", "")
                        or "unknown"
                    )
                    _fire_payment_discord(payer, request.path, 2)
                except Exception:
                    pass
            return resp
        return wrapper
    return decorator


def register_x402_discovery(app):
    @app.route("/.well-known/x402")
    def _x402_discovery():
        cfg = USDC.get(NETWORK, USDC["base"])
        return jsonify({
            "x402Version": X402_VERSION,
            "operator": "ScriptMasterLabs",
            "discoverable": True,
            "ap2": {
                "supported": True,
                "mode": os.environ.get("AP2_MODE", "optional"),
                "mandate_header": "X-AP2-MANDATE",
                "spec": "https://ap2-protocol.org/specification/",
                "note": "AP2 Intent/Cart/Payment mandates (W3C VCs) verified before honoring agent payments.",
            },
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
