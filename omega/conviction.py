from .normalization import n1
from app.config import (
    CI_OMEGA_WEIGHT, CI_ALIGNMENT_WEIGHT, CI_DECEPTION_WEIGHT,
    CI_CONFIDENCE_WEIGHT, CI_MODERATE_THRESH, CI_HIGH_THRESH,
    CI_EXTREME_THRESH
)

def calculate_conviction(omega_score: float, alignment_strength: float, deception_score: float, similarity_score: float, echo_confidence: float, state_confidence: float) -> str:
    """Calculates the final conviction bucket based on multiple subsystem inputs."""
    
    ci = (
        CI_OMEGA_WEIGHT * (omega_score / 100.0)
        + CI_ALIGNMENT_WEIGHT * (alignment_strength / 100.0)
        + CI_DECEPTION_WEIGHT * (1 - deception_score)
        + CI_CONFIDENCE_WEIGHT * max(similarity_score * echo_confidence, state_confidence)
    )
    
    if ci < CI_MODERATE_THRESH:
        return "low"
    elif ci < CI_HIGH_THRESH:
        return "moderate"
    elif ci < CI_EXTREME_THRESH:
        return "high"
    else:
        return "extreme"
