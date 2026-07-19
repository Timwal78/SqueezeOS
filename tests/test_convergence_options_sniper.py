"""
Regression test for the live PUT-order symbol bug (2026-07-19).

core/convergence_engine.py's scan_options() used to return the underlying
ticker (e.g. "IWM") in its "symbol" field instead of Tradier's real
OCC-formatted, order-ready contract symbol (e.g. "IWM250720P00293000").
core/api/convergence_bp.py's GOD MODE BEAR execution leg then preferred the
human-readable "description" string over even that wrong "symbol" field,
so every live PUT hedge on a bearish signal was sent to Tradier's
/accounts/{id}/orders as literal text like "IWM Jul 20 2026 $293.00 Put"
and rejected with HTTP 400 "Invalid parameter, symbol: is not valid."

This mocks only the unavoidable external Tradier HTTP calls — every other
line of the real scan_options() implementation runs for real.
"""

import os
import sys
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("TRADIER_API_KEY", "test-key-for-mocked-http")

from core.convergence_engine import scan_options  # noqa: E402


def _fake_tradier_response(url, params=None, **kwargs):
    resp = MagicMock()
    resp.status_code = 200
    if "expirations" in url:
        resp.json.return_value = {"expirations": {"date": ["2026-07-20"]}}
    elif "chains" in url:
        resp.json.return_value = {
            "options": {
                "option": [
                    {
                        "symbol": "IWM250720P00293000",
                        "description": "IWM Jul 20 2026 $293.00 Put",
                        "option_type": "put",
                        "strike": 293.0,
                        "expiration_date": "2026-07-20",
                        "bid": 1.25, "ask": 1.29, "last": 1.27,
                        "volume": 500, "open_interest": 1200,
                        "greeks": {"delta": -0.3949, "gamma": 0.02, "theta": -0.05, "mid_iv": 0.35},
                    }
                ]
            }
        }
    else:
        raise AssertionError(f"unexpected URL in test: {url}")
    return resp


def test_scan_options_returns_real_occ_symbol_not_underlying_or_description():
    with patch("core.convergence_engine.requests.get", side_effect=_fake_tradier_response):
        contract = scan_options("IWM", trade_type="put", current_price=290.0)

    assert "error" not in contract, contract

    # The bug: this used to be "IWM" (the underlying) here.
    assert contract["symbol"] == "IWM250720P00293000", (
        f"Expected the real OCC contract symbol, got {contract['symbol']!r} — "
        "this is the exact regression that broke live PUT orders."
    )
    assert contract["symbol"] != contract.get("underlying")
    assert contract["underlying"] == "IWM"
    assert contract["description"] == "IWM Jul 20 2026 $293.00 Put"
    print("PASS: scan_options() returns the real OCC symbol, not the underlying or description")


def _is_valid_occ_symbol(option_symbol):
    """Mirrors the exact guard added in core/api/convergence_bp.py."""
    return bool(option_symbol) and len(option_symbol) >= 16 and option_symbol[-9] in ("C", "P")


def test_convergence_bp_validation_accepts_real_symbols_and_rejects_the_old_bug():
    # What Tradier actually needs (put, and a call for good measure) — must pass.
    assert _is_valid_occ_symbol("IWM250720P00293000") is True
    assert _is_valid_occ_symbol("AAPL260117C00250000") is True   # 4-char root, still finds C/P correctly
    assert _is_valid_occ_symbol("F260117P00012000") is True      # 1-char root, still finds C/P correctly

    # What the bug actually sent to Tradier — must be rejected before ever
    # reaching place_option_order(), instead of eating a live HTTP 400.
    assert _is_valid_occ_symbol("IWM Jul 20 2026 $293.00 Put") is False  # the description string
    assert _is_valid_occ_symbol("IWM") is False                          # the bare underlying
    assert _is_valid_occ_symbol("") is False
    assert _is_valid_occ_symbol(None) is False
    print("PASS: OCC validation guard accepts real contract symbols and rejects the old buggy inputs")


if __name__ == "__main__":
    test_scan_options_returns_real_occ_symbol_not_underlying_or_description()
    test_convergence_bp_validation_accepts_real_symbols_and_rejects_the_old_bug()
    print("\nAll regression tests passed.")
