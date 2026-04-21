from typing import Set

def determine_action_class(omega_score: float, alignment_state: str, dominant_scenario: str, conviction: str, deception_score: float) -> str:
    """Classifies the market posture based on institutional decision rules."""
    
    # Rule 1 & 2: Lack of signal
    if omega_score < 40 or alignment_state == "low_signal":
        return "observe_only"
        
    # Rule 3: Trap detection
    if dominant_scenario == "failed_breakout_trap":
        return "do_not_chase"
        
    # Rule 4: Execution conflict
    if alignment_state == "directional_alignment_with_execution_conflict":
        return "watch_for_sweep"
        
    # Rule 5: Extreme deception
    if deception_score >= 0.70:
        return "do_not_chase"

    # Rule 6: Ultimate alignment (MUST be checked before general continuation)
    # Previously Rule 8 — was unreachable because Rule 6 caught it first.
    if conviction == "extreme" and deception_score < 0.35 and alignment_state == "full_alignment":
        return "high_conviction_setup"

    # Rule 7: High confidence continuation
    if dominant_scenario == "clean_continuation" and conviction in {"high", "extreme"}:
        return "post_confirmation_candidate"
        
    # Rule 8: Reversal risk
    if dominant_scenario == "reversal_after_failed_expansion":
        return "reduce_risk"
        
    # Default
    return "watch_trigger"
