# 08 — SML Flow Interceptor

**Status:** 🟡 Beta · **Source:** `/sml-flow-interceptor`

## Overview
SML Flow Interceptor captures and classifies institutional order-flow signatures (large block prints, sweep patterns, unusual options activity) in near-real-time, feeding both the SqueezeOS composite score and standalone alerting.

## Architecture
- Standalone service polling/streaming order-flow data sources, classifying flow into categories (sweep, block, dark-pool-correlated) using thresholds tuned against the core engines' historical signal set.
- Outputs feed: (a) SqueezeOS composite (01), (b) Discord alert pipeline (`discord_alerts.py`, `discord_payload.py`), (c) Tipmaster (11) for tip-based alert routing.

## Agent & Human Access
- Internal feed to SqueezeOS composite today.
- Discord alert channel for human consumption.
- Standalone x402 endpoint (raw classified flow stream) planned.

## Status & Roadmap
- [x] Flow classification engine operational, feeding composite + Discord
- [ ] Standalone x402 "raw flow" endpoint
- [ ] Historical flow archive for backtesting
