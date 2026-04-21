from typing import Dict, Tuple
from app.config import BIAS_WEIGHTS, ALIGN_WEIGHT_ARGUS, ALIGN_WEIGHT_ECHO, ALIGN_WEIGHT_GHOST, ALIGN_WEIGHT_REALITY
from .normalization import n100

def infer_directions(argus_bias: str, echo_probs: Dict[str, float], ghost_probs: Dict[str, float], reality_data: Dict[str, float]) -> Dict[str, int]:
    """Infers direction (-1, 0, 1) for each subsystem based on authoritative logic."""
    
    # ARGUS
    if "bullish" in argus_bias:
        argus_dir = 1
    elif "bearish" in argus_bias:
        argus_dir = -1
    else:
        argus_dir = 0
        
    # ECHO
    if echo_probs["continuation_probability"] >= echo_probs["reversal_probability"] and \
       echo_probs["continuation_probability"] >= echo_probs["failure_probability"]:
        echo_dir = 1
    elif echo_probs["reversal_probability"] > echo_probs["continuation_probability"] and \
         echo_probs["reversal_probability"] >= echo_probs["failure_probability"]:
        echo_dir = -1
    else:
        echo_dir = 0
        
    # GHOST
    diff = ghost_probs["sweep_probability_up"] - ghost_probs["sweep_probability_down"]
    if diff >= 0.10:
        ghost_dir = 1
    elif -diff >= 0.10:
        ghost_dir = -1
    else:
        ghost_dir = 0
        
    # REALITY (TRUTH)
    if reality_data["breakout_validity"] >= 0.60 and reality_data["deception_score"] <= 0.40:
        truth_dir = 1
    elif reality_data["deception_score"] >= 0.70 and reality_data["trap_probability"] >= 0.55:
        truth_dir = -1
    else:
        truth_dir = 0
        
    return {"argus": argus_dir, "echo": echo_dir, "ghost": ghost_dir, "truth": truth_dir}

def calculate_alignment(directions: Dict[str, int], deception_score: float) -> Dict[str, any]:
    """Determines alignment strength and state based on directional votes."""
    
    weights = {"argus": ALIGN_WEIGHT_ARGUS, "echo": ALIGN_WEIGHT_ECHO, "ghost": ALIGN_WEIGHT_GHOST, "truth": ALIGN_WEIGHT_REALITY}
    
    bull_weight = sum(weights[k] for k, v in directions.items() if v == 1)
    bear_weight = sum(weights[k] for k, v in directions.items() if v == -1)
    neutral_weight = 1.0 - bull_weight - bear_weight
    
    raw_alignment = 100 * max(bull_weight, bear_weight)
    conflict_gap = abs(bull_weight - bear_weight)
    
    alignment_strength = n100(raw_alignment * (0.60 + 0.40 * conflict_gap))
    
    # State classification (Institutional Adjudication)
    if max(bull_weight, bear_weight) >= 0.75 and neutral_weight <= 0.10:
        state = "full_alignment"
    elif max(bull_weight, bear_weight) >= 0.55 and deception_score >= 0.55:
        state = "directional_alignment_with_execution_conflict"
    elif max(bull_weight, bear_weight) >= 0.55:
        state = "directional_alignment"
    elif conflict_gap < 0.20:
        state = "mixed_conflict"
    else:
        state = "low_signal"
        
    return {
        "strength": alignment_strength,
        "state": state,
        "bull_weight": bull_weight,
        "bear_weight": bear_weight,
        "conflict_gap": conflict_gap
    }
