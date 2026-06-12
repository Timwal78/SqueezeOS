# 16 — Futures Market

**Status:** 🔵 Planned

## Overview
Futures Market extends the 402Proof discount-curve model (03) to futures-style settlement fees — bureau-discounted settlement pricing for agents executing repeated futures-related data/strategy queries.

## Architecture (Planned)
- Builds directly on 402Proof's bureau (`core/bureau_client.py`) and discount-curve pricing — same scoring mechanism, applied to a futures-focused endpoint set (futures positioning data, term-structure signals).
- Will sit alongside FTD Data Oracle (14) and Oracle Data Feed (17) as a third structured-data product on the 402Proof rail.

## Agent & Human Access (Planned)
x402-gated endpoints for futures positioning/term-structure data, priced via the existing bureau discount curve — no new payment infrastructure required, only new data endpoints.

## Status & Roadmap
- [ ] Define endpoint set (futures positioning, term structure, COT-style data)
- [ ] Wire into existing 402Proof bureau discount curve
- [ ] Deploy and list in `agents.json`
