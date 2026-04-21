"""
Omega Utility Module — Shared helpers for the institutional fusion pipeline.
All helpers must remain pure functions with no side effects.
"""
from typing import Dict, Any
import math


def softmax(scores: Dict[str, float]) -> Dict[str, float]:
    """Applies softmax normalization to a dictionary of scenario logits.
    
    Uses the numerically stable variant (subtract max before exponentiation)
    to prevent overflow on large logit values.
    """
    if not scores:
        return {}
    m = max(scores.values())
    exps = {k: math.exp(v - m) for k, v in scores.items()}
    s = sum(exps.values()) or 1.0
    return {k: exps[k] / s for k in exps}


def safe_get_nested(data: Dict[str, Any], *keys, default=None) -> Any:
    """Safely traverse nested dictionaries without KeyError.
    
    Example:
        safe_get_nested(argus, "trigger_map", "confirm_above", default=None)
    """
    current = data
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key, default)
        else:
            return default
    return current


def validate_subsystem_keys(data: Dict[str, Any], required_keys: list, subsystem_name: str) -> None:
    """Validates that all required keys exist in a subsystem payload.
    
    Raises ValueError with an institutional-grade error message if keys are missing.
    """
    missing = [k for k in required_keys if k not in data]
    if missing:
        raise ValueError(
            f"[OMEGA INTEGRITY VIOLATION] {subsystem_name} payload missing required fields: {missing}"
        )
