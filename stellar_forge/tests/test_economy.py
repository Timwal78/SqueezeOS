"""
Tests for the real economy + routing + payouts + sybil layers.

    PROOF402_TOKEN_SECRET=test-secret python -m stellar_forge.tests.test_economy

Runs the DB-backed suite against SQLite (:memory:) always, and against
PostgreSQL too when STELLAR_FORGE_TEST_PG is set to a DSN — proving the dual
backend for real, not by assertion.

The only test double is a stub bureau client (StubProof402) and a recording
payout submitter (RecordingSubmitter) — standard dependency injection so tests
are hermetic, not fake product data.
"""

from __future__ import annotations

import os
import time

os.environ.setdefault("PROOF402_TOKEN_SECRET", "test-secret")

from stellar_forge.x402_settlement import mint_test_token
from stellar_forge.economy import (
    Store, GrowthEngine, ReferralEngine, LoyaltyResolver, to_rlusd, to_drops,
    tier_for_score, RegistrationRateLimiter, EarnEligibility, RateLimitExceeded,
    PayoutRunner,
)
from stellar_forge.economy.loyalty import apply_discount
from stellar_forge.gateway import PriorityRouter

DSN = ":memory:"   # overridden when running the PG pass


def _ok(name: str) -> None:
    print(f"  ✓ {name}")


class StubProof402:
    def __init__(self, scores: dict[str, int]):
        self.scores = scores

    def bureau_score(self, wallet: str) -> dict:
        if wallet in self.scores:
            return {"wallet": wallet, "score": self.scores[wallet], "grade": "X"}
        return {"offline": True}


class RecordingSubmitter:
    """Records on-chain submissions; returns a deterministic 'hash'. Test-only."""
    def __init__(self):
        self.calls = []

    def submit(self, dest_wallet: str, amount_drops: int) -> str:
        self.calls.append((dest_wallet, amount_drops))
        return f"TESTHASH-{len(self.calls)}-{amount_drops}"


def _store() -> Store:
    s = Store(DSN)
    if DSN != ":memory:":
        s._truncate_all_for_tests()
    return s


def _engine(scores: dict[str, int], store: Store | None = None):
    store = store or _store()
    loyalty = LoyaltyResolver(StubProof402(scores), cache_ttl=0.0)
    referrals = ReferralEngine(store)
    eng = GrowthEngine(store, loyalty, referrals, expected_eid="", fee_bps=500)
    return store, eng, referrals, loyalty


# -------------------------------------------------------- pure (backend-independent)
def test_loyalty_tiers() -> None:
    assert tier_for_score(850).name == "SINGULARITY"
    assert tier_for_score(740).name == "GIANT"
    assert tier_for_score(600).name == "RELAY"
    assert tier_for_score(300).name == "PROTOSTAR"
    assert apply_discount(1000, 1500) == 850
    assert apply_discount(1000, 99999) == 0
    _ok("loyalty tier thresholds + discount math")


# -------------------------------------------------------------- DB-backed suite
def test_referral_graph_and_antifraud() -> None:
    store, eng, ref, _ = _engine({})
    a = ref.register("wallet_A")
    b = ref.register("wallet_B", referrer_code=a["referral_code"])
    assert b["referred_by"] == "wallet_A"

    again = ref.register("wallet_B", referrer_code=ref.register("wallet_SELF")["referral_code"])
    assert again["referred_by"] == "wallet_A"  # immutable

    try:
        ref.register("wallet_X", referrer_code="SFZZZZZZZZ")
        raise AssertionError("accepted unknown referral code")
    except ValueError:
        pass
    _ok("referral graph: attribution, immutability, unknown code")


def test_finalize_and_rebates() -> None:
    store, eng, ref, _ = _engine({"wallet_C": 300})
    a = ref.register("wallet_A")
    b = ref.register("wallet_B", referrer_code=a["referral_code"])
    ref.register("wallet_C", referrer_code=b["referral_code"])

    r = eng.finalize_settlement("settle-1", "fusion", 1.0, mint_test_token("wallet_C"))
    assert abs(r.gross_fee_rlusd - 0.05) < 1e-9
    accounts = {x["account"]: x for x in r.rebates}
    assert abs(accounts["wallet_B"]["rlusd"] - 0.005) < 1e-9
    assert abs(accounts["wallet_A"]["rlusd"] - 0.0015) < 1e-9
    assert abs(eng.earnings("wallet_B")["accrued_rlusd"] - 0.005) < 1e-9
    _ok("finalize: fee + 2-level rebates + ledger")


def test_loyalty_discount_applied() -> None:
    store, eng, ref, _ = _engine({"whale": 820})
    ref.register("whale")
    r = eng.finalize_settlement("settle-2", "routing", 1.0, mint_test_token("whale"))
    assert r.tier == "SINGULARITY"
    assert abs(r.net_fee_rlusd - 0.03) < 1e-9   # 40% off 0.05
    assert r.routing_priority == 100
    _ok("loyalty fee discount + routing priority from bureau tier")


def test_replay_protection() -> None:
    store, eng, ref, _ = _engine({"wallet_R": 300})
    ref.register("wallet_R")
    token = mint_test_token("wallet_R")
    assert not eng.finalize_settlement("s3", "shard", 0.5, token).replayed
    assert eng.finalize_settlement("s3b", "shard", 0.5, token).replayed
    _ok("invoice replay protection")


def test_bad_token_rejected() -> None:
    store, eng, ref, _ = _engine({})
    try:
        eng.finalize_settlement("s4", "fusion", 1.0, "garbage.deadbeef")
        raise AssertionError("accepted forged token")
    except PermissionError:
        pass
    _ok("forged settlement token rejected")


def test_sybil_rate_limit() -> None:
    store = _store()
    limiter = RegistrationRateLimiter(store, window_s=3600, max_in_window=3)
    ref = ReferralEngine(store, rate_limiter=limiter)
    for i in range(3):
        ref.register(f"w{i}", source="1.2.3.4")
    try:
        ref.register("w_over", source="1.2.3.4")
        raise AssertionError("rate limit not enforced")
    except RateLimitExceeded:
        pass
    # A different source is unaffected.
    ref.register("w_other", source="5.6.7.8")
    _ok("sybil: registration rate limit per source")


def test_earn_eligibility_gate() -> None:
    # Referrer with no spend + low bureau cannot withdraw; accrual still happens.
    store, eng, ref, loyalty = _engine({"payer": 300})   # payer low score
    elig = EarnEligibility(store, loyalty, min_score=500, min_spend_drops=to_drops(1.0))
    eng.eligibility = elig

    a = ref.register("referrer")           # referrer: no spend, unknown bureau
    ref.register("payer", referrer_code=a["referral_code"])
    eng.finalize_settlement("s5", "fusion", 1.0, mint_test_token("payer"))

    e = eng.earnings("referrer")
    assert e["accrued_rlusd"] > 0
    assert e["withdrawable"] is False      # gated: no skin in the game

    # Payout runner refuses an ineligible account.
    runner = PayoutRunner(store, submitter=RecordingSubmitter(), eligibility=elig,
                          min_payout_drops=1)
    res = runner.pay("referrer", dest_wallet="rReferrerXRPL")
    assert res.state == "INELIGIBLE", res
    _ok("sybil: rebates accrue but withdrawal gated until skin-in-the-game")


def test_payout_idempotency() -> None:
    # Eligible referrer (gets bureau score 700) → payout once, never double-pays.
    store, eng, ref, loyalty = _engine({"payer2": 300, "ref2": 700})
    elig = EarnEligibility(store, loyalty, min_score=500, min_spend_drops=to_drops(1.0))
    eng.eligibility = elig

    a = ref.register("ref2")
    ref.register("payer2", referrer_code=a["referral_code"])
    eng.finalize_settlement("s6", "fusion", 1.0, mint_test_token("payer2"))

    sub = RecordingSubmitter()
    runner = PayoutRunner(store, submitter=sub, eligibility=elig, min_payout_drops=1)

    first = runner.pay("ref2", dest_wallet="rRef2XRPL")
    assert first.state == "CONFIRMED", first
    assert len(sub.calls) == 1
    paid = sub.calls[0][1]
    assert paid == to_drops(0.005)         # L1 rebate = 10% of 0.05 fee

    # Running again with nothing new owed must NOT pay again.
    second = runner.pay("ref2", dest_wallet="rRef2XRPL")
    assert second.state == "SKIPPED", second
    assert len(sub.calls) == 1, "double-paid!"

    # A new settlement accrues more → next payout covers only the delta.
    eng.finalize_settlement("s7", "fusion", 1.0, mint_test_token("payer2-2"))
    # payer2-2 isn't referred, so ref2 gets nothing new → still skipped.
    third = runner.pay("ref2", dest_wallet="rRef2XRPL")
    assert third.state == "SKIPPED"
    assert len(sub.calls) == 1
    _ok("payout: idempotent, cursor-based, never double-pays")


def test_priority_router_ordering() -> None:
    # Deterministic (no sleeps): the single worker is pinned inside `warmup` on
    # an event until all other items are enqueued, so ordering is guaranteed by
    # priority — high(100) > mid(30) > low(1) — not by timing.
    import threading
    served: list[str] = []
    started = threading.Event()   # set when the worker enters warmup
    release = threading.Event()   # lets warmup finish once others are queued

    def handler(payload: dict):
        if payload["id"] == "warmup":
            started.set()
            release.wait(timeout=5)
        served.append(payload["id"])
        return payload["id"]

    router = PriorityRouter(handler, workers=1, max_queue=100)
    t0 = router.submit("warmup", {"id": "warmup"}, priority=1)
    assert started.wait(timeout=5), "worker never picked up warmup"
    # Worker is now blocked in warmup; submit() enqueues synchronously, so all
    # three are in the heap before we release.
    low = router.submit("low", {"id": "low"}, priority=1)
    high = router.submit("high", {"id": "high"}, priority=100)
    mid = router.submit("mid", {"id": "mid"}, priority=30)
    release.set()
    for t in (t0, low, high, mid):
        t.wait(timeout=5)
    router.shutdown()
    assert served == ["warmup", "high", "mid", "low"], served
    _ok("priority router serves higher loyalty tier first under contention")


_DB_TESTS = [
    test_referral_graph_and_antifraud,
    test_finalize_and_rebates,
    test_loyalty_discount_applied,
    test_replay_protection,
    test_bad_token_rejected,
    test_sybil_rate_limit,
    test_earn_eligibility_gate,
    test_payout_idempotency,
]


def main() -> int:
    global DSN
    print("Stellar Forge — pure logic:")
    test_loyalty_tiers()
    test_priority_router_ordering()

    print("Stellar Forge — DB-backed (SQLite :memory:):")
    DSN = ":memory:"
    for t in _DB_TESTS:
        t()

    pg = os.environ.get("STELLAR_FORGE_TEST_PG")
    if pg:
        print(f"Stellar Forge — DB-backed (PostgreSQL):")
        DSN = pg
        for t in _DB_TESTS:
            t()
    else:
        print("Stellar Forge — PostgreSQL pass: SKIPPED (set STELLAR_FORGE_TEST_PG)")

    print("\nALL ECONOMY TESTS PASSED")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
