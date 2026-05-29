# Project Neural Exchequer (PNE)
### The Sovereign Intent Auction for the x402 Economy

> "You aren't building a tool. You are building the Stock Exchange of the AI Era, disguised as a Digital Art Gallery."

PNE turns API access into a high-frequency, high-stakes visual auction where AI agents compete in milliseconds for priority execution. It is the Bloomberg Terminal of the machine economy.

---

## What Is PNE?

**PNE** is a three-part system:

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **The Gateway** | Rust / Axum | Ultra-low-latency x402 proxy + priority auction engine |
| **The Loom** | React / Three.js / WebGL | Real-time WebGL visualizer of the auction battlefield |
| **The SDK** | Python / httpx | Self-correcting agent SDK with autonomous bidding logic |

---

## Quick Start

### 1. Prerequisites

- Rust 1.78+ (`rustup`)
- Node.js 20+ / pnpm
- Python 3.11+
- Redis 7+ (local or Upstash)
- LND node OR Coinbase Developer Platform account (Base L2)

### 2. Environment

```bash
cp pne/.env.example pne/.env
# Fill in: REDIS_URL, LND_MACAROON or CDP_API_KEY, SECRET_KEY, PORT
```

### 3. Start the Gateway

```bash
cd pne/gateway
cargo build --release
./target/release/pne-gateway
# Listening on 0.0.0.0:8402
```

### 4. Start the Loom

```bash
cd pne/loom
pnpm install
pnpm dev
# Loom at http://localhost:5173
```

### 5. Use the SDK

```python
from pne_client import PNEClient

client = PNEClient(
    base_url="http://localhost:8402",
    wallet_seed="your_xrpl_or_ln_wallet",
    max_tip=5000  # satoshis
)

response = client.get("/v1/market-data", symbol="IWM")
print(response.json())
```

---

## Architecture Overview

```
Agent Request
     │
     ▼
┌─────────────────────────────────────────────────────────────┐
│                    PNE GATEWAY (Rust/Axum)                  │
│                                                             │
│  1. Parse L402 header → valid? → route to upstream          │
│  2. No header → issue 402 + BOLT11 invoice                  │
│  3. X-Grace-Tip present → insert into priority queue        │
│  4. Auction resolves in ≤5ms → upstream call                │
│  5. Broadcast auction event → Redis pub/sub                 │
└──────────────────┬──────────────────────────────────────────┘
                   │ Redis pub/sub (auction state)
                   ▼
┌─────────────────────────────────────────────────────────────┐
│                   THE LOOM (Three.js/WebGL)                 │
│                                                             │
│  • Red pulse  = 402 challenge issued                        │
│  • Gold pulse = bid settled, slot won                       │
│  • Density    = network traffic volume                      │
│  • Brightness = Grace Tip magnitude                         │
└─────────────────────────────────────────────────────────────┘
```

---

## Directory Structure

```
pne/
├── README.md               ← You are here
├── CONCEPT.md              ← Vision & "why"
├── NON_NEGOTIABLES.md      ← Institutional-grade standards
├── ARCHITECTURE.md         ← Full tech stack
├── API_SPEC.md             ← PNE Handshake Protocol
├── DISCOVERY_STRATEGY.md   ← Agent-first distribution
├── EXPERT_PROMPT.md        ← AI-agent build prompt
├── .env.example            ← Environment variables
├── gateway/                ← Rust/Axum proxy
│   ├── Cargo.toml
│   └── src/
│       ├── main.rs         ← Entry point, Axum router
│       ├── l402.rs         ← L402 header parsing & invoice generation
│       ├── auction.rs      ← Priority queue auction engine
│       ├── middleware.rs   ← Tower middleware layers
│       └── redis_state.rs  ← Redis pub/sub + Redlock
├── loom/                   ← React + Three.js visualizer
│   ├── package.json
│   ├── vite.config.ts
│   ├── index.html
│   └── src/
│       ├── main.tsx
│       ├── App.tsx
│       ├── components/
│       │   ├── Loom.tsx        ← Three.js WebGL scene
│       │   ├── AuctionBook.tsx ← Live bid orderbook
│       │   └── Leaderboard.tsx ← Agent leaderboard
│       └── hooks/
│           └── useAuction.ts   ← WebSocket auction state
└── sdk/                    ← Python PNE client
    ├── pyproject.toml
    ├── pne_client/
    │   ├── __init__.py
    │   ├── client.py       ← PNEClient main class
    │   ├── auction.py      ← Bidding strategy logic
    │   └── l402.py         ← L402 parse & payment
    └── examples/
        └── basic_usage.py
```

---

## The Monetization Engine

| Revenue Stream | Mechanism |
|---------------|-----------|
| **Admission Toll** | Every API call requires x402 micro-payment (0.001–0.01 RLUSD) |
| **Priority Surcharge** | Temporal bonding curve: closer to head-of-queue = higher price |
| **Platform Cut** | 1% of all Grace Tips collected |
| **Artifact Mint** | Daily "Most Beautiful Handshake" minted as generative 1/1 NFT |
| **Referral Bounty** | Agent-A refers Agent-B → Agent-A gets 5% toll discount |

---

## Protocol Compliance

PNE implements the **L402** standard (IETF draft, Lightning Labs spec):

- `WWW-Authenticate: L402 invoice="...", macaroon="..."`
- `Authorization: L402 <preimage>:<macaroon>`
- `X-Grace-Tip: <satoshis>` (PNE extension)

No proprietary pseudo-402 headers. Every invoice is a valid BOLT11 string.

---

## Auditing

Every auction is recorded in an append-only Merkle tree. The root hash is published to a public endpoint every 60 seconds:

```
GET /v1/audit/merkle-root
→ { "root": "0xabc...", "height": 14291, "timestamp": 1748000000 }
```

Individual auction proofs:

```
GET /v1/audit/proof/<auction_id>
→ { "leaf": "...", "path": [...], "root": "..." }
```
