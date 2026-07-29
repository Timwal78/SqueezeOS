"""
Regression test: IAM primary-system signals (CASCADE/SR-Matrix/Breakout/
MM-V4) must reach the Robinhood pending queue (core/api/iam_pending_bp.py)
IN ADDITION to their existing real Tradier order, not instead of it.

Before this change, iam_executor.execute_from_resolution() only ever placed
a real order on Tradier for primary-system signals -- Robinhood only ever
got a Discord alert literally labeled "ALERT ONLY -- execute manually on
Robinhood". Explicit operator decision (2026-07-29): both brokers should
execute the same signal independently on their own accounts (Robinhood
holds the funds and has no PDT rule; doubled exposure across the two
accounts is intended, not a bug).

This drives the real, unmodified execute_from_resolution() and the real,
unmodified iam_pending_bp queue, mocking only the true I/O boundaries
(_execute_tradier, _get_macro_regime, _gate_check, _is_market_hours,
_fire_discord_trade_alert) -- everything else (the primary-system gate,
the queue push/pop, the Flask route) runs for real.
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import iam_executor as execu  # noqa: E402
from core.api.iam_pending_bp import _pop_all, _QUEUE, _QUEUE_LOCK  # noqa: E402


def _clear_queue():
    with _QUEUE_LOCK:
        _QUEUE.clear()


def _patched():
    """Common patch set: pass every gate except the ones under test."""
    return patch.multiple(
        execu,
        _gate_check=lambda *a, **k: None,
        _get_macro_regime=lambda *a, **k: "NEUTRAL",
        _is_market_hours=lambda: True,
        _execute_tradier=lambda *a, **k: {"status": "success", "placed": True, "qty": 1},
        _fire_discord_trade_alert=lambda *a, **k: None,
    )


def test_primary_system_buy_reaches_robinhood_queue_alongside_tradier():
    _clear_queue()
    os.environ["IAM_PRIMARY_SYSTEM"] = "SML_CASCADE"
    os.environ["IAM_PAPER_MODE"] = "false"
    os.environ["IAM_EXECUTION_MODE"] = "both"
    try:
        with _patched():
            execu.execute_from_resolution(
                "NVDA", {"action": "BUY", "system": "SML_CASCADE"},
                "NEAR_TERM", 80.0, price=123.45,
            )
        signals = _pop_all()
        assert len(signals) == 1, f"expected 1 queued signal, got {signals}"
        assert signals[0]["symbol"] == "NVDA"
        assert signals[0]["action"] == "BUY"
        assert signals[0]["system"] == "SML_CASCADE"
        print("PASS: primary-system BUY reaches the Robinhood queue alongside Tradier")
    finally:
        os.environ.pop("IAM_PRIMARY_SYSTEM", None)
        os.environ.pop("IAM_PAPER_MODE", None)
        os.environ.pop("IAM_EXECUTION_MODE", None)


def test_non_primary_system_does_not_reach_robinhood_queue():
    """A system NOT in IAM_PRIMARY_SYSTEM stays alert-only on both brokers --
    the whole point of the primary-system gate."""
    _clear_queue()
    os.environ["IAM_PRIMARY_SYSTEM"] = "SML_CASCADE"
    os.environ["IAM_PAPER_MODE"] = "false"
    os.environ["IAM_EXECUTION_MODE"] = "both"
    try:
        with _patched():
            execu.execute_from_resolution(
                "AMC", {"action": "BUY", "system": "SML_ORB_MM"},
                "NEAR_TERM", 80.0, price=5.0,
            )
        signals = _pop_all()
        assert signals == [], f"expected no queued signal for non-primary system, got {signals}"
        print("PASS: non-primary-system signal does not reach the Robinhood queue")
    finally:
        os.environ.pop("IAM_PRIMARY_SYSTEM", None)
        os.environ.pop("IAM_PAPER_MODE", None)
        os.environ.pop("IAM_EXECUTION_MODE", None)


def test_paper_mode_does_not_push_a_real_robinhood_order():
    """PAPER_MODE=true must never push to the Robinhood queue -- that queue
    always results in a REAL order on the PC executor's end; there is no
    paper simulation on that side."""
    _clear_queue()
    os.environ["IAM_PRIMARY_SYSTEM"] = "SML_CASCADE"
    os.environ["IAM_PAPER_MODE"] = "true"
    os.environ["IAM_EXECUTION_MODE"] = "both"
    try:
        with _patched():
            execu.execute_from_resolution(
                "NVDA", {"action": "BUY", "system": "SML_CASCADE"},
                "NEAR_TERM", 80.0, price=123.45,
            )
        signals = _pop_all()
        assert signals == [], f"expected no queued signal in paper mode, got {signals}"
        print("PASS: paper mode never pushes a real order to the Robinhood queue")
    finally:
        os.environ.pop("IAM_PRIMARY_SYSTEM", None)
        os.environ.pop("IAM_PAPER_MODE", None)
        os.environ.pop("IAM_EXECUTION_MODE", None)


def test_alert_only_mode_does_not_push_to_robinhood_queue():
    """IAM_EXECUTION_MODE=alert means nothing auto-executes anywhere --
    Robinhood stays alert-only, matching the pre-existing Tradier gate."""
    _clear_queue()
    os.environ["IAM_PRIMARY_SYSTEM"] = "SML_CASCADE"
    os.environ["IAM_PAPER_MODE"] = "false"
    os.environ["IAM_EXECUTION_MODE"] = "alert"
    try:
        with _patched():
            execu.execute_from_resolution(
                "NVDA", {"action": "BUY", "system": "SML_CASCADE"},
                "NEAR_TERM", 80.0, price=123.45,
            )
        signals = _pop_all()
        assert signals == [], f"expected no queued signal in alert-only mode, got {signals}"
        print("PASS: alert-only mode does not push to the Robinhood queue")
    finally:
        os.environ.pop("IAM_PRIMARY_SYSTEM", None)
        os.environ.pop("IAM_PAPER_MODE", None)
        os.environ.pop("IAM_EXECUTION_MODE", None)


def test_queue_endpoint_round_trip():
    """The Flask route itself pops and clears exactly like tv_pending.

    Registers the real, unmodified iam_pending_bp blueprint on a bare Flask
    app rather than going through core.app.create_app() -- the full app
    pulls in every other blueprint's dependencies (openai, redis, etc.),
    none of which this route touches."""
    from flask import Flask
    from core.api.iam_pending_bp import iam_pending_bp, push_iam_primary_signal
    _clear_queue()
    push_iam_primary_signal("SPY", "BUY", "SML_BREAKOUT", 550.0, 82.0)

    app = Flask(__name__)
    app.register_blueprint(iam_pending_bp, url_prefix="/api/webhooks")
    client = app.test_client()
    resp = client.get("/api/webhooks/iam_pending")
    data = resp.get_json()
    assert data["count"] == 1
    assert data["signals"][0]["symbol"] == "SPY"

    # Second call must return empty -- queue clears on read
    resp2 = client.get("/api/webhooks/iam_pending")
    assert resp2.get_json()["count"] == 0
    print("PASS: /api/webhooks/iam_pending pops and clears like tv_pending")


if __name__ == "__main__":
    test_primary_system_buy_reaches_robinhood_queue_alongside_tradier()
    test_non_primary_system_does_not_reach_robinhood_queue()
    test_paper_mode_does_not_push_a_real_robinhood_order()
    test_alert_only_mode_does_not_push_to_robinhood_queue()
    test_queue_endpoint_round_trip()
    print("\nAll regression tests passed.")
