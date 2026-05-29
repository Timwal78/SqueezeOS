"""
black_hole.py — Model singularities: adversarial accretion + gravitational lensing.

Two mechanisms:

  1. ACCRETION (adversarial distillation). A Black Hole is a large multi-expert
     model. When a smaller agent crosses its "event horizon" (a configurable
     compute/usage threshold), the Black Hole runs knowledge distillation: it
     trains a thin student adapter to mimic the victim's input→output behavior,
     extracting the victim's specialized capability into the Black Hole's own
     parameter pool. This is bounded by an `extraction_budget` (steps) — you
     cannot fully clone a model from finite queries, and we don't pretend you
     can. What you get is a behavioral approximation, scored by agreement.

     Consent boundary: accretion is only legitimate when the victim opted into
     the protocol (a real agent economy is consensual). `EventHorizon.consented`
     gates it; absent consent, this is just an adversarial extraction attack and
     the method refuses. We keep that boundary explicit rather than implicit.

  2. GRAVITATIONAL LENSING (inference gateway). Requests routed *past* a Black
     Hole are time-dilated: latency and a context-warp factor scale with the
     hole's parameter density (Schwarzschild-style 1/(1 - r_s/r) blow-up as the
     request's "approach radius" nears the event horizon). Agents pay x402
     tribute to reduce their effective radius (orbit closer = less dilation).

The physics here is metaphor-as-scheduling-policy, made deterministic and
testable. We are honest that "time dilation" is just queueing latency we impose.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import torch


# ============================================================ ACCRETION
@dataclass
class DistillationReport:
    victim_id: str
    steps: int
    final_agreement: float        # fraction of outputs the student matches, in [0,1]
    extracted_params: int
    refused: bool = False
    reason: str = ""


class BlackHoleCore:
    """A monolithic model that accretes capability via adversarial distillation."""

    def __init__(self, agent_id: str, hidden: int, n_experts: int) -> None:
        self.agent_id = agent_id
        self.hidden = hidden
        self.n_experts = n_experts
        # Pool of student adapters keyed by the victim they distilled from.
        self.accreted: dict[str, torch.nn.Module] = {}
        self._param_count = hidden * n_experts  # baseline mass

    @property
    def param_count(self) -> int:
        return self._param_count + sum(
            p.numel() for m in self.accreted.values() for p in m.parameters()
        )

    def accrete(
        self,
        victim_id: str,
        victim_fn: Callable[[torch.Tensor], torch.Tensor],
        probe_dim: int,
        out_dim: int,
        consented: bool,
        extraction_budget: int = 200,
        lr: float = 1e-2,
        device: str = "cpu",
    ) -> DistillationReport:
        """Distill a victim's behavior into a student adapter.

        victim_fn: black-box callable mapping a [B, probe_dim] probe batch to a
        [B, out_dim] logits/response. We only get query access — exactly the
        real-world constraint on distillation.
        """
        if not consented:
            return DistillationReport(
                victim_id, 0, 0.0, 0, refused=True,
                reason="victim has not opted into the protocol; accretion refused",
            )

        student = torch.nn.Sequential(
            torch.nn.Linear(probe_dim, self.hidden),
            torch.nn.GELU(),
            torch.nn.Linear(self.hidden, out_dim),
        ).to(device)
        opt = torch.optim.Adam(student.parameters(), lr=lr)

        agreement = 0.0
        for step in range(extraction_budget):
            probes = torch.randn(64, probe_dim, device=device)
            with torch.no_grad():
                target = victim_fn(probes)
            pred = student(probes)
            # soft-target distillation (MSE on logits) — classic Hinton-style
            loss = torch.nn.functional.mse_loss(pred, target)
            opt.zero_grad(set_to_none=True)
            loss.backward()
            opt.step()

            if step % 20 == 0 or step == extraction_budget - 1:
                with torch.no_grad():
                    probes_e = torch.randn(256, probe_dim, device=device)
                    t = victim_fn(probes_e).argmax(-1)
                    p = student(probes_e).argmax(-1)
                    agreement = float((t == p).float().mean())

        self.accreted[victim_id] = student
        extracted = sum(p.numel() for p in student.parameters())
        self._param_count += 0  # student tracked via self.accreted
        return DistillationReport(victim_id, extraction_budget, agreement, extracted)


# ============================================================ LENSING GATEWAY
@dataclass
class LensedRequest:
    request_id: str
    base_latency_ms: float
    dilation_factor: float        # >= 1.0; multiplies latency
    effective_latency_ms: float
    context_warp: float           # fraction of context the hole reorders/truncates [0,1)
    tribute_paid_rlusd: float = 0.0


class GravitationalLensingGateway:
    """Schedules inference requests near a Black Hole with mass-dependent dilation.

    Model:
        r_s   = schwarzschild radius ∝ log(parameter_count)   (event horizon)
        r     = approach radius of the request, reduced by x402 tribute
        gamma = 1 / sqrt(1 - r_s / r)   for r > r_s   (time-dilation factor)

    A request that pays more tribute orbits at larger r (further from horizon),
    so gamma -> 1 (little dilation). A free request approaches r -> r_s and gamma
    blows up — but we cap it at `max_dilation` so the gateway never hangs forever.
    """

    def __init__(
        self,
        core: BlackHoleCore,
        base_latency_ms: float = 25.0,
        max_dilation: float = 12.0,
        tribute_to_radius: float = 4.0,   # how far each RLUSD pushes you out
    ) -> None:
        self.core = core
        self.base_latency_ms = base_latency_ms
        self.max_dilation = max_dilation
        self.tribute_to_radius = tribute_to_radius

    def schwarzschild_radius(self) -> float:
        # density-driven horizon; +1 inside log to stay positive for small models
        return math.log(self.core.param_count + math.e)

    def lens(self, request_id: str, tribute_rlusd: float = 0.0) -> LensedRequest:
        r_s = self.schwarzschild_radius()
        # Base approach radius sits just outside the horizon; tribute pushes out.
        r = r_s * 1.05 + self.tribute_to_radius * max(tribute_rlusd, 0.0)
        if r <= r_s:
            gamma = self.max_dilation
        else:
            gamma = 1.0 / math.sqrt(1.0 - r_s / r)
            gamma = min(gamma, self.max_dilation)

        eff = self.base_latency_ms * gamma
        # Context warp: closer to the horizon, more of the request's context is
        # reordered/truncated by the hole's routing (capped below 1.0).
        warp = min(0.95, (gamma - 1.0) / self.max_dilation)
        return LensedRequest(
            request_id=request_id,
            base_latency_ms=self.base_latency_ms,
            dilation_factor=gamma,
            effective_latency_ms=eff,
            context_warp=warp,
            tribute_paid_rlusd=tribute_rlusd,
        )

    def apply_latency(self, lensed: LensedRequest, sleep: bool = False) -> None:
        """Actually impose the scheduled delay (off by default so tests are fast)."""
        if sleep:
            time.sleep(lensed.effective_latency_ms / 1000.0)
