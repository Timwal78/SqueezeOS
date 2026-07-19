"""
Regression test for the phantom-position bookkeeping bug (2026-07-19).

execution_engine.py's execute_live_trade() used to record every successful
order — including a SELL that closed an existing long — as a brand-new
"OPEN" active_trades entry with a synthetic SL/TP computed as if a fresh
short had been opened. That fictional position could later "close" on its
own and feed made-up P&L into performance_tracker, while the real BUY
entry's tracking was orphaned in active_trades forever.

This test drives the real, unmodified execute_live_trade() end-to-end
(only the broker HTTP layer and tradier_api helpers are mocked — nothing
about the bookkeeping logic itself) and proves:
  1. A BUY still opens a normal tracked position (unaffected by the fix).
  2. A SELL that closes it removes/closes the tracked entry instead of
     inventing a new open one.
  3. active_trades ends up empty — no phantom short left behind.
  4. A SELL with nothing tracked for that symbol logs a standalone CLOSED
     record instead of an OPEN one.
"""

import os
import sys
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("BEAST_MAX_PRICE", "10000")  # don't hit the safety-limit reject in this test

from execution_engine import ExecutionEngine  # noqa: E402


def _make_engine(tmp_log_path):
    eng = ExecutionEngine(schwab_api=None, rmre_bridge=None)
    eng.trade_log_path = tmp_log_path
    eng.active_trades = {}
    eng._trade_history = []
    eng.day_trades = []
    eng.broker = MagicMock()
    eng.broker.available = True
    return eng


def test_buy_then_close_sell_leaves_no_phantom_position(tmp_path):
    eng = _make_engine(str(tmp_path / "trade_log_buy_close.json"))
    symbol = "TESTXYZ"

    # ── BUY ──
    eng.broker.place_order.return_value = {"status": "success", "order_id": "1001"}
    with patch("tradier_api.poll_order_fill", return_value={"filled": True, "avg_fill_price": 10.00}), \
         patch("tradier_api.get_spread_pct", return_value=None):
        buy_trade = eng.execute_live_trade(symbol, "BUY", 5, 10.00, reason="test-entry")

    assert buy_trade["status"] == "OPEN"
    assert len(eng.active_trades) == 1
    open_id = next(iter(eng.active_trades))
    assert eng.active_trades[open_id]["side"] == "BUY"
    assert eng.active_trades[open_id]["qty"] == 5

    # ── Closing SELL — price moved up to $12, real fill confirmed ──
    eng.broker.place_order.return_value = {"status": "success", "order_id": "1002"}
    with patch("tradier_api.poll_order_fill", return_value={"filled": True, "avg_fill_price": 12.00}), \
         patch("tradier_api.get_position", return_value={"quantity": 5}):
        sell_result = eng.execute_live_trade(symbol, "SELL", 5, 12.00, reason="test-exit")

    # The bug: this used to be a NEW 'OPEN' entry with side='SELL' and a
    # fabricated short SL/TP, sitting alongside the orphaned original BUY.
    assert sell_result["status"] == "CLOSED", sell_result
    assert eng.active_trades == {}, f"phantom position left behind: {eng.active_trades}"
    assert len(eng._trade_history) == 1
    closed = eng._trade_history[0]
    assert closed["symbol"] == symbol
    assert closed["side"] == "BUY"  # the original long, now correctly closed — not a fake short
    assert closed["pnl"] == (12.00 - 10.00) * 5  # real P&L on the real position
    print("PASS: BUY then closing SELL leaves zero phantom positions, correct P&L")


def test_sell_with_no_tracked_position_logs_standalone_closed_record():
    eng = _make_engine("/tmp/_unused_trade_log_standalone.json")
    symbol = "TESTABC"

    eng.broker.place_order.return_value = {"status": "success", "order_id": "2001"}
    with patch("tradier_api.poll_order_fill", return_value={"filled": True, "avg_fill_price": 5.00}), \
         patch("tradier_api.get_position", return_value={"quantity": 3}):
        result = eng.execute_live_trade(symbol, "SELL", 3, 5.00, reason="external-close")

    # Must never be recorded as OPEN — that's exactly the phantom-position bug.
    assert result["status"] == "CLOSED"
    assert eng.active_trades == {}
    print("PASS: untracked SELL is logged as a standalone CLOSED record, never OPEN")


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        class _P:
            def __init__(self, p): self._p = p
            def __truediv__(self, name): return os.path.join(self._p, name)
        test_buy_then_close_sell_leaves_no_phantom_position(_P(d))
    test_sell_with_no_tracked_position_logs_standalone_closed_record()
    print("\nAll regression tests passed.")
