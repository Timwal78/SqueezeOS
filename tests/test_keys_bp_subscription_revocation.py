"""
Regression test for the no-op subscription-cancellation handler in
core/api/keys_bp.py (2026-07-20, found by background audit agent).

checkout.session.completed provisioned `apikey:{key}` in Redis with NO TTL
and NO way to find it again by Stripe customer ID. The
customer.subscription.deleted/canceled branch was a literal `pass` — every
sibling blueprint (aeo_stripe_bp, trade_desk_stripe_bp, deltaforge_bp) calls
a real _revoke_key() on cancellation, but this one never did. A customer who
subscribed, got a key, then cancelled in the Stripe billing portal kept full
API access forever — GET /api/keys/status with the old key would return
{"active": true} indefinitely.

Fixed by: (1) checkout.session.completed now also stores a reverse index
`customer:{customer_id}` -> api_key, mirroring the pattern already used in
aeo_stripe_bp.py's _issue_key()/_revoke_key(); (2) the cancellation branch
now looks up that index and deletes both keys, so a subsequently-checked
status() call correctly 404s.

This drives the real, unmodified webhook() view end-to-end via a minimal
Flask test app wrapping keys_bp — only stripe.Webhook.construct_event (the
Stripe SDK's own signature-verification internals) and the Redis client are
faked, with a real dict-backed fake standing in for Redis so the actual
set/get/delete logic under test is exercised for real.
"""

import json
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask  # noqa: E402

import core.api.keys_bp as keys_bp  # noqa: E402


class _FakeRedis:
    """Real dict-backed stand-in — the actual set/get/delete calls under
    test run for real against this, only the network transport is fake."""
    def __init__(self):
        self._data = {}

    def set(self, key, value):
        self._data[key] = value

    def get(self, key):
        return self._data.get(key)

    def delete(self, key):
        self._data.pop(key, None)


def _make_app():
    app = Flask(__name__)
    app.register_blueprint(keys_bp.keys_bp)
    return app


def test_subscription_cancellation_now_actually_revokes_the_key():
    fake_redis = _FakeRedis()
    app = _make_app()
    client = app.test_client()

    checkout_event = {
        "type": "checkout.session.completed",
        "created": 1700000000,
        "data": {"object": {
            "client_reference_id": "sk_live_test_apikey_123",
            "customer_details": {"email": "customer@example.com"},
            "customer": "cus_TESTCUSTOMER1",
            "mode": "subscription",
        }},
    }
    cancellation_event = {
        "type": "customer.subscription.deleted",
        "data": {"object": {"customer": "cus_TESTCUSTOMER1"}},
    }

    with patch.object(keys_bp, "r", fake_redis), \
         patch.object(keys_bp.stripe.Webhook, "construct_event", return_value=checkout_event):
        resp = client.post("/api/keys/webhook", data=b"{}", headers={"Stripe-Signature": "fake"})
        assert resp.status_code == 200

    # Real key + reverse index must now exist
    assert fake_redis.get("apikey:sk_live_test_apikey_123") is not None
    assert fake_redis.get("customer:cus_TESTCUSTOMER1") == "sk_live_test_apikey_123"

    # Now cancel the subscription
    with patch.object(keys_bp, "r", fake_redis), \
         patch.object(keys_bp.stripe.Webhook, "construct_event", return_value=cancellation_event):
        resp = client.post("/api/keys/webhook", data=b"{}", headers={"Stripe-Signature": "fake"})
        assert resp.status_code == 200

    assert fake_redis.get("apikey:sk_live_test_apikey_123") is None, (
        "the API key must be deleted from Redis on real subscription cancellation"
    )
    assert fake_redis.get("customer:cus_TESTCUSTOMER1") is None
    print("PASS: subscription cancellation now actually revokes the API key in Redis")


def test_status_endpoint_correctly_404s_after_real_cancellation():
    """End-to-end through the actual customer-facing check: a cancelled
    customer's key must now fail /api/keys/status, not read as active forever."""
    fake_redis = _FakeRedis()
    app = _make_app()
    client = app.test_client()

    checkout_event = {
        "type": "checkout.session.completed",
        "created": 1700000000,
        "data": {"object": {
            "client_reference_id": "sk_live_test_apikey_456",
            "customer_details": {"email": "customer2@example.com"},
            "customer": "cus_TESTCUSTOMER2",
            "mode": "subscription",
        }},
    }
    cancellation_event = {
        "type": "customer.subscription.canceled",
        "data": {"object": {"customer": "cus_TESTCUSTOMER2"}},
    }

    with patch.object(keys_bp, "r", fake_redis):
        with patch.object(keys_bp.stripe.Webhook, "construct_event", return_value=checkout_event):
            client.post("/api/keys/webhook", data=b"{}", headers={"Stripe-Signature": "fake"})

        status_resp = client.get("/api/keys/status", headers={"X-API-Key": "sk_live_test_apikey_456"})
        assert status_resp.status_code == 200
        assert json.loads(status_resp.data)["active"] is True

        with patch.object(keys_bp.stripe.Webhook, "construct_event", return_value=cancellation_event):
            client.post("/api/keys/webhook", data=b"{}", headers={"Stripe-Signature": "fake"})

        status_resp_after = client.get("/api/keys/status", headers={"X-API-Key": "sk_live_test_apikey_456"})
        assert status_resp_after.status_code == 404, (
            f"a cancelled customer's key must now be rejected, got {status_resp_after.status_code}: {status_resp_after.data}"
        )
    print("PASS: /api/keys/status correctly 404s for a real cancelled customer's key")


def test_cancellation_with_unknown_customer_does_not_crash():
    """No prior checkout for this customer — a cancellation webhook for an
    unrecognized customer must degrade gracefully, not error."""
    fake_redis = _FakeRedis()
    app = _make_app()
    client = app.test_client()

    cancellation_event = {
        "type": "customer.subscription.deleted",
        "data": {"object": {"customer": "cus_NEVER_SEEN_BEFORE"}},
    }
    with patch.object(keys_bp, "r", fake_redis), \
         patch.object(keys_bp.stripe.Webhook, "construct_event", return_value=cancellation_event):
        resp = client.post("/api/keys/webhook", data=b"{}", headers={"Stripe-Signature": "fake"})
    assert resp.status_code == 200
    print("PASS: cancellation for an unrecognized customer degrades gracefully, no crash")


if __name__ == "__main__":
    test_subscription_cancellation_now_actually_revokes_the_key()
    test_status_endpoint_correctly_404s_after_real_cancellation()
    test_cancellation_with_unknown_customer_does_not_crash()
    print("\nAll regression tests passed.")
