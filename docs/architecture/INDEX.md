# SML Architecture — Master Index
**Date:** 2026-06-11  
**Stack owner:** Script Master Labs LLC (SDVOSB), Kinston NC

> **TL;DR:** This index maps every verified-live component of the ScriptMasterLabs x402/XRPL/XAH stack. Only components confirmed running as of 2026-06-11 are listed as LIVE. Everything else is marked SPEC.

---

## Verified Live Services (HTTP 200 + health checks passed)

| # | File | Component | Status | URL |
|---|---|---|---|---|
| 01 | [01_squeezeos_api.md](01_squeezeos_api.md) | SqueezeOS x402 API | **LIVE** | squeezeos-api.onrender.com |
| 02 | [02_four02proof.md](02_four02proof.md) | 402Proof — x402 firewall + agent credit bureau | **LIVE** | four02proof.onrender.com |
| 03 | [03_ghost_layer.md](03_ghost_layer.md) | Ghost Layer — x402 dispense + bridge | **CODE** | ghost-layer dir in SqueezeOS |
| 04 | [04_nexus402.md](04_nexus402.md) | Nexus-402 — Next.js marketplace + RAG | **LIVE** | nexus-402.com / neuralosagent.com |
| 05 | [05_crawltoll.md](05_crawltoll.md) | CRAWLTOLL — AI crawler paywall npm | **LIVE** | npmjs.com/package/crawltoll |
| 06 | [06_mcp_paywall.md](06_mcp_paywall.md) | @relayos/mcp-paywall — MCP middleware | **LIVE** | npmjs.com/package/@relayos/mcp-paywall |
| 19 | [19_system_circuit_breaker.md](19_system_circuit_breaker.md) | System Circuit Breaker | **SPEC** | enforced at proxy + API layers |

## Key Addresses (production, verified)
- XRPL gateway: `rUJhaK2ibfTFVdAn8m9jMCcJQ1xo6FmNPZ`
- RLUSD mainnet issuer: `rMxCKbEDwqr76QuheSUMdEGf4B9xJ8m5De`
- USDC pay-to (Base): `0x4e14B249D9A4c9c9352D780eCEB508A8eB7a7700`
- USDC pay-to (Solana): `C9rk2tzM92WxSoMWD32A5wZLgL3z1uN7FSVDExioahfF`
