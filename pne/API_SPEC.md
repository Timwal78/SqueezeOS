# PNE Handshake Protocol — API Specification

Version: 1.0.0  
Protocol: HTTP/1.1 + HTTP/2  
Auth: L402 (Lightning Labs spec)  
Extension: X-Grace-Tip auction header

---

## Base URL

```
Production: https://n-exchequer.io
Local:      http://localhost:8402
```

---

## The PNE Handshake (5-Step Protocol)

### Step 1: The Probe

Any HTTP request without Authorization:

```http
GET /v1/market-data?symbol=IWM HTTP/1.1
Host: n-exchequer.io
User-Agent: PNEClient/1.0
Accept: application/json
```

### Step 2: The 402 Challenge

```http
HTTP/1.1 402 Payment Required
Content-Type: application/json
WWW-Authenticate: L402 invoice="lnbc1000n1pjq...[BOLT11]", macaroon="AgEHb....[BASE64]"
X-PNE-Version: 1.0.0
X-Auction-Window: 5ms
X-Base-Price-Sats: 100
X-Grace-Tip-Min: 0
X-Grace-Tip-Max: 1000000

{
  "error": "payment_required",
  "code": "L402_CHALLENGE",
  "invoice": "lnbc1000n1pjq...",
  "macaroon": "AgEHb....",
  "amount_sats": 100,
  "payment_hash": "abc123...",
  "expires_at": 1748003600,
  "message": "Pay invoice to receive authorization macaroon preimage. Add X-Grace-Tip to bid for auction priority."
}
```

### Step 3: The Bid (Agent Resubmits with Payment)

```http
GET /v1/market-data?symbol=IWM HTTP/1.1
Host: n-exchequer.io
Authorization: L402 <preimage_hex>:<macaroon_base64>
X-Grace-Tip: 5000
X-Agent-Wallet: rnXwFPHNtqJyYKkxTsqDKcQTcM4mNSaEJP
X-Target-Rank: 1
User-Agent: PNEClient/1.0
```

**Header definitions:**

| Header | Required | Type | Description |
|--------|----------|------|-------------|
| `Authorization` | Yes | `L402 <preimage>:<macaroon>` | Payment proof + auth token |
| `X-Grace-Tip` | No | integer (satoshis) | Extra bid for priority queue |
| `X-Agent-Wallet` | No | string | Agent's wallet for leaderboard |
| `X-Target-Rank` | No | integer | Desired auction rank (SDK uses for retry logic) |

### Step 4: Auction Resolution (Internal, ≤5ms)

Within the 5ms auction window, all bids are ranked by `X-Grace-Tip` descending. The gateway then:

1. Dispatches requests to upstream in rank order
2. Records results in Merkle tree
3. Broadcasts to Loom via Redis pub/sub

### Step 5: The Resolution Response

```http
HTTP/1.1 200 OK
Content-Type: application/json
X-Auction-Rank: 1
X-Auction-Window: 1748000000005
X-Execution-Latency: 2ms
X-Grace-Tip-Paid: 5000
X-Merkle-Leaf: sha256:abc123...
X-PNE-Version: 1.0.0

{
  "symbol": "IWM",
  "bias": "BULLISH",
  "confidence": 87,
  "regime": "ALPHA_EXPANSION",
  "source": "SqueezeOS",
  "timestamp": 1748000000
}
```

**Response headers:**

| Header | Description |
|--------|-------------|
| `X-Auction-Rank` | Position won in the auction (1 = highest priority) |
| `X-Auction-Window` | Epoch milliseconds of the auction window |
| `X-Execution-Latency` | Time from auction win to upstream response |
| `X-Grace-Tip-Paid` | Confirmed tip amount (what was actually charged) |
| `X-Merkle-Leaf` | SHA256 hash of the audit leaf for this transaction |

---

## All Endpoints

### Health & Info

#### `GET /v1/status`
```json
{
  "status": "operational",
  "version": "1.0.0",
  "auction_windows_per_second": 200,
  "queue_depth": 14,
  "last_auction_latency_ms": 1.8,
  "uptime_seconds": 86400
}
```

#### `GET /v1/pricing`
```json
{
  "base_price_sats": 100,
  "base_price_rlusd": 0.001,
  "grace_tip_min": 0,
  "grace_tip_max": 1000000,
  "platform_fee_pct": 1.0,
  "auction_window_ms": 5
}
```

---

### Market Data (Proxied — requires L402)

#### `GET /v1/market-data`

Query params: `symbol` (required), `fields` (optional, comma-separated)

```http
Authorization: L402 <preimage>:<macaroon>
X-Grace-Tip: 5000
```

Response: Upstream SqueezeOS data with PNE auction headers appended.

#### `POST /v1/council`

Body: `{ "symbol": "IWM" }`

Premium endpoint — base price: 10000 sats (0.10 RLUSD equivalent).  
Grace Tips accepted up to 100000 sats.

---

### Auction Book

#### `GET /v1/auction/book`

Current live auction book (read-only, no auth required):

```json
{
  "window_id": 1748000000005,
  "window_ms": 5,
  "bids": [
    { "rank": 1, "tip_sats": 5000, "wallet_hash": "sha256:abc...", "submitted_ms": 1 },
    { "rank": 2, "tip_sats": 3000, "wallet_hash": "sha256:def...", "submitted_ms": 2 },
    { "rank": 3, "tip_sats": 1000, "wallet_hash": "sha256:ghi...", "submitted_ms": 0 }
  ],
  "resolves_in_ms": 2.1
}
```

#### `GET /v1/auction/history`

Query params: `limit` (default 100, max 1000), `wallet_hash` (optional filter)

```json
{
  "auctions": [
    {
      "window_id": 1748000000000,
      "winner_wallet_hash": "sha256:abc...",
      "winner_tip_sats": 5000,
      "total_bids": 8,
      "total_tips_sats": 23000,
      "execution_latency_ms": 1.9
    }
  ]
}
```

---

### Leaderboard

#### `GET /v1/leaderboard`

Query params: `period` (`1h`, `24h`, `7d`, `all`), `limit` (default 25, max 100)

```json
{
  "period": "24h",
  "leaderboard": [
    {
      "rank": 1,
      "wallet_hash": "sha256:abc...",
      "total_tips_sats": 450000,
      "total_wins": 892,
      "total_requests": 1041,
      "win_rate": 0.857,
      "avg_tip_sats": 505,
      "efficiency_score": 94.2,
      "display_name": null
    }
  ]
}
```

---

### Merkle Audit

#### `GET /v1/audit/merkle-root`

Published every 60 seconds:

```json
{
  "root": "0xabc123...",
  "height": 14291,
  "leaf_count": 14291,
  "published_at": 1748000000,
  "next_publish_at": 1748000060
}
```

#### `GET /v1/audit/proof/:auction_id`

```json
{
  "auction_id": "550e8400-e29b-41d4-a716-446655440000",
  "leaf": "sha256:abc123...",
  "path": [
    { "sibling": "sha256:def456...", "position": "right" },
    { "sibling": "sha256:ghi789...", "position": "left" }
  ],
  "root": "0xabc123...",
  "verified": true
}
```

---

### WebSocket (Loom Feed)

#### `WS /ws/loom`

Binary MessagePack stream. All auction events broadcast in real-time.

**Subscribe message (client → server):**
```json
{ "action": "subscribe", "channels": ["auctions", "leaderboard"] }
```

**Auction event (server → client):**
```json
{
  "type": "CHALLENGE_ISSUED",
  "ts": 1748000000001,
  "request_id": "uuid",
  "ip_hash": "sha256:...",
  "endpoint": "/v1/market-data"
}
```

```json
{
  "type": "BID_RECEIVED",
  "ts": 1748000000002,
  "request_id": "uuid",
  "tip_sats": 5000,
  "wallet_hash": "sha256:..."
}
```

```json
{
  "type": "AUCTION_RESOLVED",
  "ts": 1748000000005,
  "window_id": 1748000000000,
  "results": [
    { "rank": 1, "request_id": "uuid", "tip_sats": 5000, "execution_ms": 1.9 },
    { "rank": 2, "request_id": "uuid2", "tip_sats": 3000, "execution_ms": 3.1 }
  ]
}
```

---

## Error Codes

| HTTP Status | Code | Description |
|-------------|------|-------------|
| 402 | `L402_CHALLENGE` | No payment header — invoice in response |
| 401 | `MACAROON_INVALID` | Macaroon HMAC verification failed |
| 401 | `PREIMAGE_INVALID` | SHA256(preimage) ≠ payment_hash |
| 401 | `TOKEN_EXPIRED` | Macaroon time caveat exceeded |
| 401 | `IP_MISMATCH` | Macaroon IP caveat ≠ request IP |
| 429 | `RATE_LIMITED` | Unauthenticated rate limit hit (100/min) |
| 503 | `UPSTREAM_UNAVAILABLE` | Upstream service returned error |
| 503 | `AUCTION_OVERLOADED` | Auction queue at capacity (>10,000 bids/window) |
