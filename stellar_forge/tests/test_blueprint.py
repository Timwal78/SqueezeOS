"""
Integration test for the feature-flagged Flask blueprint (core/api/forge_bp.py).

    PROOF402_TOKEN_SECRET=test-secret python -m stellar_forge.tests.test_blueprint

Builds a bare Flask app with just forge_bp (not the full create_app, which pulls
the whole trading stack), injects a stubbed economy graph with a fake bureau +
recording payout submitter, and drives the real HTTP handlers via the test
client. Verifies register → settle → earnings → quote → payout end to end.

Skips cleanly if Flask isn't installed.
"""

from __future__ import annotations

import os

os.environ.setdefault("PROOF402_TOKEN_SECRET", "test-secret")


def _ok(name: str) -> None:
    print(f"  ✓ {name}")


def main() -> int:
    try:
        from flask import Flask
    except ImportError:
        print("Stellar Forge blueprint test: SKIPPED (flask not installed)")
        return 0

    from stellar_forge.x402_settlement import mint_test_token
    from stellar_forge.economy import (
        Store, LoyaltyResolver, ReferralEngine, GrowthEngine,
        RegistrationRateLimiter, EarnEligibility, PayoutRunner, to_drops,
    )
    import core.api.forge_bp as fb

    class StubProof402:
        def __init__(self, scores): self.scores = scores
        def bureau_score(self, wallet):
            return ({"wallet": wallet, "score": self.scores[wallet], "grade": "X"}
                    if wallet in self.scores else {"offline": True})

    class RecordingSubmitter:
        def __init__(self): self.calls = []
        def submit(self, dest, drops):
            self.calls.append((dest, drops)); return f"TX-{len(self.calls)}"

    # Build a real economy graph with stubbed external deps, inject as the
    # blueprint's singleton (bypasses _build_forge which would hit the network).
    store = Store(":memory:")
    loyalty = LoyaltyResolver(StubProof402({"payer": 760, "ref1": 760}), cache_ttl=0.0)
    rl = RegistrationRateLimiter(store, window_s=3600, max_in_window=5)
    referrals = ReferralEngine(store, rate_limiter=rl)
    elig = EarnEligibility(store, loyalty, min_score=500, min_spend_drops=to_drops(1.0))
    growth = GrowthEngine(store, loyalty, referrals, eligibility=elig)
    sub = RecordingSubmitter()
    payouts = PayoutRunner(store, submitter=sub, eligibility=elig, min_payout_drops=1)
    fb._forge = {"store": store, "loyalty": loyalty, "referrals": referrals,
                 "growth": growth, "payouts": payouts, "router": None}

    os.environ["OWNER_API_KEY"] = "owner-secret"

    app = Flask(__name__)
    app.register_blueprint(fb.forge_bp, url_prefix="/api/forge")
    c = app.test_client()

    # register referrer + referred payer
    r = c.post("/api/forge/register", json={"wallet": "ref1"})
    assert r.status_code == 200, r.get_json()
    code = r.get_json()["referral_code"]
    r = c.post("/api/forge/register", json={"wallet": "payer", "referrer_code": code})
    assert r.get_json()["referred_by"] == "ref1"
    _ok("POST /register attributes referrer")

    # quote reflects the bureau tier
    q = c.get("/api/forge/quote/payer").get_json()
    assert q["tier"] == "GIANT" and q["routing_priority"] == 60, q
    _ok("GET /quote returns loyalty tier from bureau")

    # settle without token → 402
    assert c.post("/api/forge/settle", json={"settlement_id": "x", "kind": "fusion",
                                             "amount_rlusd": 1.0}).status_code == 402
    # settle with a valid token
    tok = mint_test_token("payer")
    r = c.post("/api/forge/settle",
               json={"settlement_id": "s1", "kind": "fusion", "amount_rlusd": 1.0},
               headers={"X-Payment-Token": tok})
    body = r.get_json()
    assert r.status_code == 200 and body["tier"] == "GIANT", body
    assert any(x["account"] == "ref1" for x in body["rebates"])
    _ok("POST /settle verifies x402 token, accrues fee + rebate")

    # earnings shows accrued; ref1 has bureau 720 so withdrawable
    e = c.get("/api/forge/earnings/ref1").get_json()
    assert e["accrued_rlusd"] > 0 and e["withdrawable"] is True, e
    _ok("GET /earnings shows accrued + withdrawable")

    # payout requires owner key
    assert c.post("/api/forge/payout", json={"account": "ref1", "dest_wallet": "rDest"}).status_code == 403
    r = c.post("/api/forge/payout", json={"account": "ref1", "dest_wallet": "rDest"},
               headers={"X-Owner-Key": "owner-secret"})
    pr = r.get_json()
    assert r.status_code == 200 and pr["state"] == "CONFIRMED" and pr["tx_hash"], pr
    assert len(sub.calls) == 1
    _ok("POST /payout owner-gated; pays once via submitter")

    # route without upstream → 503 (no fake inference)
    assert c.post("/api/forge/route", json={"wallet": "payer", "payload": {}}).status_code == 503
    _ok("POST /route returns 503 when no upstream configured (no fake data)")

    print("\nBLUEPRINT TEST PASSED")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
