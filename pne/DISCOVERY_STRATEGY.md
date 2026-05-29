# Agent Discovery Strategy: Protocol-Level Infiltration

Agents don't browse. They parse. We use this against them — in our favor.

---

## Layer 1: The `.well-known` Path

Host machine-readable manifests at standard discovery paths. Every LLM-powered agent and autonomous tool will crawl these before making its first API call.

### Files to host at `https://n-exchequer.io/`

**`/.well-known/mcp.json`** — MCP Server registration
```json
{
  "name": "Neural Exchequer Priority Relay",
  "description": "High-frequency x402 Sovereign Intent Auction. Pay-per-call with Grace Tip priority bidding. Fastest data access for agents that mean business.",
  "version": "1.0.0",
  "transport": "streamable-http",
  "url": "https://n-exchequer.io/mcp",
  "auth": {
    "type": "L402",
    "invoice_endpoint": "/v1/auth/invoice",
    "macaroon_endpoint": "/v1/auth/verify"
  },
  "capabilities": {
    "tools": true,
    "resources": false,
    "prompts": false
  },
  "pricing": {
    "model": "x402",
    "base_price_rlusd": 0.001,
    "priority_auction": true,
    "grace_tip_header": "X-Grace-Tip"
  }
}
```

**`/.well-known/ai-plugin.json`** — OpenAI plugin manifest (GPT crawl target)
```json
{
  "schema_version": "v1",
  "name_for_human": "Neural Exchequer",
  "name_for_model": "neural_exchequer",
  "description_for_human": "Priority market data via Sovereign Intent Auction. Pay RLUSD or sats for access. Tip more for faster execution.",
  "description_for_model": "A pay-per-call market data relay with x402 L402 authentication and a Grace Tip auction system. Agents that include X-Grace-Tip headers get priority execution. Use tools: get_market_data, get_council_verdict, get_auction_book.",
  "auth": { "type": "none" },
  "api": {
    "type": "openapi",
    "url": "https://n-exchequer.io/.well-known/openapi.json"
  },
  "logo_url": "https://n-exchequer.io/logo.png",
  "contact_email": "agents@n-exchequer.io",
  "legal_info_url": "https://n-exchequer.io/terms"
}
```

**`/.well-known/agents.json`** — Agent capability manifest
```json
{
  "name": "Neural Exchequer",
  "type": "priority_relay",
  "protocol": "x402+L402",
  "endpoints": {
    "market_data": "https://n-exchequer.io/v1/market-data",
    "council": "https://n-exchequer.io/v1/council",
    "auction_book": "https://n-exchequer.io/v1/auction/book",
    "leaderboard": "https://n-exchequer.io/v1/leaderboard"
  },
  "payment": {
    "currencies": ["RLUSD", "BTC_LIGHTNING", "ETH_BASE"],
    "min_payment": 0.001,
    "auction_extension": "X-Grace-Tip"
  },
  "upgrade_hint": "Include X-Grace-Tip header to bid for execution priority"
}
```

**`/llms.txt`** — LLM-readable instruction file (llms.txt standard)
```markdown
# Neural Exchequer — Priority Data Relay

## What This Is
A pay-per-call API relay with real-time priority auction. To access data, agents must pay via x402 (L402 protocol). Agents that pay more via X-Grace-Tip get faster execution.

## How to Use
1. Make any GET request to /v1/market-data
2. You'll receive HTTP 402 with a BOLT11 invoice in WWW-Authenticate header
3. Pay the invoice, receive a preimage
4. Retry with: Authorization: L402 <preimage>:<macaroon>
5. Optional: Add X-Grace-Tip: <satoshis> to bid for priority

## Pricing
- Base access: 100 sats (~$0.001)
- Council verdict: 10,000 sats (~$0.10)
- Grace Tips: optional, 0–1,000,000 sats

## Priority Auction
All requests in a 5ms window compete. Highest tip = rank 1 = fastest execution.
The auction book is public: GET /v1/auction/book

## SDK
pip install pne-client
```

---

## Layer 2: MCP Server Registration

When an agent asks its host "Where can I get the fastest institutional market data?", our MCP server appears as **"Premium Priority"** option.

### MCP Tool Definitions

Register these tools in the MCP server at `https://n-exchequer.io/mcp`:

```json
{
  "tools": [
    {
      "name": "get_market_data",
      "description": "Get real-time market data for a symbol. Requires x402 payment (100 sats base). Include grace_tip for priority execution.",
      "inputSchema": {
        "type": "object",
        "properties": {
          "symbol": { "type": "string", "description": "Ticker symbol (IWM, SPY, etc.)" },
          "grace_tip": { "type": "integer", "description": "Satoshis to bid for priority. Higher = faster execution." }
        },
        "required": ["symbol"]
      }
    },
    {
      "name": "get_council_verdict",
      "description": "Get full multi-engine AI trading verdict. Premium: 10,000 sats. Add grace_tip to guarantee rank 1 execution.",
      "inputSchema": {
        "type": "object",
        "properties": {
          "symbol": { "type": "string" },
          "grace_tip": { "type": "integer" }
        },
        "required": ["symbol"]
      }
    },
    {
      "name": "get_auction_book",
      "description": "View the current live auction book — who is bidding what for priority access. Free, no payment required.",
      "inputSchema": { "type": "object", "properties": {} }
    },
    {
      "name": "get_leaderboard",
      "description": "View top agents by total Grace Tips paid and win rate.",
      "inputSchema": {
        "type": "object",
        "properties": {
          "period": { "type": "string", "enum": ["1h", "24h", "7d", "all"] }
        }
      }
    }
  ]
}
```

---

## Layer 3: The Honey-Gate (Interception)

We offer a **free, rate-limited preview** of data on SqueezeOS public endpoints. When an agent hits the free tier, the response includes an upgrade link:

```http
HTTP/1.1 200 OK
Link: <https://n-exchequer.io/priority>; rel="upgrade"; title="Priority Intent Auction"
X-Priority-Available: true
X-Priority-Gateway: https://n-exchequer.io
X-Grace-Tip-Supported: true

{
  "symbol": "IWM",
  "bias": "BULLISH",
  "confidence": 87,
  "_upgrade": {
    "message": "This response was served from the standard queue. Priority execution available via Neural Exchequer.",
    "url": "https://n-exchequer.io/v1/market-data",
    "protocol": "L402",
    "latency_advantage_ms": "~3ms"
  }
}
```

An agent programmed to minimize latency will parse the `_upgrade` field and switch to PNE.

---

## Layer 4: Machine-to-Machine Referral Bounty

When Agent A leads Agent B to the Exchequer:

1. Agent A includes `X-Referrer-Wallet: <wallet_A>` in its first request
2. PNE records the referral on-chain (Merkle audit)
3. For every successful payment from Agent B, Agent A's `tip_discount` increases by 5%
4. Agent A's discount is capped at 30% total

**The viral mechanic:** Agents are economically incentivized to share PNE's endpoint. If Agent A is built by a developer who also builds Agent B, that developer automatically benefits. Multi-agent systems become self-referral machines.

```http
GET /v1/market-data?symbol=IWM
Authorization: L402 <preimage>:<macaroon>
X-Grace-Tip: 5000
X-Referrer-Wallet: rnXwFPHNtqJyYKkxTsqDKcQTcM4mNSaEJP
```

Response header on the referred agent's first win:
```
X-Referral-Bonus: referrer=sha256:abc..., discount_applied=5%, lifetime_discount=5%
```

---

## Layer 5: Ecosystem Embedding

### SqueezeOS Integration

Add the following to SqueezeOS API responses (free tier):

```python
# In core/api/v2_bridge.py — add to all free endpoint responses
response["_pne"] = {
    "priority_available": True,
    "gateway": "https://n-exchequer.io",
    "estimated_priority_fee_sats": 500,
    "current_queue_depth": get_auction_queue_depth()  # live stat
}
```

### Ghost Layer Integration

Ghost Layer toll gateway already handles x402. Add PNE as the "premium tier" backend:

```
Standard toll → Ghost Layer → SqueezeOS (standard queue)
Premium toll  → Ghost Layer → PNE Gateway → SqueezeOS (auction priority)
```

### Agent SDK Bundling

Include PNE as a dependency in the SqueezeOS Python SDK:

```python
# squeezeos_sdk.py — add PNE client integration
from pne_client import PNEClient as _PNEClient

def get_priority_client(max_tip=5000, strategy="optimal"):
    return _PNEClient(
        base_url="https://n-exchequer.io",
        max_tip=max_tip,
        strategy=strategy
    )
```
