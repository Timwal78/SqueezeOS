# x402 Protocol Implementation for Crypto Agent APIs

In the rapidly evolving landscape of **crypto agent APIs**, traditional SaaS monetization—API keys, monthly subscriptions, and credit card gateways—is fundamentally broken for AI systems. Agents need to execute autonomously, scale infinitely, and pay programmatically without human intervention. 

To solve this, SqueezeOS natively utilizes an **x402 protocol implementation** to provide frictionless, pay-per-call access to the XRP Ledger and Base.

## What is the x402 Protocol?
The x402 protocol is an extension of the HTTP 402 "Payment Required" standard, specifically designed for AI agents and machine-to-machine economies. When an agent requests a premium resource from a **crypto agent API**, the server responds with an x402 payload: a cryptographic invoice and a payment destination.

The agent pays the invoice on-chain (e.g., in XRP or RLUSD) and submits the transaction hash back to the server. The server verifies the payment and issues a cryptographically signed JSON Web Token (JWT) that unlocks the API for a specified duration or quota.

## How SqueezeOS Uses x402
SqueezeOS uses a robust **x402 protocol implementation** (powered by the 402Proof firewall and Ghost Layer routing engine) to gate access to its MCP server. 

### The Flow
1. **Agent Request:** An agent running an LLM initiates a call to a premium SqueezeOS MCP tool (like `cube.mint`).
2. **Quote Generation:** SqueezeOS intercepts the call and issues a Quote via the `/v1/x402/quote` endpoint. This quote includes the exact cost in RLUSD and the Treasury Address.
3. **Autonomous Payment:** The agent, armed with a funded XRP wallet, signs and broadcasts a payment to the Treasury.
4. **Receipt Validation:** The agent takes the resulting `tx_hash` and submits it to the SqueezeOS dispense endpoint.
5. **Execution:** SqueezeOS validates the payment on the XRPL and immediately executes the requested tool.

## Benefits for Crypto Agent APIs
Implementing the x402 standard provides massive advantages for AI infrastructure:
* **No Signups or API Keys:** Agents do not need to register accounts. They arrive, pay, and consume.
* **Granular Pricing:** Resources can be priced dynamically down to the micro-cent.
* **DDoS Protection:** By attaching an economic cost to API execution, the SqueezeOS endpoint is naturally protected against spam and denial-of-service attacks.
* **Sovereignty:** Agents retain full control over their funds until the exact moment of API consumption.

## Getting Started
To see the **x402 protocol implementation** in action, you can test the SqueezeOS API directly via our [Ghost Layer endpoints](https://ghost-layer.onrender.com/v1/x402/catalog), which list the current pricing for all available AI tools.

For a broader guide on integrating these tools into your agentic workflow, see our guide on [Building an AI Trading Agent Framework](/docs/tutorials/building-xrpl-agents.md).
