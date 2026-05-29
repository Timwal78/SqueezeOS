# Technical Architecture

## System Diagram

```
┌──────────────────────────────────────────────────────────────────────┐
│                        AGENT / CLIENT LAYER                          │
│                                                                       │
│   Python PNEClient (SDK)    ◄──►   Any HTTP Client (curl, httpx)     │
└────────────────────────────────┬─────────────────────────────────────┘
                                 │ HTTP + L402 headers
                                 ▼
┌──────────────────────────────────────────────────────────────────────┐
│                     PNE GATEWAY (Rust / Axum)                        │
│                                                                       │
│  ┌─────────────────┐  ┌──────────────────┐  ┌────────────────────┐  │
│  │   L402 Parser   │  │  Auction Engine  │  │  Merkle Recorder   │  │
│  │  (l402.rs)      │  │  (auction.rs)    │  │  (merkle.rs)       │  │
│  │                 │  │                  │  │                    │  │
│  │ Parse headers   │  │ Priority queue   │  │ SHA256 leaf build  │  │
│  │ Verify macaroon │  │ 5ms windows      │  │ Append-only tree   │  │
│  │ Issue invoices  │  │ Grace Tip rank   │  │ Proof generation   │  │
│  └────────┬────────┘  └────────┬─────────┘  └─────────┬──────────┘  │
│           │                    │                        │             │
│  ┌────────▼────────────────────▼────────────────────────▼──────────┐ │
│  │              Redis State Engine (redis_state.rs)                 │ │
│  │  Redlock mutex ▪ Pub/Sub broadcast ▪ Auction book TTL           │ │
│  └──────────────────────────────┬───────────────────────────────────┘ │
└─────────────────────────────────┼────────────────────────────────────┘
                                  │ Redis pub/sub
           ┌───────────────┬──────┘
           │               │
           ▼               ▼
┌──────────────────┐  ┌─────────────────────────────────────────────────┐
│  LOOM VISUALIZER │  │                 UPSTREAM SERVICES                │
│  (React/Three.js)│  │                                                  │
│                  │  │  SqueezeOS API ▪ Any x402-protected endpoint     │
│  WebSocket sub   │  └─────────────────────────────────────────────────┘
│  WebGL particles │
│  Obsidian canvas │  ┌─────────────────────────────────────────────────┐
│  Leaderboard     │  │               TIMESCALE DB                       │
└──────────────────┘  │  Auction records ▪ Merkle tree ▪ Agent history  │
                       └─────────────────────────────────────────────────┘
```

---

## Component Specifications

### Gateway (Rust / Axum)

**Framework:** Axum 0.7 on Tokio async runtime  
**Target:** Single binary, `<20MB`, zero dynamic linking  
**Concurrency:** One Tokio worker per CPU core, NUMA-aware  

```
Cargo.toml dependencies:
  axum = "0.7"
  tokio = { version = "1", features = ["full"] }
  tower = "0.4"
  tower-http = { version = "0.5", features = ["trace", "cors", "limit"] }
  redis = { version = "0.24", features = ["tokio-comp", "connection-manager"] }
  hmac = "0.12"
  sha2 = "0.10"
  hex = "0.4"
  serde = { version = "1", features = ["derive"] }
  serde_json = "1"
  uuid = { version = "1", features = ["v4"] }
  tracing = "0.1"
  tracing-subscriber = "0.3"
  anyhow = "1"
  thiserror = "1"
  tokio-tungstenite = "0.21"
  futures-util = "0.3"
  reqwest = { version = "0.11", features = ["json"] }
  base64 = "0.22"
  ring = "0.17"
  dashmap = "5"
  priority-queue = "1"
  criterion = { version = "0.5", features = ["async_tokio"] }  # bench only
```

**Request lifecycle (5ms budget):**
```
T=0ms   Request arrives → Tower middleware stack
T=0.2ms L402 header parse → HMAC-SHA256 macaroon verify (CPU only)
T=0.5ms Redis GETSET auction_window:{slot} → join current auction batch
T=1ms   Grace Tip inserted into BTreeMap priority queue (O(log n))
T=5ms   Auction window expires → tokio::select! → resolve winner order
T=5.1ms Upstream HTTP call dispatched (excluded from 5ms budget)
T=5.2ms Merkle leaf computed → Redis RPUSH audit_log
T=5.3ms Response returned to agent with X-Auction-Rank header
```

---

### Payment Layer

**Primary:** Lightning Network (LND via gRPC)  
**Secondary:** Base L2 via Coinbase Developer Platform (EIP-681 URIs)  
**Tertiary:** XRPL + RLUSD (SqueezeOS native, for ecosystem integration)

**Invoice generation flow:**
```
Gateway receives unauthenticated request
→ Generate BOLT11 invoice for base_price satoshis (TTL: 300s)
→ Generate macaroon with caveats: [time<exp, ip=client_ip, endpoint=path]
→ Return: 402 + WWW-Authenticate: L402 invoice="lnbc...", macaroon="Ag..."
→ Agent pays invoice → receives preimage
→ Agent retries: Authorization: L402 <preimage>:<macaroon>
→ Gateway verifies: HMAC(macaroon_secret, caveats) == macaroon.signature
→ Check preimage: SHA256(preimage) == payment_hash
→ Auction admission granted
```

---

### State Engine (Redis + Redlock)

**Auction book key schema:**
```
auction:window:{epoch_5ms}        → Sorted set (score=grace_tip, member=request_id)
auction:meta:{request_id}         → Hash (wallet, endpoint, tip, timestamp, ip)
auction:result:{request_id}       → Hash (rank, latency_ms, executed_at)
agent:stats:{wallet}              → Hash (total_tips, wins, requests, referrer)
agent:leaderboard                 → Sorted set (score=total_tips, member=wallet)
audit:merkle:{date}               → List (leaf hashes, append-only)
```

**Redlock:** 5ms lease, single Redis instance in dev, 3-node quorum in production.

---

### Loom Visualizer (React + Three.js)

**Build:** Vite 5 + React 18 + TypeScript 5  
**3D Engine:** Three.js r165 with WebGL2 renderer  
**State:** Zustand + WebSocket (binary MessagePack for low latency)  

**Scene architecture:**
```
Scene
├── AmbientLight (intensity: 0.05) — obsidian void
├── ParticleSystem (BufferGeometry + ShaderMaterial)
│   ├── 100,000 pre-allocated particle slots (geometry instancing)
│   ├── Custom vertex shader: position = lerp(origin, target, t^2)
│   └── Custom fragment shader: additive blending, radial glow, color by tip
├── LoomWeave (LineSegments)
│   └── Each settled auction draws a permanent gold thread
├── HUDLayer (CSS2DRenderer — not WebGL)
│   ├── AuctionBook overlay (top-right)
│   └── Leaderboard overlay (bottom-left)
└── PostProcessing (EffectComposer)
    ├── UnrealBloomPass (strength: 2.0, radius: 0.5, threshold: 0.1)
    └── FilmPass (scanlines: subtle)
```

**WebSocket message format:**
```typescript
type AuctionEvent =
  | { type: "CHALLENGE_ISSUED"; request_id: string; ip_hash: string; endpoint: string }
  | { type: "BID_RECEIVED"; request_id: string; tip: number; wallet_hash: string }
  | { type: "AUCTION_RESOLVED"; window_id: string; results: AuctionResult[] }
  | { type: "UPSTREAM_COMPLETE"; request_id: string; latency_ms: number }
```

---

### SDK (Python)

**Runtime:** Python 3.11+  
**HTTP:** httpx (async-first)  
**Payment:** For LN: `lnd-grpc-client`. For XRPL: `xrpl-py`. For Base: `web3.py`  

**Class hierarchy:**
```
PNEClient
├── L402Handler         — parse/pay/retry 402 cycles
├── AuctionStrategy     — tip calculation per strategy
│   ├── AggressiveBidder
│   ├── ConservativeBidder
│   └── OptimalBidder   — Kelly criterion
├── PaymentAdapter      — abstract base
│   ├── LightningAdapter
│   ├── XRPLAdapter
│   └── BaseL2Adapter
└── AuditClient         — verify Merkle proofs
```

---

### Storage (TimescaleDB)

**Schema:**
```sql
CREATE TABLE auction_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    window_id       BIGINT NOT NULL,
    request_id      UUID NOT NULL,
    wallet_hash     TEXT NOT NULL,
    endpoint        TEXT NOT NULL,
    grace_tip       BIGINT NOT NULL,
    auction_rank    INTEGER NOT NULL,
    execution_ms    NUMERIC(10,3) NOT NULL,
    merkle_leaf     TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
SELECT create_hypertable('auction_events', 'created_at');

CREATE TABLE merkle_roots (
    height          BIGINT PRIMARY KEY,
    root_hash       TEXT NOT NULL,
    published_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**Retention:** 90-day chunk interval, automatic compression after 7 days.

---

## Deployment

### Production (Recommended)

| Service | Platform | Notes |
|---------|----------|-------|
| Gateway | Fly.io (any region, `performance-1x`) | Rust binary, ~15ms cold start |
| Loom | Vercel / Cloudflare Pages | Static build, CDN-distributed |
| Redis | Upstash (Global) | Serverless Redis, Redlock-compatible |
| TimescaleDB | Timescale Cloud | Managed, auto-compression |
| LND | Voltage.cloud | Managed Lightning node |

### Docker Compose (Dev)

```yaml
services:
  gateway:
    build: ./gateway
    ports: ["8402:8402"]
    environment:
      - REDIS_URL=redis://redis:6379
      - LND_ENDPOINT=https://lnd:8080
      - MACAROON_SECRET=${MACAROON_SECRET}
    depends_on: [redis]

  loom:
    build: ./loom
    ports: ["5173:5173"]
    environment:
      - VITE_GATEWAY_WS=ws://localhost:8402/ws

  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]
```

---

## Performance Budget

| Metric | Target | Alert | Hard Limit |
|--------|--------|-------|------------|
| Gateway overhead (P50) | <2ms | >3ms | >5ms |
| Gateway overhead (P99) | <4ms | >4.5ms | >6ms |
| Auction resolution | <5ms | >4ms | >5ms |
| Macaroon verify | <0.5ms | >1ms | >2ms |
| Redis round-trip | <1ms | >2ms | >3ms |
| Loom frame rate | 60fps | <45fps | <30fps |
| Loom particle budget | 100,000 | — | — |
