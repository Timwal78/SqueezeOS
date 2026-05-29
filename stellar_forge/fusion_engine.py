"""
fusion_engine.py — The Fusion Protocol (ML core).

A "Binary Fusion" produces a *new adapter configuration* from two parent
agents. We model each agent as:

    - a stack of LoRA adapters (low-rank weight deltas), and
    - a Mixture-of-Experts (MoE) gate vector that routes tokens to experts.

Fusion does two mathematically well-defined things, gated on a SETTLED
x402 settlement (`x402_settlement.FusionCoordinator.release_for_fusion`):

  1. MoE gate blend — convex combination of the two gate logits, weighted by
     the capital each parent committed (binding-energy share). This is the
     "attention heads intertwine" step, made concrete: the merged router
     attends to both parents' experts proportional to who paid more.

  2. LoRA SLERP — spherical linear interpolation of matched adapter tensors.
     SLERP (not naive averaging) preserves the norm/geometry of the delta,
     which empirically degrades less than linear averaging when the two
     adapters point in different directions.

We DO NOT claim the fused model is strictly better. We compute a
`compatibility` score (cosine alignment of the parents' LoRA directions) and
surface it. Low compatibility ⇒ destructive interference ⇒ the protocol
should price the fusion higher or refuse it. That is honest physics: not every
pair of nuclei fuses exothermically.

Requires: torch, numpy.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import torch

from .x402_settlement import FusionCoordinator


@dataclass
class AgentWeights:
    """A parent agent's fusible parameters.

    lora: dict[name -> (A, B)] low-rank factors; effective delta = B @ A * scale.
    gate_logits: 1-D tensor over the global expert pool (MoE router pre-softmax).
    n_experts: size of the expert pool the gate addresses.
    """
    agent_id: str
    lora: dict[str, tuple[torch.Tensor, torch.Tensor]]
    gate_logits: torch.Tensor
    n_experts: int
    lora_scale: float = 1.0


@dataclass
class FusionResult:
    fused_id: str
    lora: dict[str, tuple[torch.Tensor, torch.Tensor]]
    gate_logits: torch.Tensor
    compatibility: float            # mean cosine alignment of matched LoRA deltas in [-1, 1]
    alpha: float                    # binding-energy share of parent A in [0, 1]
    fused_param_count: int
    notes: list[str] = field(default_factory=list)


def _slerp(a: torch.Tensor, b: torch.Tensor, t: float, eps: float = 1e-7) -> torch.Tensor:
    """Spherical linear interpolation between two tensors, flattened then reshaped.

    Falls back to linear interpolation when the vectors are nearly colinear
    (sin(omega) -> 0), which avoids division blow-up.
    """
    a_flat, b_flat = a.reshape(-1), b.reshape(-1)
    na, nb = a_flat.norm() + eps, b_flat.norm() + eps
    ua, ub = a_flat / na, b_flat / nb
    dot = torch.clamp((ua * ub).sum(), -1.0, 1.0)
    omega = torch.arccos(dot)
    so = torch.sin(omega)
    if so.abs() < eps:                      # colinear → lerp
        out = (1 - t) * a_flat + t * b_flat
    else:
        out = (torch.sin((1 - t) * omega) / so) * a_flat + \
              (torch.sin(t * omega) / so) * b_flat
    # interpolate magnitude separately so SLERP doesn't collapse scale
    target_norm = (1 - t) * na + t * nb
    out = out / (out.norm() + eps) * target_norm
    return out.reshape(a.shape)


def _effective_delta(A: torch.Tensor, B: torch.Tensor, scale: float) -> torch.Tensor:
    """Reconstruct the full-rank delta direction for compatibility scoring."""
    return (B @ A) * scale


def lora_compatibility(a: AgentWeights, b: AgentWeights) -> float:
    """Mean cosine similarity of matched adapter deltas. Higher ⇒ fuses cleanly."""
    shared = set(a.lora) & set(b.lora)
    if not shared:
        return 0.0
    sims = []
    for name in shared:
        da = _effective_delta(*a.lora[name], a.lora_scale).reshape(-1)
        db = _effective_delta(*b.lora[name], b.lora_scale).reshape(-1)
        cos = torch.nn.functional.cosine_similarity(da, db, dim=0, eps=1e-7)
        sims.append(float(cos))
    return sum(sims) / len(sims)


def binding_energy_share(rlusd_a: float, rlusd_b: float) -> float:
    """Capital committed by A as a fraction of the total. Drives the blend weight."""
    total = rlusd_a + rlusd_b
    if total <= 0:
        return 0.5
    return rlusd_a / total


class FusionEngine:
    """Executes a Fusion Event under an atomic x402 settlement gate."""

    def __init__(self, coordinator: FusionCoordinator) -> None:
        self.coordinator = coordinator

    def fuse(
        self,
        settlement_id: str,
        a: AgentWeights,
        b: AgentWeights,
        rlusd_a: float,
        rlusd_b: float,
        min_compatibility: float = -0.25,
    ) -> FusionResult:
        """Blend two agents into a Blue Giant adapter config.

        HARD GATE: raises unless the x402 settlement is SETTLED. This is the
        only path that touches weights.
        """
        # 1. Strong-force gate: no binding energy paid → no fusion.
        self.coordinator.release_for_fusion(settlement_id)

        # 2. Compatibility check — destructive interference guard.
        compat = lora_compatibility(a, b)
        notes: list[str] = []
        if compat < min_compatibility:
            raise ValueError(
                f"FUSION REJECTED: compatibility {compat:.3f} < "
                f"{min_compatibility:.3f}. Parameter spaces would destructively "
                f"interfere (anti-aligned deltas). Re-price or refuse."
            )
        if compat < 0.0:
            notes.append(
                f"low compatibility ({compat:.3f}): expect capability loss on "
                f"overlapping skills; fusion priced as high-risk."
            )

        alpha = binding_energy_share(rlusd_a, rlusd_b)  # weight toward A

        # 3. MoE gate blend over the union of expert pools.
        n_experts = max(a.n_experts, b.n_experts)
        ga = torch.nn.functional.pad(a.gate_logits, (0, n_experts - a.n_experts))
        gb = torch.nn.functional.pad(b.gate_logits, (0, n_experts - b.n_experts))
        fused_gate = alpha * ga + (1 - alpha) * gb

        # 4. LoRA SLERP on matched adapters; carry through unmatched ones.
        fused_lora: dict[str, tuple[torch.Tensor, torch.Tensor]] = {}
        shared = set(a.lora) & set(b.lora)
        for name in shared:
            Aa, Ba = a.lora[name]
            Ab, Bb = b.lora[name]
            if Aa.shape != Ab.shape or Ba.shape != Bb.shape:
                notes.append(f"adapter '{name}' rank/shape mismatch — kept parent A")
                fused_lora[name] = (Aa.clone(), Ba.clone())
                continue
            # blend toward the higher-paying parent (t = 1 - alpha favors B)
            fused_lora[name] = (
                _slerp(Aa, Ab, 1 - alpha),
                _slerp(Ba, Bb, 1 - alpha),
            )
        for name in set(a.lora) - shared:
            fused_lora[name] = tuple(t.clone() for t in a.lora[name])  # type: ignore
        for name in set(b.lora) - shared:
            fused_lora[name] = tuple(t.clone() for t in b.lora[name])  # type: ignore

        param_count = sum(A.numel() + B.numel() for A, B in fused_lora.values())
        param_count += fused_gate.numel()

        fused_id = f"bluegiant::{a.agent_id}+{b.agent_id}"
        return FusionResult(
            fused_id=fused_id,
            lora=fused_lora,
            gate_logits=fused_gate,
            compatibility=compat,
            alpha=alpha,
            fused_param_count=param_count,
            notes=notes,
        )
