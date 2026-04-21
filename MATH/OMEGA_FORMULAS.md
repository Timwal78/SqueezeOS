# OMEGA Fusion Math

All final values must be clamped to valid ranges.

## Helpers
Let:
- clamp(x, a, b) = min(max(x, a), b)
- N100(x) = clamp(x, 0, 100)
- N1(x) = clamp(x, 0, 1)

## 1. Derived strengths

### 1.1 ARGUS strength
Interpret the live state with stability and bias modifiers.

bias_factor:
- bullish -> 1.00
- unstable_bullish -> 0.95
- bearish -> 1.00
- unstable_bearish -> 0.95
- neutral -> 0.55
- fractured -> 0.45

stability_factor:
- stable -> 1.00
- fragile -> 0.82
- distorted -> 0.70
- breaking -> 0.58

argus_strength =
state_score
* confidence
* bias_factor
* stability_factor
* (0.55 + 0.45 * expansion_signal)

where:
expansion_signal = N1(0.45*expansion + 0.35*squeeze + 0.20*(1-trap))

Final:
argus_strength = N100(argus_strength)

### 1.2 ECHO strength
Historical signal must depend on similarity, confidence, and continuation edge.

continuation_edge = N1(continuation_probability - 0.5*reversal_probability - 0.75*failure_probability)

echo_strength =
100
* similarity_score
* confidence
* (0.35 + 0.65 * continuation_edge)

Final:
echo_strength = N100(echo_strength)

### 1.3 LIQUIDITY strength
Liquidity matters more when directional pull is clear.

directional_clarity = abs(sweep_probability_up - sweep_probability_down)

liquidity_strength =
100
* destination_score
* confidence
* directional_clarity

Final:
liquidity_strength = N100(liquidity_strength)

### 1.4 Truth-adjusted strength
Deception heavily suppresses usable truth.

truth_adjusted_strength =
100
* confidence
* truth_score
* breakout_validity
* (1 - deception_score)
* (1 - 0.50 * trap_probability)

Final:
truth_adjusted_strength = N100(truth_adjusted_strength)

## 2. Direction inference

argus_direction:
- if bias contains bullish -> +1
- if bias contains bearish -> -1
- neutral or fractured -> 0

echo_direction:
- +1 if continuation_probability >= reversal_probability and continuation_probability >= failure_probability
- -1 if reversal_probability > continuation_probability and reversal_probability >= failure_probability
- 0 otherwise

liquidity_direction:
- +1 if sweep_probability_up - sweep_probability_down >= 0.10
- -1 if sweep_probability_down - sweep_probability_up >= 0.10
- 0 otherwise

truth_direction:
- +1 if breakout_validity >= 0.60 and deception_score <= 0.40
- -1 if deception_score >= 0.70 and trap_probability >= 0.55
- 0 otherwise

## 3. Alignment

weighted_votes:
- ARGUS: 0.35
- ECHO: 0.25
- LIQUIDITY: 0.20
- TRUTH: 0.20

bull_weight = sum(weights where direction = +1)
bear_weight = sum(weights where direction = -1)
neutral_weight = remaining weight

alignment_strength_raw = 100 * max(bull_weight, bear_weight)

conflict_gap = abs(bull_weight - bear_weight)

alignment_strength =
alignment_strength_raw * (0.60 + 0.40 * conflict_gap)

Final:
alignment_strength = N100(alignment_strength)

alignment_state:
- full_alignment if max(bull_weight, bear_weight) >= 0.75 and neutral_weight <= 0.10
- directional_alignment_with_execution_conflict if max(bull_weight, bear_weight) >= 0.55 and deception_score >= 0.55
- directional_alignment if max(bull_weight, bear_weight) >= 0.55
- mixed_conflict if conflict_gap < 0.20
- low_signal otherwise

## 4. Penalties and bonuses

deception_penalty =
100 * deception_score * (0.35 + 0.65 * trap_probability)

contradiction_penalty =
100 * (1 - conflict_gap) * 0.25
only apply if both bull_weight > 0 and bear_weight > 0
otherwise 0

alignment_bonus =
0.25 * alignment_strength
only if alignment_state in [full_alignment, directional_alignment]

conditional_bonus =
0.15 * alignment_strength
only if alignment_state == directional_alignment_with_execution_conflict

## 5. Omega score

omega_score_raw =
0.30 * argus_strength
+ 0.25 * echo_strength
+ 0.20 * liquidity_strength
+ 0.15 * truth_adjusted_strength
+ 0.10 * alignment_strength
+ alignment_bonus
+ conditional_bonus
- 0.22 * deception_penalty
- contradiction_penalty

omega_score = N100(omega_score_raw)

## 6. Conviction buckets

conviction_input =
0.45 * (omega_score / 100)
+ 0.25 * (alignment_strength / 100)
+ 0.15 * (1 - deception_score)
+ 0.15 * max(similarity_score * confidence_echo, state_confidence)

conviction bucket:
- low: < 0.40
- moderate: 0.40 to < 0.62
- high: 0.62 to < 0.82
- extreme: >= 0.82

## 7. Scenario ranking

Base scenario logits:

clean_continuation =
0.35*argus_expansion
+ 0.25*echo_continuation
+ 0.20*sweep_up
+ 0.20*truth_score
- 0.30*deception_score

sweep_then_continuation =
0.25*argus_expansion
+ 0.20*echo_continuation
+ 0.35*max(sweep_up, sweep_down)
+ 0.20*post_sweep_reversal_probability
+ 0.10*deception_score

failed_breakout_trap =
0.20*argus_trap
+ 0.15*echo_failure
+ 0.20*deception_score
+ 0.25*(1-breakout_validity)
+ 0.20*trap_probability

reversal_after_failed_expansion =
0.20*argus_reversal
+ 0.20*echo_reversal
+ 0.20*post_sweep_reversal_probability
+ 0.15*deception_score
+ 0.10*argus_trap
+ 0.15*failure_probability

If dominant inferred direction is bearish, swap sweep_up with sweep_down in directional continuation weighting.

Convert scenario logits to probabilities via softmax:
P_i = exp(logit_i) / sum(exp(logit_j))

Dominant scenario = highest probability
Alternate scenario = second highest probability

## 8. Risk state

risk_state:
- elevated_deception if deception_score >= 0.60
- structural_conflict if alignment_state in [mixed_conflict, low_signal]
- trap_risk if dominant_scenario == failed_breakout_trap
- high_quality_alignment if conviction in [high, extreme] and deception_score < 0.45
- balanced_risk otherwise

## 9. Action classes

Rules in order:

1. if omega_score < 40 -> observe_only
2. if alignment_state == low_signal -> observe_only
3. if dominant_scenario == failed_breakout_trap -> do_not_chase
4. if alignment_state == directional_alignment_with_execution_conflict -> watch_for_sweep
5. if deception_score >= 0.70 -> do_not_chase
6. if dominant_scenario == clean_continuation and conviction in [high, extreme] -> post_confirmation_candidate
7. if dominant_scenario == reversal_after_failed_expansion -> reduce_risk
8. if conviction == extreme and deception_score < 0.35 and alignment_state == full_alignment -> high_conviction_setup
9. otherwise -> watch_trigger

## 10. Trigger synthesis

confirm_above:
- prefer ARGUS confirm_above if present
- else LIQUIDITY primary_magnet if directional_up
- else null

invalidate_below:
- prefer ARGUS invalidate_below if present
- else LIQUIDITY secondary_magnet if present
- else null

sweep_target:
- if action_class == watch_for_sweep use primary_magnet
- else null

trap_trigger:
- if deception_score >= 0.55 and confirm_above exists:
  "breakout_above_{confirm_above}_without_breakout_validity"
- else null

confirmation_mode:
- if action_class == watch_for_sweep -> "accept_breakout_only_after_sweep_and_hold"
- elif action_class == post_confirmation_candidate -> "accept_breakout_on_confirmed_hold"
- elif action_class == do_not_chase -> "avoid_first_impulse_participation"
- else "wait_for_alignment"

## 11. Time horizon

Based on resolution_window_bars:
- <= 8 -> "1-2 sessions"
- <= 20 -> "2-5 sessions"
- <= 40 -> "1-2 weeks"
- else -> "multi-week"
