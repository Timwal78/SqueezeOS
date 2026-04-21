import pytest
from omega.fusion_engine import FusionEngine

@pytest.fixture
def engine():
    return FusionEngine()

@pytest.fixture
def sample_input():
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
                "trap": 0.58
            },
            "confidence": 0.81,
            "trigger_map": {
                "confirm_above": 3.42,
                "invalidate_below": 2.91
            }
        },
        "echo_forge": {
            "similarity_score": 0.83,
            "echo_type": "late_stage_compression",
            "continuation_probability": 0.68,
            "reversal_probability": 0.22,
            "failure_probability": 0.10,
            "resolution_window_bars": 20,
            "confidence": 0.78,
            "top_matches": [
                {"ticker": "TSLA", "date": "2020-08", "similarity": 0.84},
                {"ticker": "SPY", "date": "2018-01", "similarity": 0.81}
            ]
        },
        "liquidity_ghost": {
            "destination_score": 0.79,
            "primary_magnet": 3.42,
            "secondary_magnet": 2.91,
            "sweep_probability_up": 0.71,
            "sweep_probability_down": 0.34,
            "post_sweep_reversal_probability": 0.47,
            "confidence": 0.75
        },
        "false_reality": {
            "truth_score": 0.41,
            "deception_score": 0.72,
            "breakout_validity": 0.36,
            "trap_probability": 0.69,
            "failure_warning": True,
            "confidence": 0.84
        }
    }

def test_full_fusion_flow(engine, sample_input):
    result = engine.fuse(
        ticker=sample_input["ticker"],
        timeframes=sample_input["timeframes"],
        argus=sample_input["argus"],
        echo=sample_input["echo_forge"],
        ghost=sample_input["liquidity_ghost"],
        reality=sample_input["false_reality"]
    )
    
    assert result["ticker"] == "AMC"
    assert 0 <= result["omega_score"] <= 100
    assert result["conviction"] in ["low", "moderate", "high", "extreme"]
    assert "composite_briefing" in result
    assert result["alignment_state"] == "full_alignment"
    
    # Check probabilities sum to approx 1
    probs = result["scenario_probabilities"]
    assert abs(sum(probs.values()) - 1.0) < 0.001

def test_clamping(engine, sample_input):
    # Pass extreme values
    sample_input["argus"]["state_score"] = 500
    sample_input["argus"]["confidence"] = 5.0
    
    result = engine.fuse(
        ticker=sample_input["ticker"],
        timeframes=sample_input["timeframes"],
        argus=sample_input["argus"],
        echo=sample_input["echo_forge"],
        ghost=sample_input["liquidity_ghost"],
        reality=sample_input["false_reality"]
    )
    
    assert result["omega_score"] <= 100
    assert result["scores"]["argus_strength"] <= 100
