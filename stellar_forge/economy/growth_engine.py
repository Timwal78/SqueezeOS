"""
growth_engine.py — the flywheel.

Ties settlement + loyalty + referral into one finalize step and exposes the
viral loop:

    refer / share  ──▶  bureau score climbs  ──▶  loyalty tier up
         ▲                                              │
         │                                              ▼
    rebates + cheaper fusion/routing  ◀──  fee discount + routing priority

`finalize_settlement` is the single real entry point. It:
  1. verifies the x402 settlement token (real HMAC, pure CPU)
  2. enforces invoice replay-protection (an invoice settles at most once)
  3. resolves the payer's loyalty tier from the REAL Agent Credit Bureau
  4. applies the tier's fee discount
  5. persists the settlement + posts the net fee to the protocol ledger
  6. computes and posts referral rebates up to 2 levels
  7. returns an auditable receipt

No demo minting on this path. Tokens must be real 402Proof tokens (issued
after on-chain RLUSD settlement). The only place a token is minted locally is
the test suite, which sets PROOF402_TOKEN_SECRET explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..x402_settlement import verify_settlement_token
from .store import Store, to_drops, to_rlusd
from .loyalty import LoyaltyResolver, Tier, apply_discount
from .referral import ReferralEngine

PROTOCOL_ACCOUNT = "PROTOCOL"
DEFAULT_FEE_BPS = 500   # 5% base platform fee (matches futures market fee)


@dataclass
class Receipt:
    settlement_id: str
    kind: str
    payer_wallet: str
    amount_rlusd: float
    gross_fee_rlusd: float
    net_fee_rlusd: float
    tier: str
    routing_priority: int
    rebates: list[dict] = field(default_factory=list)
    replayed: bool = False

    def to_dict(self) -> dict:
        return {
            "settlement_id": self.settlement_id, "kind": self.kind,
            "payer_wallet": self.payer_wallet, "amount_rlusd": self.amount_rlusd,
            "gross_fee_rlusd": self.gross_fee_rlusd, "net_fee_rlusd": self.net_fee_rlusd,
            "tier": self.tier, "routing_priority": self.routing_priority,
            "rebates": self.rebates, "replayed": self.replayed,
        }


class GrowthEngine:
    def __init__(self, store: Store, loyalty: LoyaltyResolver,
                 referrals: ReferralEngine, expected_eid: str | None = None,
                 fee_bps: int = DEFAULT_FEE_BPS, eligibility=None) -> None:
        self.store = store
        self.loyalty = loyalty
        self.referrals = referrals
        self.expected_eid = expected_eid
        self.fee_bps = fee_bps
        self.eligibility = eligibility   # optional EarnEligibility (sybil step 3)

    def finalize_settlement(self, settlement_id: str, kind: str,
                            amount_rlusd: float, settlement_token: str) -> Receipt:
        if amount_rlusd <= 0:
            raise ValueError("amount must be positive")
        if kind not in ("fusion", "shard", "routing"):
            raise ValueError(f"unknown settlement kind: {kind}")

        # 1. Real token verification (HMAC-SHA256, no network).
        v = verify_settlement_token(
            settlement_token,
            expected_eid=self.expected_eid if self.expected_eid is not None else "",
        )
        if not v["valid"]:
            raise PermissionError(f"settlement token rejected: {v['reason']}")
        payer = v["wallet"]
        invoice_id = v.get("invoice_id")
        if not payer:
            raise PermissionError("token carries no payer wallet")

        # 2. Replay protection — an invoice may settle at most once.
        if invoice_id and self.store.settlement_exists_for_invoice(invoice_id):
            existing = self.store.settlement(settlement_id) or {}
            return Receipt(
                settlement_id=settlement_id, kind=kind, payer_wallet=payer,
                amount_rlusd=amount_rlusd, gross_fee_rlusd=0.0, net_fee_rlusd=0.0,
                tier="-", routing_priority=0, replayed=True,
            )

        # 3-4. Loyalty tier (real bureau) → fee discount.
        tier, _info = self.loyalty.resolve(payer)
        amount_drops = to_drops(amount_rlusd)
        gross_fee = (amount_drops * self.fee_bps) // 10_000
        net_fee = apply_discount(gross_fee, tier.fee_discount_bps)

        # 5. Persist settlement + protocol fee.
        self.store.create_settlement(
            settlement_id=settlement_id, kind=kind, payer_wallet=payer,
            amount_drops=amount_drops, fee_drops=net_fee,
            invoice_id=invoice_id, state="OPEN",
        )
        self.store.mark_settled(settlement_id)

        # 6. Referral rebates come OUT of the net fee (protocol keeps the rest).
        rebate_entries = self.referrals.compute_rebates(payer, net_fee)
        total_rebated = sum(r.amount_drops for r in rebate_entries)
        protocol_keep = max(0, net_fee - total_rebated)

        self.store.post_ledger(settlement_id, PROTOCOL_ACCOUNT, "fee", protocol_keep)
        rebates_out = []
        for r in rebate_entries:
            self.store.post_ledger(settlement_id, r.account, r.entry_type, r.amount_drops)
            rebates_out.append({
                "account": r.account, "type": r.entry_type,
                "rlusd": to_rlusd(r.amount_drops),
            })

        return Receipt(
            settlement_id=settlement_id, kind=kind, payer_wallet=payer,
            amount_rlusd=amount_rlusd,
            gross_fee_rlusd=to_rlusd(gross_fee), net_fee_rlusd=to_rlusd(net_fee),
            tier=tier.name, routing_priority=tier.routing_priority,
            rebates=rebates_out,
        )

    def earnings(self, wallet: str) -> dict:
        """Accrued referral earnings + whether they're withdrawable (sybil gate)."""
        accrued = to_rlusd(self.store.balance(wallet))
        withdrawable, reason = (True, "no eligibility gate configured")
        if self.eligibility is not None:
            withdrawable, reason = self.eligibility.is_withdrawable(wallet)
        return {
            "wallet": wallet,
            "accrued_rlusd": accrued,
            "withdrawable": withdrawable,
            "eligibility_reason": reason,
            "ledger": [dict(row) for row in self.store.ledger_for(wallet)],
        }
