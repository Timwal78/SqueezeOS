# 11 — Tipmaster

**Status:** 🟡 Beta · **Source:** `/tipmaster`, `/tipmaster-setup`

## Overview
Tipmaster aggregates "tips" — discrete signal events from across the ecosystem (Flow Interceptor sweeps, EchoLock confirmations, composite-score regime changes) — and routes them to the correct alert channel (Discord, email, future SMS via Twilio) based on subscriber tier.

## Architecture
- **Aggregation:** subscribes to internal event bus / polling from Flow Interceptor (08), EchoLock (10), and core composite engines.
- **Routing:** tier-based fan-out — free tier gets regime-level alerts, paid tiers get ticker-specific tip alerts.
- **Setup** (`/tipmaster-setup`): onboarding/configuration scripts for new alert channels.

## Agent & Human Access
- Human: Discord alert channels (TradeHawk Pro community), tiered via T.I.R. Substack subscription.
- Agent: planned MCP tool to subscribe a webhook URL for tip events, x402-gated by tier.

## Status & Roadmap
- [x] Aggregation + Discord routing live
- [ ] Tier-based access control tied to 402Proof bureau score
- [ ] Agent webhook subscription via MCP tool
- [ ] Twilio SMS channel for premium tier
