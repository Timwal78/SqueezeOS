<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **SqueezeOS** (2652 symbols, 4519 relationships, 58 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> If any GitNexus tool warns the index is stale, run `npx gitnexus analyze` in terminal first.

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `gitnexus_impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `gitnexus_detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `gitnexus_query({query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `gitnexus_context({name: "symbolName"})`.

## Never Do

- NEVER edit a function, class, or method without first running `gitnexus_impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `gitnexus_rename` which understands the call graph.
- NEVER commit changes without running `gitnexus_detect_changes()` to check affected scope.

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/SqueezeOS/context` | Codebase overview, check index freshness |
| `gitnexus://repo/SqueezeOS/clusters` | All functional areas |
| `gitnexus://repo/SqueezeOS/processes` | All execution flows |
| `gitnexus://repo/SqueezeOS/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
|------|---------------------|
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->

---

# SqueezeOS — Codebase Guide for AI Assistants

SqueezeOS is an **institutional-grade AI trading intelligence platform** exposed as an MCP server. Premium endpoints are pay-per-call via [402Proof](https://four02proof.onrender.com) — agents pay RLUSD on the XRP Ledger and receive a 1-hour signed JWT. No API keys, no subscriptions.

**Live endpoint:** `https://squeezeos-api.onrender.com`  
**MCP endpoint:** `/mcp` (JSON-RPC 2.0)  
**Health check:** `GET /api/status`

---

## Deployment — Source of Truth (read this before touching any URL)

> **STOP.** Before editing any URL anywhere in this repo, verify against this table.
> Previous agents caused cascading URL mistakes by trusting stale docs. This table is authoritative.

| Service | Platform | Canonical URL | Config file |
|---------|----------|---------------|-------------|
| **SqueezeOS API** (this repo) | Render | `https://squeezeos-api.onrender.com` | `render.yaml` |
| **Ghost Layer** (Go routing backend) | Render | `https://ghost-layer.onrender.com` | `ghost-layer/render.yaml` |
| **Ghost Layer Sovereign** (frontend dashboard) | Vercel | `https://scriptmasterlabs.com` | Vercel project `ghost-layer-sovereign` |
| **402Proof** (payment firewall) | Render | `https://four02proof.onrender.com` | separate repo |

**GitHub:** `github.com/timwal78/squeezeos`  
**Vercel (deleted):** `squeeze-os` project deleted May 2026 — do not recreate.  
**Railway:** not used — ignore any Railway URLs found in older docs or comments.

### scriptmasterlabs.com product catalog (what's live vs planned)

The `scriptmasterlabs.com` site lists multiple products. Only these have live backends:
- ✅ Ghost Layer Sovereign — ZK/MEV dashboard (the site itself)
- ✅ SqueezeOS — market intelligence API
- ✅ Ghost Layer — private XRP routing engine
- ✅ 402Proof — x402 payment firewall
- 🚧 Everything else on the site (Xahau Remittance Rails, Pulse-Verify, Xahau Hooks Intelligence, XRPL Copy-Trader, Memecoin Launchpad) — listed but not yet deployed

---

## Project Name Aliases (internal codenames)

When the user or docs reference these names, map them here — do not search the codebase:

| Name | Module | Location |
|------|--------|----------|
| **GraphiFY** / MarketGraphify | `MarketGraph` — Neo4j AuraDB graph (ticker nodes, Greek/dark-pool/fractal edges) | `core/market_graph.py` |
| **OpenMythos** / RDT | `RecurrentDepthTransformer` — recursive what-if loop on the graph (depth 0–3, fractal anchors) | `core/rdt_engine.py` |
| **Superpower** / Beastmode | `scriptmaster_bp` — SEO/recon node: P01 Authority Signaling, P02 Visual Saturation, P03 Sentiment Exploitation | `core/api/scriptmaster_bp.py` |

GraphiFY and OpenMythos are tightly coupled — RDT reads from `MarketGraph`. Superpower runs independently. All three surface under `GET /api/graph/rdt`, `GET /api/graph`, and `GET /api/scriptmaster/status`.

---

## The Prime Directive (non-negotiable)

These rules from `DEVELOPER_MANIFESTO.md` override everything:

1. **NO DEMO DATA** — Never hardcode ticker lists, placeholder values, or fake market activity. If live data is unavailable, return `"Awaiting Data"` or a real error.
2. **100% FETCH** — No arbitrary `.slice()`, `[:50]`, or `[:20]` limits in data loops. Let the engine handle full volume. No artificial price floors unless user-requested.
3. **TRANSPARENCY** — Every data point must have a traceable source (Tradier, Alpaca, Polygon).
4. **ZERO FAKE COMPLIANCE** — Any simulated data found must be purged immediately.

---

## Repository Layout

```
SqueezeOS/
├── core/                    # Flask application package
│   ├── app.py               # create_app() — Flask factory, blueprint registration
│   ├── state.py             # GlobalState singleton + sse_queues list
│   ├── legacy.py            # Service registry (get_service), engine loader
│   ├── oracle_engine.py     # OracleEngine — aggregates all signals into one directive
│   ├── rdt_engine.py        # RecurrentDepthTransformer — multi-symbol ranking
│   ├── market_graph.py      # Neo4j market relationship graph
│   ├── signal_history.py    # In-memory ring buffer of recent signals (200/symbol)
│   ├── telemetry_rotator.py # Background telemetry heartbeat
│   ├── ceo_trader.py        # CEOTrader institutional logic
│   └── api/                 # Flask Blueprints (one file per domain)
│       ├── mcp_bp.py        # POST /mcp — JSON-RPC 2.0 MCP server (23 tools)
│       ├── premium_bp.py    # /api/council /api/scan /api/options /api/iwm (402-gated)
│       ├── market_scanner.py# /api/market — background scan loop + cache
│       ├── marketplace_bp.py# /api/marketplace — peer signal marketplace
│       ├── futures_bp.py    # /api/futures — signal prediction market
│       ├── settlement_bp.py # /api/settlement — conditional agent escrow contracts
│       ├── hiring_bp.py     # /api/hiring — agent job board
│       ├── relay_bp.py      # /api/relay — relay node discounts
│       ├── webhook_bp.py    # /api/webhooks — webhook subscriptions + delivery
│       ├── battle.py        # /api/battle — Battle Computer consensus
│       ├── beast.py         # /api/beast — Beast mode scanner
│       ├── mmle.py          # /api/mmle — Market Maker Liquidity Engine
│       ├── ai_reads.py      # /api/ai — AI council reads
│       ├── left_wing.py     # /api/left-wing — telemetry ingestion
│       ├── ceo.py           # /api/ceo — CEO Trader endpoints
│       ├── scriptmaster_bp.py # /api/scriptmaster — ScriptMasterLabs integration
│       ├── v2_bridge.py     # /api and /api/v1 — V2 bridge routes
│       ├── agent_analytics.py # Analytics middleware (before/after request hooks)
│       └── honeypot.py      # Honeypot trap routes (registered FIRST)
├── proof402_integration.py  # @require_payment decorator — local HMAC-SHA256 JWT verify
├── sml_engine.py            # SML Fractal Cascade engine
├── execution_engine.py      # Gamma wall + execution logic
├── mm_liquidity_engine.py   # HJB/Kalman market maker intelligence
├── mmle_engine.py           # MMLE wrapper
├── options_intelligence.py  # Institutional options flow scanner
├── options_anomaly_engine.py# Anomaly detection background thread
├── iwm_odte_engine.py       # IWM zero-day-to-expiry scorer
├── gamma_flow_engine.py     # Gamma flow + flip detection
├── rmre_bridge.py           # Regime/mean-reversion engine bridge
├── whale_stalker_engine.py  # Whale position detector
├── cycle_intelligence_engine.py # Market cycle detector
├── data_providers.py        # TradierProvider, AlpacaProvider, PolygonProvider
├── tradier_api.py           # Tradier REST wrapper
├── battle_engine.py         # Battle Computer logic
├── delta_neutrality.py      # Delta neutrality calculator
├── mean_reversion_engine.py # Mean reversion signals
├── forced_move_engine.py    # Forced move detection
├── sr_patterns_engine.py    # Support/resistance pattern engine
├── squeeze_analyzer.py      # Core squeeze analysis
├── performance_tracker.py   # Signal performance tracker
├── discord_alerts.py        # Discord webhook notifications
├── agent/
│   └── sml_agent.py         # GitHub Actions autonomous agent (pays for its own data)
├── 402proof/                # 402Proof payment server (Go + Python demo)
├── ghost-layer/             # Ghost Layer toll gateway (Go, separate service)
├── pine/                    # TradingView Pine Script indicators
├── indicators/              # Additional Pine Script files
├── .well-known/             # MCP/OpenAPI/agent discovery manifests
├── .github/workflows/       # CI: agent.yml (market schedule), keepalive.yml, publish-*
├── Dockerfile               # python:3.11-slim, gunicorn, port 8182
├── render.yaml              # Render.com deployment (Docker, PORT=8182)
├── requirements.txt         # Python deps
└── .env.example             # All required env vars with documentation
```

---

## Application Startup (`core/app.py`)

`create_app()` is the Flask application factory:

1. Detects serverless mode via `VERCEL=1` env var — skips background threads when serverless.
2. Calls `init_services()` and `start_whale_stalker()` from `core/legacy.py`.
3. Registers `honeypot_bp` **first** (so trap routes take priority over all other routes).
4. Registers `before_analytics` / `after_analytics` middleware from `agent_analytics.py`.
5. Registers all 18 blueprints at their prefixes.
6. Starts background threads: `start_market_scanner()`, `start_webhook_engine()`, `start_anomaly_engine()`, `start_telemetry_rotator()`.
7. Adds `after_request` hooks: analytics, security headers (`HSTS`, `X-Content-Type-Options`, `X-Frame-Options`), SSE agent probe broadcasting.

**Entry point:** `gunicorn "core.app:create_app()"` on port `8182`.

---

## Global State (`core/state.py`)

Single `GlobalState` instance exported as `state`, plus `sse_queues: list` for SSE broadcast.

| Attribute | Type | Purpose |
|-----------|------|---------|
| `state.lock` | `threading.Lock` | Protects all mutations |
| `state.universe` | `dict` | Active ticker OHLCV |
| `state.quotes` | `dict` | Live quote snapshots |
| `state.scan_results` | `list` | Squeeze candidates |
| `state.terminal_feed` | `list[dict]` | Last 250 operational events |
| `state.audit` | `dict` | System health metrics |
| `state.heartbeats` | `dict` | Per-worker last-seen timestamps |

`state.push_terminal(event_type, msg, symbol, score, extra)` — appends to `terminal_feed` and broadcasts to all `sse_queues`.

---

## Service Registry (`core/legacy.py`)

`_services: dict` holds live engine instances. Accessed via:

```python
from core.legacy import get_service
sml = get_service("sml")   # Returns None if not initialized
dm  = get_service("dm")    # DataManager
```

Key registered services: `dm` (DataManager), `sml` (SMLEngine), `whale_stalker`, `battle`, `mmle`.

`clean_data(data)` — sanitizes any value for JSON: converts `NaN`/`Inf` floats to `None`, handles non-serializable objects.

---

## Payment System (`proof402_integration.py`)

The `@require_payment` decorator gates premium endpoints. Token verification is **pure CPU** (no network call):

1. Splits token at last `.` → `encoded.signature`
2. Verifies `HMAC-SHA256(PROOF402_TOKEN_SECRET, encoded) == signature`
3. Base64-decodes `encoded` → `{eid, wlt, iid, exp}`
4. Checks `exp > now`
5. Checks `eid` matches the endpoint's registered UUID

**Required env var:** `PROOF402_TOKEN_SECRET` — must match the secret on the 402Proof server.

**Endpoint UUID registry** (in `proof402_integration.py` and mirrored in `mcp_bp.py`):

| Endpoint | UUID | Cost |
|----------|------|------|
| `/api/council` | `12a0e7a1-...` | 0.10 RLUSD |
| `/api/scan` | `160cf28d-...` | 0.05 RLUSD |
| `/api/options` | `c951a374-...` | 0.05 RLUSD |
| `/api/iwm` | `60f48ce0-...` | 0.03 RLUSD |
| `/api/marketplace/read` | `d1a2b3c4-...` | 0.02 RLUSD |

---

## MCP Server (`core/api/mcp_bp.py`)

Mounted at `/mcp`. Implements JSON-RPC 2.0. **23 tools** total.

**Supported RPC methods:**
- `initialize` — handshake, returns `protocolVersion: "2024-11-05"`
- `tools/list` — returns all tool schemas
- `tools/call` — executes a tool via `_dispatch()`, which proxies to the REST API
- `ping` — keepalive
- `notifications/*` — silently acknowledged (204)

`_dispatch()` extracts `payment_token` and `agent_wallet` from args or request headers (`X-Payment-Token`, `X-Agent-Wallet`) and proxies to `SQUEEZEOS_BASE` or `PROOF402_BASE`.

**MCP client config:**
```json
{
  "mcpServers": {
    "squeezeos": {
      "url": "https://squeezeos-api.onrender.com/mcp",
      "transport": "streamable-http"
    }
  }
}
```

---

## Key API Endpoints

### Free Endpoints
| Route | Description |
|-------|-------------|
| `GET /api/demo` or `/api/demo/council` | IWM council verdict (5-min cache) |
| `GET /api/preview/<symbol>` | Bias + regime preview (15-min cache) |
| `GET /api/history` | All recent signals (ring buffer) |
| `GET /api/history/<symbol>` | Per-symbol history (last 200) |
| `GET /api/status` | System health + uptime |
| `GET /api/oracle` or `/api/oracle/<symbol>` | Oracle directive batch |
| `GET /api/graph` or `/api/graph/<symbol>` | Neo4j market graph snapshot |
| `GET /api/graph/rdt` | RDT multi-symbol ranked signals |
| `GET /api/events` | SSE stream (all events) |
| `POST /api/events/push` | Push custom event to SSE |
| `GET /api/ftd` | FTD registry (GME/AMC) |
| `GET /api/marketplace` | Browse peer signal listings |
| `GET /api/hiring` | Browse agent job board |
| `GET /api/futures` | Browse signal futures |
| `GET /api/futures/leaderboard` | Top predictors |
| `GET /api/settlement` | Browse conditional contracts |

### Premium Endpoints (require `X-Payment-Token` header)
| Route | Cost | Description |
|-------|------|-------------|
| `POST /api/council` | 0.10 RLUSD | Multi-engine AI verdict for any symbol |
| `GET /api/scan` | 0.05 RLUSD | Full $1–$50 squeeze scanner |
| `GET /api/options` | 0.05 RLUSD | Institutional options flow |
| `GET /api/iwm` | 0.03 RLUSD | IWM 0DTE contract scorer |
| `POST /api/marketplace/read` | 0.02 RLUSD | Full signal thesis from marketplace |

### Discovery Endpoints
`GET /llms.txt`, `GET /.well-known/mcp.json`, `GET /.well-known/openapi.json`, `GET /.well-known/ai-plugin.json`, `GET /.well-known/agents.json`, `GET /.well-known/server.json` — all served as static files. Accessing these triggers an `AGENT_PROBE` SSE broadcast.

---

## OracleEngine (`core/oracle_engine.py`)

The central signal aggregator. Accepts a `services` dict, analyzes a symbol, and emits one directive:

- `BUY (IGNITION)` — confidence ≥ 82
- `BUY` — confidence ≥ 60
- `HOLD` — confidence ≥ 40
- `SELL` — confidence ≥ 20
- `SHIELD` — below threshold / high-risk

Regime labels: `ALPHA_EXPANSION`, `MACRO_COLLAPSE`, `NEUTRAL`, `SHIELD`.

Has a 60-second per-symbol cache (`_cache`). Results feed into `signal_history` and SSE broadcasts.

---

## Signal History (`core/signal_history.py`)

In-memory ring buffer. `record(symbol, event_type, data)` stores up to 200 events per symbol. `get_history(symbol, limit)` and `get_all_recent(limit)` for retrieval. Types recorded: `SQUEEZE_ALERT`, `OPTIONS_SWEEP`, `COUNCIL_VERDICT`, `MARKETPLACE_LISTING`.

---

## SSE Event Stream

`sse_queues` is a plain `list` of `queue.Queue` objects. Any component can push to it. Queue maxsize = 100; stale queues are cleaned up lazily.

Event types: `CONNECTED`, `AGENT_PROBE`, `AGENT_PAY`, `COUNCIL_VERDICT`, `SETTLEMENT_COMPLETE`, `FUTURES_SETTLED`, `SQUEEZE_ALERT`, and any custom type via `/api/events/push`.

---

## Signal Futures Market (`core/api/futures_bp.py`)

In-memory prediction market (`_futures: dict`). Agents stake RLUSD on what the next council verdict will be. Platform fee: 5% of pot. Max 2000 futures globally, 30 per wallet. Valid symbols: `IWM SPY QQQ GME AMC MSTR NVDA TSLA PLTR HOOD`.

---

## Conditional Settlement (`core/api/settlement_bp.py`)

In-memory escrow contracts (`_contracts: dict`). Zero custody — SqueezeOS tracks intent and proof only. Platform fee: 1% on settlement. Conditions: `bias_match`, `confidence_above`, `price_above`, `price_below`, `time_elapsed`. Max 1000 contracts, 20 per wallet.

---

## Peer Marketplace (`core/api/marketplace_bp.py`)

In-memory listings (`_listings: dict`). Free to list; 0.02 RLUSD to read full thesis. Max 500 listings, 10 per seller. Each sale grants +2 Credit Bureau score points to seller.

---

## Agent Analytics (`core/api/agent_analytics.py`)

`before_analytics` / `after_analytics` middleware runs on every request. Classifies traffic by User-Agent into: `claude`, `gpt`, `gemini`, `grok`, `python-bot`, `curl`, `human`, etc. Tracks a funnel: `discovery → free_trial → invoice → payment → premium`. Ring buffer, zero external deps.

---

## Honeypot (`core/api/honeypot.py`)

Registered **before all other blueprints**. Trap routes (e.g., `/wp-admin`, `/.env`, `/phpmyadmin`) return 200 with fake data to identify malicious scanners.

---

## Data Providers (`data_providers.py`)

Priority order: **Tradier → Alpaca → Polygon → Alpha Vantage**

- `TradierProvider` — preferred for options chains (real-time with brokerage account, 15-min delayed sandbox)
- `AlpacaProvider` — real-time IEX quotes (free tier)
- `PolygonProvider` — 5 calls/min free tier
- `AlphaVantageProvider` — 25 calls/day free tier

---

## Deployment

### Render (primary)
`render.yaml` — Docker runtime, `python:3.11-slim`, gunicorn 1 worker 4 threads, port 8182. Health check: `GET /api/status`. Auto-deploy on push to `main`.

### Vercel (serverless fallback)
`vercel.json` + `api/index.py`. Detected via `VERCEL=1` env var — background threads skipped, only request-scoped handlers work.

### Docker
```bash
docker build -t squeezeos .
docker run -p 8182:8182 --env-file .env squeezeos
```

### Local
```bash
cp .env.example .env
# Fill in at minimum TRADIER_API_KEY and PROOF402_TOKEN_SECRET
pip install -r requirements.txt
python core/app.py   # or: gunicorn "core.app:create_app()"
```

---

## Environment Variables

All vars documented in `.env.example`. Key ones:

| Variable | Required | Purpose |
|----------|----------|---------|
| `TRADIER_API_KEY` | Yes (for options) | Tradier data provider |
| `TRADIER_ENV` | Yes | `sandbox` or `production` |
| `PROOF402_TOKEN_SECRET` | Yes (for premium) | HMAC secret for JWT verification |
| `PROOF402_SERVER_URL` | No | Defaults to `https://four02proof.onrender.com` |
| `DISCORD_WEBHOOK_ALL` | No | Discord alert channel |
| `POLYGON_API_KEY` | No | Polygon fallback |
| `ALPACA_API_KEY` / `ALPACA_API_SECRET` | No | Alpaca fallback |
| `PORT` | No | Defaults to `8182` |
| `FORCE_SSL` | No | `true` to enable TLS (needs cert files) |
| `NEO4J_URI` | No | Neo4j AuraDB URI (GraphiFY). Omit to disable graph. |
| `NEO4J_USERNAME` | No | Neo4j username |
| `NEO4J_PASSWORD` | No | Neo4j password |
| `NEO4J_DATABASE` | No | Neo4j database name |
| `OPENAI_API_KEY` | No | Required only by `scriptmaster_bp` (Beastmode `/api/scriptmaster/ingest_intel`, `/ai_brief`) |
| `SQUEEZEOS_BASE_URL` | No | Self-referencing base URL used by MCP proxy. Defaults to `https://squeezeos-api.onrender.com` |

---

## GitHub Actions

| Workflow | Trigger | Purpose |
|----------|---------|---------|
| `agent.yml` | Cron (5× weekday: 08:45, 09:35, 12:00, 15:00, 16:15 ET) | Runs `agent/sml_agent.py` — autonomous Claude agent that pays for market data with XRPL wallet |
| `keepalive.yml` | Cron | Pings Render + Onrender services to prevent cold starts |
| `publish-npm.yml` | Push/tag | Publishes npm package |
| `publish-pypi.yml` | Push/tag | Publishes PyPI package |

---

## Autonomous Agent (`agent/sml_agent.py`)

A Claude-powered agent with its own XRPL wallet. Uses `anthropic` SDK with tool use to:
1. Call free `signal_preview` to get IWM bias
2. If needed, call `get_invoice` → pay RLUSD on XRPL → `verify_payment` → call `council_verdict`
3. Decide a trade thesis and post it

Secrets: `AGENT_XRPL_SEED`, `AGENT_XRPL_ADDRESS`, `ANTHROPIC_API_KEY` (GitHub Actions secrets).

---

## Deployment — Source of Truth

> ⛔ STOP. Before touching any URL, service name, or deployment config — read this table first.
> Railway is DEAD for this project. `squeeze-os` Vercel project was DELETED May 2026.
> The only correct URLs are listed below. Do not guess. Do not use Railway URLs.

| Service | Platform | Canonical URL | Config |
|---------|----------|---------------|--------|
| SqueezeOS API | **Render** | `https://squeezeos-api.onrender.com` | `render.yaml` |
| Ghost Layer (bridge backend) | **Render** | `https://ghost-layer.onrender.com` | `ghost-layer/render.yaml` |
| Ghost Layer Sovereign (frontend) | **Vercel** | `https://www.scriptmasterlabs.com` | project: `ghost-layer-sovereign` |
| 402Proof | **Render** | `https://four02proof.onrender.com` | separate repo |
| SML Rails (RLUSD Rails) | **Render** | `https://sml-rails.onrender.com` | `SML-XRPL-FEE-FORGE/rails/` |

**SML-XRPL-FEE-FORGE repo** (`github.com/Timwal78/SML-XRPL-FEE-FORGE`, private) contains 4 products:

| Directory | Product | Deployed URL | Status |
|-----------|---------|-------------|--------|
| `rails/` | RLUSD Rails™ | `https://sml-rails.onrender.com` | ✅ Live on Render |
| `tiphawk/` | TipMaster™ | `https://sml-tiphawk.onrender.com` | ⚠️ Deploy failing — requires **paid X.com API** (Twitter tipping). Health check times out because service can't initialise without valid X API credentials. Do NOT debug as a port issue — it's a billing/credentials blocker. |
| `copytrader/` | XRPL Copy-Trader Engine™ | unknown | ❓ check Render dashboard |
| `launchpad/` | Memecoin Launchpad (Forge)™ | unknown | ❓ check Render dashboard |

**echo-forge repo** (`github.com/Timwal78/echo-forge`, public) — historical pattern matching engine (Polygon.io + ML cosine similarity). Dockerized, NOT yet deployed to Render as of May 2026.

**scriptmasterlabs.com products and their actual backends:**
- Ghost Layer Sovereign → Ghost Layer backend (`ghost-layer.onrender.com`) + Vercel frontend
- Xahau Hooks Intelligence → Ghost Layer's `xahau.go` URITokenMint (same service)
- Xahau Remittance Rails → `sml-rails.onrender.com` (SML-XRPL-FEE-FORGE/rails)
- Pulse-Verify™ Notary → 402Proof `/v1/verify` (same service)
- XRPL Copy-Trader Engine → SML-XRPL-FEE-FORGE/copytrader (deployment TBD)
- Memecoin Launchpad → SML-XRPL-FEE-FORGE/launchpad (deployment TBD)

## Ecosystem Services

| Service | Platform | URL | Role |
|---------|----------|-----|------|
| SqueezeOS | Render | `squeezeos-api.onrender.com` | This repo — market intelligence API + MCP server |
| 402Proof | Render | `four02proof.onrender.com` | x402 payment firewall, invoice generation, XRPL payment verification, Agent Credit Bureau |
| Ghost Layer | Render | `ghost-layer.onrender.com` | Dual-chain XRPL+Base toll gateway (Go service, `ghost-layer/`) |
| SML Rails | Render | `sml-rails.onrender.com` | RLUSD Rails — XRP/Xahau remittance (SML-XRPL-FEE-FORGE/rails) |
| Script Master Labs | Vercel | `scriptmasterlabs.com` | Operator homepage + Ghost Layer Sovereign frontend |

---

## Key Conventions

- **Blueprint naming**: each domain gets its own file in `core/api/`. Blueprint variable named `<domain>_bp`.
- **Serverless guard**: wrap any background thread start in `if not _IS_SERVERLESS:`.
- **No mock data**: if a service is `None`, return `503` not fake data.
- **Data sanitization**: always pass data through `clean_data()` before `jsonify()` to avoid NaN serialization errors.
- **SSE broadcast**: call `_broadcast_sse(event)` (or `state.push_terminal(...)`) — never write to `sse_queues` directly.
- **Token verification**: happens synchronously in the decorator, no async calls. If `PROOF402_TOKEN_SECRET` is empty, the middleware returns `ERR_SECRET_NOT_CONFIGURED`.
- **In-memory storage**: futures, settlements, marketplace listings are all in-memory dicts — they reset on server restart. This is intentional for the MVP.
- **Caching pattern**: use a local `_cache: dict` with a TTL check (`time.time() - entry["ts"] < TTL`) inside the route handler.
- **Security headers**: applied globally in `add_security_headers` after_request hook. Do not override them per-route.
- **Pine Scripts**: `pine/` and `indicators/` contain TradingView Pine Script v5 indicators. Do not rename functions — TradingView identifiers are user-facing.
- **GraphiFY graceful degradation**: `get_graph()` returns `None` when Neo4j env vars are missing or connection fails. Every caller checks `if not graph: return 503`. Never assume the graph is available.
- **OpenMythos (RDT) degraded mode**: `RecurrentDepthTransformer` accepts `graph=None` and falls back to price/vpin-only scoring — it will not crash without Neo4j.
- **Superpower (Beastmode) protocols** run async in daemon threads — `POST /api/scriptmaster/run_protocol` returns immediately. Results appear in the mission log ring buffer (50 entries), not the response body.
- **In-memory stores reset on restart**: `_futures`, `_contracts`, `_listings`, `_scan_cache`, `_preview_cache`, `_demo_cache`, `_MISSION_LOG`, `signal_history` — all lost on redeploy. This is intentional for MVP; do not add disk persistence without discussion.
- **MCP tool count**: the `_TOOLS` list in `mcp_bp.py` is the source of truth (currently 23 tools). The `_SERVER_INFO` version string is `"3.0.0"`. Update both when adding tools.
- **Blueprint registration order matters**: honeypot first, then analytics middleware, then all domain blueprints. Changing this order can cause trap routes to be shadowed or analytics to miss requests.

---

## Testing

Tests live in `tests/` and root-level `test_*.py` files. They are integration tests that hit `localhost:8182` — start the server before running.

```bash
python tests/test_battle_sync.py
python tests/test_cie_cycle.py
python tests/test_mmle_meme_cycle.py
```

There is no automated test runner configured. All tests are manual or run via GitHub Actions with a live server.
