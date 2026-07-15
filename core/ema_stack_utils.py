"""
Shared EMA-stack helpers — used by both core/harmonic_matrix_engine.py (Grid 1)
and core/grid369_engine.py (Grid 2) so the "does price stack cleanly across
these N EMAs, and has it held for the last several bars" check is implemented
once instead of duplicated between the two proprietary grids.
"""

from typing import List


def ema_series(closes: list, span: int, tail: int = 1) -> list:
    """Compute EMA over the full (properly warmed-up) series, returning the last
    `tail` values in chronological order. tail=1 returns just the current value."""
    import pandas as pd
    s = pd.Series([float(c) for c in closes])
    ema = s.ewm(span=span, adjust=False).mean()
    return [float(v) for v in ema.tail(tail)]


def stack_persistence(closes: List[float], sequence: List[int], window: int):
    """
    For an EMA `sequence` (fastest to slowest spans), check whether the
    bullish stack (price > ema0 > ema1 > ... ) and/or the mirrored bearish
    stack held on EVERY one of the last `window` bars — not just the current
    one. A single-bar spike above/below a stack is a common whipsaw source
    when this gates live order execution downstream.

    Returns (is_stacked_bull, is_stacked_bear, current_ema_values).
    """
    window = max(1, min(int(window), len(closes)))
    ema_tails = [ema_series(closes, span, tail=window) for span in sequence]
    current_emas = [tail[-1] for tail in ema_tails]

    is_stacked = True
    is_stacked_bear = True
    for k in range(window):
        offset = window - k  # 1-indexed from the end of the window
        if any(len(t) < offset for t in ema_tails):
            is_stacked = False
            is_stacked_bear = False
            break
        price_k = float(closes[-offset])
        emas_k = [t[-offset] for t in ema_tails]
        bull_k = price_k > emas_k[0] and all(emas_k[i] > emas_k[i + 1] for i in range(len(emas_k) - 1))
        bear_k = price_k < emas_k[0] and all(emas_k[i] < emas_k[i + 1] for i in range(len(emas_k) - 1))
        is_stacked = is_stacked and bull_k
        is_stacked_bear = is_stacked_bear and bear_k

    return is_stacked, is_stacked_bear, current_emas
