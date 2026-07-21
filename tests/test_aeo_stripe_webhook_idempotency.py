"""
End-to-end regression test proving core/api/aeo_stripe_bp.py's webhook no
longer double-processes a retried Stripe delivery.

Stripe retries webhook deliveries on timeout/5xx (documented, not rare).
Before core/stripe_idempotency.py was wired in, a retried `invoice.paid`
delivery for the same event id re-ran `_handle_invoice_paid()`, which calls
`aeo_treasury_bp.accrue_usd()` -- silently double-crediting the AEO
Treasury's internal 5% revenue ledger for one real payment. This never
touched the real Stripe charge (Stripe is the source of truth for money
actually moved); it corrupted this app's own bookkeeping.

This test drives the real, unmodified `aeo_stripe_webhook()` view (and the
real, unmodified `_handle_invoice_paid()` -> `accrue_usd()` -> `_accrue()`
chain in aeo_treasury_bp.py) via a minimal Flask app wrapping aeo_stripe_bp.
Only `_verify_stripe_signature` (Stripe's own HMAC check, irrelevant to the
bug) and the Redis client are faked -- with a real dict-backed fake so the
actual idempotency SET/GET logic and the actual ledger arithmetic run for
real.
"""
import json
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask  # noqa: E402

import core.api.aeo_stripe_bp as aeo_stripe_bp  # noqa: E402
import core.api.aeo_treasury_bp as aeo_treasury_bp  # noqa: E402


class _FakeRedis:
    """Real dict-backed stand-in with real NX/EX SET semantics, so the
    actual idempotency guard logic under test is exercised for real."""

    def __init__(self):
        self._data = {}

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self._data:
            return None
        self._data[key] = value
        return True

    def get(self, key):
        return self._data.get(key)

    def setex(self, key, ttl, value):
        self._data[key] = value
        return True


def _make_app():
    app = Flask(__name__)
    app.register_blueprint(aeo_stripe_bp.aeo_stripe_bp)
    return app


def _invoice_paid_event(event_id, price_id, amount_paid_cents):
    return {
        "id": event_id,
        "type": "invoice.paid",
        "data": {"object": {
            "lines": {"data": [{"price": {"id": price_id}}]},
            "amount_paid": amount_paid_cents,
        }},
    }


def test_duplicate_invoice_paid_delivery_does_not_double_accrue_treasury():
    fake_redis = _FakeRedis()
    app = _make_app()
    client = app.test_client()

    signal_price_id = "price_signal_test"
    event = _invoice_paid_event("evt_duplicate_test_1", signal_price_id, 4900)  # $49.00

    with patch.object(aeo_stripe_bp, "_SIGNAL_PRICE_ID", signal_price_id), \
         patch.object(aeo_stripe_bp, "_WEBHOOK_SECRET", "whsec_test"), \
         patch.object(aeo_stripe_bp, "_verify_stripe_signature", return_value=True), \
         patch.object(aeo_stripe_bp, "_get_redis", return_value=fake_redis), \
         patch.object(aeo_treasury_bp, "_get_redis", return_value=fake_redis):

        # First delivery -- must accrue.
        resp1 = client.post(
            "/api/aeo/stripe/webhook",
            data=json.dumps(event),
            headers={"Stripe-Signature": "fake", "Content-Type": "application/json"},
        )
        assert resp1.status_code == 200

        ledger_after_first = json.loads(fake_redis.get(aeo_treasury_bp._LEDGER_KEY))
        expected_cut = 49.00 * aeo_treasury_bp._TREASURY_CUT
        assert abs(ledger_after_first["accrued_rlusd"] - expected_cut) < 1e-6, (
            f"expected {expected_cut} accrued after first delivery, got {ledger_after_first['accrued_rlusd']}"
        )

        # Stripe retries the SAME event id (e.g. a slow response triggered a retry).
        resp2 = client.post(
            "/api/aeo/stripe/webhook",
            data=json.dumps(event),
            headers={"Stripe-Signature": "fake", "Content-Type": "application/json"},
        )
        assert resp2.status_code == 200

        ledger_after_retry = json.loads(fake_redis.get(aeo_treasury_bp._LEDGER_KEY))
        assert ledger_after_retry["accrued_rlusd"] == ledger_after_first["accrued_rlusd"], (
            "a retried delivery of the SAME Stripe event id must not accrue the treasury "
            f"a second time -- got {ledger_after_retry['accrued_rlusd']} vs "
            f"{ledger_after_first['accrued_rlusd']} after the first delivery"
        )
    print("PASS: duplicate invoice.paid delivery does not double-accrue AEO Treasury")


def test_genuinely_new_event_still_accrues_normally():
    """Guard against a fix that's so aggressive it blocks legitimate events too."""
    fake_redis = _FakeRedis()
    app = _make_app()
    client = app.test_client()

    signal_price_id = "price_signal_test"
    event_a = _invoice_paid_event("evt_real_a", signal_price_id, 4900)
    event_b = _invoice_paid_event("evt_real_b", signal_price_id, 4900)

    with patch.object(aeo_stripe_bp, "_SIGNAL_PRICE_ID", signal_price_id), \
         patch.object(aeo_stripe_bp, "_WEBHOOK_SECRET", "whsec_test"), \
         patch.object(aeo_stripe_bp, "_verify_stripe_signature", return_value=True), \
         patch.object(aeo_stripe_bp, "_get_redis", return_value=fake_redis), \
         patch.object(aeo_treasury_bp, "_get_redis", return_value=fake_redis):

        client.post("/api/aeo/stripe/webhook", data=json.dumps(event_a),
                    headers={"Stripe-Signature": "fake", "Content-Type": "application/json"})
        client.post("/api/aeo/stripe/webhook", data=json.dumps(event_b),
                    headers={"Stripe-Signature": "fake", "Content-Type": "application/json"})

        ledger = json.loads(fake_redis.get(aeo_treasury_bp._LEDGER_KEY))
        expected_cut = 2 * 49.00 * aeo_treasury_bp._TREASURY_CUT
        assert abs(ledger["accrued_rlusd"] - expected_cut) < 1e-6, (
            f"two genuinely distinct events should both accrue -- expected {expected_cut}, got {ledger['accrued_rlusd']}"
        )
    print("PASS: two genuinely distinct events both accrue normally")


if __name__ == "__main__":
    test_duplicate_invoice_paid_delivery_does_not_double_accrue_treasury()
    test_genuinely_new_event_still_accrues_normally()
    print("\nAll regression tests passed.")
