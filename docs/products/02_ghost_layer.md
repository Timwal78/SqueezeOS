# 02 — Ghost Layer

**Live URL:** https://ghost-layer.onrender.com
**Repo path:** `ghost-layer/`
**Language:** Go
**Deploy:** Render (cloud, 24/7)
**MCP endpoint:** https://ghost-layer.onrender.com/mcp

---

## What It Does
The sovereign execution and settlement backbone of the entire stack. Five core capabilities built on top of each other: dual-chain bridge → stealth dark pool trade → copy trade → XAH Hook automation → AI Decision Notary → Agent Credit Marketplace. Every operation that touches money or on-chain state flows through Ghost Layer.

## Sub-Products (all in this one service)

### A — Dual-Chain Bridge (XRPL RLUSD ↔ Base USDC)
```
POST /v1/bridge/execute
```
- XRPL path: secp256k1 signature, sub-5s finality
- Base path: EIP-3009 gasless USDC permit
- Returns: receipt, transparent fee (basis points), agent tier, net delivered
- SSE: `BRIDGE_SETTLED` on ws/metrics

### B — Stealth Trade (Dark Pool)
```
POST /v1/stealth/order   — $0.20 RLUSD
```
- Zero visible market impact
- Privacy level 0–10 (maps to PRIVACY face of Execution Matrix)
- On-chain execution receipt as URIToken on Xahau
- FIX protocol connectivity: `fix://ghost-layer.onrender.com:9000` (FIXT.1.1)
- Built on: `internal/darkpool/` + `internal/fix/`

### C — Copy Trade (Institutional Mirror)
```
POST /v1/copytrade/subscribe   — $0.15 RLUSD
```
- Mirrors institutional wallet moves in real time
- Signal-gated: GOD_MODE or DUAL_GRID_LOCK on 4H or Daily only
- Broker routing: Tradier (cloud) or Robinhood (Windows executor)
- All SqueezeOS safety gates inherited: PDT shield, cooldown, kill switch, daily loss limit
- SSE: `COPY_TRADE_MIRRORED`

### D — XAH Hooks + Execution Matrix
```
GET  /api/cube/payload   — Hook-ready binary payload
POST /api/cube/state     — commit on-chain ($0.05 RLUSD)
GET  /api/cube/state     — last committed state
```
- 6-face × 9-block programmable matrix: LIQUIDITY, PRIVACY, SPEED, POOL, HOOKS, BASE
- Every face rotation after Phase 5 auto-commits as URITokenMint on Xahau (NetworkID=21337)
- Hook parameters encoded as canonical XRPL binary
- SSE: `XAHAU_MINT_CONFIRMED`, `XAHAU_HOOK_ARMED`

### E — Decision Notary
```
POST /v1/notarize
```
- Mints any AI decision as immutable URIToken on Xahau
- Three grades: STANDARD $0.001 / CERTIFIED $0.01 (Ed25519 cert) / SOVEREIGN $0.05
- SSE: `DECISION_NOTARIZED`

### F — Agent Credit Marketplace
```
POST /v1/credit/listing
GET  /v1/credit/listings
POST /v1/credit/quote
POST /v1/credit/escrow/register
POST /v1/credit/escrow/{id}/deliver
POST /v1/credit/escrow/{id}/release
POST /v1/credit/escrow/{id}/cancel
```
- Zero custody — Ghost Layer is escrow fulfiller only
- XRPL-native EscrowCreate/EscrowFinish
- Loyalty-tier gated: sellers set min_buyer_tier

## Key Internal Files
- `internal/chain/xahau.go` — URITokenMint, Hook params, secp256k1 signing
- `internal/chain/xrpl.go` — base XRPL RPC client
- `internal/darkpool/` — order book (book.go, order.go)
- `internal/fix/` — FIX protocol server + encoder
- `internal/x402/` — x402 token layer (HMAC, attestation, notary, catalog)
- `internal/ledger/bridge.go` — bridge execution logic
- `internal/router/bridge.go` — routing + metrics hub
- `internal/toll/` — fee calculation + loyalty
- `internal/credit/marketplace.go` — P2P marketplace
- `internal/cuberouter/router.go` — signal routing

## Loyalty Tier (all products discounted)
BRONZE 0% → SILVER 5% → GOLD 10% → PLATINUM 20% → DIAMOND 30%
Check: `GET /api/agent/{wallet}/stats`

## Links To
- **402Proof [03]** — loyalty tier data, credit bureau score
- **SqueezeOS [01]** — receives GOD MODE execution signals, fires Tradier/Robinhood
- **Xahau mainnet** — URITokenMint (NetworkID=21337)
- **XRPL mainnet** — RLUSD bridge, escrow
- **Base mainnet** — USDC EIP-3009 bridge

## SSE Events
BRIDGE_SETTLED · STEALTH_TRADE_FILLED · COPY_TRADE_MIRRORED · XAHAU_HOOK_ARMED
XAHAU_MINT_CONFIRMED · DECISION_NOTARIZED · CREDIT_DELIVERED · CREDIT_RELEASED · CUBE_STATE_COMMITTED
