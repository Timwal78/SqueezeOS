"""
Tests for the 2026-07-30 operator-directed changes to iam_executor.py:
1. IAM_OPTIONS_SYSTEMS -- per-system override that routes BUY entries to
   calls regardless of the global IAM_INSTRUMENT setting.
2. IAM_MAX_OPEN_CALLS / IAM_MAX_OPEN_PUTS -- real-money account-wide comfort
   cap on concurrently open option positions, enforced via a real Tradier
   get_positions() call (mocked here) and OCC-symbol type classification.

Same convention as tests/test_iam_primary_system_multi.py: real, unmodified
code, only true I/O boundaries (env vars, tradier_api calls) mocked/monkeypatched.
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import iam_executor  # noqa: E402


def test_occ_option_regex_classifies_call_and_put():
    m_call = iam_executor._OCC_OPTION_RE.match("AMC260821C00002000")
    m_put = iam_executor._OCC_OPTION_RE.match("SPY260101P00450000")
    m_equity = iam_executor._OCC_OPTION_RE.match("SPY")
    assert m_call and m_call.group(1) == "C"
    assert m_put and m_put.group(1) == "P"
    assert m_equity is None
    print("PASS: OCC regex classifies call/put and rejects bare equity symbols")


def test_count_open_option_positions_filters_by_type_and_qty():
    fake_positions = [
        {"symbol": "AMC260821C00002000", "quantity": 5.0},
        {"symbol": "SPY260101P00450000", "quantity": 1.0},
        {"symbol": "GME261016C00027000", "quantity": 0.0},   # closed -- must not count
        {"symbol": "AAPL", "quantity": 10.0},                 # equity -- must not count
    ]
    with patch("tradier_api.get_positions", return_value=fake_positions):
        assert iam_executor._count_open_option_positions("call") == 1
        assert iam_executor._count_open_option_positions("put") == 1
    print("PASS: open-option counter filters by type, ignores zero-qty and equity rows")


def test_cap_blocks_new_call_when_at_limit():
    fake_positions = [{"symbol": "AMC260821C00002000", "quantity": 5.0}]
    with patch.dict(os.environ, {"IAM_PAPER_MODE": "false", "IAM_MAX_OPEN_CALLS": "1"}), \
         patch("tradier_api.get_positions", return_value=fake_positions), \
         patch("tradier_api.get_expirations") as mock_exp:
        result = iam_executor._execute_tradier_options("SPY", "BUY", {}, 450.0)
        assert result["status"] == "skipped"
        assert "cap reached" in result["message"]
        mock_exp.assert_not_called()  # must skip BEFORE hitting the expirations/chain/order path
    print("PASS: at-cap BUY is skipped before any chain fetch or order attempt")


def test_cap_allows_when_below_limit():
    with patch.dict(os.environ, {"IAM_PAPER_MODE": "false", "IAM_MAX_OPEN_CALLS": "1"}), \
         patch("tradier_api.get_positions", return_value=[]), \
         patch("tradier_api.get_expirations") as mock_exp:
        mock_exp.return_value = []
        result = iam_executor._execute_tradier_options("SPY", "BUY", {}, 450.0)
        mock_exp.assert_called_once()  # proceeded past the cap check
        assert result["status"] == "error"  # no expirations -- expected given mocked [] return
    print("PASS: below-cap BUY proceeds past the cap check to the real expirations/chain fetch")


def test_cap_disabled_when_zero():
    fake_positions = [{"symbol": "AMC260821C00002000", "quantity": 5.0}]
    with patch.dict(os.environ, {"IAM_PAPER_MODE": "false", "IAM_MAX_OPEN_CALLS": "0"}), \
         patch("tradier_api.get_positions", return_value=fake_positions), \
         patch("tradier_api.get_expirations", return_value=[]) as mock_exp:
        iam_executor._execute_tradier_options("SPY", "BUY", {}, 450.0)
        mock_exp.assert_called_once()  # 0 = uncapped, cap check is skipped entirely
    print("PASS: IAM_MAX_OPEN_CALLS=0 disables the cap")


def test_cap_not_enforced_in_paper_mode():
    fake_positions = [{"symbol": "AMC260821C00002000", "quantity": 5.0}]
    with patch.dict(os.environ, {"IAM_PAPER_MODE": "true", "IAM_MAX_OPEN_CALLS": "1"}), \
         patch("tradier_api.get_positions", return_value=fake_positions) as mock_positions, \
         patch("tradier_api.get_expirations", return_value=[]) as mock_exp:
        iam_executor._execute_tradier_options("SPY", "BUY", {}, 450.0)
        mock_positions.assert_not_called()  # never even checks real positions in paper mode
        mock_exp.assert_called_once()
    print("PASS: paper mode never enforces the real-money cap")


def test_chain_fetch_uses_real_functions_not_nonexistent_get_option_chain():
    """Regression test for the critical pre-existing bug: this code used to
    call tradier.get_option_chain(), which does not exist anywhere in
    tradier_api.py (only get_option_chain_schwab_format and get_chain do) --
    every single options order via this path has been raising AttributeError
    since it was written. Confirms the real get_expirations()/get_chain()
    functions are called and a full order can be placed end-to-end (paper)."""
    fake_expirations = ["2026-08-01", "2026-08-08"]
    fake_contracts = [
        {"symbol": "SPY260801C00450000", "option_type": "call", "strike": 450.0,
         "ask": 2.50, "last": 2.45, "greeks": {"delta": 0.35}},
        {"symbol": "SPY260801C00460000", "option_type": "call", "strike": 460.0,
         "ask": 1.10, "last": 1.05, "greeks": {"delta": 0.15}},
    ]
    with patch.dict(os.environ, {"IAM_PAPER_MODE": "true"}), \
         patch("tradier_api.get_expirations", return_value=fake_expirations) as mock_exp, \
         patch("tradier_api.get_chain", return_value=fake_contracts) as mock_chain:
        result = iam_executor._execute_tradier_options("SPY", "BUY", {}, 450.0)
        mock_exp.assert_called_once_with("SPY")
        mock_chain.assert_called_once()
        assert result["mode"] == "paper"
        assert result["option_symbol"] == "SPY260801C00450000"  # the 0.35-delta contract, inside the 0.32-0.40 bracket
    print("PASS: real get_expirations()/get_chain() are called end-to-end and select the in-bracket contract")


def test_options_systems_override_forces_calls_even_in_equity_mode():
    with patch.dict(os.environ, {"IAM_INSTRUMENT": "equity", "IAM_OPTIONS_SYSTEMS": "SML_SR_MATRIX"}), \
         patch.object(iam_executor, "claim_entry", return_value=True), \
         patch.object(iam_executor, "_execute_tradier_options", return_value={"status": "success"}) as mock_opt, \
         patch.object(iam_executor, "_execute_tradier_equity") as mock_eq:
        resolution = {"system": "SML_SR_MATRIX"}
        iam_executor._execute_tradier("SPY", "BUY", resolution, 450.0)
        mock_opt.assert_called_once()
        mock_eq.assert_not_called()
    print("PASS: IAM_OPTIONS_SYSTEMS routes a listed system to calls even though IAM_INSTRUMENT=equity")


def test_non_listed_system_stays_on_global_equity_setting():
    with patch.dict(os.environ, {"IAM_INSTRUMENT": "equity", "IAM_OPTIONS_SYSTEMS": "SML_SR_MATRIX"}), \
         patch.object(iam_executor, "claim_entry", return_value=True), \
         patch.object(iam_executor, "_execute_tradier_options") as mock_opt, \
         patch.object(iam_executor, "_execute_tradier_equity", return_value={"status": "success"}) as mock_eq:
        resolution = {"system": "SML_CASCADE"}
        iam_executor._execute_tradier("SPY", "BUY", resolution, 450.0)
        mock_eq.assert_called_once()
        mock_opt.assert_not_called()
    print("PASS: a system NOT in IAM_OPTIONS_SYSTEMS still obeys the global IAM_INSTRUMENT=equity setting")


def test_comma_list_instrument_value_does_not_parse_as_options():
    """Regression test documenting the real config bug found live on Render:
    IAM_INSTRUMENT=\"equity,options\" (a comma list) does NOT match the code's
    single-value check (instrument in (\"options\",\"auto\")) -- it silently
    falls through to equity-only routing. IAM_INSTRUMENT must be set to a
    single value (\"options\" or \"auto\"), not a comma list."""
    with patch.dict(os.environ, {"IAM_INSTRUMENT": "equity,options", "IAM_OPTIONS_SYSTEMS": ""}), \
         patch.object(iam_executor, "claim_entry", return_value=True), \
         patch.object(iam_executor, "_execute_tradier_options") as mock_opt, \
         patch.object(iam_executor, "_execute_tradier_equity", return_value={"status": "success"}) as mock_eq:
        resolution = {"system": "SML_CASCADE"}
        iam_executor._execute_tradier("SPY", "BUY", resolution, 450.0)
        mock_eq.assert_called_once()
        mock_opt.assert_not_called()
    print("PASS: confirmed IAM_INSTRUMENT='equity,options' falls through to equity (must be a single value)")


if __name__ == "__main__":
    test_occ_option_regex_classifies_call_and_put()
    test_count_open_option_positions_filters_by_type_and_qty()
    test_cap_blocks_new_call_when_at_limit()
    test_cap_allows_when_below_limit()
    test_cap_disabled_when_zero()
    test_cap_not_enforced_in_paper_mode()
    test_chain_fetch_uses_real_functions_not_nonexistent_get_option_chain()
    test_options_systems_override_forces_calls_even_in_equity_mode()
    test_non_listed_system_stays_on_global_equity_setting()
    test_comma_list_instrument_value_does_not_parse_as_options()
    print("ALL PASS")
