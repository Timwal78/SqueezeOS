# 01 — SqueezeOS Signal OS

**Status:** ✅ Live · **Source:** `/core`, `/indicators`, `/pine`

## Overview
SqueezeOS is the institutional-grade AI trading intelligence platform at the center of the ecosystem. It aggregates squeeze detection, cycle/harmonic analysis, institutional order-flow signals, and manipulation detection into a single signal layer consumed by humans (dashboard, alerts) and AI agents (MCP, x402).

## Architecture
- **Engines** (`/core`): convergence, harmonic matrix, Gann macro, parabolic, temporal mirror, Grid 369, oracle, EchoLock, RDT — each a self-contained scoring module feeding the composite signal.
- **Indicators** (`/indicators`, `/pine`): 50+ Pine Script v6 institutional indicators (squeeze, cycle, flow, manipulation detection) published under the ScriptMasterLabs brand.
- **Pipeline:** market data ingestion → engine scoring → composite/regime classification → alert + MCP/x402 distribution.

## Agent & Human Access
- **MCP:** `https://squeezeos-api.onrender.com/mcp` — 33 tools, JSON-RPC 2.0.
- **Free demo:** `curl https://squeezeos-api.onrender.com/api/demo/council`
- **Agent guide:** `https://squeezeos-api.onrender.com/llms.txt`
- **x402:** 8 paid routes, payment-gated via 402Proof, settled in RLUSD (XRPL).
- **Human:** T.I.R. (Traders Intelligence Report) Substack — free composite score + regime summary, paid full report ($9.99/mo).

## Endpoints (summary)
| Tier | Access | Content |
|---|---|---|
| Free | `agents.json`, `llms.txt`, demo route | Composite score + regime label |
| Paid (x402) | 8 routes via 402Proof | Full engine breakdown, mandatory-ticker scans, signal tiers |

## Mandatory Tickers
Composite scans run against the core mandatory watchlist (AMC, GME + extended universe) on 4H/Daily timeframes, avoiding PDT-restricted intraday churn.

## Status & Roadmap
- [x] Core engines live, MCP server deployed
- [x] x402 payment gating via 402Proof
- [ ] Expand signal-tier granularity (Free / Pro / Institutional)
- [ ] Add streaming (SSE) tier for real-time composite updates
