<!-- gitnexus:start -->

# OPERATOR NOTES — READ FIRST

**Owner:** Timothy (TimmyCrypto / Timwal78) — disabled veteran, memory issues. Do NOT rely on him to remember prior decisions, service names, env vars, or build state. You must carry full context yourself. Always recap what exists before starting new work.

## Render Services — Current State (as of 2026-06-26)

| Service | Render Name | URL | Status | Purpose |
|---------|-------------|-----|--------|---------|
| SqueezeOS API | `squeezeos-api` | `https://squeezeos-api.onrender.com` | ✅ Live | Main Flask monorepo — AI Council, CASCADE ACCUMULATOR, Slack bot, 52 MCP tools |
| SML Vault Executor | `sml-vault-executor` | `https://sml-vault-executor.onrender.com` | 🅿️ Parked | Future vault execution layer (Base mainnet). Currently runs squeezeos-api repo as placeholder. Gets its own codebase when vault is funded. Custom domain: `dash.scriptmasterlabs.com` |

**NEVER confuse these two services.** `squeezeos-api` is production. `sml-vault-executor` is parked/future.

## CASCADE ACCUMULATOR — Live Product

- Blueprint: `core/api/cascade_bp.py` — registered at `/api/cascade`
- Slack command: `/cascade [SYMBOL]` → ENTER/ADD/EXIT/STOP directive
- x402 payment: 0.25 RLUSD/call (AI agents)
- Stripe subscription: $149/mo — `price_1TmbGJQL50L4TFzsUsure8N0` (product `prod_Um9XO3d5Yi7TFd`)
- Stripe webhook: `POST /api/cascade/stripe/webhook` → issues Redis API keys on subscription
- Required Render env vars: `CASCADE_STRIPE_PRICE_ID`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_SECRET_KEY`, `REDIS_URL`

## AEO/GEO Intelligence Suite — Live Product

- Pricing page: `aeo.scriptmasterlabs.com` (SML_Portfolio repo, `aeo.html`)
- Tiers: Scout (free, heuristics), Signal ($49/mo, BYOK), Sovereign ($149/mo, priority BYOK)
- Blueprint: `core/api/aeo_stripe_bp.py` — registered at `/api/aeo/stripe/webhook` and `/api/aeo/key/validate`
- Stripe products (live mode, account `acct_1S07wtQL50L4TFzs`):
  - Signal: `price_1TpAMgQL50L4TFzsWONxGtl8`
  - Sovereign: `price_1TpAMoQL50L4TFzsAsM9vLbw`
- Required Render env vars: `AEO_STRIPE_SIGNAL_PRICE_ID`, `AEO_STRIPE_SOVEREIGN_PRICE_ID`, `AEO_STRIPE_WEBHOOK_SECRET`, `STRIPE_SECRET_KEY` (shared), `REDIS_URL` (shared)
- Self-advertising loop: `.github/workflows/aeo-selfad.yml` (daily 06:00 ET) runs `.github/scripts/aeo_selfad_loop.py` — S1 gap detection → S2 narrative check → S3 citation probe → S4 agent-economy read. Optional n8n upgrade path documented in `n8n/README.md` — not required, GitHub Actions keeps running either way.

### AEO Treasury — revenue ledger + auto-hire (`core/api/aeo_treasury_bp.py`)

- `GET /api/aeo/treasury` — bookkeeping ledger tracking a 5% cut of AEO Suite revenue. **This is accounting only — it does not move real money.** Stripe settles in USD to the bank account on file; there is no automatic USD→RLUSD conversion anywhere in this codebase.
- `accrue_usd()` is called from `aeo_stripe_bp._handle_invoice_paid()` on every paid AEO invoice (`invoice.paid` / `invoice.payment_succeeded` Stripe events — **must be added to the webhook endpoint's event list in the Stripe dashboard**, they weren't in the original 4-event setup).
- When the ledger crosses `AEO_TREASURY_HIRE_THRESHOLD_RLUSD` (default 25.0), it auto-posts a real job to the existing zero-custody `hiring_bp` board using `AEO_TREASURY_XRPL_ADDRESS` as poster — no private key involved, posting a job never requires signing.
- `AEO_TREASURY_XRPL_ADDRESS` is unset by default (same "not yet configured" pattern as SML-Vault-Executor below) — until it's set, the ledger still accrues but auto-hire silently no-ops and logs why.
- Getting a hired agent actually paid still requires the treasury wallet to hold real RLUSD — that's a manual funding step (e.g., periodically converting a slice of Stripe payout revenue and sending it on-chain), not something this code does automatically.

## Trade Desk (Swarm Agents Intelligence) — Live Product

- Dashboard: `swarmagentsintelligence.scriptmasterlabs.com` — 10-agent trading desk UI (Battle Computer, Oracle Journal, Pine Signals, Market Counsel, GEX/ODTE/liquidity/dark-pool analysis, etc.). **Built and hosted externally on Abacus.AI — its frontend source is NOT in this repo or any repo in this account.** This repo only provides the billing backend the dashboard calls.
- Launch pricing tiers: Free ($0, landing page only, no dashboard access), Trader ($19/mo, full dashboard + all 10 agents + Pine Signals + Oracle Journal + Battle Computer + shareable signal cards + 5-ticker watchlist), Pro ($49/mo, unlimited watchlist + Market Counsel LLM + BYOK Tradier execution panel + priority refresh).
- Blueprint: `core/api/trade_desk_stripe_bp.py` — registered at `/api/trade-desk/stripe/webhook` and `/api/trade-desk/key/validate`
- Stripe products: not yet created — see `.env.example` for the exact env vars to fill in (`TRADE_DESK_STRIPE_TRADER_PRICE_ID`, `TRADE_DESK_STRIPE_PRO_PRICE_ID`, `TRADE_DESK_STRIPE_WEBHOOK_SECRET`). Shares `STRIPE_SECRET_KEY` and `REDIS_URL` with CASCADE/AEO.
- Because the dashboard isn't in this codebase, wiring it up still needs a manual step on the Abacus.AI side: point its checkout buttons at Stripe Checkout Sessions for the two price IDs above, and have it call `POST /api/trade-desk/key/validate` with the issued `td_...` key to gate Trader/Pro-only pages.
- Owner bypass: set `TRADE_DESK_OWNER_KEY` (a private static secret, unrelated to Stripe/Redis) and use it as the dashboard's stored `api_key` to guarantee the operator's own account always validates as `tier: "pro"` — insurance against dashboard-side tier-gating bugs locking the owner out of their own product. Unset by default (no-op until configured). As of 2026-07-10 the dashboard's tier-gating (built on Abacus.AI, separately from this repo) is mid-build and has been observed locking the owner out of Pro — this bypass only takes effect once the dashboard is wired to actually call `/api/trade-desk/key/validate`, which it is not yet.

## AWS Marketplace Entitlements — Fixing the AUDIT_ERROR (blocks visibility)

- The "Script Master Labs Federal, Medical & Finance MCP (x402)" AWS Marketplace listing (product ID `prod-lop2m2yjjcs76`, contract pricing model) has failed "Update product visibility" twice with `AUDIT_ERROR`: AWS requires a successful `GetEntitlements` call (verified via CloudTrail) before visibility can go public, and no code anywhere in this account ever called it.
- Fixed 2026-07-11: `core/api/aws_marketplace_bp.py`, registered at `/api/aws-marketplace` — real `boto3` integration (`meteringmarketplace` client for `ResolveCustomer`/`BatchMeterUsage`, `marketplace-entitlement` client for `GetEntitlements`). A background self-check fires once at every app boot (`run_entitlements_self_check()` in `core/app.py`) and makes one real `GetEntitlements` call the moment credentials are configured — that's what produces the CloudTrail record the audit checks for. A prior agent (Google Antigravity) apparently attempted this and failed; nothing from that attempt was ever pushed to GitHub, so this was built from scratch.
- **Still blocked on the owner providing real AWS resources** — until these are set on the `squeezeos-api` Render service, the self-check no-ops (logs why) and the audit keeps failing:
  - `AWS_MARKETPLACE_PRODUCT_CODE` — from the Product summary tab (same page as `prod-lop2m2yjjcs76`)
  - `AWS_MARKETPLACE_ACCESS_KEY_ID` / `AWS_MARKETPLACE_SECRET_ACCESS_KEY` — a **dedicated** IAM user (do not reuse other AWS creds) with only `aws-marketplace:GetEntitlements`, `aws-marketplace:ResolveCustomer`, `aws-marketplace:BatchMeterUsage` (see `.env.example` for the exact IAM policy JSON)
  - `AWS_MARKETPLACE_REGION` — optional, defaults to `us-east-1` (Marketplace Metering/Entitlement APIs only exist there)
- Also required in the AWS Marketplace Management Portal (not an env var): under **Fulfillment options**, set the Fulfillment URL to `https://squeezeos-api.onrender.com/api/aws-marketplace/resolve` so AWS redirects subscribing customers there for `ResolveCustomer` + `GetEntitlements`.
- Once those three env vars are set and the service redeploys, check `GET /api/aws-marketplace/status` — `last_self_check.ok: true` confirms the real call succeeded and you can resubmit the "Update product visibility" request.
- In-memory resolved-customer store (`_customers` in the blueprint) resets on restart — same MVP pattern as `_futures`/`_contracts`/`_listings`. Do not add persistence without discussion.

## Autonomous Grant Agent — Discovery → Qualify → Draft → Human Approval

Built 2026-07-13. **Zero custody, zero autonomous submission** — this was an explicit operator decision (Timothy chose "full human approval, zero custody" over letting the agent auto-submit low-tier applications). No code anywhere in this feature signs a transaction, holds a wallet seed, or files an application on Timothy's behalf.

- `agent/dept/grant_scout.py` — new specialist under the CEO (`campaign_director.py`), runs every 4h with the rest of the marketing department (`.github/workflows/marketing-daily.yml`). Reuses `federal_scout.py`'s SBIR/NIH x402 data and `SML_CAPABILITIES` profile. Scores each opportunity 0-100 against SML's stack; only opportunities scoring ≥85 get a drafted proposal (capability statement + milestones + USD/RLUSD budget outline) via Claude, which is then POSTed to the review queue. Its only side effect is that one HTTP POST — nothing is submitted to a funder.
- `core/api/grants_bp.py`, registered at `/api/grants` — the review queue itself. `GET /api/grants` and `/api/grants/queue` are public/read-only. `POST /submit`, `/<id>/approve`, `/<id>/reject` require `X-Grants-Secret` matching `GRANTS_QUEUE_SECRET`. Approving an item only flips its status — it does **not** submit anything anywhere. In-memory (`_queue`), resets on restart — same MVP pattern as `_futures`/`_contracts`/`_listings`/`_jobs`.
- Auto-archive: anything scoring below `GRANTS_QUALIFY_THRESHOLD` (default 85) is queued as `archived` instead of `pending_review`, so low-confidence matches never cost Timothy a review cycle.
- Required env vars: `GRANTS_QUEUE_SECRET` (shared between the Render service and the `marketing-daily.yml` GitHub Actions secret — same pattern as `MARKETING_ACTIVITY_SECRET`). Optional: `GRANTS_QUALIFY_THRESHOLD`.
- **Not wired yet — do not assume these exist:** Gitcoin Grants Stack / Allo Protocol, XRPL Grants Program, Virtuals Protocol launchpad grants, AWS Activate / Google Cloud for Startups credit pools. `grant_scout.py`'s docstring explicitly says not to fabricate a source for these without first confirming a real, current public API. Wiring any of them is future work, not done.
- **On-chain milestone escrow (XRPL `EscrowCreate`) was explicitly NOT built.** It was part of the original proposal but the operator decided against any agent-held signing key. If this is revisited later, it would need its own explicit decision (and likely its own dedicated wallet + spending-limit guardrails) — do not casually add XRPL signing to this feature.
- To review/approve from the CLI:
  ```bash
  curl https://squeezeos-api.onrender.com/api/grants/queue           # see what's pending
  curl -X POST https://squeezeos-api.onrender.com/api/grants/<id>/approve \
    -H "X-Grants-Secret: $GRANTS_QUEUE_SECRET"
  ```

## Gap Synthesist — Semantic Gap Detector → Build Proposal → Human Approval

Built 2026-07-19. Closes the loop on the **Semantic Gap Detector** (`core/api/gap_detector_bp.py`, live since before this date, `GET /api/graph/gaps`): that engine already finds real unmet developer demand from Reddit/HN and clusters it by topic, but nothing previously acted on what it found. **Zero custody, zero auto-deploy** — same operator-approval pattern as the Autonomous Grant Agent above. No code anywhere in this feature writes application code, opens a pull request, or merges anything.

- `agent/dept/gap_synthesist.py` — new specialist under the CEO (`campaign_director.py`), runs every 4h with the rest of the marketing department (`.github/workflows/marketing-daily.yml`). Reads the real, live gap leaderboard from `GET /api/graph/gaps`, scores each uncovered gap's build-worthiness 0-100 against SML's actual capability surface, and for anything scoring ≥60 drafts a concrete technical spec (proposed route, what existing module it extends, effort estimate, open questions for Timothy) via Claude, which is then POSTed to the review queue. Its only side effect is that one HTTP POST — nothing is written, opened, or deployed.
- `core/api/gap_proposals_bp.py`, registered at `/api/gap-proposals` — the review queue itself. `GET /api/gap-proposals` and `/api/gap-proposals/queue` are public/read-only. `POST /submit`, `/<id>/approve`, `/<id>/reject` require `X-Gap-Proposals-Secret` matching `GAP_PROPOSALS_QUEUE_SECRET`. Approving an item only flips its status to `approved_to_build` — it does **not** write or deploy any code; building it out remains a separate, ordinary dev task. In-memory (`_queue`), resets on restart — same MVP pattern as `_futures`/`_contracts`/`_listings`/`_jobs`/`_queue` (grants).
- Each queued proposal carries an `evidence_hash` — a SHA-256 digest over its gap topic, source evidence, and spec, computed at submit time. This is an honest integrity checksum anyone can recompute to confirm the record wasn't altered after logging. It is **not** a zero-knowledge proof, and nothing in this codebase claims otherwise — if a future agent is asked to add real ZK proofs here, that needs its own explicit decision (circuit choice, proving library) rather than a placeholder string.
- Auto-archive: anything scoring below `GAP_PROPOSALS_QUALIFY_THRESHOLD` (default 60) is queued as `archived` instead of `pending_review`, so low-confidence gaps never cost Timothy a review cycle.
- Required env vars: `GAP_PROPOSALS_QUEUE_SECRET` (shared between the Render service and the `marketing-daily.yml` GitHub Actions secret — same pattern as `GRANTS_QUEUE_SECRET`). Optional: `GAP_PROPOSALS_QUALIFY_THRESHOLD`.
- **Deliberately NOT built as part of this feature — do not assume these exist:** an SEO/AEO technical-issue scanner (Ahrefs-style 404/meta/indexability auto-fix). SqueezeOS already ships a live AEO/GEO Intelligence Suite (`aeo_stripe_bp.py`, `citation_scout_bp.py`) — a gap-fixer for that same surface would duplicate a live product without an explicit decision from Timothy. Also not built: any "malicious agent skill" security guardrail — this codebase doesn't host a third-party agent-skill marketplace, so that attack model (mutable payloads swapped in after review) has no real target here to guard. Either would need its own fresh, explicit ask before being built.
- To review/approve from the CLI:
  ```bash
  curl https://squeezeos-api.onrender.com/api/gap-proposals/queue           # see what's pending
  curl -X POST https://squeezeos-api.onrender.com/api/gap-proposals/<id>/approve \
    -H "X-Gap-Proposals-Secret: $GAP_PROPOSALS_QUEUE_SECRET"
  ```

## x402 Settlement Router — multi-agent Base/USDC payment-graph netting

Built 2026-07-16, in response to the "x402 Settlement Router" product spec (non-custodial payment netting layer for multi-agent AI economies, 0.5% protocol fee, Base/USDC). **Not deployed to any network yet** — this is real, tested code with no live contract address, same "not yet configured" status as SML-Vault-Executor and the AWS Marketplace integration below.

- **Where the actual money logic lives:** `mcp-x402-xrpl/asc-contracts/contracts/settlement-router/` — five Solidity contracts (`FeeRegistry`, `IReputationOracle`/`ReputationOracle`, `TaskEscrow`, `SettlementRouter`, `SettlementRouterFactory`) on Base. Non-custodial, no admin keys on `TaskEscrow` beyond a 7-day-timelocked emergency withdraw, fee hard-capped at 5% on-chain. `ReputationOracle`'s bond tiers mirror the *real* ARGUS/402Proof credit score scale already live in `mcp-x402-xrpl` (300-850 FICO-style — PROTOSTAR/NEUTRON/PULSAR/QUASAR), not the 0-1000 scale the original spec assumed.
- **Off-chain netting engine:** `mcp-x402-xrpl/src/settlement-router/netting.ts` — pure function, sums a payment graph's inflows/outflows per agent, validates the netted result against the task's real on-chain budget + fee before anything gets signed. `mcp-x402-xrpl/src/settlement-router/client.ts` wraps the actual contract calls.
- **HTTP surface:** `mcp-x402-xrpl/src/vending-router-server.ts`'s `/settlement-router/tasks*` routes (secret-gated via `X-Orchestrator-Secret`, not x402-metered — the real revenue event is the on-chain protocol fee, metering the HTTP trigger too would double-charge).
- **This repo's hook (`core/api/settlement_router_bp.py`, `/api/settlement-router`):** off-chain bookkeeping for a task's agent list + accumulated payment-graph edges, then forwards to the mcp-x402-xrpl HTTP surface above to actually create/settle on-chain. Deliberately a **new** blueprint, not an extension of `hiring_bp.py` or `settlement_bp.py` — both of those are single poster/executor pairs settling XRPL wallet-to-wallet by design; a multi-agent Base/USDC payment graph is a different shape of problem.
- Required env vars (all unset by default): `SETTLEMENT_ROUTER_API_BASE`, `SETTLEMENT_ROUTER_ORCHESTRATOR_SECRET` (this repo, calls out); `SETTLEMENT_ROUTER_RPC_URL`, `SETTLEMENT_ROUTER_ADDRESS`, `SETTLEMENT_ROUTER_ORCHESTRATOR_PRIVATE_KEY`, `SETTLEMENT_ROUTER_ORCHESTRATOR_SECRET` (mcp-x402-xrpl, holds the signing key) — see `mcp-x402-xrpl/render.yaml`.
- **Still needed before this is real money:** deploy `SettlementRouterFactory` to Base (`asc-contracts/scripts/deploy-settlement-router.ts`, needs a Gnosis Safe treasury — see PRD non-negotiable #6), create a router for this orchestrator (`create-router.ts`), and wire an agentDid-to-Base-address mapping for `update-reputation-oracle.ts` (ARGUS scores are keyed by DID; `TaskEscrow` bonds are keyed by address — nothing in either codebase maps one to the other yet, documented directly in that script rather than papered over).
- Solidity compiler note for future agents in this sandbox: `npx hardhat compile` needs `binaries.soliditylang.org`, which this session's egress policy blocks entirely (list.json fetch fails for every platform, including wasm). `asc-contracts/scripts/local-compile.cjs` compiles the same sources via the official `solc` npm package (real compiler, permitted registry) and writes Hardhat-format artifacts directly so `npx hardhat test --no-compile` still runs. Once run somewhere with normal network access, plain `npx hardhat compile` works unchanged.

## LEVIATHAN / Virtuals ACP Marketplace — Visibility Blocker (investigated 2026-07-16)

The Virtuals Protocol ACP marketplace listing for the LEVIATHAN seller agent ("scriptmasterlabs", `virtualAgentId` 106978, wallet `0x0f035c36c4ce65a6f1bf4370f779bac722d59004`) does not appear in ACP marketplace search despite having ~40-54 live offerings — a prior agent-run investigation confirmed this via direct search testing on the marketplace.

- **Root cause: the agent NFT has never been minted/"graduated" on Virtuals Protocol** (`erc8004AgentId: null`). An older ScriptMasterLabs ACP agent *was* minted (`erc8004AgentId 58311`, `virtualAgentId` different from 106978) and is visible in search, but has 0 live offerings — it's stale/superseded. The ACP browse API only returns agents with a minted `erc8004AgentId`.
- **Confirmed: this cannot be done from code/CLI.** Pulled and inspected `@virtuals-protocol/acp-node-v2@0.1.7`'s full type surface (`AcpAgent`, `clientFactory`, `core/operations`) — it only exposes job lifecycle methods (`createJob*`, `setBudget`, `submit`, `complete`, `reject`, `browseAgents`, `getAgentByWalletAddress`, `getMe`). There is no mint/graduate/publish-visibility/update-profile method anywhere in the SDK. Minting and profile fields (the listing's empty description was also flagged) are dashboard-only actions.
- **Manual action required (owner, not an agent):** go to `app.virtuals.io`, find the SCRIPT token agent (`virtualAgentId` 106978), and graduate/mint it as an agent NFT, then fill in its profile description. This is the only way to make it appear in ACP marketplace search.
- **Deployment discrepancy found while investigating — worth knowing so nobody chases the wrong code:**
  - The **live** LEVIATHAN agent runs from **`SML_Portfolio/mcp-x402`** (`src/server/acp/leviathan.ts`, 54 offerings, Title-Case job names e.g. `"SqueezeOS Council (7-Agent AI)"`), deployed as the Render service `mcp-x402`, with `ACP_WALLET_ADDRESS=0x0f035c36c4ce65a6f1bf4370f779bac722d59004` set directly in `SML_Portfolio/mcp-x402/render.yaml`. This is the wallet/agent from the visibility report above.
  - **`mcp-x402-xrpl/src/acp/leviathan.ts`** (12 offerings, snake_case job names, hardcoded wallet default `0x4e14B249D9A4c9c9352D780eCEB508A8eB7a7700` — actually the *payment-receiver* address, not an ACP wallet) is **not part of the deployed service**. `mcp-x402-xrpl`'s Render service (`scriptmaster-vending-router`, `render.yaml`) runs `start:vending-router` → `src/vending-router-server.ts`, which never imports or starts LEVIATHAN. The only place that repo's `leviathan.ts` gets wired up is `src/squeezeos-server.ts` (`npm start`), which is not the script Render actually runs. Treat `mcp-x402-xrpl/src/acp/leviathan.ts` as stale/orphaned — do not use its job names, wallet default, or offering count as a reference; `SML_Portfolio/mcp-x402/src/server/acp/leviathan.ts` is the one real agents talk to.

## SML-IMO Oscillator + Executor Hard Stops (built 2026-07-17)

**Operator decision (Timothy, 2026-07-17): paper-first auto-trading approved** — IMO/CASCADE signals → existing executor with hard stop-losses, fixed small sizing, daily loss cutoff. Explicitly NOT "a bot that always wins" (impossible; do not let anyone re-promise that). Live arming is a separate future decision.

- `indicators/SML_Institutional_Momentum_Oscillator_v6.pine` (SML-IMO) — zero-lag volume-force momentum oscillator (Jurik/Gaussian-4-pole/ZLEMA core, dynamic ±σ variance bands, Kaufman-ER regime filter, smart dashboard, early hook BUY/SELL signals). Built on PR #347.
- **Wire to execution:** the script's webhook bridge inputs (passphrase + signal mode) emit the exact JSON `/api/webhooks/tradingview` expects (`system: "SML_IMO"`, `EXECUTE_LONG`/`EXECUTE_SHORT`). One TradingView alert with condition "Any alert() function call" + webhook URL `https://squeezeos-api.onrender.com/api/webhooks/tradingview`. Requires `TV_WEBHOOK_PASSPHRASE` set on Render (fails closed without it).
- **Executor upgrades (`iam_executor.py`):**
  - `IAM_STOP_LOSS_PCT` (default 3.0) — on live BUY fills, a real GTC stop sell order is placed at entry−N% (`tradier_api.place_equity_order` now supports `order_type="stop"` + `stop_price`). Extended-hours entries can't carry a stop (Tradier restriction) — logged loudly instead.
  - **Fixed dead daily-loss breaker:** nothing ever called `record_fill()` before, so `IAM_DAILY_LOSS_LIMIT` could never trip. New in-process `_positions` ledger records entries/exits (paper AND live) and feeds realized P&L to the breaker. P&L basis is signal price, not broker fill — approximate by design, disclosed in `status()` as `pnl_basis`.
  - `iam_executor.status()` now reports `stop_loss_pct` + `open_positions`.
- **Paper desk runs OUT OF THE BOX (operator instruction 2026-07-19: "ok put it on paper mode")** — while `IAM_PAPER_MODE=true` (default), `IAM_AUTO_TRADING` defaults to armed and `IAM_EXECUTION_MODE` defaults to `both`, so paper signals + the position ledger + the loss breaker all run with zero Render config. The moment `IAM_PAPER_MODE=false`, the arm default flips back to DISARMED — live still requires both explicit flags. Also per operator directive the same day: **symbol universes are DYNAMIC, never hardcoded** ("I don't even trade those") — `IAM_SYMBOL_ALLOWLIST` is empty/opt-in, and the IMO/ORB scanners resolve their universe from env override → allowlist → live market-scanner candidates → quoted universe.
- **Paper mode is the default** (`IAM_PAPER_MODE=true`). Going live requires flipping `IAM_PAPER_MODE=false` + `IAM_AUTO_TRADING=true` + `IAM_EXECUTION_MODE=tradier|both` — do not flip these for Timothy without an explicit fresh decision from him, and only after paper results have been reviewed. (2026-07-18: Timothy said "JUST FIX AND GO LIVE" — agent could not flip Render env vars from the sandbox and recommended a paper burn-in first; the two-stage checklist was given to him. If he re-confirms after seeing paper signals, that satisfies the "fresh decision" bar.)
- **IMO runs natively in Python — TradingView is OPTIONAL** (built 2026-07-18 after Timothy asked "why can't you just run this in Python"): `imo_engine.py` is the single implementation of the IMO math (Pine script is a visual of the same math; `tests/backtest_imo.py` imports it — no drift). `imo_scanner.py` background loop (started in `core/app.py` beside `iam_scanner`) pulls real daily bars via DataManager and routes new signals to `iam_executor` under the full safety stack. Symbol universe is DYNAMIC (operator directive 2026-07-19, Prime Directive #1 — he does not trade a fixed list): env override → `IAM_SYMBOL_ALLOWLIST` → live market-scanner candidates → quoted universe; never hardcoded. Status/on-demand: `GET /api/imo/status`, `GET /api/imo/<symbol>` (`core/api/imo_bp.py`). Wire verified end-to-end in-sandbox with real SPY bars (scanner → engine → executor gates → paper alert). The TradingView webhook bridge still works too — both paths feed the same executor, and its cooldown dedups overlap.
- **"Delete what doesn't win" directive:** measured evidence first — `tests/backtest_imo.py` is the harness. No engine deletions were made on 2026-07-17; do not delete engines without backtest evidence + explicit operator sign-off per engine.
- **ORB v6 BEASTMODE (2026-07-19, operator-submitted Pine, wants it as PRIMARY trader):** `indicators/SML_ORB_MM_Intelligence_v6.pine` (hardened: NY-timezone OR window + webhook bridge, system `SML_ORB_MM`), Python twin `orb_engine.py` + `orb_scanner.py` (intraday 5MIN bars — needs Polygon/Alpaca key; idles honestly on Tradier-only), `/api/orb` blueprint. New executor gate `IAM_PRIMARY_SYSTEM` — when set, only that system's signals reach the broker, everything else downgrades to alert-only (untagged resolutions = "IAM"). **Backtest verdict (tests/backtest_orb_mm.py, 29 sessions × 5 symbols real 5-min bars, 4 param configs): ORB loses in essentially every configuration (PF 0.44–1.30, almost all totals negative).** Evidence was shown to Timothy; making it primary is HIS call via `IAM_PRIMARY_SYSTEM=SML_ORB_MM` on Render — do not set it for him, and do not let anyone claim this strategy is proven. Longer paper burn-in may change the verdict; 6 weeks of 5-min history was the maximum obtainable in-session.
- **Engine scoreboard (2026-07-17): measurement DONE** — `tests/backtest_engines.py` ran IMO/CASCADE/IAM on 10 symbols × 5y real daily data; full results + findings in `docs/ENGINE_SCOREBOARD_2026-07-17.md`. Verdict: no engine deleted (each wins somewhere; engines are also paid API products), but engine×symbol pairs differ wildly — nobody earned GME/AMC/MSTR. Execution-side cut mechanism: `IAM_SYMBOL_ALLOWLIST` (entries only, exits never blocked, empty default = unchanged). Recommended value `SPY,IWM,QQQ,NVDA,HOOD` — **awaiting Timothy's sign-off, not applied**. Options-flow engines (gamma/MMLE/0DTE/whale) are unmeasurable without recorded flow history — start recording via `performance_tracker.py` and re-score in 60–90 days.

## SML-DRUCK (Druckenmiller Liquidity Breakout) — code-audited, wired to paper trading; NOT yet profitability-tested (2026-07-20)

**Owner is anxious to get this live — read this whole section before touching any DRUCK env var.** "Live" here means two separate things that must not be conflated: (1) the signal now reaches the real paper-mode executor out of the box, same as IMO/ORB, which is DONE; (2) whether the strategy actually makes money, which is UNMEASURED — no sandbox in this account has ever had real market-data network access to run a real backtest (confirmed again 2026-07-20: `api.tradier.com`/`api.polygon.io` both return `403` on the CONNECT tunnel from this sandbox). Fabricating backtest numbers to satisfy urgency would violate this repo's own Prime Directive — refused, same as every prior attempt this project.

- `indicators/SML_Druckenmiller_Liquidity_Breakout_v6.pine` — reviewed line-by-line 2026-07-20, no bugs found. `druck_engine.py` is the single Python implementation of the same math (Pine is a visual of it, same convention as `imo_engine.py`/`orb_engine.py`) — one real bug caught and fixed during the port (breakout crossover was using a one-bar-lag approximation instead of the true two-bar-lookback `ta.crossover` semantics Pine actually uses), documented in the module docstring rather than silently corrected.
- **New 2026-07-20 — wired to live paper execution, matching the ORB/IMO pattern exactly:**
  - `druck_engine.analyze(symbol, bars, p)` — on-demand single-symbol wrapper (mirrors `orb_engine.analyze()`), used by both the new blueprint and scanner below.
  - `druck_scanner.py` — background Python loop (started in `core/app.py` beside `imo_scanner`/`orb_scanner`), pulls real bars via DataManager (`DRUCK_TIMEFRAME=15MIN` default, pairing the Pine script's default 2H HTF filter), routes fresh BUY/SELL signals to `iam_executor.execute_async()` tagged `system="SML_DRUCK"`. Per-bar dedup prevents re-firing the same signal every scan pass. Needs Polygon/Alpaca for intraday bars (Tradier is daily-only) — idles honestly and logs why on a Tradier-only deployment, exactly like ORB.
  - `core/api/druck_bp.py`, registered at `/api/druck` — `GET /api/druck/status` (scanner state) and `GET /api/druck/<symbol>` (on-demand analysis, 503 without intraday data).
  - Env vars (all optional, sensible defaults): `DRUCK_SCAN_ENABLED`, `DRUCK_SCAN_INTERVAL` (300s), `DRUCK_SCAN_SYMBOLS`, `DRUCK_SCAN_TOP_N` (10), `DRUCK_TIMEFRAME` (15MIN), `DRUCK_BARS_LIMIT` (500 — DRUCK's `atr_pctile_len=100` default needs real history, larger than ORB's window).
  - **This does NOT flip any live-trading switch.** DRUCK signals flow through the exact same `iam_executor` gates as every other system — `IAM_PAPER_MODE=true` is still the default, so DRUCK trades on paper out of the box, same as IMO. Nobody has set `IAM_PRIMARY_SYSTEM=SML_DRUCK`, so it doesn't block other systems either. Going actually-live still requires the same explicit two-flag decision as every other engine (`IAM_PAPER_MODE=false` + `IAM_AUTO_TRADING=true`) — do not flip those for Timothy.
- `tests/backtest_druck.py` — real backtest harness (position state machine: ATR stop, R:R target, trailing stop, capped pyramids), **could not be run this session** — same network restriction as above. `tests/test_druck_engine_smoke.py` (code-correctness only) and `tests/test_druck_scanner_wiring.py` (new 2026-07-20 — analyze() shape, scanner dedup, blueprint registration, all against real production code with only the data provider mocked) both pass.
- **What "audited" actually covers as of this entry:** Pine↔Python math parity, the crossover bug fix, the live-wiring path (scanner → executor → paper fill), and dedup correctness. What it does NOT cover: whether the strategy wins. The moment real market-data access exists (a machine with Tradier/Polygon reachable, or Render itself once deployed), run `tests/backtest_druck.py` for real numbers before treating this as anything more than "correctly wired," same bar every other engine here had to clear (see ORB's backtest verdict above — code-correct is not the same as profitable).

"Trade the Delta. Catch the Explosion." Full product spec: `docs/DELTAFORGE.md`. **Non-custodial by design** — the API returns signals and order *payloads* only; execution happens on the customer's machine with their own broker keys (BYOK). No code in this product ever holds a broker credential or places an order server-side.

- `core/api/deltaforge_bp.py`, registered at `/api/deltaforge` — server-side twin of the Pine flagship: `GET /signal/<symbol>` runs the v2.1 engine on real Tradier 15-min bars (503 without `TRADIER_API_KEY`), picks the 0.32–0.40Δ contract via the Delta Explosion Scanner below, and (elite tier) returns ready-to-fill Tradier/Robinhood order payloads with `quantity: null` (sizing is client-side — server never knows account equity). Signals broadcast as `DELTAFORGE_SIGNAL` on the SSE stream. 60s signal cache.
- Tiers: scout (free, no key) / operator ($49) / elite ($149). Keys are `df_...` in Redis (`deltaforge:apikey:`), issued by the Stripe webhook at `/api/deltaforge/stripe/webhook` — **Stripe products not yet created**; webhook no-ops until `DELTAFORGE_STRIPE_*` env vars are set (mirrors Trade Desk pattern exactly).
- **Founder access: `DELTAFORGE_OWNER_KEY` env var** — permanent free elite, independent of Stripe/Redis (same owner-bypass pattern as `TRADE_DESK_OWNER_KEY`). Unset by default; Timothy must set it on Render to use it.
- `sdk/deltaforge_client.py` — BYOK execution client: RiskEngine (1.5%/trade, 4% daily halt, 3-loss circuit breaker, cooldowns, kill switch `DELTAFORGE_KILL_SWITCH`), TradierBroker (customer token, sandbox default), optional RobinhoodBroker (robin_stocks, customer logs in themselves). **Paper by default; live needs `paper=False` AND `DELTAFORGE_ARM_LIVE=true`.** Do not arm live for Timothy without a fresh explicit decision (same rule as IAM executor).
- No WebSocket on the Flask/gunicorn stack — SSE (`/api/events`) is the push channel; docs name Ghost Layer as the future WS path. Not an MCP tool yet (4-manifest sync required — future work).

## Delta Explosion Scanner (built 2026-07-18)

Operator directive (Timothy, 2026-07-18): delta .32–.40 contracts are his sweet spot for explosive plays. `core/api/delta_explosion_bp.py`, registered at `/api/delta-explosion` — free endpoint, real Tradier greeks only (fails 503 without `TRADIER_API_KEY`, never estimates a delta).

- `GET /api/delta-explosion/<symbol>?direction=long|short` → contracts with |delta| in 0.32–0.40 (band and 5–45 DTE window overridable via query params), ranked by `explosion_score = (gamma/mid) / (1 + 10*spread_pct)` — convexity per premium dollar, penalized for wide spreads. Dead contracts (no bid, no OI+volume) are excluded. 120s in-memory cache (`_cache`, resets on restart like the rest).
- Companion to the DeltaForge Pine strategies (`indicators/ScriptMaster_DeltaForge_Flagship_v6.pine` v2.1 + `ScriptMaster_DeltaForge_v6.pine` v1.3, PRs #349/#351): DeltaForge fires the underlying signal on TradingView; this endpoint picks the option contract. Pine cannot see option chains, so contract selection deliberately lives server-side. History: v1.1/v1.2/v2.0 of DeltaForge had a mathematically impossible entry gate (breakout + negative 10-bar momentum) — fixed in PR #351; don't resurrect old copies from chat logs.
- Not registered as an MCP tool (would require the 4-manifest sync per Key Conventions) — future work if wanted.

## SML-Vault-Executor — What's Needed When Vault Build Starts

Missing env vars (not yet configured — vault not funded):
- `VAULT_ADDRESS` — deployed vault contract `0x036454...` on Base mainnet
- `EXECUTION_RPC_URL` — Base mainnet RPC endpoint
- `EXECUTION_PRIVATE_KEY` — wallet that signs vault calls

Already configured on that service:
- `SML_EMA_PERIODS`, `SML_DRAWDOWN_STEP`, `SML_PROFIT_TARGET`, `CCXT_EXCHANGE`, `DASHBOARD_USER/PASS`, `MASTER_WALLET_ADDRESS`, `STRIPE_SECRET_KEY`

---

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
|----------|--------|
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
**Vercel (Loom):** `signal-auction-loom` project — `https://signal-auction-loom.vercel.app` (also reachable via legacy `squeeze-os.vercel.app`). Root dir: `pne/loom`.  
**Agent Kiosk backend:** PNE Gateway (Railway) was deleted. Signal Auction Loom now connects directly to Ghost Layer via `wss://ghost-layer.onrender.com/ws/loom`. Ghost Layer translates its `MetricsFrame` events into Loom-compatible `AuctionEvent` format client-side (`pne/loom/src/hooks/useAuction.ts`).

### scriptmasterlabs.com product catalog (what's live vs planned)

The `scriptmasterlabs.com` site lists multiple products. Only these have live backends:
- ✅ Ghost Layer Sovereign — ZK/MEV dashboard (the site itself)
- ✅ SqueezeOS — market intelligence API
- ✅ Ghost Layer — private XRP routing engine
- ✅ 402Proof — x402 payment firewall
- ✅ RLUSD Rails / Xahau Remittance Rails — `sml-rails.onrender.com` (SML-XRPL-FEE-FORGE/rails)
- ✅ XRPL Copy-Trader Engine — `sml-copytrader.onrender.com` (SML-XRPL-FEE-FORGE/copytrader)
- ✅ Memecoin Launchpad — `sml-launchpad.onrender.com` (SML-XRPL-FEE-FORGE/launchpad)
- 🚧 Pulse-Verify™ Notary → 402Proof `/v1/verify` (endpoint exists, site link pending)
- 🚧 Xahau Hooks Intelligence → Ghost Layer's `xahau.go` URITokenMint (endpoint exists, site link pending)

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

## Mobile App (Neural_OS) — `mobile/` — Extended Manifesto

The `mobile/` directory contains a Capacitor Android app (Neural_OS). The same Prime Directive applies with additional rules:

### NEVER do any of the following in `mobile/`:

- **NO hardcoded numbers in HTML/JS that represent real-time data** — no `847`, `42%`, `0.002 ETH/hr`, hardcoded agent names like `Commerce_Strategist_Pro`, or any value that looks like live data but is static.
- **NO fake agent node names** — agent nodes must come from `NOS.Agents.all()` or `agents.json`. If no agents are running, show "No agents running", not invented names.
- **NO hardcoded fee breakdowns** — fee distribution charts must be populated from `NOS.AgentRuntime.getSwarmStats()` or a real API endpoint. Never use fixed percentages.
- **NO hardcoded wallet addresses in displayed UI** — the billing wallet (`BILLING_WALLET`) is for payments only; never show it as a "live node" or "wallet drain".
- **NO placeholder QR codes** — the receive modal must use the real `QRCode` library with the real connected wallet address.
- **NO simulated scan progress** — if a scan is not actually running, show 0% or a "not running" state. Random-increment animations on real-seeming progress bars are prohibited.
- **NO default tier above 'free'** — `Subscription.getTier()` defaults to `'free'`. Owner wallets get `'institutional'` via the `OWNER_WALLETS` array in `config.js`, not localStorage.
- **NO localStorage-only loyalty** — loyalty volume must sync to Supabase (`CloudDB.saveLoyalty`) after each transaction. Local data is optimistic only; server wins on conflict.
- **NO fire-and-forget fee transactions** — protocol fee transfers must be awaited and failures must be logged to `nos:failed-fees` in localStorage for reconciliation.

### Subscription & Access Control Rules:

- Owner wallets: defined in `VITE_OWNER_WALLETS` env var (comma-separated). They receive lifetime institutional access. Add new owner addresses to this env var — never via localStorage.
- Tester wallets: defined in `VITE_TESTER_WALLETS` env var. They can switch tiers freely via the dev panel on `subscription.html`. This panel is only visible to owner/tester wallets.
- Tier verification: `Subscription.markVerified(tier, period)` must be called after every successful server-side payment confirmation. Without it, tiers expire after the subscription window.
- `Subscription.getTier()` is synchronous and must remain synchronous — do not add async logic to it.

### Data Source Rules:

| Data | Source | NOT acceptable |
|------|--------|----------------|
| Agent status | `NOS.Agents.all()` | Hardcoded names/values |
| Protocol fee activity | `NOS.AgentRuntime.getSwarmStats()` | Fixed percentages |
| TX history | `NOS.Wallet.getTransfers()` via Alchemy | Any placeholder rows |
| ETH price | `NOS.Price.getEth()` (60s cache) | Hardcoded `$2000` |
| XRP balance | `NOS.XRPL.getBalance(addr)` | Static strings |
| Loyalty volume | Supabase `neural_os_loyalty` + localStorage | Client-only |
| Subscription tier | Supabase `neural_os_subscriptions` | localStorage alone |
| Market signals | `NOS.SqueezeOS.getHistory()` | Mock signal objects |
| AIXBT signals | `NOS.AIXBT.getSignals()` | Placeholder text |
| Wallet balance | Live from wallet provider | Any cached/stale values |

### If live data is unavailable, show:
- `—` (em dash) for missing numeric values
- `"Awaiting data"` or `"Connect wallet"` for context-dependent data
- `"Unavailable"` for API failures
- Never invent numbers to fill the space.

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
│       ├── mcp_bp.py        # POST /mcp — JSON-RPC 2.0 MCP server (52 tools)
│       ├── premium_bp.py    # /api/council /api/scan /api/options /api/iwm (402-gated)
│       ├── market_scanner.py# /api/market — background scan loop + cache
│       ├── marketplace_bp.py# /api/marketplace — peer signal marketplace
│       ├── futures_bp.py    # /api/futures — signal prediction market
│       ├── settlement_bp.py # /api/settlement — conditional agent escrow contracts
│       ├── hiring_bp.py     # /api/hiring — agent job board
│       ├── grants_bp.py     # /api/grants — Autonomous Grant Agent review queue (zero custody)
│       ├── gap_proposals_bp.py # /api/gap-proposals — Gap Synthesist build-proposal review queue (zero custody, zero auto-deploy)
│       ├── settlement_router_bp.py # /api/settlement-router — multi-agent Base/USDC payment-graph netting hook (zero custody, see below)
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
|-----------|------|--------|
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

Mounted at `/mcp`. Implements JSON-RPC 2.0. **52 tools** total.

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
| `GET /api/grants` or `/api/grants/queue` | Browse Autonomous Grant Agent's discovered/queued opportunities |
| `GET /api/gap-proposals` or `/api/gap-proposals/queue` | Browse Gap Synthesist's drafted build proposals |
| `GET /api/settlement-router/tasks` or `/tasks/<id>` | Browse x402 Settlement Router tasks (multi-agent Base payment netting) |

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
|----------|---------|--------|
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

## Marketing Department (`agent/dept/`) — CEO + specialist agents

Real, Claude-powered agents. No agent in this department fabricates a result — each either does the real work (live HTTP checks, real API reads) or reports a real error. Runs **every 4 hours** via `.github/workflows/marketing-daily.yml` (cron `15 */4 * * *`, 6x/day) — a single job that calls `campaign_director.run()` directly, not a duplicate inline script.

| Role | Module | Real job |
|------|--------|----------|
| **CEO** | `campaign_director.py` | Dispatches work to the 4 specialists below, verifies each one actually produced usable output (not just "didn't crash"), reports every real result to the live activity feed, then synthesizes an executive report and posts it to Slack |
| Directory Ranger | `directory_ranger.py` | Live HTTP checks against 25 real AI/MCP/dev directories; generates ready-to-submit listing copy for unlisted ones. Does **not** auto-submit — a human still has to paste the generated package in |
| Community Scout | `community_scout.py` | Reads real Reddit (12 subreddits) + HackerNews for developer conversations relevant to SML's products |
| Federal Scout | `federal_scout.py` | Uses SML's own x402 federal data endpoints to find real government AI/tech contract opportunities (SAM UEI `G24VZA4RLMK3`) |
| Grant Scout | `grant_scout.py` | Discovers/scores/drafts grant proposals (SBIR/NIH today), queues them at `/api/grants` for manual approval — zero custody, never submits or signs anything. See "Autonomous Grant Agent" section above |
| Gap Synthesist | `gap_synthesist.py` | Reads real gap clusters from the live Semantic Gap Detector (`/api/graph/gaps`), scores build-worthiness, drafts technical specs, queues them at `/api/gap-proposals` for manual approval — zero custody, never writes or deploys code. See "Gap Synthesist" section above |

**Content Factory** (`SML_Portfolio/agent/content_factory.py`) is a separate daily agent (`content-factory.yml`, 06:00 UTC) that generates and commits real SEO pages — it isn't orchestrated by the CEO since it lives in a different repo, but it reports to the same activity feed.

### Live activity feed (`core/api/marketing_activity_bp.py`)

`GET /api/marketing/activity` — public, returns the most recent real agent events (capped 50). This is the **only** legitimate source for any "live agent activity" UI. If you see a hardcoded/looping array of agent action strings anywhere in a frontend (there was one in `SML_Portfolio/agentswarm-seo.html` — removed), that's fake and must be wired to this endpoint instead, never left as a static array.

`POST /api/marketing/activity` requires `X-Marketing-Secret` matching `MARKETING_ACTIVITY_SECRET` — without it the endpoint returns 503. This exists specifically so the feed can't be spammed with fabricated entries; the entire point of this feed is that every line in it is a verifiably real event, not because the data is sensitive.

---

## Deployment — Source of Truth

> ⛔ STOP. Before touching any URL, service name, or deployment config — read this table first.
> The only correct URLs are listed below. Do not guess.

| Service | Platform | Canonical URL | Config |
|---------|----------|---------------|--------|
| SqueezeOS API | **Render** | `https://squeezeos-api.onrender.com` | `render.yaml` |
| Agent Kiosk / PNE backend | **Ghost Layer** | `https://ghost-layer.onrender.com/ws/loom` | deleted Railway service — now routes through Ghost Layer |
| Signal Auction Loom | **Vercel** | `https://signal-auction-loom.vercel.app` | project `signal-auction-loom`, root `pne/loom` |
| Ghost Layer (bridge backend) | **Render** | `https://ghost-layer.onrender.com` | `ghost-layer/render.yaml` |
| Ghost Layer Sovereign (frontend) | **Vercel** | `https://www.scriptmasterlabs.com` | project: `ghost-layer-sovereign` |
| 402Proof | **Render** | `https://four02proof.onrender.com` | separate repo |
| SML Rails (RLUSD Rails) | **Render** | `https://sml-rails.onrender.com` | `SML-XRPL-FEE-FORGE/rails/` |

**SML-XRPL-FEE-FORGE repo** (`github.com/Timwal78/SML-XRPL-FEE-FORGE`, private) — 7 services:

> ⚠️ `tiphawk/` has been **deleted** — X.com API requires paid access. **TipMaster™** was rebuilt for **Farcaster (Neynar free tier)** and lives in a **separate repo** (NOT in SML-XRPL-FEE-FORGE).

| Directory | Product | Deployed URL | Status |
|-----------|---------|-------------|--------|
| `rails/` | RLUSD Rails™ | `https://sml-rails.onrender.com` | ✅ Live on Render |
| *(separate repo)* | **TipMaster™** (Farcaster) | `https://tipmaster.onrender.com` | 🅿️ **Suspended on Render as of 2026-07-04** (owner action). Still also needs: `NEYNAR_API_KEY`, `NEYNAR_WEBHOOK_SECRET`, `NEYNAR_BOT_SIGNER_UUID`, `TIPMASTER_BOT_FID`, `TIPMASTER_XRPL_SEED`, `TIPMASTER_XRPL_ADDRESS`, `TIPMASTER_TREASURY_ADDRESS` before it can go live again. Marked `"status": "suspended"` in `.well-known/agents.json` and `catalog.json`; its two endpoints were removed from `.well-known/x402-registry.json`'s free-endpoints table — restore all three when it's un-suspended and configured. |
| `copytrader/` | XRPL Copy-Trader Engine™ | `https://sml-copytrader.onrender.com` | ⚠️ Deployed with PostgreSQL — needs `COPYTRADER_DB_URL`, `OPERATOR_WALLET_SEED`, `OPERATOR_WALLET_ADDRESS`, `DISCORD_WEBHOOK_COPYTRADER` |
| `launchpad/` | Memecoin Launchpad (Forge)™ | `https://sml-launchpad.onrender.com` | ⚠️ Deployed with PostgreSQL — needs `LAUNCHPAD_DB_URL`, `OPERATOR_WALLET_SEED`, `OPERATOR_WALLET_ADDRESS`, `DISCORD_WEBHOOK_LAUNCHPAD` |
| `x402-gateway/` | x402 Payment Gateway (Go) | `https://forge-gateway-a822.onrender.com` | ⚠️ Go service — needs `MERCHANT_WALLET_ADDRESS`, `ANTHROPIC_API_KEY`, `XRPL_NOTARY_WALLET_ADDRESS`, `XRPL_NOTARY_WALLET_SEED`, `REDIS_URL` |
| `shadow-desk/` | Shadow Desk MCP Server (Go) | `https://shadow-desk.onrender.com` | 🅿️ Manually suspended on Render (2026-07-04). Also still needs `INGEST_SECRET`, `ALPHA_PROVIDER_WALLET`, `PLATFORM_WALLET`, `ADMIN_API_KEY` before it can go live |
| `dashboard/` | Forge Dashboard (React/Vite) | `https://sml-forge-dashboard.onrender.com` | ✅ Static site — `VITE_GATEWAY_URL=https://forge-gateway-a822.onrender.com` |

**echo-forge repo** (`github.com/Timwal78/echo-forge`, public) — historical pattern matching engine (Polygon.io + ML cosine similarity). Dockerized, NOT yet deployed to Render as of May 2026.

**scriptmasterlabs.com products and their actual backends:**
- Ghost Layer Sovereign → Ghost Layer backend (`ghost-layer.onrender.com`) + Vercel frontend
- Xahau Hooks Intelligence → Ghost Layer's `xahau.go` URITokenMint (same service)
- Xahau Remittance Rails → `sml-rails.onrender.com` (SML-XRPL-FEE-FORGE/rails)
- Pulse-Verify™ Notary → 402Proof `/v1/verify` (same service)
- XRPL Copy-Trader Engine → `sml-copytrader.onrender.com` (SML-XRPL-FEE-FORGE/copytrader)
- Memecoin Launchpad → `sml-launchpad.onrender.com` (SML-XRPL-FEE-FORGE/launchpad)

## Ecosystem Services

| Service | Platform | URL | Role |
|---------|----------|-----|------|
| SqueezeOS | Render | `squeezeos-api.onrender.com` | This repo — market intelligence API + MCP server |
| 402Proof | Render | `four02proof.onrender.com` | x402 payment firewall, invoice generation, XRPL payment verification, Agent Credit Bureau |
| Ghost Layer | Render | `ghost-layer.onrender.com` | Dual-chain XRPL+Base toll gateway (Go service, `ghost-layer/`) |
| SML Rails | Render | `sml-rails.onrender.com` | RLUSD Rails — XRP/Xahau remittance (SML-XRPL-FEE-FORGE/rails) |
| SML Copy-Trader | Render | `sml-copytrader.onrender.com` | XRPL whale copy-trading engine (SML-XRPL-FEE-FORGE/copytrader) |
| SML Launchpad | Render | `sml-launchpad.onrender.com` | Memecoin bonding curve launchpad (SML-XRPL-FEE-FORGE/launchpad) |
| Forge x402 Gateway | Render | `forge-gateway-a822.onrender.com` | x402 payment protocol + BYOK LLM proxy (SML-XRPL-FEE-FORGE/x402-gateway) |
| Shadow Desk | Render | `shadow-desk.onrender.com` | 🅿️ **Manually suspended on Render as of 2026-07-04.** MCP signal server + billing (SML-XRPL-FEE-FORGE/shadow-desk) — was never fully configured either (still missing `INGEST_SECRET`, `ALPHA_PROVIDER_WALLET`, `PLATFORM_WALLET`, `ADMIN_API_KEY`, see row above). Removed from `.well-known/institutional.json`'s `payment_rails` and `x402-registry.json`'s payment gateway list — restore both if unsuspended and configured. |
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
- **In-memory stores reset on restart**: `_futures`, `_contracts`, `_listings`, `_jobs`, `_queue` (grants), `_queue` (gap proposals), `_tasks` (settlement router), `_scan_cache`, `_preview_cache`, `_demo_cache`, `_MISSION_LOG`, `signal_history` — all lost on redeploy. This is intentional for MVP; do not add disk persistence without discussion.
- **MCP tool count**: the `_TOOLS` list in `mcp_bp.py` is the source of truth (currently 52 tools). The `_SERVER_INFO` version string is `"5.0.0"`. When adding tools, also sync: (1) the tools array in `.well-known/mcp.json`, (2) `tool_count` in `.well-known/catalog.json`, (3) the `"X MCP tools"` text in `.well-known/server.json` and `llms.txt`. Names must match exactly — historical drift between `signal_preview` (source) and `get_signal_preview` (manifest) caused every agent free-trial to fail with "method not found".
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
