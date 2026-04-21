def clamp(val: float, min_val: float, max_val: float) -> float:
    """Clamps a value between a minimum and maximum range."""
    return max(min_val, min(max_val, val))

def n1(val: float) -> float:
    """Normalizes a value to a 0-1 range."""
    return clamp(val, 0.0, 1.0)

def n100(val: float) -> float:
    """Normalizes a value to a 0-100 range."""
    return clamp(val, 0.0, 100.0)
