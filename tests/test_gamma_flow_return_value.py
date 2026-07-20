"""
Regression test for the missing-return bug in gamma_flow_engine.py (2026-07-20).

process_ticker() never had a `return` statement on any code path — every
branch was a bare `return` (None) or fell off the end (None). core/oracle_
engine.py's _get_gamma_flow() is the only caller anywhere in the repo that
expects a dict back (`result.get("gamma_flip"/"regime"/"score")`), so
`gflow` was always `{}` in Oracle's composite scoring — the gamma-flip
+15 bonus and the gamma_score*0.30 term (up to 30% of the whole composite)
silently contributed nothing to any BUY/SELL/HOLD/SHIELD directive, ever.

This drives the real, unmodified process_ticker() end-to-end against a
synthetic-but-realistic Schwab-shape option chain (only the external
Polygon/Tradier calls are mocked — the GEX math, Kalman/HJB state, and
signal-dispatch logic all run for real) and proves it now returns a
dict Oracle can actually use.
"""

import asyncio
import os
import sys
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gamma_flow_engine import GammaFlowEngine  # noqa: E402


def _synthetic_chain(spot: float, short_gamma: bool):
    """
    Minimal Schwab-shape chain with real enough fields (gamma, OI, volume,
    IV) for calculate_gex_profile() to build a genuine GEXProfile. Puts
    dominate GEX when short_gamma=True (net negative total_gex), calls
    dominate when False (net positive) — mirrors real dealer positioning,
    not arbitrary test-only fields.
    """
    def contract(oi, gamma, vol=100, iv=32.0, last=1.5):
        return {"openInterest": oi, "gamma": gamma, "totalVolume": vol,
                "volatility": iv, "lastPrice": last}

    strike = round(spot)
    call_oi, put_oi = (500, 3000) if short_gamma else (3000, 500)

    return {
        "callExpDateMap": {
            "2026-08-15:26": {str(strike): [contract(call_oi, 0.05)]},
        },
        "putExpDateMap": {
            "2026-08-15:26": {str(strike): [contract(put_oi, 0.05)]},
        },
    }


def _make_engine(spot: float, short_gamma: bool) -> GammaFlowEngine:
    polygon = MagicMock()
    polygon.get_last_trade.return_value = {"price": spot}
    engine = GammaFlowEngine(polygon=polygon, watchlist=["TESTGEX"])
    engine._get_chain = lambda ticker: _synthetic_chain(spot, short_gamma)
    return engine


def test_process_ticker_returns_a_dict_not_none():
    engine = _make_engine(spot=100.0, short_gamma=True)
    result = asyncio.run(engine.process_ticker("TESTGEX"))

    assert result is not None, "process_ticker() returned None — the exact bug being fixed"
    assert isinstance(result, dict)
    assert set(result.keys()) == {"gamma_flip", "regime", "score"}
    assert isinstance(result["gamma_flip"], bool)
    assert isinstance(result["regime"], str)
    assert 0.0 <= result["score"] <= 100.0
    print(f"PASS: process_ticker() returns a real dict — {result}")


def test_short_gamma_regime_is_labeled_correctly():
    engine = _make_engine(spot=100.0, short_gamma=True)
    result = asyncio.run(engine.process_ticker("TESTGEX"))
    assert result["regime"] == "SHORT_GAMMA", result
    print(f"PASS: short-gamma-dominant chain correctly labeled SHORT_GAMMA (score={result['score']})")


def test_long_gamma_regime_is_labeled_correctly():
    engine = _make_engine(spot=100.0, short_gamma=False)
    result = asyncio.run(engine.process_ticker("TESTGEX"))
    assert result["regime"] == "LONG_GAMMA", result
    print(f"PASS: long-gamma-dominant chain correctly labeled LONG_GAMMA (score={result['score']})")


def test_gamma_flip_detected_across_two_calls_with_opposite_regimes():
    """Same ticker, same engine instance (so gex_cache carries over): first
    call establishes a baseline regime, second call with the opposite
    regime must set gamma_flip=True — this is the exact condition that used
    to fire _signal_gamma_flip() but whose result was previously discarded."""
    polygon = MagicMock()
    polygon.get_last_trade.return_value = {"price": 100.0}
    engine = GammaFlowEngine(polygon=polygon, watchlist=["TESTGEX"])

    engine._get_chain = lambda ticker: _synthetic_chain(100.0, short_gamma=True)
    first = asyncio.run(engine.process_ticker("TESTGEX"))
    assert first["gamma_flip"] is False  # no prior cached profile to flip from

    engine._get_chain = lambda ticker: _synthetic_chain(100.0, short_gamma=False)
    second = asyncio.run(engine.process_ticker("TESTGEX"))
    assert second["gamma_flip"] is True, second
    print("PASS: a real regime change across two calls is correctly reported as gamma_flip=True")


def test_oracle_get_gamma_flow_actually_receives_real_data_now():
    """End-to-end: core/oracle_engine.py's own _get_gamma_flow() must now
    surface real gamma_flip/regime/score instead of always falling through
    to its `if not result: return {}` branch."""
    import core.oracle_engine as oe

    engine = oe.OracleEngine(services={"dm": MagicMock()})

    import gamma_flow_engine as gfe_module
    real_engine = _make_engine(spot=100.0, short_gamma=True)

    class _FakeGFE:
        def __init__(self, polygon, watchlist):
            pass
        async def process_ticker(self, ticker):
            return await real_engine.process_ticker(ticker)

    orig_cls = gfe_module.GammaFlowEngine
    gfe_module.GammaFlowEngine = _FakeGFE
    try:
        result = engine._get_gamma_flow("TESTGEX")
    finally:
        gfe_module.GammaFlowEngine = orig_cls

    assert result != {}, "Oracle's _get_gamma_flow() still falling through to the empty-dict branch"
    assert "gamma_score" in result and "gamma_flip" in result
    print(f"PASS: Oracle's _get_gamma_flow() now receives real data end-to-end — {result}")


if __name__ == "__main__":
    test_process_ticker_returns_a_dict_not_none()
    test_short_gamma_regime_is_labeled_correctly()
    test_long_gamma_regime_is_labeled_correctly()
    test_gamma_flip_detected_across_two_calls_with_opposite_regimes()
    test_oracle_get_gamma_flow_actually_receives_real_data_now()
    print("\nAll regression tests passed.")
