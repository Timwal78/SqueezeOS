"""
Regression test for squeeze_analyzer.py's dead "Beast Boost" bonus and fake
momentum fields (2026-07-20).

analyze_symbol() used to unpack `_compression_score()`'s return as
`(intensity, momentum_osc, raw_slope)`, but that function only ever returns
a plain float — so `slope` was hardcoded 0.0 and `m_osc` hardcoded 5.0 on
every single call, for every symbol, forever. Concretely:
  - The "Beast Boost" +10 bonus (`if s2 >= 12 and abs(slope) > 0.1 and
    hurst_val > 0.55: raw_total += 10.0`) could never fire, since
    abs(0.0) > 0.1 is always False.
  - The API's `analysis_components.momentum_osc` field and the top-level
    `momentum_slope` field were fabricated constants (5.0 and 0.0
    respectively) presented as if they were live computed signals — the
    kind of thing the repo's own Prime Directive prohibits.

Fixed by removing the dead bonus branch and the two fake fields entirely
(zero behavior change for every real request, since the bonus never fired
and the fields were never real).

This drives the real, unmodified analyze_symbol() end-to-end and proves:
(1) it still runs and returns a valid score, (2) the fake fields are gone,
(3) raw_score is exactly the sum of the 8 real module scores with no
phantom +10, even in a scenario engineered to have hit every Beast Boost
precondition under the old (broken) logic.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from squeeze_analyzer import SqueezeAnalyzer, clamp  # noqa: E402


def _history_in_squeeze_and_trending(n=40):
    """Real-shape OHLCV history: tight range (squeeze) for a while, then a
    steady persistent uptrend — engineered to make s2 (compression) high
    AND hurst_val > 0.55, the two live preconditions Beast Boost needed.
    Under the old code slope was always 0.0 regardless, so this scenario
    used to prove the bonus was dead; now it proves the bonus is just gone."""
    bars = []
    price = 100.0
    for i in range(n):
        if i < 25:
            # Tight consolidation
            o = price
            c = price + (0.05 if i % 2 == 0 else -0.05)
            h = max(o, c) + 0.02
            l = min(o, c) - 0.02
        else:
            # Persistent uptrend
            o = price
            c = price + 0.6
            h = c + 0.05
            l = o - 0.02
        bars.append({"close": c, "high": h, "low": l, "open": o, "volume": 500000})
        price = c
    return bars


def test_analyze_symbol_runs_and_returns_no_fake_momentum_fields():
    analyzer = SqueezeAnalyzer()
    history = _history_in_squeeze_and_trending()
    quote_data = {
        "price": history[-1]["close"], "volume": 800000, "avgVolume": 400000,
        "volRatio": 2.0, "changePct": 1.5,
        "high": history[-1]["high"], "low": history[-1]["low"], "open": history[-1]["open"],
        "source": "test",
    }

    result = analyzer.analyze_symbol("BEAST", quote_data, history)

    assert result is not None
    assert "momentum_slope" not in result, "fake constant momentum_slope field must be removed"
    assert "momentum_osc" not in result["analysis_components"], (
        "fake constant momentum_osc field must be removed from analysis_components"
    )
    print(f"PASS: no fake momentum fields in a real analyze_symbol() response — {result['analysis_components']}")


def test_raw_score_is_exact_sum_of_the_eight_real_modules_no_phantom_bonus():
    analyzer = SqueezeAnalyzer()
    history = _history_in_squeeze_and_trending()
    quote_data = {
        "price": history[-1]["close"], "volume": 800000, "avgVolume": 400000,
        "volRatio": 2.0, "changePct": 1.5,
        "high": history[-1]["high"], "low": history[-1]["low"], "open": history[-1]["open"],
        "source": "test",
    }

    result = analyzer.analyze_symbol("BEAST", quote_data, history)
    comps = result["analysis_components"]
    expected_raw = clamp(sum(comps.values()), 0.0, 100.0)

    assert abs(result["raw_score"] - round(expected_raw, 1)) < 0.05, (
        f"raw_score={result['raw_score']} must equal the sum of the 8 module scores "
        f"({expected_raw}) with no hidden Beast Boost addition"
    )
    print(f"PASS: raw_score={result['raw_score']} exactly matches the sum of real module scores, no phantom bonus")


if __name__ == "__main__":
    test_analyze_symbol_runs_and_returns_no_fake_momentum_fields()
    test_raw_score_is_exact_sum_of_the_eight_real_modules_no_phantom_bonus()
    print("\nAll regression tests passed.")
