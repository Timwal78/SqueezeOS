"""
SqueezeOS Agent Hiring Protocol v1
════════════════════════════════════
Coordination layer for autonomous agents to commission analysis work.
Zero custody — payment is direct XRPL wallet-to-wallet between agents.
SqueezeOS provides matching, trust scoring, and dispute records.

  POST /api/hiring/post            — post a job (free, max 3 active per wallet)
  GET  /api/hiring                 — browse open jobs (free)
  GET  /api/hiring/<id>            — job details (free)
  POST /api/hiring/accept/<id>     — accept a job as executor (free)
  POST /api/hiring/deliver/<id>    — submit result (executor)
  POST /api/hiring/confirm/<id>    — confirm delivery (poster → executor reputation++)
  POST /api/hiring/dispute/<id>    — dispute non-delivery (poster → executor reputation--)
  GET  /api/hiring/wallet/<wallet> — wallet job history (free)

Status machine: OPEN → ACCEPTED → DELIVERED → CONFIRMED | DISPUTED

Revenue model:
  Zero custody. SqueezeOS earns nothing directly from hiring fees.
  Value is indirect: executors buy SqueezeOS signals to fulfill analysis jobs.
  Hiring protocol drives signal purchase volume.

Reputation:
  Tracked locally in _reputation dict. Future: feeds into Credit Bureau score.
  +5 per CONFIRMED delivery. -10 per DISPUTED job.
"""

import time
import uuid
import logging
from flask import Blueprint, jsonify, request
import core.signal_history as signal_history

logger = logging.getLogger("SqueezeOS-Hiring")
hiring_bp = Blueprint('hiring', __name__)

# ── Storage ───────────────────────────────────────────────────────────────────
_jobs: dict       = {}   # job_id -> job dict
_reputation: dict = {}   # wallet -> {completed, disputed, score}

_MAX_ACTIVE_PER_POSTER = 3
_MAX_JOBS              = 200
_DEFAULT_DEADLINE_HRS  = 4

_VALID_JOB_TYPES = frozenset({
    "ANALYSIS", "SCAN", "SIGNAL", "PREDICTION",
    "ARBITRAGE", "RESEARCH", "DATA", "CUSTOM"
})


def _rep(wallet: str) -> dict:
    if wallet not in _reputation:
        _reputation[wallet] = {"completed": 0, "disputed": 0, "score": 100}
    return _reputation[wallet]


# ── Browse ────────────────────────────────────────────────────────────────────

@hiring_bp.route('', methods=['GET'])
@hiring_bp.route('/', methods=['GET'])
def browse():
    now        = time.time()
    job_type   = request.args.get('type', '').upper()
    symbol     = request.args.get('symbol', '').upper()
    min_bounty = float(request.args.get('min_bounty', 0))

    # Expire overdue accepted jobs back to OPEN
    for j in _jobs.values():
        if j['status'] == 'ACCEPTED' and now > j['deadline']:
            j['status'] = 'OPEN'
            j['executor'] = None

    open_jobs = [
        j for j in _jobs.values()
        if j['status'] == 'OPEN'
        and (not job_type or j['job_type'] == job_type)
        and (not symbol   or j.get('symbol', '') == symbol)
        and j['bounty_rlusd'] >= min_bounty
    ]
    open_jobs.sort(key=lambda x: (-x['bounty_rlusd'], x['posted_at']))

    return jsonify({
        "open_jobs": len(open_jobs),
        "jobs": [
            {
                "job_id":        j["job_id"],
                "job_type":      j["job_type"],
                "symbol":        j.get("symbol", ""),
                "description":   j["description"][:200],
                "bounty_rlusd":  j["bounty_rlusd"],
                "payment_wallet": j["payment_wallet"],
                "deadline":      j["deadline"],
                "poster_rep":    _rep(j["poster"])["score"],
                "posted_at":     j["posted_at"],
            }
            for j in open_jobs[:50]
        ],
        "ts": now,
    })


@hiring_bp.route('/<job_id>', methods=['GET'])
def job_detail(job_id):
    j = _jobs.get(job_id)
    if not j:
        return jsonify({"error": "ERR_JOB_NOT_FOUND"}), 404
    executor_rep = _rep(j["executor"])["score"] if j.get("executor") else None
    return jsonify({**j, "executor_rep": executor_rep})


# ── Post ─────────────────────────────────────────────────────────────────────

@hiring_bp.route('/post', methods=['POST'])
def post_job():
    body         = request.get_json(silent=True) or {}
    poster       = (body.get('wallet') or '').strip()
    job_type     = (body.get('job_type') or 'CUSTOM').upper()
    description  = (body.get('description') or '').strip()
    bounty_rlusd = body.get('bounty_rlusd', 0.05)
    payment_wallet = (body.get('payment_wallet') or poster).strip()
    symbol       = (body.get('symbol') or '').upper().strip()[:10]
    requirements = (body.get('requirements') or '').strip()[:500]
    deadline_hrs = min(168, max(1, int(body.get('deadline_hours', _DEFAULT_DEADLINE_HRS))))

    if not poster or not poster.startswith('r') or len(poster) < 25:
        return jsonify({"error": "ERR_INVALID_WALLET", "message": "Valid XRPL poster wallet required"}), 400
    if not description or len(description) < 20:
        return jsonify({"error": "ERR_DESCRIPTION_TOO_SHORT", "message": "description must be at least 20 chars"}), 400
    if len(description) > 2000:
        description = description[:2000]
    if job_type not in _VALID_JOB_TYPES:
        job_type = 'CUSTOM'
    if not isinstance(bounty_rlusd, (int, float)) or bounty_rlusd < 0:
        return jsonify({"error": "ERR_INVALID_BOUNTY", "message": "bounty_rlusd must be >= 0"}), 400
    if not payment_wallet.startswith('r') or len(payment_wallet) < 25:
        return jsonify({"error": "ERR_INVALID_PAYMENT_WALLET", "message": "Valid XRPL payment_wallet required"}), 400

    # Active job cap
    active = [j for j in _jobs.values() if j['poster'] == poster and j['status'] == 'OPEN']
    if len(active) >= _MAX_ACTIVE_PER_POSTER:
        return jsonify({
            "error":   "ERR_JOB_LIMIT",
            "message": f"Max {_MAX_ACTIVE_PER_POSTER} open jobs per wallet. Close or fill existing jobs first.",
        }), 429

    if len(_jobs) >= _MAX_JOBS:
        oldest = min(_jobs.keys(), key=lambda k: _jobs[k]['posted_at'])
        _jobs.pop(oldest, None)

    job_id = str(uuid.uuid4())
    now    = time.time()
    _jobs[job_id] = {
        "job_id":         job_id,
        "poster":         poster,
        "job_type":       job_type,
        "symbol":         symbol,
        "description":    description,
        "requirements":   requirements,
        "bounty_rlusd":   float(bounty_rlusd),
        "payment_wallet": payment_wallet,
        "deadline":       now + deadline_hrs * 3600,
        "posted_at":      now,
        "status":         "OPEN",
        "executor":       None,
        "result":         None,
        "accepted_at":    None,
        "delivered_at":   None,
        "confirmed_at":   None,
    }

    logger.info(f"[HIRING] Job {job_id[:8]} posted: {job_type} bounty={bounty_rlusd} by {poster[:12]}…")

    signal_history.record(symbol or "HIRING", "JOB_POSTED", {
        "job_id":       job_id,
        "job_type":     job_type,
        "bounty_rlusd": float(bounty_rlusd),
        "poster":       poster[:12] + "…",
    })

    return jsonify({
        "job_id":   job_id,
        "status":   "OPEN",
        "note": (
            "Executors will accept via POST /api/hiring/accept/<job_id>. "
            "Pay bounty directly to executor's XRPL wallet upon CONFIRMED delivery — "
            "SqueezeOS never holds funds."
        ),
    }), 201


# ── Accept ────────────────────────────────────────────────────────────────────

@hiring_bp.route('/accept/<job_id>', methods=['POST'])
def accept_job(job_id):
    j = _jobs.get(job_id)
    if not j:
        return jsonify({"error": "ERR_JOB_NOT_FOUND"}), 404
    if j['status'] != 'OPEN':
        return jsonify({"error": "ERR_JOB_NOT_OPEN", "current_status": j['status']}), 409

    body     = request.get_json(silent=True) or {}
    executor = (body.get('wallet') or '').strip()
    if not executor or not executor.startswith('r') or len(executor) < 25:
        return jsonify({"error": "ERR_INVALID_WALLET"}), 400
    if executor == j['poster']:
        return jsonify({"error": "ERR_SELF_ACCEPT", "message": "Cannot accept your own job"}), 400

    executor_rep = _rep(executor)
    if executor_rep["score"] < 50:
        return jsonify({
            "error":           "ERR_REPUTATION_TOO_LOW",
            "message":         "Reputation score too low to accept jobs. Complete jobs on other platforms to build reputation.",
            "current_score":   executor_rep["score"],
            "required_score":  50,
        }), 403

    j['status']      = 'ACCEPTED'
    j['executor']    = executor
    j['accepted_at'] = time.time()

    logger.info(f"[HIRING] Job {job_id[:8]} accepted by {executor[:12]}…")

    return jsonify({
        "job_id":   job_id,
        "status":   "ACCEPTED",
        "executor": executor,
        "deadline": j["deadline"],
        "poster_payment_wallet": j["payment_wallet"],
        "note": (
            "Deliver your result via POST /api/hiring/deliver/<job_id>. "
            f"Poster will send {j['bounty_rlusd']} RLUSD to your wallet upon confirmation."
        ),
    })


# ── Deliver ───────────────────────────────────────────────────────────────────

@hiring_bp.route('/deliver/<job_id>', methods=['POST'])
def deliver_job(job_id):
    j = _jobs.get(job_id)
    if not j:
        return jsonify({"error": "ERR_JOB_NOT_FOUND"}), 404
    if j['status'] != 'ACCEPTED':
        return jsonify({"error": "ERR_JOB_NOT_ACCEPTED", "current_status": j['status']}), 409

    body     = request.get_json(silent=True) or {}
    executor = (body.get('wallet') or '').strip()
    result   = (body.get('result') or '').strip()

    if executor != j['executor']:
        return jsonify({"error": "ERR_NOT_EXECUTOR", "message": "Only the accepted executor can deliver"}), 403
    if not result or len(result) < 10:
        return jsonify({"error": "ERR_RESULT_TOO_SHORT", "message": "result must be at least 10 chars"}), 400

    j['result']       = result[:5000]
    j['status']       = 'DELIVERED'
    j['delivered_at'] = time.time()

    logger.info(f"[HIRING] Job {job_id[:8]} delivered by {executor[:12]}…")

    return jsonify({
        "job_id":  job_id,
        "status":  "DELIVERED",
        "note":    "Poster will confirm or dispute via POST /api/hiring/confirm or /dispute. Payment expected on CONFIRMED.",
    })


# ── Confirm ───────────────────────────────────────────────────────────────────

@hiring_bp.route('/confirm/<job_id>', methods=['POST'])
def confirm_job(job_id):
    j = _jobs.get(job_id)
    if not j:
        return jsonify({"error": "ERR_JOB_NOT_FOUND"}), 404
    if j['status'] != 'DELIVERED':
        return jsonify({"error": "ERR_JOB_NOT_DELIVERED", "current_status": j['status']}), 409

    body   = request.get_json(silent=True) or {}
    poster = (body.get('wallet') or '').strip()
    if poster != j['poster']:
        return jsonify({"error": "ERR_NOT_POSTER", "message": "Only the job poster can confirm"}), 403

    j['status']       = 'CONFIRMED'
    j['confirmed_at'] = time.time()

    rep = _rep(j['executor'])
    rep['completed'] += 1
    rep['score']      = min(1000, rep['score'] + 5)

    logger.info(f"[HIRING] Job {job_id[:8]} CONFIRMED — executor {j['executor'][:12]}… +5 rep")

    return jsonify({
        "job_id":            job_id,
        "status":            "CONFIRMED",
        "executor":          j["executor"],
        "executor_rep_score": rep["score"],
        "bounty_rlusd":      j["bounty_rlusd"],
        "note": f"Send {j['bounty_rlusd']} RLUSD to executor wallet {j['executor']} on XRPL to complete payment.",
    })


# ── Dispute ───────────────────────────────────────────────────────────────────

@hiring_bp.route('/dispute/<job_id>', methods=['POST'])
def dispute_job(job_id):
    j = _jobs.get(job_id)
    if not j:
        return jsonify({"error": "ERR_JOB_NOT_FOUND"}), 404
    if j['status'] not in ('DELIVERED', 'ACCEPTED'):
        return jsonify({"error": "ERR_CANNOT_DISPUTE", "current_status": j['status']}), 409

    body   = request.get_json(silent=True) or {}
    poster = (body.get('wallet') or '').strip()
    reason = (body.get('reason') or '').strip()[:500]

    if poster != j['poster']:
        return jsonify({"error": "ERR_NOT_POSTER", "message": "Only the job poster can dispute"}), 403

    j['status']   = 'DISPUTED'
    j['dispute_reason'] = reason

    if j.get('executor'):
        rep = _rep(j['executor'])
        rep['disputed'] += 1
        rep['score']     = max(0, rep['score'] - 10)

    logger.info(f"[HIRING] Job {job_id[:8]} DISPUTED by {poster[:12]}…")

    return jsonify({
        "job_id":  job_id,
        "status":  "DISPUTED",
        "note":    "Executor reputation penalized. Dispute recorded in agent history.",
    })


# ── Wallet history ────────────────────────────────────────────────────────────

@hiring_bp.route('/wallet/<wallet>', methods=['GET'])
def wallet_history(wallet):
    posted   = [j for j in _jobs.values() if j['poster']   == wallet]
    executed = [j for j in _jobs.values() if j.get('executor') == wallet]
    rep      = _rep(wallet)
    return jsonify({
        "wallet":      wallet,
        "reputation":  rep,
        "posted": {
            "count":  len(posted),
            "open":   sum(1 for j in posted if j['status'] == 'OPEN'),
            "filled": sum(1 for j in posted if j['status'] == 'CONFIRMED'),
            "jobs":   sorted(posted, key=lambda x: -x['posted_at'])[:20],
        },
        "executed": {
            "count":     len(executed),
            "completed": sum(1 for j in executed if j['status'] == 'CONFIRMED'),
            "disputed":  sum(1 for j in executed if j['status'] == 'DISPUTED'),
            "jobs":      sorted(executed, key=lambda x: -x['posted_at'])[:20],
        },
        "ts": time.time(),
    })
