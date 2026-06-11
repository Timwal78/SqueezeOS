# 04 — Signal Loom / PNE (Predictive Neural Data Feed)

**Live URL:** https://pne-gateway.onrender.com
**Repo path:** `pne/`
**Language:** Rust (Axum)
**Deploy:** Render (cloud, 24/7)

---

## What It Does
Rust Axum gateway that sits in front of SqueezeOS and forwards signals upstream with proper payment headers. Acts as the neural inference proxy layer — enriches requests with prediction context before passing to the signal engines.

## Key Behavior
- Forwards `X-PAYMENT` (x402 Base/USDC), `X-Payment-Token` (RLUSD/XRPL), and `X-Agent-Wallet` headers to upstream SqueezeOS calls
- Pre-x402 the gateway stripped all auth headers causing every paid upstream call to 402-loop — fixed in PR #117

## Endpoints
```
GET /v1/scan             → proxy to SqueezeOS /api/scan (paid, forwards X-PAYMENT)
GET /v1/options          → proxy to SqueezeOS /api/options (paid)
POST /v1/council         → proxy to SqueezeOS /api/council (paid)
GET /v1/signal/{symbol}  → live predictive signal for a symbol
GET /v1/feed/live        → live feed stream
```

## Links To
- **SqueezeOS [01]** — primary upstream, all paid signals
- **402Proof [03]** — header forwarding ensures payment flows through correctly
