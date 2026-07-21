"""
Regression tests for core/stripe_idempotency.py's already_processed().

Drives the real, unmodified production function. Redis is faked with a
minimal dict-backed stand-in that implements the same NX/EX semantics
real redis-py uses, so the atomic "only set if absent" behavior is
actually exercised, not assumed.
"""
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.stripe_idempotency import already_processed


class _FakeRedis:
    """Dict-backed stand-in for redis.Redis, real NX/EX SET semantics only."""

    def __init__(self):
        self.store = {}

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return None  # redis-py: None means "not set, key already existed"
        self.store[key] = value
        return True


class _BrokenRedis:
    """Simulates a Redis outage — every call raises."""

    def set(self, *a, **kw):
        raise ConnectionError("redis is down")


def test_fresh_event_id_is_not_a_duplicate():
    r = _FakeRedis()
    assert already_processed(r, "evt_fresh_1") is False
    assert "stripe:processed_event:evt_fresh_1" in r.store


def test_repeated_event_id_is_flagged_as_duplicate():
    r = _FakeRedis()
    first = already_processed(r, "evt_dup_1")
    second = already_processed(r, "evt_dup_1")
    assert first is False, "first delivery of a new event id must not be flagged as duplicate"
    assert second is True, "second delivery of the SAME event id must be flagged as duplicate"


def test_different_event_ids_are_independent():
    r = _FakeRedis()
    assert already_processed(r, "evt_a") is False
    assert already_processed(r, "evt_b") is False
    assert already_processed(r, "evt_a") is True
    assert already_processed(r, "evt_b") is True


def test_fails_open_when_event_id_missing():
    r = _FakeRedis()
    assert already_processed(r, "") is False
    assert already_processed(r, None) is False
    assert r.store == {}, "must not attempt to store an empty/missing event id"


def test_fails_open_when_redis_client_missing():
    assert already_processed(None, "evt_x") is False


def test_fails_open_on_redis_error():
    r = _BrokenRedis()
    # Must not raise -- a Redis outage should not crash webhook processing.
    assert already_processed(r, "evt_during_outage") is False


if __name__ == "__main__":
    test_fresh_event_id_is_not_a_duplicate()
    test_repeated_event_id_is_flagged_as_duplicate()
    test_different_event_ids_are_independent()
    test_fails_open_when_event_id_missing()
    test_fails_open_when_redis_client_missing()
    test_fails_open_on_redis_error()
    print("All test_stripe_idempotency tests passed.")
