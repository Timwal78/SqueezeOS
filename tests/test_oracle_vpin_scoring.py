"""
Regression test for the Oracle VPIN-as-BUY-booster fix (2026-07-20).

VPIN (Volume-Synchronized Probability of Informed Trading) is a pure
order-flow imbalance *magnitude* — mmle_engine.py's VPINEngine computes it
as |buy_volume - sell_volume| / total, with no sign, so it cannot indicate
which side the imbalance is on. core/oracle_engine.py used to add
`vpin * 40` — the single largest weighted term in its composite score —
unconditionally toward a BUY directive, even though heavy VPIN from
informed *selling* is exactly the wrong time to lean bullish. This
contradicted the engine's own SELL/SHIELD gates and the sibling
core/rdt_engine.py, both of which already treat high VPIN as bearish/
risk-off evidence.

This drives the real, unmodified OracleEngine.analyze() end-to-end (only
its per-signal fetch methods are patched, since those hit live services)
and proves high VPIN alone no longer inflates the composite score.
"""

import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.oracle_engine import OracleEngine  # noqa: E402


def _make_engine():
    return OracleEngine(services={})


def _patch_signals(engine, *, vpin, fractal_score=0, gamma_score=0, gamma_flip=False,
                    regime="NEUTRAL", axis_collapse=False):
    return (
        patch.object(engine, "_get_quote", return_value={"price": 20.0, "volume": 1_000_000}),
        patch.object(engine, "_get_gamma_walls", return_value={}),
        patch.object(engine, "_get_regime", return_value=regime),
        patch.object(engine, "_get_fractal_signal", return_value={"fractal_score": fractal_score, "fractal_match": "None", "lifecycle": "DORMANT"}),
        patch.object(engine, "_get_mmle_signal", return_value={"vpin": vpin, "axis_collapse": axis_collapse}),
        patch.object(engine, "_get_gamma_flow", return_value={"gamma_flip": gamma_flip, "gamma_score": gamma_score}),
        patch.object(engine, "_get_proprietary_ema", return_value={}),
    )


def test_high_vpin_alone_no_longer_inflates_score_toward_buy():
    engine = _make_engine()

    patches_low_vpin = _patch_signals(engine, vpin=0.05)
    with patches_low_vpin[0], patches_low_vpin[1], patches_low_vpin[2], patches_low_vpin[3], \
         patches_low_vpin[4], patches_low_vpin[5], patches_low_vpin[6]:
        result_low_vpin = engine.analyze("TEST1")

    engine2 = _make_engine()
    patches_high_vpin = _patch_signals(engine2, vpin=0.95)
    with patches_high_vpin[0], patches_high_vpin[1], patches_high_vpin[2], patches_high_vpin[3], \
         patches_high_vpin[4], patches_high_vpin[5], patches_high_vpin[6]:
        result_high_vpin = engine2.analyze("TEST2")

    # The bug: with the old `score += vpin * 40`, confidence would jump by
    # ~36 points (0.90 * 40) between these two runs with everything else
    # held identical. Now VPIN alone must not move the score at all.
    assert result_low_vpin["confidence"] == result_high_vpin["confidence"], (
        f"VPIN alone changed the composite score: "
        f"low={result_low_vpin['confidence']} high={result_high_vpin['confidence']} "
        f"— it should only affect directive via the SELL/SHIELD gates, not the score."
    )
    print(f"PASS: VPIN 0.05 vs 0.95 produce identical confidence ({result_low_vpin['confidence']}) — no BUY inflation")


def test_sell_gate_still_uses_vpin_under_macro_collapse():
    """
    The existing risk gate this fix was never supposed to touch must still
    work. Needs a non-trivial base score independent of VPIN (e.g. some
    fractal_score) so the composite clears Oracle's separate, pre-existing
    "score < 5 -> SHIELD" floor and the SELL gate actually gets evaluated —
    an all-zero-except-VPIN scenario would hit that floor first regardless
    of this fix, since VPIN no longer props the score up either.
    """
    engine = _make_engine()
    # 0.30 * 80 (fractal weight) - 15 (MACRO_COLLAPSE penalty) = 9, clears the
    # separate score<5 floor while staying well under the BUY thresholds.
    patches = _patch_signals(engine, vpin=0.80, regime="MACRO_COLLAPSE", fractal_score=80)
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
        result = engine.analyze("TEST3")

    assert result["directive"] == "SELL", result
    print("PASS: MACRO_COLLAPSE + high VPIN still correctly triggers SELL via the existing gate")


if __name__ == "__main__":
    test_high_vpin_alone_no_longer_inflates_score_toward_buy()
    test_sell_gate_still_uses_vpin_under_macro_collapse()
    print("\nAll regression tests passed.")
