# ARGUS OMEGA // MASTER SPEC

## Mission
Build a production-grade fusion layer that combines four already-existing intelligence systems into one institutional decision-support engine.

The fusion layer must behave like a chief intelligence officer, not a dumb average.

It must:
1. collect subsystem outputs
2. normalize them into a common semantic frame
3. detect alignment or contradiction
4. compute conviction and scenario hierarchy
5. map the result to disciplined action classes
6. issue a final narrative briefing

## Existing systems
### ARGUS
Purpose: live hidden-state intelligence

Expected fields:
- state_score: float 0..100
- bias: one of [bullish, bearish, neutral, fractured, unstable_bullish, unstable_bearish]
- stability: one of [stable, fragile, distorted, breaking]
- event_risk.expansion: float 0..1
- event_risk.reversal: float 0..1
- event_risk.squeeze: float 0..1
- event_risk.trap: float 0..1
- confidence: float 0..1
- trigger_map.confirm_above: optional float
- trigger_map.invalidate_below: optional float

### ECHO FORGE
Purpose: historical analog + recurrence engine

Expected fields:
- similarity_score: float 0..1
- echo_type: string
- continuation_probability: float 0..1
- reversal_probability: float 0..1
- failure_probability: float 0..1
- resolution_window_bars: int
- confidence: float 0..1
- top_matches: list

### LIQUIDITY GHOST
Purpose: liquidity destination / sweep map

Expected fields:
- destination_score: float 0..1
- primary_magnet: optional float
- secondary_magnet: optional float
- sweep_probability_up: float 0..1
- sweep_probability_down: float 0..1
- post_sweep_reversal_probability: float 0..1
- confidence: float 0..1

### FALSE REALITY
Purpose: deception / trap engine

Expected fields:
- truth_score: float 0..1
- deception_score: float 0..1
- breakout_validity: float 0..1
- trap_probability: float 0..1
- failure_warning: bool
- confidence: float 0..1

## Non-negotiable rules
- Do NOT reduce this to buy/sell output
- Do NOT use simple weighted averages without adjudication
- Do NOT ignore deception / contradiction penalties
- Do NOT let a single subsystem dominate without confidence and alignment support
- Do NOT output casual prose
- Do NOT simplify the action model into long/short only

## What makes this fund-grade
- conditional agreement is treated differently from full agreement
- liquidity destination affects execution posture, not just direction
- deception suppresses conviction even during directional alignment
- historical analog strength increases confidence only when similarity and subsystem confidence both hold
- scenario ranking is explicit and probabilistic
- action class is behavior guidance, not a trade signal

## Required endpoint
POST /omega_scan

Input:
{
  "ticker": "AMC",
  "timeframes": ["15m", "1h", "1d"],
  "argus": {...},
  "echo_forge": {...},
  "liquidity_ghost": {...},
  "false_reality": {...}
}

Output:
{
  "ticker": "AMC",
  "omega_score": 87.2,
  "conviction": "high",
  "alignment_state": "directional_alignment_with_execution_conflict",
  "dominant_scenario": "sweep_then_continuation",
  "alternate_scenario": "failed_breakout_trap",
  "risk_state": "elevated_deception",
  "action_class": "watch_for_sweep",
  "time_horizon": "2-5 sessions",
  "composite_briefing": "...",
  "trigger_map": {...},
  "subsystems": {...},
  "scores": {
    "argus_strength": ...,
    "echo_strength": ...,
    "liquidity_strength": ...,
    "truth_adjusted_strength": ...,
    "alignment_strength": ...
  }
}
