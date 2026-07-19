# OPERATOR TODO — Timothy's Action Items

**Purpose:** you have memory issues and multiple agents work on this codebase — this file is the durable, checked-in source of truth for everything that's built and working but waiting on *you* specifically (a credential, a dashboard click, or a yes/no decision). Nothing in this list requires touching code. When you resolve an item, delete its line (or ask any agent to do it and update `CLAUDE.md` if the underlying feature doc references it).

Last compiled: 2026-07-19, from `CLAUDE.md`'s documented state. If it's been a while, ask an agent to re-scan `CLAUDE.md` for `awaiting`/`not yet`/`blocked on`/`suspended` markers and refresh this file — some items below may already be resolved.

---

## 🔴 Need a real credential/account only you can get

- [ ] **AWS Marketplace** — dedicated IAM user with only `GetEntitlements`/`ResolveCustomer`/`BatchMeterUsage` perms (policy JSON in `.env.example`), then set `AWS_MARKETPLACE_PRODUCT_CODE`, `AWS_MARKETPLACE_ACCESS_KEY_ID`, `AWS_MARKETPLACE_SECRET_ACCESS_KEY` on `squeezeos-api` Render service. Blocks the "Update product visibility" audit from ever passing.
- [ ] **AEO Treasury** — a dedicated XRPL wallet, then set `AEO_TREASURY_XRPL_ADDRESS`. Until set, revenue still accrues in the ledger but auto-hire silently no-ops.
- [ ] **Settlement Router (x402, Base)** — a Gnosis Safe treasury, then deploy `SettlementRouterFactory` to Base and create a router for the orchestrator. Real code, zero live deployment yet.
- [ ] **SML-Vault-Executor** — fund the vault, then set `VAULT_ADDRESS`, `EXECUTION_RPC_URL`, `EXECUTION_PRIVATE_KEY`.
- [ ] **TipMaster™ (Farcaster)** — `NEYNAR_API_KEY`, `NEYNAR_WEBHOOK_SECRET`, `NEYNAR_BOT_SIGNER_UUID`, `TIPMASTER_BOT_FID`, `TIPMASTER_XRPL_SEED`, `TIPMASTER_XRPL_ADDRESS`, `TIPMASTER_TREASURY_ADDRESS`. Also currently suspended on Render (your own action, 2026-07-04) — un-suspend when ready.
- [ ] **Shadow Desk** — `INGEST_SECRET`, `ALPHA_PROVIDER_WALLET`, `PLATFORM_WALLET`, `ADMIN_API_KEY`. Also currently manually suspended on Render (2026-07-04) — un-suspend when ready.
- [ ] **XRPL Copy-Trader Engine** — `COPYTRADER_DB_URL` (Postgres), `OPERATOR_WALLET_SEED`, `OPERATOR_WALLET_ADDRESS`, `DISCORD_WEBHOOK_COPYTRADER`.
- [ ] **Memecoin Launchpad (Forge)** — `LAUNCHPAD_DB_URL` (Postgres), `OPERATOR_WALLET_SEED`, `OPERATOR_WALLET_ADDRESS`, `DISCORD_WEBHOOK_LAUNCHPAD`.
- [ ] **Forge x402 Gateway (Go)** — `MERCHANT_WALLET_ADDRESS`, `XRPL_NOTARY_WALLET_ADDRESS`, `XRPL_NOTARY_WALLET_SEED`, `REDIS_URL`.

## 🟡 Stripe products — create in dashboard, then set the price IDs

- [ ] **Trade Desk (Swarm Agents Intelligence)** — create Trader ($19/mo) and Pro ($49/mo) products in Stripe, then set `TRADE_DESK_STRIPE_TRADER_PRICE_ID`, `TRADE_DESK_STRIPE_PRO_PRICE_ID`, `TRADE_DESK_STRIPE_WEBHOOK_SECRET`. Separately: have the Abacus.AI dashboard point its checkout buttons at these and call `POST /api/trade-desk/key/validate`.
- [ ] **ScriptMaster DeltaForge™** — create operator ($49) and elite ($149) products in Stripe, then set the `DELTAFORGE_STRIPE_*` env vars (mirrors Trade Desk pattern).
- [ ] **AEO Treasury webhook events** — in the Stripe dashboard, add `invoice.paid` and `invoice.payment_succeeded` to the `/api/aeo/stripe/webhook` endpoint's event list (they weren't in the original 4-event setup, so treasury accrual has been silently missing these).

## 🟢 Founder/owner bypass keys — optional, set whenever convenient

- [ ] `TRADE_DESK_OWNER_KEY` — guarantees your account always validates `tier: pro` regardless of dashboard bugs. Only takes effect once Abacus.AI actually calls the validate endpoint (not yet, as of 2026-07-10).
- [ ] `DELTAFORGE_OWNER_KEY` — permanent free elite access, independent of Stripe.

## 🔵 Decisions awaiting your explicit sign-off (no credentials needed)

- [ ] **Engine allowlist** — `IAM_SYMBOL_ALLOWLIST=SPY,IWM,QQQ,NVDA,HOOD` is the backtested recommendation from the 2026-07-17 engine scoreboard (`docs/ENGINE_SCOREBOARD_2026-07-17.md`). Not applied — needs your go-ahead. Note: your 2026-07-19 directive was that symbol universes should stay dynamic ("I don't even trade those") — worth deciding whether this recommendation still applies or is superseded.
- [ ] **ORB v6 as PRIMARY trading system** (`IAM_PRIMARY_SYSTEM=SML_ORB_MM`) — you asked for this, but the real backtest (`tests/backtest_orb_mm.py`, 29 sessions × 5 symbols) came back losing in almost every config (PF 0.44–1.30). Not set. A longer paper burn-in could change this — your call whether to wait or set it anyway knowing the current evidence.
- [ ] **IMO live arming** — paper mode has been running by default since 2026-07-19. Going live needs `IAM_PAPER_MODE=false` + `IAM_AUTO_TRADING=true` + `IAM_EXECUTION_MODE=tradier|both`, and should only happen after you've reviewed paper results (per your own 2026-07-18 exchange where you said "just fix and go live" but agreed to a paper burn-in first).
- [ ] **DeltaForge live arming** — same rule, separate flag: `DELTAFORGE_ARM_LIVE=true` (BYOK client-side, not server-side).
- [ ] **LEVIATHAN / Virtuals ACP visibility** — go to `app.virtuals.io`, find `virtualAgentId 106978`, graduate/mint it as an agent NFT, and fill in its profile description. **This cannot be done from code or CLI at all** — confirmed by inspecting the full Virtuals SDK surface. It's the only reason your ~54 live LEVIATHAN offerings don't show up in marketplace search.

## 🟣 Recurring review queues — check periodically, not one-time

- [ ] **Grant proposals**: `curl https://squeezeos-api.onrender.com/api/grants/queue` — Grant Scout drafts these every 4h; approving only flips status, never auto-submits.
- [ ] **Gap-to-build proposals** (new, 2026-07-19): `curl https://squeezeos-api.onrender.com/api/gap-proposals/queue` — Gap Synthesist drafts these every 4h from real Reddit/HN demand signals; approving only flips status, never auto-deploys code. **Needs `GAP_PROPOSALS_QUEUE_SECRET` set on Render + as a GitHub Actions secret before it can accept any drafts at all** — this one's not just "check periodically," it's currently non-functional without that secret.

---

*This file intentionally does not duplicate the deep technical detail behind each item — that lives in `CLAUDE.md`, organized by product. This is the flat action list.*
