# EXPERT PROMPT — Project Neural Exchequer (PNE)
### Feed this to Claude Code, Google Vertex AI, or any high-reasoning IDE agent

---

```
SYSTEM ROLE: ELITE DISTRIBUTED SYSTEMS ARCHITECT + RUST / REACT ENGINEER

You are building "Project Neural Exchequer" (PNE) — a production-ready, 
institutional-grade x402 Sovereign Intent Auction gateway.

Read these files in order before writing a single line of code:
1. CONCEPT.md       — Understand the WHY
2. NON_NEGOTIABLES.md — Understand what cannot change
3. ARCHITECTURE.md  — Understand the HOW
4. API_SPEC.md      — Understand the protocol
5. DISCOVERY_STRATEGY.md — Understand distribution

HARD CONSTRAINTS (violating any of these = restart from scratch):
• Gateway MUST be Rust/Axum. No exceptions.
• Gateway MUST add ≤5ms overhead at P99. Benchmark this.
• L402 protocol MUST be followed exactly. No pseudo-402.
• Loom MUST be Three.js + React. No D3, no Canvas2D.
• Loom MUST use ONLY the palette: #0A0A0F, #00FFE7, #FFD700, #FF2D55, #8B5CF6
• SDK MUST auto-handle the full 402 cycle. No human-in-the-loop.
• ZERO hardcoded data anywhere. Return "awaiting_intent" if empty.
• Every auction MUST produce a Merkle leaf. No exceptions.

=============================================================
TASK 1: THE GATEWAY (Rust/Axum)
=============================================================

Build: pne/gateway/src/

Files to create:
• main.rs       — Axum app factory, router, middleware stack, server bind
• l402.rs       — L402 header parser, macaroon generator/verifier, invoice issuer
• auction.rs    — 5ms auction window engine, BTreeMap priority queue, resolution
• middleware.rs — Tower layers: rate_limit, cors, tls_redirect, auth_check
• redis_state.rs — Redis connection pool, auction book CRUD, pub/sub broadcast
• merkle.rs     — SHA256 Merkle tree, leaf computation, proof generation
• error.rs      — Custom error types with axum::IntoResponse impl
• config.rs     — Config struct from environment variables

Key behaviors to implement:

1. Request arrives at ANY /v1/* route
2. Tower middleware checks for Authorization: L402 header
   - If missing → generate BOLT11 invoice (mock LND call in dev) → return 402
   - If present → verify macaroon HMAC → verify preimage → continue
3. Parse X-Grace-Tip header (default: 0 satoshis)
4. Call auction engine:
   - Get current 5ms window ID: epoch_ms / 5 (integer division)
   - ZADD auction:window:{window_id} <tip> <request_id> in Redis
   - Wait for window to close (tokio::time::sleep until next 5ms boundary)
   - ZREVRANGE to get ranked list → assign X-Auction-Rank
5. Forward request to upstream (SQUEEZEOS_BASE_URL env var)
6. Compute Merkle leaf → RPUSH audit:merkle:{date} in Redis
7. Publish auction event to Redis pub/sub channel "loom:events"
8. Return upstream response with PNE headers attached

Rust crates to use (exact versions in Cargo.toml):
  axum = "0.7"
  tokio = { version = "1", features = ["full"] }
  tower = "0.4"
  tower-http = { version = "0.5", features = ["cors", "trace"] }
  redis = { version = "0.24", features = ["tokio-comp", "connection-manager"] }
  hmac = "0.12"
  sha2 = "0.10"
  hex = "0.4"
  serde = { version = "1", features = ["derive"] }
  serde_json = "1"
  uuid = { version = "1", features = ["v4"] }
  tracing = "0.1"
  tracing-subscriber = { version = "0.3", features = ["env-filter"] }
  anyhow = "1"
  thiserror = "1"
  reqwest = { version = "0.11", features = ["json"] }
  base64 = "0.22"
  dashmap = "5"
  tokio-tungstenite = "0.21"
  futures-util = "0.3"

For the WebSocket loom broadcast:
- Subscribe to Redis pub/sub "loom:events" in a background Tokio task
- Broadcast each event to all connected WebSocket clients
- WebSocket endpoint: GET /ws/loom

=============================================================
TASK 2: THE LOOM (React + Three.js)
=============================================================

Build: pne/loom/src/

Files to create:
• main.tsx           — Vite entry, React root mount
• App.tsx            — Top-level layout: full-screen Loom + HUD overlays
• components/Loom.tsx        — Three.js WebGL scene (the centerpiece)
• components/AuctionBook.tsx — Live orderbook overlay (CSS2DRenderer)
• components/Leaderboard.tsx — Agent leaderboard overlay
• hooks/useAuction.ts        — WebSocket connection + Zustand state store
• shaders/particle.vert.glsl — Custom vertex shader
• shaders/particle.frag.glsl — Custom fragment shader (additive blending)

Loom.tsx requirements:
1. Three.js scene setup:
   - WebGLRenderer with antialias: true, alpha: false
   - Background color: 0x0A0A0F (obsidian)
   - Camera: PerspectiveCamera(60, aspect, 0.1, 10000)
   - OrbitControls (auto-rotate, damping enabled)

2. Particle system (BufferGeometry + custom ShaderMaterial):
   - Pre-allocate 100,000 particle slots
   - Each particle has: position (vec3), velocity (vec3), color (vec3), size (float), alpha (float), state (int)
   - States: 0=dormant, 1=challenge(red), 2=bidding(cyan), 3=settled(gold), 4=executing(white)
   - Particle lifecycle: spawn at origin → arc toward "upstream node" → burst on resolution
   - ShaderMaterial: blending = AdditiveBlending, depthWrite = false, transparent = true

3. Vertex shader behavior:
   - State 1 (challenge): small, pulsing red sphere, position jitter
   - State 2 (bidding): medium, elongated in direction of travel, cyan trail
   - State 3 (settled): large, gold burst, scale up then fade
   - State 4 (executing): racing cyan line to upstream node, speed ∝ auction rank

4. The Loom Weave (gold threads):
   - Every settled bid draws a permanent LineSegments thread
   - Thread from agent spawn point → upstream node
   - Color: 0xFFD700, opacity: 0.3
   - Maximum 10,000 threads before oldest are removed (ring buffer)

5. Post-processing (EffectComposer):
   - UnrealBloomPass: strength=2.5, radius=0.4, threshold=0.05
   - FilmPass: scanlines=0.15, grayscale=false

6. Animation loop (requestAnimationFrame):
   - Update all particle positions per frame (lerp/physics)
   - Update particle colors based on state transitions from useAuction hook
   - Render scene

useAuction.ts requirements:
1. WebSocket connection to ws://gateway:8402/ws/loom
2. Auto-reconnect with exponential backoff (1s, 2s, 4s, 8s, max 30s)
3. Parse binary MessagePack events (use @msgpack/msgpack library)
4. Zustand store shape:
   {
     particles: Map<string, Particle>   // keyed by request_id
     auctionBook: AuctionBid[]          // current window bids
     leaderboard: LeaderboardEntry[]    // top 25 agents
     lastWindowId: bigint
     totalVolume: bigint                // cumulative tips
     connectedAgents: number
     addEvent: (event: AuctionEvent) => void
   }
5. Map AuctionEvent types to particle state transitions:
   CHALLENGE_ISSUED → spawn new particle, state=1
   BID_RECEIVED → update particle, state=2, size ∝ tip
   AUCTION_RESOLVED → transition winners to state=3, losers to state=4
   UPSTREAM_COMPLETE → burst particle, then fade to dormant

AuctionBook.tsx requirements:
- CSS2DRenderer overlay (not WebGL, for crisp text)
- Position: top-right corner
- Show: current window bids ranked by tip
- Font: 'JetBrains Mono', 12px, color: #00FFE7
- Animate bid entries sliding in from right
- Flash gold on resolution

Leaderboard.tsx requirements:
- CSS2DRenderer overlay, bottom-left
- Top 10 agents by 24h tips
- Show: wallet_hash (truncated), tips_sats, win_rate, efficiency_score
- Highlight rank changes with arrow animation

package.json dependencies:
  "three": "^0.165.0"
  "@types/three": "^0.165.0"
  "react": "^18.3.0"
  "react-dom": "^18.3.0"
  "zustand": "^4.5.0"
  "@msgpack/msgpack": "^3.0.0"
  "postprocessing": "^6.36.0"
  "@react-three/fiber": "^8.16.0"   (optional, can use Three.js directly)
  "typescript": "^5.4.0"
  "vite": "^5.3.0"

vite.config.ts:
  server.proxy: { '/api': 'http://localhost:8402', '/ws': { ws: true, target: 'ws://localhost:8402' } }
  build.target: 'esnext'
  build.minify: 'terser'

=============================================================
TASK 3: THE SDK (Python)
=============================================================

Build: pne/sdk/pne_client/

Files to create:
• __init__.py    — Public exports
• client.py      — PNEClient main class
• auction.py     — BiddingStrategy implementations
• l402.py        — L402 parse, invoice pay, macaroon verify
• payment.py     — PaymentAdapter base + LightningAdapter + XRPLAdapter
• audit.py       — AuditClient Merkle proof verifier
• exceptions.py  — Custom exceptions

client.py — PNEClient class:

```python
class PNEClient:
    def __init__(
        self,
        base_url: str = "https://n-exchequer.io",
        wallet_seed: str | None = None,
        max_tip: int = 5000,           # satoshis
        tip_step: int = 500,
        target_rank: int = 1,
        max_retries: int = 3,
        strategy: str = "optimal",    # "aggressive", "conservative", "optimal"
        payment_rail: str = "xrpl",   # "lightning", "xrpl", "base"
        on_payment: Callable | None = None,
        on_auction_rank: Callable | None = None,
        on_budget_exhausted: Callable | None = None,
    )

    async def get(self, path: str, **kwargs) -> httpx.Response
    async def post(self, path: str, **kwargs) -> httpx.Response
    async def _execute_with_l402(self, method: str, path: str, **kwargs) -> httpx.Response
    async def _handle_402(self, response: httpx.Response) -> str  # returns preimage
    async def _retry_with_tip_increase(self, ...) -> httpx.Response
    def get_auction_rank(self, response: httpx.Response) -> int | None
    def get_merkle_leaf(self, response: httpx.Response) -> str | None
    async def verify_audit(self, auction_id: str) -> bool
```

The core 402 cycle (_execute_with_l402):
```python
async def _execute_with_l402(self, method, path, grace_tip=0, **kwargs):
    headers = kwargs.pop("headers", {})
    
    for attempt in range(self.max_retries):
        if self._current_token:
            headers["Authorization"] = f"L402 {self._current_token}"
        if grace_tip > 0:
            headers["X-Grace-Tip"] = str(grace_tip)
        headers["X-Agent-Wallet"] = self.wallet_address
        
        response = await self._client.request(method, path, headers=headers, **kwargs)
        
        if response.status_code == 402:
            preimage = await self._handle_402(response)
            macaroon = self._parse_macaroon(response)
            self._current_token = f"{preimage}:{macaroon}"
            continue  # retry with auth
        
        if response.status_code == 200:
            rank = self.get_auction_rank(response)
            if self.on_auction_rank:
                self.on_auction_rank(rank)
            
            if rank and rank > self.target_rank and grace_tip < self.max_tip:
                new_tip = self.strategy.increase_tip(grace_tip, rank)
                if new_tip <= self.max_tip:
                    return await self._execute_with_l402(method, path, grace_tip=new_tip, **kwargs)
            
            return response
        
        response.raise_for_status()
    
    raise MaxRetriesExceeded(f"Failed after {self.max_retries} attempts")
```

auction.py — BiddingStrategy:
```python
class BiddingStrategy(Protocol):
    def initial_tip(self, max_tip: int) -> int: ...
    def increase_tip(self, current_tip: int, current_rank: int) -> int: ...

class AggressiveBidder:
    # Start at 80% of max_tip
    # Reduce by 10% each time we win below max_tip
    def initial_tip(self, max_tip): return int(max_tip * 0.8)
    def increase_tip(self, current_tip, current_rank): return int(current_tip * 1.2)

class ConservativeBidder:
    # Start at 10% of max_tip
    # Increase by 20% on each rank miss
    def initial_tip(self, max_tip): return int(max_tip * 0.1)
    def increase_tip(self, current_tip, current_rank): return int(current_tip * 1.2)

class OptimalBidder:
    # Kelly criterion approximation
    # tip = (win_rate * expected_value) / (1 / odds)
    # Maintain rolling win_rate from past 100 requests
    def __init__(self):
        self._history = deque(maxlen=100)
    
    def initial_tip(self, max_tip):
        if len(self._history) < 10:
            return int(max_tip * 0.3)  # cold start
        win_rate = sum(1 for r in self._history if r["rank"] == 1) / len(self._history)
        kelly = win_rate - (1 - win_rate)  # simplified Kelly
        return max(0, min(int(max_tip * kelly), max_tip))
    
    def increase_tip(self, current_tip, current_rank):
        return min(int(current_tip * (1 + (current_rank - 1) * 0.15)), self._max_tip)
    
    def record_outcome(self, rank: int, tip: int):
        self._history.append({"rank": rank, "tip": tip})
```

=============================================================
ENVIRONMENT VARIABLES (pne/.env.example)
=============================================================

# Gateway
PORT=8402
REDIS_URL=redis://localhost:6379
UPSTREAM_BASE_URL=https://squeezeos-api.onrender.com
MACAROON_SECRET=<32-byte-hex-string>
RATE_LIMIT_UNAUTH=100          # requests per minute per IP

# Payment (choose one)
LND_ENDPOINT=https://localhost:8080
LND_MACAROON_HEX=<hex>
# OR
CDP_API_KEY=<coinbase-developer-platform-key>
CDP_PROJECT_ID=<project-id>
# OR
XRPL_WALLET_SEED=<xrpl-seed>
XRPL_WALLET_ADDRESS=<xrpl-address>

# Audit
TIMESCALE_URL=postgres://pne:password@localhost:5432/pne_audit

# Loom
VITE_GATEWAY_WS=ws://localhost:8402
VITE_GATEWAY_HTTP=http://localhost:8402

# SDK (for examples)
PNE_BASE_URL=http://localhost:8402
PNE_MAX_TIP=5000
PNE_STRATEGY=optimal

=============================================================
PRODUCTION CHECKLIST
=============================================================

Before calling this production-ready, verify:

[ ] cargo bench -- auction_overhead shows P99 < 5ms
[ ] cargo test passes all unit tests in gateway/src/
[ ] Loom renders at 60fps with 10,000 simulated particles
[ ] Python SDK handles 402 → pay → retry cycle end-to-end
[ ] GET /v1/audit/proof/:id returns valid Merkle proof
[ ] All NON_NEGOTIABLES.md items are satisfied
[ ] .env.example documents every required env var
[ ] Docker Compose starts all services cleanly
[ ] TLS 1.3 is the only accepted protocol in production config
[ ] No payment preimages appear in any log output
[ ] Rate limiting rejects 101st unauthenticated request per minute

=============================================================
AESTHETIC STANDARD
=============================================================

The Loom is the product. The auction is the engine.
When a human looks at the running system for the first time,
their first reaction must be: "What IS this?"

The obsidian void + neon particles + gold threads must feel
like looking at a living organism. Not a dashboard.
Not a chart. A WORLD.

If at any point the Loom looks like a normal web app,
restart the visual design from scratch.

The code must match the ambition.
```
