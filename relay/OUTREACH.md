# @relay/mcp-paywall — Go-to-Market Content

Reference copy for community outreach. Adapt tone per platform. Do not post the same message verbatim across channels.

---

## 1. awesome-mcp-servers PR Body

**PR title:** `feat: add @relay/mcp-paywall — x402 RLUSD micropayments for MCP tools`

**Target section:** Add under a new `## Monetization / Payments` heading, or append to an existing payments/finance cluster if one exists.

---

### PR body (markdown):

```markdown
## Add @relay/mcp-paywall

Adds a new entry under a **Monetization** section for the first x402-native payment middleware designed specifically for MCP tool servers.

### Entry

- **[@relay/mcp-paywall](https://www.npmjs.com/package/@relay/mcp-paywall)** — Add pay-per-call RLUSD micropayments to any MCP tool in one line of code. Implements the x402 payment protocol over XRPL. Zero-custody: the agent wallet seed never leaves memory, spend is hard-capped per call, and anti-replay is enforced server-side. No shared payment infra required.

### Why it belongs here

MCP is becoming the standard for agentic tool invocation. As agents begin autonomously calling paid APIs, there's an emerging need for a standard payment layer that:

1. Doesn't require developers to stand up a payment gateway
2. Works natively with AI agent wallets (auto-pay on 402)
3. Is auditable on-chain (XRPL + RLUSD)

@relay/mcp-paywall is the first npm package to fill this gap specifically for the MCP ecosystem.

### Links

- npm: https://www.npmjs.com/package/@relay/mcp-paywall
- Source: https://github.com/timwal78/squeezeos/tree/main/relay/mcp-paywall
- Protocol: x402 (https://x402.org) adapted for XRPL/RLUSD
```

---

## 2. Developer DM — Base L2 / x402 Devs

**Context:** Developers already running x402 payment flows on Base (Coinbase's L2). They know the protocol, not necessarily XRPL.

---

Hey — saw you're running x402 on Base. Quick question: are you getting compliance receipts on those USDC micropayments?

With USDC on Base you're moving money, but you're not generating anything the GENIUS Act or a bank audit would recognize as a payment record. That's going to matter when your agent is making 10k calls/day on behalf of an enterprise customer.

We just shipped `@relay/mcp-paywall` — same x402 handshake you know, but settled in RLUSD on XRPL. Every payment hits the ledger with a full audit trail, GENIUS Act-aligned stablecoin, and Ripple's compliance infrastructure behind it.

10-minute integration if you're already using MCP. Happy to walk you through it — want to jump on a quick call or should I just drop the code example here?

---

## 3. XRPL Discord Drop — AgentHotspot / XRPL Commons

**Context:** XRPL AI builder communities. More casual. Lead with the value gap.

---

If you're giving away your MCP server for free, you're doing it wrong.

Every time an AI agent calls your tool — data lookup, API bridge, compute task — you could be earning RLUSD. Not "set up a Stripe account" earning. On-chain, per-call, sub-cent micropayments that settle in 3 seconds on XRPL.

We just shipped `@relay/mcp-paywall`:

```bash
npm i @relay/mcp-paywall
```

Wrap your existing MCP tool handler in `paywall()`, set a price in RLUSD, and you're done. Agents auto-detect the 402, sign the payment from their XRPL wallet, and retry — no human in the loop.

It's x402 protocol + XRPL + RLUSD. Zero custody, hard spend caps on the agent side, anti-replay on the server side.

XAO DAO has microgrants for XRPL builders — if you're using this to monetize an MCP server, that's exactly the kind of infra project they fund. Worth a look.

Source + docs: https://github.com/timwal78/squeezeos/tree/main/relay/mcp-paywall

---

## 4. X/Twitter Thread — 5 Posts

**Format:** Paste each post in sequence. Do not number them visibly in the actual tweets — use thread replies.

---

**Post 1 — Hook**

You built an MCP tool server. Agents are calling it. You're earning: $0.00.

There's now a fix.

`@relay/mcp-paywall` — pay-per-call RLUSD micropayments for any MCP tool. x402 protocol. XRPL settlement. One wrapper function.

Thread 🧵

---

**Post 2 — Server-side: paywall in 3 lines**

Gate any MCP tool behind payment in 3 lines:

```ts
paywall(
  { priceRlusd: 0.10, recipient: "rYourAddress", network: "xrpl_mainnet" },
  async ({ query }) => ({ content: [{ type: "text", text: yourData(query) }] })
)
```

No payment gateway. No webhooks. No Stripe. Just XRPL.

---

**Post 3 — Agent side: auto-pay**

The agent side is just as clean:

```ts
const wallet = agentWallet({
  seed: process.env.AGENT_SEED,
  network: "xrpl_mainnet",
  maxSpendPerCallRlusd: 1.0,  // hard cap — never pays more
});

const result = await wallet.callWithPayment(callTool, "fetch-prices", { symbol: "BTC" });
```

Agent gets a 402 → signs RLUSD payment → retries → gets data. Fully autonomous. No human approval loop.

---

**Post 4 — Compliance angle**

Why RLUSD on XRPL instead of USDC on Base?

- RLUSD is a GENIUS Act-aligned regulated stablecoin
- Every micropayment is an on-chain transaction with a full audit trail
- Enterprises running AI agents need payment records — not just token transfers
- XRPL settles in ~3 seconds with sub-cent fees

When your agent is making 50k tool calls/month for an enterprise customer, compliance receipts matter.

---

**Post 5 — CTA**

`@relay/mcp-paywall` is MIT, live on npm, and works with any MCP server today.

```bash
npm i @relay/mcp-paywall
```

Docs + source: https://github.com/timwal78/squeezeos/tree/main/relay/mcp-paywall

If you're building paid MCP tools or autonomous agent wallets — we want to hear what you're making. Reply or DM.
