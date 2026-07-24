"""
Regression test for POST /api/cascade/admin/reconcile — the retroactive
sweep for CASCADE keys issued before the cascade:sub:{sub_id} reverse index
existed (see test_cascade_subscription_revocation.py / PR #388). Those
pre-fix keys have a `customer` field but no `sub_id`, so the ordinary
cancellation webhook can never find and revoke them even after the fix
shipped -- a customer who cancelled before 2026-07-24 keeps permanent free
access via proof402_integration.py's sml_live_ prefix bypass.

This endpoint doesn't guess who to revoke: it reconciles Redis against
Stripe's real, current subscription list. A key survives only if it
positively matches an active/trialing subscription, by sub_id (post-fix
keys) or by customer email (pre-fix keys). Anything unmatched is revoked.

Drives the real, unmodified cascade_admin_reconcile() view via a minimal
Flask test app wrapping cascade_bp -- only stripe.Subscription.list and
_get_redis() are faked, with a real dict-backed fake Redis so the actual
scan/get/delete logic under test runs for real.
"""

import json
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask  # noqa: E402

import core.api.cascade_bp as cascade_bp  # noqa: E402


class _FakeRedis:
    """Real dict-backed stand-in -- scan/get/delete run for real against this."""
    def __init__(self, data=None):
        self._data = dict(data or {})

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self._data:
            return None
        self._data[key] = value
        return True

    def get(self, key):
        return self._data.get(key)

    def delete(self, key):
        self._data.pop(key, None)

    def scan_iter(self, match=None):
        prefix = (match or "*").rstrip("*")
        return [k for k in list(self._data.keys()) if k.startswith(prefix)]


class _FakeSubList:
    def __init__(self, subs):
        self._subs = subs

    def auto_paging_iter(self):
        return iter(self._subs)


def _make_app():
    app = Flask(__name__)
    cascade_bp._STRIPE_SECRET_KEY = "sk_test_fake"
    cascade_bp._CASCADE_PRICE_ID = "price_test_cascade"
    cascade_bp._CASCADE_ADMIN_SECRET = "test_admin_secret"
    app.register_blueprint(cascade_bp.cascade_bp, url_prefix="/api/cascade")
    return app


def _fake_sub_list_factory(active_subs):
    """active_subs: list of {"id": ..., "customer": {"email": ...}} -- returned
    for status='active' queries, empty for 'trialing' (no trials in this test)."""
    def _fake_sub_list(price=None, status=None, limit=None, expand=None):
        if status == "active":
            return _FakeSubList(active_subs)
        return _FakeSubList([])
    return _fake_sub_list


def test_reconcile_requires_secret_header():
    app = _make_app()
    client = app.test_client()
    resp = client.post("/api/cascade/admin/reconcile")
    assert resp.status_code == 401
    print("PASS: reconcile endpoint rejects requests without the admin secret")


def test_reconcile_revokes_key_with_no_matching_active_subscription():
    """A post-fix key (has sub_id) whose subscription is no longer active/
    trialing in Stripe must be revoked -- this is the ordinary case the
    webhook itself should have caught but might have missed (e.g. a
    cancellation event that failed delivery)."""
    fake_redis = _FakeRedis({
        "apikey:sml_live_cascade_cancelled1": json.dumps({
            "active": True, "customer": "cancelled@example.com", "sub_id": "sub_CANCELLED",
        }),
        "cascade:sub:sub_CANCELLED": "sml_live_cascade_cancelled1",
    })
    app = _make_app()
    client = app.test_client()

    with patch.object(cascade_bp, "_get_redis", return_value=fake_redis), \
         patch("stripe.Subscription.list", side_effect=_fake_sub_list_factory([])):
        resp = client.post(
            "/api/cascade/admin/reconcile",
            headers={"X-Cascade-Admin-Secret": "test_admin_secret"},
        )

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["revoked_count"] == 1
    assert body["revoked"][0]["api_key"] == "sml_live_cascade_cancelled1"
    assert fake_redis.get("apikey:sml_live_cascade_cancelled1") is None
    assert fake_redis.get("cascade:sub:sub_CANCELLED") is None
    print("PASS: key with no matching active subscription is revoked")


def test_reconcile_keeps_key_matching_active_subscription_by_sub_id():
    fake_redis = _FakeRedis({
        "apikey:sml_live_cascade_stillpaying1": json.dumps({
            "active": True, "customer": "paying@example.com", "sub_id": "sub_STILLACTIVE",
        }),
        "cascade:sub:sub_STILLACTIVE": "sml_live_cascade_stillpaying1",
    })
    app = _make_app()
    client = app.test_client()

    active_subs = [{"id": "sub_STILLACTIVE", "customer": {"email": "paying@example.com"}}]
    with patch.object(cascade_bp, "_get_redis", return_value=fake_redis), \
         patch("stripe.Subscription.list", side_effect=_fake_sub_list_factory(active_subs)):
        resp = client.post(
            "/api/cascade/admin/reconcile",
            headers={"X-Cascade-Admin-Secret": "test_admin_secret"},
        )

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["revoked_count"] == 0
    assert body["kept"] == 1
    assert fake_redis.get("apikey:sml_live_cascade_stillpaying1") is not None
    print("PASS: key matching an active subscription by sub_id is kept")


def test_reconcile_keeps_pre_fix_key_matched_by_customer_email():
    """Pre-fix keys have no sub_id at all -- must fall back to matching the
    stored customer email against Stripe's active subscriber emails."""
    fake_redis = _FakeRedis({
        "apikey:sml_live_cascade_prefixkey1": json.dumps({
            "active": True, "customer": "PreFix@Example.com",
        }),
    })
    app = _make_app()
    client = app.test_client()

    active_subs = [{"id": "sub_WHATEVER", "customer": {"email": "prefix@example.com"}}]
    with patch.object(cascade_bp, "_get_redis", return_value=fake_redis), \
         patch("stripe.Subscription.list", side_effect=_fake_sub_list_factory(active_subs)):
        resp = client.post(
            "/api/cascade/admin/reconcile",
            headers={"X-Cascade-Admin-Secret": "test_admin_secret"},
        )

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["revoked_count"] == 0
    assert body["kept"] == 1
    assert fake_redis.get("apikey:sml_live_cascade_prefixkey1") is not None
    print("PASS: pre-fix key with no sub_id is kept via case-insensitive customer email match")


def test_reconcile_revokes_pre_fix_key_with_no_matching_email():
    """The actual bug this endpoint exists to fix: a pre-fix key for a
    customer who has since cancelled has no sub_id and no active email
    match anywhere in Stripe -- must be revoked."""
    fake_redis = _FakeRedis({
        "apikey:sml_live_cascade_prefixcancelled1": json.dumps({
            "active": True, "customer": "longgone@example.com",
        }),
    })
    app = _make_app()
    client = app.test_client()

    with patch.object(cascade_bp, "_get_redis", return_value=fake_redis), \
         patch("stripe.Subscription.list", side_effect=_fake_sub_list_factory([])):
        resp = client.post(
            "/api/cascade/admin/reconcile",
            headers={"X-Cascade-Admin-Secret": "test_admin_secret"},
        )

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["revoked_count"] == 1
    assert body["revoked"][0]["customer"] == "longgone@example.com"
    assert fake_redis.get("apikey:sml_live_cascade_prefixcancelled1") is None
    print("PASS: pre-fix key for a cancelled, unmatched customer is revoked -- the actual bug fix")


if __name__ == "__main__":
    test_reconcile_requires_secret_header()
    test_reconcile_revokes_key_with_no_matching_active_subscription()
    test_reconcile_keeps_key_matching_active_subscription_by_sub_id()
    test_reconcile_keeps_pre_fix_key_matched_by_customer_email()
    test_reconcile_revokes_pre_fix_key_with_no_matching_email()
    print("\nAll regression tests passed.")
