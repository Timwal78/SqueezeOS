"""
Regression test: core/api/tradingview_webhook_bp.py's `limit` param
(2026-08-01 fix) -- the exact same bug and fix as
tests/test_iam_pending_queue_limit_fix.py, applied to the OTHER
pop-and-clear signal queue in this codebase.

Before this fix: GET /api/webhooks/tv_pending always popped and cleared
the ENTIRE queue on every read, but the only consumer
(_poll_tv_pending() in tools/robinhood_executor_sml.py) only ever executes
up to MAX_PER_SCAN of the returned signals per 45s poll via one shared
scan_counter. Any Pine-script signal (SML_Sniper, MMLE Beast, etc.) beyond
that cap in a single fetch was silently discarded forever, not deferred to
the next cycle as the executor's log line implied, since the server-side
queue backing it had already been wiped by the act of fetching it.

Fix: an optional `?limit=N` query param on the route (and
_queue_pop_all() directly) that pops only the oldest N fresh signals,
FIFO, leaving the remainder queued in original order for a later poll.
Omitted/invalid still pops everything (prior behavior, unchanged default).

Drives the real, unmodified _queue_pop_all() / Flask route / _queue_push()
-- no mocking, this is pure in-memory queue logic.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.api.tradingview_webhook_bp import (  # noqa: E402
    _queue_pop_all, _TV_QUEUE, _TV_QUEUE_LOCK, _queue_push,
)


def _clear_queue():
    with _TV_QUEUE_LOCK:
        _TV_QUEUE.clear()


def _push_n(n, system="SML_Sniper"):
    for i in range(n):
        _queue_push(f"SYM{i}", "BUY", system, 10.0 + i)


def test_pop_all_no_limit_pops_everything_backward_compat():
    _clear_queue()
    _push_n(5)
    signals = _queue_pop_all()
    assert len(signals) == 5
    assert _queue_pop_all() == [], "queue must be empty after an unlimited pop"
    print("PASS: _queue_pop_all() with no limit still pops and clears everything")


def test_pop_all_with_limit_leaves_remainder_queued_fifo():
    """The actual bug fix: requesting fewer than what's queued must NOT
    discard the rest."""
    _clear_queue()
    _push_n(7)
    first = _queue_pop_all(limit=3)
    assert [s["symbol"] for s in first] == ["SYM0", "SYM1", "SYM2"]

    remaining_in_queue = _queue_pop_all()
    assert [s["symbol"] for s in remaining_in_queue] == [
        "SYM3", "SYM4", "SYM5", "SYM6",
    ], "the 4 signals beyond the first limit=3 pop must have survived, not been discarded"
    print("PASS: limited pop leaves the remainder queued in FIFO order instead of discarding it")


def test_pop_all_limit_zero_pops_nothing():
    _clear_queue()
    _push_n(3)
    assert _queue_pop_all(limit=0) == []
    assert len(_queue_pop_all()) == 3
    print("PASS: limit=0 pops nothing and leaves the full queue intact")


def test_pop_all_limit_greater_than_queue_pops_everything():
    _clear_queue()
    _push_n(2)
    signals = _queue_pop_all(limit=999)
    assert len(signals) == 2
    assert _queue_pop_all() == []
    print("PASS: a limit larger than the queue still pops (and clears) everything available")


def test_multi_poll_drains_full_queue_without_loss():
    _clear_queue()
    _push_n(10)
    max_per_scan = 3
    delivered = []
    for _ in range(10):
        batch = _queue_pop_all(limit=max_per_scan)
        if not batch:
            break
        delivered.extend(s["symbol"] for s in batch)
    assert delivered == [f"SYM{i}" for i in range(10)], f"expected all 10 signals delivered in order, got {delivered}"
    print("PASS: repeated limited polls drain the full queue with zero signal loss")


def test_route_limit_query_param():
    from flask import Flask
    from core.api.tradingview_webhook_bp import tradingview_webhook_bp

    _clear_queue()
    _push_n(5)

    app = Flask(__name__)
    app.register_blueprint(tradingview_webhook_bp, url_prefix="/api/webhooks")
    client = app.test_client()

    resp = client.get("/api/webhooks/tv_pending?limit=2")
    data = resp.get_json()
    assert data["count"] == 2
    assert [s["symbol"] for s in data["signals"]] == ["SYM0", "SYM1"]

    resp2 = client.get("/api/webhooks/tv_pending")
    data2 = resp2.get_json()
    assert data2["count"] == 3
    assert [s["symbol"] for s in data2["signals"]] == ["SYM2", "SYM3", "SYM4"]
    print("PASS: GET /api/webhooks/tv_pending?limit=N pops only N, leaves the rest queued")


def test_route_invalid_or_missing_limit_falls_back_to_pop_all():
    from flask import Flask
    from core.api.tradingview_webhook_bp import tradingview_webhook_bp

    _clear_queue()
    _push_n(4)

    app = Flask(__name__)
    app.register_blueprint(tradingview_webhook_bp, url_prefix="/api/webhooks")
    client = app.test_client()

    resp = client.get("/api/webhooks/tv_pending?limit=notanumber")
    data = resp.get_json()
    assert data["count"] == 4, "an invalid limit must not crash the route or silently drop signals"
    print("PASS: an invalid ?limit= value degrades safely to pop-everything")


def test_ttl_still_expires_signals_left_queued_by_a_limited_pop():
    from core.api import tradingview_webhook_bp as mod

    _clear_queue()
    with mod._TV_QUEUE_LOCK:
        mod._TV_QUEUE.append({
            "symbol": "STALE", "action": "BUY", "system": "SML_Sniper",
            "price": 1.0, "ts": time.time() - 700, "confidence": 80.0,
        })
        mod._TV_QUEUE.append({
            "symbol": "FRESH", "action": "BUY", "system": "SML_Sniper",
            "price": 1.0, "ts": time.time(), "confidence": 80.0,
        })
    signals = _queue_pop_all(limit=5)
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
