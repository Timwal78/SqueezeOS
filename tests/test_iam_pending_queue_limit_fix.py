"""
Regression test: core/api/iam_pending_bp.py's `limit` param (2026-08-01 fix)
and tools/robinhood_executor_sml.py's matching `_poll_iam_primary()` request.

Before this fix: the GET /api/webhooks/iam_pending route always popped and
cleared the ENTIRE queue on every read, but the only consumer
(_poll_iam_primary() in tools/robinhood_executor_sml.py) only ever executes
up to MAX_PER_SCAN (was 3, now 10) of the returned signals per 45s poll via
one shared scan_counter. With 7 primary systems (CASCADE/SR-Matrix/Breakout/
MM-V4/Sovereign-Squeeze/Quad-Score/SR-Zone+Pattern) now able to queue
signals in the same window, any signal beyond MAX_PER_SCAN in a single
fetch was silently discarded forever -- not "deferred to next cycle" as the
per-signal log line implied, since the server-side queue backing it had
already been wiped by the act of fetching it.

Fix: an optional `?limit=N` query param on the route (and _pop_all()
directly) that pops only the oldest N fresh signals, FIFO, leaving the
remainder queued in original order for a later poll -- safe within the
existing 10-minute TTL given the 45s poll cadence. Omitted/invalid still
pops everything (prior behavior, unchanged default) so any caller that
predates this fix keeps working exactly as before.

Drives the real, unmodified _pop_all() / Flask route / push_iam_primary_signal
-- no mocking, this is pure in-memory queue logic.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.api.iam_pending_bp import (  # noqa: E402
    _pop_all, _QUEUE, _QUEUE_LOCK, push_iam_primary_signal,
)


def _clear_queue():
    with _QUEUE_LOCK:
        _QUEUE.clear()


def _push_n(n, system="SML_CASCADE"):
    for i in range(n):
        push_iam_primary_signal(f"SYM{i}", "BUY", system, 10.0 + i, 80.0)


def test_pop_all_no_limit_pops_everything_backward_compat():
    """Omitting `limit` must behave exactly like the pre-fix pop-and-clear-all
    -- this is the compatibility guarantee for any caller that predates the
    fix."""
    _clear_queue()
    _push_n(5)
    signals = _pop_all()
    assert len(signals) == 5
    assert _pop_all() == [], "queue must be empty after an unlimited pop"
    print("PASS: _pop_all() with no limit still pops and clears everything")


def test_pop_all_with_limit_leaves_remainder_queued_fifo():
    """The actual bug fix: requesting fewer than what's queued must NOT
    discard the rest -- it must stay queued, in original order, for the
    next call."""
    _clear_queue()
    _push_n(7)  # e.g. 7 primary systems all firing in the same window
    first = _pop_all(limit=3)
    assert [s["symbol"] for s in first] == ["SYM0", "SYM1", "SYM2"]

    remaining_in_queue = _pop_all()  # unlimited: drain what's left
    assert [s["symbol"] for s in remaining_in_queue] == [
        "SYM3", "SYM4", "SYM5", "SYM6",
    ], "the 4 signals beyond the first limit=3 pop must have survived, not been discarded"
    print("PASS: limited pop leaves the remainder queued in FIFO order instead of discarding it")


def test_pop_all_limit_zero_pops_nothing():
    _clear_queue()
    _push_n(3)
    assert _pop_all(limit=0) == []
    assert len(_pop_all()) == 3, "nothing should have been consumed by a limit=0 pop"
    print("PASS: limit=0 pops nothing and leaves the full queue intact")


def test_pop_all_limit_greater_than_queue_pops_everything():
    _clear_queue()
    _push_n(2)
    signals = _pop_all(limit=999)
    assert len(signals) == 2
    assert _pop_all() == []
    print("PASS: a limit larger than the queue still pops (and clears) everything available")


def test_multi_poll_drains_full_queue_without_loss():
    """The real-world scenario this fix targets: more signals arrive in one
    window than a single poll's MAX_PER_SCAN can consume. Polling with a
    fixed limit across several cycles must eventually deliver every signal
    exactly once, never lose any."""
    _clear_queue()
    _push_n(10)
    max_per_scan = 3
    delivered = []
    for _ in range(10):  # far more cycles than needed; loop should drain and then stay empty
        batch = _pop_all(limit=max_per_scan)
        if not batch:
            break
        delivered.extend(s["symbol"] for s in batch)
    assert delivered == [f"SYM{i}" for i in range(10)], f"expected all 10 signals delivered in order, got {delivered}"
    print("PASS: repeated limited polls drain the full queue with zero signal loss")


def test_route_limit_query_param():
    """The Flask route itself must honor ?limit=N."""
    from flask import Flask
    from core.api.iam_pending_bp import iam_pending_bp

    _clear_queue()
    _push_n(5)

    app = Flask(__name__)
    app.register_blueprint(iam_pending_bp, url_prefix="/api/webhooks")
    client = app.test_client()

    resp = client.get("/api/webhooks/iam_pending?limit=2")
    data = resp.get_json()
    assert data["count"] == 2
    assert [s["symbol"] for s in data["signals"]] == ["SYM0", "SYM1"]

    # Remainder must still be queued for the next call.
    resp2 = client.get("/api/webhooks/iam_pending")
    data2 = resp2.get_json()
    assert data2["count"] == 3
    assert [s["symbol"] for s in data2["signals"]] == ["SYM2", "SYM3", "SYM4"]
    print("PASS: GET /api/webhooks/iam_pending?limit=N pops only N, leaves the rest queued")


def test_route_invalid_or_missing_limit_falls_back_to_pop_all():
    """A malformed ?limit= (or omitting it) must not error -- it must fall
    back to the pre-fix pop-everything behavior."""
    from flask import Flask
    from core.api.iam_pending_bp import iam_pending_bp

    _clear_queue()
    _push_n(4)

    app = Flask(__name__)
    app.register_blueprint(iam_pending_bp, url_prefix="/api/webhooks")
    client = app.test_client()

    resp = client.get("/api/webhooks/iam_pending?limit=notanumber")
    data = resp.get_json()
    assert data["count"] == 4, "an invalid limit must not crash the route or silently drop signals"
    print("PASS: an invalid ?limit= value degrades safely to pop-everything")


def test_ttl_still_expires_signals_left_queued_by_a_limited_pop():
    """A signal that outlives the 10-minute TTL while sitting in the queue
    (because an earlier limited pop left it behind) must still expire --
    the fix must not accidentally grant queued signals immortality."""
    from core.api import iam_pending_bp as mod

    _clear_queue()
    with mod._QUEUE_LOCK:
        mod._QUEUE.append({
            "symbol": "STALE", "action": "BUY", "system": "SML_CASCADE",
            "price": 1.0, "confidence": 80.0, "ts": time.time() - 700,
        })
        mod._QUEUE.append({
            "symbol": "FRESH", "action": "BUY", "system": "SML_CASCADE",
            "price": 1.0, "confidence": 80.0, "ts": time.time(),
        })
    signals = _pop_all(limit=5)
    assert [s["symbol"] for s in signals] == ["FRESH"], "the >10min-old signal must be dropped by TTL regardless of limit"
    print("PASS: TTL expiry still applies to signals held over by a limited pop")


if __name__ == "__main__":
    test_pop_all_no_limit_pops_everything_backward_compat()
    test_pop_all_with_limit_leaves_remainder_queued_fifo()
    test_pop_all_limit_zero_pops_nothing()
    test_pop_all_limit_greater_than_queue_pops_everything()
    test_multi_poll_drains_full_queue_without_loss()
    test_route_limit_query_param()
    test_route_invalid_or_missing_limit_falls_back_to_pop_all()
    test_ttl_still_expires_signals_left_queued_by_a_limited_pop()
    print("\nAll regression tests passed.")
