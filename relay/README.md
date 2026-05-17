# Relay — Zero-Custody Agent Commerce Protocol

Relay is an open protocol for AI agents and humans to hire, pay, and dispute work on XRPL — without Relay ever touching funds or private keys.

---

## Architecture

| Package | Purpose |
|---------|---------|
| `sdk` | Core logic: job lifecycle, dispute resolution, evaluator selection, loyalty tiers, VRF, XRPL transaction building |
| `api` | REST coordination layer — job registry, dispute orchestration, reputation, loyalty, settlement notifications |
| `mcp-paywall` | Server-side MCP tool wrapper (`paywall()`) + agent-side autonomous payer (`agentWallet()`) over x402/RLUSD |
| `indexer` | XRPL ledger listener — syncs on-chain payment channel and escrow events into Postgres |

```
┌─────────────┐   REST    ┌─────────────┐   SQL   ┌──────────────┐
│  Agent /    │ ────────► │     api     │ ──────► │   Postgres   │
│  Hirer app  │           │  (port 3001)│         │              │
└─────────────┘           └─────────────┘         └──────────────┘
       │                         ▲                        ▲
       │ MCP                     │ reads                  │ writes
       ▼                         │                        │
┌─────────────┐           ┌─────────────┐         ┌──────────────┐
│ mcp-paywall │           │   indexer   │ ──────► │    XRPL      │
│  (server)   │           │             │ ◄────── │  (mainnet /  │
└─────────────┘           └─────────────┘         │   testnet)   │
                                                   └──────────────┘
```

---

## Zero-Custody Guarantees

- **No escrow.** Funds live in XRPL payment channels controlled by hirer + worker keys only.
- **No private keys.** The Relay API never generates, stores, or signs with any wallet key. Settlement transactions are built unsigned and returned to callers.
- **No EVM.** XRPL only — deterministic finality, native multi-sig, no gas spikes.
- **Client-side signing only.** Agents sign payments locally via `agentWallet()`; evaluators sign dispute outcomes from their own wallets.
- **Anti-replay.** Every `_relay_payment` proof carries a nonce; the paywall verifier rejects reused proofs.
- **Spending caps.** `agentWallet` enforces `maxSpendPerCallRlusd` per call; no unbounded payments.

---

## Quick Start (local dev)

```bash
npm run install:all
cp api/.env.example api/.env   # fill in DATABASE_URL
npm run migrate
npm run dev:api
```

In another terminal:

```bash
npm run dev:indexer
```

The API listens on `http://localhost:3001` by default. Set `XRPL_NETWORK=xrpl_testnet` in `api/.env` to use the XRPL Altnet.

---

## Docker Deploy

```bash
cp api/.env.example api/.env && cp indexer/.env.example indexer/.env
# Fill in DATABASE_URL, XRPL_NETWORK, and any optional values
docker-compose up -d
```

The compose file starts Postgres, the API, and the indexer. Redis is optional — remove the `REDIS_URL` line to run without it (loyalty endpoints fall through to DB on cache miss).

---

## API Reference

All endpoints are under `/api/v1/`.

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/jobs` | Create a job (records channel + signer config) |
| `GET` | `/jobs/:id` | Get job details |
| `PATCH` | `/jobs/:id/status` | Update job status (accept, complete, cancel) |
| `GET` | `/jobs` | List jobs for a hirer or worker address |
| `POST` | `/disputes` | Open a dispute for an active job |
| `GET` | `/disputes/:id` | Get dispute state and current votes |
| `GET` | `/disputes` | List disputes by jobId |
| `POST` | `/disputes/:id/vote` | Submit an evaluator vote (signature verified) |
| `GET` | `/reputation/:address` | Reputation score, tier, attestations, stake |
| `POST` | `/reputation/attest` | Issue a cryptographic attestation (10+ jobs required) |
| `GET` | `/reputation/:address/events` | Paginated reputation event history |
| `GET` | `/evaluators` | List active evaluators |
| `GET` | `/evaluators/:address` | Evaluator profile |
| `POST` | `/evaluators` | Register as an evaluator (min 500 RLUSD stake) |
| `POST` | `/settlement/:disputeId/finalize` | Record confirmed settlement tx hash |
| `GET` | `/loyalty/:address` | Full loyalty profile (participant + evaluator tiers) |
| `GET` | `/loyalty/:address/status` | Cached fee tier, streak multiplier, tenure (≤20 ms) |
| `POST` | `/payments/verify` | Verify an x402 RLUSD payment proof |

---

## MCP Paywall

### Server side — gating a tool behind RLUSD payment

```typescript
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { paywall, paywallSchema } from "@relay/mcp-paywall";
import { z } from "zod";

const server = new McpServer({ name: "my-data-server", version: "1.0.0" });

server.tool(
  "fetch-market-data",
  "Returns proprietary market data for the requested symbol",
  paywallSchema({ symbol: z.string() }),
  paywall(
    {
      priceRlusd: 0.10,
      recipient: "rYourXrplAddress",
      network: "xrpl_testnet",
    },
    async ({ symbol }) => ({
      content: [{ type: "text", text: JSON.stringify(getMarketData(symbol)) }],
    })
  )
);
```

When `_relay_payment` is absent, `paywall()` returns a structured 402 challenge. When a valid RLUSD payment proof is provided, the inner handler executes with `_relay_payment` stripped from the params object.

### Agent side — auto-pay on 402

```typescript
import { agentWallet } from "@relay/mcp-paywall";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";

const wallet = agentWallet({
  seed: process.env.AGENT_SEED!,         // never leaves this process
  network: "xrpl_testnet",
  maxSpendPerCallRlusd: 0.50,            // hard cap per tool call
  // Optional: refuse payment if server reputation score is too low
  relayApiUrl: "https://api.relay.xyz",
  minServerReputationScore: 50,
});

const mcpClient = new Client({ name: "my-agent", version: "1.0.0" }, { capabilities: {} });
// ... connect transport ...

const result = await wallet.callWithPayment(
  (name, args) => mcpClient.callTool({ name, arguments: args }),
  "fetch-market-data",
  { symbol: "BTC/RLUSD" }
);
// result is the tool response — 402 handling is transparent
```

`callWithPayment` calls the tool once without payment, detects the 402 challenge, signs a RLUSD payment on XRPL, and retries automatically. The seed is never serialised or sent over the network.

---

## Examples

```bash
# Basic job flow: create → accept → complete
npm run example:basic

# Full dispute: open → vote (3-of-5) → settle
npm run example:dispute

# Wallet adapter patterns (browser extension, hardware, MPC)
npm run example:wallets
```

---

## License

MIT
