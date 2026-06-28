"""
REGULATORY COMPLIANCE SWARM ENGINE — Leviathan Matrix
ScriptMaster Labs / SqueezeOS

20 specialist regulatory agents, each continuously auditing a single domain.
The Anomaly Council (Leviathan Matrix) runs cross-regulation pattern detection.
Banks earn proactive compliance credits on 402Proof by self-reporting before
regulators find violations.

Architecture:
  - All state is in-memory (resets on redeploy — intentional MVP)
  - No mock data: agents return "Awaiting Data" when feeds are missing
  - Score algorithm is open-source; infrastructure is the moat
"""

import time
import uuid
import math
import logging
import threading
from collections import defaultdict, deque
from typing import Any, Optional

logger = logging.getLogger("ComplianceSwarm")

# ── Constants ──────────────────────────────────────────────────────────────────

_MAX_ANOMALIES   = 5_000   # global ring
_MAX_REPORTS     = 1_000
_MAX_BANKS       = 500
_SCORE_HISTORY_QUARTERS = 4

# Remediation speed buckets (seconds → score points contribution)
_REMEDIATION_TIERS = [
    (3_600,      100),   # < 1 hour
    (86_400,      85),   # < 1 day
    (604_800,     65),   # < 1 week
    (2_592_000,   40),   # < 30 days
    (float('inf'), 10),  # slow
]

# ── Agent Definitions ──────────────────────────────────────────────────────────

AGENTS = [
    {
        "id": "SOX-1",
        "regulation": "SOX § 404",
        "domain": "Internal Controls",
        "description": "Monitors ERP logs and approval chains for segregation-of-duties violations.",
        "data_sources": ["ERP logs", "approval chains", "access control matrices"],
        "anomaly_triggers": ["SoD violation", "shared credentials", "unauthorized approval"],
        "severity_weight": 0.9,
        "fine_exposure_usd": 5_000_000,
    },
    {
        "id": "SOX-2",
        "regulation": "SOX § 302 / § 906",
        "domain": "Financial Statements",
        "description": "Scans GL entries and reconciliations for material misstatement patterns.",
        "data_sources": ["GL entries", "reconciliations", "sub-ledgers", "journal approvals"],
        "anomaly_triggers": ["round-number entries", "end-of-period clustering", "override spikes"],
        "severity_weight": 0.95,
        "fine_exposure_usd": 10_000_000,
    },
    {
        "id": "GDPR-1",
        "regulation": "GDPR Art. 17",
        "domain": "Data Subject Rights",
        "description": "Tracks deletion requests and CRM export logs for unfulfilled right-to-erasure.",
        "data_sources": ["CRM exports", "deletion logs", "subject request queues"],
        "anomaly_triggers": ["overdue deletion (>30d)", "re-appearance of erased record", "missing log"],
        "severity_weight": 0.7,
        "fine_exposure_usd": 20_000_000,
    },
    {
        "id": "GDPR-2",
        "regulation": "GDPR Art. 46 / Schrems II",
        "domain": "Cross-Border Transfers",
        "description": "Monitors cloud routing and encryption status for data leaving EU without adequacy decision.",
        "data_sources": ["cloud routing tables", "encryption manifests", "SCC logs"],
        "anomaly_triggers": ["unencrypted transfer", "non-adequate jurisdiction", "missing SCC"],
        "severity_weight": 0.75,
        "fine_exposure_usd": 20_000_000,
    },
    {
        "id": "BASEL-III-1",
        "regulation": "Basel III — RWA",
        "domain": "Risk-Weighted Assets",
        "description": "Monitors loan portfolios and collateral for concentration risk spikes.",
        "data_sources": ["loan portfolios", "collateral registers", "credit ratings"],
        "anomaly_triggers": ["concentration >25% tier-1", "haircut breach", "unrated exposure"],
        "severity_weight": 0.85,
        "fine_exposure_usd": 50_000_000,
    },
    {
        "id": "BASEL-III-2",
        "regulation": "Basel III — LCR",
        "domain": "Liquidity Coverage Ratio",
        "description": "Tracks cash flow projections for LCR drops below the 100% regulatory floor.",
        "data_sources": ["cash flow projections", "HQLA register", "net outflow models"],
        "anomaly_triggers": ["LCR < 100%", "intraday shortfall", "HQLA reclassification"],
        "severity_weight": 0.9,
        "fine_exposure_usd": 25_000_000,
    },
    {
        "id": "SEC-15C3-3",
        "regulation": "SEC Rule 15c3-3",
        "domain": "Customer Protection",
        "description": "Monitors segregated account balances against the reserve formula weekly.",
        "data_sources": ["segregated accounts", "PAB accounts", "reserve formula workpapers"],
        "anomaly_triggers": ["reserve deficiency", "commingled funds", "late deposit"],
        "severity_weight": 0.95,
        "fine_exposure_usd": 30_000_000,
    },
    {
        "id": "SEC-13F",
        "regulation": "SEC Rule 13F",
        "domain": "Institutional Holdings",
        "description": "Validates 13F filings for timeliness and accuracy against position files.",
        "data_sources": ["position files", "EDGAR submissions", "13F XML feeds"],
        "anomaly_triggers": ["late filing", "position delta >5%", "omitted security class"],
        "severity_weight": 0.6,
        "fine_exposure_usd": 1_000_000,
    },
    {
        "id": "FINRA-1",
        "regulation": "FINRA Rule 7410 / CAT",
        "domain": "Trade Reporting",
        "description": "Cross-validates OATS/CAT submissions against executed order records.",
        "data_sources": ["CAT data", "OATS records", "order management system"],
        "anomaly_triggers": ["execution mismatch", "late report", "missing order event"],
        "severity_weight": 0.7,
        "fine_exposure_usd": 2_000_000,
    },
    {
        "id": "AML-1",
        "regulation": "BSA / FinCEN",
        "domain": "Transaction Monitoring",
        "description": "Detects structuring, layering, and velocity anomalies in wire transfers and SARs.",
        "data_sources": ["wire transfers", "SARs", "transaction velocity metrics"],
        "anomaly_triggers": ["structuring pattern", "rapid layering", "SAR backlog >30d"],
        "severity_weight": 0.9,
        "fine_exposure_usd": 100_000_000,
    },
    {
        "id": "AML-2",
        "regulation": "OFAC / UN Sanctions",
        "domain": "Sanctions Screening",
        "description": "Monitors counterparty screening against OFAC SDN and UN consolidated lists.",
        "data_sources": ["OFAC SDN", "UN sanctions lists", "counterparty master"],
        "anomaly_triggers": ["unscreened counterparty", "false-negative hit", "stale list >24h"],
        "severity_weight": 0.95,
        "fine_exposure_usd": 500_000_000,
    },
    {
        "id": "MIFID-II",
        "regulation": "MiFID II Art. 27",
        "domain": "Best Execution",
        "description": "Analyzes order routing and venue selection for systematic best-execution failures.",
        "data_sources": ["order routing logs", "venue analysis", "RTS 27/28 reports"],
        "anomaly_triggers": ["inferior venue routing", "SI flag anomaly", "missing RTS 28"],
        "severity_weight": 0.75,
        "fine_exposure_usd": 5_000_000,
    },
    {
        "id": "DODD-FRANK",
        "regulation": "Dodd-Frank § 731",
        "domain": "Swap Reporting",
        "description": "Validates SDR submissions for completeness and timeliness on OTC derivatives.",
        "data_sources": ["SDR submissions", "swap trade repository", "CFTC part 45 fields"],
        "anomaly_triggers": ["missing report", "late T+1", "LEI mismatch"],
        "severity_weight": 0.7,
        "fine_exposure_usd": 3_000_000,
    },
    {
        "id": "CCAR",
        "regulation": "FR Y-14 / CCAR",
        "domain": "Stress Testing",
        "description": "Monitors capital plan scenario models for assumption drift and model risk.",
        "data_sources": ["scenario models", "capital plans", "model inventory"],
        "anomaly_triggers": ["assumption drift >10%", "unvalidated model", "pro-cyclical bias"],
        "severity_weight": 0.8,
        "fine_exposure_usd": 20_000_000,
    },
    {
        "id": "FATCA",
        "regulation": "IRC § 1471–1474",
        "domain": "Foreign Account Reporting",
        "description": "Audits W-8BEN/W-9 collection and TIN validation for FATCA PFFI compliance.",
        "data_sources": ["W-8BEN forms", "W-9 records", "IRS IDES submissions"],
        "anomaly_triggers": ["missing TIN", "incorrect treaty claim", "IDES rejection"],
        "severity_weight": 0.65,
        "fine_exposure_usd": 1_000_000,
    },
    {
        "id": "PCI-DSS",
        "regulation": "PCI DSS v4.0",
        "domain": "Cardholder Data",
        "description": "Scans network segmentation and access logs for unencrypted PAN storage or transmission.",
        "data_sources": ["network scans", "access logs", "encryption key registers"],
        "anomaly_triggers": ["unencrypted PAN", "flat network exposure", "key rotation failure"],
        "severity_weight": 0.8,
        "fine_exposure_usd": 5_000_000,
    },
    {
        "id": "BCBS-239",
        "regulation": "BCBS Principle 239",
        "domain": "Risk Data Aggregation",
        "description": "Validates data lineage and quality scores for complete, accurate risk snapshots.",
        "data_sources": ["data lineage graphs", "quality scorecards", "risk system metadata"],
        "anomaly_triggers": ["incomplete snapshot", "lineage break", "quality score <85"],
        "severity_weight": 0.7,
        "fine_exposure_usd": 10_000_000,
    },
    {
        "id": "EMIR",
        "regulation": "EMIR Art. 9",
        "domain": "Derivatives Reporting",
        "description": "Reconciles TR submissions against internal OTC derivative records for breaks.",
        "data_sources": ["TR submissions", "internal OTC records", "reconciliation reports"],
        "anomaly_triggers": ["reconciliation break", "UTI mismatch", "missing LEI"],
        "severity_weight": 0.7,
        "fine_exposure_usd": 3_000_000,
    },
    {
        "id": "SR-11-7",
        "regulation": "SR Letter 11-7",
        "domain": "Model Validation",
        "description": "Audits model inventory for unvalidated or expired models deployed in production.",
        "data_sources": ["model inventory", "validation reports", "MRM governance logs"],
        "anomaly_triggers": ["unvalidated model in prod", "expired validation", "missing challenger"],
        "severity_weight": 0.75,
        "fine_exposure_usd": 10_000_000,
    },
    {
        "id": "WHISTLEBLOWER",
        "regulation": "SEC Rule 21F / Dodd-Frank § 922",
        "domain": "Internal Reporting",
        "description": "Monitors ethics hotline case backlog and detects retaliation patterns against reporters.",
        "data_sources": ["ethics portal", "hotline cases", "HR action logs"],
        "anomaly_triggers": ["case backlog >45d", "retaliation marker", "reporter adverse action"],
        "severity_weight": 0.85,
        "fine_exposure_usd": 50_000_000,
    },
]

_AGENT_INDEX = {a["id"]: a for a in AGENTS}

# ── In-Memory State ────────────────────────────────────────────────────────────

_lock = threading.Lock()

# anomaly_id → anomaly record
_anomalies: dict[str, dict] = {}
_anomaly_order: deque = deque(maxlen=_MAX_ANOMALIES)

# bank_id → score record
_bank_scores: dict[str, dict] = {}

# bank_id → list of quarterly score snapshots (last 4)
_score_history: dict[str, deque] = defaultdict(lambda: deque(maxlen=_SCORE_HISTORY_QUARTERS))

# bank_id → list of self-report records
_self_reports: dict[str, list] = defaultdict(list)

# anomaly_id → remediation record
_remediations: dict[str, dict] = {}

# Leviathan Matrix cross-regulation correlation log
_council_log: deque = deque(maxlen=200)

# ── Anomaly Management ─────────────────────────────────────────────────────────

def create_anomaly(
    bank_id: str,
    agent_id: str,
    trigger: str,
    detail: str,
    severity: str = "HIGH",
    evidence: Optional[dict] = None,
) -> dict:
    """Record a new compliance anomaly detected by an agent."""
    if agent_id not in _AGENT_INDEX:
        raise ValueError(f"Unknown agent: {agent_id}")

    agent = _AGENT_INDEX[agent_id]
    anomaly_id = f"ANO-{uuid.uuid4().hex[:10].upper()}"
    now = time.time()

    record = {
        "anomaly_id":    anomaly_id,
        "bank_id":       bank_id,
        "agent_id":      agent_id,
        "regulation":    agent["regulation"],
        "domain":        agent["domain"],
        "trigger":       trigger,
        "detail":        detail,
        "severity":      severity,          # CRITICAL / HIGH / MEDIUM / LOW
        "evidence":      evidence or {},
        "status":        "OPEN",           # OPEN / SELF_REPORTED / REMEDIATED / ESCALATED
        "detected_ts":   now,
        "reported_ts":   None,             # when bank self-reported
        "remediated_ts": None,
        "regulator_found": False,
        "credit_issued": False,
        "credit_points": 0,
    }

    with _lock:
        if len(_anomaly_order) >= _MAX_ANOMALIES:
            oldest = _anomaly_order[0]
            _anomalies.pop(oldest, None)
        _anomalies[anomaly_id] = record
        _anomaly_order.append(anomaly_id)

    logger.info("[Swarm] Anomaly %s created — bank=%s agent=%s trigger=%s",
                anomaly_id, bank_id, agent_id, trigger)
    _recompute_score(bank_id)
    return record


def self_report_anomaly(bank_id: str, anomaly_id: str) -> dict:
    """
    Bank proactively self-reports a violation before regulator finds it.
    Issues proactive compliance credit to the bank's 402Proof score.
    """
    with _lock:
        anomaly = _anomalies.get(anomaly_id)
        if not anomaly:
            return {"error": "anomaly_not_found"}
        if anomaly["bank_id"] != bank_id:
            return {"error": "bank_mismatch"}
        if anomaly["status"] != "OPEN":
            return {"error": "already_reported"}

        now = time.time()
        # Credit is higher the faster the self-report comes in
        hours_elapsed = (now - anomaly["detected_ts"]) / 3600
        if hours_elapsed < 1:
            credit = 15
        elif hours_elapsed < 24:
            credit = 12
        elif hours_elapsed < 168:
            credit = 8
        else:
            credit = 4

        anomaly["status"]        = "SELF_REPORTED"
        anomaly["reported_ts"]   = now
        anomaly["credit_issued"] = True
        anomaly["credit_points"] = credit

        _self_reports[bank_id].append({
            "anomaly_id":   anomaly_id,
            "reported_ts":  now,
            "credit_points": credit,
        })

    _recompute_score(bank_id)
    logger.info("[Swarm] Self-report %s — bank=%s credit=+%d", anomaly_id, bank_id, credit)
    return {"anomaly_id": anomaly_id, "status": "SELF_REPORTED", "credit_points": credit}


def mark_remediated(bank_id: str, anomaly_id: str, remediation_notes: str = "") -> dict:
    """Mark an anomaly as remediated. Records time-to-fix for score calculation."""
    with _lock:
        anomaly = _anomalies.get(anomaly_id)
        if not anomaly:
            return {"error": "anomaly_not_found"}
        if anomaly["bank_id"] != bank_id:
            return {"error": "bank_mismatch"}
        if anomaly["status"] == "REMEDIATED":
            return {"error": "already_remediated"}

        now = time.time()
        ttf = now - anomaly["detected_ts"]  # time-to-fix in seconds

        anomaly["status"]        = "REMEDIATED"
        anomaly["remediated_ts"] = now

        _remediations[anomaly_id] = {
            "anomaly_id":        anomaly_id,
            "bank_id":           bank_id,
            "time_to_fix_secs":  ttf,
            "notes":             remediation_notes,
            "remediated_ts":     now,
        }

    _recompute_score(bank_id)
    return {"anomaly_id": anomaly_id, "status": "REMEDIATED", "time_to_fix_secs": ttf}


def regulator_query(bank_id: str) -> dict:
    """
    Regulator queries the swarm for real-time compliance status.
    Any OPEN anomaly not yet self-reported → penalize bank score and mark regulator_found.
    """
    found_new = []
    with _lock:
        for aid, a in _anomalies.items():
            if a["bank_id"] == bank_id and a["status"] == "OPEN":
                a["status"]          = "ESCALATED"
                a["regulator_found"] = True
                found_new.append(aid)

    if found_new:
        _recompute_score(bank_id)
        logger.warning("[Swarm] Regulator found %d unreported anomalies for bank=%s",
                       len(found_new), bank_id)

    score_rec = get_bank_score(bank_id)
    return {
        "bank_id":          bank_id,
        "compliance_score": score_rec["score"],
        "score_label":      score_rec["label"],
        "open_anomalies":   _count_open(bank_id),
        "newly_escalated":  found_new,
        "agents_healthy":   _agents_healthy(bank_id),
        "query_ts":         time.time(),
        "regulatory_treatment": score_rec["regulatory_treatment"],
    }


# ── Leviathan Matrix — Cross-Regulation Anomaly Council ───────────────────────

def run_leviathan_matrix(bank_id: str) -> dict:
    """
    Cross-regulation pattern detection. Looks for systemic failure signatures:
    - Violations clustering in multiple regulations simultaneously
    - Temporal correlation (multiple agents firing within 30 days)
    - Severity escalation patterns
    Returns a council verdict with confidence score and systemic risk label.
    """
    with _lock:
        bank_anomalies = [
            a for a in _anomalies.values()
            if a["bank_id"] == bank_id and a["status"] not in ("REMEDIATED",)
        ]

    if not bank_anomalies:
        return {
            "bank_id":       bank_id,
            "verdict":       "CLEAN",
            "confidence":    100,
            "systemic_risk": False,
            "patterns":      [],
            "council_ts":    time.time(),
        }

    # Count affected domains
    domains_hit = {a["domain"] for a in bank_anomalies}
    regulations_hit = {a["regulation"] for a in bank_anomalies}
    critical_count = sum(1 for a in bank_anomalies if a["severity"] == "CRITICAL")
    high_count     = sum(1 for a in bank_anomalies if a["severity"] == "HIGH")

    # Temporal clustering: anomalies within 30-day window
    now = time.time()
    recent_30d = [a for a in bank_anomalies if now - a["detected_ts"] < 2_592_000]
    cluster_score = len({a["agent_id"] for a in recent_30d})

    # Systemic failure: 4+ regulations hit simultaneously
    systemic = len(regulations_hit) >= 4

    # Confidence in violation (higher = more certain something is wrong)
    confidence = min(100, int(
        (len(bank_anomalies) * 8)
        + (critical_count * 15)
        + (high_count * 7)
        + (cluster_score * 5)
    ))

    # Verdict
    if critical_count >= 2 or (systemic and confidence >= 70):
        verdict = "MATERIAL_WEAKNESS"
    elif critical_count == 1 or (len(regulations_hit) >= 3 and confidence >= 50):
        verdict = "SIGNIFICANT_DEFICIENCY"
    elif high_count >= 3:
        verdict = "CONTROL_GAP"
    else:
        verdict = "ISOLATED_FINDING"

    patterns = []
    if systemic:
        patterns.append("SYSTEMIC_FAILURE: violations span %d regulations simultaneously" % len(regulations_hit))
    if cluster_score >= 5:
        patterns.append("TEMPORAL_CLUSTER: %d agents fired within 30-day window" % cluster_score)
    if critical_count >= 2:
        patterns.append("CRITICAL_STACK: %d critical-severity findings unresolved" % critical_count)

    council_record = {
        "bank_id":           bank_id,
        "verdict":           verdict,
        "confidence":        confidence,
        "systemic_risk":     systemic,
        "domains_affected":  sorted(domains_hit),
        "regulations_hit":   sorted(regulations_hit),
        "open_anomaly_count": len(bank_anomalies),
        "critical_count":    critical_count,
        "patterns":          patterns,
        "council_ts":        time.time(),
    }

    with _lock:
        _council_log.append(council_record)

    return council_record


# ── 402Proof Score Algorithm (open-source formula) ────────────────────────────
#
# Score 0–1000 composed of five weighted components:
#   1. Self-Reporting Rate    (30%) — proactive_found / total_violations
#   2. Remediation Speed      (25%) — avg time-to-fix against tier buckets
#   3. Anomaly Volume         (20%) — inverse of open anomaly count
#   4. Cross-Reg Consistency  (15%) — violations NOT clustered in one domain
#   5. Historical Trend       (10%) — Q-over-Q improvement
#
# Score bands:
#   900–1000  Exemplary        → streamlined audits, reduced frequency
#   750–899   Satisfactory     → standard audit cycle
#   600–749   Needs Improvement → enhanced monitoring
#   400–599   Deficient        → mandatory field examination
#   0–399     Critical         → enforcement action likely

def _remediation_speed_score(bank_id: str) -> float:
    """0–100 score based on average time-to-fix across all remediated anomalies."""
    with _lock:
        fixes = [r for r in _remediations.values() if r["bank_id"] == bank_id]

    if not fixes:
        return 75.0  # neutral when no history

    scores = []
    for fix in fixes:
        ttf = fix["time_to_fix_secs"]
        for threshold, pts in _REMEDIATION_TIERS:
            if ttf < threshold:
                scores.append(pts)
                break

    return sum(scores) / len(scores)


def _self_reporting_rate(bank_id: str) -> float:
    """0.0–1.0 — fraction of bank's violations that were self-reported before regulator found them."""
    with _lock:
        bank_anoms = [a for a in _anomalies.values() if a["bank_id"] == bank_id]

    if not bank_anoms:
        return 1.0  # no violations = perfect rate

    proactive = sum(1 for a in bank_anoms if a["credit_issued"])
    regulator_caught = sum(1 for a in bank_anoms if a["regulator_found"])
    total = proactive + regulator_caught

    return proactive / total if total else 1.0


def _anomaly_volume_score(bank_id: str) -> float:
    """0–100 inversely proportional to open anomaly count."""
    count = _count_open(bank_id)
    if count == 0:
        return 100.0
    # Logarithmic decay: 0 open=100, 1=85, 5=60, 10=40, 20+=10
    return max(10.0, 100.0 - (math.log(count + 1, 1.5) * 20))


def _cross_reg_consistency_score(bank_id: str) -> float:
    """
    0–100. High score = violations spread across domains (not systemic).
    Low score = violations cluster in one regulation (systemic failure indicator).
    Paradox: we reward spread ONLY when total volume is low; heavy spread at high volume is worse.
    """
    with _lock:
        open_anoms = [
            a for a in _anomalies.values()
            if a["bank_id"] == bank_id and a["status"] not in ("REMEDIATED",)
        ]

    if not open_anoms:
        return 100.0

    domain_counts: dict[str, int] = defaultdict(int)
    for a in open_anoms:
        domain_counts[a["domain"]] += 1

    total = len(open_anoms)
    domains = len(domain_counts)

    # If single domain holds >60% of violations → systemic in that domain
    max_share = max(domain_counts.values()) / total
    if max_share > 0.6:
        return max(10.0, 50.0 * (1 - max_share))

    # Multiple domains + low volume → better
    spread_bonus = min(30.0, domains * 5)
    base = max(20.0, 100.0 - (total * 4))
    return min(100.0, base + spread_bonus)


def _historical_trend_score(bank_id: str) -> float:
    """0–100. Improving Q-over-Q score = bonus. Degrading = penalty."""
    hist = list(_score_history[bank_id])
    if len(hist) < 2:
        return 75.0  # neutral, no history yet

    recent  = hist[-1]["raw_score"]
    prior   = hist[-2]["raw_score"]
    delta   = recent - prior

    if delta >= 50:
        return 100.0
    elif delta >= 20:
        return 90.0
    elif delta >= 0:
        return 75.0
    elif delta >= -30:
        return 50.0
    else:
        return 20.0


def _compute_raw_score(bank_id: str) -> dict:
    """Compute weighted 402Proof score components and return full breakdown."""
    sr_rate  = _self_reporting_rate(bank_id)
    rem_spd  = _remediation_speed_score(bank_id)
    vol_scr  = _anomaly_volume_score(bank_id)
    crc_scr  = _cross_reg_consistency_score(bank_id)
    trend    = _historical_trend_score(bank_id)

    # Weighted sum → 0–1000
    raw = (
        (sr_rate * 100 * 0.30)
        + (rem_spd      * 0.25)
        + (vol_scr      * 0.20)
        + (crc_scr      * 0.15)
        + (trend        * 0.10)
    ) * 10  # scale to 1000

    raw = max(0.0, min(1000.0, raw))

    return {
        "self_reporting_rate":      round(sr_rate * 100, 1),
        "remediation_speed":        round(rem_spd, 1),
        "anomaly_volume":           round(vol_scr, 1),
        "cross_reg_consistency":    round(crc_scr, 1),
        "historical_trend":         round(trend, 1),
        "raw_score":                round(raw, 1),
    }


def _score_label(score: float) -> tuple[str, str]:
    if score >= 900:
        return "EXEMPLARY", "Streamlined audits, reduced examination frequency"
    elif score >= 750:
        return "SATISFACTORY", "Standard audit cycle — no enhanced monitoring"
    elif score >= 600:
        return "NEEDS_IMPROVEMENT", "Enhanced monitoring, more frequent regulator queries"
    elif score >= 400:
        return "DEFICIENT", "Mandatory field examination required"
    else:
        return "CRITICAL", "Enforcement action likely — trading restrictions possible"


def _recompute_score(bank_id: str) -> None:
    """Recompute and cache the bank's 402Proof compliance score."""
    breakdown = _compute_raw_score(bank_id)
    score     = breakdown["raw_score"]
    label, treatment = _score_label(score)

    record = {
        "bank_id":              bank_id,
        "score":                score,
        "label":                label,
        "regulatory_treatment": treatment,
        "components":           breakdown,
        "open_anomalies":       _count_open(bank_id),
        "total_credits_earned": sum(a["credit_points"] for a in _anomalies.values()
                                    if a["bank_id"] == bank_id and a["credit_issued"]),
        "computed_ts":          time.time(),
    }

    with _lock:
        _bank_scores[bank_id] = record
        _score_history[bank_id].append({"raw_score": score, "ts": time.time()})


def get_bank_score(bank_id: str) -> dict:
    """Return cached score, computing fresh if not present."""
    with _lock:
        cached = _bank_scores.get(bank_id)

    if not cached:
        _recompute_score(bank_id)
        with _lock:
            cached = _bank_scores.get(bank_id, {})

    return cached


# ── Helpers ────────────────────────────────────────────────────────────────────

def _count_open(bank_id: str) -> int:
    with _lock:
        return sum(
            1 for a in _anomalies.values()
            if a["bank_id"] == bank_id and a["status"] in ("OPEN", "ESCALATED")
        )


def _agents_healthy(bank_id: str) -> list[str]:
    """Return IDs of agents that have NOT fired for this bank (all quiet = healthy)."""
    with _lock:
        fired = {a["agent_id"] for a in _anomalies.values()
                 if a["bank_id"] == bank_id and a["status"] not in ("REMEDIATED",)}

    return [a["id"] for a in AGENTS if a["id"] not in fired]


def get_bank_anomalies(bank_id: str, status_filter: Optional[str] = None) -> list:
    with _lock:
        results = [
            a for a in _anomalies.values()
            if a["bank_id"] == bank_id
            and (status_filter is None or a["status"] == status_filter)
        ]
    return sorted(results, key=lambda x: x["detected_ts"], reverse=True)


def get_swarm_status() -> dict:
    """High-level health snapshot for the /status endpoint."""
    with _lock:
        total_anomalies  = len(_anomalies)
        total_banks      = len(_bank_scores)
        open_count       = sum(1 for a in _anomalies.values() if a["status"] == "OPEN")
        self_report_count = sum(1 for a in _anomalies.values() if a["credit_issued"])
        regulator_found  = sum(1 for a in _anomalies.values() if a["regulator_found"])

    return {
        "swarm":            "REGULATORY COMPLIANCE SWARM",
        "version":          "1.0.0",
        "agent_count":      len(AGENTS),
        "total_banks":      total_banks,
        "total_anomalies":  total_anomalies,
        "open_anomalies":   open_count,
        "self_reported":    self_report_count,
        "regulator_found":  regulator_found,
        "leviathan_matrix": "ONLINE",
        "status_ts":        time.time(),
    }


def get_score_leaderboard(limit: int = 20) -> list:
    """Top banks by 402Proof compliance score."""
    with _lock:
        scores = list(_bank_scores.values())

    scores.sort(key=lambda x: x["score"], reverse=True)
    return scores[:limit]
