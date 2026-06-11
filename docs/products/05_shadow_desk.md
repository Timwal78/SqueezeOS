# 05 — Shadow Desk (Dark Pool Surveillance)

**Live URL:** https://shadow-desk.onrender.com
**Repo path:** `core/` (shadow ingestion engine integrated)
**Deploy:** Render (cloud, 24/7)

---

## What It Does
Institutional dark pool flow monitoring. Tracks hidden liquidity, block prints, internalized flow, and off-exchange institutional accumulation in real time. Feeds dark pool flow intelligence into SqueezeOS signal quality scoring.

Built from the real shadow ingestion latency harness (PR #141). NOT the "predict the squeeze / front-run forced buying" engine — this is legitimate surveillance data: what happened in the dark pool, surfaced as a research tool.

## Endpoints
```
GET /v1/flow/{symbol}     → institutional dark pool flow for a symbol
GET /v1/blocks/live       → live block print feed
```

## Links To
- **SqueezeOS [01]** — dark pool flow enriches signal quality scoring
- **Ghost Layer [02]** — stealth trade execution uses dark pool intelligence
- **402Proof [03]** — x402-gated access

## Note
Shadow ingestion latency harness built and tested (PR #141). Full real-time dark pool data pipeline.
