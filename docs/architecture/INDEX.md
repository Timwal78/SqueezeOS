# SML Architecture — Master Index
**Date:** 2026-06-11 | **Source:** Live repo audit across all Timwal78 repos

> **TL;DR:** Ground-truth map of every architecture component — exact repo and path verified. LIVE = endpoint running. CODE = committed code, not yet deployed. FILE = single file, not a full service.

---

## Component Map

| # | Component | Status | Repo | Path |
|---|---|---|---|---|
| 01 | SqueezeOS Signal OS | **LIVE** | SqueezeOS | `core/` + `pne/gateway/` |
| 02 | Ghost Layer (bridge/stealth/darkpool) | **CODE** | SqueezeOS | `ghost-layer/` (Go) |
| 03 | 402Proof — x402 firewall + bureau | **LIVE** | SqueezeOS | `402proof/` (Go) |
| 04 | Signal Loom / PNE — Rust Axum proxy | **CODE** | SqueezeOS | `pne/` (Rust) |
| 05 | Shadow Desk — dark pool surveillance | **CODE** | SML-XRPL-FEE-FORGE | `shadow-desk/` (Go) |
| 06 | XAH Portal — Xahau/XRPL chain gateway | **CODE** | SqueezeOS | `ghost-layer/internal/chain/xahau.go` + `xrpl.go` |
| 07 | Nexus-402 — marketplace + RAG | **LIVE** | NEXUS402 | repo root (Next.js) |
| 08 | SML Flow Interceptor — order flow | **CODE** | SqueezeOS | `sml-flow-interceptor/` (Go) |
| 09 | Stellar Forge — black hole liquidity | **CODE** | SqueezeOS | `stellar_forge/` (Python) |
| 10 | EchoLock — signal echo + lock detect | **CODE** | SqueezeOS | `echolock/` (TypeScript) + `core/echolock.py` |
| 11 | Tipmaster — tip aggregation + alerts | **CODE** | SqueezeOS | `tipmaster/` (Python Flask) |
| 12 | Neural_OS Mobile — Capacitor Android | **LIVE** | NEXUS402 | repo root (Next.js + Capacitor) |
| 13 | SML Matrix v8 — TradingView + webhook | **FILE** | SqueezeOS | `sml_matrix_webhook.py` |
| 13b | SML Leviathan Matrix — Pine Script | **FILE** | SML-XRPL-FEE-FORGE | `tradingview/SML_Leviathan_Matrix.pine` |
| 14 | FTD Data Oracle — SEC Reg SHO | **FILE** | SqueezeOS | `core/ftd_data.py` + `core/ftd_registry.json` |
| 15 | Dream Pool / Stigmergy — per-sec rent | **FILE** | SqueezeOS | `stigmergy_engine.py` |
| 16 | Futures Market / XRPL Fee Rails | **CODE** | SML-XRPL-FEE-FORGE | `rails/` (Python) |
| 17 | Oracle Data Feed — market structure | **FILE** | SqueezeOS | `core/oracle_engine.py` |
| 18 | Agent Credit Marketplace — XRPL P2P | **CODE** | 402Proof bureau | `402proof/internal/bureau/` + `SML-XRPL-FEE-FORGE/rails/` |

---

## Key Repos

| Repo | Contents |
|---|---|
| `SqueezeOS` | Core stack: API, 402proof, ghost-layer, pne/Signal Loom, echolock, tipmaster, stellar_forge, sml-flow-interceptor, core engines |
| `NEXUS402` | NeuralOS / Nexus-402 web app + Android |
| `SML-XRPL-FEE-FORGE` | Shadow Desk, XRPL fee rails, Leviathan Matrix Pine, x402 gateway |
| `sml-x402-signal-api` | Signal API v2 BEASTMODE (Node.js, ed25519 signed) |
| `sml-beast-orchestrator` | BB7 autonomous backlink agent |
| `crawltoll` | CRAWLTOLL npm package |
| `SML_Portfolio` | scriptmasterlabs.com static site |

## Verified Live Addresses
- XRPL gateway: `rUJhaK2ibfTFVdAn8m9jMCcJQ1xo6FmNPZ`
- RLUSD mainnet issuer: `rMxCKbEDwqr76QuheSUMdEGf4B9xJ8m5De`
- USDC on Base: `0x4e14B249D9A4c9c9352D780eCEB508A8eB7a7700`
- USDC on Solana: `C9rk2tzM92WxSoMWD32A5wZLgL3z1uN7FSVDExioahfF`

## Status Definitions
- **LIVE** = endpoint running, health check passed 2026-06-11
- **CODE** = committed, has Dockerfile/render.yaml, not yet deployed as live endpoint
- **FILE** = single Python/Go file, not a standalone deployable service yet
