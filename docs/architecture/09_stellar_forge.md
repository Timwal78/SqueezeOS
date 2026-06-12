# 09 — Stellar Forge

**Status:** 🟡 Beta · **Source:** `/stellar_forge`

## Overview
Stellar Forge models liquidity using a "black hole" framework — identifying price levels where liquidity concentration creates a strong gravitational pull on price (support/resistance with unusually high mean-reversion probability), distinct from standard volume-profile analysis.

## Architecture
- Liquidity-density modeling over order book / options open-interest data, producing "event horizon" levels per ticker.
- Designed to complement the Liquidity Sweep Matrix and Chain Pressure Engine (core engines) — Stellar Forge identifies *where* liquidity concentrates, the core engines identify *when* it's swept.
- Output consumable as a layer on SML Matrix v8 (13) charts.

## Agent & Human Access
Currently a Pine Script / internal-model component; standalone API planned for x402 access to "event horizon" level data per ticker.

## Status & Roadmap
- [x] Core liquidity-density model implemented
- [ ] Standalone x402 endpoint: per-ticker event-horizon levels
- [ ] Integration with SML Matrix v8 as an overlay layer
