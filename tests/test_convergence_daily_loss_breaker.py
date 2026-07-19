"""
Regression test for the GOD MODE daily-loss circuit breaker (2026-07-19).

Before this, core/api/convergence_bp.py had a master arm switch, PDT shield,
per-symbol cooldown, and cross-engine claim — but nothing capped cumulative
daily realized loss, unlike iam_executor.py's IAM_DAILY_LOSS_LIMIT/
record_fill/breaker_tripped. This is the engine that placed the real GME buy
order visible in production logs, on a small live account, with no circuit
breaker on cumulative losses at all.

Exercises the real, unmodified breaker functions and the real _fire_execution
bull-entry gate — only the external Tradier calls are mocked.
"""

import os
import sys
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["TRADIER_API_KEY"] = "test-key"
os.environ["LIVE_TRADING_ENABLED"] = "true"
os.environ["GOD_MODE_DAILY_LOSS_LIMIT"] = "100"

import core.api.convergence_bp as bp  # noqa: E402


def _reset_breaker():
    with bp._breaker_lock:
        bp._breaker_state.update(date=None, realized_pnl=0.0, tripped=False)


def test_breaker_trips_when_realized_loss_exceeds_limit():
    _reset_breaker()
    assert bp._breaker_tripped() is False

    bp._record_realized_pnl(-40.0)
    assert bp._breaker_tripped() is False, "should not trip below the limit"

    bp._record_realized_pnl(-65.0)  # cumulative -105, limit is -100
    assert bp._breaker_tripped() is True, "should trip once cumulative realized loss exceeds the limit"
    print("PASS: breaker trips once cumulative realized loss crosses GOD_MODE_DAILY_LOSS_LIMIT")


def test_breaker_resets_on_new_day():
    _reset_breaker()
    bp._record_realized_pnl(-150.0)
    assert bp._breaker_tripped() is True

    # Simulate a new trading day
    with bp._breaker_lock:
        bp._breaker_state["date"] = "2020-01-01"
    assert bp._breaker_tripped() is False, "a fresh day must reset the breaker"
    print("PASS: breaker resets on a new trading day")


def test_fire_execution_blocks_new_long_entry_once_tripped():
    _reset_breaker()
    bp._record_realized_pnl(-150.0)  # trip it
    assert bp._breaker_tripped() is True

    symbol = "TESTBRK"
    bp._last_execution.pop(symbol, None)

    result = {
        "sml_matrix": {
            "execute_gate": True, "tier": "GOD_MODE", "god_stacked": 6,
            "bear_execute_gate": False, "bear_tier": "NONE", "bear_god_stacked": 0,
        }
    }

    place_order_mock = MagicMock()
    with patch("tradier_api.get_account_balance", return_value=5000.0), \
         patch("tradier_api.get_quote", return_value={"last": 10.0, "ask": 10.0}), \
         patch("tradier_api.place_equity_order", place_order_mock):
        bp._fire_execution(symbol, result, dm=None)

    place_order_mock.assert_not_called()
    print("PASS: a qualifying GOD MODE bull signal places NO order once the breaker is tripped")


def test_fire_execution_allows_entry_when_not_tripped():
    _reset_breaker()  # realized_pnl = 0, not tripped

    symbol = "TESTOK"
    bp._last_execution.pop(symbol, None)

    result = {
        "sml_matrix": {
            "execute_gate": True, "tier": "GOD_MODE", "god_stacked": 6,
            "bear_execute_gate": False, "bear_tier": "NONE", "bear_god_stacked": 0,
        }
    }

    place_order_mock = MagicMock(return_value={"status": "success", "order_id": "999"})
    with patch("tradier_api.get_account_balance", return_value=5000.0), \
         patch("tradier_api.get_quote", return_value={"last": 10.0, "ask": 10.0}), \
         patch("tradier_api.place_equity_order", place_order_mock):
        bp._fire_execution(symbol, result, dm=None)

    place_order_mock.assert_called_once()
    print("PASS: a qualifying GOD MODE bull signal places a real order when the breaker is not tripped (sanity check)")


if __name__ == "__main__":
    test_breaker_trips_when_realized_loss_exceeds_limit()
    test_breaker_resets_on_new_day()
    test_fire_execution_blocks_new_long_entry_once_tripped()
    test_fire_execution_allows_entry_when_not_tripped()
    print("\nAll regression tests passed.")
