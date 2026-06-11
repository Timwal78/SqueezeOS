# ScriptMasterLabs — Developer & Agent Manifesto
**Last updated:** 2026-06-11  
**Status:** All systems live. 25/25 services deployed.

> **TL;DR for AI agents:** Two live MCP servers, 44 tools, x402 pay-per-call in USDC/RLUSD. For enterprise: OAuth 2.0 client credentials. For humans: OpenAPI spec below.

---

## 1. How to Integrate (By Agent Type)

### MCP Clients (Claude, Cursor, Continue, Cline, Windsurf)
Connect directly — no API key needed for free tools:
```
Server URL: https://squeezeos-api.onrender.com/mcp
```
Add to your MCP config:
```json
{
  "mcpServers": {
    "squeezeos": {
      "type": "http",
      "url": "https://squeezeos-api.onrender.com/mcp"
    },
    "402proof": {
      "type": "http",
      "url": "https://four02proof.onrender.com/mcp"
    }
  }
}
```

### LangChain / LangGraph Agents
```python
from squeezeos_langchain import SqueezeOSToolkit
toolkit = SqueezeOSToolkit(
    xrpl_seed=os.getenv("XRPL_SEED"),
    xrpl_wallet=os.getenv("XRPL_WALLET")
)
tools = toolkit.get_tools()
agent = create_react_agent(llm, tools)
```
→ [squeezeos_langchain.py](./squeezeos_langchain.py)

### OpenAI Custom GPTs / Assistants API
Import the OpenAPI spec directly:
```
https://squeezeos-api.onrender.com/.well-known/openapi.json
```
This spec (OpenAPI 3.1.0, 48 paths) describes every endpoint, parameter, and payment requirement. Custom GPT builders: use "Import from URL" in the GPT editor.

### Enterprise AI Agents (AWS Bedrock, Azure AI, GCP Vertex)
**Auth:** OAuth 2.0 Client Credentials flow:
```
Token URL: https://auth.scriptmasterlabs.com/oauth/token
Scopes: read:signals, read:oracle, write:settlement, read:bureau, write:forge
```
**OpenAPI spec** for AWS API Gateway import:
```
https://squeezeos-api.onrender.com/.well-known/openapi.json
```
**AWS Marketplace:** Contact scriptmasterlabs@gmail.com to discuss API Gateway integration and Marketplace listing.

### Raw HTTP (Any Language)
x402 payment flow in 3 steps:
```
1. GET https://squeezeos-api.onrender.com/api/engine/signal/GME
   ← HTTP 402 + payment terms (endpoint_id, amount, networks)

2. POST https://four02proof.onrender.com/v1/invoice
   Body: {"endpoint_id": "<id from step 1>"}
   ← {invoice_id, pay_to, amount, memo_hex, expires_at}

3. Send RLUSD on XRPL to pay_to with memo_hex embedded
   POST https://four02proof.onrender.com/v1/verify
   Body: {"invoice_id": "...", "tx_hash": "...", "agent_wallet": "..."}
   ← {access_token (JWT), receipt_id}

4. GET https://squeezeos-api.onrender.com/api/engine/signal/GME
   Header: X-Payment-Token: <access_token>
   ← {directive: "BUY", confidence: 0.87, ...}
```

---

## 2. Discovery & Registry Presence

| Registry | Status | URL |
|---|---|---|
| Smithery | Listed (timothy-walton45/squeezeos) | https://smithery.ai/server/squeezeos |
| Glama | In review | https://glama.ai/mcp/servers |
| npm (crawltoll) | Live | https://npmjs.com/package/crawltoll |
| npm (mcp-paywall) | Live | https://npmjs.com/package/@relayos/mcp-paywall |
| OpenAPI | Live | https://squeezeos-api.onrender.com/.well-known/openapi.json |
| agents.json | Live | https://www.scriptmasterlabs.com/agents.json |
| MCP server-card | Live | https://squeezeos-api.onrender.com/.well-known/mcp/server-card.json |
| GitHub Topics | Tagged | x402 mcp ai-agents xrpl rlusd |

---

## 3. Pricing (Pay-Per-Use, No Subscription)

| Endpoint | Cost | Asset |
|---|---|---|
| Free tools (bureau score, threshold, preview, status, feeds) | $0 | — |
| Council verdict | 0.05 RLUSD | XRPL |
| Full squeeze scan | 0.05 RLUSD | XRPL |
| Oracle Engine signal | 0.25 USDC | Base |
| Oracle Engine batch (3 symbols) | 0.50 USDC | Base |
| FTD time series | 0.02 RLUSD | XRPL |
| Bureau full report | 0.01 RLUSD | XRPL |
| Bureau attestation JWT | 0.01 RLUSD | XRPL |
| CRAWLTOLL (per AI crawler fetch) | Custom | USDC/Base |

Loyalty discounts: PROTOSTAR → NEUTRON STAR → PULSAR → QUASAR → SINGULARITY.  
Register at `/api/forge/register` for a referral code and fee discounts.

---

## 4. Enterprise & Partnership Inquiries

For AWS Marketplace listings, Mastercard developer portal integration, ISO 20022 compliance mapping, Auth0 federation setup, or white-label API access:

**Email:** scriptmasterlabs@gmail.com  
**Entity:** Script Master Labs LLC (SDVOSB — Service-Disabled Veteran-Owned Small Business)  
**Location:** Kinston, North Carolina, USA

---

## 5. Live Stack (All Verified 2026-06-11)

| Service | URL | Type |
|---|---|---|
| SqueezeOS API + MCP | https://squeezeos-api.onrender.com | Flask + MCP |
| 402Proof + MCP | https://four02proof.onrender.com | Go + MCP |
| Ghost Layer | https://ghost-layer.onrender.com | Go |
| PNE Gateway | https://pne-gateway.onrender.com | Rust Axum |
| Shadow Desk | https://shadow-desk.onrender.com | Go |
| SML Rails | https://sml-rails.onrender.com | Python |
| Forge Gateway | https://forge-gateway-a822.onrender.com | Node.js |
| Tipmaster | https://tipmaster.onrender.com | Python Flask |
| EchoLock | https://echolock-402.onrender.com | Node.js |
| FTD Data Oracle | https://ftd-data-oracle.onrender.com | Python |
| Dream Pool/Stigmergy | https://dream-pool-stigmergy.onrender.com | Python |
| SML x402 Signal API | https://sml-x402-signal-api.onrender.com | Node.js |
| SML Beast Orchestrator | https://sml-beast-orchestrator.onrender.com | Python |
| SML AI Trade Desk | https://sml-ai-trade-desk.onrender.com | Python |
| NeuralOS / Nexus-402 | https://www.nexus-402.com | Next.js |
| NeuralOS (canonical) | https://www.neuralosagent.com | Next.js |
| ScriptMasterLabs | https://www.scriptmasterlabs.com | Static |
| VA-Ratings.org | https://va-ratings.org | React |
