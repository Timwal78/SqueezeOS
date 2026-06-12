# 04 — Signal Loom / PNE

**Status:** 🟡 Beta · **Source:** `/pne`

## Overview
Signal Loom (PNE — Pine Network Engine) is a Rust/Axum proxy that sits between raw market-data providers and the SqueezeOS engine layer, normalizing and rate-limiting feeds before they hit the scoring pipeline. It exists to keep upstream provider keys server-side while exposing a uniform, agent-consumable interface.

## Architecture
- **Gateway** (`pne/gateway`): Rust/Axum reverse proxy — normalizes provider responses into a single schema.
- **Loom** (`pne/loom`): routing/orchestration layer — directs requests to the correct upstream provider based on symbol/timeframe/cost.
- **SDK** (`pne/sdk`): client bindings for downstream services (SqueezeOS core, Oracle Data Feed).
- Deployable via Railway (`deploy-railway.sh`) or Render (`render.yaml`), containerized via `docker-compose.yml`.

## Agent & Human Access
Internal-facing today — consumed by SqueezeOS core engines and the Oracle Data Feed (17). Public x402-gated endpoint planned per `DISCOVERY_STRATEGY.md`.

## Status & Roadmap
- [x] Rust/Axum proxy + routing layer functional
- [x] Internal SDK consumed by core engines
- [ ] Public x402 endpoint (per `pne/DISCOVERY_STRATEGY.md`)
- [ ] Formal `API_SPEC.md` → OpenAPI generation
