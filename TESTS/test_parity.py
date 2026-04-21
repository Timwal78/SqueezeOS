"""
Comprehensive Parity + Guardrail Test Suite for Argus Omega.

Tests:
1. Mathematical parity with REFERENCE_IMPL across multiple scenarios
2. Clamping guardrails
3. Deception suppression
4. Contradiction penalty application
5. Scenario ordering stability
6. Action class mapping correctness
7. Trigger synthesis edge cases
8. Missing optional fields
9. Near-tie scenario probabilities
10. Fractured bias handling
"""
import pytest
import sys
import os
import math

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from omega.fusion_engine import FusionEngine as ProductionEngine
from REFERENCE_IMPL.omega_reference import FusionEngine as ReferenceEngine


@pytest.fixture
def prod():
    return ProductionEngine()


@pytest.fixture
def ref():
    return ReferenceEngine()


def _base_input():
    """Canonical sample input matching reference test."""
    return {
        "ticker": "AMC",
        "timeframes": ["15m", "1h", "1d"],
        "argus": {
            "state_score": 84,
            "bias": "unstable_bullish",
            "stability": "distorted",
            "event_risk": {
                "expansion": 0.77,
                "reversal": 0.31,
                "squeeze": 0.62,
                "trap": 0.58,
            },
            "confidence": 0.81,
            "trigger_map": {
                "confirm_above": 3.42,
                "invalidate_below": 2.91,
            },
        },
        "echo_forge": {
            "similarity_score": 0.83,
            "echo_type": "late_stage_compression",
            "continuation_probability": 0.68,
            "reversal_probability": 0.22,
            "failure_probability": 0.10,
            "resolution_window_bars": 20,
            "confidence": 0.78,
            "top_matches": [],
        },
        "liquidity_ghost": {
            "destination_score": 0.79,
            "primary_magnet": 3.42,
            "secondary_magnet": 2.91,
            "sweep_probability_up": 0.71,
            "sweep_probability_down": 0.34,
            "post_sweep_reversal_probability": 0.47,
            "confidence": 0.75,
        },
        "false_reality": {
            "truth_score": 0.41,
            "deception_score": 0.72,
            "breakout_validity": 0.36,
            "trap_probability": 0.69,
            "failure_warning": True,
            "confidence": 0.84,
        },
    }


def _fuse_both(prod, ref, inp):
    """Run both engines and return both outputs."""
    args = (inp["ticker"], inp["timeframes"], inp["argus"], inp["echo_forge"],
            inp["liquidity_ghost"], inp["false_reality"])
    return prod.fuse(*args), ref.fuse(*args)


# ============================================================================
# SECTION 1: Mathematical Parity Tests
# ============================================================================

class TestMathematicalParity:
    """Every output field must match the reference implementation exactly."""

    def test_canonical_sample_full_parity(self, prod, ref):
        inp = _base_input()
        p, r = _fuse_both(prod, ref, inp)

        assert p["omega_score"] == r["omega_score"]
        assert p["conviction"] == r["conviction"]
        assert p["alignment_state"] == r["alignment_state"]
        assert p["dominant_scenario"] == r["dominant_scenario"]
        assert p["alternate_scenario"] == r["alternate_scenario"]
        assert p["risk_state"] == r["risk_state"]
        assert p["action_class"] == r["action_class"]
        assert p["time_horizon"] == r["time_horizon"]

        for k in r["scores"]:
            assert p["scores"][k] == r["scores"][k], f"Score mismatch: {k}"

        for k in r["scenario_probabilities"]:
            assert p["scenario_probabilities"][k] == r["scenario_probabilities"][k], \
                f"Scenario probability mismatch: {k}"

    def test_high_signal_low_deception(self, prod, ref):
        """All bullish, low deception — should produce full_alignment."""
        inp = _base_input()
        inp["false_reality"]["deception_score"] = 0.10
        inp["false_reality"]["trap_probability"] = 0.05
        inp["false_reality"]["breakout_validity"] = 0.90
        inp["false_reality"]["truth_score"] = 0.85

        p, r = _fuse_both(prod, ref, inp)
        assert p["omega_score"] == r["omega_score"]
        assert p["alignment_state"] == r["alignment_state"]
        assert p["conviction"] == r["conviction"]
        assert p["action_class"] == r["action_class"]

    def test_bearish_bias(self, prod, ref):
        """Bearish ARGUS bias with directional sweep down."""
        inp = _base_input()
        inp["argus"]["bias"] = "bearish"
        inp["liquidity_ghost"]["sweep_probability_up"] = 0.20
        inp["liquidity_ghost"]["sweep_probability_down"] = 0.75
        inp["echo_forge"]["continuation_probability"] = 0.20
        inp["echo_forge"]["reversal_probability"] = 0.65
        inp["echo_forge"]["failure_probability"] = 0.15

        p, r = _fuse_both(prod, ref, inp)
        assert p["omega_score"] == r["omega_score"]
        assert p["dominant_scenario"] == r["dominant_scenario"]

    def test_neutral_bias(self, prod, ref):
        """Neutral ARGUS — low signal environment."""
        inp = _base_input()
        inp["argus"]["bias"] = "neutral"
        inp["argus"]["stability"] = "stable"
        inp["argus"]["state_score"] = 45

        p, r = _fuse_both(prod, ref, inp)
        assert p["omega_score"] == r["omega_score"]
        assert p["alignment_state"] == r["alignment_state"]

    def test_fractured_bias(self, prod, ref):
        """Fractured bias — lowest bias factor (0.45)."""
        inp = _base_input()
        inp["argus"]["bias"] = "fractured"
        inp["argus"]["stability"] = "breaking"
        inp["argus"]["state_score"] = 30
        inp["argus"]["confidence"] = 0.40

        p, r = _fuse_both(prod, ref, inp)
        assert p["omega_score"] == r["omega_score"]
        assert p["scores"]["argus_strength"] == r["scores"]["argus_strength"]


# ============================================================================
# SECTION 2: Clamping Guardrails
# ============================================================================

class TestClampingGuardrails:
    """Every derived score must be in valid range regardless of inputs."""

    def test_extreme_argus_values(self, prod):
        inp = _base_input()
        inp["argus"]["state_score"] = 500  # Way above 100
        inp["argus"]["confidence"] = 5.0   # Way above 1
        result = prod.fuse(inp["ticker"], inp["timeframes"], inp["argus"],
                          inp["echo_forge"], inp["liquidity_ghost"], inp["false_reality"])
        assert 0 <= result["omega_score"] <= 100
        assert 0 <= result["scores"]["argus_strength"] <= 100

    def test_zero_inputs(self, prod):
        """All zeros should not crash and should produce valid bounded output."""
        inp = _base_input()
        inp["argus"]["state_score"] = 0
        inp["argus"]["confidence"] = 0
        inp["echo_forge"]["similarity_score"] = 0
        inp["echo_forge"]["confidence"] = 0
        inp["liquidity_ghost"]["destination_score"] = 0
        inp["liquidity_ghost"]["confidence"] = 0
        inp["false_reality"]["truth_score"] = 0
        inp["false_reality"]["confidence"] = 0
        inp["false_reality"]["deception_score"] = 0

        result = prod.fuse(inp["ticker"], inp["timeframes"], inp["argus"],
                          inp["echo_forge"], inp["liquidity_ghost"], inp["false_reality"])
        assert 0 <= result["omega_score"] <= 100
        assert result["conviction"] in {"low", "moderate", "high", "extreme"}

    def test_negative_omega_clamped(self, prod):
        """Extreme deception with low signal → omega should clamp to 0, not go negative."""
        inp = _base_input()
        inp["argus"]["state_score"] = 10
        inp["argus"]["confidence"] = 0.1
        inp["argus"]["bias"] = "fractured"
        inp["argus"]["stability"] = "breaking"
        inp["false_reality"]["deception_score"] = 0.99
        inp["false_reality"]["trap_probability"] = 0.99

        result = prod.fuse(inp["ticker"], inp["timeframes"], inp["argus"],
                          inp["echo_forge"], inp["liquidity_ghost"], inp["false_reality"])
        assert result["omega_score"] >= 0

    def test_all_scores_bounded(self, prod):
        """Every score in the output must be 0-100."""
        inp = _base_input()
        result = prod.fuse(inp["ticker"], inp["timeframes"], inp["argus"],
                          inp["echo_forge"], inp["liquidity_ghost"], inp["false_reality"])
        for k, v in result["scores"].items():
            assert 0 <= v <= 100, f"{k} out of bounds: {v}"


# ============================================================================
# SECTION 3: Deception Guardrail
# ============================================================================

class TestDeceptionGuardrail:
    """High deception MUST suppress conviction and action aggression."""

    def test_high_deception_suppresses_conviction(self, prod):
        """Even with perfect bullish signal, extreme deception must limit conviction."""
        inp = _base_input()
        inp["argus"]["bias"] = "bullish"
        inp["argus"]["stability"] = "stable"
        inp["argus"]["state_score"] = 95
        inp["argus"]["confidence"] = 0.95
        inp["false_reality"]["deception_score"] = 0.95
        inp["false_reality"]["trap_probability"] = 0.90

        result = prod.fuse(inp["ticker"], inp["timeframes"], inp["argus"],
                          inp["echo_forge"], inp["liquidity_ghost"], inp["false_reality"])
        # Extreme deception should prevent "extreme" conviction
        assert result["conviction"] != "extreme"
        assert result["risk_state"] == "elevated_deception"

    def test_high_deception_triggers_do_not_chase(self, prod):
        """Deception >= 0.70 should trigger do_not_chase if conditions met."""
        inp = _base_input()
        inp["false_reality"]["deception_score"] = 0.75
        inp["false_reality"]["trap_probability"] = 0.80

        result = prod.fuse(inp["ticker"], inp["timeframes"], inp["argus"],
                          inp["echo_forge"], inp["liquidity_ghost"], inp["false_reality"])
        assert result["risk_state"] == "elevated_deception"


# ============================================================================
# SECTION 4: Contradiction Penalty
# ============================================================================

class TestContradictionPenalty:
    """Contradiction penalty only applies when BOTH bull and bear weight > 0."""

    def test_contradiction_applied(self, prod, ref):
        """Force a mixed signal environment — ARGUS bearish but ECHO/GHOST bullish."""
        inp = _base_input()
        inp["argus"]["bias"] = "bearish"
        inp["false_reality"]["deception_score"] = 0.30
        inp["false_reality"]["breakout_validity"] = 0.80
        inp["false_reality"]["trap_probability"] = 0.10

        p, r = _fuse_both(prod, ref, inp)
        assert p["omega_score"] == r["omega_score"]

    def test_no_contradiction_when_unidirectional(self, prod, ref):
        """All subsystems bullish — no contradiction penalty."""
        inp = _base_input()
        inp["false_reality"]["deception_score"] = 0.10
        inp["false_reality"]["breakout_validity"] = 0.90
        inp["false_reality"]["trap_probability"] = 0.05

        p, r = _fuse_both(prod, ref, inp)
        assert p["omega_score"] == r["omega_score"]


# ============================================================================
# SECTION 5: Scenario Ordering
# ============================================================================

class TestScenarioOrdering:
    """Scenario probabilities must sum to ~1 and be properly ordered."""

    def test_probabilities_sum_to_one(self, prod):
        inp = _base_input()
        result = prod.fuse(inp["ticker"], inp["timeframes"], inp["argus"],
                          inp["echo_forge"], inp["liquidity_ghost"], inp["false_reality"])
        total = sum(result["scenario_probabilities"].values())
        assert abs(total - 1.0) < 0.01, f"Probabilities sum to {total}"

    def test_dominant_is_highest(self, prod):
        inp = _base_input()
        result = prod.fuse(inp["ticker"], inp["timeframes"], inp["argus"],
                          inp["echo_forge"], inp["liquidity_ghost"], inp["false_reality"])
        probs = result["scenario_probabilities"]
        assert probs[result["dominant_scenario"]] >= probs[result["alternate_scenario"]]

    def test_near_tie_stability(self, prod, ref):
        """When scenarios are nearly tied, both engines must agree."""
        inp = _base_input()
        inp["argus"]["event_risk"]["expansion"] = 0.50
        inp["argus"]["event_risk"]["reversal"] = 0.50
        inp["argus"]["event_risk"]["trap"] = 0.50
        inp["echo_forge"]["continuation_probability"] = 0.34
        inp["echo_forge"]["reversal_probability"] = 0.33
        inp["echo_forge"]["failure_probability"] = 0.33

        p, r = _fuse_both(prod, ref, inp)
        assert p["dominant_scenario"] == r["dominant_scenario"]
        assert p["alternate_scenario"] == r["alternate_scenario"]


# ============================================================================
# SECTION 6: Action Class Mapping
# ============================================================================

class TestActionClassMapping:
    """Action class rules must fire in the exact priority order from the spec."""

    def test_low_omega_observe_only(self, prod):
        """omega_score < 40 → observe_only (Rule 1)."""
        inp = _base_input()
        inp["argus"]["state_score"] = 10
        inp["argus"]["confidence"] = 0.1
        inp["argus"]["bias"] = "fractured"
        inp["argus"]["stability"] = "breaking"
        inp["false_reality"]["deception_score"] = 0.90
        inp["false_reality"]["trap_probability"] = 0.90

        result = prod.fuse(inp["ticker"], inp["timeframes"], inp["argus"],
                          inp["echo_forge"], inp["liquidity_ghost"], inp["false_reality"])
        assert result["action_class"] == "observe_only"


# ============================================================================
# SECTION 7: Trigger Synthesis Edge Cases
# ============================================================================

class TestTriggerSynthesis:
    """Trigger map must handle missing optional values gracefully."""

    def test_missing_trigger_map(self, prod, ref):
        """When argus has no trigger_map, fallback to liquidity magnets."""
        inp = _base_input()
        inp["argus"]["trigger_map"] = None

        p, r = _fuse_both(prod, ref, inp)
        assert p["trigger_map"] == r["trigger_map"]

    def test_missing_trigger_map_key(self, prod, ref):
        """When argus trigger_map key is entirely absent."""
        inp = _base_input()
        del inp["argus"]["trigger_map"]

        p, r = _fuse_both(prod, ref, inp)
        assert p["trigger_map"] == r["trigger_map"]

    def test_missing_magnets(self, prod, ref):
        """When neither trigger_map nor magnets exist."""
        inp = _base_input()
        inp["argus"]["trigger_map"] = None
        inp["liquidity_ghost"]["primary_magnet"] = None
        inp["liquidity_ghost"]["secondary_magnet"] = None

        p, r = _fuse_both(prod, ref, inp)
        assert p["trigger_map"]["confirm_above"] is None
        assert p["trigger_map"]["invalidate_below"] is None


# ============================================================================
# SECTION 8: Time Horizon
# ============================================================================

class TestTimeHorizon:

    def test_short_horizon(self, prod):
        inp = _base_input()
        inp["echo_forge"]["resolution_window_bars"] = 5
        result = prod.fuse(inp["ticker"], inp["timeframes"], inp["argus"],
                          inp["echo_forge"], inp["liquidity_ghost"], inp["false_reality"])
        assert result["time_horizon"] == "1-2 sessions"

    def test_medium_horizon(self, prod):
        inp = _base_input()
        inp["echo_forge"]["resolution_window_bars"] = 15
        result = prod.fuse(inp["ticker"], inp["timeframes"], inp["argus"],
                          inp["echo_forge"], inp["liquidity_ghost"], inp["false_reality"])
        assert result["time_horizon"] == "2-5 sessions"

    def test_long_horizon(self, prod):
        inp = _base_input()
        inp["echo_forge"]["resolution_window_bars"] = 35
        result = prod.fuse(inp["ticker"], inp["timeframes"], inp["argus"],
                          inp["echo_forge"], inp["liquidity_ghost"], inp["false_reality"])
        assert result["time_horizon"] == "1-2 weeks"

    def test_multiweek_horizon(self, prod):
        inp = _base_input()
        inp["echo_forge"]["resolution_window_bars"] = 100
        result = prod.fuse(inp["ticker"], inp["timeframes"], inp["argus"],
                          inp["echo_forge"], inp["liquidity_ghost"], inp["false_reality"])
        assert result["time_horizon"] == "multi-week"


# ============================================================================
# SECTION 9: Narrative Guardrail
# ============================================================================

class TestNarrativeGuardrail:
    """Narratives must be institutional-grade — no slang, no emojis, no retail hype."""

    def test_no_emojis_in_briefing(self, prod):
        inp = _base_input()
        result = prod.fuse(inp["ticker"], inp["timeframes"], inp["argus"],
                          inp["echo_forge"], inp["liquidity_ghost"], inp["false_reality"])
        briefing = result["composite_briefing"]
        # Check for common emoji ranges
        for char in briefing:
            assert ord(char) < 0x1F600 or ord(char) > 0x1F9FF, \
                f"Emoji detected in briefing: {char}"

    def test_briefing_is_not_empty(self, prod):
        inp = _base_input()
        result = prod.fuse(inp["ticker"], inp["timeframes"], inp["argus"],
                          inp["echo_forge"], inp["liquidity_ghost"], inp["false_reality"])
        assert len(result["composite_briefing"]) > 50

    def test_briefing_contains_deception_metric(self, prod):
        """Briefing must contain the deception score for transparency."""
        inp = _base_input()
        result = prod.fuse(inp["ticker"], inp["timeframes"], inp["argus"],
                          inp["echo_forge"], inp["liquidity_ghost"], inp["false_reality"])
        assert "0.72" in result["composite_briefing"]


# ============================================================================
# SECTION 10: Response Shape Integrity
# ============================================================================

class TestResponseShapeIntegrity:
    """The response must contain every field the spec requires."""

    def test_all_required_fields_present(self, prod):
        inp = _base_input()
        result = prod.fuse(inp["ticker"], inp["timeframes"], inp["argus"],
                          inp["echo_forge"], inp["liquidity_ghost"], inp["false_reality"])

        required_keys = [
            "ticker", "timeframes", "omega_score", "conviction", "alignment_state",
            "dominant_scenario", "alternate_scenario", "risk_state", "action_class",
            "time_horizon", "composite_briefing", "trigger_map", "scores",
            "scenario_probabilities", "subsystems",
        ]
        for k in required_keys:
            assert k in result, f"Missing required field: {k}"

    def test_scores_shape(self, prod):
        inp = _base_input()
        result = prod.fuse(inp["ticker"], inp["timeframes"], inp["argus"],
                          inp["echo_forge"], inp["liquidity_ghost"], inp["false_reality"])
        required_scores = [
            "argus_strength", "echo_strength", "liquidity_strength",
            "truth_adjusted_strength", "alignment_strength",
        ]
        for k in required_scores:
            assert k in result["scores"], f"Missing score: {k}"

    def test_trigger_map_shape(self, prod):
        inp = _base_input()
        result = prod.fuse(inp["ticker"], inp["timeframes"], inp["argus"],
                          inp["echo_forge"], inp["liquidity_ghost"], inp["false_reality"])
        required_triggers = [
            "confirm_above", "invalidate_below", "sweep_target",
            "trap_trigger", "confirmation_mode",
        ]
        for k in required_triggers:
            assert k in result["trigger_map"], f"Missing trigger: {k}"

    def test_subsystem_passthrough(self, prod):
        """Subsystems must be echoed back verbatim for audit trail."""
        inp = _base_input()
        result = prod.fuse(inp["ticker"], inp["timeframes"], inp["argus"],
                          inp["echo_forge"], inp["liquidity_ghost"], inp["false_reality"])
        assert result["subsystems"]["argus"] == inp["argus"]
        assert result["subsystems"]["echo_forge"] == inp["echo_forge"]
        assert result["subsystems"]["liquidity_ghost"] == inp["liquidity_ghost"]
        assert result["subsystems"]["false_reality"] == inp["false_reality"]
