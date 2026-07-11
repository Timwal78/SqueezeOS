"""
AWS Marketplace — SaaS Entitlements & Metering Integration
════════════════════════════════════════════════════════════
Backs the "Script Master Labs Federal, Medical & Finance MCP (x402)" AWS
Marketplace listing (contract pricing model).

AWS's automated listing audit requires a contract-pricing SaaS product to
successfully call the Entitlements Service (`GetEntitlements`) at least
once, verified via CloudTrail, before "Update product visibility" can be
approved. Before this blueprint, no code in this repo ever called any AWS
Marketplace API — that's why every visibility request failed with
AUDIT_ERROR.

Routes (all at /api/aws-marketplace/...):
  GET  /status              Free — config state + last entitlement check result
  POST /resolve             AWS redirects subscribing customers here with a
                             x-amzn-marketplace-token (the product's
                             "Fulfillment URL" in AWS Marketplace Management
                             Portal must point here). Resolves the token via
                             ResolveCustomer, then immediately calls
                             GetEntitlements for that customer.
  GET  /entitlements/<customer_identifier>   Free — cached entitlements for a
                             resolved customer (TTL-refreshed via GetEntitlements)

Real AWS calls only happen when AWS_MARKETPLACE_PRODUCT_CODE and IAM
credentials are configured (see .env.example). Until then every route
returns 503 "not_configured" — never fake entitlement data.

Credentials accept either naming convention set on Render:
AWS_MARKETPLACE_ACCESS_KEY_ID / AWS_MARKETPLACE_SECRET_ACCESS_KEY /
AWS_MARKETPLACE_REGION (preferred, dedicated-credential naming), or the
plain AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY / AWS_DEFAULT_REGION (the
names boto3 itself recognizes by default) — whichever is actually set.

AWS Marketplace Metering/Entitlement APIs are us-east-1 only, regardless of
where the SaaS product itself is hosted.
"""

import os
import time
import logging

from flask import Blueprint, request, jsonify
from core.legacy import clean_data

logger = logging.getLogger("AWSMarketplaceBP")

aws_marketplace_bp = Blueprint("aws_marketplace", __name__)

_PRODUCT_CODE = os.environ.get("AWS_MARKETPLACE_PRODUCT_CODE", "").strip()

# In-memory MVP store — resolved customers + their entitlements. Resets on
# restart, consistent with this repo's other MVP stores (_futures,
# _contracts, _listings). Re-resolving via /resolve or the AWS redirect
# repopulates it.
_customers: dict = {}
_ENTITLEMENT_CACHE_TTL = 300  # seconds

_last_self_check: dict = {"ran": False, "ok": None, "ts": None, "error": None}


def _access_key_id() -> str:
    return os.environ.get("AWS_MARKETPLACE_ACCESS_KEY_ID") or os.environ.get("AWS_ACCESS_KEY_ID", "")


def _secret_access_key() -> str:
    return os.environ.get("AWS_MARKETPLACE_SECRET_ACCESS_KEY") or os.environ.get("AWS_SECRET_ACCESS_KEY", "")


def _region() -> str:
    return (
        os.environ.get("AWS_MARKETPLACE_REGION")
        or os.environ.get("AWS_DEFAULT_REGION")
        or "us-east-1"
    )


def _configured() -> bool:
    return bool(_PRODUCT_CODE and _access_key_id() and _secret_access_key())


def _not_configured_response():
    return jsonify({
        "error": "not_configured",
        "message": (
            "AWS Marketplace integration is not configured. Set "
            "AWS_MARKETPLACE_PRODUCT_CODE and either "
            "AWS_MARKETPLACE_ACCESS_KEY_ID/AWS_MARKETPLACE_SECRET_ACCESS_KEY "
            "or AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY (see .env.example) "
            "on the squeezeos-api Render service, then redeploy."
        ),
    }), 503


def _clients():
    """Lazily build boto3 clients scoped to the configured IAM credentials.
    Returns (metering_client, entitlement_client)."""
    import boto3
    session = boto3.session.Session(
        aws_access_key_id=_access_key_id(),
        aws_secret_access_key=_secret_access_key(),
        region_name=_region(),
    )
    return (
        session.client("meteringmarketplace"),
        session.client("marketplace-entitlement"),
    )


def get_entitlements(customer_identifier: str = None) -> dict:
    """Real GetEntitlements call. Raises on boto3/ClientError — callers decide
    how to handle (never fabricate entitlement data on failure)."""
    _, entitlement_client = _clients()
    kwargs = {"ProductCode": _PRODUCT_CODE}
    if customer_identifier:
        kwargs["Filter"] = {"CUSTOMER_IDENTIFIER": [customer_identifier]}
    resp = entitlement_client.get_entitlements(**kwargs)
    return {
        "entitlements": resp.get("Entitlements", []),
        "next_token": resp.get("NextToken"),
        "ts": time.time(),
    }


def run_entitlements_self_check():
    """Called once at app startup (if configured) so the very first deploy
    after credentials are added produces a real, CloudTrail-visible
    GetEntitlements call — satisfying AWS's audit without needing to wait
    for a live customer subscription first."""
    global _last_self_check
    if not _configured():
        _last_self_check = {
            "ran": False, "ok": None, "ts": time.time(),
            "error": "AWS_MARKETPLACE_PRODUCT_CODE / credentials not set",
        }
        logger.warning(
            "[AWS-MARKETPLACE] Skipping GetEntitlements self-check — not configured. "
            "Set AWS_MARKETPLACE_PRODUCT_CODE, AWS_MARKETPLACE_ACCESS_KEY_ID, "
            "AWS_MARKETPLACE_SECRET_ACCESS_KEY on Render to clear the AWS "
            "Marketplace AUDIT_ERROR."
        )
        return
    try:
        result = get_entitlements()
        _last_self_check = {"ran": True, "ok": True, "ts": time.time(), "error": None}
        logger.info(
            "[AWS-MARKETPLACE] GetEntitlements self-check OK — %d entitlement(s) "
            "for product %s. This call is what AWS's audit checks for.",
            len(result["entitlements"]), _PRODUCT_CODE,
        )
    except Exception as e:
        _last_self_check = {"ran": True, "ok": False, "ts": time.time(), "error": str(e)}
        logger.error("[AWS-MARKETPLACE] GetEntitlements self-check FAILED: %s", e)


# ── Free Endpoints ─────────────────────────────────────────────────────────

@aws_marketplace_bp.route("/status", methods=["GET"])
def status():
    return jsonify(clean_data({
        "configured": _configured(),
        "product_code": _PRODUCT_CODE or None,
        "region": _region(),
        "resolved_customers": len(_customers),
        "last_self_check": _last_self_check,
    }))


@aws_marketplace_bp.route("/resolve", methods=["POST"])
def resolve():
    """AWS Marketplace Fulfillment URL target. AWS POSTs
    x-amzn-marketplace-token as a form field after checkout."""
    if not _configured():
        return _not_configured_response()

    token = request.form.get("x-amzn-marketplace-token") or (request.get_json(silent=True) or {}).get("x-amzn-marketplace-token")
    if not token:
        return jsonify({"error": "missing x-amzn-marketplace-token"}), 400

    try:
        metering_client, _ = _clients()
        resolved = metering_client.resolve_customer(RegistrationToken=token)
    except Exception as e:
        logger.error("[AWS-MARKETPLACE] ResolveCustomer failed: %s", e)
        return jsonify({"error": "resolve_customer_failed", "detail": str(e)}), 502

    customer_id = resolved.get("CustomerIdentifier")
    aws_account_id = resolved.get("CustomerAWSAccountId")
    product_code = resolved.get("ProductCode")

    if product_code != _PRODUCT_CODE:
        logger.warning(
            "[AWS-MARKETPLACE] Resolved token for unexpected product_code=%s (expected %s)",
            product_code, _PRODUCT_CODE,
        )
        return jsonify({"error": "product_code_mismatch"}), 400

    try:
        entitlements = get_entitlements(customer_id)
    except Exception as e:
        logger.error("[AWS-MARKETPLACE] GetEntitlements failed for %s: %s", customer_id, e)
        entitlements = {"entitlements": [], "next_token": None, "ts": time.time(), "error": str(e)}

    _customers[customer_id] = {
        "customer_identifier": customer_id,
        "aws_account_id": aws_account_id,
        "product_code": product_code,
        "entitlements": entitlements["entitlements"],
        "resolved_ts": time.time(),
        "entitlements_ts": entitlements["ts"],
    }

    return jsonify(clean_data({
        "customer_identifier": customer_id,
        "aws_account_id": aws_account_id,
        "product_code": product_code,
        "entitlements": entitlements["entitlements"],
    }))


@aws_marketplace_bp.route("/entitlements/<customer_identifier>", methods=["GET"])
def entitlements_for_customer(customer_identifier: str):
    if not _configured():
        return _not_configured_response()

    record = _customers.get(customer_identifier)
    stale = (not record) or (time.time() - record["entitlements_ts"] > _ENTITLEMENT_CACHE_TTL)

    if stale:
        try:
            fresh = get_entitlements(customer_identifier)
        except Exception as e:
            if record:
                logger.warning("[AWS-MARKETPLACE] Refresh failed for %s, serving cached: %s", customer_identifier, e)
            else:
                return jsonify({"error": "get_entitlements_failed", "detail": str(e)}), 502
        else:
            record = _customers.setdefault(customer_identifier, {"customer_identifier": customer_identifier})
            record["entitlements"] = fresh["entitlements"]
            record["entitlements_ts"] = fresh["ts"]

    if not record:
        return jsonify({"error": "customer_not_found", "customer_identifier": customer_identifier}), 404

    return jsonify(clean_data(record))
