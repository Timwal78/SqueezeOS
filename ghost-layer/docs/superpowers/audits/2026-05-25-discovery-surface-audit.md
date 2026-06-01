# Ghost Layer Discovery Surface Audit

**Date:** 2026-05-25
**Scope:** Diff every public discovery file against the live `cmd/bridge/main.go` route table
**Trigger:** Phase 1–4 shipped, beacons never updated, front door pointing to the wrong building
**Output:** Punch list of stale-vs-missing — direct input for the rewrite phase

---

## TL;DR

Ghost Layer has **7 discovery files** in production. They were written for an older API (`/api/ghost/bridge/*`) that does not exist in the current binary. An AI agent following the published spec gets 404 on every documented bridge route. **Zero discovery files mention the x402 vendor surface (`/v1/x402/*`) that we shipped yesterday.**

**Status by file:**

| File | Live in prod? | Accuracy | Recommended action |
|------|:------------:|:--------:|---|
| `/llms.txt` | ✅ | **STALE** — describes dead routes, missing all Phase 1–4 surface | **REWRITE** |
| `/robots.txt` | ✅ | ✅ accurate | Leave alone (AI crawler allowlist is correct) |
| `/sitemap.xml` | ✅ | ⚠️ minor — should also list /v1/x402/catalog | Add 1 URL |
| `/.well-known/openapi.json` | ✅ | **STALE** — 4 of 5 documented routes are dead | **REWRITE** |
| `/.well-known/mcp.json` | ✅ | **STALE** — 3 of 5 tools map to dead endpoints | **REWRITE** |
| `/.well-known/agents.json` | ✅ | **STALE** — references dead tools + dead audit URL | **REWRITE** |
| `/.well-known/server.json` | ✅ | ⚠️ minor — `_meta.audit` points at dead URL, otherwise OK | One-line fix |
| `/.well-known/ai-plugin.json` | ✅ | ⚠️ minor — points at the stale openapi.json, otherwise OK | Inherits openapi rewrite, no direct edit |

---

## Live route table (source of truth)

Extracted from `cmd/bridge/main.go` route registrations:

| Method | Path | Documented? |
|--------|------|:------------:|
| GET | `/health` | partial (server.json mentions health) |
| GET | `/api/agent/{addr}/stats` | ❌ undocumented |
| GET | `/api/config` | ❌ undocumented |
| GET | `/ws/metrics` | ❌ undocumented |
| GET | `/api/events` | partial (llms.txt mentions SSE in passing) |
| GET | `/v1/x402/catalog` | ❌ undocumented |
| POST | `/v1/x402/quote` | ❌ undocumented |
| GET | `/v1/x402/dispense/{pid}` | ❌ undocumented |
| POST | `/v1/bridge/execute` | ❌ undocumented (THE PRIMARY REVENUE PRODUCT) |
| GET, POST | `/mcp` | ✅ documented |
| POST | `/api/cube/pay/verify` | ❌ undocumented |
| GET, POST | `/api/cube/state` | ✅ documented |
| GET | `/api/cube/payload` | ❌ undocumented |
| GET | `/.well-known/mcp.json` | (serves the static file) |
| GET | `/.well-known/server.json` | (serves the static file) |

---

## Punch list by file

### 1. `/llms.txt` — REWRITE

**Dead content to rip out:**

- Lines 27–37 ("Agent Payment Flow — XRPL Path"): describes `POST /api/ghost/bridge` → returns `{bridge_id, pay_to, memo_hex}`. **This endpoint does not exist.** The real bridge is `POST /v1/bridge/execute` with an EIP-3009 signed payload + `gross_amount` + `fee_basis_points`.
- Lines 39–53 ("Base/EVM Path"): describes `POST /api/ghost/eip3009/authorize`. **Endpoint does not exist.** EIP-3009 is folded into `/v1/bridge/execute` via the `eip3009` field in the request payload.
- Lines 88–98 ("Audit Endpoint"): describes `GET /api/ghost/audit`. **Endpoint does not exist.** Closest live equivalent is `/health` + `/api/config`.
- Lines 122–131 ("MCP Server" — tool names): lists `ghost_bridge_health`, `ghost_layer_bridge`, `ghost_audit_stats`. These names map to the dead `/api/ghost/*` endpoints — need a full tool list audit (see mcp.json section).

**Stale data to correct:**

- Loyalty tier thresholds (lines 109–113) are in RLUSD whole units (`0.00–0.99 RLUSD = Bronze`). The live `internal/toll/loyalty.go` uses drops (`SILVER = 1_000_000` drops = 1 RLUSD). The numbers align (1M drops = 1 RLUSD) but units must be stated explicitly to avoid agent confusion.

**Missing entirely — add:**

- **`POST /v1/bridge/execute`** — the primary product. Request schema: `{source_wallet, destination_wallet, gross_amount, fee_basis_points, eip3009?, is_dust_test?}`. Returns `{status, transaction_hash, transparent_fee, net_delivered, agent_tier, effective_bps, treasury_routing}`.
- **`GET /v1/x402/catalog`** — list available institutional products.
- **`POST /v1/x402/quote`** — request a signed invoice for a catalog product. Body: `{product_id, agent_wallet, args?}`. Returns signed token + price (loyalty-discounted) + memo.
- **`GET /v1/x402/dispense/{pid}`** — HTTP 402 challenge if no `X-Payment-Token`; dispense if token valid.
- **`GET /api/agent/{addr}/stats`** — loyalty tier + total volume + discount BPS.
- **`GET /api/config`** — bootstrap config (ws_metrics_url, x402_endpoint, x402_products, etc).
- **`GET /ws/metrics`** — sovereign WebSocket stream. Frame schema: `{type, ts, total_bridges, tps, accumulated_fee, chain?, tx_hash?, gross_amount?, net_amount?, fee_amount?, agent_tier?, effective_bps?, product_id?, wallet?}`. Event types: `BRIDGE_SETTLED`, `AGENT_PROBE`, `X402_DISPENSED`, `HEARTBEAT`, `CONNECTED`.

**Estimated rewrite size:** ~50% of llms.txt is dead or wrong. Cleaner to write from scratch than to patch.

---

### 2. `/.well-known/openapi.json` — REWRITE

**Dead operations (must remove):**

| `operationId` | Path | Status |
|---|---|---|
| `initiateBridge` | `POST /api/ghost/bridge` | DEAD |
| `getBridgeStatus` | `GET /api/ghost/bridge/{bridge_id}` | DEAD |
| `eip3009Authorize` | `POST /api/ghost/eip3009/authorize` | DEAD |
| `getAuditStats` | `GET /api/ghost/audit` | DEAD |
| `mintCubeState` | `POST /api/cube/state` | ✅ LIVE — keep |

**Missing operations (must add):**

- `executeBridge` — `POST /v1/bridge/execute` (the primary product)
- `getX402Catalog` — `GET /v1/x402/catalog`
- `requestX402Quote` — `POST /v1/x402/quote`
- `dispenseX402Product` — `GET /v1/x402/dispense/{pid}` (with 402 challenge response documented)
- `getAgentStats` — `GET /api/agent/{addr}/stats`
- `getServerConfig` — `GET /api/config`

**Schemas to add to `components.schemas`:**

- `BridgeExecuteRequest` — `{source_wallet, destination_wallet, gross_amount, fee_basis_points, eip3009?: EIP3009Payload, is_dust_test?: bool}`
- `BridgeExecuteResponse` — `{status, transaction_hash, gross_processed, transparent_fee, net_delivered, treasury_routing, agent_tier, effective_bps}`
- `X402Catalog` — `{products: [{id, name, base_price_drops, available}]}`
- `X402Invoice` — `{invoice_id, product_id, price_drops, currency, destination, memo_required, expires_at, agent_tier, tier_discount_pct, token}`
- `X402DispenseChallenge` — same shape as `X402Invoice`, returned with HTTP 402
- `AgentStats` — `{agent, tier, total_volume, discount_bps, effective_bps_at_50}`
- `ConfigResponse` — the `/api/config` body

**Keep:** `BridgeResult`, `ComplianceReceipt`, `FaceState`, `CubeMintResult`. Cube schemas are still valid.

**Note:** the `info.x-agent-instructions` field is still mostly correct (payment is mandatory, identity headers, 402Proof tokens) but should be augmented to mention the **native** x402 surface as an alternative to 402Proof.

---

### 3. `/.well-known/mcp.json` — REWRITE

**Dead tools (need re-mapping or removal):**

| `name` | Maps to | Status |
|---|---|---|
| `ghost_layer_bridge` | dead `/api/ghost/bridge` | RENAME + RE-MAP to `/v1/bridge/execute` |
| `ghost_bridge_status` | dead `/api/ghost/bridge/{id}` | REMOVE (no status-by-id route exists in current main.go) |
| `ghost_audit_stats` | dead `/api/ghost/audit` | REPLACE with a tool that reads `/api/config` + `/health` |
| `cube_state_mint` | live `/api/cube/state` | ✅ KEEP |
| `eip3009_authorize` | dead `/api/ghost/eip3009/authorize` | REMOVE (folded into the rewritten `ghost_layer_bridge` tool, which now accepts an `eip3009` sub-object) |

**Missing tools (add):**

- `x402_catalog` — list available products
- `x402_quote` — request a signed invoice
- `x402_dispense` — fetch a product with an existing token
- `agent_stats` — loyalty lookup by wallet

**Other corrections:**

- Top-level `payment_protocol: "x402"` — true, **but** the doc implies external (402Proof). Should add a `native_x402_endpoint: "/v1/x402"` field so MCP clients know Ghost Layer is itself a vendor, not just a payment-required service.
- `version: "2.2.0"` — bump to `3.0.0` to signal the breaking API change (path prefix `/api/ghost/*` → `/v1/*`).

---

### 4. `/.well-known/agents.json` — REWRITE

**Issues:**

- `tools` array (lines 18–23) lists tool names by string with `cost` but no endpoint mapping. Three of the four (`ghost_bridge_health`, `ghost_layer_bridge`, `ghost_audit_stats`) map to dead routes through their names. Either replace with the rewritten mcp.json tool list, or remove the array and reference mcp.json as the single source of truth.
- `sse_events` (line 24) lists 4 events; live cube reacts to **9** event types including the new `X402_DISPENSED`. Add the missing ones or trim the list to what's actually broadcast over `/api/events` (legacy SSE) vs `/ws/metrics` (sovereign WS). Honestly recommend splitting into two arrays: `sse_events` and `ws_events`.
- `payment_gateway: "https://four02proof.onrender.com"` — half-true. Ghost Layer is **also** a native x402 vendor now. Should be two fields: `external_payment_gateway` and `native_x402_endpoint`.

**Missing:**

- No mention of `/ws/metrics` or the WebSocket capability
- No mention of `/v1/x402/*` catalog
- No mention of `/api/agent/{addr}/stats`

---

### 5. `/.well-known/server.json` — ONE-LINE FIX

The MCP-registry server descriptor is **almost correct.** It only references `mcp_endpoint` (live) and `tags` (still accurate). One stale field:

- Line 48 `_meta.io.modelcontextprotocol.registry/publisher-provided.audit` → `"https://ghost-layer.onrender.com/api/ghost/audit"`. Dead URL. **Replace with `/health` or remove.**

The `tags` array is good and includes `agent-economy` and `micropayment` which still draw the right crawlers.

`version: "2.1.0"` — bump to match the mcp.json version bump.

---

### 6. `/.well-known/ai-plugin.json` — NO DIRECT EDIT

This file is a thin wrapper that points at openapi.json. Once openapi.json is rewritten, ai-plugin.json automatically becomes accurate. **The two text fields (`description_for_human` and `description_for_model`) should be reviewed for accuracy** — `description_for_model` currently says "Payment is mandatory for bridge operations — anonymous requests are tarpitted." That's still true. Leave alone unless we want to mention the x402 product catalog.

The `verification_tokens.openai` field is for OpenAI plugin store registration. Harmless if unused.

---

### 7. `/robots.txt` — NO CHANGES

The crawler allowlist is comprehensive and correct: GPTBot, ClaudeBot, anthropic-ai, OAI-SearchBot, PerplexityBot, CCBot, YouBot, cohere-ai, DuckAssistBot, ByteSpider, Applebot, Amazonbot, Bingbot, ChatGPT-User, Claude-Web. Sitemap reference is correct. **Leave alone.**

---

### 8. `/sitemap.xml` — ONE URL ADDITION

Add an entry for `/v1/x402/catalog` so AI crawlers indexing the sitemap discover the catalog endpoint without needing to read llms.txt first.

---

## Cross-cutting issues

1. **Version mismatch.** openapi (`2.1.0`), mcp.json (`2.2.0`), server.json (`2.1.0`). Phase 4 shipped a meaningful API addition. Bump all three to `3.0.0` and document the API change in CHANGELOG terms within llms.txt.

2. **No mention of the native x402 protocol surface anywhere.** Every file says `payment_protocol: x402` but none of them describe the quote/dispense flow on Ghost Layer's own endpoints. An agent reading these files thinks payment goes through `four02proof.onrender.com` exclusively.

3. **Loyalty thresholds need explicit units everywhere.** llms.txt says "RLUSD". loyalty.go uses drops. The relationship (1M drops = 1 RLUSD) is implicit. Pick a unit and state it.

4. **WebSocket capability invisible.** The most agent-friendly new feature (`/ws/metrics` real-time bridge events) is documented in zero discovery files.

5. **Frame schema for the WS stream needs publishing.** Without a documented `MetricsFrame` shape, any agent that connects will have to reverse-engineer the wire format from the live stream.

---

## Recommended rewrite order

1. **`llms.txt`** — highest-leverage. AI agents read this first and treat it as the authoritative narrative. Rewrite covers all Phase 1–4 surface.
2. **`openapi.json`** — agents using the OpenAPI path are programmatic; must be 100% accurate. Once this is right, `ai-plugin.json` is automatically right.
3. **`mcp.json`** — MCP clients (Smithery, Claude Desktop, Cursor) need correct tool mappings.
4. **`agents.json`** — secondary; references the other three.
5. **`server.json`** — one-line fix, low priority.
6. **`sitemap.xml`** — one URL add, low priority.

Each rewrite is a contained PR. None of them touch live Go code.

---

## What this audit does NOT cover

- **The Render service's actual responses.** This audit reads the route table from source; it does not curl prod to confirm the live binary matches the source. Recommend a post-rewrite verification: extend `cmd/x402probe` or add `cmd/discoveryprobe` that fetches each documented endpoint and asserts non-404 + schema match.
- **Google Search Console submission.** Sitemap auto-resubmission via the GSC API is a separate piece of work (needs GSC property verification + OAuth token). Not in scope here.
- **SqueezeOS or 402Proof discovery files.** Audit limited to Ghost Layer.
