# 19 — System Circuit Breaker
**Date:** 2026-06-11  
**Status:** SPEC — implement at proxy + API layers  
**Scope:** SqueezeOS API, 402Proof, Ghost Layer (enforced inside existing Go/Python services)

> **TL;DR:** A lightweight, stateless circuit breaker enforced as env-var-controlled kill switches + hard financial caps inside the existing proxy layer (Signal Loom / SqueezeOS API) and the 402Proof firewall. No new service. Sub-100-line implementation per service.

---

## Problem

The live stack has no automated protection against:
1. Toxic upstream signal flood (bad data from Polygon, Yahoo Finance, or SEC SSE) reaching execution
2. Runaway per-agent spend (replay, loop, or compromised wallet draining RLUSD reserves)
3. Cascade failure when a downstream service (XRPL RPC, Render free-tier cold start) is unresponsive

## Design Principles

- **No new service.** All breaker logic lives inside existing services as middleware.
- **Env-var kill switch.** `CIRCUIT_BREAKER_OPEN=true` halts all outbound payments and signal emission instantly. Deployable from Render dashboard in under 10 seconds.
- **Hard caps, not soft warnings.** Caps are enforced at the code level, not monitoring dashboards.
- **Stateless.** No Redis, no distributed state. Per-process counters reset on restart (acceptable for Render Starter tier).

---

## Implementation: 402Proof (Go)

Add to `402proof/internal/firewall/breaker.go`:

```go
package firewall

import (
    "os"
    "sync/atomic"
)

// GlobalOpen — set CIRCUIT_BREAKER_OPEN=true in Render env to halt all payments.
func GlobalOpen() bool {
    return os.Getenv("CIRCUIT_BREAKER_OPEN") == "true"
}

// Per-process counters (reset on restart)
var (
    invoicesIssued  int64
    paymentsSettled int64
    totalSpendDrops int64 // in RLUSD drops (1 RLUSD = 1,000,000 drops)
)

// Hard caps — tune via env vars
func maxInvoicesPerHour() int64 { return envInt("CB_MAX_INVOICES_HOUR", 500) }
func maxSpendPerHour()    int64 { return envInt("CB_MAX_SPEND_DROPS_HOUR", 10_000_000) } // 10 RLUSD

func IncrInvoice() bool {
    n := atomic.AddInt64(&invoicesIssued, 1)
    return n <= maxInvoicesPerHour()
}

func IncrSpend(drops int64) bool {
    n := atomic.AddInt64(&totalSpendDrops, drops)
    return n <= maxSpendPerHour()
}
```

Add to `POST /v1/invoice` handler (before invoice creation):
```go
if firewall.GlobalOpen() {
    writeJSON(w, http.StatusServiceUnavailable, map[string]string{
        "error": "CIRCUIT_BREAKER_OPEN", "message": "Payment system halted by operator",
    })
    return
}
if !firewall.IncrInvoice() {
    writeJSON(w, http.StatusTooManyRequests, map[string]string{
        "error": "RATE_CAP_EXCEEDED", "message": "Invoice rate cap reached — try later",
    })
    return
}
```

---

## Implementation: SqueezeOS API (Python/Flask)

Add `squeezeos/circuit_breaker.py`:

```python
import os
from threading import Lock
from datetime import datetime, timedelta

_lock = Lock()
_window_start = datetime.utcnow()
_signal_count = 0
_error_count = 0

# Env-var kill switch
def is_open() -> bool:
    return os.getenv("CIRCUIT_BREAKER_OPEN", "false").lower() == "true"

# Hard caps (tune via env)
MAX_SIGNALS_HOUR = int(os.getenv("CB_MAX_SIGNALS_HOUR", "1000"))
MAX_ERRORS_HOUR  = int(os.getenv("CB_MAX_ERRORS_HOUR",  "50"))

def check_and_increment() -> tuple[bool, str]:
    """Returns (allowed, reason). Call before emitting any signal."""
    if is_open():
        return False, "CIRCUIT_BREAKER_OPEN"
    global _window_start, _signal_count, _error_count
    with _lock:
        now = datetime.utcnow()
        if now - _window_start > timedelta(hours=1):
            _window_start = now
            _signal_count = 0
            _error_count = 0
        _signal_count += 1
        if _signal_count > MAX_SIGNALS_HOUR:
            return False, "SIGNAL_RATE_CAP"
        return True, "OK"

def record_error():
    global _error_count
    with _lock:
        _error_count += 1
        if _error_count >= int(os.getenv("CB_MAX_ERRORS_HOUR", "50")):
            # Auto-open breaker on sustained error storm
            os.environ["CIRCUIT_BREAKER_OPEN"] = "true"
```

Wrap signal emission routes:
```python
from circuit_breaker import check_and_increment

@app.route("/api/scan")
@require_payment
def scan():
    allowed, reason = check_and_increment()
    if not allowed:
        return jsonify({"error": reason}), 503
    # ... existing scan logic
```

---

## Env Vars (all services)

| Var | Default | Effect |
|---|---|---|
| `CIRCUIT_BREAKER_OPEN` | `false` | `true` = immediate full halt, all payment + signal routes return 503 |
| `CB_MAX_INVOICES_HOUR` | `500` | 402Proof invoice rate cap |
| `CB_MAX_SPEND_DROPS_HOUR` | `10000000` | 402Proof spend cap (10 RLUSD/hr) |
| `CB_MAX_SIGNALS_HOUR` | `1000` | SqueezeOS signal emission cap |
| `CB_MAX_ERRORS_HOUR` | `50` | SqueezeOS auto-open threshold |

---

## Operating Procedures

**To halt everything immediately:**
1. Render dashboard → squeezeos-api service → Environment → `CIRCUIT_BREAKER_OPEN=true` → Save
2. Repeat for four02proof service
3. Both services restart in ~15 seconds and return 503 on all payment/signal routes

**To reopen:**
1. Delete or set `CIRCUIT_BREAKER_OPEN=false` in both services → Save

**To raise caps during high-volume periods:**
- Adjust `CB_MAX_INVOICES_HOUR`, `CB_MAX_SIGNALS_HOUR` in Render env without a code deploy

---

## What This Does NOT Cover

- Cross-chain atomic rollback (out of scope for Render Starter)
- Distributed rate limiting across multiple instances (single-instance on Render Starter — not needed)
- ZK-proof state relayer (future: hash-commit XRPL memo is sufficient for current v1)
