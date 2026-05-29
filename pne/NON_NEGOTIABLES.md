# Institutional-Grade Non-Negotiables

These rules cannot be overridden by product decisions, time pressure, or investor requests.
Any deviation requires a written architectural exception signed by the lead engineer.

---

## 1. Latency: The 5ms Rule

**Rule:** The PNE proxy must not add more than **5ms of overhead** to any upstream request.

**Enforcement:**
- Core auction logic written in Rust (Axum + Tokio). No Python, Node, or Go in the hot path.
- Redis Redlock acquisition must complete in ≤1ms (use pipelining, not round-trip per lock).
- Macaroon verification is CPU-only (HMAC-SHA256). No network calls during auth.
- Auction resolution runs as a single `tokio::task` per 5ms window — no mutex contention across windows.
- P99 latency overhead measured continuously. Alert at 3ms, hard-stop service at 6ms.

**Test:** `cargo bench -- auction_overhead` must pass before any commit to `gateway/src/auction.rs`.

---

## 2. Protocol Standardization: Strict L402

**Rule:** PNE must implement the **L402** protocol as specified by Lightning Labs, with zero proprietary mutations to the core auth flow.

**Compliant:**
- `WWW-Authenticate: L402 invoice="lnbc...", macaroon="AgEH..."`
- `Authorization: L402 <preimage_hex>:<macaroon_base64>`
- BOLT11 invoices for Lightning Network payments
- Base L2 (EIP-681 URIs) as the secondary payment rail

**Non-compliant (banned):**
- Custom `X-PNE-Auth` headers replacing `Authorization`
- Non-standard challenge formats
- Expired macaroon reuse — must reject immediately with `WWW-Authenticate: L402 error="token_expired"`

**Extension (allowed):**
- `X-Grace-Tip: <satoshis>` — PNE auction extension header (additive, never replaces L402)
- `X-Auction-Rank: <integer>` — response header (informational only)
- `X-Execution-Latency: <ms>` — response header (informational only)

---

## 3. The Loom: Aesthetic Non-Negotiables

**Rule:** The Loom visualizer must be built in **Three.js/React**. No D3, no Canvas 2D, no SVG animations.

**Mandatory palette:**
| Token | Hex | Usage |
|-------|-----|-------|
| `obsidian` | `#0A0A0F` | Background, void |
| `neon-cyan` | `#00FFE7` | Validated macaroon, confirmed bid |
| `liquid-gold` | `#FFD700` | Settled auction, winner glow |
| `challenge-red` | `#FF2D55` | 402 challenge issued |
| `sponsor-violet` | `#8B5CF6` | Sponsor pool halo |

**Forbidden:**
- Standard UI component libraries (MUI, shadcn, Chakra) for the main Loom canvas
- Flat colors on particles — all particles must use additive blending
- Static particle sizes — all sizes must pulse with auction activity
- Default browser fonts for auction data overlays — use `Space Mono` or `JetBrains Mono`

**Performance target:** 60fps at 10,000 simultaneous particles on M2 MacBook and RTX 3070.

---

## 4. Agent Autonomy: The Self-Correcting SDK

**Rule:** The Python `PNEClient` must handle the full 402 cycle autonomously with zero human intervention.

**Required behaviors:**
1. On receiving HTTP 402 → parse `WWW-Authenticate` header → pay invoice → retry with `Authorization` header
2. On receiving `X-Auction-Rank > target_rank` in response → increase `grace_tip` by `tip_step` and retry (up to `max_retries`)
3. On `INSUFFICIENT_FUNDS` error → emit `on_budget_exhausted` callback, do not retry
4. On `TOKEN_EXPIRED` → request new invoice, re-pay, retry once
5. `BiddingStrategy.AGGRESSIVE` — start tip at 80% of `max_tip`, reduce by 10% per successful sub-max win
6. `BiddingStrategy.CONSERVATIVE` — start tip at 10% of `max_tip`, increase by 20% on each rank miss
7. `BiddingStrategy.OPTIMAL` — Kelly-criterion-inspired: tip = `(win_rate * expected_value) / odds`

**No human-in-the-loop allowed in the hot path.** SDK callbacks are for logging only.

---

## 5. Transparency: Public Merkle Audit Trail

**Rule:** Every auction resolution must be recorded in an append-only Merkle tree. The root is public.

**Implementation:**
- Leaf = `SHA256(auction_id || winner_wallet || tip_amount || upstream_response_hash || timestamp)`
- Tree built with SHA256, no custom hash functions
- Root published to `GET /v1/audit/merkle-root` every 60 seconds
- Individual proof endpoint: `GET /v1/audit/proof/<auction_id>` returns inclusion proof
- Tree state persisted to TimescaleDB — not in-memory (this is the only component that touches disk)

**Auditability guarantee:** Any third party with the auction_id can verify their transaction was processed without trusting PNE.

---

## 6. No Demo Data

**Rule:** Zero hardcoded auction results, fake agent wallets, or simulated bids in any code path.

If the auction book is empty:
```json
{ "status": "awaiting_intent", "queue_depth": 0, "last_auction_ms": null }
```

Not:
```json
{ "status": "active", "queue_depth": 47, "winner": "agent_demo_wallet" }
```

**Violation response:** Any PR containing hardcoded auction data is rejected and the author is required to reread NON_NEGOTIABLES.md before resubmitting.

---

## 7. Data Source Traceability

**Rule:** Every upstream data response must carry a `X-Data-Source` header identifying the origin (e.g., `Tradier`, `SqueezeOS`, `Polygon`).

PNE is a *proxy*. It does not manufacture data. If the upstream source cannot be identified, return 503 with:
```json
{ "error": "UPSTREAM_UNAVAILABLE", "source": null }
```

---

## 8. Security Baseline

**Rule:** These security controls are non-negotiable and always on:

- **TLS 1.3 only** — no TLS 1.2, no cleartext in production
- **Macaroon caveats** — every macaroon must include `time < now+3600` and `ip = <client_ip>`
- **Rate limiting** — max 100 unauthenticated requests per IP per minute (Axum Tower layer)
- **No logging of payment preimages** — preimages are payment secrets, treat as passwords
- **CORS** — allow only `https://n-exchequer.io` and localhost in dev mode
- **Audit log** — every 402 challenge and auction resolution logged to TimescaleDB, never to stdout
