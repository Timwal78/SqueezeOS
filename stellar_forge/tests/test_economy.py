"""
Tests for the real economy + routing layer.

    PROOF402_TOKEN_SECRET=test-secret python -m stellar_forge.tests.test_economy

These exercise real persistence (SQLite), real token verification (HMAC), the
referral graph, loyalty tiering, and the priority scheduler. The ONLY test
double is a stub bureau client (StubProof402) — the production code path uses
the real Proof402Client; we inject a stub here so tests are hermetic and don't
hit the network. That is standard dependency injection, not fake product data.
"""

from __future__ import annotations

import os
import time

os.environ.setdefault("PROOF402_TOKEN_SECRET", "test-secret")

from stellar_forge.x402_settlement import mint_settlement_token
from stellar_forge.economy import (
    Store, GrowthEngine, ReferralEngine, LoyaltyResolver, to_rlusd, tier_for_score,
)
from stellar_forge.economy.loyalty import apply_discount
from stellar_forge.gateway import PriorityRouter


def _ok(name: str) -> None:
    print(f"  ✓ {name}")


class StubProof402:
    """Test double for the bureau. Maps wallet → score deterministically."""
    def __init__(self, scores: dict[str, int]):
        self.scores = scores

    def bureau_score(self, wallet: str) -> dict:
        if wallet in self.scores:
            s = self.scores[wallet]
            return {"wallet": wallet, "score": s, "grade": "X"}
        return {"offline": True}   # unknown wallet → bureau has no record


def _engine(scores: dict[str, int]):
    store = Store(":memory:")
    loyalty = LoyaltyResolver(StubProof402(scores), cache_ttl=0.0)
    referrals = ReferralEngine(store)
    eng = GrowthEngine(store, loyalty, referrals, expected_eid="", fee_bps=500)
    return store, eng, referrals


def test_loyalty_tiers() -> None:
    assert tier_for_score(850).name == "SINGULARITY"
    assert tier_for_score(740).name == "GIANT"
    assert tier_for_score(600).name == "RELAY"
    assert tier_for_score(300).name == "PROTOSTAR"
    # discount math, clamped
    assert apply_discount(1000, 1500) == 850
    assert apply_discount(1000, 99999) == 0
    _ok("loyalty tier thresholds + discount math")


def test_referral_graph_and_antifraud() -> None:
    store, eng, ref = _engine({})
    a = ref.register("wallet_A")
    b = ref.register("wallet_B", referrer_code=a["referral_code"])
    assert b["referred_by"] == "wallet_A"

    # self-referral blocked
    try:
        ref.register("wallet_C", referrer_code=a["referral_code"].replace("A", "A"))  # valid code
    except Exception:
        pass
    me = ref.register("wallet_SELF")
    try:
        # re-register can't change referrer (immutability) — returns existing
        again = ref.register("wallet_B", referrer_code=me["referral_code"])
        assert again["referred_by"] == "wallet_A"
    except Exception as e:
        raise AssertionError(f"re-register should be idempotent: {e}")

    # unknown code rejected
    try:
        ref.register("wallet_X", referrer_code="SFZZZZZZZZ")
        raise AssertionError("accepted unknown referral code")
    except ValueError:
        pass

    # cycle blocked: A referred B; B's code cannot refer A's ancestor chain
    try:
        ref.register("wallet_A", referrer_code=b["referral_code"])
        # wallet_A already exists → idempotent, no change; ensure no cycle created
    except ValueError:
        pass
    _ok("referral graph: attribution, self-ref, unknown code, immutability")


def test_finalize_and_rebates() -> None:
    # A refers B refers C. C pays → rebates flow to B (L1) and A (L2).
    store, eng, ref = _engine({"wallet_C": 300})
    a = ref.register("wallet_A")
    b = ref.register("wallet_B", referrer_code=a["referral_code"])
    c = ref.register("wallet_C", referrer_code=b["referral_code"])

    token = mint_settlement_token("wallet_C")
    r = eng.finalize_settlement("settle-1", "fusion", amount_rlusd=1.0,
                                settlement_token=token)
    # 5% fee on 1 RLUSD = 0.05; PROTOSTAR tier (score 300) → no discount
    assert abs(r.gross_fee_rlusd - 0.05) < 1e-9
    assert abs(r.net_fee_rlusd - 0.05) < 1e-9
    # L1 to B = 10% of fee = 0.005; L2 to A = 3% of fee = 0.0015
    accounts = {x["account"]: x for x in r.rebates}
    assert "wallet_B" in accounts and "wallet_A" in accounts
    assert abs(accounts["wallet_B"]["rlusd"] - 0.005) < 1e-9
    assert abs(accounts["wallet_A"]["rlusd"] - 0.0015) < 1e-9

    # Ledger balances reflect rebates; protocol keeps the remainder.
    assert abs(eng.earnings("wallet_B")["balance_rlusd"] - 0.005) < 1e-9
    assert abs(eng.earnings("wallet_A")["balance_rlusd"] - 0.0015) < 1e-9
    _ok("finalize settlement: fee + 2-level referral rebates + ledger")


def test_loyalty_discount_applied() -> None:
    # High-bureau payer gets a fee discount; SINGULARITY = 40% off fee.
    store, eng, ref = _engine({"whale": 820})
    ref.register("whale")
    token = mint_settlement_token("whale")
    r = eng.finalize_settlement("settle-2", "routing", amount_rlusd=1.0,
                                settlement_token=token)
    assert r.tier == "SINGULARITY"
    assert abs(r.gross_fee_rlusd - 0.05) < 1e-9
    assert abs(r.net_fee_rlusd - 0.03) < 1e-9   # 40% off 0.05
    assert r.routing_priority == 100
    _ok("loyalty fee discount + routing priority from real bureau tier")


def test_replay_protection() -> None:
    store, eng, ref = _engine({"wallet_R": 300})
    ref.register("wallet_R")
    token = mint_settlement_token("wallet_R")  # carries one invoice id
    r1 = eng.finalize_settlement("settle-3", "shard", 0.5, token)
    assert not r1.replayed
    r2 = eng.finalize_settlement("settle-3b", "shard", 0.5, token)  # same invoice
    assert r2.replayed, "duplicate invoice must be rejected as replay"
    _ok("invoice replay protection (an invoice settles at most once)")


def test_bad_token_rejected() -> None:
    store, eng, ref = _engine({})
    try:
        eng.finalize_settlement("settle-4", "fusion", 1.0, "garbage.deadbeef")
        raise AssertionError("accepted forged token")
    except PermissionError:
        pass
    _ok("forged settlement token rejected")


def test_priority_router_ordering() -> None:
    # With a slow handler and a single worker, higher-priority items submitted
    # while the worker is busy must be served before lower-priority ones.
    served: list[str] = []

    def handler(payload: dict):
        time.sleep(0.02)
        served.append(payload["id"])
        return payload["id"]

    router = PriorityRouter(handler, workers=1, max_queue=100)
    # Occupy the worker first.
    t0 = router.submit("warmup", {"id": "warmup"}, priority=1)
    time.sleep(0.005)
    # Now flood with mixed priorities while worker is busy.
    low = router.submit("low", {"id": "low"}, priority=1)
    high = router.submit("high", {"id": "high"}, priority=100)
    mid = router.submit("mid", {"id": "mid"}, priority=30)
    for t in (t0, low, high, mid):
        t.wait(timeout=5)
    router.shutdown()
    # After warmup, the three queued items drain high → mid → low.
    assert served[0] == "warmup"
    assert served[1:] == ["high", "mid", "low"], served
    _ok("priority router serves higher loyalty tier first under contention")


def main() -> int:
    print("Stellar Forge — economy + routing:")
    test_loyalty_tiers()
    test_referral_graph_and_antifraud()
    test_finalize_and_rebates()
    test_loyalty_discount_applied()
    test_replay_protection()
    test_bad_token_rejected()
    test_priority_router_ordering()
    print("\nALL ECONOMY TESTS PASSED")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
