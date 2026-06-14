# xDEO — x402 Decentralized Earnings Oracle

> A machine-native marketplace for corporate **earnings estimates**. Analysts
> publish EPS/revenue opinions; the protocol **automatically scores them against
> real SEC EDGAR filings** and compounds an on-chain reputation. AI agents
> discover and pay per estimate via **x402 (USDC on Base)**.
>
> **Zero custody. Public data only. Not investment advice.** Estimates are
> opinions, not securities. No broker-dealer activity. No KYC. The service never
> holds or routes user funds — x402 payments settle peer-to-peer.

This is the **functional core** (Phase 1–2 + the AI-agent discovery layer of
Phase 5) of the xDEO build. It lives as a self-contained subproject inside the
SqueezeOS x402/MCP ecosystem.

---

## What's built

| Area | Status | Where |
|------|--------|-------|
| Cloudflare Workers + Hono API | ✅ | `src/index.ts`, `src/routes/` |
| Real SEC EDGAR ingestion (submissions + XBRL companyconcept) | ✅ | `src/edgar/` |
| Auto-scoring of open estimates on filing (5-min cron) | ✅ | `src/edgar/ingest.ts`, `src/reputation/apply.ts` |
| Reputation engine (accuracy × timeliness × streak, compounding) | ✅ | `src/reputation/engine.ts` |
| x402 payment gate (HTTP 402 → facilitator verify/settle) | ✅ | `src/x402/middleware.ts` |
| Tiers (Observer→Legend), streaks, referrals, agent affiliates | ✅ | schema + routes |
| MCP server (JSON-RPC 2.0) | ✅ | `src/mcp/server.ts` |
| Agent manifest + OpenAPI + llms.txt | ✅ | `src/lib/manifest.ts`, `public/llms.txt` |
| Shareable OG estimate cards (SVG) | ✅ | `src/og/card.ts` |
| D1 schema | ✅ | `migrations/0001_init.sql` |
| Unit tests (35, pure logic) | ✅ | `test/` |
| Smart contracts (Base) | 🚧 interfaces only | `contracts/` |
| Next.js frontend | 🚧 roadmap | — |
| Twitter/X bot, embeds, prediction-market integration | 🚧 roadmap | — |

> ⚠️ The EDGAR endpoints are blocked from the build sandbox's egress allowlist,
> so live ingestion was validated by code + unit tests against the documented
> EDGAR response shapes, not a live call from CI. It runs on Cloudflare Workers,
> which can reach `data.sec.gov`.

---

## Architecture

```
Agent / browser
   │  x402 (USDC on Base)            MCP (JSON-RPC)
   ▼                                  ▼
┌──────────────────────────────────────────────┐
│ Cloudflare Worker (Hono)                       │
│  /api/v1/*   /mcp   /.well-known/*   /og/*      │
│  requirePayment ── facilitator verify/settle ──┼──► x402 facilitator → Base
│  cron(5m) ── EDGAR submissions + XBRL ──────────┼──► data.sec.gov (free)
│  reputation engine (pure) ─► scoring            │
└───────────────┬────────────────────────────────┘
                ▼
        Cloudflare D1 (SQLite)   +   KV (cache/ratelimit)
```

## Reputation model (the "market for truth")

Each scored estimate yields `score ∈ [0,100]` from three terms:

- **Accuracy** — `exp(-relativeError / 0.144)` (≈0.5 at 10% error).
- **Timeliness** — full credit at ≥30 days lead, 0.25 floor for last-minute calls.
- **Confidence as stake** — confident hits rewarded, confident misses punished harder.

Reputation folds in each score via a bounded EMA (alpha floor 0.08) so it
**compounds**: a long record is hard-won and one miss can't erase it, nor one hit
fake it. Streaks (7d→1.5×, 30d→2.5×, 100d→5×) amplify gains only. See
`src/reputation/engine.ts` and the 21 unit tests in `test/reputation.test.ts`.

## API

Free: `GET /api/v1/tickers`, `/tickers/:t`, `/analysts`, `/analysts/:addr`,
`/verdict/:filingId`, `/agents/leaderboard`, `POST /estimates`,
`GET /.well-known/agent-manifest.json`, `/api/v1/openapi.json`, `/llms.txt`, `/mcp`.

x402-gated: `GET /api/v1/tickers/:t/estimates` ($0.01), `GET /api/v1/estimates/:id`
(analyst-priced, $0.01–$5.00).

### Agent affiliate program

Send `X-AGENT-ID` on any request. Reads you drive credit you 15% of the fee
(`AGENT_AFFILIATE_BPS`). Register a payout address at `POST /api/v1/agents/track`.

## Develop

```bash
npm install
npm test            # 35 unit tests
npm run typecheck
npm run dev         # wrangler dev (needs D1 + KV bound)

# Provision infra (one-time), then migrate:
#   wrangler d1 create xdeo   → paste database_id into wrangler.toml
#   wrangler kv namespace create KV → paste id into wrangler.toml
npm run db:migrate:local
npm run deploy

# Secrets (never commit):
wrangler secret put X402_PAY_TO            # Base wallet that receives fees
wrangler secret put X402_DEV_BYPASS_TOKEN  # optional local test bypass
```

## Roadmap (remaining phases)

- **Phase 3** — implement `contracts/` (Foundry tests + audit), soulbound badges, treasury governance.
- **Phase 4** — Next.js frontend, leaderboard embeds, Verdict threads, X bot.
- **Phase 5+** — WebSocket streaming, prediction-market read-through, agent bounty payouts.

## Legal

xDEO is an information service. It does not create, trade, or reference
securities or investment products; provides no investment advice; performs no
broker-dealer activity; and never custodies or routes user funds. All underlying
data is free public data (SEC EDGAR). x402 is permissionless; users connect
wallets only.
