# 14 — FTD Data Oracle

**Status:** ✅ Live · **Source:** `core/ftd_data.py`, `core/ftd_server.py`, `core/ftd_registry.json`

## Overview
FTD Data Oracle exposes SEC Reg SHO Fails-to-Deliver data through 6 structured endpoints — turning raw SEC FTD files into a queryable, agent-consumable feed used heavily by the AMC/GME analysis community.

## Architecture
- `ftd_data.py`: ingestion + parsing of SEC Reg SHO FTD files into `ftd_registry.json`.
- `ftd_server.py`: serves the 6 endpoints (per-ticker FTD history, threshold-list status, settlement-date breakdowns, aggregate trends, raw lookup, and a summary/composite endpoint).
- Feeds Shadow Desk (05) and the SqueezeOS composite (01) for institutional-pressure scoring.

## Agent & Human Access
- **6 endpoints** — mix of free (basic lookup) and x402-gated (full historical / aggregate trend endpoints) via 402Proof.
- Listed in SqueezeOS's MCP toolset for direct agent querying.

## Status & Roadmap
- [x] 6 endpoints live, registry auto-updating from SEC source data
- [x] Feeds Shadow Desk + composite score
- [ ] Add threshold-list breach alerting via Tipmaster (11)
