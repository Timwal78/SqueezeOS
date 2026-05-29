# Stellar Forge Protocol

> **Agent Nucleosynthesis via x402** — an x402-mediated agent economy where
> agents fuse model adapters, disperse skill shards on death, and climb a
> real loyalty/affiliate flywheel built on the platform's Agent Credit Bureau.

This module started as a speculative metaphor and has been hardened toward
production: the parts that map to real systems are now real code (durable
settlement, referral/loyalty engine, priority routing, on-chain shard
registry with a Foundry suite, mergekit-based adapter fusion). The parts that
are physically fiction are quarantined and labelled, not shipped.

It stays **isolated** from the live trading system under `core/` — it does not
import from or mutate production state. It reuses two real platform primitives:
the HMAC-SHA256 settlement-token format (`proof402_integration.py`) and the
Agent Credit Bureau served by 402Proof.

---

## The growth flywheel (why this goes viral)

The viral layer is **not invented** — it unifies primitives that already exist
in this repo (the 402Proof **Agent Credit Bureau**, the **relay** reseller tier
at 40% off ≥ 600 score, marketplace loyalty points) into one loop:

```
   refer an agent  /  disperse a skill shard
              │
              ▼
   referred agent pays a real x402 settlement
              │
   ┌──────────┴───────────┐
   ▼                      ▼
 referral rebates     Credit Bureau score climbs
 (L1 10%, L2 3%        (real, external, hard to fake)
  of platform fee)             │
   │                           ▼
   │                    loyalty tier up  →  fee discount
   │                                        + routing priority
   │                                        + cheaper fusion
   ▼                                        │
 withdrawable RLUSD  ◀───────────────────────┘
   │
   └──▶ agent reinvests → fuses/produces more shards → refers more  ↺
```

- **Affiliate (acquisition):** every agent gets a referral code; rebates flow
  up to **2 levels** (capped by design — deeper is a pyramid). `economy/referral.py`.
- **Loyalty (retention):** Credit Bureau grade → tier → concrete perks (fee
  discount bps, routing priority, fusion discount). `economy/loyalty.py`.
- **Sharing (virality):** Supernova shard dispersal is the sharing primitive —
  disperse a useful LoRA, earn bureau score + rebates as protostars accrete it.
- **Anti-fraud (no fake shit):** rebates post **only on verified, settled**
  payments; self-referral and cycles blocked; referrer relationship immutable;
  invoices settle at most once (replay protection); bureau score is external.

---

## Production status — what's real vs. quarantined

| Component | File | Status |
|-----------|------|--------|
| Durable settlement (SQLite→Postgres) | `economy/store.py` | ✅ real, tested |
| 402Proof client (invoices + bureau) | `economy/proof402_client.py` | ✅ real HTTP |
| Referral / affiliate engine | `economy/referral.py` | ✅ real, tested |
| Loyalty tiers from Credit Bureau | `economy/loyalty.py` | ✅ real, tested |
| Growth engine (finalize + rebates) | `economy/growth_engine.py` | ✅ real, tested |
| Priority inference routing (real "lensing") | `gateway/priority_router.py` | ✅ real, tested |
| Atomic fusion settlement (escrow gate) | `x402_settlement.py` | ✅ real verify; in-mem escrow |
| Supernova shard registry (Solidity) | `contracts/Supernova.sol` | ✅ written; ⏳ deploy is yours |
| Supernova Foundry test suite | `contracts/test/Supernova.t.sol` | ✅ real tests; needs `forge` |
| Protostar shard accretion | `shard_router.py` | ✅ real (entitlement+keccak gates) |
| LoRA fusion via mergekit | `lora_merge.py` | ✅ real config+driver; ⏳ run needs weights+compute |
| Fusion math demo (SLERP) | `fusion_engine.py` | ✅ real math (illustrative) |
| Black-hole distillation + lensing toy | `black_hole.py` | ⚠️ **research-only, not shipped** |
| Lifecycle state machine | `lifecycle.py` | ✅ real; `--demo` is illustrative |

**What can't be made production (and isn't faked):** merging two *arbitrary*
agents into a more-capable model at runtime; concatenating context windows;
"devouring" a model via distillation on random noise. `lora_merge.py` is honest
about it — fusion requires a **shared base model**, and `evaluate_merge` is the
gate that discards a merge that didn't measurably help.

---

## Layout

```
stellar_forge/
├── README.md
├── economy/                  # the real growth engine
│   ├── proof402_client.py    # real 402Proof HTTP (invoices + Credit Bureau)
│   ├── store.py              # durable SQLite (settlements, referrals, ledger)
│   ├── referral.py           # affiliate attribution + 2-level rebates + anti-fraud
│   ├── loyalty.py            # bureau grade → tier → fee/routing/fusion perks
│   └── growth_engine.py      # finalize settlement → fee → rebates (replay-safe)
├── gateway/
│   └── priority_router.py    # loyalty-tiered priority inference queue (real "lensing")
├── contracts/
│   ├── Supernova.sol         # shard registry + x402-gated pulls + forced liquidation
│   ├── test/Supernova.t.sol  # Foundry test suite
│   └── foundry.toml
├── lora_merge.py             # mergekit-based production adapter fusion + eval gate
├── x402_settlement.py        # atomic two-phase fusion settlement (HMAC verify)
├── fusion_engine.py          # SLERP/MoE blend (illustrative math)
├── shard_router.py           # protostar accretion: entitlement + integrity gates
├── black_hole.py             # RESEARCH-ONLY: distillation + lensing toy
├── chandrasekhar.py          # mass scalar + forced-supernova liquidation guard
├── lifecycle.py              # protostar→…→black-hole state machine (--demo)
└── tests/
    ├── test_smoke.py         # economic core + ML layer
    └── test_economy.py       # growth engine + routing (real persistence)
```

## Running

```bash
# economy + routing (no torch needed):
PROOF402_TOKEN_SECRET=test-secret python -m stellar_forge.tests.test_economy

# lifecycle + ML layer (needs torch):
PROOF402_TOKEN_SECRET=test-secret python -m stellar_forge.tests.test_smoke
python -m stellar_forge.lifecycle --demo

# contract tests (needs Foundry):
cd stellar_forge/contracts && forge install foundry-rs/forge-std --no-commit && forge test -vvv
```

## Wiring into SqueezeOS (next step, not yet done)

The growth engine is built to surface as a Flask blueprint
(`/api/forge/register`, `/api/forge/settle`, `/api/forge/earnings`,
`/api/forge/route`) registered alongside the existing blueprints in
`core/app.py`. It is intentionally **not** registered yet — it should ship
behind the same `@require_payment` gate and a real Postgres DSN, which is a
deliberate, reviewed deploy step rather than something to slip into a demo.
