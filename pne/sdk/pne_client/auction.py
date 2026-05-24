"""Bidding strategy implementations for the PNE auction."""
from __future__ import annotations

import math
from collections import deque
from enum import Enum
from typing import Protocol


class BiddingStrategy(Protocol):
    def initial_tip(self, max_tip: int) -> int: ...
    def increase_tip(self, current_tip: int, current_rank: int, max_tip: int) -> int: ...
    def record_outcome(self, rank: int, tip: int) -> None: ...


class Strategy(str, Enum):
    AGGRESSIVE = "aggressive"
    CONSERVATIVE = "conservative"
    OPTIMAL = "optimal"


class AggressiveBidder:
    """Start at 80% of max_tip. Increase by 25% on each rank miss."""

    def initial_tip(self, max_tip: int) -> int:
        return int(max_tip * 0.80)

    def increase_tip(self, current_tip: int, current_rank: int, max_tip: int) -> int:
        return min(int(current_tip * 1.25), max_tip)

    def record_outcome(self, rank: int, tip: int) -> None:
        pass  # Aggressive strategy doesn't adapt


class ConservativeBidder:
    """Start at 10% of max_tip. Increase by 20% on each rank miss."""

    def initial_tip(self, max_tip: int) -> int:
        return int(max_tip * 0.10)

    def increase_tip(self, current_tip: int, current_rank: int, max_tip: int) -> int:
        bump = 1.0 + 0.20 * current_rank
        return min(int(current_tip * bump), max_tip)

    def record_outcome(self, rank: int, tip: int) -> None:
        pass


class OptimalBidder:
    """
    Kelly-criterion-inspired strategy.
    Maintains a rolling window of past outcomes to estimate win probability.
    tip = max_tip * kelly_fraction
    kelly_fraction = win_rate - (1 - win_rate) * rank_cost_multiplier
    """

    def __init__(self, window: int = 100):
        self._history: deque[dict] = deque(maxlen=window)

    def _win_rate(self) -> float:
        if len(self._history) < 5:
            return 0.3  # cold start: assume 30% win rate
        wins = sum(1 for h in self._history if h["rank"] == 1)
        return wins / len(self._history)

    def _avg_winning_tip(self) -> float:
        wins = [h["tip"] for h in self._history if h["rank"] == 1]
        return sum(wins) / len(wins) if wins else 0

    def initial_tip(self, max_tip: int) -> int:
        wr = self._win_rate()
        # Kelly fraction: bet proportional to edge
        edge = wr - (1 - wr)
        fraction = max(0.05, min(edge, 0.95))  # clamp to [5%, 95%]
        return max(0, int(max_tip * fraction))

    def increase_tip(self, current_tip: int, current_rank: int, max_tip: int) -> int:
        wr = self._win_rate()
        # Increase proportional to how far off rank we are
        rank_penalty = (current_rank - 1) * 0.15
        new_fraction = min(wr + rank_penalty, 1.0)
        return min(int(max_tip * new_fraction), max_tip)

    def record_outcome(self, rank: int, tip: int) -> None:
        self._history.append({"rank": rank, "tip": tip})


def make_strategy(name: str) -> BiddingStrategy:
    match name.lower():
        case "aggressive":
            return AggressiveBidder()
        case "conservative":
            return ConservativeBidder()
        case "optimal" | _:
            return OptimalBidder()
