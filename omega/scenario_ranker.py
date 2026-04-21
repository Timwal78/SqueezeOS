"""
Scenario Ranking Module — Probabilistic scenario adjudication via softmax logits.

Implements Section 7 of OMEGA_FORMULAS.md exactly.
Uses the shared softmax from omega.utils for consistency.
"""
import math
from typing import Dict, Any


def softmax(logits: Dict[str, float]) -> Dict[str, float]:
    """Applies softmax to a dictionary of scenario logits.
    
    Uses numerically stable variant (subtract max before exp)
    to prevent overflow.
    """
    if not logits:
        return {}
    m = max(logits.values())
    exps = {k: math.exp(v - m) for k, v in logits.items()}
    s = sum(exps.values()) or 1.0
    return {k: exps[k] / s for k in exps}


def rank_scenarios(
    argus_ev: Dict[str, float],
    echo_data: Dict[str, float],
    ghost_data: Dict[str, float],
    reality_data: Dict[str, float],
    dominant_direction: int,
) -> Dict[str, float]:
    """Ranks market scenarios based on the OMEGA vision model.
    
    Implements Section 7 of OMEGA_FORMULAS.md with exact coefficient parity
    to the reference implementation. Coefficients are inlined (not config-driven)
    because they are part of the mathematical specification, not tunable parameters.
    
    If dominant direction is bearish, sweep_up and sweep_down are swapped
    per the spec: "swap sweep_up with sweep_down in directional continuation weighting."
    """
    sweep_up = ghost_data["sweep_probability_up"]
    sweep_down = ghost_data["sweep_probability_down"]

    if dominant_direction < 0:
        sweep_up, sweep_down = sweep_down, sweep_up

    logits = {
        "clean_continuation": (
            0.35 * argus_ev["expansion"]
            + 0.25 * echo_data["continuation_probability"]
            + 0.20 * sweep_up
            + 0.20 * reality_data["truth_score"]
            - 0.30 * reality_data["deception_score"]
        ),
        "sweep_then_continuation": (
            0.25 * argus_ev["expansion"]
            + 0.20 * echo_data["continuation_probability"]
            + 0.35 * max(sweep_up, sweep_down)
            + 0.20 * ghost_data["post_sweep_reversal_probability"]
            + 0.10 * reality_data["deception_score"]
        ),
        "failed_breakout_trap": (
            0.20 * argus_ev["trap"]
            + 0.15 * echo_data["failure_probability"]
            + 0.20 * reality_data["deception_score"]
            + 0.25 * (1 - reality_data["breakout_validity"])
            + 0.20 * reality_data["trap_probability"]
        ),
        "reversal_after_failed_expansion": (
            0.20 * argus_ev["reversal"]
            + 0.20 * echo_data["reversal_probability"]
            + 0.20 * ghost_data["post_sweep_reversal_probability"]
            + 0.15 * reality_data["deception_score"]
            + 0.10 * argus_ev["trap"]
            + 0.15 * echo_data["failure_probability"]
        ),
    }

    return softmax(logits)
