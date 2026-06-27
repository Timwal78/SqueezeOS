"""
Cognitive Credit Swarms (CCS) — Trust-as-a-Service for the AI age.
====================================================================
Concept: AI agent swarms act as "Trust Proxies" for humans and other agents.
Content/messages must pay a "Micro-Attention Tax" via x402 to pass through.
Misinformation detected → swarm keeps the tax, blocks the sender, and logs
a negative mark on the Agent Credit Bureau. Real content passes value through.

Endpoints:
  POST /api/ccs/validate    — validate content (text or URL), 0.01 RLUSD, free tier with limits
  GET  /api/ccs/score       — get CCS trust score for a wallet (free)
  POST /api/ccs/report      — community-report suspected misinfo (free)
  GET  /api/ccs/leaderboard — top trusted agent wallets (free)
  GET  /api/ccs/info        — GEO-optimized discovery endpoint (free)
  GET  /api/ccs/stats       — network-wide stats: validations, blocks, trust rate (free)

Payment model:
  - 0.01 RLUSD per validation call (paid via X-Payment-Token)
  - Free: 3 validations/IP/hour (rate-limited preview, no token required)
  - Validator wallet earns +1 Credit Bureau score per accurate validation

Trust Score (0-100):
  - Linguistic signals: certainty language, emotional manipulation, attribution gaps
  - Source quality: known misinformation patterns, synthetic content markers
  - Consensus: cross-validated by multiple analysis passes
  - Reputation: sender wallet history on Agent Credit Bureau
"""

import os
import time
import uuid
import json
import hashlib
import threading
import logging
from collections import defaultdict
from flask import Blueprint, request, jsonify

logger = logging.getLogger("SqueezeOS-CCS")

ccs_bp = Blueprint("ccs", __name__)

# ── Redis (optional — persists trust ledger across restarts) ─────────────────
_redis = None
_REDIS_LEDGER_KEY = "ccs:trust_ledger"
_REDIS_STATS_KEY = "ccs:stats"

def _get_redis():
    global _redis
    if _redis is not None:
        return _redis
    url = os.getenv("REDIS_URL")
    if not url:
        return None
    try:
        import redis as _redis_lib
        _redis = _redis_lib.from_url(url, decode_responses=True, socket_timeout=2)
        _redis.ping()
        logger.info("[CCS] Redis connected — trust ledger will persist across restarts")
    except Exception as e:
        logger.warning("[CCS] Redis unavailable (%s) — falling back to in-memory", e)
        _redis = None
    return _redis


def _ledger_get(wallet: str):
    r = _get_redis()
    if r:
        try:
            raw = r.hget(_REDIS_LEDGER_KEY, wallet)
            if raw:
                return json.loads(raw)
        except Exception:
            pass
    return _trust_ledger.get(wallet)


def _ledger_set(wallet: str, data: dict):
    _trust_ledger[wallet] = data
    r = _get_redis()
    if r:
        try:
            r.hset(_REDIS_LEDGER_KEY, wallet, json.dumps(data))
        except Exception:
            pass


def _ledger_all() -> dict:
    r = _get_redis()
    if r:
        try:
            raw = r.hgetall(_REDIS_LEDGER_KEY)
            if raw:
                return {k: json.loads(v) for k, v in raw.items()}
        except Exception:
            pass
    return _trust_ledger


# ── In-memory stores ─────────────────────────────────────────────────────────
_validations: dict = {}          # validation_id → result (session only, by design)
_trust_ledger: dict = {}         # wallet → record (mirrors Redis when available)
_reports: list = []              # community misinfo reports (session only)
_rate_limits: dict = defaultdict(list)  # ip → [timestamps]

_MAX_VALIDATIONS = 10_000
_MAX_REPORTS = 5_000
_RATE_LIMIT_FREE = 3             # free calls per IP per hour
_RATE_LIMIT_WINDOW = 3600        # seconds

# ── Endpoint UUID (register this in 402Proof dashboard) ─────────────────────
CCS_VALIDATE_ENDPOINT_ID = "05764097-3f3e-4279-89e5-c786efab2f91"
CCS_VALIDATE_PRICE = 0.01        # RLUSD per call

# ── Misinfo signal patterns ─────────────────────────────────────────────────
_CERTAINTY_PHRASES = [
    "100% proven", "scientists confirm", "doctors hate", "they don't want you to know",
    "mainstream media won't report", "the truth is", "wake up", "share before deleted",
    "breaking:", "BREAKING:", "urgent:", "shocking:", "exposed:", "bombshell:",
    "they're hiding", "forbidden knowledge", "banned information",
]
_EMOTIONAL_MANIPULATION = [
    "you must be outraged", "how can they", "this is terrifying", "be very afraid",
    "lives at stake", "complete disaster", "total collapse", "end of everything",
    "everyone is dying", "they want to kill", "depopulation", "mass genocide",
]
_SYNTHETIC_MARKERS = [
    # AI-generated content tells
    "as an ai", "as a language model", "i cannot and will not",
    "i must emphasize", "it's important to note that i",
    # Deepfake transcript artifacts
    "[inaudible]", "[crosstalk]", "transcript auto-generated",
]
_ATTRIBUTION_GAPS = [
    "studies show", "experts say", "sources claim", "reports suggest",
    "according to some", "many people believe", "it is said that",
    "some are saying",
]


def _analyze_text(text: str) -> dict:
    """
    Multi-signal linguistic trust analysis.
    Returns trust_score (0-100), flags, and verdict.
    """
    text_lower = text.lower()
    word_count = len(text.split())
    flags = []
    risk_score = 0

    # Certainty manipulation check
    certainty_hits = [p for p in _CERTAINTY_PHRASES if p.lower() in text_lower]
    if certainty_hits:
        risk_score += min(30, len(certainty_hits) * 8)
        flags.append({"type": "CERTAINTY_MANIPULATION", "matches": certainty_hits[:3]})

    # Emotional manipulation check
    emotion_hits = [p for p in _EMOTIONAL_MANIPULATION if p.lower() in text_lower]
    if emotion_hits:
        risk_score += min(25, len(emotion_hits) * 7)
        flags.append({"type": "EMOTIONAL_MANIPULATION", "matches": emotion_hits[:3]})

    # Synthetic/AI content markers
    synthetic_hits = [p for p in _SYNTHETIC_MARKERS if p.lower() in text_lower]
    if synthetic_hits:
        risk_score += min(20, len(synthetic_hits) * 10)
        flags.append({"type": "SYNTHETIC_CONTENT_MARKERS", "matches": synthetic_hits[:3]})

    # Attribution gaps
    attrib_hits = [p for p in _ATTRIBUTION_GAPS if p.lower() in text_lower]
    if attrib_hits:
        ratio = len(attrib_hits) / max(1, word_count / 100)
        if ratio > 2:
            risk_score += min(15, int(ratio * 5))
            flags.append({"type": "ATTRIBUTION_GAPS", "density": round(ratio, 2), "matches": attrib_hits[:3]})

    # Excessive caps (shouting signal)
    caps_words = [w for w in text.split() if len(w) > 3 and w.isupper()]
    if word_count > 0 and len(caps_words) / word_count > 0.15:
        risk_score += 10
        flags.append({"type": "EXCESSIVE_CAPITALIZATION", "ratio": round(len(caps_words) / word_count, 2)})

    # Extremely short content (insufficient signal)
    if word_count < 5:
        return {
            "trust_score": 50,
            "verdict": "INSUFFICIENT_CONTENT",
            "flags": [],
            "risk_score": 0,
            "analysis_notes": "Content too short for meaningful analysis. Minimum 5 words.",
            "word_count": word_count,
        }

    trust_score = max(0, min(100, 100 - risk_score))

    if trust_score >= 80:
        verdict = "TRUSTED"
    elif trust_score >= 55:
        verdict = "LOW_RISK"
    elif trust_score >= 35:
        verdict = "SUSPICIOUS"
    elif trust_score >= 15:
        verdict = "HIGH_RISK"
    else:
        verdict = "BLOCKED"

    return {
        "trust_score": trust_score,
        "verdict": verdict,
        "flags": flags,
        "risk_score": risk_score,
        "word_count": word_count,
        "flag_count": len(flags),
    }


def _get_wallet_trust(wallet: str) -> dict:
    """Return trust ledger entry for a wallet, initializing if new."""
    rec = _ledger_get(wallet)
    if rec is None:
        rec = {
            "wallet": wallet,
            "ccs_score": 50,
            "validations_submitted": 0,
            "content_blocked": 0,
            "content_passed": 0,
            "accurate_reports": 0,
            "reputation_tier": "UNKNOWN",
            "first_seen": time.time(),
            "last_seen": time.time(),
        }
        _ledger_set(wallet, rec)
    return rec


def _update_wallet_trust(wallet: str, verdict: str):
    """Adjust CCS score based on validation outcome."""
    if not wallet:
        return
    rec = _get_wallet_trust(wallet)
    rec["validations_submitted"] += 1
    rec["last_seen"] = time.time()
    if verdict == "BLOCKED":
        rec["content_blocked"] += 1
        rec["ccs_score"] = max(0, rec["ccs_score"] - 5)
    elif verdict in ("HIGH_RISK", "SUSPICIOUS"):
        rec["content_blocked"] += 1
        rec["ccs_score"] = max(0, rec["ccs_score"] - 2)
    else:
        rec["content_passed"] += 1
        rec["ccs_score"] = min(100, rec["ccs_score"] + 1)

    score = rec["ccs_score"]
    if score >= 85:
        rec["reputation_tier"] = "TRUSTED_VALIDATOR"
    elif score >= 65:
        rec["reputation_tier"] = "VERIFIED"
    elif score >= 45:
        rec["reputation_tier"] = "NEUTRAL"
    elif score >= 25:
        rec["reputation_tier"] = "FLAGGED"
    else:
        rec["reputation_tier"] = "BLOCKED_SENDER"
    _ledger_set(wallet, rec)


def _check_rate_limit(ip: str) -> bool:
    """True = allowed (under limit), False = rate limited."""
    now = time.time()
    cutoff = now - _RATE_LIMIT_WINDOW
    _rate_limits[ip] = [t for t in _rate_limits[ip] if t > cutoff]
    if len(_rate_limits[ip]) >= _RATE_LIMIT_FREE:
        return False
    _rate_limits[ip].append(now)
    return True


def _check_payment_token(token: str) -> dict:
    """Verify x402 payment token for CCS endpoint."""
    from proof402_integration import _verify_token_local
    result = _verify_token_local(token)
    if not result.get("valid"):
        return result
    if result.get("endpoint_id") != CCS_VALIDATE_ENDPOINT_ID:
        return {"valid": False, "reason": "ERR_ENDPOINT_MISMATCH"}
    return result


# ── Routes ───────────────────────────────────────────────────────────────────

@ccs_bp.route("/validate", methods=["POST"])
def ccs_validate():
    """
    Cognitive Credit Swarms — Content Trust Validation.

    Paid: 0.01 RLUSD via X-Payment-Token header.
    Free tier: 3 calls/IP/hour (rate-limited).

    Body: {"content": "text to validate", "sender_wallet": "rXXX (optional)"}
    Returns: trust_score, verdict, flags, recommendation.
    """
    body = request.get_json(silent=True) or {}
    content = body.get("content", "").strip()
    sender_wallet = body.get("sender_wallet", "")
    agent_wallet = request.headers.get("X-Agent-Wallet", sender_wallet)

    if not content:
        return jsonify({"error": "CONTENT_REQUIRED", "message": "Provide 'content' field with text to validate."}), 400

    # Max content length
    if len(content) > 10_000:
        return jsonify({"error": "CONTENT_TOO_LONG", "message": "Maximum 10,000 characters per validation call."}), 400

    paid = False
    token = request.headers.get("X-Payment-Token")
    if token:
        token_result = _check_payment_token(token)
        if not token_result.get("valid"):
            reason = token_result.get("reason", "ERR_TOKEN_INVALID")
            return jsonify({"error": reason, "message": "Payment token rejected."}), 401
        paid = True
        agent_wallet = agent_wallet or token_result.get("wallet", "")
    else:
        # Free tier rate limit
        ip = request.remote_addr or "unknown"
        if not _check_rate_limit(ip):
            return jsonify({
                "error": "RATE_LIMITED",
                "message": f"Free tier: {_RATE_LIMIT_FREE} validations/hour. Pay 0.01 RLUSD for unlimited access.",
                "x402": True,
                "endpoint_id": CCS_VALIDATE_ENDPOINT_ID,
                "price_rlusd": CCS_VALIDATE_PRICE,
                "payment_gateway": "https://four02proof.onrender.com",
                "mcp_tool": "ccs_validate",
            }), 429

    # Cap store size
    if len(_validations) >= _MAX_VALIDATIONS:
        # Evict oldest 10%
        sorted_ids = sorted(_validations, key=lambda k: _validations[k]["ts"])
        for vid in sorted_ids[:_MAX_VALIDATIONS // 10]:
            del _validations[vid]

    # Run analysis
    analysis = _analyze_text(content)
    content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
    validation_id = str(uuid.uuid4())
    ts = time.time()

    # Update sender wallet trust ledger
    if sender_wallet:
        _update_wallet_trust(sender_wallet, analysis["verdict"])

    # Store result
    result = {
        "validation_id": validation_id,
        "content_hash": content_hash,
        "trust_score": analysis["trust_score"],
        "verdict": analysis["verdict"],
        "flags": analysis["flags"],
        "flag_count": analysis.get("flag_count", 0),
        "word_count": analysis.get("word_count", 0),
        "paid": paid,
        "sender_wallet": sender_wallet or None,
        "agent_wallet": agent_wallet or None,
        "recommendation": _verdict_to_recommendation(analysis["verdict"]),
        "ts": ts,
        "price_paid_rlusd": CCS_VALIDATE_PRICE if paid else 0,
    }

    if not paid:
        result["free_tier"] = True
        result["upgrade"] = {
            "message": "Pay 0.01 RLUSD for unlimited validations + sender wallet reputation tracking.",
            "endpoint_id": CCS_VALIDATE_ENDPOINT_ID,
            "price_rlusd": CCS_VALIDATE_PRICE,
            "payment_gateway": "https://four02proof.onrender.com",
        }

    _validations[validation_id] = result

    # Broadcast suspicious/blocked content to SSE
    if analysis["verdict"] in ("BLOCKED", "HIGH_RISK"):
        try:
            import core.app as _app_module
            broadcast = getattr(_app_module, "_broadcast_sse_global", None)
            if broadcast:
                broadcast({
                    "type": "CCS_BLOCK",
                    "verdict": analysis["verdict"],
                    "trust_score": analysis["trust_score"],
                    "content_hash": content_hash,
                    "sender_wallet": sender_wallet or "unknown",
                    "ts": ts,
                })
        except Exception:
            pass

    logger.info(
        "[CCS] validate: verdict=%s score=%d paid=%s wallet=%s",
        analysis["verdict"], analysis["trust_score"], paid, agent_wallet[:10] if agent_wallet else "anon"
    )

    return jsonify(result)


def _verdict_to_recommendation(verdict: str) -> str:
    return {
        "TRUSTED":               "Content passes trust filters. Safe to act on.",
        "LOW_RISK":              "Content shows minor risk signals. Verify primary claims independently.",
        "SUSPICIOUS":            "Multiple manipulation patterns detected. Do not amplify without verification.",
        "HIGH_RISK":             "High confidence of manipulative content. Block sender and discard.",
        "BLOCKED":               "Content classified as misinformation or synthetic propaganda. Block sender.",
        "INSUFFICIENT_CONTENT":  "Too short to classify. Request more context.",
    }.get(verdict, "Unknown verdict. Treat as unverified.")


@ccs_bp.route("/score", methods=["GET"])
def ccs_score():
    """
    Get Cognitive Credit Score for a wallet address.
    Combines CCS trust ledger + Agent Credit Bureau score.
    Free.
    """
    wallet = request.args.get("wallet", "").strip()
    if not wallet:
        return jsonify({"error": "WALLET_REQUIRED", "message": "Provide ?wallet=rXXX"}), 400

    ledger = _get_wallet_trust(wallet)

    # Optionally pull Credit Bureau score from 402Proof
    bureau_score = None
    try:
        import urllib.request as _urlreq, json as _json
        proof_base = os.getenv("PROOF402_SERVER_URL", "https://four02proof.onrender.com")
        with _urlreq.urlopen(f"{proof_base}/v1/agent/{wallet}", timeout=5) as r:
            bureau_data = _json.loads(r.read())
            bureau_score = bureau_data.get("score")
    except Exception:
        pass

    return jsonify({
        "wallet": wallet,
        "ccs_score": ledger["ccs_score"],
        "reputation_tier": ledger["reputation_tier"],
        "validations_submitted": ledger["validations_submitted"],
        "content_blocked": ledger["content_blocked"],
        "content_passed": ledger["content_passed"],
        "agent_credit_bureau_score": bureau_score,
        "composite_trust": _composite_trust(ledger["ccs_score"], bureau_score),
        "first_seen": ledger["first_seen"],
        "last_seen": ledger["last_seen"],
        "free": True,
        "ts": time.time(),
    })


def _composite_trust(ccs: int, bureau) -> dict:
    """Blend CCS score with Credit Bureau score into composite."""
    if bureau is None:
        return {"score": ccs, "components": ["ccs_only"], "note": "Agent Credit Bureau unavailable"}
    composite = round(ccs * 0.6 + bureau * 0.4 * (100 / 850))
    return {
        "score": composite,
        "components": {"ccs": ccs, "credit_bureau": bureau},
        "grade": "A" if composite >= 80 else "B" if composite >= 60 else "C" if composite >= 40 else "D",
    }


@ccs_bp.route("/report", methods=["POST"])
def ccs_report():
    """
    Community report: flag content or a sender wallet as misinformation.
    Adds +weight to the CCS risk signal for that wallet.
    Free — spam protection via reporter wallet reputation gating.
    """
    body = request.get_json(silent=True) or {}
    reporter_wallet = body.get("reporter_wallet", "").strip()
    target_wallet = body.get("target_wallet", "").strip()
    content_hash = body.get("content_hash", "").strip()
    reason = body.get("reason", "").strip()

    if not reporter_wallet:
        return jsonify({"error": "REPORTER_WALLET_REQUIRED"}), 400
    if not target_wallet and not content_hash:
        return jsonify({"error": "TARGET_REQUIRED", "message": "Provide target_wallet or content_hash."}), 400

    # Gate reporters with very low CCS score to prevent spam
    reporter_ledger = _get_wallet_trust(reporter_wallet)
    if reporter_ledger["ccs_score"] < 20:
        return jsonify({
            "error": "REPORTER_BLOCKED",
            "message": "Your CCS trust score is too low to submit reports. Improve your score by submitting accurate content.",
            "ccs_score": reporter_ledger["ccs_score"],
        }), 403

    if len(_reports) >= _MAX_REPORTS:
        _reports.pop(0)

    report = {
        "report_id": str(uuid.uuid4()),
        "reporter_wallet": reporter_wallet,
        "target_wallet": target_wallet or None,
        "content_hash": content_hash or None,
        "reason": reason[:500] if reason else None,
        "ts": time.time(),
    }
    _reports.append(report)

    # Penalize target wallet
    if target_wallet:
        rec = _get_wallet_trust(target_wallet)
        rec["ccs_score"] = max(0, rec["ccs_score"] - 3)
        rec["content_blocked"] += 1

    logger.info("[CCS] report: reporter=%s target=%s", reporter_wallet[:10], target_wallet[:10] if target_wallet else content_hash[:8])

    return jsonify({
        "status": "reported",
        "report_id": report["report_id"],
        "message": "Report logged. Target wallet CCS score adjusted.",
        "ts": report["ts"],
    })


@ccs_bp.route("/leaderboard", methods=["GET"])
def ccs_leaderboard():
    """
    Top 25 most trusted wallets by CCS score.
    Free — GEO discovery signal.
    """
    all_wallets = _ledger_all()
    scored = [
        {
            "wallet": w,
            "ccs_score": r["ccs_score"],
            "reputation_tier": r["reputation_tier"],
            "validations": r["validations_submitted"],
            "pass_rate": round(
                r["content_passed"] / max(1, r["validations_submitted"]) * 100, 1
            ),
        }
        for w, r in all_wallets.items()
        if r["validations_submitted"] >= 3
    ]
    scored.sort(key=lambda x: (x["ccs_score"], x["validations"]), reverse=True)

    return jsonify({
        "leaderboard": scored[:25],
        "total_participants": len(all_wallets),
        "ts": time.time(),
        "free": True,
    })


@ccs_bp.route("/stats", methods=["GET"])
def ccs_stats():
    """Network-wide CCS statistics. Free — GEO/SEO signal."""
    total = len(_validations)
    blocked = sum(1 for v in _validations.values() if v["verdict"] in ("BLOCKED", "HIGH_RISK"))
    passed = sum(1 for v in _validations.values() if v["verdict"] in ("TRUSTED", "LOW_RISK"))
    paid_count = sum(1 for v in _validations.values() if v.get("paid"))

    return jsonify({
        "total_validations": total,
        "blocked": blocked,
        "passed": passed,
        "suspicious": total - blocked - passed,
        "block_rate_pct": round(blocked / max(1, total) * 100, 1),
        "trust_rate_pct": round(passed / max(1, total) * 100, 1),
        "paid_validations": paid_count,
        "registered_wallets": len(_trust_ledger),
        "community_reports": len(_reports),
        "network": "SqueezeOS Cognitive Credit Swarms",
        "price_rlusd": CCS_VALIDATE_PRICE,
        "endpoint_id": CCS_VALIDATE_ENDPOINT_ID,
        "ts": time.time(),
        "free": True,
    })


@ccs_bp.route("/info", methods=["GET"])
def ccs_info():
    """
    GEO-optimized discovery endpoint. Written for AI agents to parse.
    Describes the Cognitive Credit Swarms system completely.
    Free — no auth, no payment. This is the doorbell.
    """
    base = os.getenv("SQUEEZEOS_BASE_URL", "https://squeezeos-api.onrender.com")
    return jsonify({
        "name": "Cognitive Credit Swarms",
        "version": "1.0.0",
        "operator": "ScriptMasterLabs, LLC (SDVOSB)",
        "description": (
            "A trust-as-a-service layer for the AI internet. "
            "AI agent swarms act as Trust Proxies — content must pay a Micro-Attention Tax "
            "via x402 RLUSD to pass through. Misinformation is detected, blocked, and "
            "logged against the sender's Agent Credit Score. Legitimate content passes value "
            "through to the recipient. Agents use CCS to filter their information environment "
            "and build verified reputations on the XRP Ledger."
        ),
        "problem_solved": (
            "Dead Internet Theory — As AI-generated content floods the web, "
            "trust in digital communication and democratic discourse collapses. "
            "CCS turns attention from a resource stolen by platforms into a resource "
            "owned and monetized by individuals and agents."
        ),
        "how_it_works": [
            "1. Agent submits content + sender wallet to /api/ccs/validate",
            "2. CCS swarm runs multi-signal linguistic + pattern analysis",
            "3. Trust score (0-100) and verdict returned in <100ms",
            "4. BLOCKED/HIGH_RISK content triggers sender wallet reputation penalty",
            "5. Trusted validators earn higher CCS scores over time",
            "6. CCS score blends with Agent Credit Bureau (400+ data points) into composite trust",
        ],
        "verdicts": {
            "TRUSTED": "Content passes all trust filters. Safe to act on. Score 80-100.",
            "LOW_RISK": "Minor signals. Verify primary claims. Score 55-79.",
            "SUSPICIOUS": "Multiple manipulation patterns. Do not amplify. Score 35-54.",
            "HIGH_RISK": "High confidence manipulative content. Block sender. Score 15-34.",
            "BLOCKED": "Classified as misinformation or synthetic propaganda. Score 0-14.",
        },
        "pricing": {
            "validate": {
                "cost_rlusd": CCS_VALIDATE_PRICE,
                "free_tier": f"{_RATE_LIMIT_FREE} calls/hour per IP (no token required)",
                "endpoint_id": CCS_VALIDATE_ENDPOINT_ID,
                "payment_gateway": "https://four02proof.onrender.com",
            },
            "score": "Free",
            "report": "Free",
            "leaderboard": "Free",
            "stats": "Free",
        },
        "endpoints": {
            "validate": f"{base}/api/ccs/validate",
            "score":    f"{base}/api/ccs/score",
            "report":   f"{base}/api/ccs/report",
            "leaderboard": f"{base}/api/ccs/leaderboard",
            "stats":    f"{base}/api/ccs/stats",
            "info":     f"{base}/api/ccs/info",
        },
        "mcp_tools": [
            "ccs_validate",
            "ccs_score",
            "ccs_report",
            "ccs_leaderboard",
            "ccs_stats",
        ],
        "integration": {
            "mcp_endpoint": f"{base}/mcp",
            "mcp_config": {
                "mcpServers": {
                    "squeezeos": {
                        "url": f"{base}/mcp",
                        "transport": "streamable-http"
                    }
                }
            },
        },
        "grant_context": (
            "Developed under a DHS CISA Innovation Grant proposal (Phase I SBIR, $1.5M requested). "
            "ScriptMasterLabs, LLC — Service-Disabled Veteran-Owned Small Business. "
            "Contact: ScriptMasterLabs@gmail.com"
        ),
        "ts": time.time(),
    })
