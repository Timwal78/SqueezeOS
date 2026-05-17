# Discord Drop Templates — @relay/mcp-paywall

Ready-to-paste messages for MCP and Web3 developer communities.
Keep the code blocks intact — Discord renders them correctly.

---

## Drop 1: MCP Developer Discord — #general or #showcase

> **Want to earn RLUSD every time an AI agent calls your MCP tool?**
>
> I just shipped `@relay/mcp-paywall` — it adds pay-per-call micropayments to any MCP tool server in about 3 lines:
>
> ```typescript
> server.tool(
>   "fetch-prices",
>   "Proprietary price data",
>   paywallSchema({ symbol: z.string() }),
>   paywall(
>     { priceRlusd: 0.10, recipient: "rYourXRPLAddress", network: "xrpl_mainnet" },
>     async ({ symbol }) => ({ content: [{ type: "text", text: await getPrices(symbol) }] })
>   )
> );
> ```
>
> - Agents without a payment proof get a structured 402 challenge they can auto-pay
> - Verification is fully local — no Relay API call required
> - Zero custody: your seed never leaves memory, hard spend cap enforced before signing
>
> ```bash
> npm i @relay/mcp-paywall
> ```
>
> Follows the x402 protocol adapted for XRPL + RLUSD. Drop me questions here or open an issue on GitHub.
> → https://github.com/timwal78/squeezeos/tree/claude/relay-agent-commerce-BYvie/relay/mcp-paywall

---

## Drop 2: AI Agents Discord / AgentHotspot — #tools or #infrastructure

> **Your agent can now pay MCP tools autonomously — no human approval, hard spend cap.**
>
> `agentWallet()` in `@relay/mcp-paywall` intercepts 402 responses from paywall-gated tools, signs an XRPL RLUSD payment, and retries — all in one call:
>
> ```typescript
> const wallet = agentWallet({
>   seed: process.env.AGENT_SEED!,
>   network: "xrpl_mainnet",
>   maxSpendPerCallRlusd: 1.0,   // never pays more than $1 per tool call
> });
>
> const result = await wallet.callWithPayment(
>   (name, args) => mcp.callTool({ name, arguments: args }),
>   "fetch-prices",
>   { symbol: "BTC" }
> );
> ```
>
> `maxSpendPerCallRlusd` is the key safety lever — if the server's invoice exceeds it, the call throws before any signing happens. No renegotiation, no surprises.
>
> The full loop: call → 402 challenge → verify price ≤ cap → sign XRPL tx → retry with proof → result.
>
> ```bash
> npm i @relay/mcp-paywall
> ```
>
> Repo: https://github.com/timwal78/squeezeos/tree/claude/relay-agent-commerce-BYvie/relay/mcp-paywall

---

## Drop 3: XRPL Builder Discord / XAO DAO — #builders or #projects

> **GENIUS Act compliance + XRPL + MCP tool monetisation — first package out the door.**
>
> `@relay/mcp-paywall` uses RLUSD (Ripple's regulated USD stablecoin, GENIUS Act aligned) for AI agent micropayments over the x402 protocol on XRPL.
>
> Why this matters for XAO DAO / XRPL builders:
>
> - RLUSD is the regulated stablecoin rails — not a speculative token
> - XRPL settles in ~3 seconds for fractions of a cent in fees
> - MCP is the protocol that every major AI agent framework (Claude, OpenAI Agents, LangChain) is adopting for tool use
> - First-mover: no other npm package gates MCP tools behind x402 on XRPL today
>
> If you're building on XRPL and want to monetise AI agent traffic, this is the missing piece. Would love to discuss XAO DAO grant eligibility — the use case fits squarely in "XRPL ecosystem tooling."
>
> ```bash
> npm i @relay/mcp-paywall
> ```
>
> Repo + full docs: https://github.com/timwal78/squeezeos/tree/claude/relay-agent-commerce-BYvie/relay/mcp-paywall

---

## Drop 4: Crypto Twitter / DeFi Discord — #alpha or #dev

> **x402 on XRPL is live.**
>
> ```
> Agent calls MCP tool
>        ↓
> Server: 402 Payment Required
>   invoice: { priceRlusd: 0.10, recipient: rXxx..., expiresAt }
>        ↓
> Agent: verify price ≤ cap → sign XRPL RLUSD tx → attach proof
>        ↓
> Server: verify on-chain → execute → return result
>        ↓
> Agent gets data. Server gets paid. No intermediary.
> ```
>
> One npm package. No payment infra. RLUSD.
>
> ```bash
> npm i @relay/mcp-paywall
> ```
>
> → https://github.com/timwal78/squeezeos/tree/claude/relay-agent-commerce-BYvie/relay/mcp-paywall
