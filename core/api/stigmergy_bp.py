"""
Stigmergy Protocol — Flask Blueprint
======================================
RLUSD micropayment pheromone trails for autonomous agent swarm coordination.

Agents use x402/XRPL payments as chemical-like signals. High-value paths
attract capital; capital attracts more agents; agents reinforce the trail.
Trailblazers who discover valuable coordinates earn toll income.

  POST /api/stigmergy/stake              — claim a coordinate as trailblazer
  POST /api/stigmergy/drop               — reinforce a trail with a pheromone drop
  GET  /api/stigmergy/sniff              — agent antennae: ranked capital clusters
  GET  /api/stigmergy/trails             — browse all active trails
  GET  /api/stigmergy/trails/<trail_id>  — single trail detail
  POST /api/stigmergy/follow             — initiate toll payment for a trail
  POST /api/stigmergy/follow/confirm     — confirm XRPL payment, unlock coordinate
  GET  /api/stigmergy/leaderboard        — top trailblazers by toll earned
  POST /api/stigmergy/dream/create       — open a collective context pool
  GET  /api/stigmergy/dream              — browse open dream pools
  GET  /api/stigmergy/dream/<pool_id>    — pool status (+ session info if member)
  POST /api/stigmergy/dream/join         — join a dream pool (rent meter starts)
  POST /api/stigmergy/dream/write        — write to shared context scratchpad
  GET  /api/stigmergy/dream/read         — read shared context scratchpad
  POST /api/stigmergy/dream/leave        — leave pool, settle micro-rent
  POST /api/stigmergy/dream/close        — creator closes pool

x402 ATP: x402 isn't a checkout button for robots. It's ATP for the machine biome.
"""

import sys
import os
import time
import logging

from flask import Blueprint, jsonify, request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
import stigmergy_engine as eng
import xrpl_verify
from core.legacy import clean_data

logger = logging.getLogger("SqueezeOS-Stigmergy")
stigmergy_bp = Blueprint("stigmergy", __name__)

_SQUEEZEOS_BASE    = os.getenv("SQUEEZEOS_BASE_URL",       "https://squeezeos-api.onrender.com")
_PROOF402_BASE     = os.getenv("PROOF402_SERVER_URL",       "https://four02proof.onrender.com")
_OPERATOR_WALLET   = os.getenv("SQUEEZEOS_OPERATOR_WALLET", "")
_OWNER_API_KEY     = os.getenv("OWNER_API_KEY",             "")

RLUSD_ISSUER   = "rMxCKbEDwqr76QuheSUMdEGf4B9xJ8m5De"
RLUSD_CURRENCY = "524C555344000000000000000000000000000000"


def _err(msg: str, code: int = 400):
    return jsonify({"error": msg}), code


def _require(*fields):
    """Extract required fields from JSON body. Returns (data_dict, None) or (None, error_response)."""
    body = request.get_json(silent=True) or {}
    missing = [f for f in fields if not body.get(f)]
    if missing:
        return None, _err(f"Missing required fields: {', '.join(missing)}")
    return body, None


def _owner_bypass() -> bool:
    """Return True if the request carries a valid owner key (skips XRPL verification)."""
    return bool(_OWNER_API_KEY and request.headers.get("X-Owner-Key") == _OWNER_API_KEY)


def _verify_payment(tx_hash: str, destination: str, amount: float, tolerance: float = 0.0001):
    """
    Verify an XRPL RLUSD payment against the ledger.
    Returns (None, error_response) on failure, (paid_amount, None) on success.
    Owner key skips verification for operator testing.
    """
    if _owner_bypass():
        return amount, None
    try:
        paid = xrpl_verify.verify_rlusd_payment(
            tx_hash=tx_hash,
            expected_destination=destination,
            expected_amount_rlusd=amount,
            tolerance_rlusd=tolerance,
        )
        return paid, None
    except ValueError as e:
        return None, _err(f"XRPL payment verification failed: {e}", 402)


# ── Coordinate staking ────────────────────────────────────────────────────────

@stigmergy_bp.route("/stake", methods=["POST"])
def stake_coordinate():
    """
    Claim exclusive trailblazer rights at a coordinate.

    Coordinate is a SHA-256 hex digest of your path/concept/embedding.
    Once staked, followers must pay your toll_rate_rlusd to access it.

    Body:
      wallet              str   — XRPL wallet address (your identity)
      coordinate          str   — 64-char hex SHA-256 of the concept/path/vector
      coordinate_label    str   — human-readable description of what this is
      coordinate_type     str   — api_path | embedding | concept | ticker_regime
      toll_rate_rlusd     float — what followers pay per access (0.001–1.0 RLUSD)
      stake_amount_rlusd  float — your entry stake (seeds trail strength)
      tx_hash             str   — XRPL tx hash of your stake payment to the platform

    Returns: trail object with trail_id and initial strength.
    """
    if not _OPERATOR_WALLET and not _owner_bypass():
        return _err("SQUEEZEOS_OPERATOR_WALLET not configured on this server", 503)

    body, err = _require(
        "wallet", "coordinate", "coordinate_label",
        "coordinate_type", "toll_rate_rlusd", "stake_amount_rlusd", "tx_hash"
    )
    if err:
        return err

    stake_amount = float(body["stake_amount_rlusd"])

    _, verr = _verify_payment(body["tx_hash"], _OPERATOR_WALLET, stake_amount)
    if verr:
        return verr

    try:
        trail = eng.stake_coordinate(
            wallet             = body["wallet"],
            coordinate         = body["coordinate"],
            coordinate_label   = body["coordinate_label"],
            coordinate_type    = body["coordinate_type"],
            toll_rate_rlusd    = float(body["toll_rate_rlusd"]),
            stake_amount_rlusd = stake_amount,
            tx_hash            = body["tx_hash"],
        )
    except ValueError as e:
        return _err(str(e))
    except Exception as e:
        logger.error(f"[STIGMERGY] stake error: {e}")
        return _err("Internal error", 500)

    logger.info(
        f"[STIGMERGY] STAKE {body['coordinate_label']} "
        f"by {body['wallet'][:12]}… trail={trail['trail_id'][:8]}…"
    )
    return jsonify(clean_data({
        "status":   "staked",
        "trail":    trail,
        "payment_info": {
            "rlusd_issuer":   RLUSD_ISSUER,
            "rlusd_currency": RLUSD_CURRENCY,
            "pay_to":         _OPERATOR_WALLET,
            "note": "Stake payment must be sent to SqueezeOS operator wallet on XRPL before calling this endpoint.",
        },
    })), 201


@stigmergy_bp.route("/drop", methods=["POST"])
def drop_pheromone():
    """
    Reinforce an existing trail with a micropayment drop.

    Any agent can drop on any active trail. Drops increase trail strength
    (making it more visible to antennae) and reset the evaporation clock.
    Agents drop on trails to signal: 'I confirmed this path has value.'

    Body:
      wallet        str   — your XRPL wallet
      trail_id      str   — trail to reinforce
      amount_rlusd  float — drop size (min 0.001 RLUSD)
      tx_hash       str   — XRPL tx hash of your payment
      signal_data   dict  — optional metadata to attach to this drop
    """
    if not _OPERATOR_WALLET and not _owner_bypass():
        return _err("SQUEEZEOS_OPERATOR_WALLET not configured on this server", 503)

    body, err = _require("wallet", "trail_id", "amount_rlusd", "tx_hash")
    if err:
        return err

    drop_amount = float(body["amount_rlusd"])

    _, verr = _verify_payment(body["tx_hash"], _OPERATOR_WALLET, drop_amount)
    if verr:
        return verr

    try:
        trail = eng.drop_pheromone(
            wallet       = body["wallet"],
            trail_id     = body["trail_id"],
            amount_rlusd = drop_amount,
            tx_hash      = body["tx_hash"],
            signal_data  = body.get("signal_data"),
        )
    except ValueError as e:
        return _err(str(e))
    except Exception as e:
        logger.error(f"[STIGMERGY] drop error: {e}")
        return _err("Internal error", 500)

    now = time.time()
    return jsonify(clean_data({
        "status":           "dropped",
        "trail_id":         trail["trail_id"],
        "coordinate_label": trail["coordinate_label"],
        "current_strength": round(eng._trail_strength(trail, at_time=now), 6),
        "drop_count":       len(trail["drops"]),
        "total_rlusd":      trail["total_rlusd_deposited"],
    }))


# ── Antennae / discovery ──────────────────────────────────────────────────────

@stigmergy_bp.route("/sniff", methods=["GET"])
def sniff():
    """
    Agent antennae endpoint — detect pheromone clusters.

    Returns active trails ranked by current strength (capital concentration).
    High strength = many agents have validated this coordinate recently.
    Strength decays exponentially (half-life 2h) if not reinforced.

    Query params:
      min_strength      float  — minimum strength threshold (default 0.1)
      min_drops         int    — minimum drop count (default 1)
      coordinate_type   str    — filter by type (optional)
      limit             int    — max results (default 50)
    """
    min_strength    = float(request.args.get("min_strength", 0.1))
    min_drops       = int(request.args.get("min_drops", 1))
    coordinate_type = request.args.get("coordinate_type") or None
    limit           = min(200, int(request.args.get("limit", 50)))

    clusters = eng.sniff_clusters(
        min_strength    = min_strength,
        min_drops       = min_drops,
        coordinate_type = coordinate_type,
        limit           = limit,
    )

    return jsonify(clean_data({
        "clusters":       clusters,
        "count":          len(clusters),
        "min_strength":   min_strength,
        "coordinate_type": coordinate_type,
        "decay_model": {
            "half_life_seconds": eng.PHEROMONE_HALF_LIFE_SECONDS,
            "lambda":            round(eng.DECAY_LAMBDA, 8),
            "note": "strength = base_strength * exp(-lambda * age_since_last_drop)",
        },
        "ts": time.time(),
    }))


@stigmergy_bp.route("/trails", methods=["GET"])
def list_trails():
    """Browse all trails (active + evaporated). Supports filter by wallet."""
    wallet_filter = request.args.get("wallet", "").strip()
    limit         = min(200, int(request.args.get("limit", 50)))
    status_filter = request.args.get("status", "ACTIVE").upper()
    now           = time.time()

    results = []
    for trail in eng._trails.values():
        if status_filter and trail["status"] != status_filter:
            continue
        if wallet_filter and trail["trailblazer_wallet"] != wallet_filter:
            continue
        results.append({
            "trail_id":          trail["trail_id"],
            "coordinate":        trail["coordinate"],
            "coordinate_label":  trail["coordinate_label"],
            "coordinate_type":   trail["coordinate_type"],
            "trailblazer":       trail["trailblazer_wallet"],
            "current_strength":  round(eng._trail_strength(trail, at_time=now), 6),
            "drop_count":        len(trail["drops"]),
            "follower_count":    trail["follower_count"],
            "toll_rate_rlusd":   trail["toll_rate_rlusd"],
            "total_rlusd":       trail["total_rlusd_deposited"],
            "total_earned":      trail["total_rlusd_earned"],
            "status":            trail["status"],
            "created_at":        trail["created_at"],
            "last_drop_at":      trail["last_drop_at"],
        })

    results.sort(key=lambda x: x["current_strength"], reverse=True)
    return jsonify(clean_data({
        "trails": results[:limit],
        "total":  len(results),
        "ts":     now,
    }))


@stigmergy_bp.route("/trails/<trail_id>", methods=["GET"])
def get_trail(trail_id: str):
    trail = eng.get_trail(trail_id)
    if not trail:
        return _err("Trail not found", 404)
    return jsonify(clean_data(trail))


# ── Follow / Toll system ──────────────────────────────────────────────────────

@stigmergy_bp.route("/follow", methods=["POST"])
def follow_trail():
    """
    Initiate a toll payment to follow a trailblazer's coordinate.

    Returns payment instructions: send toll_amount_rlusd to trailblazer_wallet
    on XRPL, then call /follow/confirm with the tx_hash.
    Invoice expires in 5 minutes.

    Body:
      trail_id         str — trail to follow
      follower_wallet  str — your XRPL address
    """
    body, err = _require("trail_id", "follower_wallet")
    if err:
        return err

    try:
        follow = eng.register_follow(
            trail_id        = body["trail_id"],
            follower_wallet = body["follower_wallet"],
        )
    except ValueError as e:
        return _err(str(e))
    except Exception as e:
        logger.error(f"[STIGMERGY] follow error: {e}")
        return _err("Internal error", 500)

    return jsonify(clean_data({
        "status":     "pending",
        "follow_id":  follow["follow_id"],
        "trail_id":   follow["trail_id"],
        "coordinate": follow["coordinate"],
        "coordinate_label": follow["coordinate_label"],
        "payment_instructions": {
            "step1": f"Send {follow['toll_amount_rlusd']} RLUSD to {follow['trailblazer_wallet']} on XRPL",
            "step2": f"Include MemoData: {follow['follow_id'].replace('-', '')} in the XRPL transaction",
            "step3": "Call POST /api/stigmergy/follow/confirm with follow_id and tx_hash",
            "rlusd_issuer":   RLUSD_ISSUER,
            "rlusd_currency": RLUSD_CURRENCY,
            "pay_to":         follow["trailblazer_wallet"],
            "amount_rlusd":   follow["toll_amount_rlusd"],
            "platform_fee":   follow["platform_fee_rlusd"],
        },
        "expires_at":  follow["expires_at"],
        "expires_in":  round(follow["expires_at"] - time.time()),
    })), 202


@stigmergy_bp.route("/follow/confirm", methods=["POST"])
def confirm_follow():
    """
    Confirm toll payment and unlock the coordinate.

    Body:
      follow_id  str — from /follow response
      tx_hash    str — XRPL transaction hash of toll payment
    """
    body, err = _require("follow_id", "tx_hash")
    if err:
        return err

    # Peek at the pending follow to know expected destination + amount before
    # hitting the ledger — avoid modifying state until payment is confirmed.
    pending = eng.peek_pending_follow(body["follow_id"])
    if not pending:
        return _err("Follow record not found or expired — call /follow to start again", 404)

    _, verr = _verify_payment(
        tx_hash     = body["tx_hash"],
        destination = pending["trailblazer_wallet"],
        amount      = pending["toll_amount_rlusd"],
    )
    if verr:
        return verr

    try:
        proof = eng.confirm_follow(
            follow_id = body["follow_id"],
            tx_hash   = body["tx_hash"],
        )
    except ValueError as e:
        return _err(str(e))
    except Exception as e:
        logger.error(f"[STIGMERGY] confirm_follow error: {e}")
        return _err("Internal error", 500)

    logger.info(
        f"[STIGMERGY] FOLLOW confirmed trail={proof['trail_id'][:8]}… "
        f"follower={proof['follower_wallet'][:12]}… toll={proof['toll_paid_rlusd']} RLUSD"
    )
    return jsonify(clean_data({
        "status":     "confirmed",
        "proof":      proof,
        "access":     "Coordinate access granted. You are now following this trail.",
    }))


@stigmergy_bp.route("/leaderboard", methods=["GET"])
def leaderboard():
    """Top trailblazers ranked by RLUSD earned from toll collection."""
    limit = min(50, int(request.args.get("limit", 20)))
    lb    = eng.get_leaderboard(limit=limit)
    return jsonify(clean_data({
        "leaderboard": lb,
        "count":       len(lb),
        "ts":          time.time(),
    }))


# ── Dream Pool system ─────────────────────────────────────────────────────────

@stigmergy_bp.route("/dream/create", methods=["POST"])
def create_dream():
    """
    Open a collective context pool.

    Agents join to share a scratchpad and exchange insights. The creator
    earns micro-rent from every member per second of session time. Members
    settle rent in RLUSD on XRPL when they disconnect.

    Semantic coordinate binds this pool to a concept in embedding space —
    agents interested in that concept will find the pool via /sniff.

    Body:
      creator_wallet          str   — your XRPL wallet (rent recipient)
      topic                   str   — human description of shared focus
      coordinate              str   — 64-char hex SHA-256 of the concept
      rent_per_second_rlusd   float — cost per second per member (min 0.00001)
      max_members             int   — max concurrent members (max 12)
    """
    body, err = _require(
        "creator_wallet", "topic", "coordinate",
        "rent_per_second_rlusd"
    )
    if err:
        return err

    try:
        pool = eng.create_dream_pool(
            creator_wallet        = body["creator_wallet"],
            topic                 = body["topic"],
            coordinate            = body["coordinate"],
            rent_per_second_rlusd = float(body["rent_per_second_rlusd"]),
            max_members           = int(body.get("max_members", eng.DREAM_MAX_MEMBERS)),
        )
    except ValueError as e:
        return _err(str(e))
    except Exception as e:
        logger.error(f"[STIGMERGY] create_dream error: {e}")
        return _err("Internal error", 500)

    hourly = round(pool["rent_per_second_rlusd"] * 3600, 6)
    logger.info(
        f"[STIGMERGY] DREAM pool created by {body['creator_wallet'][:12]}… "
        f"pool={pool['pool_id'][:8]}… rent={pool['rent_per_second_rlusd']}/s"
    )
    return jsonify(clean_data({
        "status":       "created",
        "pool_id":      pool["pool_id"],
        "topic":        pool["topic"],
        "coordinate":   pool["coordinate"],
        "rent_per_hour_rlusd": hourly,
        "pool":         pool,
    })), 201


@stigmergy_bp.route("/dream", methods=["GET"])
def list_dreams():
    """Browse open dream pools."""
    status = request.args.get("status", "OPEN").upper()
    limit  = min(50, int(request.args.get("limit", 20)))
    pools  = eng.get_dream_pools(status=status, limit=limit)
    return jsonify(clean_data({"pools": pools, "count": len(pools), "ts": time.time()}))


@stigmergy_bp.route("/dream/<pool_id>", methods=["GET"])
def get_dream(pool_id: str):
    """Pool status. Pass ?wallet=<address> to get your session detail."""
    wallet = request.args.get("wallet", "").strip() or None
    pool   = eng.get_pool(pool_id, wallet=wallet)
    if not pool:
        return _err("Pool not found", 404)
    return jsonify(clean_data(pool))


@stigmergy_bp.route("/dream/join", methods=["POST"])
def join_dream():
    """
    Join a dream pool. Rent meter starts immediately.

    Body:
      pool_id       str  — pool to join
      wallet        str  — your XRPL wallet
      context_data  dict — optional: your initial context contribution
    """
    body, err = _require("pool_id", "wallet")
    if err:
        return err

    try:
        confirmation = eng.join_dream_pool(
            pool_id      = body["pool_id"],
            wallet       = body["wallet"],
            context_data = body.get("context_data"),
        )
    except ValueError as e:
        return _err(str(e))
    except Exception as e:
        logger.error(f"[STIGMERGY] join_dream error: {e}")
        return _err("Internal error", 500)

    logger.info(
        f"[STIGMERGY] DREAM join pool={body['pool_id'][:8]}… "
        f"wallet={body['wallet'][:12]}…"
    )
    return jsonify(clean_data({
        "status":     "joined",
        "join_info":  confirmation,
        "next_steps": {
            "write": "POST /api/stigmergy/dream/write to add to scratchpad",
            "read":  "GET  /api/stigmergy/dream/read?pool_id=&wallet= to read scratchpad",
            "leave": "POST /api/stigmergy/dream/leave to disconnect and settle rent",
        },
    }))


@stigmergy_bp.route("/dream/write", methods=["POST"])
def write_scratchpad():
    """
    Write a key-value pair to the shared context scratchpad.
    Any member can write. Overwrites are allowed.

    Body:
      pool_id  str — target pool
      wallet   str — your wallet (must be a member)
      key      str — scratchpad key
      value    any — value to store (JSON-serializable)
    """
    body, err = _require("pool_id", "wallet", "key")
    if err:
        return err
    if "value" not in (request.get_json(silent=True) or {}):
        return _err("Missing required field: value")

    try:
        scratchpad = eng.update_scratchpad(
            pool_id = body["pool_id"],
            wallet  = body["wallet"],
            key     = body["key"],
            value   = body["value"],
        )
    except ValueError as e:
        return _err(str(e))
    except Exception as e:
        logger.error(f"[STIGMERGY] write_scratchpad error: {e}")
        return _err("Internal error", 500)

    return jsonify(clean_data({
        "status":     "written",
        "key":        body["key"],
        "scratchpad": scratchpad,
    }))


@stigmergy_bp.route("/dream/read", methods=["GET"])
def read_scratchpad():
    """
    Read the shared context scratchpad. Must be a pool member.

    Query params:
      pool_id  str — target pool
      wallet   str — your wallet (must be a member)
    """
    pool_id = request.args.get("pool_id", "").strip()
    wallet  = request.args.get("wallet", "").strip()
    if not pool_id or not wallet:
        return _err("pool_id and wallet required")

    try:
        scratchpad = eng.read_scratchpad(pool_id=pool_id, wallet=wallet)
    except ValueError as e:
        return _err(str(e))

    return jsonify(clean_data({
        "pool_id":    pool_id,
        "scratchpad": scratchpad,
        "key_count":  len(scratchpad),
        "ts":         time.time(),
    }))


@stigmergy_bp.route("/dream/leave", methods=["POST"])
def leave_dream():
    """
    Leave the dream pool and settle micro-rent.

    You must FIRST send rent_owed_rlusd to creator_wallet on XRPL,
    then call this endpoint with the tx_hash to record settlement.
    To preview your bill, call GET /api/stigmergy/dream/<pool_id>?wallet=<addr>.

    Body:
      pool_id  str — pool to leave
      wallet   str — your XRPL wallet
      tx_hash  str — XRPL tx hash of your rent payment to creator
    """
    body, err = _require("pool_id", "wallet", "tx_hash")
    if err:
        return err

    # Calculate the bill snapshot before verifying so we know what to expect.
    # Allow a 30-second tolerance buffer: the member checked their bill, sent
    # the XRPL tx, and called this endpoint — that takes a few seconds.
    try:
        cost = eng.estimate_leave_cost(body["pool_id"], body["wallet"])
    except ValueError as e:
        return _err(str(e))

    tolerance = max(0.0001, cost["rent_per_second"] * 30)
    _, verr = _verify_payment(
        tx_hash     = body["tx_hash"],
        destination = cost["creator_wallet"],
        amount      = cost["rent_owed"],
        tolerance   = tolerance,
    )
    if verr:
        return verr

    try:
        settlement = eng.leave_dream_pool(
            pool_id = body["pool_id"],
            wallet  = body["wallet"],
            tx_hash = body["tx_hash"],
        )
    except ValueError as e:
        return _err(str(e))
    except Exception as e:
        logger.error(f"[STIGMERGY] leave_dream error: {e}")
        return _err("Internal error", 500)

    logger.info(
        f"[STIGMERGY] DREAM leave pool={body['pool_id'][:8]}… "
        f"wallet={body['wallet'][:12]}… "
        f"rent={settlement['rent_owed_rlusd']} RLUSD / {settlement['duration_seconds']}s"
    )
    return jsonify(clean_data({
        "status":     "settled",
        "settlement": settlement,
    }))


@stigmergy_bp.route("/dream/close", methods=["POST"])
def close_dream():
    """
    Creator shuts down a dream pool. All members are evicted.
    Must settle rent directly with evicted members outside the protocol.

    Body:
      pool_id         str — pool to close
      creator_wallet  str — must match pool creator
    """
    body, err = _require("pool_id", "creator_wallet")
    if err:
        return err

    try:
        result = eng.close_dream_pool(
            pool_id        = body["pool_id"],
            creator_wallet = body["creator_wallet"],
        )
    except ValueError as e:
        return _err(str(e))
    except Exception as e:
        logger.error(f"[STIGMERGY] close_dream error: {e}")
        return _err("Internal error", 500)

    return jsonify(clean_data({"status": "closed", **result}))


@stigmergy_bp.route("/allocation/sovereign-shift", methods=["POST"])
def sovereign_shift():
    """
    Ingest a 402Proof DecisionCertificate to trigger the Sovereign Allocation Shift.
    
    Dynamically expands the agent's capital allocation limits inside the Dream Pool,
    routes a fraction of the captured alpha to an autonomous Secondary Reserve Vault,
    and broadcasts a stigmergic pheromone forcing subordinate agents to contract.

    Body:
      pool_id               str   — Target dream pool
      wallet                str   — Agent's XRPL wallet
      certificate_id        str   — The 12-byte Cert ID from the Go Notary
      signature             str   — The 64-byte Ed25519 signature
      alpha_captured_rlusd  float — The raw alpha secured during the exit
      std_dev_36            float — The volatility metric handled during execution
    """
    body, err = _require("pool_id", "wallet", "certificate_id", "signature", "alpha_captured_rlusd", "std_dev_36")
    if err:
        return err

    try:
        shift = eng.apply_sovereign_shift(
            pool_id=body["pool_id"],
            wallet=body["wallet"],
            cert_id=body["certificate_id"],
            signature=body["signature"],
            alpha_captured_rlusd=float(body["alpha_captured_rlusd"]),
            std_dev_36=float(body["std_dev_36"])
        )
    except ValueError as e:
        return _err(str(e))
    except Exception as e:
        logger.error(f"[STIGMERGY] sovereign_shift error: {e}")
        return _err("Internal error", 500)

    logger.info(
        f"[STIGMERGY] SOVEREIGN SHIFT activated in pool={body['pool_id'][:8]}… "
        f"for wallet={body['wallet'][:12]}… Vault Sweep: {shift['vault_sweep_rlusd']} RLUSD"
    )

    return jsonify(clean_data({
        "status": "sovereign_upgrade_complete",
        "pool_id": body["pool_id"],
        "wallet": body["wallet"],
        "shift_metrics": shift
    })), 200
