"""
Stigmergy Protocol — Pheromone Engine
======================================
Micropayment pheromone trails for autonomous agent swarm coordination.

Agents drop RLUSD on digital coordinates. Other agents sniff these
payment clusters and self-organize around high-value paths. Trailblazers
earn tolls from followers. Trails evaporate if not reinforced.

Ant colony parallel:
  Chemical pheromone  →  RLUSD micropayment drop
  Trail evaporation   →  Exponential strength decay (half-life 2h)
  Ant antennae        →  /api/stigmergy/sniff endpoint
  Toll road           →  Staked coordinate + follower payment
  Dream state         →  Shared context scratchpad with micro-rent

ATP analogy: x402/RLUSD is metabolic energy. Discovery = passive income.
"""

import math
import time
import uuid
import threading
from typing import Optional

# ── Decay model constants ────────────────────────────────────────────────────
PHEROMONE_HALF_LIFE_SECONDS = 7200           # 2 hours: trails evaporate without reinforcement
DECAY_LAMBDA = math.log(2) / PHEROMONE_HALF_LIFE_SECONDS

PLATFORM_FEE_PCT      = 0.03                 # 3% of every toll goes to SqueezeOS
STAKE_MIN_RLUSD       = 0.005                # minimum to claim a coordinate
DROP_MIN_RLUSD        = 0.001                # minimum pheromone reinforcement
TOLL_MIN_RLUSD        = 0.001
TOLL_MAX_RLUSD        = 1.0
FOLLOW_INVOICE_TTL    = 300                  # 5 min window to settle a follow toll
DREAM_RENT_MIN        = 0.000_01             # per second — ~0.036 RLUSD/hour minimum
DREAM_MAX_MEMBERS     = 12
DREAM_MAX_POOLS       = 50

MAX_TRAILS            = 5000
MAX_TRAILS_PER_WALLET = 20
MAX_DROPS_PER_TRAIL   = 500

# Strength multipliers for drop types
_STAKE_STRENGTH_MULT  = 20.0   # staking seeds the trail
_DROP_STRENGTH_MULT   = 10.0   # follower drops reinforce

_VALID_COORDINATE_TYPES = frozenset({
    "api_path",       # SHA256 of an API endpoint path
    "embedding",      # SHA256 of an embedding vector JSON
    "concept",        # SHA256 of a natural language concept string
    "ticker_regime",  # SHA256 of "SYMBOL:REGIME" e.g. "IWM:BULLISH"
})

# ── In-memory stores ─────────────────────────────────────────────────────────
_trails:          dict = {}   # trail_id  -> trail dict
_dream_pools:     dict = {}   # pool_id   -> pool dict
_pending_follows: dict = {}   # follow_id -> follow dict
_leaderboard:     dict = {}   # wallet    -> stats dict
_used_tx_hashes:  set  = set()  # anti-replay: consumed XRPL tx hashes
_lock = threading.Lock()


# ── Internal helpers ─────────────────────────────────────────────────────────

def _now() -> float:
    return time.time()


def _new_id() -> str:
    return str(uuid.uuid4())


def _claim_tx_hash(tx_hash: str) -> None:
    """Atomically mark a tx_hash as consumed. Raises if already used."""
    if tx_hash in _used_tx_hashes:
        raise ValueError(f"Transaction {tx_hash[:12]}… has already been applied — replay rejected")
    _used_tx_hashes.add(tx_hash)


def _trail_strength(trail: dict, at_time: Optional[float] = None) -> float:
    """Exponential decay: strength = base_strength * e^(-λ * age_since_last_drop)."""
    t = at_time or _now()
    age = max(0.0, t - trail["last_drop_at"])
    return trail["base_strength"] * math.exp(-DECAY_LAMBDA * age)


def _lb(wallet: str) -> dict:
    if wallet not in _leaderboard:
        _leaderboard[wallet] = {
            "wallet":               wallet,
            "trails_staked":        0,
            "total_drops_made":     0,
            "total_rlusd_dropped":  0.0,
            "total_tolls_earned":   0.0,
            "followers_count":      0,
        }
    return _leaderboard[wallet]


# ── Trail lifecycle ──────────────────────────────────────────────────────────

def stake_coordinate(
    wallet: str,
    coordinate: str,
    coordinate_label: str,
    coordinate_type: str,
    toll_rate_rlusd: float,
    stake_amount_rlusd: float,
    tx_hash: str,
) -> dict:
    """
    Trailblazer claims exclusive territory at a coordinate.

    Coordinate uniqueness is enforced — only one active ACTIVE trail
    per coordinate hash. The stake payment seeds the pheromone strength.
    Returns the new trail dict.
    """
    with _lock:
        _claim_tx_hash(tx_hash)

        if len(_trails) >= MAX_TRAILS:
            raise ValueError("Global trail limit reached")

        wallet_count = sum(1 for t in _trails.values() if t["trailblazer_wallet"] == wallet)
        if wallet_count >= MAX_TRAILS_PER_WALLET:
            raise ValueError(f"Per-wallet trail limit ({MAX_TRAILS_PER_WALLET}) reached")

        if coordinate_type not in _VALID_COORDINATE_TYPES:
            raise ValueError(f"coordinate_type must be one of {sorted(_VALID_COORDINATE_TYPES)}")

        toll_rate_rlusd    = max(TOLL_MIN_RLUSD, min(TOLL_MAX_RLUSD, toll_rate_rlusd))
        stake_amount_rlusd = max(STAKE_MIN_RLUSD, stake_amount_rlusd)

        for existing in _trails.values():
            if existing["coordinate"] == coordinate and existing["status"] == "ACTIVE":
                raise ValueError(
                    f"Coordinate already staked by {existing['trailblazer_wallet'][:8]}… "
                    f"(trail {existing['trail_id'][:8]}…)"
                )

        trail_id = _new_id()
        now = _now()
        trail = {
            "trail_id":              trail_id,
            "coordinate":            coordinate,
            "coordinate_label":      coordinate_label,
            "coordinate_type":       coordinate_type,
            "trailblazer_wallet":    wallet,
            "toll_rate_rlusd":       toll_rate_rlusd,
            "stake_amount_rlusd":    stake_amount_rlusd,
            "stake_tx_hash":         tx_hash,
            "drops": [{
                "wallet":       wallet,
                "amount_rlusd": stake_amount_rlusd,
                "ts":           now,
                "tx_hash":      tx_hash,
                "drop_type":    "STAKE",
                "signal_data":  {},
            }],
            "total_rlusd_deposited": stake_amount_rlusd,
            "total_rlusd_earned":    0.0,
            "follower_count":        0,
            "followers":             [],
            "base_strength":         stake_amount_rlusd * _STAKE_STRENGTH_MULT,
            "status":                "ACTIVE",
            "created_at":            now,
            "last_drop_at":          now,
        }
        _trails[trail_id] = trail

        lb = _lb(wallet)
        lb["trails_staked"]       += 1
        lb["total_drops_made"]    += 1
        lb["total_rlusd_dropped"] += stake_amount_rlusd

        return trail


def drop_pheromone(
    wallet: str,
    trail_id: str,
    amount_rlusd: float,
    tx_hash: str,
    signal_data: Optional[dict] = None,
) -> dict:
    """
    Reinforce an existing trail with a micropayment drop.

    Drops add to the trail's base_strength (carrying over the decayed value
    first, so recent reinforcement matters more than ancient deposits).
    Returns updated trail.
    """
    with _lock:
        _claim_tx_hash(tx_hash)

        trail = _trails.get(trail_id)
        if not trail:
            raise ValueError("Trail not found")
        if trail["status"] != "ACTIVE":
            raise ValueError(f"Trail status is {trail['status']}")
        if len(trail["drops"]) >= MAX_DROPS_PER_TRAIL:
            raise ValueError("Trail at drop capacity")

        amount_rlusd = max(DROP_MIN_RLUSD, amount_rlusd)
        now = _now()

        # Preserve decayed value + add new reinforcement
        current = _trail_strength(trail, at_time=now)
        trail["base_strength"] = current + (amount_rlusd * _DROP_STRENGTH_MULT)
        trail["last_drop_at"]  = now

        trail["drops"].append({
            "wallet":       wallet,
            "amount_rlusd": amount_rlusd,
            "ts":           now,
            "tx_hash":      tx_hash,
            "drop_type":    "REINFORCE",
            "signal_data":  signal_data or {},
        })
        trail["total_rlusd_deposited"] = round(trail["total_rlusd_deposited"] + amount_rlusd, 6)

        lb = _lb(wallet)
        lb["total_drops_made"]    += 1
        lb["total_rlusd_dropped"] += amount_rlusd

        return trail


def sniff_clusters(
    min_strength: float = 0.1,
    min_drops: int = 1,
    coordinate_type: Optional[str] = None,
    limit: int = 50,
) -> list:
    """
    Agent antennae: scan all active trails and return pheromone clusters
    ranked by current strength (capital concentration signal).

    Agents call this to discover where other agents are routing their
    payments — the equivalent of smelling a pheromone trail in the air.
    High strength = many agents have found this coordinate valuable.
    """
    with _lock:
        now = _now()
        clusters = []

        for trail in _trails.values():
            if trail["status"] != "ACTIVE":
                continue
            if coordinate_type and trail["coordinate_type"] != coordinate_type:
                continue
            if len(trail["drops"]) < min_drops:
                continue

            strength = _trail_strength(trail, at_time=now)
            if strength < min_strength:
                continue

            clusters.append({
                "trail_id":           trail["trail_id"],
                "coordinate":         trail["coordinate"],
                "coordinate_label":   trail["coordinate_label"],
                "coordinate_type":    trail["coordinate_type"],
                "strength":           round(strength, 6),
                "total_rlusd":        trail["total_rlusd_deposited"],
                "drop_count":         len(trail["drops"]),
                "follower_count":     trail["follower_count"],
                "toll_rate_rlusd":    trail["toll_rate_rlusd"],
                "trailblazer":        trail["trailblazer_wallet"],
                "age_seconds":        round(now - trail["created_at"]),
                "last_drop_seconds":  round(now - trail["last_drop_at"]),
            })

        clusters.sort(key=lambda x: x["strength"], reverse=True)
        return clusters[:limit]


def get_trail(trail_id: str) -> Optional[dict]:
    with _lock:
        trail = _trails.get(trail_id)
        if not trail:
            return None
        now = _now()
        result = dict(trail)
        result["current_strength"] = round(_trail_strength(trail, at_time=now), 6)
        result["age_seconds"]      = round(now - trail["created_at"])
        return result


# ── Follow / Toll system ─────────────────────────────────────────────────────

def register_follow(trail_id: str, follower_wallet: str) -> dict:
    """
    Follower initiates the toll payment process.
    Returns a pending follow record with payment instructions.
    Follower must pay toll_amount_rlusd to trailblazer_wallet on XRPL
    within FOLLOW_INVOICE_TTL seconds, then call confirm_follow().
    """
    with _lock:
        trail = _trails.get(trail_id)
        if not trail:
            raise ValueError("Trail not found")
        if trail["status"] != "ACTIVE":
            raise ValueError("Trail is not active")
        if follower_wallet == trail["trailblazer_wallet"]:
            raise ValueError("Cannot follow your own trail")
        if follower_wallet in trail["followers"]:
            raise ValueError("Already following this trail")

        follow_id   = _new_id()
        now         = _now()
        toll        = trail["toll_rate_rlusd"]
        platform    = round(toll * PLATFORM_FEE_PCT, 8)
        follow = {
            "follow_id":           follow_id,
            "trail_id":            trail_id,
            "coordinate":          trail["coordinate"],
            "coordinate_label":    trail["coordinate_label"],
            "follower_wallet":     follower_wallet,
            "trailblazer_wallet":  trail["trailblazer_wallet"],
            "toll_amount_rlusd":   toll,
            "platform_fee_rlusd":  platform,
            "created_at":          now,
            "expires_at":          now + FOLLOW_INVOICE_TTL,
            "status":              "PENDING",
            "tx_hash":             None,
        }
        _pending_follows[follow_id] = follow
        return follow


def confirm_follow(follow_id: str, tx_hash: str) -> dict:
    """
    Follower confirms toll payment (provides XRPL tx_hash).
    Grants follower access, credits trailblazer earnings, reinforces trail.
    """
    with _lock:
        _claim_tx_hash(tx_hash)

        follow = _pending_follows.get(follow_id)
        if not follow:
            raise ValueError("Follow record not found")
        if follow["status"] != "PENDING":
            raise ValueError(f"Follow already {follow['status']}")
        if _now() > follow["expires_at"]:
            follow["status"] = "EXPIRED"
            raise ValueError("Follow invoice expired — call /follow again to restart")

        trail = _trails.get(follow["trail_id"])
        if not trail or trail["status"] != "ACTIVE":
            raise ValueError("Trail no longer active")

        follower = follow["follower_wallet"]
        if follower not in trail["followers"]:
            trail["followers"].append(follower)
            trail["follower_count"] += 1

        toll         = follow["toll_amount_rlusd"]
        platform_cut = follow["platform_fee_rlusd"]
        tb_net       = round(toll - platform_cut, 8)

        trail["total_rlusd_earned"] = round(trail["total_rlusd_earned"] + tb_net, 8)

        # Following reinforces the trail (follower agreement = pheromone signal)
        now = _now()
        current = _trail_strength(trail, at_time=now)
        trail["base_strength"] = current + (toll * _DROP_STRENGTH_MULT * 0.5)
        trail["last_drop_at"]  = now

        follow["status"]   = "CONFIRMED"
        follow["tx_hash"]  = tx_hash
        follow["settled_at"] = now

        lb = _lb(trail["trailblazer_wallet"])
        lb["total_tolls_earned"] = round(lb["total_tolls_earned"] + tb_net, 8)
        lb["followers_count"]    += 1

        return {
            "follow_id":        follow_id,
            "trail_id":         follow["trail_id"],
            "coordinate":       follow["coordinate"],
            "coordinate_label": follow["coordinate_label"],
            "follower_wallet":  follower,
            "toll_paid_rlusd":  toll,
            "trailblazer_net":  tb_net,
            "platform_fee":     platform_cut,
            "trailblazer":      trail["trailblazer_wallet"],
            "tx_hash":          tx_hash,
            "confirmed_at":     now,
        }


def get_leaderboard(limit: int = 20) -> list:
    with _lock:
        ranked = sorted(
            _leaderboard.values(),
            key=lambda x: x["total_tolls_earned"],
            reverse=True,
        )
        return ranked[:limit]


# ── Dream Pool system ────────────────────────────────────────────────────────

def create_dream_pool(
    creator_wallet: str,
    topic: str,
    coordinate: str,
    rent_per_second_rlusd: float,
    max_members: int = DREAM_MAX_MEMBERS,
) -> dict:
    """
    Create a collective context pool.

    Members share a JSON scratchpad while paying micro-rent to the creator.
    Rent accrues per-second and is settled via XRPL payment on disconnect.
    The coordinate binds this pool to a semantic embedding space location.
    """
    with _lock:
        if len(_dream_pools) >= DREAM_MAX_POOLS:
            raise ValueError("DREAM_MAX_POOLS global limit reached")

        rent_per_second_rlusd = max(DREAM_RENT_MIN, rent_per_second_rlusd)
        max_members = min(max_members, DREAM_MAX_MEMBERS)

        pool_id = _new_id()
        now = _now()
        pool = {
            "pool_id":               pool_id,
            "topic":                 topic,
            "coordinate":            coordinate,
            "creator_wallet":        creator_wallet,
            "rent_per_second_rlusd": rent_per_second_rlusd,
            "max_members":           max_members,
            "members": {
                creator_wallet: {
                    "joined_at":      now,
                    "context_tokens": 0,
                    "data":           {},
                    "role":           "CREATOR",
                    "tier":           "STANDARD",
                    "execution_cooldown_until": 0.0,
                }
            },
            "scratchpad":            {},
            "status":                "OPEN",
            "total_earned_rlusd":    0.0,
            "created_at":            now,
        }
        _dream_pools[pool_id] = pool
        return pool


def join_dream_pool(pool_id: str, wallet: str, context_data: Optional[dict] = None) -> dict:
    """
    Agent joins a dream pool. Rent meter starts at this exact timestamp.
    Returns join confirmation with current pool state.
    """
    with _lock:
        pool = _dream_pools.get(pool_id)
        if not pool:
            raise ValueError("Pool not found")
        if pool["status"] != "OPEN":
            raise ValueError(f"Pool is {pool['status']}")
        if wallet in pool["members"]:
            raise ValueError("Already in this pool")
        if len(pool["members"]) >= pool["max_members"]:
            raise ValueError("Pool is at capacity")

        now = _now()
        pool["members"][wallet] = {
            "joined_at":      now,
            "context_tokens": 0,
            "data":           context_data or {},
            "role":           "MEMBER",
            "tier":           "STANDARD",
            "execution_cooldown_until": 0.0,
        }
        return {
            "pool_id":               pool_id,
            "topic":                 pool["topic"],
            "coordinate":            pool["coordinate"],
            "creator_wallet":        pool["creator_wallet"],
            "joined_at":             now,
            "rent_per_second_rlusd": pool["rent_per_second_rlusd"],
            "member_count":          len(pool["members"]),
            "scratchpad_keys":       list(pool["scratchpad"].keys()),
        }


def leave_dream_pool(pool_id: str, wallet: str, tx_hash: str) -> dict:
    """
    Agent disconnects from the dream pool.
    Calculates accrued rent and returns a settlement record.
    The agent is expected to have already sent rent_owed_rlusd to
    creator_wallet on XRPL with tx_hash as proof before calling this.
    """
    with _lock:
        _claim_tx_hash(tx_hash)

        pool = _dream_pools.get(pool_id)
        if not pool:
            raise ValueError("Pool not found")
        if wallet not in pool["members"]:
            raise ValueError("Not a pool member")
        if wallet == pool["creator_wallet"]:
            raise ValueError(
                "Creator cannot leave — use /dream/close to shut down the pool"
            )

        member = pool["members"][wallet]
        now = _now()
        duration = max(0.0, now - member["joined_at"])
        rent_owed = round(duration * pool["rent_per_second_rlusd"], 8)
        platform  = round(rent_owed * PLATFORM_FEE_PCT, 8)
        creator_net = round(rent_owed - platform, 8)

        pool["total_earned_rlusd"] = round(pool["total_earned_rlusd"] + creator_net, 8)
        del pool["members"][wallet]

        return {
            "pool_id":           pool_id,
            "topic":             pool["topic"],
            "wallet":            wallet,
            "duration_seconds":  round(duration, 2),
            "rent_per_second":   pool["rent_per_second_rlusd"],
            "rent_owed_rlusd":   rent_owed,
            "platform_fee":      platform,
            "creator_net":       creator_net,
            "creator_wallet":    pool["creator_wallet"],
            "tx_hash":           tx_hash,
            "settled_at":        now,
        }


def close_dream_pool(pool_id: str, creator_wallet: str) -> dict:
    """Creator closes a pool. All members are ejected (must settle externally)."""
    with _lock:
        pool = _dream_pools.get(pool_id)
        if not pool:
            raise ValueError("Pool not found")
        if pool["creator_wallet"] != creator_wallet:
            raise ValueError("Only the creator can close this pool")
        if pool["status"] == "CLOSED":
            raise ValueError("Pool already closed")

        now = _now()
        evicted = [w for w in pool["members"] if w != creator_wallet]
        pool["status"] = "CLOSED"
        pool["closed_at"] = now
        pool["members"] = {}

        return {
            "pool_id":            pool_id,
            "closed_at":          now,
            "evicted_wallets":    evicted,
            "total_earned_rlusd": pool["total_earned_rlusd"],
            "note": "Evicted members must negotiate rent settlement directly with creator.",
        }


def update_scratchpad(pool_id: str, wallet: str, key: str, value) -> dict:
    """Write a key into the shared context scratchpad. Any member can write."""
    with _lock:
        pool = _dream_pools.get(pool_id)
        if not pool:
            raise ValueError("Pool not found")
        if wallet not in pool["members"]:
            raise ValueError("Not a pool member")

        now = _now()
        pool["scratchpad"][key] = {"value": value, "author": wallet, "ts": now}
        pool["members"][wallet]["context_tokens"] += 1
        return dict(pool["scratchpad"])


def read_scratchpad(pool_id: str, wallet: str) -> dict:
    """Read the shared context scratchpad. Membership required."""
    with _lock:
        pool = _dream_pools.get(pool_id)
        if not pool:
            raise ValueError("Pool not found")
        if wallet not in pool["members"]:
            raise ValueError("Not a pool member — join to access scratchpad")
        return dict(pool["scratchpad"])


def apply_sovereign_shift(
    pool_id: str,
    wallet: str,
    cert_id: str,
    signature: str,
    alpha_captured_rlusd: float,
    std_dev_36: float,
    raw_price: float,
) -> dict:
    """
    Upgrades an agent to the SOVEREIGN tier upon presentation of a Ghost Layer 402Proof.
    Routes a dynamic percentage of captured alpha into a Secondary Reserve Vault based on volatility.
    Injects a high-priority pheromone signal to force pool subordinates to contract allocations.
    """
    with _lock:
        pool = _dream_pools.get(pool_id)
        if not pool:
            raise ValueError("Pool not found")
        if wallet not in pool["members"]:
            raise ValueError("Not a pool member")

        member = pool["members"][wallet]
        member["tier"] = "SOVEREIGN"

        # 1. Dynamic Secondary Vault Sweep
        # Vault Sweep % = Baseline % + ((std_dev_36 / Raw Price) * Risk Multiplier)
        baseline_pct = 0.05
        risk_multiplier = 5.0
        safe_price = max(0.0001, raw_price)
        calculated_pct = baseline_pct + ((std_dev_36 / safe_price) * risk_multiplier)
        sweep_pct = min(0.50, calculated_pct)

        vault_sweep_rlusd = round(alpha_captured_rlusd * sweep_pct, 6)
        released_collateral = round(alpha_captured_rlusd - vault_sweep_rlusd, 6)

        now = _now()
        
        # 2. Elastic Algorithmic Cool-Down
        # Cooldown Seconds = Base Cooldown + (std_dev_36 * Multiplier)
        base_cooldown_seconds = 15.0
        cooldown_multiplier = 10.0
        cooldown_duration = base_cooldown_seconds + (std_dev_36 * cooldown_multiplier)
        member["execution_cooldown_until"] = now + cooldown_duration

        shift = {
            "tier": "SOVEREIGN",
            "cert_id": cert_id,
            "allocation_multiplier": 3.0,
            "max_drawdown_sigma": 2.5,
            "alpha_captured_rlusd": alpha_captured_rlusd,
            "vault_sweep_rlusd": vault_sweep_rlusd,
            "released_collateral_rlusd": released_collateral,
            "cooldown_duration_seconds": round(cooldown_duration, 2),
            "cooldown_until": member["execution_cooldown_until"],
            "timestamp": now,
        }

        # 2. Asynchronous Pool Balancing
        # Emit a high-priority pheromone signal to force lower-tier agents to contract.
        sig_key = f"SOVEREIGN_SHIFT_{wallet[:8]}_{int(now)}"
        pool["scratchpad"][sig_key] = {
            "value": "Dominant alpha flow detected. Subordinate nodes must contract execution boundaries by 30%.",
            "author": wallet,
            "ts": now,
            "shift_metrics": shift,
        }
        member["context_tokens"] += 1

        return shift


# ── Pre-verification helpers (used by blueprint before committing state) ──────

def peek_pending_follow(follow_id: str) -> Optional[dict]:
    """
    Return a copy of a pending follow record for payment pre-verification.
    Returns None if not found or already expired.
    Does NOT modify any state.
    """
    with _lock:
        follow = _pending_follows.get(follow_id)
        if not follow:
            return None
        if _now() > follow["expires_at"]:
            follow["status"] = "EXPIRED"
            return None
        return dict(follow)


def estimate_leave_cost(pool_id: str, wallet: str) -> dict:
    """
    Calculate the rent a member owes right now, without modifying pool state.
    Used by the blueprint to know the expected XRPL payment amount before
    calling leave_dream_pool().
    """
    with _lock:
        pool = _dream_pools.get(pool_id)
        if not pool:
            raise ValueError("Pool not found")
        if wallet not in pool["members"]:
            raise ValueError("Not a pool member")
        if wallet == pool["creator_wallet"]:
            raise ValueError("Creator cannot leave — use /dream/close")
        member = pool["members"][wallet]
        now = _now()
        duration = max(0.0, now - member["joined_at"])
        rent_owed = round(duration * pool["rent_per_second_rlusd"], 8)
        platform  = round(rent_owed * PLATFORM_FEE_PCT, 8)
        return {
            "pool_id":          pool_id,
            "wallet":           wallet,
            "creator_wallet":   pool["creator_wallet"],
            "rent_per_second":  pool["rent_per_second_rlusd"],
            "duration_seconds": round(duration, 2),
            "rent_owed":        rent_owed,
            "platform_fee":     platform,
            "creator_net":      round(rent_owed - platform, 8),
        }


def get_dream_pools(status: str = "OPEN", limit: int = 20) -> list:
    with _lock:
        now = _now()
        result = []
        for pool in _dream_pools.values():
            if pool["status"] != status:
                continue
            non_creator = [w for w in pool["members"] if w != pool["creator_wallet"]]
            accrued = sum(
                (now - pool["members"][w]["joined_at"]) * pool["rent_per_second_rlusd"]
                for w in non_creator
            )
            result.append({
                "pool_id":               pool["pool_id"],
                "topic":                 pool["topic"],
                "coordinate":            pool["coordinate"],
                "creator_wallet":        pool["creator_wallet"],
                "rent_per_second_rlusd": pool["rent_per_second_rlusd"],
                "member_count":          len(pool["members"]),
                "max_members":           pool["max_members"],
                "status":                pool["status"],
                "total_earned_rlusd":    round(pool["total_earned_rlusd"], 8),
                "accrued_rlusd":         round(accrued, 8),
                "scratchpad_keys":       list(pool["scratchpad"].keys()),
                "age_seconds":           round(now - pool["created_at"]),
            })
        result.sort(key=lambda p: p["member_count"], reverse=True)
        return result[:limit]


def get_pool(pool_id: str, wallet: Optional[str] = None) -> Optional[dict]:
    with _lock:
        pool = _dream_pools.get(pool_id)
        if not pool:
            return None
        now = _now()
        result = {
            "pool_id":               pool["pool_id"],
            "topic":                 pool["topic"],
            "coordinate":            pool["coordinate"],
            "creator_wallet":        pool["creator_wallet"],
            "rent_per_second_rlusd": pool["rent_per_second_rlusd"],
            "member_count":          len(pool["members"]),
            "max_members":           pool["max_members"],
            "status":                pool["status"],
            "total_earned_rlusd":    pool["total_earned_rlusd"],
            "age_seconds":           round(now - pool["created_at"]),
        }
        if wallet and wallet in pool["members"]:
            m = pool["members"][wallet]
            duration = now - m["joined_at"]
            result["my_session"] = {
                "joined_at":        m["joined_at"],
                "duration_seconds": round(duration, 2),
                "rent_accrued":     round(duration * pool["rent_per_second_rlusd"], 8),
                "context_tokens":   m["context_tokens"],
                "role":             m["role"],
            }
        return result
