"""
SML AP2 — Agent Payments Protocol mandate verification (Python / Flask)
Port of crawltoll/ap2.js for SqueezeOS + Leviathan Matrix signal APIs.

Verifies Google AP2 Mandates (W3C Verifiable Credentials) before honoring
agent payments. Intent / Cart / Payment mandates, ECDSA P-256 + SHA-256 over
JCS-canonicalized claims (RFC 8785).

Spec: https://ap2-protocol.org/specification/
(c) Script Master Labs LLC — BEAST MODE
"""
import json
import time
import base64
from typing import Optional, Dict, Any

try:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec, utils as asym_utils
    from cryptography.exceptions import InvalidSignature
    _CRYPTO = True
except Exception:
    _CRYPTO = False


# ---------------------------------------------------------------------------
# JSON Canonicalization Scheme (JCS, RFC 8785)
# ---------------------------------------------------------------------------
def jcs_canonicalize(value: Any) -> str:
    if value is None or isinstance(value, (str, int, float, bool)):
        return json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ",".join(jcs_canonicalize(v) for v in value) + "]"
    if isinstance(value, dict):
        keys = sorted(value.keys())
        return "{" + ",".join(json.dumps(k, ensure_ascii=False) + ":" + jcs_canonicalize(value[k]) for k in keys) + "}"
    return json.dumps(str(value))


# ---------------------------------------------------------------------------
# Signature verification (ECDSA P-256 / SHA-256)
# ---------------------------------------------------------------------------
def verify_vc_signature(vc: Dict[str, Any], public_key_pem: str) -> Dict[str, Any]:
    if not _CRYPTO:
        return {"ok": False, "reason": "cryptography_unavailable"}
    try:
        proof = vc.get("proof")
        if not proof or not proof.get("proofValue"):
            return {"ok": False, "reason": "missing_proof"}
        unsigned = {k: v for k, v in vc.items() if k != "proof"}
        canonical = jcs_canonicalize(unsigned).encode("utf-8")
        sig = base64.b64decode(proof["proofValue"])
        pub = serialization.load_pem_public_key(public_key_pem.encode("utf-8") if isinstance(public_key_pem, str) else public_key_pem)
        try:
            # DER-encoded signature path
            pub.verify(sig, canonical, ec.ECDSA(hashes.SHA256()))
            return {"ok": True, "reason": "valid"}
        except InvalidSignature:
            return {"ok": False, "reason": "bad_signature"}
    except Exception as e:
        return {"ok": False, "reason": "verify_error:" + str(e)[:60]}


# ---------------------------------------------------------------------------
# TTL / scope helpers
# ---------------------------------------------------------------------------
def _not_expired(vc: Dict[str, Any]) -> bool:
    exp = vc.get("expirationDate") or (vc.get("credentialSubject", {}) or {}).get("ttl")
    if not exp:
        return True
    try:
        if isinstance(exp, (int, float)):
            return time.time() < float(exp)
        # ISO 8601
        from datetime import datetime
        t = datetime.fromisoformat(str(exp).replace("Z", "+00:00")).timestamp()
        return time.time() < t
    except Exception:
        return True


def _within(amount_atomic_usdc: int, intent_max_usdc) -> bool:
    if intent_max_usdc is None:
        return True
    try:
        return amount_atomic_usdc <= round(float(intent_max_usdc) * 1e6)
    except Exception:
        return True


# ---------------------------------------------------------------------------
# Top-level verifier
# ---------------------------------------------------------------------------
def verify_mandate(mandate: Optional[Dict[str, Any]], ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    ctx = ctx or {}
    result = {"ap2": True, "valid": False, "checks": {}, "reason": None}
    if not mandate or not isinstance(mandate, dict):
        result["reason"] = "no_mandate"
        return result

    intent = mandate.get("intent")
    cart = mandate.get("cart")
    payment = mandate.get("payment")
    trusted = ctx.get("trustedIssuers", {}) or {}
    amount = int(ctx.get("amountAtomicUSDC", 0) or 0)
    checks = result["checks"]

    if intent:
        cs = intent.get("credentialSubject", {}) or {}
        checks["intent_present"] = True
        checks["intent_not_expired"] = _not_expired(intent)
        max_price = cs.get("maxPrice") or (cs.get("constraints", {}) or {}).get("max_price") or (cs.get("hardConstraints", {}) or {}).get("maxPrice")
        checks["within_price_cap"] = _within(amount, max_price)
        allowed = cs.get("allowedMerchants") or cs.get("allowed_merchants") or cs.get("allowedResources")
        if isinstance(allowed, list) and allowed:
            pay_to = str(ctx.get("payTo", "")).lower()
            res = str(ctx.get("resource", ""))
            checks["merchant_allowed"] = any(str(a).lower() == pay_to for a in allowed) or any(str(a) in res for a in allowed)
        else:
            checks["merchant_allowed"] = True
        key_ref = (intent.get("proof", {}) or {}).get("verificationMethod") or intent.get("issuer")
        if key_ref in trusted:
            checks["intent_signature"] = verify_vc_signature(intent, trusted[key_ref])["ok"]

    if cart:
        cs = cart.get("credentialSubject", {}) or {}
        checks["cart_present"] = True
        checks["cart_not_expired"] = _not_expired(cart)
        total = cs.get("total") or cs.get("amount") or cs.get("cartTotal")
        if total is not None:
            checks["cart_amount_matches"] = abs(round(float(total) * 1e6) - amount) <= 1
        key_ref = (cart.get("proof", {}) or {}).get("verificationMethod") or cart.get("issuer")
        if key_ref in trusted:
            checks["cart_signature"] = verify_vc_signature(cart, trusted[key_ref])["ok"]

    if payment:
        checks["payment_present"] = True
        checks["payment_not_expired"] = _not_expired(payment)
        key_ref = (payment.get("proof", {}) or {}).get("verificationMethod") or payment.get("issuer")
        if key_ref in trusted:
            checks["payment_signature"] = verify_vc_signature(payment, trusted[key_ref])["ok"]

    ran = list(checks.values())
    all_pass = len(ran) > 0 and all(ran)
    result["valid"] = bool(intent) and all_pass
    if not result["valid"]:
        failed = [k for k, v in checks.items() if not v]
        result["reason"] = "failed:" + ",".join(failed) if failed else "no_intent_mandate"
    else:
        result["reason"] = "mandate_valid"
    return result


def mandate_from_request(headers) -> Optional[Dict[str, Any]]:
    """headers: dict-like (Flask request.headers). Returns parsed mandate or None."""
    hdr = headers.get("X-AP2-MANDATE") or headers.get("X-AP2-MANDATES")
    if not hdr:
        return None
    try:
        return json.loads(base64.b64decode(hdr).decode("utf-8"))
    except Exception:
        try:
            return json.loads(hdr)
        except Exception:
            return None
