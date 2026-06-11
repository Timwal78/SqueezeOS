# 17 — Oracle Data Feed (Regulatory + Market Intelligence)

**Live URL:** https://squeezeos-api.onrender.com/api/oracle
**Repo path:** `core/api/oracle_data_bp.py`
**Language:** Python / Flask
**Deploy:** Render (part of SqueezeOS service)

---

## What It Does
Regulatory and market intelligence oracle feed. Ingests SEC filings (8-K, etc.), market structure data, and other regulatory feeds. Normalizes into time series. Available as per-call x402-gated endpoints and a live SSE stream.

## Endpoints

| Endpoint | Price | Description |
|----------|-------|-------------|
| GET /api/oracle/feeds | free | List all available feeds |
| GET /api/oracle/latest/{feed} | $0.02 USDC | Latest record for a feed (e.g. `sec_8k`) |
| POST /api/oracle/query | $0.02 USDC | Query a feed with filters |
| GET /api/oracle/stream | $0.05 USDC | SSE live stream of oracle events |

## Available Feeds (examples)
- `sec_8k` — SEC 8-K material event filings
- Market structure regulatory data

## Links To
- **SqueezeOS [01]** — runs in same service, enriches signal quality
- **402Proof [03]** — x402 payment gating
- **FTD Data Oracle [14]** — companion regulatory data product (SEC Reg SHO)
- **Signal Loom/PNE [04]** — oracle data forwarded upstream via PNE gateway
