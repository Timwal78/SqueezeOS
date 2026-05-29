# Ghost Layer V2 Phase 1 Engine A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply 5 targeted defensive fixes — zero-fee guard, sweepWg goroutine tracking, XRPL route-level mutex, ADMIN_TOKEN startup fatal — to harden the Ghost Layer Go backend for live agent volume.

**Architecture:** All changes are purely defensive. No success-path logic is modified. Three files touched: `internal/toll/fees.go` (1-line guard change), `internal/router/bridge.go` (add routeMu + sweepWg fields, fix goroutine tracking, lock routeXRPL), `cmd/bridge/main.go` (ADMIN_TOKEN fatal + WaitGroup wiring). Two new test files created. No new packages.

**Tech Stack:** Go 1.22, standard `sync` and `testing` packages. Module: `ghost-layer-core`.

---

## File Map

| File | Action | What changes |
|---|---|---|
| `internal/toll/fees.go` | Modify | `bps < 0` → `bps <= 0`; error message |
| `internal/toll/fees_test.go` | Create | Unit tests for `CalculateBasisPointFee` |
| `internal/router/bridge.go` | Modify | Add `routeMu`, `sweepWg` fields; update constructor; fix goroutine; lock routeXRPL |
| `internal/router/bridge_test.go` | Create | Constructor smoke test; WaitGroup field verification |
| `cmd/bridge/main.go` | Modify | ADMIN_TOKEN fatal; remove misplaced sweepWg wrapping; pass `&sweepWg` to constructor |

---

## Task 1 — Write failing unit tests for fees.go

**Files:**
- Create: `internal/toll/fees_test.go`

- [ ] **Step 1: Create the test file with a table-driven suite**

```go
package toll

import (
	"testing"
)

func TestCalculateBasisPointFee(t *testing.T) {
	cases := []struct {
		name      string
		amount    string
		bps       int64
		wantErr   bool
		wantFee   string
		wantNet   string
	}{
		{name: "valid 50bps", amount: "1000000", bps: 50, wantErr: false, wantFee: "5000", wantNet: "995000"},
		{name: "valid 1bps floor", amount: "1000000", bps: 1, wantErr: false, wantFee: "100", wantNet: "999900"},
		{name: "valid 500bps ceiling", amount: "1000000", bps: 500, wantErr: false, wantFee: "50000", wantNet: "950000"},
		{name: "zero bps rejected", amount: "1000000", bps: 0, wantErr: true},
		{name: "negative bps rejected", amount: "1000000", bps: -1, wantErr: true},
		{name: "bps above ceiling rejected", amount: "1000000", bps: 501, wantErr: true},
		{name: "zero amount rejected", amount: "0", bps: 50, wantErr: true},
		{name: "negative amount rejected", amount: "-1", bps: 50, wantErr: true},
		{name: "non-numeric amount rejected", amount: "abc", bps: 50, wantErr: true},
		{name: "amount too long rejected", amount: "12345678901234567890123456789012345678901", bps: 50, wantErr: true},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			fee, net, err := CalculateBasisPointFee(tc.amount, tc.bps)
			if tc.wantErr {
				if err == nil {
					t.Fatalf("expected error, got nil (fee=%v net=%v)", fee, net)
				}
				return
			}
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if fee.String() != tc.wantFee {
				t.Errorf("fee: want %s got %s", tc.wantFee, fee.String())
			}
			if net.String() != tc.wantNet {
				t.Errorf("net: want %s got %s", tc.wantNet, net.String())
			}
		})
	}
}
```

- [ ] **Step 2: Run the tests — expect "zero bps rejected" to FAIL**

```
cd C:\Users\timot\Downloads\SqueezeOS_Github\ghost-layer
go test ./internal/toll/... -v -run TestCalculateBasisPointFee
```

Expected: most cases PASS. The `zero bps rejected` case FAILS with something like:
```
--- FAIL: TestCalculateBasisPointFee/zero_bps_rejected
    fees_test.go:XX: expected error, got nil
```

---

## Task 2 — Fix the zero-fee guard in fees.go

**Files:**
- Modify: `internal/toll/fees.go:17-19`

- [ ] **Step 3: Change the guard condition and error message**

In `internal/toll/fees.go`, replace:
```go
if bps < 0 || bps > MaxBPS {
    return nil, nil, fmt.Errorf("fee_basis_points out of range [0, %d], got %d", MaxBPS, bps)
}
```

With:
```go
if bps <= 0 || bps > MaxBPS {
    return nil, nil, fmt.Errorf("fee_basis_points out of range [1, %d], got %d", MaxBPS, bps)
}
```

- [ ] **Step 4: Run the tests — expect all to PASS**

```
go test ./internal/toll/... -v -run TestCalculateBasisPointFee
```

Expected output — all 10 cases green:
```
--- PASS: TestCalculateBasisPointFee/valid_50bps
--- PASS: TestCalculateBasisPointFee/valid_1bps_floor
--- PASS: TestCalculateBasisPointFee/valid_500bps_ceiling
--- PASS: TestCalculateBasisPointFee/zero_bps_rejected
--- PASS: TestCalculateBasisPointFee/negative_bps_rejected
--- PASS: TestCalculateBasisPointFee/bps_above_ceiling_rejected
--- PASS: TestCalculateBasisPointFee/zero_amount_rejected
--- PASS: TestCalculateBasisPointFee/negative_amount_rejected
--- PASS: TestCalculateBasisPointFee/non-numeric_amount_rejected
--- PASS: TestCalculateBasisPointFee/amount_too_long_rejected
PASS
```

- [ ] **Step 5: Commit**

```
git add internal/toll/fees.go internal/toll/fees_test.go
git commit -m "fix(fees): reject bps=0 — enforce minimum 1bp platform fee"
```

---

## Task 3 — Write failing tests for bridge.go engine constructor

**Files:**
- Create: `internal/router/bridge_test.go`

- [ ] **Step 6: Create the test file**

```go
package router

import (
	"sync"
	"testing"
)

// TestNewEngineAcceptsWaitGroup verifies the constructor stores the WaitGroup reference.
// This test FAILS until Task 4 adds the sweepWg parameter to the constructor.
func TestNewEngineAcceptsWaitGroup(t *testing.T) {
	var wg sync.WaitGroup
	e := NewTransparentBridgeEngine("rTreasury", "0xTreasury", nil, nil, &wg)
	if e == nil {
		t.Fatal("expected non-nil engine")
	}
	if e.sweepWg != &wg {
		t.Fatal("sweepWg field not set on engine")
	}
}

// TestRouteXRPLNilClient verifies routeXRPL short-circuits safely when xrpl client is nil.
// This exercises the function path without needing a live XRPL node.
func TestRouteXRPLNilClient(t *testing.T) {
	var wg sync.WaitGroup
	e := NewTransparentBridgeEngine("rTreasury", "0xTreasury", nil, nil, &wg)
	_, err := e.routeXRPL("rDest", nil, nil)
	if err == nil {
		t.Fatal("expected error for nil xrpl client, got nil")
	}
	want := "XRPL client not initialised"
	if err.Error()[:len(want)] != want {
		t.Errorf("error message: want prefix %q, got %q", want, err.Error())
	}
}
```

- [ ] **Step 7: Run the tests — expect COMPILE ERROR or FAIL**

```
go test ./internal/router/... -v -run "TestNewEngineAcceptsWaitGroup|TestRouteXRPLNilClient"
```

Expected: compile error because `NewTransparentBridgeEngine` does not yet accept a `*sync.WaitGroup` parameter.

---

## Task 4 — Harden bridge.go: routeMu + sweepWg

**Files:**
- Modify: `internal/router/bridge.go`

- [ ] **Step 8: Add imports and new fields to the engine struct**

At the top of `internal/router/bridge.go`, the import block currently reads:
```go
import (
    "context"
    "errors"
    "fmt"
    "log"
    "math/big"
    "strings"

    "ghost-layer-core/internal/chain"
    "ghost-layer-core/internal/toll"
)
```

Replace with:
```go
import (
    "context"
    "errors"
    "fmt"
    "log"
    "math/big"
    "strings"
    "sync"

    "ghost-layer-core/internal/chain"
    "ghost-layer-core/internal/toll"
)
```

Replace the struct definition:
```go
type TransparentBridgeEngine struct {
    TreasuryXRPL string
    TreasuryETH  string
    xrpl         *chain.XRPLClient
    base         *chain.BaseClient
}
```

With:
```go
type TransparentBridgeEngine struct {
    TreasuryXRPL string
    TreasuryETH  string
    xrpl         *chain.XRPLClient
    base         *chain.BaseClient
    routeMu      sync.Mutex      // serialises XRPL fee+net payment pairs
    sweepWg      *sync.WaitGroup // tracks async sweep goroutines for shutdown drain
}
```

- [ ] **Step 9: Update the constructor to accept *sync.WaitGroup**

Replace:
```go
func NewTransparentBridgeEngine(treasuryXRPL, treasuryETH string, xrpl *chain.XRPLClient, base *chain.BaseClient) *TransparentBridgeEngine {
    return &TransparentBridgeEngine{
        TreasuryXRPL: treasuryXRPL,
        TreasuryETH:  treasuryETH,
        xrpl:         xrpl,
        base:         base,
    }
}
```

With:
```go
func NewTransparentBridgeEngine(treasuryXRPL, treasuryETH string, xrpl *chain.XRPLClient, base *chain.BaseClient, sweepWg *sync.WaitGroup) *TransparentBridgeEngine {
    return &TransparentBridgeEngine{
        TreasuryXRPL: treasuryXRPL,
        TreasuryETH:  treasuryETH,
        xrpl:         xrpl,
        base:         base,
        sweepWg:      sweepWg,
    }
}
```

- [ ] **Step 10: Lock routeXRPL across both SendPayment calls**

Replace the existing `routeXRPL` function (lines 155–167):
```go
func (e *TransparentBridgeEngine) routeXRPL(destination string, fee, net *big.Int) (string, error) {
    if e.xrpl == nil {
        return "", errors.New("XRPL client not initialised — set GATEWAY_XRPL_PRIVATE_KEY")
    }
    if _, err := e.xrpl.SendPayment(e.TreasuryXRPL, fee.Uint64()); err != nil {
        return "", fmt.Errorf("XRPL fee payment: %w", err)
    }
    txHash, err := e.xrpl.SendPayment(destination, net.Uint64())
    if err != nil {
        return "", fmt.Errorf("XRPL principal payment: %w", err)
    }
    return txHash, nil
}
```

With:
```go
func (e *TransparentBridgeEngine) routeXRPL(destination string, fee, net *big.Int) (string, error) {
    if e.xrpl == nil {
        return "", errors.New("XRPL client not initialised — set GATEWAY_XRPL_PRIVATE_KEY")
    }
    // Hold routeMu across both sends so no other route's transactions land between
    // this route's fee and net payments on the ledger.
    e.routeMu.Lock()
    defer e.routeMu.Unlock()
    if _, err := e.xrpl.SendPayment(e.TreasuryXRPL, fee.Uint64()); err != nil {
        return "", fmt.Errorf("XRPL fee payment: %w", err)
    }
    txHash, err := e.xrpl.SendPayment(destination, net.Uint64())
    if err != nil {
        return "", fmt.Errorf("XRPL principal payment: %w", err)
    }
    return txHash, nil
}
```

- [ ] **Step 11: Fix the sweep goroutine to track sweepWg correctly**

Replace the goroutine block inside `RouteTransactionWithDisclosure` (lines 72–76):
```go
go func() {
    if err := e.sweepBestEffort(source); err != nil {
        log.Printf("[SWEEP] error: %v", err)
    }
}()
```

With:
```go
e.sweepWg.Add(1)
go func() {
    defer e.sweepWg.Done()
    if err := e.sweepBestEffort(source); err != nil {
        log.Printf("[SWEEP] error: %v", err)
    }
}()
```

**Critical ordering note:** `sweepWg.Add(1)` MUST be called before the `go` statement, never inside the goroutine. If `Add` is inside the goroutine, a concurrent `sweepWg.Wait()` could return before `Add` is called, causing the goroutine to run after shutdown.

- [ ] **Step 12: Run the bridge tests — expect PASS**

```
go test ./internal/router/... -v -run "TestNewEngineAcceptsWaitGroup|TestRouteXRPLNilClient"
```

Expected:
```
--- PASS: TestNewEngineAcceptsWaitGroup
--- PASS: TestRouteXRPLNilClient
PASS
```

---

## Task 5 — Fix main.go: ADMIN_TOKEN fatal + sweepWg wiring

**Files:**
- Modify: `cmd/bridge/main.go`

- [ ] **Step 13: Add ADMIN_TOKEN fatal check after the gateway key block**

In `main()`, the existing gateway key block ends around line 422:
```go
if xrplKey == "" && ethKey == "" {
    log.Fatalf("[FATAL] No gateway keys configured — set GATEWAY_XRPL_PRIVATE_KEY and/or GATEWAY_ETH_PRIVATE_KEY in Render secrets")
}
```

Immediately after that block, add:
```go
if os.Getenv("ADMIN_TOKEN") == "" {
    log.Fatalf("[FATAL] ADMIN_TOKEN not set — admin endpoints cannot be secured. Set ADMIN_TOKEN in Render secrets.")
}
```

- [ ] **Step 14: Remove the misplaced sweepWg tracking from the bridge handler**

In the `/v1/bridge/execute` handler, find:
```go
sweepWg.Add(1)
txHash, fee, netAmt, err := engine.RouteTransactionWithDisclosure(
    req.Context(),
    p.SourceWallet, p.DestinationWallet,
    p.GrossAmount, effectiveBPS,
    auth,
)
sweepWg.Done()
```

Replace with:
```go
txHash, fee, netAmt, err := engine.RouteTransactionWithDisclosure(
    req.Context(),
    p.SourceWallet, p.DestinationWallet,
    p.GrossAmount, effectiveBPS,
    auth,
)
```

- [ ] **Step 15: Pass &sweepWg to the engine constructor**

Find:
```go
engine := router.NewTransparentBridgeEngine(treasuryXRPL, treasuryETH, xrplClient, baseClient)
```

Replace with:
```go
engine := router.NewTransparentBridgeEngine(treasuryXRPL, treasuryETH, xrplClient, baseClient, &sweepWg)
```

---

## Task 6 — Build verification + race detector

- [ ] **Step 16: Verify the build compiles cleanly**

```
cd C:\Users\timot\Downloads\SqueezeOS_Github\ghost-layer
go build ./...
```

Expected: no output (zero errors, zero warnings).

- [ ] **Step 17: Run the full test suite with the race detector**

```
go test -race ./internal/toll/... ./internal/router/...
```

Expected:
```
ok  	ghost-layer-core/internal/toll	0.XXXs
ok  	ghost-layer-core/internal/router	0.XXXs
```

No DATA RACE warnings. If any appear, the sweepWg.Add ordering in Step 11 is the first place to check.

- [ ] **Step 18: Manual smoke test — verify ADMIN_TOKEN fatal**

Start the server WITHOUT ADMIN_TOKEN set:
```
GATEWAY_XRPL_PRIVATE_KEY=<any_32_byte_hex> go run ./cmd/bridge/
```

Expected: immediate fatal log line:
```
[FATAL] ADMIN_TOKEN not set — admin endpoints cannot be secured. Set ADMIN_TOKEN in Render secrets.
exit status 1
```

- [ ] **Step 19: Final commit**

```
git add internal/router/bridge.go internal/router/bridge_test.go cmd/bridge/main.go
git commit -m "fix(engine): XRPL route atomicity, sweepWg goroutine tracking, ADMIN_TOKEN startup fatal"
```

---

## Self-Audit

**Spec coverage:**
- ✅ `bps=0` zero-fee guard — Task 2
- ✅ `sweepWg` tracks async goroutine, not the synchronous route — Tasks 3–4 (bridge.go) + Task 5 (main.go)
- ✅ XRPL fee+net pair protected by `routeMu` — Task 4 Step 10
- ✅ `ADMIN_TOKEN` startup fatal — Task 5 Step 13
- ✅ Context longevity — already correct, no change needed (noted in spec)
- ✅ Double-hash check — already clean, no change needed (noted in spec)

**No placeholders.** Every step contains exact code or exact commands.

**Type consistency:** `NewTransparentBridgeEngine` signature updated in both bridge.go (Task 4 Step 9) and main.go (Task 5 Step 15). `sweepWg` field referenced in test (Task 3 Step 6) matches field name added in Task 4 Step 8.
