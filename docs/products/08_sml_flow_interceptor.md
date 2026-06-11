# 08 — SML Flow Interceptor (Institutional Order Flow)

**Live URL:** https://sml-flow.onrender.com
**Repo path:** `sml-flow-interceptor/`
**Language:** Go
**Deploy:** Render (cloud, 24/7)

---

## What It Does
Institutional order flow interception and analysis. Captures and processes order flow data at the institutional level — routing, classification, and intelligence extraction from real market order flow.

## Repo Structure
- `cmd/` — Go entry points
- `internal/` — flow interception logic
- `internal/sink/webhook.go` — webhook delivery sink

## Links To
- **SqueezeOS [01]** — order flow data enriches signal quality
- **Shadow Desk [05]** — complements dark pool surveillance with order routing intelligence
- **Ghost Layer [02]** — flow intelligence feeds stealth trade and copy trade routing
