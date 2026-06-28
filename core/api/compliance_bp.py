"""
REGULATORY COMPLIANCE SWARM — Flask Blueprint
ScriptMaster Labs / SqueezeOS

Routes (all at /api/compliance/...):
  GET  /status                   Free  — swarm health + agent roster
  GET  /agents                   Free  — all 20 agent specs
  GET  /score/<bank_id>          Free  — 402Proof compliance score
  GET  /leaderboard              Free  — top banks by score
  GET  /anomalies/<bank_id>      Free  — bank anomaly list (auth = bank_id in query)
  POST /anomaly                  x402  — submit a new anomaly detection (5.00 RLUSD)
  POST /self-report              Free  — bank proactively self-reports a violation
  POST /remediate                Free  — mark anomaly remediated
  POST /audit                    x402  — full Leviathan Matrix audit cycle (5.00 RLUSD)
  GET  /regulator/query/<bank_id> x402 — regulator real-time compliance dashboard (2.50 RLUSD)
  GET  /council/log              Free  — last 50 Leviathan Matrix council verdicts
"""

import time
import logging

from flask import Blueprint, request, jsonify
from core.legacy import clean_data
from proof402_integration import require_payment
import compliance_swarm_engine as swarm

logger = logging.getLogger("ComplianceBP")

compliance_bp = Blueprint("compliance", __name__)

_BASE = "https://squeezeos-api.onrender.com"


# ── Free Endpoints ─────────────────────────────────────────────────────────────

@compliance_bp.route("/status", methods=["GET"])
def swarm_status():
    return jsonify(clean_data({
        **swarm.get_swarm_status(),
        "endpoint": f"{_BASE}/api/compliance",
        "docs":     f"{_BASE}/api/compliance/agents",
        "pricing": {
            "anomaly_detection": "5.00 RLUSD per call (x402)",
            "full_audit":        "5.00 RLUSD per call (x402)",
            "regulator_query":   "2.50 RLUSD per call (x402)",
            "self_report":       "Free — earns proactive compliance credits",
        },
    }))


@compliance_bp.route("/agents", methods=["GET"])
def list_agents():
    return jsonify(clean_data({
        "agents":     swarm.AGENTS,
        "count":      len(swarm.AGENTS),
        "council":    "Leviathan Matrix — cross-regulation pattern detection",
        "score_algo": {
            "components": [
                {"name": "Self-Reporting Rate",       "weight": "30%"},
                {"name": "Remediation Speed",         "weight": "25%"},
                {"name": "Anomaly Volume",            "weight": "20%"},
                {"name": "Cross-Reg Consistency",     "weight": "15%"},
                {"name": "Historical Trend",          "weight": "10%"},
            ],
            "scale": "0–1000",
            "bands": [
                {"range": "900–1000", "label": "EXEMPLARY",         "treatment": "Streamlined audits"},
                {"range": "750–899",  "label": "SATISFACTORY",      "treatment": "Standard cycle"},
                {"range": "600–749",  "label": "NEEDS_IMPROVEMENT", "treatment": "Enhanced monitoring"},
                {"range": "400–599",  "label": "DEFICIENT",         "treatment": "Mandatory field exam"},
                {"range": "0–399",    "label": "CRITICAL",          "treatment": "Enforcement action"},
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
    return jsonify(clean_data({
        "leaderboard": board,
        "count":       len(board),
        "ts":          time.time(),
    }))


@compliance_bp.route("/anomalies/<bank_id>", methods=["GET"])
def bank_anomalies(bank_id: str):
    status_filter = request.args.get("status")
    anomalies = swarm.get_bank_anomalies(bank_id, status_filter)
    return jsonify(clean_data({
        "bank_id":   bank_id,
        "anomalies": anomalies,
        "count":     len(anomalies),
        "ts":        time.time(),
    }))


@compliance_bp.route("/council/log", methods=["GET"])
def council_log():
    with swarm._lock:
        entries = list(swarm._council_log)[-50:]
    return jsonify(clean_data({
        "council":    "Leviathan Matrix",
        "entries":    list(reversed(entries)),
        "count":      len(entries),
        "ts":         time.time(),
    }))


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
        status = 404 if result["error"] == "anomaly_not_found" else 400
        return jsonify(result), status

    score_rec = swarm.get_bank_score(bank_id)
    return jsonify(clean_data({
        **result,
        "bank_id":          bank_id,
        "updated_score":    score_rec.get("score"),
        "score_label":      score_rec.get("label"),
        "message": (
            f"Proactive compliance credit issued: +{result['credit_points']} points. "
            f"Your 402Proof score has been updated. Self-reporting before regulators find "
            f"violations reduces future audit fees."
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
    return jsonify(clean_data({
        **result,
        "bank_id":       bank_id,
        "updated_score": score_rec.get("score"),
        "score_label":   score_rec.get("label"),
    }))


# ── x402-Gated: Anomaly Submission ────────────────────────────────────────────

@compliance_bp.route("/anomaly", methods=["POST"])
@require_payment
def submit_anomaly():
    """
    Submit a new compliance anomaly detected by an external agent or data feed.
    5.00 RLUSD per submission. Triggers automatic Leviathan Matrix analysis.
    """
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
        return jsonify({
            "error": "unknown_agent",
            "valid_agents": [a["id"] for a in swarm.AGENTS],
        }), 400

    if severity not in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
        severity = "HIGH"

    try:
        anomaly = swarm.create_anomaly(
            bank_id=bank_id,
            agent_id=agent_id,
            trigger=trigger,
            detail=detail,
            severity=severity,
            evidence=evidence,
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    # Auto-run Leviathan Matrix on new anomaly
    council = swarm.run_leviathan_matrix(bank_id)
    score_rec = swarm.get_bank_score(bank_id)

    return jsonify(clean_data({
        "anomaly":        anomaly,
        "council_verdict": council,
        "bank_score":     score_rec.get("score"),
        "score_label":    score_rec.get("label"),
        "action_required": council["verdict"] in ("MATERIAL_WEAKNESS", "SIGNIFICANT_DEFICIENCY"),
        "self_report_recommended": True,
        "self_report_endpoint": f"{_BASE}/api/compliance/self-report",
    }))


# ── x402-Gated: Full Audit Cycle ──────────────────────────────────────────────

@compliance_bp.route("/audit", methods=["POST"])
@require_payment
def full_audit():
    """
    Full Leviathan Matrix cross-regulation audit for a bank.
    5.00 RLUSD per cycle. Returns comprehensive compliance report with remediation plan.
    """
    body = request.get_json(silent=True) or {}
    bank_id = body.get("bank_id", "").strip()

    if not bank_id:
        return jsonify({"error": "bank_id required"}), 400

    council   = swarm.run_leviathan_matrix(bank_id)
    score_rec = swarm.get_bank_score(bank_id)
    anomalies = swarm.get_bank_anomalies(bank_id)
    open_cts  = {
        a["agent_id"]: a for a in anomalies
        if a["status"] not in ("REMEDIATED",)
    }

    # Build per-agent status table
    agent_status = []
    for agent in swarm.AGENTS:
        open_finding = open_cts.get(agent["id"])
        agent_status.append({
            "agent_id":   agent["id"],
            "regulation": agent["regulation"],
            "domain":     agent["domain"],
            "status":     "FINDING" if open_finding else "CLEAN",
            "severity":   open_finding["severity"] if open_finding else None,
            "trigger":    open_finding["trigger"] if open_finding else None,
            "anomaly_id": open_finding["anomaly_id"] if open_finding else None,
        })

    # Remediation priority order (severity + fine exposure)
    open_findings = [a for a in anomalies if a["status"] not in ("REMEDIATED",)]
    open_findings.sort(
        key=lambda x: (
            {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}.get(x["severity"], 0),
            swarm._AGENT_INDEX.get(x["agent_id"], {}).get("fine_exposure_usd", 0),
        ),
        reverse=True,
    )

    remediation_plan = []
    for i, finding in enumerate(open_findings[:10], 1):
        agent = swarm._AGENT_INDEX.get(finding["agent_id"], {})
        remediation_plan.append({
            "priority":       i,
            "anomaly_id":     finding["anomaly_id"],
            "agent_id":       finding["agent_id"],
            "regulation":     finding["regulation"],
            "trigger":        finding["trigger"],
            "severity":       finding["severity"],
            "fine_exposure":  f"${agent.get('fine_exposure_usd', 0):,.0f}",
            "self_report_eligible": finding["status"] == "OPEN",
            "credit_available": finding["status"] == "OPEN",
        })

    total_fine_exposure = sum(
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
        "total_fine_exposure":  f"${total_fine_exposure:,.0f}",
        "self_report_savings":  f"${total_fine_exposure * 0.8:,.0f} estimated fine reduction via proactive reporting",
        "next_steps": [
            "Self-report all OPEN anomalies immediately via POST /api/compliance/self-report",
            "Execute remediation plan in priority order",
            "Submit remediation evidence via POST /api/compliance/remediate",
            "Re-run audit to confirm score improvement before next regulator query",
        ],
    }))


# ── x402-Gated: Regulator Query ───────────────────────────────────────────────

@compliance_bp.route("/regulator/query/<bank_id>", methods=["GET"])
@require_payment
def regulator_query(bank_id: str):
    """
    Regulator real-time compliance dashboard.
    2.50 RLUSD per query. Any OPEN unreported anomaly is escalated and penalizes the bank's score.
    """
    result    = swarm.regulator_query(bank_id)
    council   = swarm.run_leviathan_matrix(bank_id)
    score_rec = swarm.get_bank_score(bank_id)

    examination_recommendation = "NO_ACTION"
    if score_rec.get("score", 1000) < 400:
        examination_recommendation = "IMMEDIATE_ENFORCEMENT"
    elif score_rec.get("score", 1000) < 600:
        examination_recommendation = "FIELD_EXAMINATION"
    elif score_rec.get("score", 1000) < 750:
        examination_recommendation = "ENHANCED_MONITORING"
    elif result.get("newly_escalated"):
        examination_recommendation = "FOLLOW_UP_REQUIRED"

    return jsonify(clean_data({
        **result,
        "council_verdict":           council,
        "examination_recommendation": examination_recommendation,
        "score_components":          score_rec.get("components", {}),
        "regulator_note": (
            f"402Proof Compliance Score: {score_rec.get('score', '—')}/1000 "
            f"({score_rec.get('label', '—')}). "
            f"Score verified on-chain and portable across regulators."
        ),
    }))
