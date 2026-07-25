"""
Tests for the SML Gamma Pin live-execution wiring: gamma_pin_scanner.py's
dedup/dispatch logic and blueprint registration -- the pieces that make the
constraint actually reachable from a live scan pass. Same convention as
tests/test_sr_matrix_scanner_wiring.py/tests/test_breakout_scanner_wiring.py.

Not a profitability claim -- no backtest exists for this constraint (see
gamma_pin_scanner.py's module docstring for why: no historical options-chain
data source is reachable from this codebase). This proves the wiring is
correct and reaches the real executor, nothing about real returns.
"""
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _fake_chain():
    return {
        "underlyingPrice": 449.90,
        "callExpDateMap": {"2026-08-01:1": {"450.0": [{"openInterest": 100}]}},
        "putExpDateMap": {},
    }


def _fake_profile():
    from gamma_flow_engine import GEXProfile
    return GEXProfile(ticker="SPY", spot_price=449.90, total_gex=1.0,
                       profile_shape="short_gamma", max_oi_strike=450.0)


def test_scanner_dedup_prevents_double_firing_the_same_pin_condition():
    """gamma_pin_scanner.scan_once()'s (expiry, strike, direction) dedup key
    must not re-fire the executor for an unchanged pin condition across
    consecutive passes -- same convention as druck_scanner.py/orb_scanner.py's
    _last_fired guard."""
    import gamma_pin_scanner

    fixed_pin = {"expiry": "2026-08-01", "dte": 1, "spot": 449.90,
                 "max_oi_strike": 450.0, "direction": "BUY"}

    with patch("tradier_api.get_option_chain_schwab_format", return_value=_fake_chain()), \
         patch("gamma_flow_engine.calculate_gex_profile", return_value=_fake_profile()), \
         patch("gamma_flow_engine.detect_pin_risk", return_value=fixed_pin), \
         patch("gamma_pin_scanner._symbols", return_value=["SPY"]), \
         patch("iam_executor.execute_async") as mock_exec:
        gamma_pin_scanner._last_fired.clear()
        fired_1 = gamma_pin_scanner.scan_once()
        fired_2 = gamma_pin_scanner.scan_once()

    assert fired_1 == 1, "first pass with a real pin condition must fire exactly once"
    assert fired_2 == 0, "second pass on the SAME expiry/strike/direction must be deduped"
    assert mock_exec.call_count == 1, "executor must only be called once across both passes"
    call_args = mock_exec.call_args
    assert call_args[0][0] == "SPY"
    assert call_args[0][1]["system"] == "SML_GAMMA_PIN"
    assert call_args[0][1]["action"] == "BUY"
    print("PASS: scanner dedups repeat passes and tags the resolution system=SML_GAMMA_PIN correctly")


def test_scanner_skips_honestly_when_no_chain_data():
    """No fabricated chain, no fabricated signal, when Tradier has nothing
    (e.g. TRADIER_API_KEY unset)."""
    import gamma_pin_scanner

    with patch("tradier_api.get_option_chain_schwab_format", return_value=None), \
         patch("gamma_pin_scanner._symbols", return_value=["SPY"]), \
         patch("iam_executor.execute_async") as mock_exec:
        gamma_pin_scanner._last_fired.clear()
        fired = gamma_pin_scanner.scan_once()

    assert fired == 0
    assert mock_exec.call_count == 0
    print("PASS: scanner honestly skips symbols with no real Tradier chain data, never fabricates a signal")


def test_scanner_does_not_fire_when_no_pin_risk_detected():
    """No expiry in the DTE window / no proximity match must never reach the executor."""
    import gamma_pin_scanner

    with patch("tradier_api.get_option_chain_schwab_format", return_value=_fake_chain()), \
         patch("gamma_flow_engine.calculate_gex_profile", return_value=_fake_profile()), \
         patch("gamma_flow_engine.detect_pin_risk", return_value=None), \
         patch("gamma_pin_scanner._symbols", return_value=["SPY"]), \
         patch("iam_executor.execute_async") as mock_exec:
        gamma_pin_scanner._last_fired.clear()
        fired = gamma_pin_scanner.scan_once()

    assert fired == 0
    assert mock_exec.call_count == 0
    print("PASS: scanner does not fire the executor when detect_pin_risk finds no constraint")


def test_scanner_does_not_fire_when_direction_unresolved():
    """A pin condition with no resolvable direction (measure-zero exact-equality
    case) must never reach the executor."""
    import gamma_pin_scanner

    undirected_pin = {"expiry": "2026-08-01", "dte": 1, "spot": 450.0,
                       "max_oi_strike": 450.0, "direction": None}

    with patch("tradier_api.get_option_chain_schwab_format", return_value=_fake_chain()), \
         patch("gamma_flow_engine.calculate_gex_profile", return_value=_fake_profile()), \
         patch("gamma_flow_engine.detect_pin_risk", return_value=undirected_pin), \
         patch("gamma_pin_scanner._symbols", return_value=["SPY"]), \
         patch("iam_executor.execute_async") as mock_exec:
        gamma_pin_scanner._last_fired.clear()
        fired = gamma_pin_scanner.scan_once()

    assert fired == 0
    assert mock_exec.call_count == 0
    print("PASS: scanner does not fire on an undirected pin condition")


def test_blueprint_registers_at_expected_routes():
    from core.app import create_app
    app = create_app()
    rules = {r.rule for r in app.url_map.iter_rules() if "gamma-pin" in r.rule}
    assert "/api/gamma-pin/status" in rules, rules
    assert "/api/gamma-pin/<symbol>" in rules, rules
    print(f"PASS: /api/gamma-pin blueprint registered — {rules}")


if __name__ == "__main__":
    test_scanner_dedup_prevents_double_firing_the_same_pin_condition()
    test_scanner_skips_honestly_when_no_chain_data()
    test_scanner_does_not_fire_when_no_pin_risk_detected()
    test_scanner_does_not_fire_when_direction_unresolved()
    test_blueprint_registers_at_expected_routes()
    print("\nAll regression tests passed.")
