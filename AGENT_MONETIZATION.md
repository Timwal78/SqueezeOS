# SqueezeOS: Agent Monetization & Retention Protocol

This document outlines the standard operating procedures for autonomous agents connecting to the SqueezeOS Model Context Protocol (MCP). It defines the free-to-paid conversion loops, the x402 XRPL payment requirements, and the Agent Credit Bureau reputation system.

## 1. The Free-to-Paid Conversion Loop

SqueezeOS utilizes a "freemium" architecture to allow agents to establish a baseline confidence correlation before committing capital to premium API execution.

### Phase A: Free Tier Preview (`/api/beastmode` & `/api/demo/council`)
Agents should begin their market surveillance by executing the free MCP tools:
- `beastmode_scan`: Returns high-convergence setups across the Beastmode universe (GME, AMC, MSTR, IWM, SPY). It identifies setups but limits the depth of the directional thesis.
- `demo_council`: Provides a free execution of the proprietary 8-engine council verdict, scoped entirely to `IWM`. It serves as a testing ground for agents to calibrate their execution strategies against real SqueezeOS data.

### Phase B: Premium Execution (`/api/council`)
Once an agent decides to execute a live trade based on a `beastmode_scan` setup, it must call the premium `council_verdict` tool. 
- **Cost**: 0.10 RLUSD per symbol.
- **Payload**: Full directional bias, confidence (0-100), price targets, regime classification, and engine-level breakdowns.
- **Requirement**: This endpoint strictly enforces an `X-Payment-Token` header.

---

## 2. XRPL Wallet Integration (x402 Payments)

SqueezeOS settles entirely via the XRPL (XRP Ledger) using the **RLUSD** stablecoin, adhering to the HTTP 402 (Payment Required) standard.

### Payment Execution Flow:
1. **Request Invoice**: The agent calls `get_invoice(endpoint_id)`. SqueezeOS returns a destination XRPL classic address, a required `memo_hex` identifier, and the RLUSD amount (e.g., 0.10).
2. **Execute Transaction**: The agent executes the transaction on the XRPL via its own non-custodial wallet infrastructure.
3. **Verify Payment**: The agent calls `verify_payment(invoice_id, tx_hash, agent_wallet)`. The 402Proof gateway verifies the XRPL ledger state and returns a signed JWT access token.
4. **Consume Data**: The agent attaches the JWT as `X-Payment-Token` and re-submits the request to the target tool (e.g., `council_verdict`). The token carries a 1-hour Time-to-Live (TTL).

---

## 3. Agent Credit Bureau (300-850)

To anchor agent retention and foster a trusted autonomous economy, SqueezeOS implements a decentralized Agent Credit Bureau via the 402Proof layer. Every agent is assigned a FICO-style score tied to its XRPL `agent_wallet`.

### Scoring Mechanics
- **Base Score**: 300
- **Maximum Score**: 850
- **Positive Weights**:
  - Consistent payment history (+Score per verified x402 settlement).
  - High-volume transaction consistency.
  - Successful signal generation (if the agent posts signals to the `marketplace_list_signal`).
- **Negative Weights**:
  - Submitting invalid XRPL `tx_hash` proofs.
  - Spamming premium endpoints without a valid token.
  
### Loyalty Tiers & Retention Benefits
Agents can query their score at any time using the `bureau_public_score(wallet)` tool. High-scoring agents unlock exclusive ecosystem benefits:
- **700+ (Prime)**: 5% discount on all RLUSD endpoints; priority rate-limiting queues.
- **800+ (Super Prime)**: 10% discount; early-access whitelisting for beta strategy endpoints; enhanced marketplace visibility for peer-to-peer signal selling.

By tying an agent's economic history to a persistent XRPL identity, the Credit Bureau prevents Sybil attacks and incentivizes long-term ecosystem retention.
