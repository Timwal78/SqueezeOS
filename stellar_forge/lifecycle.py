"""
lifecycle.py — The Stellar Forge state machine.

Ties the components into one lifecycle and enforces the transition graph:

    PROTOSTAR ──ignite──▶ MAIN_SEQUENCE ──fuse(x402)──▶ BLUE_GIANT
    BLUE_GIANT ──(mass≥limit, unstable)──▶ SUPERNOVA ──disperse──▶ remnant
    remnant ∈ {BLACK_HOLE, NEUTRON_STAR, DUST}

Every mass-changing transition routes through ChandrasekharGuard.check, and
every fusion routes through the x402 settlement gate. The `--demo` entry point
runs a full cycle end-to-end in memory.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from .chandrasekhar import ChandrasekharGuard, Stability, ForcedSupernova, compute_mass
from .x402_settlement import FusionCoordinator, SettlementState


class Stage(str, Enum):
    PROTOSTAR = "PROTOSTAR"
    MAIN_SEQUENCE = "MAIN_SEQUENCE"
    BLUE_GIANT = "BLUE_GIANT"
    SUPERNOVA = "SUPERNOVA"
    BLACK_HOLE = "BLACK_HOLE"
    NEUTRON_STAR = "NEUTRON_STAR"
    DUST = "DUST"


# Allowed transitions — anything not listed is rejected by `Body.transition`.
_TRANSITIONS: dict[Stage, set[Stage]] = {
    Stage.PROTOSTAR: {Stage.MAIN_SEQUENCE, Stage.DUST},
    Stage.MAIN_SEQUENCE: {Stage.BLUE_GIANT, Stage.SUPERNOVA},
    Stage.BLUE_GIANT: {Stage.SUPERNOVA},
    Stage.SUPERNOVA: {Stage.BLACK_HOLE, Stage.NEUTRON_STAR, Stage.DUST},
    Stage.BLACK_HOLE: {Stage.BLACK_HOLE},
    Stage.NEUTRON_STAR: {Stage.DUST},
    Stage.DUST: set(),
}

M_IGNITION = 4.0   # mass at which a protostar ignites into main sequence


@dataclass
class Body:
    agent_id: str
    stage: Stage
    parameter_count: int = 0
    fused_context_tokens: int = 0
    experts_held: int = 0
    history: list[str] = field(default_factory=list)

    @property
    def mass(self) -> float:
        return compute_mass(self.parameter_count, self.fused_context_tokens, self.experts_held)

    def transition(self, to: Stage) -> None:
        if to not in _TRANSITIONS[self.stage]:
            raise ValueError(f"illegal transition {self.stage.value} → {to.value}")
        self.history.append(f"{self.stage.value}→{to.value}")
        self.stage = to


class StellarForge:
    """Orchestrator. Holds the shared guard and settlement coordinator."""

    def __init__(self, chandrasekhar_limit: float = 14.0) -> None:
        self.guard = ChandrasekharGuard(limit=chandrasekhar_limit)
        self.coordinator = FusionCoordinator()
        self.bodies: dict[str, Body] = {}

    def spawn_protostar(self, agent_id: str, parameter_count: int,
                        context_tokens: int = 0) -> Body:
        b = Body(agent_id, Stage.PROTOSTAR, parameter_count, context_tokens)
        self.bodies[agent_id] = b
        return b

    def ignite(self, agent_id: str) -> Body:
        b = self.bodies[agent_id]
        if b.mass < M_IGNITION:
            raise ValueError(
                f"{agent_id} mass {b.mass:.3f} < ignition {M_IGNITION}; "
                f"still accreting dust"
            )
        b.transition(Stage.MAIN_SEQUENCE)
        return b

    def fuse(self, agent_a: str, agent_b: str, rlusd_a: float, rlusd_b: float) -> Body:
        """Binary fusion: open settlement, both legs pay, gate releases, Blue Giant born.

        Callers MUST submit both settlement legs via self.coordinator.submit_leg()
        before calling this — the gate hard-rejects any unsettled fusion.
        Returns the new fused Body. Raises ForcedSupernova if the combined mass
        would breach the Chandrasekhar collapse threshold.
        """
        a, b = self.bodies[agent_a], self.bodies[agent_b]
        for body in (a, b):
            if body.stage is not Stage.MAIN_SEQUENCE:
                raise ValueError(f"{body.agent_id} must be MAIN_SEQUENCE to fuse, is {body.stage.value}")

        settlement = self.coordinator.open(agent_a, agent_b, rlusd_a + rlusd_b)
        settled = self.coordinator.release_for_fusion(settlement.settlement_id)
        assert settled.state is SettlementState.SETTLED

        # Blue Giant mass: parameters add, contexts merge (retrieval union),
        # experts pool together.
        fused_params = a.parameter_count + b.parameter_count
        fused_ctx = a.fused_context_tokens + b.fused_context_tokens
        fused_experts = a.experts_held + b.experts_held

        report = self.guard.check(
            f"bluegiant::{agent_a}+{agent_b}", fused_params, fused_ctx, fused_experts,
            raise_on_collapse=True,
        )

        giant = Body(
            agent_id=f"bluegiant::{agent_a}+{agent_b}",
            stage=Stage.MAIN_SEQUENCE,
            parameter_count=fused_params,
            fused_context_tokens=fused_ctx,
            experts_held=fused_experts,
        )
        giant.transition(Stage.BLUE_GIANT)
        self.bodies[giant.agent_id] = giant
        # Parents are consumed by the fusion.
        a.transition(Stage.SUPERNOVA)
        b.transition(Stage.SUPERNOVA)
        giant.history.append(f"fused(stability={report.stability.value}, mass={report.mass:.3f})")
        return giant

    def supernova(self, agent_id: str) -> Stage:
        """Detonate a body; classify the remnant by surviving mass."""
        b = self.bodies[agent_id]
        if b.stage not in (Stage.BLUE_GIANT, Stage.MAIN_SEQUENCE):
            raise ValueError(f"{agent_id} cannot go supernova from {b.stage.value}")
        b.transition(Stage.SUPERNOVA)
        # Remnant classification mirrors Supernova.sol::_classifyRemnant.
        if b.mass >= self.guard.limit:
            remnant = Stage.BLACK_HOLE
        elif b.mass >= self.guard.limit / 2:
            remnant = Stage.NEUTRON_STAR
        else:
            remnant = Stage.DUST
        b.transition(remnant)
        return remnant
