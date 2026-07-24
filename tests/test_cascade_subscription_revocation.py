"""
Regression test for the no-op subscription-cancellation handler in
core/api/cascade_bp.py, found 2026-07-24 during a live Stripe audit.

checkout.session.completed issued an `apikey:{key}` in Redis with
"active": true and NO way to find it again by subscription ID. The
customer.subscription.deleted/paused branch only logged a message and
never revoked anything. This matters more than a typical missed-revocation
bug because proof402_integration.py's require_payment decorator accepts
ANY key starting with "sml_live_" (not just cascade-specific ones) as a
universal bypass for the x402 payment gate on every @require_payment
endpoint in the whole API, as long as Redis has it marked active. CASCADE's
issued keys are literally f"sml_live_cascade_{...}", so a single $149
CASCADE payment was granting permanent, free, account-wide paid-API access
that survived cancellation indefinitely.

Every sibling billing blueprint (aeo_stripe_bp, trade_desk_stripe_bp,
deltaforge_bp, and keys_bp as of its own 2026-07-20 fix — see
test_keys_bp_subscription_revocation.py) already revokes correctly on
cancellation. cascade_bp.py was simply missed when that pattern was
established elsewhere.

Fixed by: (1) checkout.session.completed now also stores a reverse index
`cascade:sub:{sub_id}` -> api_key; (2) the
customer.subscription.deleted/paused branch now looks up that index and
deletes both keys, mirroring keys_bp.py's already-tested pattern.

Drives the real, unmodified webhook() view end-to-end via a minimal Flask
test app wrapping cascade_bp — only stripe.Webhook.construct_event (the
Stripe SDK's own signature-verification internals) and _get_redis() are
faked, with a real dict-backed fake standing in for Redis so the actual
set/get/delete logic under test runs for real.
"""

import json
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask  # noqa: E402

import core.api.cascade_bp as cascade_bp  # noqa: E402


class _FakeRedis:
    """Real dict-backed stand-in — the actual set/get/delete calls under
    test run for real against this, only the network transport is fake."""
    def __init__(self):
        self._data = {}

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self._data:
            return None
        self._data[key] = value
        return True

    def get(self, key):
        return self._data.get(key)

    def delete(self, key):
        self._data.pop(key, None)


def _make_app():
    app = Flask(__name__)
    cascade_bp._STRIPE_SECRET_KEY = "sk_test_fake"
    cascade_bp._STRIPE_WEBHOOK_SECRET = "whsec_fake"
    app.register_blueprint(cascade_bp.cascade_bp, url_prefix="/api/cascade")
    return app


def test_subscription_cancellation_now_actually_revokes_the_cascade_key():
    fake_redis = _FakeRedis()
    app = _make_app()
    client = app.test_client()

    checkout_event = {
        "id": "evt_test_checkout_1",
        "type": "checkout.session.completed",
        "data": {"object": {
            "metadata": {"product": "CASCADE_ACCUMULATOR", "tier": "human_monthly"},
            "customer_email": "customer@example.com",
            "subscription": "sub_TESTSUB1",
        }},
    }
    cancellation_event = {
        "id": "evt_test_cancel_1",
        "type": "customer.subscription.deleted",
        "data": {"object": {"id": "sub_TESTSUB1"}},
    }

    with patch.object(cascade_bp, "_get_redis", return_value=fake_redis), \
         patch("stripe.Webhook.construct_event", return_value=checkout_event):
        resp = client.post("/api/cascade/stripe/webhook", data=b"{}", headers={"Stripe-Signature": "fake"})
        assert resp.status_code == 200

    # Real key + reverse index must now exist, and match the sml_live_
    # prefix require_payment's Stripe-key bypass checks for.
    issued_keys = [k for k in fake_redis._data if k.startswith("apikey:sml_live_cascade_")]
    assert len(issued_keys) == 1, f"expected exactly 1 issued key, got {issued_keys}"
    assert fake_redis.get("cascade:sub:sub_TESTSUB1") == issued_keys[0].removeprefix("apikey:")
    assert json.loads(fake_redis.get(issued_keys[0]))["active"] is True

    # Now cancel the subscription
    with patch.object(cascade_bp, "_get_redis", return_value=fake_redis), \
         patch("stripe.Webhook.construct_event", return_value=cancellation_event):
        resp = client.post("/api/cascade/stripe/webhook", data=b"{}", headers={"Stripe-Signature": "fake"})
        assert resp.status_code == 200

    assert fake_redis.get(issued_keys[0]) is None, (
        "the CASCADE API key must be deleted from Redis on real subscription cancellation "
        "-- otherwise it remains a permanent, free, account-wide require_payment bypass "
        "(see proof402_integration.py's sml_live_ prefix check)"
    )
    assert fake_redis.get("cascade:sub:sub_TESTSUB1") is None
    print("PASS: CASCADE subscription cancellation now actually revokes the API key in Redis")


def test_subscription_pause_also_revokes_the_cascade_key():
    """paused (e.g. a failed-payment dunning pause) must revoke exactly
    like a full cancellation -- both were previously no-ops."""
    fake_redis = _FakeRedis()
    app = _make_app()
    client = app.test_client()

    checkout_event = {
        "id": "evt_test_checkout_2",
        "type": "checkout.session.completed",
        "data": {"object": {
            "metadata": {"product": "CASCADE_ACCUMULATOR", "tier": "human_monthly"},
            "customer_email": "customer2@example.com",
            "subscription": "sub_TESTSUB2",
        }},
    }
    pause_event = {
        "id": "evt_test_pause_2",
        "type": "customer.subscription.paused",
        "data": {"object": {"id": "sub_TESTSUB2"}},
    }

    with patch.object(cascade_bp, "_get_redis", return_value=fake_redis), \
         patch("stripe.Webhook.construct_event", return_value=checkout_event):
        client.post("/api/cascade/stripe/webhook", data=b"{}", headers={"Stripe-Signature": "fake"})

    issued_keys = [k for k in fake_redis._data if k.startswith("apikey:sml_live_cascade_")]
    assert len(issued_keys) == 1

    with patch.object(cascade_bp, "_get_redis", return_value=fake_redis), \
         patch("stripe.Webhook.construct_event", return_value=pause_event):
        resp = client.post("/api/cascade/stripe/webhook", data=b"{}", headers={"Stripe-Signature": "fake"})
        assert resp.status_code == 200

    assert fake_redis.get(issued_keys[0]) is None, "a paused subscription must also revoke the key"
    print("PASS: CASCADE subscription pause also revokes the API key in Redis")


def test_non_cascade_checkout_sessions_are_ignored():
    """The account-wide checkout.session.completed handler must not issue a
    CASCADE key for an unrelated product's purchase (e.g. AEO Suite)."""
    fake_redis = _FakeRedis()
    app = _make_app()
    client = app.test_client()

    other_product_event = {
        "id": "evt_test_other_1",
        "type": "checkout.session.completed",
        "data": {"object": {
            "metadata": {"product": "AEO_SUITE"},
            "customer_email": "someone@example.com",
            "subscription": "sub_OTHERPRODUCT",
        }},
    }

    with patch.object(cascade_bp, "_get_redis", return_value=fake_redis), \
         patch("stripe.Webhook.construct_event", return_value=other_product_event):
        resp = client.post("/api/cascade/stripe/webhook", data=b"{}", headers={"Stripe-Signature": "fake"})
        assert resp.status_code == 200

    assert not any(k.startswith("apikey:sml_live_cascade_") for k in fake_redis._data), (
        "a non-CASCADE checkout session must not issue a CASCADE key"
    )
    print("PASS: non-CASCADE checkout sessions are correctly ignored")


def test_cancellation_with_unknown_subscription_does_not_crash():
    fake_redis = _FakeRedis()
    app = _make_app()
    client = app.test_client()

    cancellation_event = {
        "id": "evt_test_cancel_unknown",
        "type": "customer.subscription.deleted",
        "data": {"object": {"id": "sub_NEVER_SEEN_BEFORE"}},
    }
    with patch.object(cascade_bp, "_get_redis", return_value=fake_redis), \
         patch("stripe.Webhook.construct_event", return_value=cancellation_event):
        resp = client.post("/api/cascade/stripe/webhook", data=b"{}", headers={"Stripe-Signature": "fake"})
    assert resp.status_code == 200
    print("PASS: cancellation for an unrecognized subscription degrades gracefully, no crash")


if __name__ == "__main__":
    test_subscription_cancellation_now_actually_revokes_the_cascade_key()
    test_subscription_pause_also_revokes_the_cascade_key()
    test_non_cascade_checkout_sessions_are_ignored()
    test_cancellation_with_unknown_subscription_does_not_crash()
    print("\nAll regression tests passed.")
