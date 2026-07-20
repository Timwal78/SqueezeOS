"""
Regression test for the dead daily-loss circuit breaker in ceo_trader.py /
execution_engine.py (2026-07-20, found by background audit agent).

CEOTrader.__init__ bolts a `daily_pnl` attribute onto its ExecutionEngine
instance (`if not hasattr(self.exec, "daily_pnl"): self.exec.daily_pnl = 0.0`)
and _check_circuit_breaker() halts the autopilot when it drops below
-(equity * AUTOPILOT_MAX_DAILY_LOSS_PCT). Nothing, anywhere in the codebase,
ever incremented that attribute — execution_engine.py's _close_trade_unsafe()
computes a real, correct `pnl` for every closed trade and forwards it to
performance_tracker, but never touched exec.daily_pnl. The breaker could
therefore never trip regardless of real realized losses.

This drives the real, unmodified ExecutionEngine.execute_trade() ->
close_trade() -> _close_trade_unsafe() path (shadow mode, no live broker) and
CEOTrader._check_circuit_breaker() end-to-end, proving: (1) daily_pnl now
accumulates real realized P&L from real closed trades, (2) the breaker
actually trips on a real loss past threshold, (3) ExecutionEngine used
WITHOUT a CEOTrader attached (no daily_pnl attribute) still closes trades
without crashing — the hasattr guard must not break standalone usage.
"""

import os
import sys
import tempfile
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from execution_engine import ExecutionEngine  # noqa: E402
from core.ceo_trader import CEOTrader  # noqa: E402


def _fresh_engine():
    """Real ExecutionEngine, no broker/rmre/discord — shadow mode only,
    trade log redirected to a scratch file so tests don't write into the repo."""
    engine = ExecutionEngine(schwab_api=None, rmre_bridge=None,
                              performance_tracker=None, discord_alerts=None)
    engine.trade_log_path = tempfile.NamedTemporaryFile(suffix=".json", delete=False).name
    engine.active_trades = {}
    engine._trade_history = []
    return engine


def test_close_trade_without_ceo_trader_attached_does_not_crash():
    """Standalone ExecutionEngine (no daily_pnl attribute) must close trades
    exactly as before this fix — the hasattr guard must not require CEOTrader."""
    engine = _fresh_engine()
    assert not hasattr(engine, "daily_pnl")

    trade = engine.execute_trade("TEST", "BUY", 100, 10.0)
    assert trade["status"] == "OPEN"
    engine.active_trades[trade["id"]]["current_price"] = 9.80

    closed = engine.close_trade(trade["id"])
    assert closed["status"] == "CLOSED"
    assert abs(closed["pnl"] - (-20.0)) < 1e-9
    assert not hasattr(engine, "daily_pnl")
    print("PASS: standalone ExecutionEngine still closes trades correctly with no daily_pnl attribute")


def test_daily_pnl_accumulates_real_realized_loss_from_a_closed_trade():
    engine = _fresh_engine()
    ceo = CEOTrader(execution_engine=engine, oracle_engine=MagicMock())
    assert engine.daily_pnl == 0.0

    # BUY 100 @ $10.00, exit @ $9.80 -> realized pnl = (9.80 - 10.00) * 100 = -$20
    trade = engine.execute_trade("TEST", "BUY", 100, 10.0)
    engine.active_trades[trade["id"]]["current_price"] = 9.80
    engine.close_trade(trade["id"])

    assert abs(engine.daily_pnl - (-20.0)) < 1e-9, engine.daily_pnl
    print(f"PASS: daily_pnl correctly accumulated a real closed-trade loss — daily_pnl={engine.daily_pnl}")


def test_daily_pnl_accumulates_across_multiple_trades_not_overwritten():
    engine = _fresh_engine()
    ceo = CEOTrader(execution_engine=engine, oracle_engine=MagicMock())

    t1 = engine.execute_trade("AAA", "BUY", 100, 10.0)
    engine.active_trades[t1["id"]]["current_price"] = 9.80   # -$20
    engine.close_trade(t1["id"])

    t2 = engine.execute_trade("BBB", "BUY", 50, 20.0)
    engine.active_trades[t2["id"]]["current_price"] = 19.50  # -$25
    engine.close_trade(t2["id"])

    assert abs(engine.daily_pnl - (-45.0)) < 1e-9, engine.daily_pnl
    print(f"PASS: daily_pnl correctly accumulates across multiple closed trades — daily_pnl={engine.daily_pnl}")


def test_circuit_breaker_actually_trips_on_a_real_loss_past_threshold():
    """Fallback equity is AUTOPILOT_MAX_ORDER_VALUE (default $500) when no
    live broker is wired; default AUTOPILOT_MAX_DAILY_LOSS_PCT=0.02 ->
    threshold = -$10. A -$20 realized loss must trip the breaker."""
    os.environ.pop("AUTOPILOT_MAX_ORDER_VALUE", None)
    os.environ.pop("AUTOPILOT_MAX_DAILY_LOSS_PCT", None)

    engine = _fresh_engine()
    ceo = CEOTrader(execution_engine=engine, oracle_engine=MagicMock())
    assert engine.circuit_breaker_tripped is False

    trade = engine.execute_trade("TEST", "BUY", 100, 10.0)
    engine.active_trades[trade["id"]]["current_price"] = 9.80  # -$20, past -$10 threshold
    engine.close_trade(trade["id"])

    ceo._check_circuit_breaker()

    assert engine.circuit_breaker_tripped is True, (
        f"breaker must trip: daily_pnl={engine.daily_pnl} vs threshold -$10"
    )
    print(f"PASS: circuit breaker actually trips on a real realized loss — daily_pnl={engine.daily_pnl}")


def test_circuit_breaker_does_not_trip_on_a_small_loss_under_threshold():
    os.environ.pop("AUTOPILOT_MAX_ORDER_VALUE", None)
    os.environ.pop("AUTOPILOT_MAX_DAILY_LOSS_PCT", None)

    engine = _fresh_engine()
    ceo = CEOTrader(execution_engine=engine, oracle_engine=MagicMock())

    trade = engine.execute_trade("TEST", "BUY", 10, 10.0)
    engine.active_trades[trade["id"]]["current_price"] = 9.95  # -$0.50, well under -$10 threshold
    engine.close_trade(trade["id"])

    ceo._check_circuit_breaker()

    assert engine.circuit_breaker_tripped is False, engine.daily_pnl
    print(f"PASS: circuit breaker correctly stays clear on a small loss under threshold — daily_pnl={engine.daily_pnl}")


if __name__ == "__main__":
    test_close_trade_without_ceo_trader_attached_does_not_crash()
    test_daily_pnl_accumulates_real_realized_loss_from_a_closed_trade()
    test_daily_pnl_accumulates_across_multiple_trades_not_overwritten()
    test_circuit_breaker_actually_trips_on_a_real_loss_past_threshold()
    test_circuit_breaker_does_not_trip_on_a_small_loss_under_threshold()
    print("\nAll regression tests passed.")
