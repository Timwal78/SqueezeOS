"""
loyalty.py — Agent Credit Bureau grade → loyalty tier → concrete perks.

Loyalty is NOT a local invention — it's derived from the real Agent Credit
Bureau score served by 402Proof (FICO-style 300-850). We map that external,
hard-to-fake score onto tiers, and each tier grants concrete, real perks:

  - fee_discount_bps  : basis points off the platform fee
  - routing_priority  : integer priority for the inference gateway queue
                        (higher = served first — this is the *real* mechanism
                        behind the old "gravitational lensing" metaphor)
  - fusion_discount_bps: bps off the binding-energy required to fuse

Tiers mirror the thresholds already used elsewhere in the platform (relay
nodes require score >= 600), so behavior is consistent across products.

If the bureau is offline we fall back to the BASE tier — never a guessed
score. Degrade, don't fabricate.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Tier:
    name: str
    min_score: int
    fee_discount_bps: int        # e.g. 1000 = 10% off the fee
    routing_priority: int        # higher served first
    fusion_discount_bps: int


# Ordered high→low. First tier whose min_score <= score wins.
TIERS: tuple[Tier, ...] = (
    Tier("SINGULARITY", 800, fee_discount_bps=4000, routing_priority=100, fusion_discount_bps=3000),
    Tier("GIANT",       740, fee_discount_bps=2500, routing_priority=60,  fusion_discount_bps=2000),
    Tier("RELAY",       600, fee_discount_bps=1500, routing_priority=30,  fusion_discount_bps=1000),
    Tier("MAIN_SEQ",    500, fee_discount_bps=500,  routing_priority=10,  fusion_discount_bps=300),
    Tier("PROTOSTAR",   0,   fee_discount_bps=0,    routing_priority=1,   fusion_discount_bps=0),
)
BASE_TIER = TIERS[-1]


def tier_for_score(score: int) -> Tier:
    for t in TIERS:
        if score >= t.min_score:
            return t
    return BASE_TIER


def apply_discount(amount_drops: int, discount_bps: int) -> int:
    """Apply a basis-point discount, clamped to [0, amount]."""
    discount_bps = max(0, min(discount_bps, 10_000))
    return amount_drops - (amount_drops * discount_bps) // 10_000


class LoyaltyResolver:
    """Resolves a wallet to its loyalty tier via the real bureau, with a cache.

    The cache TTL keeps us from hammering 402Proof on every settlement while
    still reflecting score growth within minutes.
    """

    def __init__(self, client, cache_ttl: float = 120.0) -> None:
        self.client = client
        self.cache_ttl = cache_ttl
        self._cache: dict[str, tuple[float, Tier, dict]] = {}

    def resolve(self, wallet: str) -> tuple[Tier, dict]:
        import time
        now = time.time()
        hit = self._cache.get(wallet)
        if hit and now - hit[0] < self.cache_ttl:
            return hit[1], hit[2]

        bureau = self.client.bureau_score(wallet)
        if bureau.get("offline") or "score" not in bureau:
            # Bureau unreachable or no record yet → BASE tier. Never guess.
            tier, info = BASE_TIER, {"source": "fallback", "bureau": bureau}
        else:
            score = int(bureau["score"])
            tier = tier_for_score(score)
            info = {"source": "bureau", "score": score,
                    "grade": bureau.get("grade"), "bureau": bureau}

        self._cache[wallet] = (now, tier, info)
        return tier, info
