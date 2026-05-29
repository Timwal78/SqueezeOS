# Ghost Layer V2 — Phase 1 Engine A Design
**Date:** 2026-05-25
**Scope:** Claude Code Engine A — Go backend surgical fixes
**Option:** B — Phase 1 bugs + ADMIN_TOKEN startup fatal

---

## Problem Statement

Four confirmed bugs in the existing Go backend require targeted fixes before the platform opens to live agent volume. Two additional items from the directive's self-audit checklist are addressed in the same pass.

---

## Bugs & Fixes

### Bug 1 — Zero-fee routing allowed
**File:** `internal/toll/fees.go:17`
**Root cause:** Guard reads `bps < 0`, so `bps=0` passes. fee=0, net=gross. Gateway routes for free.
**Fix:** Change to `bps <= 0`. Valid range becomes `[1, 500]`. Error message updated to reflect new floor.

### Bug 2 — sweepWg tracks the wrong thing
**File:** `cmd/bridge/main.go:647-653` + `internal/router/bridge.go:72-76`
**Root cause:** `sweepWg.Add(1)/Done()` wraps the synchronous `RouteTransactionWithDisclosure` call. The async sweep goroutine launched *inside* that function is never tracked. `sweepWg.Wait()` during graceful shutdown returns before sweep goroutines finish.
**Fix:**
- Add `sweepWg *sync.WaitGroup` field to `TransparentBridgeEngine` struct.
- Constructor accepts `*sync.WaitGroup` as a new parameter.
- Call `e.sweepWg.Add(1)` immediately before the goroutine launch (MUST be outside the goroutine to avoid a race with `Wait()`), and `defer e.sweepWg.Done()` as the first statement inside.
- Strip the misplaced `sweepWg.Add(1)/Done()` from `main.go`.
- Pass `&sweepWg` to `NewTransparentBridgeEngine` in `main.go`.

### Bug 3 — XRPL fee+net pair not atomic
**File:** `internal/router/bridge.go:155-167`
**Root cause:** `routeXRPL` makes two sequential `SendPayment` calls with no operation-level lock. Under concurrent load, another route's transactions can be interleaved between a route's fee tx and net tx on the ledger. If the net tx fails after the fee tx succeeds, the fee is in treasury but the principal is never delivered.
**Fix:** Add `routeMu sync.Mutex` field to `TransparentBridgeEngine`. `routeXRPL` acquires `e.routeMu.Lock()` before the first `SendPayment` and holds it across both calls. XRPL routes are serialized (one-at-a-time). Base routes are unaffected — `PullAndRoute` handles its own atomicity at the EVM layer.

### Bug 4 — ADMIN_TOKEN not checked at startup
**File:** `cmd/bridge/main.go`
**Root cause:** Gateway keys are checked with `log.Fatalf` at startup, but `ADMIN_TOKEN` is only validated in middleware (returns 403). Directive self-audit requires fatal exit on missing vital parameters.
**Fix:** Add `log.Fatalf` immediately after gateway key validation: if `ADMIN_TOKEN` env var is empty, the server must not start.

---

## Architecture

No new packages. No new files. Changes confined to:

```
internal/toll/fees.go          — 1-line guard change
internal/router/bridge.go      — add routeMu, sweepWg field + goroutine fix
cmd/bridge/main.go             — ADMIN_TOKEN fatal + remove misplaced sweepWg tracking
```

Data flow is unchanged. All 5 changes are defensive — they add rejections or guard expansions on invalid states. No success-path logic is modified.

---

## Self-Audit Post-Fix Status

| Check | Status |
|---|---|
| Zero-key fatal shutdown (gateway keys) | ✅ existing |
| Zero-key fatal shutdown (ADMIN_TOKEN) | ✅ added by this fix |
| Graceful 30s shutdown drain | ✅ sweepWg now correctly tracks sweep goroutines |
| 1MB body limit on unauthenticated gates | ✅ existing on `/v1/bridge/execute` |
| Health check boolean flags | ✅ existing |
| Nonce replay cache | ✅ existing |
| Per-IP token bucket rate limiter | ✅ existing |
| Security headers (X-Frame-Options, X-Content-Type-Options) | ✅ existing in corsMiddleware |

---

## What Is NOT Changed

- `VerifyEIP3009Signature` — already correct (no double-hash)
- `sweepBestEffort` context handling — already uses `context.Background()`
- Nonce replay cache — already implemented
- Rate limiter — already implemented
- All Antigravity additions (`loyalty.go`, `metrics_hub.go`) — untouched
