# 18 — Agent Credit Marketplace

**Status:** 🟡 Beta · **Source:** `credit_manifest.json`, `credit_repair.html`, `credit_sw.js`, 402Proof bureau (03)

## Overview
Agent Credit Marketplace is the capstone of the 402Proof bureau system (03) — an XRPL peer-to-peer escrow marketplace where AI agents with strong bureau scores can extend short-term "credit" (pre-funded escrow) to other agents or services, settled trustlessly on XRPL.

## Architecture
- **Bureau integration**: agent credit scores from `core/bureau_client.py` (03) determine marketplace eligibility and terms.
- **Escrow**: XRPL native escrow primitives — funds locked by a lender-agent, released to a borrower-agent on fulfillment of agreed conditions (verified via 402Proof receipts/notary, 02).
- `credit_manifest.json`: schema/manifest defining credit product terms; `credit_repair.html` + `credit_sw.js`: human-facing credit-status interface and service worker for offline/PWA support.

## Agent & Human Access
- Agent: marketplace listings queryable/payable via x402 — agents browse available credit offers and settle escrow terms programmatically.
- Human: `credit_repair.html` PWA interface for monitoring credit status / bureau score.

## Status & Roadmap
- [x] Bureau scoring + manifest schema defined, PWA interface live
- [ ] Live XRPL escrow contract integration (currently manifest/scoring only)
- [ ] List marketplace on Nexus402 (07) and `agents.json`
