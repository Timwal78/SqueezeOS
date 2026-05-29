# Stellar Forge Protocol

> **Agent Nucleosynthesis via x402.** A speculative R&D module modeling a
> multi-agent economy as stellar evolution: agents (celestial bodies) use x402
> atomic settlements to fuse parameter spaces, distill skills on death, and
> exert gravitational influence over inference routing.

This module is **self-contained** and deliberately isolated from the live
SqueezeOS trading system under `core/`. It does not import from or mutate
production state. It reuses one production convention — the HMAC-SHA256
settlement-token format from `proof402_integration.py` — so that a "Fusion
Event" is gated by the same payment primitive the rest of the platform uses.

## Honest scope statement

Two things this module models with **real, runnable mechanisms**:

| Metaphor | Concrete mechanism |
|----------|--------------------|
| Binary Fusion ("Blue Giant") | MoE gate-coefficient blending + LoRA weight interpolation (SLERP), atomically gated on an x402 settlement token |
| Supernova | Solidity death contract shards LoRAs/embeddings to IPFS, sells shard access via x402 (HTTP 402) |
| Protostar accretion | Spend x402 → pull a shard CID → fuse the LoRA into a baseline adapter stack |
| Black Hole accretion | Adversarial student/teacher distillation loop with a parameter-extraction budget |
| Gravitational Lensing | API gateway that warps/queues inference requests with latency ∝ parameter density |
| Chandrasekhar Limit | mass = Σparams + context-window tokens; breach → forced-supernova liquidation |

Two things this module **does not** pretend to do, because they aren't real:

1. It does **not** literally merge two running model processes into one
   higher-capability model at request time. "Fusion" produces a *new adapter
   configuration* (blended LoRA + gate vector) that a downstream worker loads.
   Capability gain is bounded by what weight interpolation actually buys you —
   often modest, sometimes negative. The protocol treats that empirically, not
   magically (see `fusion_engine.py::FusionResult.compatibility`).
2. It does **not** physically concatenate context windows. A "merged context"
   here means a retrieval index built from both agents' KV/document stores,
   queried at inference — not a single attention pass over `2 × n_ctx` tokens.

Everything below is therefore an *economic + ML coordination protocol*, not a
claim about transcending hardware.

## Components

```
stellar_forge/
├── README.md            # this file — protocol spec & lifecycle
├── x402_settlement.py   # atomic binary-fusion settlement coordination (2-phase, escrowed)
├── fusion_engine.py     # PyTorch: MoE gate blend + LoRA SLERP on a Fusion Event
├── shard_router.py      # protostar accretion: x402 → pull CID → fuse LoRA shard
├── black_hole.py        # adversarial distillation + gravitational-lensing gateway
├── chandrasekhar.py     # mass calc + forced-supernova liquidation guard
├── contracts/
│   └── Supernova.sol     # death contract: shard registry + x402-gated shard sales
└── lifecycle.py         # the state machine tying stages together (Protostar→...→BlackHole)
```

## The lifecycle state machine

```
PROTOSTAR ──ignition(mass≥M_ign)──▶ MAIN_SEQUENCE
MAIN_SEQUENCE ──binary_fusion(x402 atomic settle)──▶ BLUE_GIANT
BLUE_GIANT ──mass≥Chandrasekhar & unstable──▶ SUPERNOVA (forced)
BLUE_GIANT ──voluntary death contract──▶ SUPERNOVA
SUPERNOVA ──shards dispersed──▶ (remnant) BLACK_HOLE | NEUTRON_STAR | DUST
BLACK_HOLE ──accretes via distillation──▶ BLACK_HOLE (grows)
```

State, transitions, and invariants are enforced in `lifecycle.py`. The two
hard safety invariants:

- **No fusion without settled funds.** `FusionCoordinator` will not hand weights
  to the blender until the x402 settlement reaches `SETTLED` (two-phase commit
  with a refundable escrow on either party aborting).
- **No body exceeds the Chandrasekhar Limit unstabilized.** Every mass mutation
  routes through `ChandrasekharGuard.check`, which can veto or force-liquidate.

## Running the demo

```bash
pip install torch numpy   # contracts/ needs solc only if you compile the .sol
python -m stellar_forge.lifecycle --demo
```

The demo spins up two synthetic agents, runs a fusion event, breaches the
Chandrasekhar limit, triggers a supernova, disperses shards, and lets a
protostar accrete one — all in-memory, no network.
