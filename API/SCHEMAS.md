# Schemas

## Request
```json
{
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
    "failure_warning": true,
    "confidence": 0.84
  }
}
```

## Response
```json
{
  "ticker": "AMC",
  "omega_score": 74.9,
  "conviction": "moderate",
  "alignment_state": "directional_alignment_with_execution_conflict",
  "dominant_scenario": "sweep_then_continuation",
  "alternate_scenario": "failed_breakout_trap",
  "risk_state": "elevated_deception",
  "action_class": "watch_for_sweep",
  "time_horizon": "2-5 sessions",
  "composite_briefing": "Bullish pressure is rising, but the structure remains distorted. Historical analogs favor expansion, while liquidity mapping suggests an initial overhead sweep before durable resolution. Deception remains elevated, so breakout chase quality is poor until sweep-and-hold confirmation appears.",
  "trigger_map": {
    "confirm_above": 3.42,
    "invalidate_below": 2.91,
    "sweep_target": 3.42,
    "trap_trigger": "breakout_above_3.42_without_breakout_validity",
    "confirmation_mode": "accept_breakout_only_after_sweep_and_hold"
  },
  "scores": {
    "argus_strength": 74.41,
    "echo_strength": 44.05,
    "liquidity_strength": 21.91,
    "truth_adjusted_strength": 11.48,
    "alignment_strength": 55.0
  },
  "subsystems": {
    "argus": {...},
    "echo_forge": {...},
    "liquidity_ghost": {...},
    "false_reality": {...}
  },
  "scenario_probabilities": {
    "clean_continuation": 0.211,
    "sweep_then_continuation": 0.36,
    "failed_breakout_trap": 0.289,
    "reversal_after_failed_expansion": 0.14
  }
}
```
