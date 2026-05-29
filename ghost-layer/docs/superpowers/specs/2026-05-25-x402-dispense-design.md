# Ghost Layer X402 Dispense — Design

**Date:** 2026-05-25
**Scope:** Native HTTP 402 challenge → quote → pay → JWT-gated dispense for institutional reads
**Branch:** `claude/x402-dispense`
**Predecessor:** M2M-VENDING-01 (Phases 1–3, on `main`)

---

## Problem Statement

`/api/config` already advertises `x402_compliant: true` and the bottom-bar UI shows an `X402 ✓` badge, but there is no actual HTTP 402 challenge surface on Ghost Layer. The Cube mint route consults the external `four02proof.onrender.com` service via `fetchCubeMintInvoice`, which leaves Ghost Layer dependent on a third party for any vending. This phase makes Ghost Layer a self-contained x402 vendor: it issues its own invoices, verifies its own tokens, and dispenses its own products.

---

## Goals

1. Ghost Layer issues HMAC-SHA256 signed invoices natively. No outbound call to 402Proof during the quote phase.
2. The token format is byte-compatible with `proof402_integration.py` (`<base64(payload)>.<hex-hmac>`) so a SqueezeOS-style decorator can be reused on either side later.
3. Pricing is loyalty-aware — `EffectiveBPS` (or a tier-keyed price table for catalog items) is applied at quote time, not at dispense time.
4. Every dispense fires a `X402_DISPENSED` frame on `metricsHub`, the cube swaps to a new `vend` palette, and the bottom-bar `X402 ✓` badge briefly pulses on dispatch.
5. Replay protection: `iid` (invoice ID) is checked against a TTL'd nonce cache before the product is dispensed.

---

## Non-Goals (this phase)

- Multi-product side-effects (no minting, no cross-chain routing perks). V1 ships **one product** end-to-end.
- External 402Proof integration changes. The existing Cube mint flow is left untouched.
- Persisted invoice store. Invoices are stateless HMAC tokens; only the **post-dispense** nonce cache holds state, and only in-memory.

---

## Token Format

Identical to the existing `verifyPaymentToken` shape so the verifier stays consistent:

```
<base64url(payload_json)>.<hex(hmac_sha256(secret, base64url(payload_json)))>
```

`payload_json` is:

```json
{
  "pid": "routing.telemetry",
  "wlt": "rAgentXrplAddress...",
  "iid": "01HQ7V9...ULID",
  "exp": 1735689600,
  "tier": "GOLD"
}
```

- `pid` — product ID from the catalog (string, not UUID — readable IDs are easier to debug)
- `wlt` — agent's XRPL wallet address (informational; not bound to verifier check in V1)
- `iid` — invoice ID, ULID. Used as the replay-cache key
- `exp` — unix seconds. Tokens expire 5 minutes after issuance
- `tier` — agent tier at quote time (informational; pricing was already applied)

**Secret:** `X402_TOKEN_SECRET` env var. Startup fatal if missing in production. Distinct from `PROOF402_TOKEN_SECRET` so the two systems can rotate independently.

---

## Flow

### 1. Quote (`POST /v1/x402/quote`)

Request body:
```json
{ "product_id": "routing.telemetry", "agent_wallet": "rAgent..." }
```

Server response (HTTP 200):
```json
{
  "invoice_id": "01HQ7V9...",
  "product_id": "routing.telemetry",
  "price_drops": 50000,
  "currency": "RLUSD",
  "destination": "rNduuviQ3CCvHqWUTjJDD82Ko2tjqFGs3q",
  "memo_required": "01HQ7V9...",
  "expires_at": 1735689600,
  "agent_tier": "GOLD",
  "tier_discount_pct": 10,
  "token": "<base64payload>.<hmac>"
}
```

The `token` is the **pre-issued** x402 token, valid for `exp`. The client must pay `price_drops` RLUSD on XRPL with `memo_required` in the payment memo before calling dispense.

### 2. Dispense (`GET /v1/x402/dispense/{product_id}`)

Two modes:

**Mode A — no `X-Payment-Token` header:**
- Server returns HTTP **402 Payment Required**
- Header `X-Payment-Required: <invoice JSON>` (full quote inlined)
- Body: same invoice JSON, also human-readable

**Mode B — `X-Payment-Token: <token>` present:**
- Verify HMAC, `exp`, and `pid` matches the URL `{product_id}`
- Check `iid` against the nonce cache; reject if seen
- Call the catalog dispatcher for `pid`
- Mark `iid` consumed (TTL = original `exp` − `now` + 60s grace)
- Broadcast `X402_DISPENSED` on `metricsHub` with `product_id`, `wlt`, `tier`
- Return 200 with the product payload

**No XRPL ledger lookup in V1.** Issuing the token at quote time and not requiring a separate `/verify` step means the client can pay or not pay — the value of the product determines whether they bother. This is the same trust model as `four02proof.onrender.com` uses for sandbox-mode tokens, and is appropriate for the V1 surface (read-only telemetry). A ledger-verified `POST /v1/x402/verify` route can be added later as a hardening pass.

> Rationale: the quote-issues-token model keeps the dispense path pure CPU and replay-protected via `iid`. A leaked token is bounded by `exp` (5 min) and single-use (`iid`). The realistic threat — paying agent gets a token, doesn't actually pay, still consumes the product — is acceptable for V1 telemetry reads. Higher-value products (mint, bridge.priority) will require ledger verification in Phase 5.

---

## Product Catalog (V1)

Stored as a Go map in `internal/x402/catalog.go`. Only one product ships live in V1; three stubs are reserved with `Disabled: true`:

| ID | Status | Base Price (drops) | Dispatcher |
|----|--------|-------------------:|------------|
| `routing.telemetry` | LIVE | 50000 (0.05 RLUSD) | returns last 60s of `metricsHub` TPS samples + bridge counts + fee total |
| `bridge.attestation` | RESERVED | 100000 | future: signed attestation of a settled bridge tx |
| `bridge.priority` | RESERVED | 500000 | future: priority queue slot for a bridge route |
| `cube.mint` | RESERVED | 50000 | future: replace the 402Proof external call |

Tier discounts (catalog items):

| Tier | Discount |
|------|---------:|
| BRONZE | 0% |
| SILVER | 5% |
| GOLD | 10% |
| PLATINUM | 20% |
| DIAMOND | 30% |

Mirrors the loyalty BPS schedule for routing fees. Computed as `price - (price * discount_pct / 100)`, floored at 1 drop.

---

## Architecture

New package `internal/x402/`:

```
internal/x402/
├── token.go        — Encode/Decode/Sign/Verify (HMAC-SHA256 hex)
├── invoice.go      — Issue() — builds payload + signs token
├── catalog.go      — Product registry + dispatcher function map
├── nonce.go        — TTL'd replay cache (map[string]int64 of iid→exp)
├── token_test.go   — round-trip, expiry, tamper rejection
├── nonce_test.go   — replay rejection, TTL cleanup
└── catalog_test.go — tier discount math
```

Wired into `cmd/bridge/main.go`:

- New routes: `POST /v1/x402/quote`, `GET /v1/x402/dispense/{pid}`
- `/api/config` adds `x402_endpoint: "/v1/x402"` and `x402_products: [...]`
- `/health` adds `x402_dispensed: <counter>`
- Startup: `log.Fatalf` if `X402_TOKEN_SECRET == ""` (mirrors existing `ADMIN_TOKEN` fatal)
- Startup log line: `[SERVER] X402 Vendor: ARMED | Catalog: routing.telemetry`

Wired into `public/js/cube.js` + `public/index.html`:

- New `EVENT_CFG` entry: `X402_DISPENSED: { speed: 0.040, palette: 'pay', label: 'VEND', face: 'pz', edgeIdx: 1, delta: 2 }` (re-uses `pay` palette so we don't introduce a new color set in V1)
- Bottom-bar `X402 ✓` badge: add a brief `.x402-badge.flash` CSS class on dispense (300ms pulse, white→neon-purple), triggered by the WS frame.

---

## Loyalty Coupling

`Quote` calls `agentLedger.AgentStats(wallet)` to get the tier, then `catalog.Price(pid, tier)` applies the discount. The dispense path does **not** re-check tier — the price was already burned into the signed invoice. This decouples pricing from in-flight tier changes (an agent who upgrades to PLATINUM mid-invoice still pays the GOLD price they were quoted).

There's no fee invariant for catalog items (loyalty.go's `min 1 BPS` rule is about routing). Catalog prices floor at 1 drop, enforced in `catalog.Price`.

---

## Self-Audit

| Check | Approach |
|---|---|
| Secret rotation | `X402_TOKEN_SECRET` distinct from `PROOF402_TOKEN_SECRET`. Either can rotate without breaking the other. |
| Replay protection | `iid` (ULID) checked against in-memory nonce cache. TTL = token `exp` + 60s grace. Cleanup goroutine sweeps every 60s. |
| Token expiry | `exp` checked on every verify. 5-min window. |
| Tamper detection | HMAC over base64-encoded payload. Constant-time compare via `hmac.Equal`. |
| Startup fatal | Missing `X402_TOKEN_SECRET` exits 1 in prod. Same pattern as `ADMIN_TOKEN`. |
| Dispense isolation | Dispatcher functions are pure — no shared mutable state beyond what `metricsHub` already owns. |
| WS broadcast non-blocking | Existing `metricsHub.Broadcast` is already non-blocking per-client. No change. |
| Rate limiting | Falls under existing per-IP token bucket on the shared mux. `/v1/x402/dispense` inherits the same limiter as `/v1/bridge/execute` (20/min, burst 5). |

---

## What Is NOT Changed

- `loyalty.go`, `metrics_hub.go`, `fees.go`, `bridge.go` — untouched.
- `fetchCubeMintInvoice` — left in place. Cube mint continues to use external 402Proof in V1.
- SSE hub — untouched. WS metrics hub gets one new event type.
- Frontend SqueezeOS signal feed — untouched.
