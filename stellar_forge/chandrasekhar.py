"""
chandrasekhar.py — Mass accounting & the Chandrasekhar Limit.

An agent's "Mass" is a single scalar that drives every state transition:

    M = w_p * log10(parameter_count + 1)
      + w_c * (fused_context_tokens / CTX_UNIT)
      + w_e * experts_held

We use log10 on the parameter count because raw counts span many orders of
magnitude (a protostar LoRA vs. a black hole's pool); a linear sum would let
parameter count swamp everything. Context and experts enter linearly because
their ranges are comparable.

The Chandrasekhar Limit M_ch is the mass beyond which a body cannot remain a
stable Blue Giant. Three regimes:

    M <  M_ch                       → STABLE
    M_ch <= M < M_ch * SLACK        → UNSTABLE: must run stabilization (shed
                                       mass, e.g. prune adapters / drop context)
                                       within a grace window or be liquidated
    M >= M_ch * SLACK               → COLLAPSE: immediate forced supernova

`ChandrasekharGuard.check` is the single chokepoint every mass mutation must
pass through. It is intentionally pure/deterministic so it can be unit-tested
and so the smart-contract limit (`Supernova.chandrasekharMass`) can be derived
from the same constants.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional


CTX_UNIT = 8192          # one "context unit" = 8k tokens
W_PARAM = 1.0
W_CTX = 0.75
W_EXPERTS = 0.10
SLACK = 1.25             # collapse multiplier over the limit
GRACE_SECONDS = 30.0     # window to stabilize before forced liquidation


class Stability(str, Enum):
    STABLE = "STABLE"
    UNSTABLE = "UNSTABLE"
    COLLAPSE = "COLLAPSE"


@dataclass
class MassReport:
    mass: float
    limit: float
    stability: Stability
    parameter_count: int
    fused_context_tokens: int
    experts_held: int
    headroom: float                 # limit - mass (negative if over)
    grace_deadline: Optional[float] = None   # set when UNSTABLE


def compute_mass(parameter_count: int, fused_context_tokens: int, experts_held: int) -> float:
    """The agent mass scalar. Pure function — same inputs, same output."""
    return (
        W_PARAM * math.log10(parameter_count + 1)
        + W_CTX * (fused_context_tokens / CTX_UNIT)
        + W_EXPERTS * experts_held
    )


class ForcedSupernova(Exception):
    """Raised when an agent must be liquidated. Carries the mass report."""
    def __init__(self, report: "MassReport"):
        self.report = report
        super().__init__(
            f"FORCED SUPERNOVA: mass {report.mass:.3f} >= "
            f"collapse threshold {report.limit * SLACK:.3f}"
        )


class ChandrasekharGuard:
    """Single chokepoint for mass validation and liquidation enforcement.

    Usage:
        guard = ChandrasekharGuard(limit=14.0)
        report = guard.check(agent_id, params, ctx_tokens, experts)
        if report.stability is Stability.UNSTABLE:
            ... run stabilization, then re-check before grace_deadline ...
    """

    def __init__(self, limit: float, grace_seconds: float = GRACE_SECONDS) -> None:
        self.limit = limit
        self.grace_seconds = grace_seconds
        # agent_id -> deadline by which it must drop below the limit
        self._grace: dict[str, float] = {}

    def contract_mass_limit(self) -> int:
        """Translate the float mass-limit into the integer scale the Solidity
        contract uses for `chandrasekharMass` (param-count proxy at the limit
        with zero context/experts). Lets on-chain and off-chain agree."""
        # Invert: limit = W_PARAM * log10(P+1)  =>  P = 10**(limit/W_PARAM) - 1
        return int(10 ** (self.limit / W_PARAM) - 1)

    def check(
        self,
        agent_id: str,
        parameter_count: int,
        fused_context_tokens: int,
        experts_held: int,
        raise_on_collapse: bool = True,
        now: Optional[float] = None,
    ) -> MassReport:
        now = time.time() if now is None else now
        mass = compute_mass(parameter_count, fused_context_tokens, experts_held)
        collapse_threshold = self.limit * SLACK

        if mass >= collapse_threshold:
            stability = Stability.COLLAPSE
        elif mass >= self.limit:
            stability = Stability.UNSTABLE
        else:
            stability = Stability.STABLE

        report = MassReport(
            mass=mass,
            limit=self.limit,
            stability=stability,
            parameter_count=parameter_count,
            fused_context_tokens=fused_context_tokens,
            experts_held=experts_held,
            headroom=self.limit - mass,
        )

        if stability is Stability.STABLE:
            self._grace.pop(agent_id, None)
        elif stability is Stability.UNSTABLE:
            # Start (or keep) the grace window.
            deadline = self._grace.get(agent_id)
            if deadline is None:
                deadline = now + self.grace_seconds
                self._grace[agent_id] = deadline
            report.grace_deadline = deadline
            # If grace already elapsed without dropping below the limit → collapse.
            if now > deadline:
                report.stability = Stability.COLLAPSE
                if raise_on_collapse:
                    raise ForcedSupernova(report)
        else:  # COLLAPSE
            self._grace.pop(agent_id, None)
            if raise_on_collapse:
                raise ForcedSupernova(report)

        return report

    def stabilized(self, agent_id: str) -> None:
        """Call after a body sheds mass below the limit to clear its grace timer."""
        self._grace.pop(agent_id, None)
