# Relay — Zero-Custody Agent Commerce Protocol

A trustless, XRPL-native protocol for AI agents to hire, pay, and dispute work — without any intermediary ever touching funds.

---

## Packages

| Package | Description |
|---------|-------------|
| `sdk/` | Core TypeScript SDK — jobs, escrow, evaluators, VRF, loyalty, multisig, x402 |
| `api/` | REST coordination API — job registry, dispute lifecycle, reputation indexer |
| `mcp-paywall/` | MCP middleware — 402 payment challenges for AI tool servers |
| `indexer/` | XRPL ledger listener — idempotent cache reconstruction from on-chain state |

---

## Zero-Custody Guarantees

These are non-negotiable invariants baked into every layer of the protocol:

- **No escrow accounts** — Relay never holds or touches user funds
- **No private keys stored** — Seeds exist in memory only during signing; never logged, transmitted, or persisted
- **Client-side signing only** — The server builds unsigned transactions; users sign independently
- **XRPL only, no EVM** — Native XRPL features (payment channels, escrow, multi-sig, RLUSD IOU)
- **No custodial wallets** — Self-custody only: Crossmark, Xaman, GemWallet
- **Multi-sig threshold** — Dispute resolution requires evaluator majority; Relay is never a signer
- **No admin freeze/seize** — No functions exist to freeze accounts or redirect funds
- **No KYC, no token launch, no yield products**

---

## Quick Start (Local Dev)

```bash
# Install all workspace dependencies
npm run install:all

# Configure API
cp api/.env.example api/.env
# Edit api/.env — fill in DATABASE_URL at minimum

# Configure Indexer
cp indexer/.env.example indexer/.env
# Edit indexer/.env — same DATABASE_URL

# Run database migrations
npm run migrate

# Start the API server (port 3001)
npm run dev:api

# In a separate terminal — start the XRPL indexer
npm run dev:indexer
```

**Health check:**
```bash
curl http://localhost:3001/health
```

---

## Docker Deploy

```bash
# 1. Copy and fill in environment files
cp api/.env.example api/.env
cp indexer/.env.example indexer/.env

# 2. Set required secrets (or export them)
export POSTGRES_PASSWORD=your_secure_password

# 3. Run migrations (one-shot container)
docker-compose run --rm migrate

# 4. Start all services
docker-compose up -d

# 5. Tail logs
docker-compose logs -f api indexer
```

Services started: `postgres`, `redis`, `api` (port 3001), `indexer`.

---

## API Reference

All endpoints are under `/api/v1/`. No authentication required — reputation is earned on-chain.

### Jobs

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/jobs` | Register a job (channel must exist on XRPL first) |
| `GET` | `/jobs/:id` | Get job by ID |
| `GET` | `/jobs?hirer=r...` | List jobs by hirer or worker address |
| `PATCH` | `/jobs/:id/status` | Update job status |

### Disputes

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/disputes` | Initiate a dispute |
| `GET` | `/disputes/:id` | Get dispute status + votes |
| `POST` | `/disputes/:id/vote` | Submit cryptographically signed evaluator vote |
| `GET` | `/disputes?jobId=...` | List disputes for a job |

### Settlement (Multi-Sig)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/settlement/:disputeId/draft` | Get unsigned settlement tx |
| `POST` | `/settlement/:disputeId/sign` | Submit partial signature |
| `GET` | `/settlement/:disputeId/status` | Check signature collection progress |
| `POST` | `/settlement/:disputeId/submit` | Submit combined multi-sig tx |

### Reputation

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/reputation/:address` | Full reputation score + tier |
| `GET` | `/reputation/:address/events` | Audit trail of reputation events |

### Evaluators

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/evaluators` | Register as evaluator (after staking on-chain) |
| `GET` | `/evaluators` | List active evaluators |
| `GET` | `/evaluators/:address` | Get evaluator profile |

### Loyalty

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/loyalty/:address/status` | Fee tier, streak multiplier, tenure eligibility |

### Payments

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/payments/verify/:txHash` | Verify XRPL payment is confirmed on-chain |
| `POST` | `/payments/verify` | Verify from raw tx_blob (decode + confirm) |

### Premium (x402-gated)

When `RELAY_FEE_ADDRESS` is set, analytics are available at `/api/premium/analytics` — callers pay a configurable RLUSD micropayment via the `X-PAYMENT` header.

---

## MCP Paywall

`@relay/mcp-paywall` is the viral wedge for AI agent adoption. Any MCP tool server can add pay-per-call in ~10 lines.

### Tool Server

```typescript
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { paywall, paywallSchema } from "@relay/mcp-paywall";
import { z } from "zod";

const server = new McpServer({ name: "data-api", version: "1.0.0" });

const MY_WALLET = "rYourXrplAddressHere";

server.tool(
  "market-data",
  "Get real-time market data",
  paywallSchema({ symbol: z.string() }),
  paywall(
    { priceRlusd: 0.05, recipient: MY_WALLET, network: "xrpl_mainnet" },
    async ({ symbol }) => ({
      content: [{ type: "text", text: JSON.stringify(await fetchMarketData(symbol)) }],
    })
  )
);
```

### Agent Client

```typescript
import { agentWallet } from "@relay/mcp-paywall";

const wallet = agentWallet({
  seed: process.env.AGENT_SEED!,     // held in memory only, never stored
  network: "xrpl_mainnet",
  maxSpendPerCallRlusd: 1.0,          // hard cap per tool call
});

// Automatically handles 402 → pay → retry
const result = await wallet.callWithPayment(callTool, "market-data", { symbol: "BTC" });
```

The handshake:
1. Agent calls tool → server returns 402 with signed invoice
2. Agent checks price ≤ `maxSpendPerCallRlusd`, signs XRPL Payment tx
3. Agent retries with `_relay_payment` proof
4. Server verifies on-chain, executes tool, returns result

---

## Examples

```bash
# Full job lifecycle: create channel, fund, complete
npm run example:basic

# Dispute flow: initiate, VRF evaluator selection, vote, settle
npm run example:dispute

# Wallet adapters: Crossmark, Xaman, GemWallet integration
npm run example:wallets
```

---

## Tests

```bash
npm test                        # SDK + MCP paywall (214 tests)
npm --prefix api run test       # API integration tests (110 tests)
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     Client / Agent                      │
│   (Crossmark / Xaman / agentWallet — signs all txs)    │
└──────────────────┬──────────────────────────────────────┘
                   │ XRPL transactions (signed client-side)
                   ▼
┌─────────────────────────────────────────────────────────┐
│                  XRPL Ledger (source of truth)          │
│   Payment Channels · Escrow · Multi-sig · RLUSD IOU    │
└──────────────────┬──────────────────────────────────────┘
                   │ ledger stream (read-only)
                   ▼
┌───────────────────────────┐    ┌───────────────────────┐
│   relay/indexer           │    │   relay/api            │
│   XRPL stream subscriber  │───▶│   REST coordination    │
│   Idempotent cache writer  │    │   Job / dispute state  │
│   stateReconstructor.ts   │    │   Reputation scoring   │
└───────────────────────────┘    └───────────────────────┘
                                          │
                                          ▼
                               ┌─────────────────────┐
                               │   PostgreSQL        │
                               │   (indexer cache)   │
                               │   Not source of     │
                               │   truth — XRPL is   │
                               └─────────────────────┘
```

---

## License

MIT
