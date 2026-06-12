# 06 — XAH Portal

**Status:** 🟡 Beta · **Source:** Ghost Layer Hooks (02), `xrpl_verify.py`

## Overview
XAH Portal is the unified chain gateway for Xahau (XAH) — providing a single integration point for Hooks-based on-ledger automation, sitting alongside the existing XRPL verification layer (`xrpl_verify.py`) used by 402Proof.

## Architecture
- Built on top of Ghost Layer's **Hooks** sub-product (02) — Xahau Hooks deployed for on-ledger payment/automation triggers.
- Shares verification primitives with `xrpl_verify.py` (XRPL transaction validation used by 402Proof's settlement checks).
- Acts as the routing layer so SqueezeOS, 402Proof, and Ghost Layer can target either XRPL mainline or Xahau without separate integrations.

## Agent & Human Access
Internal gateway today — exposed indirectly via 402Proof's XRPL settlement path. A dedicated `/xah` MCP namespace is planned for direct Hooks interaction by agents.

## Status & Roadmap
- [x] Hooks deployed via Ghost Layer
- [x] Shared XRPL/Xahau verification primitives
- [ ] Dedicated XAH Portal MCP namespace
- [ ] Public docs for Hooks-based automation triggers
