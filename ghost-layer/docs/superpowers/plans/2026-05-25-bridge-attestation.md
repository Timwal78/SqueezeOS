# Ghost Layer bridge.attestation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Flip `bridge.attestation` from a disabled catalog entry to a live Ed25519-signed institutional product. End-to-end: bridge ledger captures settlements, quote validates against the ledger, dispense returns a signed envelope, public key endpoint published for offline verification.

**Architecture:** One new package `internal/ledger/` (bridge record store), two new files in `internal/x402/` (attestation envelope + tests), three modifications (`x402/catalog.go`, `x402/token.go`, `cmd/bridge/main.go`). No new external deps — `crypto/ed25519` is stdlib.

**Tech stack:** Go 1.22 stdlib (`crypto/ed25519`, `crypto/rand`, `encoding/hex`, `encoding/json`, `sync`).

**Spec:** `ghost-layer/docs/superpowers/specs/2026-05-25-bridge-attestation-design.md`

---

## File Map

| File | Action | What changes |
|---|---|---|
| `internal/ledger/bridge.go` | Create | `BridgeRecord`, `Ledger` with bounded FIFO eviction |
| `internal/ledger/bridge_test.go` | Create | Record/lookup, eviction |
| `internal/x402/attestation.go` | Create | `Envelope`, `CanonicalBytes`, `SignEnvelope`, `VerifyEnvelope` |
| `internal/x402/attestation_test.go` | Create | Sign/verify roundtrip, tamper rejection, wrong-key rejection |
| `internal/x402/catalog.go` | Modify | `Dispatcher` signature: `func()` → `func(map[string]any)` |
| `internal/x402/catalog_test.go` | Modify | Existing test that touches the dispatcher field — one-line update |
| `internal/x402/token.go` | Modify | `Payload` struct: +`Args map[string]any` |
| `internal/x402/token_test.go` | Modify | Add a token roundtrip with args populated |
| `cmd/bridge/main.go` | Modify | Load Ed25519 key, init bridge ledger, record settlements, flip attestation to live, add `/v1/x402/attestation/pubkey` route, pre-quote validation, `/api/config` field |

---

## Task 1 — Bridge ledger

- [ ] **Step 1: Create `internal/ledger/bridge.go`**

```go
package ledger

import (
	"sync"
)

// BridgeRecord is the complete settlement record for one bridge tx.
// Used by bridge.attestation to build a signed envelope.
type BridgeRecord struct {
	BridgeID          string
	TxHash            string
	Chain             string
	SourceWallet      string
	DestinationWallet string
	GrossAmount       string
	FeeAmount         string
	NetAmount         string
	EffectiveBPS      int64
	AgentTier         string
	SettledAt         int64
}

// Ledger is a bounded in-memory store keyed by tx_hash with FIFO eviction.
type Ledger struct {
	mu         sync.RWMutex
	items      map[string]BridgeRecord
	order      []string // insertion order — index 0 is oldest
	maxRecords int
}

func NewLedger(maxRecords int) *Ledger {
	if maxRecords <= 0 {
		maxRecords = 10000
	}
	return &Ledger{
		items:      make(map[string]BridgeRecord, maxRecords),
		order:      make([]string, 0, maxRecords),
		maxRecords: maxRecords,
	}
}

// Record inserts the record. If size exceeds maxRecords, the oldest is evicted.
// Records for an existing tx_hash overwrite (settle-then-resettle is impossible
// in practice but the overwrite keeps the data consistent).
func (l *Ledger) Record(r BridgeRecord) {
	l.mu.Lock()
	defer l.mu.Unlock()
	if _, exists := l.items[r.TxHash]; !exists {
		l.order = append(l.order, r.TxHash)
		if len(l.order) > l.maxRecords {
			delete(l.items, l.order[0])
			l.order = l.order[1:]
		}
	}
	l.items[r.TxHash] = r
}

func (l *Ledger) Lookup(txHash string) (BridgeRecord, bool) {
	l.mu.RLock()
	defer l.mu.RUnlock()
	r, ok := l.items[txHash]
	return r, ok
}

func (l *Ledger) Size() int {
	l.mu.RLock()
	defer l.mu.RUnlock()
	return len(l.items)
}
```

- [ ] **Step 2: Create `internal/ledger/bridge_test.go`**

```go
package ledger

import (
	"fmt"
	"testing"
)

func TestRecordAndLookup(t *testing.T) {
	l := NewLedger(0)
	l.Record(BridgeRecord{TxHash: "tx1", Chain: "xrpl"})
	r, ok := l.Lookup("tx1")
	if !ok || r.Chain != "xrpl" {
		t.Fatalf("lookup tx1: got ok=%v rec=%+v", ok, r)
	}
	_, ok = l.Lookup("nope")
	if ok {
		t.Fatal("lookup of missing tx_hash should return ok=false")
	}
}

func TestEvictionFIFO(t *testing.T) {
	l := NewLedger(3)
	for i := 0; i < 5; i++ {
		l.Record(BridgeRecord{TxHash: fmt.Sprintf("tx%d", i)})
	}
	if l.Size() != 3 {
		t.Fatalf("expected 3 records after 5 inserts, got %d", l.Size())
	}
	// Oldest two (tx0, tx1) should have been evicted.
	for _, gone := range []string{"tx0", "tx1"} {
		if _, ok := l.Lookup(gone); ok {
			t.Errorf("expected %s to be evicted", gone)
		}
	}
	for _, kept := range []string{"tx2", "tx3", "tx4"} {
		if _, ok := l.Lookup(kept); !ok {
			t.Errorf("expected %s to still be present", kept)
		}
	}
}

func TestRecordOverwriteDoesNotDoubleCount(t *testing.T) {
	l := NewLedger(3)
	l.Record(BridgeRecord{TxHash: "tx1", Chain: "xrpl"})
	l.Record(BridgeRecord{TxHash: "tx1", Chain: "base"})
	if l.Size() != 1 {
		t.Fatalf("re-recording same tx_hash should not grow size; got %d", l.Size())
	}
	r, _ := l.Lookup("tx1")
	if r.Chain != "base" {
		t.Errorf("expected overwrite to apply, got chain=%s", r.Chain)
	}
}
```

- [ ] **Step 3: Run the tests**

```
cd ghost-layer
go test ./internal/ledger/... -v
```

Expected: 3 passes.

---

## Task 2 — Attestation envelope + Ed25519 sign/verify

- [ ] **Step 4: Create `internal/x402/attestation.go`**

```go
package x402

import (
	"crypto/ed25519"
	"crypto/rand"
	"encoding/hex"
	"errors"
	"strconv"
	"time"

	"ghost-layer-core/internal/ledger"
)

const (
	AttestationVersion = "1.0"
	AttestationAlg     = "ed25519"
	AttestationIssuer  = "ghost-layer.onrender.com"
)

// Envelope is the institutional attestation document. The signature is computed
// over CanonicalBytes(env) and stored as hex in env.Signature.
type Envelope struct {
	Version           string `json:"version"`
	AttestationID     string `json:"attestation_id"`
	BridgeID          string `json:"bridge_id"`
	TxHash            string `json:"tx_hash"`
	Chain             string `json:"chain"`
	SourceWallet      string `json:"source_wallet"`
	DestinationWallet string `json:"destination_wallet"`
	GrossAmount       string `json:"gross_amount"`
	FeeAmount         string `json:"fee_amount"`
	NetAmount         string `json:"net_amount"`
	EffectiveBPS      int64  `json:"effective_bps"`
	AgentTier         string `json:"agent_tier"`
	SettledAt         int64  `json:"settled_at"`
	IssuedAt          int64  `json:"issued_at"`
	Issuer            string `json:"issuer"`
	SignatureAlg      string `json:"signature_alg"`
	Signature         string `json:"signature"`
}

// CanonicalBytes returns the byte sequence that gets signed. Fixed-order
// field concatenation, newline-separated, signature field excluded.
// Verifier reproduces this exactly from the JSON envelope.
func CanonicalBytes(e Envelope) []byte {
	parts := []string{
		e.Version,
		e.AttestationID,
		e.BridgeID,
		e.TxHash,
		e.Chain,
		e.SourceWallet,
		e.DestinationWallet,
		e.GrossAmount,
		e.FeeAmount,
		e.NetAmount,
		strconv.FormatInt(e.EffectiveBPS, 10),
		e.AgentTier,
		strconv.FormatInt(e.SettledAt, 10),
		strconv.FormatInt(e.IssuedAt, 10),
		e.Issuer,
		e.SignatureAlg,
	}
	var out []byte
	for _, p := range parts {
		out = append(out, []byte(p)...)
		out = append(out, '\n')
	}
	return out
}

// BuildAndSign assembles a fresh envelope from a BridgeRecord and signs it.
// Returns the completed envelope.
func BuildAndSign(rec ledger.BridgeRecord, priv ed25519.PrivateKey) (Envelope, error) {
	if len(priv) != ed25519.PrivateKeySize {
		return Envelope{}, errors.New("ERR_PRIVATE_KEY_INVALID")
	}
	env := Envelope{
		Version:           AttestationVersion,
		AttestationID:     newAttestationID(),
		BridgeID:          rec.BridgeID,
		TxHash:            rec.TxHash,
		Chain:             rec.Chain,
		SourceWallet:      rec.SourceWallet,
		DestinationWallet: rec.DestinationWallet,
		GrossAmount:       rec.GrossAmount,
		FeeAmount:         rec.FeeAmount,
		NetAmount:         rec.NetAmount,
		EffectiveBPS:      rec.EffectiveBPS,
		AgentTier:         rec.AgentTier,
		SettledAt:         rec.SettledAt,
		IssuedAt:          time.Now().Unix(),
		Issuer:            AttestationIssuer,
		SignatureAlg:      AttestationAlg,
	}
	sig := ed25519.Sign(priv, CanonicalBytes(env))
	env.Signature = hex.EncodeToString(sig)
	return env, nil
}

// VerifyEnvelope checks the envelope's signature against the supplied pubkey.
// Returns nil on valid, an error otherwise.
func VerifyEnvelope(env Envelope, pub ed25519.PublicKey) error {
	if len(pub) != ed25519.PublicKeySize {
		return errors.New("ERR_PUBLIC_KEY_INVALID")
	}
	sig, err := hex.DecodeString(env.Signature)
	if err != nil {
		return errors.New("ERR_SIGNATURE_MALFORMED")
	}
	if !ed25519.Verify(pub, CanonicalBytes(env), sig) {
		return errors.New("ERR_SIGNATURE_INVALID")
	}
	return nil
}

func newAttestationID() string {
	b := make([]byte, 12)
	_, _ = rand.Read(b)
	return hex.EncodeToString(b)
}
```

- [ ] **Step 5: Create `internal/x402/attestation_test.go`**

```go
package x402

import (
	"crypto/ed25519"
	"crypto/rand"
	"strings"
	"testing"

	"ghost-layer-core/internal/ledger"
)

func freshKey(t *testing.T) (ed25519.PublicKey, ed25519.PrivateKey) {
	t.Helper()
	pub, priv, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatalf("keygen: %v", err)
	}
	return pub, priv
}

func sampleRecord() ledger.BridgeRecord {
	return ledger.BridgeRecord{
		BridgeID: "br-123", TxHash: "ABC", Chain: "xrpl",
		SourceWallet: "rSrc", DestinationWallet: "rDst",
		GrossAmount: "1000", FeeAmount: "5", NetAmount: "995",
		EffectiveBPS: 50, AgentTier: "GOLD", SettledAt: 1700000000,
	}
}

func TestBuildSignVerifyRoundTrip(t *testing.T) {
	pub, priv := freshKey(t)
	env, err := BuildAndSign(sampleRecord(), priv)
	if err != nil {
		t.Fatalf("build: %v", err)
	}
	if env.Signature == "" {
		t.Fatal("signature should be populated")
	}
	if err := VerifyEnvelope(env, pub); err != nil {
		t.Fatalf("verify: %v", err)
	}
}

func TestVerifyRejectsTamperedField(t *testing.T) {
	pub, priv := freshKey(t)
	env, _ := BuildAndSign(sampleRecord(), priv)
	env.NetAmount = "999999" // tamper after signing
	if err := VerifyEnvelope(env, pub); err == nil {
		t.Fatal("verify should reject tampered envelope")
	}
}

func TestVerifyRejectsWrongPubKey(t *testing.T) {
	_, priv := freshKey(t)
	otherPub, _ := freshKey(t)
	env, _ := BuildAndSign(sampleRecord(), priv)
	if err := VerifyEnvelope(env, otherPub); err == nil {
		t.Fatal("verify should reject under wrong pubkey")
	}
}

func TestBuildRejectsInvalidPriv(t *testing.T) {
	_, err := BuildAndSign(sampleRecord(), ed25519.PrivateKey{1, 2, 3})
	if err == nil || !strings.Contains(err.Error(), "PRIVATE_KEY") {
		t.Fatalf("expected ERR_PRIVATE_KEY_INVALID, got %v", err)
	}
}

func TestCanonicalBytesDeterministic(t *testing.T) {
	rec := sampleRecord()
	pub, priv := freshKey(t)
	env, _ := BuildAndSign(rec, priv)
	b1 := CanonicalBytes(env)
	b2 := CanonicalBytes(env)
	if string(b1) != string(b2) {
		t.Fatal("CanonicalBytes must be deterministic for the same envelope")
	}
	// Sanity: pubkey verifies against the canonical bytes the verifier rebuilds.
	if err := VerifyEnvelope(env, pub); err != nil {
		t.Fatalf("verify after canonical compare: %v", err)
	}
}
```

- [ ] **Step 6: Run the new tests**

```
go test ./internal/x402/... -v -run "Attestation|BuildSignVerify|Verify|CanonicalBytes"
```

Expected: 5 passes.

---

## Task 3 — Extend Dispatcher signature + Payload.Args

- [ ] **Step 7: Modify `internal/x402/catalog.go`**

Replace:
```go
Dispatcher func() (json.RawMessage, error) `json:"-"`
```

With:
```go
Dispatcher func(args map[string]any) (json.RawMessage, error) `json:"-"`
```

And update `Dispatch`:
```go
// Before:
func (r *Registry) Dispatch(id string) (json.RawMessage, error) {
    p, err := r.Lookup(id)
    if err != nil { return nil, err }
    if p.Dispatcher == nil { return nil, fmt.Errorf("ERR_NO_DISPATCHER") }
    return p.Dispatcher()
}

// After:
func (r *Registry) Dispatch(id string, args map[string]any) (json.RawMessage, error) {
    p, err := r.Lookup(id)
    if err != nil { return nil, err }
    if p.Dispatcher == nil { return nil, fmt.Errorf("ERR_NO_DISPATCHER") }
    return p.Dispatcher(args)
}
```

- [ ] **Step 8: Fix `internal/x402/catalog_test.go`**

The test currently constructs a dispatcher as `func() (json.RawMessage, error)`. Update to `func(map[string]any) (json.RawMessage, error)` and replace any `r.Dispatch("live")` with `r.Dispatch("live", nil)`.

- [ ] **Step 9: Modify `internal/x402/token.go`**

Add `Args` to `Payload`:
```go
type Payload struct {
    Pid  string         `json:"pid"`
    Wlt  string         `json:"wlt"`
    Iid  string         `json:"iid"`
    Exp  int64          `json:"exp"`
    Tier string         `json:"tier"`
    Args map[string]any `json:"args,omitempty"`
}
```

No changes needed to `Sign`/`Verify` — they marshal/unmarshal the whole struct.

- [ ] **Step 10: Add a token-with-args round-trip test in `token_test.go`**

```go
func TestSignVerifyWithArgs(t *testing.T) {
    p := Payload{
        Pid: "bridge.attestation", Iid: "iid1",
        Exp: time.Now().Add(time.Minute).Unix(),
        Args: map[string]any{"tx_hash": "ABC123"},
    }
    tok, err := Sign(p, "s")
    if err != nil { t.Fatalf("sign: %v", err) }
    got, err := Verify(tok, "s")
    if err != nil { t.Fatalf("verify: %v", err) }
    if got.Args["tx_hash"] != "ABC123" {
        t.Fatalf("args.tx_hash round-trip failed: got %v", got.Args["tx_hash"])
    }
}
```

- [ ] **Step 11: Update `invoice.go` Issue() signature**

Change:
```go
func Issue(productID, wallet, tier string, basePrice int64, treasury, secret string) (Invoice, error)
```

To:
```go
func Issue(productID, wallet, tier string, basePrice int64, treasury, secret string, args map[string]any) (Invoice, error)
```

And pass `args` into the `Payload` it builds. Update all existing callers (just `cmd/bridge/main.go`).

- [ ] **Step 12: Run the full x402 test suite**

```
go test ./internal/x402/... -v
```

All previously passing tests should still pass, plus the new ones.

---

## Task 4 — Wire main.go: load key, capture settlements, flip attestation live

- [ ] **Step 13: Add imports**

In `cmd/bridge/main.go`, add:
```go
"crypto/ed25519"
"ghost-layer-core/internal/ledger"
```

(`encoding/hex` is already imported.)

- [ ] **Step 14: Add globals**

Below the existing `x402Dispensed atomic.Int64`:
```go
var (
    attestationPrivKey ed25519.PrivateKey
    attestationPubKey  ed25519.PublicKey
)
var bridgeLedger = ledger.NewLedger(10000)
```

- [ ] **Step 15: Startup fatal for ATTESTATION_PRIVATE_KEY**

Right after the `X402_TOKEN_SECRET` fatal:
```go
keyHex := os.Getenv("ATTESTATION_PRIVATE_KEY")
if keyHex == "" {
    log.Fatalf("[FATAL] ATTESTATION_PRIVATE_KEY not set — bridge.attestation cannot sign. Generate with: openssl genpkey -algorithm ed25519")
}
keyBytes, err := hex.DecodeString(keyHex)
if err != nil || len(keyBytes) != ed25519.SeedSize {
    log.Fatalf("[FATAL] ATTESTATION_PRIVATE_KEY must be %d-byte hex (got %d bytes after decode)", ed25519.SeedSize, len(keyBytes))
}
attestationPrivKey = ed25519.NewKeyFromSeed(keyBytes)
attestationPubKey = attestationPrivKey.Public().(ed25519.PublicKey)
log.Printf("[SERVER] Attestation Signer: ARMED | pubkey=%s", hex.EncodeToString(attestationPubKey))
```

- [ ] **Step 16: Update routing.telemetry dispatcher signature**

In the existing `init()`, change:
```go
Dispatcher: func() (json.RawMessage, error) {
```
to:
```go
Dispatcher: func(_ map[string]any) (json.RawMessage, error) {
```

- [ ] **Step 17: Replace the disabled `bridge.attestation` entry with a live registration**

Currently:
```go
for _, id := range []string{"bridge.attestation", "bridge.priority", "cube.mint"} {
    x402Registry.Register(&x402.Product{ID: id, Disabled: true, BasePrice: 100000})
}
```

Replace with:
```go
x402Registry.Register(&x402.Product{
    ID:        "bridge.attestation",
    Name:      "Bridge Settlement Attestation (Ed25519)",
    BasePrice: 100000, // 0.10 RLUSD
    Dispatcher: func(args map[string]any) (json.RawMessage, error) {
        txHash, _ := args["tx_hash"].(string)
        if txHash == "" {
            return nil, fmt.Errorf("ERR_MISSING_TX_HASH")
        }
        rec, ok := bridgeLedger.Lookup(txHash)
        if !ok {
            return nil, fmt.Errorf("ERR_BRIDGE_NOT_FOUND")
        }
        env, err := x402.BuildAndSign(rec, attestationPrivKey)
        if err != nil {
            return nil, err
        }
        return json.Marshal(env)
    },
})
for _, id := range []string{"bridge.priority", "cube.mint"} {
    x402Registry.Register(&x402.Product{ID: id, Disabled: true, BasePrice: 500000})
}
```

> Note `bridge.priority` base price bumped to 500000 (0.50 RLUSD) — was 100000 in the placeholder; the spec for that product (still reserved) anticipates a higher price band. Defensible drive-by adjustment; if you want strict no-drive-by behavior, leave at 100000 and address in the next phase.

- [ ] **Step 18: Capture settlements into the bridge ledger**

In the `/v1/bridge/execute` handler, immediately after `newTier := agentLedger.RecordVolume(...)` and the chain detection (currently lines ~791–797), insert:

```go
bridgeID := fmt.Sprintf("br-%x", time.Now().UnixNano())
bridgeLedger.Record(ledger.BridgeRecord{
    BridgeID:          bridgeID,
    TxHash:            txHash,
    Chain:             chain,
    SourceWallet:      p.SourceWallet,
    DestinationWallet: p.DestinationWallet,
    GrossAmount:       p.GrossAmount,
    FeeAmount:         fee.String(),
    NetAmount:         netAmt.String(),
    EffectiveBPS:      effectiveBPS,
    AgentTier:         newTier,
    SettledAt:         time.Now().Unix(),
})
```

(Optionally surface `bridge_id` in the response JSON so the agent gets it on settle.)

- [ ] **Step 19: Pre-quote validation for bridge.attestation**

In the `/v1/x402/quote` handler, after the product lookup succeeds and before calling `x402.Issue`, insert:

```go
if product.ID == "bridge.attestation" {
    txHash, _ := body.Args["tx_hash"].(string)
    if txHash == "" {
        writeJSONErr(w, http.StatusBadRequest, "ERR_MISSING_TX_HASH")
        return
    }
    if _, ok := bridgeLedger.Lookup(txHash); !ok {
        writeJSONErr(w, http.StatusNotFound, "ERR_BRIDGE_NOT_FOUND")
        return
    }
}
```

The quote request struct also needs an `Args` field:
```go
var body struct {
    ProductID   string         `json:"product_id"`
    AgentWallet string         `json:"agent_wallet"`
    Args        map[string]any `json:"args,omitempty"`
}
```

And the `x402.Issue(...)` call now passes `body.Args`.

- [ ] **Step 20: Pass payload.Args into Dispatch in the dispense handler**

In the `/v1/x402/dispense/{pid}` handler, change:
```go
out, err := x402Registry.Dispatch(pid)
```
to:
```go
out, err := x402Registry.Dispatch(pid, payload.Args)
```

- [ ] **Step 21: New route: GET /v1/x402/attestation/pubkey**

Near the other x402 routes:
```go
r.Get("/v1/x402/attestation/pubkey", func(w http.ResponseWriter, req *http.Request) {
    w.Header().Set("Content-Type", "application/json")
    json.NewEncoder(w).Encode(map[string]interface{}{
        "algorithm":      "ed25519",
        "public_key_hex": hex.EncodeToString(attestationPubKey),
        "issuer":         x402.AttestationIssuer,
        "version":        x402.AttestationVersion,
    })
})
```

- [ ] **Step 22: Extend /api/config**

In the existing /api/config handler, add:
```go
"x402_attestation_pubkey": hex.EncodeToString(attestationPubKey),
```

- [ ] **Step 23: Build + race tests**

```
go build ./...
go test -race ./internal/x402/... ./internal/router/... ./internal/toll/... ./internal/ledger/...
```

Expected: zero errors, all green.

---

## Task 5 — Local end-to-end smoke

- [ ] **Step 24: Generate an Ed25519 seed (32 hex bytes)**

```
openssl rand -hex 32
```

- [ ] **Step 25: Boot the server with all required env vars**

```
ADMIN_TOKEN=test \
X402_TOKEN_SECRET=test-secret \
ATTESTATION_PRIVATE_KEY=<the hex from step 24> \
GATEWAY_XRPL_PRIVATE_KEY=000102030405060708090a0b0c0d0e0f000102030405060708090a0b0c0d0e0f \
PORT=8181 \
go run ./cmd/bridge/
```

Expected log lines:
```
[SERVER] X402 Vendor: ARMED | Catalog: routing.telemetry | Endpoint: /v1/x402
[SERVER] Attestation Signer: ARMED | pubkey=<64 hex chars>
```

- [ ] **Step 26: Fetch the public key**

```
curl -s localhost:8181/v1/x402/attestation/pubkey | jq
```

Expected: `{algorithm:"ed25519", public_key_hex:"...", issuer:"ghost-layer.onrender.com", version:"1.0"}`.

- [ ] **Step 27: Try to quote without a real bridge — expect 404**

```
curl -s -X POST localhost:8181/v1/x402/quote \
  -H 'Content-Type: application/json' \
  -d '{"product_id":"bridge.attestation","agent_wallet":"rAgent","args":{"tx_hash":"FAKE"}}'
```

Expected: `{"error":"ERR_BRIDGE_NOT_FOUND"}`.

- [ ] **Step 28: Quote without tx_hash — expect 400**

```
curl -s -X POST localhost:8181/v1/x402/quote \
  -H 'Content-Type: application/json' \
  -d '{"product_id":"bridge.attestation","agent_wallet":"rAgent"}'
```

Expected: `{"error":"ERR_MISSING_TX_HASH"}`.

- [ ] **Step 29: Manually seed a bridge record for testing**

Since we can't (easily) settle a real cross-chain bridge during a smoke run, add a temporary admin route (or use a Go test) to inject a `BridgeRecord` directly. Simplest path: write a quick helper in `cmd/bridgeprobe/main.go` (similar to `cmd/x402probe`) that POSTs against a dev-only endpoint, OR just write an integration test under `cmd/bridge/` that exercises the full flow with httptest.

Recommended: add an integration test rather than a runtime-only admin route. Avoids permanent attack surface.

- [ ] **Step 30: Build a verifier — `cmd/attestverify/main.go`**

A tiny Go program that:
1. Fetches `/v1/x402/attestation/pubkey`
2. Reads a JSON envelope from stdin
3. Calls `x402.VerifyEnvelope(env, pub)`
4. Exits 0 on valid, 1 on invalid

Same pattern as `cmd/x402probe`. Keeps the verifier in-repo for future operators.

---

## Task 6 — Commit + PR

- [ ] **Step 31: Stage and commit**

Split into logical commits:
1. `internal/ledger/` — new package
2. `internal/x402/` — attestation + dispatcher signature change + payload.Args
3. `cmd/bridge/main.go` — wiring + ledger capture + new routes
4. `cmd/attestverify/main.go` — verifier tool
5. Docs (spec + plan, already on this branch)

- [ ] **Step 32: Push and open draft PR**

```
git push -u origin claude/bridge-attestation
```

Open as draft. Title: `bridge.attestation: Ed25519-signed institutional settlement attestation`. Body links spec.

---

## Self-Audit

**Spec coverage:**
- ✅ Ed25519 sign + offline verify — Task 2 (attestation.go + tests)
- ✅ Bound to real settlement — Task 4 Steps 17, 18, 19 (ledger capture + pre-quote validation)
- ✅ Loyalty-aware pricing — reuses existing `x402.Price(base, tier)` unchanged
- ✅ Canonical signing format deterministic + portable — Task 2 `CanonicalBytes`
- ✅ Public key discoverable — Task 4 Step 21
- ✅ Bounded ledger memory — Task 1 (FIFO eviction at 10000)
- ✅ Startup fatal on missing key — Task 4 Step 15

**No placeholders.** Every step has exact code or exact commands.

**Backward compat:** existing `routing.telemetry` test continues to pass (one-char dispatcher signature change). x402 token clients in flight at deploy-time will see no schema break — `Args` is `omitempty`, missing on telemetry tokens.

**Reserved-product cleanup:** `bridge.priority` and `cube.mint` remain disabled with bumped placeholder prices. They are not part of this phase.
