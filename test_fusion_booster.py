from omega.fusion_engine import FusionEngine

engine = FusionEngine()

# Test mock payload with sml_squeeze booster
mock_argus = {
    "state_score": 80,
    "bias": "bullish",
    "stability": "stable",
    "event_risk": {"expansion": 0.1, "reversal": 0.1, "squeeze": 0.8, "trap": 0.1},
    "confidence": 0.9,
    "trigger_map": {"confirm_above": 20.0, "invalidate_below": 15.0}
}

mock_echo = {
    "similarity_score": 0.7,
    "echo_type": "recursive_expansion",
    "continuation_probability": 0.8,
    "reversal_probability": 0.1,
    "failure_probability": 0.1,
    "resolution_window_bars": 15,
    "confidence": 0.8,
    "top_matches": []
}

mock_ghost = {
    "destination_score": 0.9,
    "primary_magnet": 22.0,
    "secondary_magnet": 18.0,
    "sweep_probability_up": 0.8,
    "sweep_probability_down": 0.2,
    "post_sweep_reversal_probability": 0.3,
    "confidence": 0.9
}

mock_reality = {
    "truth_score": 0.9,
    "deception_score": 0.1,
    "breakout_validity": 0.9,
    "trap_probability": 0.1,
    "failure_warning": False,
    "confidence": 0.9
}

# 147-day cycle at peak (score 1.0)
mock_sml = {
    "cycle_147_score": 1.0
}

# Run fusion for GME
res = engine.fuse(
    ticker="GME",
    timeframes=["1d"],
    argus=mock_argus,
    echo=mock_echo,
    ghost=mock_ghost,
    reality=mock_reality,
    sml_squeeze=mock_sml
)

print(f"Ticker: {res['ticker']}")
print(f"Omega Score: {res['omega_score']}")
print(f"SML Cycle Booster: {res['boosters']['sml_cycle_booster']}")

# Run fusion for SPY (should have NO booster)
res_spy = engine.fuse(
    ticker="SPY",
    timeframes=["1d"],
    argus=mock_argus,
    echo=mock_echo,
    ghost=mock_ghost,
    reality=mock_reality,
    sml_squeeze=mock_sml
)
print(f"Ticker: {res_spy['ticker']}")
print(f"SML Cycle Booster (SPY): {res_spy['boosters']['sml_cycle_booster']}")
