"""VAPL Flask middleware for SqueezeOS.

Attaches to every successful (2xx) API response:
  X-VAPL-VC        base64url(JSON(InteractionCredential))
  X-VAPL-Issuer    did:key:z6Mk...  (SqueezeOS service DID)
  X-VAPL-VC-ID     urn:vapl:vc:...  (unique VC identifier)

The credential's subject is the calling agent's DID derived from X-Agent-Wallet,
or a generic "anonymous" DID when no wallet header is present.
Only fires on /api/* paths to avoid polluting static file responses.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging

from flask import request

from .credentials import issue_interaction_vc
from .soul_manager import get_soul

log = logging.getLogger("vapl.middleware")

# Paths exempt from VC emission (health/keepalive/static)
_EXEMPT_PREFIXES = ("/health", "/robots", "/sitemap", "/llms", "/openapi",
                    "/vapl/verify", "/vapl/reputation", "/vapl/soul")

_ENDPOINT_TYPE_MAP: dict[str, str] = {
    "/api/council":          "CouncilVerdict",
    "/api/scan":             "SqueezeOSScan",
    "/api/options":          "OptionsFlowFetch",
    "/api/iwm":              "IWMScoreFetch",
    "/api/marketplace/read": "MarketplaceRead",
    "/api/marketplace":      "MarketplaceListing",
    "/api/futures":          "FuturesPrediction",
    "/api/settlement":       "SettlementResolution",
    "/api/hiring":           "AgentHire",
    "/api/relay":            "RelayRoute",
    "/api/webhooks":         "WebhookSubscription",
    "/api/graph":            "AlphaMeshContribution",
    "/api/preview":          "SqueezeOSScan",
    "/api/oracle":           "CouncilVerdict",
    "/api/history":          "SqueezeOSScan",
    "/api/demo":             "SqueezeOSScan",
    "/api/status":           "SystemHealthCheck",
    "/mcp":                  "MCPToolCall",
}


def _interaction_type(path: str) -> str:
    for prefix, itype in _ENDPOINT_TYPE_MAP.items():
        if path.startswith(prefix):
            return itype
    return "CouncilVerdict"


def _agent_did(wallet: str) -> str:
    """Derive a stable pseudonymous DID from an agent wallet address."""
    if wallet and len(wallet) >= 10:
        h = hashlib.sha256(wallet.lower().encode()).digest()[:32]
        return f"did:x402:{base64.urlsafe_b64encode(h).rstrip(b'=').decode()}"
    return "did:x402:anonymous"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def install_vapl_middleware(app) -> None:
    """Register the VAPL after_request hook on a Flask app."""

    @app.after_request
    def emit_vapl_vc(response):
        try:
            path = request.path
            if not path.startswith("/api/") and not path.startswith("/mcp"):
                return response
            if any(path.startswith(p) for p in _EXEMPT_PREFIXES):
                return response
            if response.status_code < 200 or response.status_code >= 300:
                return response

            soul = get_soul()
            wallet = request.headers.get("X-Agent-Wallet", "")
            subject_did = _agent_did(wallet)
            itype = _interaction_type(path)
            outcome = "success" if response.status_code < 300 else "error"

            vc = issue_interaction_vc(
                soul=soul,
                subject_did=subject_did,
                interaction_type=itype,
                resource=f"https://squeezeos-api.onrender.com{path}",
                outcome=outcome,
            )

            vc_json = json.dumps(vc, separators=(",", ":"))
            vc_b64 = _b64url(vc_json.encode())
            response.headers["X-VAPL-VC"] = vc_b64
            response.headers["X-VAPL-Issuer"] = soul.did
            response.headers["X-VAPL-VC-ID"] = vc.get("id", "")
        except Exception as exc:
            log.debug("[VAPL] Middleware error (non-fatal): %s", exc)
        return response
