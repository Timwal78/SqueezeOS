# 15 — Dream Pool / Stigmergy

**Status:** 🟡 Beta · **Source:** `stigmergy_engine.py`, `stigmergy_server.py`, `stigmergy_render.yaml`

## Overview
Dream Pool (Stigmergy Engine) implements per-second, bureau-discounted compute/data "rent" — a stigmergic pricing model where access cost decreases dynamically based on aggregate agent demand and the requesting agent's 402Proof bureau score (03).

## Architecture
- `stigmergy_engine.py`: core pricing/allocation logic — per-second rent calculation, discount curve driven by 402Proof bureau data.
- `stigmergy_server.py`: serving layer, deployed via `stigmergy_render.yaml` on Render.
- "Dream Pool" naming reflects the shared-resource pool model: agents draw from a shared compute/data pool, paying only for actual per-second usage at their bureau-adjusted rate.

## Agent & Human Access
- Agent-primary: designed for autonomous agents running long sessions where per-second billing is more efficient than per-call x402.
- Settlement via 402Proof RLUSD rail, same bureau (03) used for discount-curve eligibility.

## Status & Roadmap
- [x] Core pricing engine + server deployed
- [ ] Public per-second rate card published (tied to bureau tiers)
- [ ] Integration test against live 402Proof bureau scoring
