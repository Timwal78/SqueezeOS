"""
Stellar Forge economy — the real growth engine.

Unifies the platform's existing, real primitives (402Proof Agent Credit Bureau,
relay reseller discounts) into one viral flywheel: affiliate referrals +
loyalty tiers + durable settlement. No demo data; no in-memory-only product
state; rebates only on verified, settled x402 payments.
"""

from .proof402_client import Proof402Client
from .store import Store, to_drops, to_rlusd, DROPS_PER_RLUSD
from .loyalty import LoyaltyResolver, Tier, TIERS, tier_for_score, apply_discount
from .referral import ReferralEngine, generate_referral_code, RebateEntry
from .growth_engine import GrowthEngine, Receipt, PROTOCOL_ACCOUNT
from .antisybil import (
    RegistrationRateLimiter, EarnEligibility, RateLimitExceeded,
)
from .payouts import PayoutRunner, PayoutResult, XRPLSubmitter, DryRunSubmitter

__all__ = [
    "Proof402Client",
    "Store", "to_drops", "to_rlusd", "DROPS_PER_RLUSD",
    "LoyaltyResolver", "Tier", "TIERS", "tier_for_score", "apply_discount",
    "ReferralEngine", "generate_referral_code", "RebateEntry",
    "GrowthEngine", "Receipt", "PROTOCOL_ACCOUNT",
    "RegistrationRateLimiter", "EarnEligibility", "RateLimitExceeded",
    "PayoutRunner", "PayoutResult", "XRPLSubmitter", "DryRunSubmitter",
]
