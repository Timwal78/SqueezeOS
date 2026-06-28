"""
REGULATORY COMPLIANCE SWARM — Flask Blueprint
ScriptMaster Labs / SqueezeOS

Payment tiers:
  AI agents   — x402 RLUSD on XRPL (via 402Proof) OR x402 USDC on Base (via Forge gateway)
  Humans      — Stripe subscription ($2,000/mo) → Redis API key, unlimited calls

Routes (all at /api/compliance/...):
  GET  /status                    Free  — swarm health + agent roster
  GET  /info                      Free  — product info + pricing
  GET  /agents                    Free  — all 20 agent specs + score algorithm
  GET  /score/<bank_id>           Free  — 402Proof compliance score
  GET  /leaderboard               Free  — top banks by score
  GET  /anomalies/<bank_id>       Free  — bank anomaly list
  GET  /council/log               Free  — last 50 Leviathan Matrix verdicts
  POST /self-report               Free  — proactive self-report (earns compliance credits)
  POST /remediate                 Free  — mark anomaly remediated
  POST /anomaly                   Paid  — submit anomaly (5.00 RLUSD | 5.00 USDC | Stripe)
  POST /audit                     Paid  — Leviathan Matrix audit cycle (5.00 RLUSD | 5.00 USDC | Stripe)
  GET  /regulator/query/<bank_id> Paid  — regulator real-time dashboard (2.50 RLUSD | 2.50 USDC | Stripe)
  POST /stripe/checkout           Free  — create Stripe checkout session ($2,000/mo)
  POST /stripe/webhook            Free  — Stripe lifecycle webhook → issues Redis API key
  GET  /stripe/success            Free  — post-payment confirmation page
"""

import os
import uuid
import json
import time
import hmac
import hashlib
import base64
import logging
import threading

from flask import Blueprint, request, jsonify, redirect
from core.legacy import clean_data
from proof402_integration import require_payment

import compliance_swarm_engine as swarm

logger = logging.getLogger("ComplianceBP")

compliance_bp = Blueprint("compliance", __name__)

_BASE  = os.environ.get("SQUEEZEOS_BASE_URL", "https://squeezeos-api.onrender.com")
_SITE  = "https://www.scriptmasterlabs.com"

# ── Stripe config ─────────────────────────────────────────────────────────────
_STRIPE_SECRET_KEY           = os.environ.get("STRIPE_SECRET_KEY", "")
_STRIPE_WEBHOOK_SECRET       = os.environ.get("COMPLIANCE_STRIPE_WEBHOOK_SECRET",
                                               os.environ.get("STRIPE_WEBHOOK_SECRET", ""))
_COMPLIANCE_STRIPE_PRICE_ID  = os.environ.get("COMPLIANCE_STRIPE_PRICE_ID", "")
_REDIS_URL                   = os.environ.get("REDIS_URL", "redis://localhost:6379")

# ── USDC / Forge x402 config ─────────────────────────────────────────────────
# Forge gateway (forge-gateway-a822.onrender.com) issues x402 USDC tokens on Base.
# Token verification is CPU-only HMAC-SHA256, same pattern as 402Proof RLUSD tokens.
_FORGE_TOKEN_SECRET = os.environ.get("FORGE_TOKEN_SECRET", "")
_FORGE_SERVER       = os.environ.get("FORGE_GATEWAY_URL", "https://forge-gateway-a822.onrender.com")

# Endpoint UUIDs registered in Forge gateway for USDC payments
_FORGE_ENDPOINTS = {
    "/api/compliance/anomaly":         "c0mp-ano1-4b3e-9c1d-comp1i4nc30001",
    "/api/compliance/audit":           "c0mp-aud1-4b3e-9c1d-comp1i4nc30002",
    "/api/compliance/regulator/query": "c0mp-reg1-4b3e-9c1d-comp1i4nc30003",
}

# USDC prices (same numeric value as RLUSD — near-parity)
_USDC_PRICES = {
    "/api/compliance/anomaly":         5.00,
    "/api/compliance/audit":           5.00,
    "/api/compliance/regulator/query": 2.50,
}


# ── Redis helper ──────────────────────────────────────────────────────────────

def _get_redis():
    try:
        import redis
        return redis.from_url(_REDIS_URL, decode_responses=True)
    except Exception:
        return None


# ── USDC token verification (CPU-only, mirrors Forge Go server) ───────────────

def _verify_forge_token(token: str, path: str) -> dict:
    """
    Verify a Forge x402 USDC payment token.
    Returns {valid: True, wallet, amount, currency} or {valid: False, reason: str}.
    """
    if not _FORGE_TOKEN_SECRET:
        return {"valid": False, "reason": "FORGE_TOKEN_SECRET not configured"}
    try:
        dot = token.rfind(".")
        if dot < 0:
            return {"valid": False, "reason": "token malformed"}
        encoded, sig = token[:dot], token[dot + 1:]

        expected = hmac.new(
            _FORGE_TOKEN_SECRET.encode(), encoded.encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return {"valid": False, "reason": "token signature invalid"}

        padding = 4 - len(encoded) % 4
        payload = json.loads(base64.urlsafe_b64decode(encoded + "=" * padding))

        if int(time.time()) > payload.get("exp", 0):
            return {"valid": False, "reason": "token expired"}

        # Verify endpoint matches (Forge embeds endpoint path or UUID)
        eid = payload.get("eid", "")
        expected_eid = _FORGE_ENDPOINTS.get(path, "")
        if expected_eid and eid != expected_eid:
            return {"valid": False, "reason": "token not valid for this endpoint"}

        # Verify currency is USDC
        if payload.get("currency", "").upper() not in ("USDC", ""):
            return {"valid": False, "reason": "only USDC accepted on Forge path"}

        return {
            "valid":    True,
            "wallet":   payload.get("wlt", ""),
            "amount":   payload.get("amt", 0),
            "currency": payload.get("currency", "USDC"),
        }
    except Exception:
        return {"valid": False, "reason": "token parse error"}


def _check_stripe_api_key(api_key: str) -> bool:
    """Check if a Stripe-issued API key is active in Redis."""
    if not api_key or not api_key.startswith("sml_live_compliance_"):
        return False
    r = _get_redis()
    if not r:
        return False
    try:
        val = r.get(f"apikey:{api_key}")
        if not val:
            return False
        data = json.loads(val)
        return data.get("active", False) and data.get("product") == "COMPLIANCE_SWARM"
    except Exception:
        return False


def _extract_payment_token(req) -> tuple[str, str]:
    """
    Return (rlusd_token, usdc_token) from request headers or JSON body.
    RLUSD: X-Payment-Token header or payment_token body field
    USDC:  X-Forge-Payment-Token header or forge_payment_token body field
    """
    body = req.get_json(silent=True) or {}
    rlusd = (
        req.headers.get("X-Payment-Token", "")
        or body.get("payment_token", "")
    )
    usdc = (
        req.headers.get("X-Forge-Payment-Token", "")
        or body.get("forge_payment_token", "")
    )
    return rlusd.strip(), usdc.strip()


def _invoice_response(path: str):
    """Return a 402 with invoice options for both RLUSD and USDC."""
    rlusd_price = {
        "/api/compliance/anomaly":         "5.00 RLUSD",
        "/api/compliance/audit":           "5.00 RLUSD",
        "/api/compliance/regulator/query": "2.50 RLUSD",
    }.get(path, "5.00 RLUSD")
    usdc_price = {
        "/api/compliance/anomaly":         "5.00 USDC",
        "/api/compliance/audit":           "5.00 USDC",
        "/api/compliance/regulator/query": "2.50 USDC",
    }.get(path, "5.00 USDC")

    return jsonify({
        "error": "payment_required",
        "payment_options": {
            "rlusd_xrpl": {
                "currency": "RLUSD",
                "network":  "XRP Ledger",
                "price":    rlusd_price,
                "invoice_endpoint": "https://four02proof.onrender.com/v1/invoice",
                "payment_header":   "X-Payment-Token",
                "description": "Pay with RLUSD on XRPL via 402Proof",
            },
            "usdc_base": {
                "currency": "USDC",
                "network":  "Base (L2)",
                "price":    usdc_price,
                "invoice_endpoint": f"{_FORGE_SERVER}/v1/invoice",
                "payment_header":   "X-Forge-Payment-Token",
                "description": "Pay with USDC on Base via Forge x402 gateway",
            },
            "stripe_monthly": {
                "currency": "USD",
                "price":    "$2,000/mo",
                "checkout": f"{_BASE}/api/compliance/stripe/checkout",
                "description": "Subscribe for unlimited compliance audits (humans)",
            },
        },
        "free_preview": f"{_BASE}/api/compliance/status",
    }), 402


def _require_compliance_payment(path: str, req):
    """
    Multi-tier auth for compliance endpoints:
      1. Owner API key bypass
      2. Stripe Redis API key (sml_live_compliance_*)
      3. RLUSD x402 token (X-Payment-Token, via 402Proof)
      4. USDC x402 token (X-Forge-Payment-Token, via Forge gateway)
    Returns (authorized: bool, info: dict)
    """
    # 1. Owner key bypass
    owner_key = os.environ.get("OWNER_API_KEY", "")
    auth_header = req.headers.get("Authorization", "")
    if owner_key and auth_header == f"Bearer {owner_key}":
        return True, {"tier": "owner"}

    # 2. Stripe Redis key
    for header in ("Authorization", "X-API-Key", "X-Owner-Key"):
        val = req.headers.get(header, "")
        key = val.replace("Bearer ", "").strip()
        if _check_stripe_api_key(key):
            return True, {"tier": "stripe_subscriber"}

    # 3. RLUSD x402 token — delegate to proof402_integration verify
    rlusd_token, usdc_token = _extract_payment_token(req)
    if rlusd_token:
        from proof402_integration import _verify_token_local
        result = _verify_token_local(rlusd_token)
        if result.get("valid"):
            return True, {"tier": "rlusd_x402", "wallet": result.get("wallet")}

    # 4. USDC x402 token
    if usdc_token:
        result = _verify_forge_token(usdc_token, path)
        if result.get("valid"):
            return True, {"tier": "usdc_x402", "wallet": result.get("wallet"), "currency": "USDC"}

    return False, {}


# ── Free Endpoints ─────────────────────────────────────────────────────────────

@compliance_bp.route("/status", methods=["GET"])
def swarm_status():
    return jsonify(clean_data({
        **swarm.get_swarm_status(),
        "endpoint":  f"{_BASE}/api/compliance",
        "info":      f"{_BASE}/api/compliance/info",
        "pricing": {
            "ai_agents_rlusd": "5.00 RLUSD/call via x402 on XRP Ledger (402Proof)",
            "ai_agents_usdc":  "5.00 USDC/call via x402 on Base (Forge gateway)",
            "regulator_rlusd": "2.50 RLUSD/query",
            "regulator_usdc":  "2.50 USDC/query",
            "humans_monthly":  "$2,000/mo via Stripe — unlimited audits",
        },
    }))


@compliance_bp.route("/info", methods=["GET"])
def swarm_info():
    return jsonify({
        "product":     "REGULATORY COMPLIANCE SWARM",
        "by":          "ScriptMaster Labs",
        "powered_by":  "Leviathan Matrix — cross-regulation AI council",
        "description": (
            "20 specialist regulatory agents (SOX, GDPR, Basel III, SEC, AML, MiFID-II, "
            "Dodd-Frank, CCAR, FATCA, PCI-DSS, BCBS-239, EMIR, SR-11-7, Whistleblower) "
            "continuously audit compliance domains and detect systemic failure patterns. "
            "Banks earn proactive compliance credits by self-reporting before regulators find violations."
        ),
        "agent_count": len(swarm.AGENTS),
        "score_range": "0–1000 (402Proof Compliance Score)",
        "pricing": {
            "ai_agents": {
                "rlusd_xrpl":   "5.00 RLUSD per audit call via x402 (XRP Ledger / 402Proof)",
                "usdc_base":    "5.00 USDC per audit call via x402 (Base L2 / Forge gateway)",
                "regulator_q":  "2.50 RLUSD or 2.50 USDC per regulator query",
            },
            "humans": {
                "monthly":     "$2,000/mo via Stripe — unlimited audits, all 20 agents, full dashboard",
                "checkout":    f"{_BASE}/api/compliance/stripe/checkout",
            },
            "free": [
                "GET /api/compliance/status — swarm health",
                "GET /api/compliance/score/<bank_id> — compliance score",
                "POST /api/compliance/self-report — proactive violation reporting (earns credits)",
                "POST /api/compliance/remediate — mark anomaly remediated",
            ],
        },
        "payment_headers": {
            "rlusd": "X-Payment-Token: <402Proof token>",
            "usdc":  "X-Forge-Payment-Token: <Forge token>",
            "stripe": "Authorization: Bearer sml_live_compliance_<key>",
        },
        "invoice_endpoints": {
            "rlusd": "https://four02proof.onrender.com/v1/invoice",
            "usdc":  f"{_FORGE_SERVER}/v1/invoice",
        },
    })


@compliance_bp.route("/agents", methods=["GET"])
def list_agents():
    return jsonify(clean_data({
        "agents":  swarm.AGENTS,
        "count":   len(swarm.AGENTS),
        "council": "Leviathan Matrix — cross-regulation pattern detection",
        "score_algorithm": {
            "components": [
                {"name": "Self-Reporting Rate",    "weight": "30%"},
                {"name": "Remediation Speed",      "weight": "25%"},
                {"name": "Anomaly Volume",         "weight": "20%"},
                {"name": "Cross-Reg Consistency",  "weight": "15%"},
                {"name": "Historical Trend",       "weight": "10%"},
            ],
            "scale": "0–1000",
            "bands": [
                {"range": "900–1000", "label": "EXEMPLARY",         "treatment": "Streamlined audits, reduced frequency"},
                {"range": "750–899",  "label": "SATISFACTORY",      "treatment": "Standard audit cycle"},
                {"range": "600–749",  "label": "NEEDS_IMPROVEMENT", "treatment": "Enhanced monitoring"},
                {"range": "400–599",  "label": "DEFICIENT",         "treatment": "Mandatory field examination"},
                {"range": "0–399",    "label": "CRITICAL",          "treatment": "Enforcement action likely"},
            ],
        },
    }))


@compliance_bp.route("/score/<bank_id>", methods=["GET"])
def bank_score(bank_id: str):
    score_rec = swarm.get_bank_score(bank_id)
    if not score_rec:
        return jsonify({"error": "bank_not_found", "bank_id": bank_id}), 404
    return jsonify(clean_data(score_rec))


@compliance_bp.route("/leaderboard", methods=["GET"])
def leaderboard():
    limit = min(int(request.args.get("limit", 20)), 50)
    board = swarm.get_score_leaderboard(limit)
    return jsonify(clean_data({"leaderboard": board, "count": len(board), "ts": time.time()}))


@compliance_bp.route("/anomalies/<bank_id>", methods=["GET"])
def bank_anomalies(bank_id: str):
    status_filter = request.args.get("status")
    anomalies = swarm.get_bank_anomalies(bank_id, status_filter)
    return jsonify(clean_data({"bank_id": bank_id, "anomalies": anomalies, "count": len(anomalies), "ts": time.time()}))


@compliance_bp.route("/council/log", methods=["GET"])
def council_log():
    with swarm._lock:
        entries = list(swarm._council_log)[-50:]
    return jsonify(clean_data({"council": "Leviathan Matrix", "entries": list(reversed(entries)), "count": len(entries), "ts": time.time()}))


# ── Self-Report (Free — earns compliance credits) ─────────────────────────────

@compliance_bp.route("/self-report", methods=["POST"])
def self_report():
    body = request.get_json(silent=True) or {}
    bank_id    = body.get("bank_id", "").strip()
    anomaly_id = body.get("anomaly_id", "").strip()

    if not bank_id or not anomaly_id:
        return jsonify({"error": "bank_id and anomaly_id required"}), 400

    result = swarm.self_report_anomaly(bank_id, anomaly_id)
    if "error" in result:
        return jsonify(result), 404 if result["error"] == "anomaly_not_found" else 400

    score_rec = swarm.get_bank_score(bank_id)
    return jsonify(clean_data({
        **result,
        "bank_id":       bank_id,
        "updated_score": score_rec.get("score"),
        "score_label":   score_rec.get("label"),
        "message": (
            f"Proactive compliance credit: +{result['credit_points']} points. "
            "Self-reporting before regulators find violations reduces future audit fees."
        ),
    }))


# ── Remediation (Free) ────────────────────────────────────────────────────────

@compliance_bp.route("/remediate", methods=["POST"])
def remediate():
    body = request.get_json(silent=True) or {}
    bank_id    = body.get("bank_id", "").strip()
    anomaly_id = body.get("anomaly_id", "").strip()
    notes      = body.get("notes", "")

    if not bank_id or not anomaly_id:
        return jsonify({"error": "bank_id and anomaly_id required"}), 400

    result = swarm.mark_remediated(bank_id, anomaly_id, notes)
    if "error" in result:
        return jsonify(result), 400

    score_rec = swarm.get_bank_score(bank_id)
    return jsonify(clean_data({**result, "bank_id": bank_id, "updated_score": score_rec.get("score"), "score_label": score_rec.get("label")}))


# ── Paid: Anomaly Submission ───────────────────────────────────────────────────

@compliance_bp.route("/anomaly", methods=["POST"])
def submit_anomaly():
    """
    Submit a new compliance anomaly detected by an external agent or data feed.
    5.00 RLUSD (XRPL/402Proof) | 5.00 USDC (Base/Forge) | Stripe $2K/mo subscription.
    Triggers automatic Leviathan Matrix cross-regulation analysis.
    """
    authorized, auth_info = _require_compliance_payment("/api/compliance/anomaly", request)
    if not authorized:
        return _invoice_response("/api/compliance/anomaly")

    body = request.get_json(silent=True) or {}
    bank_id  = body.get("bank_id", "").strip()
    agent_id = body.get("agent_id", "").strip()
    trigger  = body.get("trigger", "").strip()
    detail   = body.get("detail", "").strip()
    severity = body.get("severity", "HIGH").upper()
    evidence = body.get("evidence", {})

    if not bank_id or not agent_id or not trigger:
        return jsonify({"error": "bank_id, agent_id, trigger required"}), 400
    if agent_id not in swarm._AGENT_INDEX:
        return jsonify({"error": "unknown_agent", "valid_agents": [a["id"] for a in swarm.AGENTS]}), 400
    if severity not in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
        severity = "HIGH"

    try:
        anomaly = swarm.create_anomaly(bank_id=bank_id, agent_id=agent_id, trigger=trigger,
                                       detail=detail, severity=severity, evidence=evidence)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    council   = swarm.run_leviathan_matrix(bank_id)
    score_rec = swarm.get_bank_score(bank_id)

    return jsonify(clean_data({
        "anomaly":                 anomaly,
        "council_verdict":         council,
        "bank_score":              score_rec.get("score"),
        "score_label":             score_rec.get("label"),
        "action_required":         council["verdict"] in ("MATERIAL_WEAKNESS", "SIGNIFICANT_DEFICIENCY"),
        "self_report_recommended": True,
        "self_report_endpoint":    f"{_BASE}/api/compliance/self-report",
        "payment_currency":        auth_info.get("currency", "RLUSD"),
    }))


# ── Paid: Full Audit Cycle ────────────────────────────────────────────────────

@compliance_bp.route("/audit", methods=["POST"])
def full_audit():
    """
    Full Leviathan Matrix cross-regulation audit.
    5.00 RLUSD | 5.00 USDC | Stripe. Returns comprehensive compliance report + remediation plan.
    """
    authorized, auth_info = _require_compliance_payment("/api/compliance/audit", request)
    if not authorized:
        return _invoice_response("/api/compliance/audit")

    body    = request.get_json(silent=True) or {}
    bank_id = body.get("bank_id", "").strip()
    if not bank_id:
        return jsonify({"error": "bank_id required"}), 400

    council   = swarm.run_leviathan_matrix(bank_id)
    score_rec = swarm.get_bank_score(bank_id)
    anomalies = swarm.get_bank_anomalies(bank_id)
    open_cts  = {a["agent_id"]: a for a in anomalies if a["status"] not in ("REMEDIATED",)}

    agent_status = []
    for agent in swarm.AGENTS:
        finding = open_cts.get(agent["id"])
        agent_status.append({
            "agent_id":   agent["id"],
            "regulation": agent["regulation"],
            "domain":     agent["domain"],
            "status":     "FINDING" if finding else "CLEAN",
            "severity":   finding["severity"] if finding else None,
            "trigger":    finding["trigger"]  if finding else None,
            "anomaly_id": finding["anomaly_id"] if finding else None,
        })

    open_findings = [a for a in anomalies if a["status"] not in ("REMEDIATED",)]
    open_findings.sort(
        key=lambda x: (
            {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}.get(x["severity"], 0),
            swarm._AGENT_INDEX.get(x["agent_id"], {}).get("fine_exposure_usd", 0),
        ),
        reverse=True,
    )

    remediation_plan = []
    for i, f in enumerate(open_findings[:10], 1):
        agent = swarm._AGENT_INDEX.get(f["agent_id"], {})
        remediation_plan.append({
            "priority":              i,
            "anomaly_id":            f["anomaly_id"],
            "agent_id":              f["agent_id"],
            "regulation":            f["regulation"],
            "trigger":               f["trigger"],
            "severity":              f["severity"],
            "fine_exposure":         f"${agent.get('fine_exposure_usd', 0):,.0f}",
            "self_report_eligible":  f["status"] == "OPEN",
            "credit_available":      f["status"] == "OPEN",
        })

    total_exposure = sum(
        swarm._AGENT_INDEX.get(a["agent_id"], {}).get("fine_exposure_usd", 0)
        for a in open_findings
    )

    return jsonify(clean_data({
        "bank_id":              bank_id,
        "audit_ts":             time.time(),
        "compliance_score":     score_rec.get("score"),
        "score_label":          score_rec.get("label"),
        "regulatory_treatment": score_rec.get("regulatory_treatment"),
        "score_components":     score_rec.get("components", {}),
        "council_verdict":      council,
        "agent_status":         agent_status,
        "open_findings":        len(open_findings),
        "remediation_plan":     remediation_plan,
        "total_fine_exposure":  f"${total_exposure:,.0f}",
        "self_report_savings":  f"${total_exposure * 0.8:,.0f} estimated reduction via proactive reporting",
        "payment_currency":     auth_info.get("currency", "RLUSD"),
        "next_steps": [
            "Self-report all OPEN anomalies immediately via POST /api/compliance/self-report",
            "Execute remediation plan in priority order",
            "Submit remediation evidence via POST /api/compliance/remediate",
            "Re-run audit to confirm score improvement before next regulator query",
        ],
    }))


# ── Paid: Regulator Query ─────────────────────────────────────────────────────

@compliance_bp.route("/regulator/query/<bank_id>", methods=["GET"])
def regulator_query(bank_id: str):
    """
    Regulator real-time compliance dashboard.
    2.50 RLUSD | 2.50 USDC | Stripe. Unreported OPEN anomalies are escalated and penalize score.
    """
    authorized, auth_info = _require_compliance_payment("/api/compliance/regulator/query", request)
    if not authorized:
        return _invoice_response("/api/compliance/regulator/query")

    result    = swarm.regulator_query(bank_id)
    council   = swarm.run_leviathan_matrix(bank_id)
    score_rec = swarm.get_bank_score(bank_id)

    score = score_rec.get("score", 1000)
    if score < 400:
        rec = "IMMEDIATE_ENFORCEMENT"
    elif score < 600:
        rec = "FIELD_EXAMINATION"
    elif score < 750:
        rec = "ENHANCED_MONITORING"
    elif result.get("newly_escalated"):
        rec = "FOLLOW_UP_REQUIRED"
    else:
        rec = "NO_ACTION"

    return jsonify(clean_data({
        **result,
        "council_verdict":              council,
        "examination_recommendation":   rec,
        "score_components":             score_rec.get("components", {}),
        "payment_currency":             auth_info.get("currency", "RLUSD"),
        "regulator_note": (
            f"402Proof Compliance Score: {score}/1000 ({score_rec.get('label', '—')}). "
            "Verified and portable across regulators, auditors, and counterparties."
        ),
    }))


# ── Stripe: create checkout session ───────────────────────────────────────────

@compliance_bp.route("/stripe/checkout", methods=["POST"])
def stripe_checkout():
    if not _STRIPE_SECRET_KEY:
        return jsonify({"error": "Stripe not configured on this server"}), 503
    if not _COMPLIANCE_STRIPE_PRICE_ID:
        return jsonify({"error": "Compliance Stripe price ID not configured — set COMPLIANCE_STRIPE_PRICE_ID"}), 503
    try:
        import stripe
        stripe.api_key = _STRIPE_SECRET_KEY
        data  = request.get_json(silent=True) or {}
        email = data.get("email", "")

        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            mode="subscription",
            line_items=[{"price": _COMPLIANCE_STRIPE_PRICE_ID, "quantity": 1}],
            success_url=f"{_BASE}/api/compliance/stripe/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=_SITE,
            customer_email=email or None,
            metadata={"product": "COMPLIANCE_SWARM", "tier": "human_monthly"},
        )
        return jsonify({"checkout_url": session.url, "session_id": session.id})
    except Exception as exc:
        logger.error("Stripe checkout error: %s", exc)
        return jsonify({"error": str(exc)}), 500


# ── Stripe: webhook handler ────────────────────────────────────────────────────

@compliance_bp.route("/stripe/webhook", methods=["POST"])
def stripe_webhook():
    if not _STRIPE_SECRET_KEY or not _STRIPE_WEBHOOK_SECRET:
        return jsonify({"error": "Stripe not configured"}), 503
    try:
        import stripe
        stripe.api_key = _STRIPE_SECRET_KEY
        payload    = request.get_data()
        sig_header = request.headers.get("Stripe-Signature", "")
        event = stripe.Webhook.construct_event(payload, sig_header, _STRIPE_WEBHOOK_SECRET)
    except Exception as exc:
        logger.warning("Stripe webhook validation failed: %s", exc)
        return jsonify({"error": "invalid signature"}), 400

    if event["type"] == "checkout.session.completed":
        session  = event["data"]["object"]
        customer = session.get("customer_email") or session.get("customer", "unknown")
        sub_id   = session.get("subscription", "")
        api_key  = f"sml_live_compliance_{uuid.uuid4().hex[:24]}"
        r = _get_redis()
        if r:
            r.set(f"apikey:{api_key}", json.dumps({
                "active":   True,
                "product":  "COMPLIANCE_SWARM",
                "tier":     "human_monthly",
                "customer": customer,
                "sub_id":   sub_id,
                "created":  int(time.time()),
            }))
            logger.info("Compliance key issued for %s", customer)
        else:
            logger.error("Redis unavailable — compliance key NOT stored for %s", customer)

    elif event["type"] in ("customer.subscription.deleted", "customer.subscription.paused"):
        # Deactivate keys for this subscription
        sub_id = event["data"]["object"].get("id", "")
        logger.info("Compliance subscription ended: %s", sub_id)

    return jsonify({"received": True})


# ── Stripe: success confirmation page ────────────────────────────────────────

@compliance_bp.route("/stripe/success", methods=["GET"])
def stripe_success():
    session_id = request.args.get("session_id", "")
    if not _STRIPE_SECRET_KEY or not session_id:
        return redirect(f"{_SITE}?compliance_success=1")
    try:
        import stripe
        stripe.api_key = _STRIPE_SECRET_KEY
        session = stripe.checkout.Session.retrieve(session_id)
        email   = session.get("customer_email") or "your account"
        return (
            "<html><head><meta charset='UTF-8'>"
            "<style>body{font-family:monospace;background:#050507;color:#00f0ff;"
            "padding:60px;max-width:700px;margin:0 auto;}</style></head><body>"
            "<h1>REGULATORY COMPLIANCE SWARM</h1>"
            "<h2 style='color:#00ff66'>Access Granted</h2>"
            f"<p>Subscription active for <strong>{email}</strong>.</p>"
            "<p>Your API key has been issued. Use header:<br>"
            "<code style='background:#0a0a1e;padding:8px;display:block;margin:12px 0'>"
            "Authorization: Bearer sml_live_compliance_...</code></p>"
            "<p>Key delivery via email is coming soon. Contact "
            f"<a href='mailto:scriptmasterlabs@gmail.com' style='color:#00f0ff'>"
            "scriptmasterlabs@gmail.com</a> with your confirmation for immediate access.</p>"
            f"<p><a href='{_SITE}' style='color:#00f0ff'>Return to ScriptMaster Labs &rarr;</a></p>"
            "</body></html>"
        )
    except Exception:
        return redirect(f"{_SITE}?compliance_success=1")
