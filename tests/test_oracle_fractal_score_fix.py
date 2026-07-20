"""
Regression test for the dead fractal_score key in core/oracle_engine.py's
_get_fractal_signal() (2026-07-20, found by background audit agent).

sml_engine.SMLEngine.compute_all() never returns a "fractal_score" key —
_get_fractal_signal() read `result.get("fractal_score", 0)`, which was
therefore always 0, permanently zeroing this term's 30% weight in
OracleEngine.analyze()'s composite score
(`score += fractal.get("fractal_score", 0) * 0.30`) for every symbol, ever.

Same root cause broke the "Harmonic Convergence" override: it compared
`fractal.get("lifecycle")` (an SMLLifecycle enum text value — Dormant/
Early/Building/Triggered/Active/Extended/Exhausting/Invalid) against the
literal string "HARMONIC_CONVERGENCE", which that field can never equal.
The real flag compute_all() computes for this
(`kinetic_matrix.harmonic_convergence`, a genuine bool from stacked-EMA +
compression + MTF-alignment + net-pressure conditions) was never read.

Fixed by reading `confidence` (compute_all()'s real 0-100 composite) as
fractal_score, exposing `harmonic_convergence` as its own real boolean field,
and rewiring the override to check that real flag instead of the dead
string comparison — operator-confirmed 2026-07-20 (it forces score=100/BUY/
ALPHA_EXPANSION, bypassing CEOTrader's regime gates, so it needed an
explicit decision before being un-inerted, not just restoring a dropped
score term).

This drives the real, unmodified _get_fractal_signal() and analyze() against
a realistic mocked sml.compute_all() result — the shape of which mirrors
sml_engine.py's actual return dict.
"""

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.oracle_engine import OracleEngine  # noqa: E402


def _sml_result(confidence=0.0, lifecycle_text="Dormant", harmonic_convergence=False):
    """Mirrors the real shape of sml_engine.SMLEngine.compute_all()'s return dict
    (only the fields _get_fractal_signal() actually reads)."""
    return {
        "confidence": confidence,
        "lifecycle_text": lifecycle_text,
        "kinetic_matrix": {
            "matrix": {}, "highest_stacked_set": 0,
            "harmonic_convergence": harmonic_convergence,
        },
    }


def test_fractal_score_now_reflects_real_confidence_not_always_zero():
    sml = MagicMock()
    sml.compute_all.return_value = _sml_result(confidence=72.5)
    engine = OracleEngine(services={"sml": sml})

    result = engine._get_fractal_signal("GME", price=20.0)

    assert result["fractal_score"] == 72.5, result
    print(f"PASS: fractal_score now reads the real compute_all() confidence — {result['fractal_score']}")


def test_fractal_score_is_zero_only_when_real_confidence_is_zero():
    sml = MagicMock()
    sml.compute_all.return_value = _sml_result(confidence=0.0)
    engine = OracleEngine(services={"sml": sml})

    result = engine._get_fractal_signal("GME", price=20.0)
    assert result["fractal_score"] == 0.0, result
    print("PASS: fractal_score correctly reads 0 when the real engine's confidence is genuinely 0")


def test_harmonic_convergence_flag_reflects_the_real_kinetic_matrix_bool():
    sml = MagicMock()
    sml.compute_all.return_value = _sml_result(harmonic_convergence=True)
    engine = OracleEngine(services={"sml": sml})

    result = engine._get_fractal_signal("GME", price=20.0)
    assert result["harmonic_convergence"] is True, result

    sml.compute_all.return_value = _sml_result(harmonic_convergence=False)
    result2 = engine._get_fractal_signal("GME", price=20.0)
    assert result2["harmonic_convergence"] is False, result2
    print("PASS: harmonic_convergence correctly reflects the real kinetic_matrix flag both ways")


def test_lifecycle_text_can_never_satisfy_the_old_broken_override_condition():
    """Documents the second half of the bug: no matter what compute_all()
    returns, `lifecycle` can never equal "HARMONIC_CONVERGENCE" — it's always
    one of SMLLifecycle's real enum values."""
    for lifecycle_text in ("Dormant", "Early", "Building", "Triggered",
                            "Active", "Extended", "Exhausting", "Invalid"):
        sml = MagicMock()
        sml.compute_all.return_value = _sml_result(lifecycle_text=lifecycle_text)
        engine = OracleEngine(services={"sml": sml})
        result = engine._get_fractal_signal("GME", price=20.0)
        assert result["lifecycle"] != "HARMONIC_CONVERGENCE", result
    print("PASS: confirmed lifecycle can never equal the literal override string, for any real enum value")


def test_composite_score_end_to_end_now_moves_with_real_fractal_confidence():
    """End-to-end through the real analyze() -> _get_fractal_signal() chain
    (only the underlying services are mocked) — the 30%-weighted fractal
    term must now actually move the composite score."""
    def _make_engine(confidence):
        sml = MagicMock()
        sml.compute_all.return_value = _sml_result(confidence=confidence)
        engine = OracleEngine(services={"sml": sml})
        return engine

    common_patches = dict(
        _get_quote=lambda self, *a: {"price": 20.0, "volume": 1_000_000},
        _get_gamma_walls=lambda self, *a: {},
        _get_regime=lambda self, *a: "NEUTRAL",
        _get_mmle_signal=lambda self, *a: {"vpin": 0.1, "axis_collapse": False},
        _get_gamma_flow=lambda self, *a: {"gamma_flip": False, "gamma_score": 0},
        _get_proprietary_ema=lambda self, *a: {},
    )

    engine_low = _make_engine(confidence=0.0)
    with patch.multiple(OracleEngine, **common_patches):
        result_low = engine_low.analyze("TEST_LOW_FRACTAL")

    engine_high = _make_engine(confidence=90.0)
    with patch.multiple(OracleEngine, **common_patches):
        result_high = engine_high.analyze("TEST_HIGH_FRACTAL")

    assert result_high["confidence"] > result_low["confidence"], (
        f"real fractal confidence must move the composite score: "
        f"low={result_low['confidence']} high={result_high['confidence']}"
    )
    # 0.30 * 90 = 27-point swing expected (before the max(0,min(100,...)) clamp)
    assert result_high["confidence"] - result_low["confidence"] >= 20, (
        result_low["confidence"], result_high["confidence"]
    )
    print(f"PASS: composite score now moves with real fractal confidence — "
          f"low={result_low['confidence']} high={result_high['confidence']}")


def _analyze_with_harmonic_convergence(harmonic_convergence: bool, confidence: float = 10.0):
    sml = MagicMock()
    sml.compute_all.return_value = _sml_result(confidence=confidence, harmonic_convergence=harmonic_convergence)
    engine = OracleEngine(services={"sml": sml})

    common_patches = dict(
        _get_quote=lambda self, *a: {"price": 20.0, "volume": 1_000_000},
        _get_gamma_walls=lambda self, *a: {},
        _get_regime=lambda self, *a: "MACRO_COLLAPSE",  # deliberately NOT whitelist-friendly on its own
        _get_mmle_signal=lambda self, *a: {"vpin": 0.1, "axis_collapse": False},
        _get_gamma_flow=lambda self, *a: {"gamma_flip": False, "gamma_score": 0},
        _get_proprietary_ema=lambda self, *a: {},
    )
    with patch.multiple(OracleEngine, **common_patches):
        return engine.analyze("TEST_HARMONIC")


def test_harmonic_convergence_override_now_actually_fires_when_real_flag_is_true():
    result = _analyze_with_harmonic_convergence(harmonic_convergence=True)
    assert result["directive"] == "BUY", result
    assert result["confidence"] == 100, result
    assert result["regime"] == "ALPHA_EXPANSION", result
    assert "HARMONIC CONVERGENCE" in result["reason"], result
    print(f"PASS: Harmonic Convergence override now actually fires on the real flag — {result['directive']} @ {result['confidence']}")


def test_harmonic_convergence_override_stays_inert_when_real_flag_is_false():
    result = _analyze_with_harmonic_convergence(harmonic_convergence=False)
    assert result["confidence"] != 100 or result["directive"] != "BUY", (
        "override must not fire when harmonic_convergence is genuinely False", result
    )
    assert result["regime"] == "MACRO_COLLAPSE", result
    print(f"PASS: override correctly stays inert without the real flag — {result['directive']} @ {result['confidence']}, regime={result['regime']}")


if __name__ == "__main__":
    test_fractal_score_now_reflects_real_confidence_not_always_zero()
    test_fractal_score_is_zero_only_when_real_confidence_is_zero()
    test_harmonic_convergence_flag_reflects_the_real_kinetic_matrix_bool()
    test_lifecycle_text_can_never_satisfy_the_old_broken_override_condition()
    test_composite_score_end_to_end_now_moves_with_real_fractal_confidence()
    test_harmonic_convergence_override_now_actually_fires_when_real_flag_is_true()
    test_harmonic_convergence_override_stays_inert_when_real_flag_is_false()
    print("\nAll regression tests passed.")
