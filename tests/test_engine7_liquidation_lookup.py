"""
Regression test for the dead APEX emergency-liquidation bug (2026-07-19).

core/engine7_parabolic.py's PARABOLIC_EXHAUSTION_EXIT liquidation path used
`if symbol in active_trades` where active_trades is a List[Dict] returned by
execution_engine.ExecutionEngine.get_active_trades() — a string can never
equal a dict, so that condition was always False and the emergency
liquidation SELL never actually fired for any parabolic-exhaustion signal
ever detected, in any live account state.

This proves the extracted _find_open_long() helper actually finds the real
open long, and that the old buggy check would never have.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.engine7_parabolic import _find_open_long  # noqa: E402


def test_old_buggy_check_was_always_false():
    active_trades = [
        {"id": "LIVE_GME_1", "symbol": "GME", "side": "BUY", "status": "OPEN", "qty": 5},
    ]
    # This is exactly the condition that shipped: `if symbol in active_trades`
    # where active_trades is the List[Dict] above.
    assert ("GME" in active_trades) is False, (
        "This is the exact bug: a string is never a member of a list of dicts, "
        "so the liquidation branch could never execute."
    )
    print("PASS: confirmed the old check was structurally always False")


def test_find_open_long_matches_real_open_position():
    active_trades = [
        {"id": "LIVE_GME_1", "symbol": "GME", "side": "BUY", "status": "OPEN", "qty": 5},
        {"id": "LIVE_AMC_1", "symbol": "AMC", "side": "BUY", "status": "OPEN", "qty": 3},
    ]
    trade = _find_open_long(active_trades, "GME")
    assert trade is not None
    assert trade["id"] == "LIVE_GME_1"
    assert trade["qty"] == 5
    print("PASS: _find_open_long finds the real open BUY position")


def test_find_open_long_ignores_closed_and_phantom_short_entries():
    active_trades = [
        {"id": "LIVE_GME_1", "symbol": "GME", "side": "BUY", "status": "CLOSED", "qty": 5},
        {"id": "LIVE_GME_2", "symbol": "GME", "side": "SELL", "status": "OPEN", "qty": 5},  # phantom short
        {"id": "LIVE_GME_3", "symbol": "GME", "side": "BUY", "status": "OPEN", "qty": 0},   # zero qty
    ]
    assert _find_open_long(active_trades, "GME") is None
    print("PASS: _find_open_long correctly ignores closed, short-side, and zero-qty entries")


def test_find_open_long_returns_none_when_no_position():
    assert _find_open_long([], "GME") is None
    assert _find_open_long([{"symbol": "AMC", "side": "BUY", "status": "OPEN", "qty": 1}], "GME") is None
    print("PASS: _find_open_long returns None when there's nothing to liquidate")


if __name__ == "__main__":
    test_old_buggy_check_was_always_false()
    test_find_open_long_matches_real_open_position()
    test_find_open_long_ignores_closed_and_phantom_short_entries()
    test_find_open_long_returns_none_when_no_position()
    print("\nAll regression tests passed.")
