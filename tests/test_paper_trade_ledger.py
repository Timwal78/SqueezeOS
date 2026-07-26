"""
Tests for paper_trade_ledger.py -- the persistent, per-system paper trade
record built per operator request ("all paper trades should be recorded").
Exercises the local-JSON-file fallback path only (no Redis needed in this
sandbox) -- the Redis path uses the exact same call shape, just a different
backend, so correctness here carries over.

Also verifies iam_executor.py's _ledger_buy/_ledger_sell actually call into
this module (with the correct system tag) when PAPER_MODE() is on -- the
whole point of threading `system` through _execute_tradier ->
_close_equity_position/_execute_tradier_equity.
"""
import importlib
import os
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _fresh_ledger(tmp_path):
    """Reload paper_trade_ledger against a throwaway JSON file, with Redis
    disabled, so tests never touch a real Redis instance or a shared file."""
    os.environ["PAPER_LEDGER_JSON_PATH"] = tmp_path
    os.environ.pop("REDIS_URL", None)
    import paper_trade_ledger
    importlib.reload(paper_trade_ledger)
    return paper_trade_ledger


def test_open_then_close_computes_correct_pnl_and_stats():
    with tempfile.TemporaryDirectory() as d:
        pl = _fresh_ledger(os.path.join(d, "ledger.json"))
        pl.record_open("SML_MM_INTEL", "SPY", 10, 100.0)
        pl.record_close("SML_MM_INTEL", "SPY", 10, 105.0)

        summary = pl.get_summary("SML_MM_INTEL")
        assert summary["stats"]["SML_MM_INTEL"]["total_trades"] == 1
        assert summary["stats"]["SML_MM_INTEL"]["wins"] == 1
        assert abs(summary["stats"]["SML_MM_INTEL"]["total_pnl"] - 50.0) < 1e-6
        assert summary["closed_trades"][0]["pnl"] == 50.0
        assert summary["open_positions"] == {}
        print("PASS: open+close computes correct realized P&L and updates per-system stats")


def test_two_systems_trading_same_symbol_stay_separately_attributed():
    """The exact gap this module closes: iam_executor._positions is keyed
    only by symbol, so two engines trading the same symbol merge into one
    untraceable position. This ledger must keep them apart."""
    with tempfile.TemporaryDirectory() as d:
        pl = _fresh_ledger(os.path.join(d, "ledger.json"))
        pl.record_open("SML_CASCADE", "SPY", 10, 100.0)
        pl.record_open("SML_MM_INTEL", "SPY", 5, 200.0)

        cascade_summary = pl.get_summary("SML_CASCADE")
        mm_summary = pl.get_summary("SML_MM_INTEL")

        assert "SML_CASCADE|SPY" in cascade_summary["open_positions"]
        assert "SML_MM_INTEL|SPY" not in cascade_summary["open_positions"]
        assert "SML_MM_INTEL|SPY" in mm_summary["open_positions"]
        assert cascade_summary["open_positions"]["SML_CASCADE|SPY"]["qty"] == 10
        assert mm_summary["open_positions"]["SML_MM_INTEL|SPY"]["qty"] == 5
        print("PASS: two systems trading the same symbol stay separately attributed")


def test_close_clamps_to_available_quantity():
    with tempfile.TemporaryDirectory() as d:
        pl = _fresh_ledger(os.path.join(d, "ledger.json"))
        pl.record_open("SML_BREAKOUT", "IWM", 5, 50.0)
        pl.record_close("SML_BREAKOUT", "IWM", 100, 55.0)  # over-close, should clamp to 5

        summary = pl.get_summary("SML_BREAKOUT")
        assert summary["closed_trades"][0]["qty"] == 5
        assert summary["open_positions"] == {}
        print("PASS: closing more than the open quantity clamps to what's actually open")


def test_close_with_no_open_position_is_a_safe_noop():
    with tempfile.TemporaryDirectory() as d:
        pl = _fresh_ledger(os.path.join(d, "ledger.json"))
        pl.record_close("SML_SR_MATRIX", "GME", 10, 20.0)  # nothing open
        summary = pl.get_summary("SML_SR_MATRIX")
        assert summary["closed_trades"] == []
        print("PASS: closing with no open position is a safe no-op, not an error")


def test_get_summary_reports_local_json_backend_when_redis_unset():
    with tempfile.TemporaryDirectory() as d:
        pl = _fresh_ledger(os.path.join(d, "ledger.json"))
        summary = pl.get_summary()
        assert summary["backend"] == "local_json_no_redis_configured"
        print("PASS: get_summary honestly discloses the local-JSON (non-Redis) backend")


def test_iam_executor_ledger_calls_paper_ledger_with_correct_system_tag():
    """The wiring point: _ledger_buy/_ledger_sell must call
    paper_trade_ledger.record_open/record_close with the resolution's real
    system tag, only while PAPER_MODE() is on."""
    import iam_executor

    with patch("iam_executor.PAPER_MODE", return_value=True), \
         patch("paper_trade_ledger.record_open") as mock_open, \
         patch("paper_trade_ledger.record_close") as mock_close:
        iam_executor._positions.clear()
        iam_executor._ledger_buy("SPY", 10, 100.0, "SML_MM_INTEL")
        mock_open.assert_called_once_with("SML_MM_INTEL", "SPY", 10, 100.0)

        iam_executor._ledger_sell("SPY", 10, 105.0, "SML_MM_INTEL")
        mock_close.assert_called_once_with("SML_MM_INTEL", "SPY", 10, 105.0)
    print("PASS: iam_executor's ledger functions call paper_trade_ledger with the correct system tag")


def test_blueprint_registers_at_expected_routes():
    from core.app import create_app
    app = create_app()
    rules = {r.rule for r in app.url_map.iter_rules() if "paper-trades" in r.rule}
    assert "/api/paper-trades" in rules or "/api/paper-trades/" in rules, rules
    assert "/api/paper-trades/<system>" in rules, rules
    print(f"PASS: /api/paper-trades blueprint registered — {rules}")


def test_iam_executor_ledger_skips_paper_ledger_when_not_paper_mode():
    """Scoped exactly to what was asked -- 'all PAPER trades should be
    recorded' -- so live fills must not also start writing here."""
    import iam_executor

    with patch("iam_executor.PAPER_MODE", return_value=False), \
         patch("paper_trade_ledger.record_open") as mock_open, \
         patch("paper_trade_ledger.record_close") as mock_close:
        iam_executor._positions.clear()
        iam_executor._ledger_buy("SPY", 10, 100.0, "SML_CASCADE")
        iam_executor._ledger_sell("SPY", 10, 105.0, "SML_CASCADE")
        mock_open.assert_not_called()
        mock_close.assert_not_called()
    print("PASS: paper_trade_ledger is not touched for live (non-paper) fills")


if __name__ == "__main__":
    test_open_then_close_computes_correct_pnl_and_stats()
    test_two_systems_trading_same_symbol_stay_separately_attributed()
    test_close_clamps_to_available_quantity()
    test_close_with_no_open_position_is_a_safe_noop()
    test_get_summary_reports_local_json_backend_when_redis_unset()
    test_blueprint_registers_at_expected_routes()
    test_iam_executor_ledger_calls_paper_ledger_with_correct_system_tag()
    test_iam_executor_ledger_skips_paper_ledger_when_not_paper_mode()
    print("\nAll regression tests passed.")
