# 17 — Oracle Data Feed

**Status:** ✅ Live · **Source:** `core/oracle_engine.py`, `core/legacy.py`, `core/market_graph.py`

## Overview
Oracle Data Feed combines SEC 8-K filing monitoring with a market-structure Server-Sent Events (SSE) stream — giving agents a real-time feed of material corporate events alongside live market-structure changes (regime shifts, liquidity-level breaches).

## Architecture
- `oracle_engine.py`: core oracle logic — synthesizes 8-K filing data with market-structure state from `market_graph.py`.
- **SSE stream**: persistent connection delivering market-structure updates as they occur (regime changes, EchoLock locks, Stellar Forge level breaches) — lower-latency than polling.
- Routed through Signal Loom / PNE (04) for upstream data normalization.

## Agent & Human Access
- **SSE endpoint**: x402-gated streaming connection (pay-per-session or per-second via Dream Pool model, 15).
- **8-K endpoint**: discrete query per ticker, standard x402 per-call via 402Proof.
- Listed in `agents.json` / SqueezeOS MCP toolset.

## Status & Roadmap
- [x] 8-K monitoring + SSE market-structure stream live
- [x] Routed through PNE for data normalization
- [ ] Per-second Dream Pool billing for SSE sessions (currently flat per-session)
