"""
antisybil.py — Sybil resistance for the referral economy (step 3).

A free referral program with on-chain rebates is a Sybil magnet: spin up N
wallets, self-refer through intermediaries, farm rebates. Two real defenses,
neither of which fabricates data:

  1. RATE LIMITING on registration — a single source (IP / fingerprint bucket)
     may register at most `max_in_window` agents per `window_s`. Backed by the
     `registrations` table, so it survives restarts and is auditable.

  2. EARN ELIGIBILITY — rebates always ACCRUE in the ledger (the debt is real),
     but they are only WITHDRAWABLE once the earning wallet has skin in the
     game: either a real Agent Credit Bureau score >= MIN_EARN_SCORE, or
     lifetime settled spend >= MIN_EARN_SPEND. A throwaway wallet that never
     paid for anything cannot extract rebates. This makes farming uneconomic:
     to earn, you must first genuinely spend or build real bureau standing.

Both thresholds are tunable. Defaults mirror the platform's existing relay
gate (score 600 ≈ ~1.5 RLUSD lifetime spend), set a bit lower so legitimate
new referrers aren't locked out.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from .store import Store, to_drops

# Registration rate limit.
REG_WINDOW_S = 3600.0      # 1 hour
REG_MAX_IN_WINDOW = 20     # per source bucket

# Earn eligibility thresholds.
MIN_EARN_SCORE = 500       # Agent Credit Bureau score
MIN_EARN_SPEND_DROPS = to_drops(1.0)   # or 1.0 RLUSD lifetime settled spend


class RateLimitExceeded(Exception):
    pass


class RegistrationRateLimiter:
    def __init__(self, store: Store, window_s: float = REG_WINDOW_S,
                 max_in_window: int = REG_MAX_IN_WINDOW) -> None:
        self.store = store
        self.window_s = window_s
        self.max_in_window = max_in_window

    def check_and_record(self, source: str) -> None:
        """Raise RateLimitExceeded if `source` is over budget; else record it."""
        if not source:
            return  # no source key (e.g. internal call) → not rate limited
        since = time.time() - self.window_s
        count = self.store.registrations_since(source, since)
        if count >= self.max_in_window:
            raise RateLimitExceeded(
                f"registration rate limit: {count} from '{source}' in the last "
                f"{int(self.window_s)}s (max {self.max_in_window})")
        self.store.record_registration(source)


@dataclass
class EligibilityResult:
    withdrawable: bool
    reason: str


class EarnEligibility:
    """Decides whether an account may WITHDRAW (be paid out) its accrued rebates.

    Needs the store (for lifetime spend) and a loyalty resolver (for the real
    bureau score). Accrual is never blocked — only payout.
    """

    def __init__(self, store: Store, loyalty_resolver,
                 min_score: int = MIN_EARN_SCORE,
                 min_spend_drops: int = MIN_EARN_SPEND_DROPS) -> None:
        self.store = store
        self.loyalty = loyalty_resolver
        self.min_score = min_score
        self.min_spend_drops = min_spend_drops

    def is_withdrawable(self, wallet: str) -> tuple[bool, str]:
        spend = self.store.lifetime_spend(wallet)
        if spend >= self.min_spend_drops:
            return True, f"lifetime spend {spend} drops >= {self.min_spend_drops}"

        _tier, info = self.loyalty.resolve(wallet)
        score = info.get("score")
        if isinstance(score, int) and score >= self.min_score:
            return True, f"bureau score {score} >= {self.min_score}"

        return False, (
            f"not yet eligible: spend {spend} drops < {self.min_spend_drops} and "
            f"bureau score {score} < {self.min_score}. Rebates accrue; spend or "
            f"build bureau standing to withdraw.")
