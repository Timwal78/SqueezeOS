# Ghost Layer bridge.attestation — Design

**Date:** 2026-05-25
**Scope:** First real institutional product on the x402 catalog — Ed25519-signed cryptographic proof of a settled bridge transaction
**Branch:** `claude/bridge-attestation`
**Predecessor:** M2M-VENDING-01 Phase 4 (native x402 vendor, `routing.telemetry` live)

---

## Problem Statement

`routing.telemetry` proved the x402 wire end-to-end but isn't worth 0.05 RLUSD to anyone — the data it returns (`tps`, `total_bridges`, `accumulated_fee`) is global state any unauthenticated caller can derive from the public WebSocket stream.

`bridge.attestation` is the first product on the shelf with a real buyer. It returns a **cryptographically signed envelope** of facts about a specific bridge tx that *cannot be derived from the on-chain transaction alone*: which Ghost Layer route it took, the fee split, the loyalty tier discount applied at settle time, and Ghost Layer's signed assertion that the settlement actually went through this gateway. The buyer is a compliance team, a counterparty reconciling cross-chain books, an insurer arbitrating a dispute, or the agent itself building an audit trail.

The signature is **Ed25519, not HMAC.** A symmetric MAC means the verifier has to trust Ghost Layer's word that the token is valid — that's an oracle, not an attestation. An institutional product needs offline third-party verifiability against a published public key.

---

## Goals

1. **Third-party verifiable.** Ghost Layer signs each attestation with an Ed25519 private key held server-side. The matching public key is published at `GET /v1/x402/attestation/pubkey`. Any verifier can validate offline.
2. **Bound to a real settlement.** The server only issues an invoice for `bridge.attestation` if the `tx_hash` argument exists in the in-memory bridge ledger. No attestations of nonexistent bridges.
3. **Loyalty-aware pricing.** Same tier discount schedule as `routing.telemetry`. Base price 100000 drops (0.10 RLUSD), DIAMOND pays 70000.
4. **Canonical signing format.** A `CanonicalBytes(envelope)` function builds the signed message by concatenating fields in a fixed order. Same function ports trivially to a JS/Python verifier.
5. **Zero new external deps.** Go stdlib `crypto/ed25519` is sufficient.

---

## Non-Goals (this phase)

- Off-chain attestation registry / inclusion proofs. The attestation is a standalone signed JSON document; it is not anchored on-chain.
- Batched attestations.
- Revocation lists. An issued attestation is valid as long as the public key is recognized.
- Multi-sig / threshold signing.
- Key rotation tooling. V1 reads one key from env; rotation = redeploy with new key + publish a `previous_pubkey` field at the discovery endpoint when the time comes.
- Persistence of the bridge ledger. Settlement records live in memory and are lost on restart, matching the existing pattern for `_futures`, `_settlements`, `_listings` in `core/api/`.

---

## Attestation Envelope

```json
{
  "version": "1.0",
  "attestation_id": "<24-char hex>",
  "bridge_id": "<24-char hex, server-issued at settle time>",
  "tx_hash": "<XRPL or Base tx hash>",
  "chain": "xrpl|base",
  "source_wallet": "rAgent... or 0x...",
  "destination_wallet": "rDest... or 0x...",
  "gross_amount": "<big.Int string, drops or wei>",
  "fee_amount":   "<big.Int string>",
  "net_amount":   "<big.Int string>",
  "effective_bps": 50,
  "agent_tier": "GOLD",
  "settled_at": 1779751791,
  "issued_at":  1779751800,
  "issuer": "ghost-layer.onrender.com",
  "signature_alg": "ed25519",
  "signature": "<hex(ed25519.Sign(privkey, CanonicalBytes(envelope)))>"
}
```

`CanonicalBytes` concatenates the field values in **fixed order**, each followed by `\n`:
```
version | attestation_id | bridge_id | tx_hash | chain |
source_wallet | destination_wallet | gross_amount | fee_amount |
net_amount | effective_bps | agent_tier | settled_at | issued_at |
issuer | signature_alg
```

The `signature` field itself is excluded from the canonical bytes. Verifier rebuilds the same string from the JSON, runs `ed25519.Verify(pubkey, msg, sig)`.

---

## Bridge Ledger

New package `internal/ledger/`. In-memory bounded store of every settled bridge tx.

```
internal/ledger/
├── bridge.go        — BridgeRecord struct, Ledger with sync.RWMutex
├── bridge_test.go   — record/lookup, max-size FIFO eviction
```

- `Record(rec BridgeRecord)` — inserts; if size > `MaxRecords` (10000), evicts the oldest entry.
- `Lookup(txHash string) (BridgeRecord, bool)` — O(1) lookup.
- Eviction order tracked via a parallel slice of insertion-ordered tx_hashes; not LRU. Trade-off: simpler, and "first 10000 settled bridges" is fine for a single Render dyno's working set.

Populated from `cmd/bridge/main.go` immediately after `RouteTransactionWithDisclosure` succeeds, before the broadcast calls.

---

## Dispatcher Signature Change

`internal/x402/catalog.go`:

```go
// Before:
Dispatcher func() (json.RawMessage, error)
// After:
Dispatcher func(args map[string]any) (json.RawMessage, error)
```

`routing.telemetry`'s existing dispatcher gets a one-character change (`func()` → `func(_ map[string]any)`). The new `bridge.attestation` dispatcher reads `args["tx_hash"]` to find the settlement record, builds the envelope, signs, returns.

`internal/x402/token.go` `Payload`:

```go
type Payload struct {
    Pid  string         `json:"pid"`
    Wlt  string         `json:"wlt"`
    Iid  string         `json:"iid"`
    Exp  int64          `json:"exp"`
    Tier string         `json:"tier"`
    Args map[string]any `json:"args,omitempty"` // NEW
}
```

Quote request body grows one optional field:

```json
{
  "product_id": "bridge.attestation",
  "agent_wallet": "rAgent...",
  "args": { "tx_hash": "ABC123..." }
}
```

For products that don't take args (`routing.telemetry`), `args` is omitted and the token's `args` field is absent.

---

## Pre-Quote Validation

At quote time, the server checks if the product wants any per-arg validation:

| Product | Validation |
|---------|------------|
| `routing.telemetry` | none |
| `bridge.attestation` | `args.tx_hash` must exist in `bridgeLedger` |

If validation fails → `404 ERR_BRIDGE_NOT_FOUND`. No invoice issued, no x402 payment wasted on an attestation of nothing.

This is a per-product validator function, not a generic preflight. Defined inline in `cmd/bridge/main.go`'s quote handler — keeping the validation logic close to the lookup keeps cognitive overhead low.

---

## Public Key Discovery

New route: `GET /v1/x402/attestation/pubkey`

```json
{
  "algorithm": "ed25519",
  "public_key_hex": "<32 bytes hex>",
  "issuer": "ghost-layer.onrender.com",
  "version": "1.0"
}
```

Optionally surfaced in `/api/config` under `x402_attestation_pubkey` so client libs cache it on bootstrap.

---

## Pricing

Tier discount table from `loyalty.go` (already imported by `x402.Price`):

| Tier | Price (drops) | RLUSD |
|------|--------------:|------:|
| BRONZE   | 100000 | 0.10 |
| SILVER   |  95000 | 0.095 |
| GOLD     |  90000 | 0.09 |
| PLATINUM |  80000 | 0.08 |
| DIAMOND  |  70000 | 0.07 |

Tier resolved from `agentLedger.AgentStats(agent_wallet)` at quote time.

---

## Architecture

```
internal/ledger/
├── bridge.go              [NEW]   — BridgeRecord + Ledger (bounded in-memory)
├── bridge_test.go         [NEW]

internal/x402/
├── attestation.go         [NEW]   — Envelope, CanonicalBytes, Sign, Verify
├── attestation_test.go    [NEW]   — sign/verify roundtrip, tamper, missing-key
├── catalog.go             [MOD]   — Dispatcher signature now accepts args
├── token.go               [MOD]   — Payload + Args field

cmd/bridge/main.go         [MOD]
├── ATTESTATION_PRIVATE_KEY startup fatal
├── attestationPrivKey + attestationPubKey globals (loaded at boot)
├── bridgeLedger global   = ledger.NewLedger(10000)
├── bridgeLedger.Record(...) after RouteTransactionWithDisclosure succeeds
├── x402Registry: bridge.attestation now LIVE with dispatcher
├── Quote handler: pre-quote validation for bridge.attestation
├── New route: GET /v1/x402/attestation/pubkey
├── /api/config: +x402_attestation_pubkey
```

No frontend changes. The cube already reacts to `X402_DISPENSED` regardless of which product was dispensed.

---

## Self-Audit

| Check | Approach |
|---|---|
| Third-party verifiable | Ed25519, public key published, canonical bytes deterministic |
| Forgery-resistant | Signing is Ed25519 — verifier doesn't need the private key |
| Tamper detection | Verifier rebuilds canonical bytes from JSON; any field change → signature mismatch |
| Bound to real settlement | Pre-quote validation: tx_hash must exist in `bridgeLedger` |
| Replay protection | Existing nonce cache covers the dispense token; the envelope itself is reusable evidence by design |
| Private key safety | `ATTESTATION_PRIVATE_KEY` env var; startup fatal if missing; loaded once at boot, held in a `var` not re-read |
| Canonical format port | Field concatenation in fixed order makes a 30-line JS/Python verifier feasible |
| Ledger memory bound | `MaxRecords` 10000 with FIFO eviction; bounded per-dyno memory |
| Loyalty integration | Same `x402.Price(base, tier)` used by all catalog products |
| Catalog discovery | `bridge.attestation` flips from `Disabled: true` to live; surfaces in `/v1/x402/catalog` |

---

## What Is NOT Changed

- `loyalty.go`, `metrics_hub.go`, `fees.go`, `bridge.go` — untouched
- `routing.telemetry` — still live, only dispatcher signature changes (one-char `func()` → `func(_ map[string]any)`)
- `cube.js` / `index.html` — no change. The cube reacts to any `X402_DISPENSED` event by product-agnostic palette swap.
- 402Proof integration for Cube mint — untouched. Cube mint still goes through `four02proof.onrender.com`.
- `X402_TOKEN_SECRET` — unchanged. HMAC still gates the dispense path; Ed25519 only signs the attestation payload itself.

---

## Future Work (post-V1)

- **Persistence.** Bridge ledger on disk so attestations survive restarts. SQLite is the natural choice (no new infra), but adds a dep. Defer until restart-loss becomes a real complaint.
- **Inclusion proofs.** Anchor a Merkle root of issued attestations to XRPL/Xahau periodically. Makes the attestation set provably append-only.
- **Multi-version pubkey discovery.** When the first key rotation happens, `/v1/x402/attestation/pubkey` returns an array of `{key_id, public_key_hex, valid_from, valid_until}` so old attestations still verify.
- **Counterparty lookup.** Currently anyone with the `tx_hash` can request an attestation. A future hardening pass might require the requester to prove they're a party to the tx (signed challenge from the source or destination wallet).
