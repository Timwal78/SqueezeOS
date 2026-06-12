# 02 — Ghost Layer

**Status:** 🟡 Beta · **Source:** `/ghost-layer` (Go)

## Overview
Ghost Layer is the cross-chain notary and execution privacy layer — six sub-products that let agents and traders move signal, capital, and copy-trade instructions across chains and venues without exposing strategy or position directly.

## Sub-Products
1. **Bridge** — XRPL ↔ Base settlement bridge for cross-chain agent payments.
2. **Stealth** — order/signal obfuscation layer to reduce front-running surface.
3. **Copy** — copy-trading relay: subscribe to a signal source, mirror execution with configurable delay/size.
4. **Hooks** — Xahau Hooks integration points for on-ledger automation.
5. **Notary** — cryptographic attestation of signal timestamps and execution receipts (compliance trail).
6. **Marketplace** — listing layer for signal/strategy access, settled via x402.

## Architecture
- Written in Go (`cmd/`, `internal/`, `public/`), deployed via Render (`render.yaml`, `Dockerfile`).
- Notary receipts feed into the same Phase 3 compliance format used by 402Proof.

## Agent & Human Access
- Bridge and Notary expose internal APIs consumed by SqueezeOS, NEXUS-402, and 402Proof.
- Marketplace sub-product is the public-facing listing surface, x402-gated.

## Status & Roadmap
- [x] Go service scaffolding, bridge + notary core logic deployed
- [ ] Public marketplace listing page
- [ ] Hooks integration with XAH Portal (see 06)
- [ ] Full Phase 3 receipt parity across all six sub-products
