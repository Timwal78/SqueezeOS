# @relay/mcp-paywall

> Add pay-per-call RLUSD micropayments to any MCP tool server in one line of code.

[![npm](https://img.shields.io/npm/v/@relay/mcp-paywall)](https://www.npmjs.com/package/@relay/mcp-paywall)
[![license](https://img.shields.io/npm/l/@relay/mcp-paywall)](./LICENSE)
[![node](https://img.shields.io/node/v/@relay/mcp-paywall)](https://nodejs.org)

---

## Install

```bash
npm i @relay/mcp-paywall
```

Requires Node >= 22. Peer deps: `@modelcontextprotocol/sdk >= 1.0.0`, `zod >= 3.0.0`.

---

## Server: Gate any tool behind payment

Wrap your existing MCP tool handler with `paywall()`. That's it. No payment infra to run.

```typescript
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { paywall, paywallSchema } from "@relay/mcp-paywall";
import { z } from "zod";

const server = new McpServer({ name: "my-data-server", version: "1.0.0" });

server.tool(
  "fetch-prices",
  "Fetches proprietary price data",
  paywallSchema({ symbol: z.string() }),
  paywall(
    {
      priceRlusd: 0.10,          // $0.10 RLUSD per call
      recipient: "rYourXRPLAddress",
      network: "xrpl_mainnet",
    },
    async ({ symbol }) => ({
      content: [{ type: "text", text: JSON.stringify(await getPrices(symbol)) }],
    })
  )
);
```

- `paywallSchema(shape)` — extends your Zod shape with the optional `_relay_payment` field so MCP lets the proof through
- `paywall(config, handler)` — returns a drop-in replacement handler that enforces payment before execution
- Agents without a payment proof receive a structured 402 challenge they can parse and auto-pay

---

## Agent: Auto-pay on 402

On the client side, `agentWallet()` intercepts 402 responses, signs an XRPL payment, and retries — transparently.

```typescript
import { agentWallet } from "@relay/mcp-paywall";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";

const mcp = new Client({ name: "my-agent", version: "1.0.0" });
// ... connect mcp to your transport

const wallet = agentWallet({
  seed: process.env.AGENT_SEED!,      // XRPL wallet seed — held in memory only
  network: "xrpl_mainnet",
  maxSpendPerCallRlusd: 1.0,          // hard cap — never pays more than $1 per call
});

// Transparent auto-pay: call → 402 → sign → retry → result
const result = await wallet.callWithPayment(
  (name, args) => mcp.callTool({ name, arguments: args }),
  "fetch-prices",
  { symbol: "BTC" }
);

console.log(result.content[0].text);
```

The agent never pays more than `maxSpendPerCallRlusd`. If the server asks for more, the call throws before signing.

---

## How it works

The 402 handshake follows the [x402 protocol](https://x402.org) adapted for XRPL:

- **Challenge** — Server returns `{ error: "PAYMENT_REQUIRED", code: 402, invoice: { priceRlusd, recipient, endpointId, expiresAt } }` when no payment proof is present
- **Sign** — Agent wallet builds and signs an XRPL RLUSD Payment transaction targeting the exact recipient and amount, encodes it as a base64 proof envelope
- **Verify & Execute** — Server decodes the proof, checks amount, recipient, expiry, and anti-replay uniqueness, then executes the real handler if valid

All verification happens locally on the server — no Relay API call required for the basic flow.

---

## Zero-custody guarantees

- **Seed never leaves memory** — `agentWallet()` derives the XRPL address at construction time; the seed string is accessed only at signing time and never stored
- **Seed is never logged or serialised** — not in error messages, not in network requests
- **Hard spend cap** — `maxSpendPerCallRlusd` is enforced before any signing; mismatched invoices are rejected, not renegotiated
- **Anti-replay** — each payment proof is single-use; the server's per-instance store rejects duplicate proofs
- **Expiry enforcement** — invoices carry an `expiresAt` Unix timestamp; stale proofs are rejected on both sides
- **No shared state** — each `paywall()` call creates an isolated replay store; multi-tool servers can't cross-contaminate

---

## API

### `paywall(config, handler)`

Wraps an MCP tool handler behind an RLUSD paywall.

```typescript
function paywall<P extends Record<string, unknown>>(
  config: PaywallConfig,
  handler: ToolHandler<Omit<P, "_relay_payment">>
): ToolHandler<P & { _relay_payment?: string }>
```

**`PaywallConfig`**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `priceRlusd` | `number` | yes | Price in RLUSD per tool call |
| `recipient` | `string` | yes | XRPL classic address receiving payment |
| `network` | `"xrpl_mainnet" \| "xrpl_testnet"` | yes | XRPL network |
| `description` | `string` | no | Human-readable description of what is being sold |
| `relayApiUrl` | `string` | no | If set, submits the tx to Relay for on-chain settlement confirmation |
| `gracePeriodMs` | `number` | no | Payment window in ms. Default: `300_000` (5 min) |

---

### `paywallSchema(shape)`

Extends any Zod raw shape with the optional `_relay_payment` field.

```typescript
function paywallSchema<T extends ZodRawShape>(
  shape: T
): T & { _relay_payment: ZodOptional<ZodString> }
```

Use this whenever you declare the tool schema so MCP passes the proof through instead of stripping it as an unknown field.

---

### `agentWallet(config)`

Creates an autonomous XRPL signing wallet for agent-side auto-pay.

```typescript
function agentWallet(config: AgentWalletConfig): AgentWallet
```

**`AgentWalletConfig`**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `seed` | `string` | yes | XRPL wallet seed. Held in memory only — never logged or transmitted |
| `network` | `"xrpl_mainnet" \| "xrpl_testnet"` | yes | XRPL network |
| `maxSpendPerCallRlusd` | `number` | yes | Hard cap per call — agent refuses to pay more than this |
| `relayApiUrl` | `string` | no | Relay API base URL for server reputation checks before paying |
| `minServerReputationScore` | `number` | no | Reject servers whose on-chain reputation is below this score |

**`AgentWallet`**

```typescript
interface AgentWallet {
  readonly address: string;  // XRPL classic address of the agent

  callWithPayment(
    callTool: (name: string, args: Record<string, unknown>) => Promise<CallToolResult>,
    toolName: string,
    toolArgs: Record<string, unknown>
  ): Promise<CallToolResult>;
}
```

---

### Types

```typescript
// The 402 challenge body returned by a paywalled tool
interface PaymentInvoice {
  version: "1.0";
  priceRlusd: number;
  recipient: string;          // XRPL classic address
  network: Network;
  endpointId: string;         // Unique per paywall() registration — prevents cross-tool replays
  expiresAt: number;          // Unix timestamp
}

// Base64-encoded JSON: { scheme, network, payload: signed_tx_blob }
type PaymentProof = string;

type Network = "xrpl_mainnet" | "xrpl_testnet";
```

Additional exports: `is402Response`, `extract402Invoice`, `buildInvoice`, `verifyPayment`, `createInMemoryReplayStore` — see [source](https://github.com/timwal78/squeezeos/tree/main/relay/mcp-paywall/src) for full signatures.

---

## License

MIT — [timwal78/squeezeos](https://github.com/timwal78/squeezeos)
