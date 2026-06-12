# 05 — Shadow Desk

**Status:** 🟡 Beta · **Source:** `core/shadow_ingestion.py`, `core/counsel_agent.py`

## Overview
Shadow Desk is the dark-pool / off-exchange surveillance layer. It ingests dark pool print data, FTD (Fail-to-Deliver) registry data, and SEC Reg SHO feeds to surface institutional positioning that doesn't show up on lit-exchange tape.

## Architecture
- **Ingestion** (`shadow_ingestion.py`): pulls and normalizes dark-pool / off-exchange print data on a scheduled basis.
- **Counsel Agent** (`counsel_agent.py`): the "Council" reasoning layer — synthesizes Shadow Desk data with core engine signals into a narrative assessment (referenced in SqueezeOS demo route as `/api/demo/council`).
- Feeds directly into the SqueezeOS composite score and the FTD Data Oracle (14).

## Agent & Human Access
Currently internal — output surfaces through the SqueezeOS composite signal and Council demo endpoint. Standalone x402 endpoint planned.

## Status & Roadmap
- [x] Ingestion pipeline + Council synthesis live, feeding SqueezeOS composite
- [ ] Standalone Shadow Desk x402 endpoint (raw dark-pool print access)
- [ ] Historical dark-pool archive / backtest interface
