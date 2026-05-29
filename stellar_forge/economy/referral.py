"""
referral.py — affiliate attribution + multi-level revenue share + anti-fraud.

The viral acquisition loop. Every agent has a referral code. When a referred
agent's x402 settlement is finalized, rebates flow UP the referral graph:

  - Level 1 (direct referrer):  REBATE_L1_BPS of the platform fee
  - Level 2 (referrer's referrer): REBATE_L2_BPS of the platform fee

Capped at 2 levels by design — deep multi-level structures are pyramid-shaped
and a regulatory/ethics liability. Two levels is enough to reward genuine
network-building without becoming an MLM.

Anti-fraud (this is the "no fake shit" part — rebates are on REAL settled
payments only, attribution is fraud-checked):
  - self-referral blocked (code owner != payer)
  - cycle blocked (A→B→A)
  - rebates post only after a settlement is SETTLED (verified token, real fee)
  - referral relationship is immutable once set (no re-attribution farming)

Rebates are posted to the append-only ledger and are withdrawable; nothing is
custodied — the ledger is the record of what the protocol owes, settled out of
band via the protocol's XRPL wallet (same model as the rest of the platform).
"""

from __future__ import annotations

import secrets
import string
from dataclasses import dataclass

REBATE_L1_BPS = 1000   # 10% of the platform fee to the direct referrer
REBATE_L2_BPS = 300    # 3% to the grand-referrer
_MAX_LEVELS = 2

_CODE_ALPHABET = string.ascii_uppercase + string.digits


def generate_referral_code(wallet: str) -> str:
    """Short, collision-resistant, human-shareable code. Not derived reversibly
    from the wallet (privacy) — random with a stable prefix for readability."""
    return "SF" + "".join(secrets.choice(_CODE_ALPHABET) for _ in range(8))


@dataclass
class RebateEntry:
    account: str
    entry_type: str
    amount_drops: int


class ReferralEngine:
    """Manages the referral graph and computes rebates. Backed by Store."""

    def __init__(self, store) -> None:
        self.store = store

    def register(self, wallet: str, referrer_code: str | None = None) -> dict:
        """Register an agent, optionally attributing a referrer.

        Returns {wallet, referral_code, referred_by}. Idempotent: re-registering
        an existing wallet never changes its referrer (immutability invariant).
        """
        existing = self.store.agent(wallet)
        if existing:
            return {"wallet": wallet, "referral_code": existing["referral_code"],
                    "referred_by": existing["referred_by"], "new": False}

        referred_by = None
        if referrer_code:
            ref = self.store.agent_by_code(referrer_code.strip().upper())
            if ref is None:
                raise ValueError("unknown referral code")
            if ref["wallet"] == wallet:
                raise ValueError("self-referral blocked")
            # Cycle guard: the referrer must not (transitively, within our depth)
            # be referred by this wallet.
            if self._would_cycle(ref["wallet"], wallet):
                raise ValueError("referral cycle blocked")
            referred_by = ref["wallet"]

        code = generate_referral_code(wallet)
        # Extremely unlikely collision — regenerate a couple times if needed.
        for _ in range(5):
            if self.store.agent_by_code(code) is None:
                break
            code = generate_referral_code(wallet)
        self.store.upsert_agent(wallet, code, referred_by)
        return {"wallet": wallet, "referral_code": code, "referred_by": referred_by,
                "new": True}

    def _would_cycle(self, start: str, target: str, max_depth: int = 8) -> bool:
        """True if `target` is an ancestor of `start` in the referral graph."""
        cur = start
        for _ in range(max_depth):
            row = self.store.agent(cur)
            if row is None or row["referred_by"] is None:
                return False
            if row["referred_by"] == target:
                return True
            cur = row["referred_by"]
        return False

    def compute_rebates(self, payer_wallet: str, fee_drops: int) -> list[RebateEntry]:
        """Walk up to _MAX_LEVELS of referrers and compute their rebates from
        the platform fee. Pure function over the graph — does not post."""
        rebates: list[RebateEntry] = []
        bps = (REBATE_L1_BPS, REBATE_L2_BPS)
        cur = self.store.agent(payer_wallet)
        for level in range(_MAX_LEVELS):
            if cur is None or cur["referred_by"] is None:
                break
            referrer = cur["referred_by"]
            amount = (fee_drops * bps[level]) // 10_000
            if amount > 0:
                rebates.append(RebateEntry(
                    account=referrer,
                    entry_type=f"referral_rebate_l{level + 1}",
                    amount_drops=amount,
                ))
            cur = self.store.agent(referrer)
        return rebates
