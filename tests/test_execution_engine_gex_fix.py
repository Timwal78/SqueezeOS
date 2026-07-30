"""
Regression test for the ExecutionEngine.get_gamma_walls() dead-GEX bug
(2026-07-30): it used to try to instantiate BEAST.gex.sml_gex_engine.GEXEngine,
a module that does not exist anywhere in this codebase, so the method always
returned the hardcoded all-zero dict for every symbol, unconditionally.
Fixed to call the real gamma_flow_engine.calculate_gex_profile() (the same
engine already live via Oracle/Gamma Pin/Squeeze Fuel) with a real Tradier
Schwab-shape chain.

Drives the real, unmodified ExecutionEngine.get_gamma_walls(), mocking only
the two true I/O boundaries (tradier_api.get_option_chain_schwab_format,
which needs a live network call, and nothing else -- calculate_gex_profile
is real, unmocked math).
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from execution_engine import ExecutionEngine  # noqa: E402


def _fake_schwab_chain(spot=100.0):
    """A minimal but real-shaped Schwab-format chain with enough OI/gamma to
    produce a non-zero GEX profile via the real calculate_gex_profile()."""
    return {
        "symbol": "TEST",
        "underlyingPrice": spot,
        "callExpDateMap": {
            "2026-08-15:15": {
                "100.0": [{"openInterest": 5000, "gamma": 0.05, "totalVolume": 1200,
                           "volatility": 30.0, "putCall": "CALL"}],
                "105.0": [{"openInterest": 8000, "gamma": 0.04, "totalVolume": 2000,
                           "volatility": 32.0, "putCall": "CALL"}],
            }
        },
        "putExpDateMap": {
            "2026-08-15:15": {
                "95.0": [{"openInterest": 6000, "gamma": 0.045, "totalVolume": 1500,
                          "volatility": 31.0, "putCall": "PUT"}],
            }
        },
    }


def test_gex_no_longer_hardcoded_zero_with_real_chain():
    engine = ExecutionEngine(schwab_api=None, rmre_bridge=None)
    with patch("tradier_api.get_option_chain_schwab_format", return_value=_fake_schwab_chain()):
        result = engine.get_gamma_walls("TEST")

    assert result["regime"] in ("LONG_GAMMA", "SHORT_GAMMA"), result
    assert result["call_wall"] != 0.0 or result["put_wall"] != 0.0, result
    assert result["total_gex"] != 0.0, result
    print(f"PASS: real chain -> real non-zero GEX profile (regime={result['regime']}, "
          f"call_wall={result['call_wall']}, total_gex={result['total_gex']})")


def test_gex_honestly_zero_when_no_chain_available():
    engine = ExecutionEngine(schwab_api=None, rmre_bridge=None)
    with patch("tradier_api.get_option_chain_schwab_format", return_value=None):
        result = engine.get_gamma_walls("NOCHAIN")

    assert result["regime"] == "NEUTRAL"
    assert result["total_gex"] == 0.0
    assert result["call_wall"] == 0.0
    print("PASS: no chain available -> honest zero/NEUTRAL default, not a crash")


def test_gex_cache_reused_within_ttl():
    engine = ExecutionEngine(schwab_api=None, rmre_bridge=None)
    with patch("tradier_api.get_option_chain_schwab_format", return_value=_fake_schwab_chain()) as mock_fetch:
        r1 = engine.get_gamma_walls("TEST")
        r2 = engine.get_gamma_walls("TEST")
    assert r1 == r2
    mock_fetch.assert_called_once()  # second call served from the 300s cache, no re-fetch
    print("PASS: repeat call within TTL reuses cache, doesn't re-fetch")


if __name__ == "__main__":
    test_gex_no_longer_hardcoded_zero_with_real_chain()
    test_gex_honestly_zero_when_no_chain_available()
    test_gex_cache_reused_within_ttl()
    print("\nAll tests passed.")
