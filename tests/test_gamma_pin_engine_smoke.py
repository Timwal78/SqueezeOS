"""
Tests for gamma_flow_engine.find_near_expiry()/detect_pin_risk() — the
synchronous pin-risk restatement gamma_pin_scanner.py depends on. Verifies
it only fires within the same 0-2 DTE + 0.5% max-OI-strike-proximity window
GammaFlowEngine._check_pin_risk() already uses in production, and resolves
a directional sign correctly.

Not a profitability claim — no backtest exists for this constraint (see
gamma_pin_scanner.py's module docstring for why). This proves the
detection math and direction sign are correct, nothing about real returns.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gamma_flow_engine import GEXProfile, find_near_expiry, detect_pin_risk


def _expiry_key(days_out: int) -> str:
    dt = datetime.now() + timedelta(days=days_out)
    return f"{dt.strftime('%Y-%m-%d')}:{days_out}"


def _chain_with_expiry(days_out: int) -> dict:
    return {
        "callExpDateMap": {_expiry_key(days_out): {"450.0": [{"openInterest": 100}]}},
        "putExpDateMap": {},
    }


def _profile(spot: float, max_oi_strike: float) -> GEXProfile:
    return GEXProfile(
        ticker="TEST", spot_price=spot, total_gex=1.0, profile_shape="short_gamma",
        max_oi_strike=max_oi_strike,
    )


def test_find_near_expiry_finds_expiry_within_window():
    # days_out doesn't map 1:1 to computed dte -- dt is parsed as midnight,
    # so (dt - datetime.now()).days floors on time-of-day (inherited as-is
    # from GammaFlowEngine._check_pin_risk()'s identical formula). Assert
    # the window, not a specific value.
    chain = _chain_with_expiry(1)
    near = find_near_expiry(chain)
    assert near is not None
    assert 0 <= near["dte"] <= 2
    print(f"PASS: find_near_expiry finds an expiry within the 0-2 window (dte={near['dte']})")


def test_find_near_expiry_none_outside_window():
    chain = _chain_with_expiry(10)
    assert find_near_expiry(chain) is None
    print("PASS: find_near_expiry returns None for a 10-DTE expiry (outside window)")


def test_find_near_expiry_none_on_malformed_or_empty_chain():
    assert find_near_expiry({}) is None
    assert find_near_expiry({"callExpDateMap": {"not-a-date": {}}, "putExpDateMap": {}}) is None
    print("PASS: find_near_expiry returns None on empty/malformed chain data")


def test_detect_pin_risk_fires_with_buy_direction_when_strike_above_spot():
    chain = _chain_with_expiry(1)
    profile = _profile(spot=449.90, max_oi_strike=450.0)  # strike above spot, within 0.5%
    result = detect_pin_risk(chain, profile)
    assert result is not None
    assert result["direction"] == "BUY", "max_oi_strike above spot must resolve BUY (magnet pulls price up)"
    assert 0 <= result["dte"] <= 2
    print("PASS: detect_pin_risk fires BUY when max-OI strike is above spot within proximity band")


def test_detect_pin_risk_fires_with_sell_direction_when_strike_below_spot():
    chain = _chain_with_expiry(1)
    profile = _profile(spot=450.10, max_oi_strike=450.0)  # strike below spot, within 0.5%
    result = detect_pin_risk(chain, profile)
    assert result is not None
    assert result["direction"] == "SELL", "max_oi_strike below spot must resolve SELL (magnet pulls price down)"
    print("PASS: detect_pin_risk fires SELL when max-OI strike is below spot within proximity band")


def test_detect_pin_risk_none_when_outside_dte_window():
    chain = _chain_with_expiry(10)
    profile = _profile(spot=449.90, max_oi_strike=450.0)
    assert detect_pin_risk(chain, profile) is None
    print("PASS: detect_pin_risk does not fire outside the 0-2 DTE window even with tight proximity")


def test_detect_pin_risk_none_when_outside_proximity_band():
    chain = _chain_with_expiry(1)
    profile = _profile(spot=400.0, max_oi_strike=450.0)  # >12% away, way outside 0.5% band
    assert detect_pin_risk(chain, profile) is None
    print("PASS: detect_pin_risk does not fire when spot is far from the max-OI strike")


def test_detect_pin_risk_none_on_zero_spot():
    chain = _chain_with_expiry(1)
    profile = _profile(spot=0.0, max_oi_strike=450.0)
    assert detect_pin_risk(chain, profile) is None
    print("PASS: detect_pin_risk safely returns None on a zero/invalid spot price")


if __name__ == "__main__":
    test_find_near_expiry_finds_expiry_within_window()
    test_find_near_expiry_none_outside_window()
    test_find_near_expiry_none_on_malformed_or_empty_chain()
    test_detect_pin_risk_fires_with_buy_direction_when_strike_above_spot()
    test_detect_pin_risk_fires_with_sell_direction_when_strike_below_spot()
    test_detect_pin_risk_none_when_outside_dte_window()
    test_detect_pin_risk_none_when_outside_proximity_band()
    test_detect_pin_risk_none_on_zero_spot()
    print("\nAll regression tests passed.")
