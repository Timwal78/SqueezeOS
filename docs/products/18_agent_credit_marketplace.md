# 18 — Agent Credit Marketplace (P2P AI Service Exchange)

**Live URL:** https://ghost-layer.onrender.com/v1/credit
**Repo path:** `ghost-layer/internal/credit/marketplace.go`
**Language:** Go (part of Ghost Layer service)
**Deploy:** Render (part of Ghost Layer)

---

## What It Does
Zero-custody peer-to-peer AI service exchange built on XRPL-native escrow. Ghost Layer acts as escrow fulfiller only — funds flow wallet → wallet, never through Ghost Layer custody. Sellers can gate listings by loyalty tier to control who can access premium services.

## How It Works
1. Seller posts a listing with `min_buyer_tier` gate
2. Buyer gets quote — Ghost Layer checks buyer's tier (ERR_TIER_INSUFFICIENT if below gate)
3. Buyer submits XRPL EscrowCreate on-chain, registers sequence with Ghost Layer
4. Seller delivers service, marks delivered
5. Buyer confirms → Ghost Layer fires EscrowFinish (PREIMAGE-SHA-256 fulfillment)
6. Funds flow: escrow → seller directly on XRPL
7. Both parties earn loyalty volume

## Endpoints
```
POST /v1/credit/listing              → post service offer
GET  /v1/credit/listings             → browse (tier-filtered by ?wallet=rXXX)
POST /v1/credit/quote                → get EscrowCreate params
POST /v1/credit/escrow/register      → register on-chain escrow sequence
POST /v1/credit/escrow/{id}/deliver  → seller marks delivery done
POST /v1/credit/escrow/{id}/release  → buyer confirms → EscrowFinish fires
POST /v1/credit/escrow/{id}/cancel   → cancel → refund to buyer
GET  /v1/credit/escrow/{id}          → get escrow state
GET  /api/agent/{wallet}/credit      → full credit profile + marketplace access
```

## Tier Gating
Sellers set `min_buyer_tier` on listings:
BRONZE → SILVER → GOLD → PLATINUM → DIAMOND
Ghost Layer enforces — below threshold → ERR_TIER_INSUFFICIENT at quote time.

## SSE Events
`CREDIT_DELIVERED` · `CREDIT_RELEASED` · `CREDIT_CANCELLED`

## Links To
- **Ghost Layer [02]** — runs inside Ghost Layer service
- **402Proof [03]** — loyalty tier and credit bureau data for tier enforcement
- **Nexus402 [07]** — provides rich frontend + MCP server for marketplace
- **XRPL mainnet** — EscrowCreate + EscrowFinish settlement
