# 09 — Stellar Forge (Fusion Engine + Black Hole Liquidity Model)

**Live URL:** https://stellar-forge.onrender.com
**Repo path:** `stellar_forge/`
**Language:** Python
**Deploy:** Render (cloud, 24/7)

---

## What It Does
Fusion engine with a black hole liquidity model. Chandrasekhar-limit-inspired position sizing and liquidity collapse detection. Models institutional liquidity as a gravitational system — identifies liquidity black holes where price gets pulled toward large order concentrations.

## Key Files
- `stellar_forge/fusion_engine.py` — core fusion model
- `stellar_forge/black_hole.py` — black hole liquidity model
- `stellar_forge/chandrasekhar.py` — Chandrasekhar-limit position sizing
- `stellar_forge/lifecycle.py` — position lifecycle management
- `stellar_forge/gateway/` — API gateway
- `stellar_forge/economy/` — economic model layer
- `stellar_forge/lora_merge.py` — LoRA model merging for signal fusion

## Links To
- **SqueezeOS [01]** — liquidity intelligence feeds signal quality
- **Ghost Layer [02]** — position sizing feeds stealth trade and copy trade
- **402Proof [03]** — x402 payment gating
