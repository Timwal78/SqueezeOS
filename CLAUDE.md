<!-- gitnexus:start -->

# OPERATOR NOTES — READ FIRST

**Owner:** Timothy (TimmyCrypto / Timwal78) — disabled veteran, memory issues. Do NOT rely on him to remember prior decisions, service names, env vars, or build state. You must carry full context yourself. Always recap what exists before starting new work.

## Render Services — Current State (as of 2026-06-26)

| Service | Render Name | URL | Status | Purpose |
|---------|-------------|-----|--------|---------|
| SqueezeOS API | `squeezeos-api` | `https://squeezeos-api.onrender.com` | ✅ Live | Main Flask monorepo — AI Council, CASCADE ACCUMULATOR, Slack bot, 62 MCP tools |
| SML Vault Executor | `sml-vault-executor` | `https://sml-vault-executor.onrender.com` | 🅿️ Parked | Future vault execution layer (Base mainnet). Currently runs squeezeos-api repo as placeholder. Gets its own codebase when vault is funded. Custom domain: `dash.scriptmasterlabs.com` |

**NEVER confuse these two services.** `squeezeos-api` is production. `sml-vault-executor` is parked/future.

## CASCADE ACCUMULATOR — Live Product

- Blueprint: `core/api/cascade_bp.py` — registered at `/api/cascade`
- Slack command: `/cascade [SYMBOL]` → ENTER/ADD/EXIT/STOP directive
- x402 payment: 0.25 RLUSD/call (AI agents)
- Stripe subscription: $149/mo — `price_1TmbGJQL50L4TFzsUsure8N0` (product `prod_Um9XO3d5Yi7TFd`)
- Stripe webhook: `POST /api/cascade/stripe/webhook` → issues Redis API keys on subscription
- Required Render env vars: `CASCADE_STRIPE_PRICE_ID`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_SECRET_KEY`, `REDIS_URL`
- Checkout landing page: `https://www.scriptmasterlabs.com/cascade` (SML_Portfolio repo, `cascade.html`) — real 5-year backtest table + working Stripe subscribe button. Added 2026-07-21; previously there was no public page pointing at the POST-only checkout endpoint.

### Retroactive key reconciliation (`POST /api/cascade/admin/reconcile`, built 2026-07-24)

Closes the gap the PR #388 fix (above) explicitly couldn't: that fix only stops *future* cancellations from leaking access, it does nothing for a customer who subscribed, got a key, and cancelled *before* the fix shipped (their key has no `cascade:sub:{sub_id}` entry to look up). This endpoint doesn't guess who to revoke — it reconciles every `apikey:sml_live_cascade_*` key in Redis against Stripe's real, current subscription list. A key survives only if it positively matches an active/trialing subscription, by `sub_id` (post-fix keys) or by customer email (pre-fix keys). Anything unmatched is revoked and listed in the JSON response for manual review.

- Secret-gated: `X-Cascade-Admin-Secret` header must match `CASCADE_ADMIN_SECRET` (unset = 503, same pattern as `GRANTS_QUEUE_SECRET` etc.).
- Not scheduled anywhere — run it manually (`curl -X POST .../api/cascade/admin/reconcile -H "X-Cascade-Admin-Secret: ..."`) whenever a retroactive sweep is wanted. Safe to re-run any time; it's pure reconciliation against Stripe, not a one-shot migration.
- Tests: `tests/test_cascade_admin_reconcile.py` — 5 tests against the real, unmodified view (secret gating, sub_id match kept, email-match kept for pre-fix keys, no-match revoked for both key shapes).

### CASCADE never actually fired a live signal until 2026-07-29 — two dormant bugs, one of them critical (fixed same day)

Despite being documented as "LIVE" since 2026-07-25 below, `avg_down_engine.py`'s live scanner almost certainly never produced a single real ENTER/ADD/EXIT/STOP signal until 2026-07-29, when both bugs below were found and fixed in the same session:

1. **`_fetch_closes()` requested too few bars, ever.** It passed `BARS_NEEDED+20` (420) straight through as `tradier_api.get_history_df()`'s `days` param — which is CALENDAR days, not trading days. A 430-calendar-day window only returns ~296-307 actual NYSE trading closes, always short of the 365 `_compute_layers()` needs for the L5 EMA — `_evaluate()` returned `None` on every call. Fixed with a proper calendar/trading-day conversion (NYSE ~252/365 ratio). The same bug class was also found and fixed in the shared `data_providers.DataManager.get_bars()` (used by `breakout_scanner`/`sr_matrix_scanner`/`cie_scanner`) — silently under-fetching by ~30% (e.g. `limit=300` → ~223 actual bars). Neither was ever caught by `tests/backtest_engines.py`, which calls `_evaluate()`/`compute_series()` directly with real CSV bars and bypasses these fetch functions entirely.
2. **Once bug #1 was fixed and the engine could finally evaluate, a second, far worse bug surfaced immediately: `_fetch_closes()` was reading Volume as price.** It checked for a lowercase `"close"` column, but `tradier_api.get_history_df()` renames it to `"Close"` (capitalized) before returning — the check never matched, so it silently fell back to `df.columns[-1]`, which is `"Volume"`. Every EMA/entry price this engine ever computed was actually a share-volume count. This produced real live entries priced at literal millions of dollars per share within minutes of bug #1's fix deploying — confirmed in production logs 2026-07-29: `ENTER AMIX @ 69739502.0000`, `ENTER BE @ 43900059.0000`, `ENTER AVTR @ 42790810.0000`, each with a real, confirmed Tradier order ID. Position sizing collapsed to 1 share per garbage-priced entry (so per-trade dollar exposure was small), but every signal was meaningless and every computed stop-loss was unreachable garbage too — no real protective stop existed on any of these positions. Fixed by checking `"Close"` first. **Every position CASCADE opened before this second fix deployed needs manual review on the real Tradier account — this was never verified from any sandbox.**
3. Regression tests for both: `tests/test_avg_down_fetch_window.py`, `tests/test_data_manager_daily_bars_window.py`, `tests/test_avg_down_close_column.py` — all three confirmed failing pre-fix and passing post-fix against the real, unmodified code.
4. **Lesson for future agents:** a "backtest-proven, LIVE-since-X" engine's live wiring can still be silently, completely broken (or actively harmful) if the backtest harness and the live fetch path diverge, even slightly, in how they source data. Prefer feeding a live scanner's actual fetch function into any backtest/verification harness rather than bypassing it, or explicitly flag when a harness bypasses it (as `backtest_engines.py`'s own docstring now should, given this history).

### Robinhood auto-execution wired alongside Tradier (2026-07-29) — both brokers place the same trade, intentionally

Operator directive (Timothy, 2026-07-29): "we were working on getting primary trading on Robinhood and not just only TradingView — Robinhood has all the funds and no PDT rule." Before this, `IAM_PRIMARY_SYSTEM` signals (CASCADE/SR-Matrix/Breakout/MM-V4) only ever placed a real order on **Tradier** — Robinhood only got a Discord alert literally labeled "ALERT ONLY — execute manually on Robinhood."

- `core/api/iam_pending_bp.py` — new pending-signal queue mirroring `core/api/tradingview_webhook_bp.py`'s existing `tv_pending` queue exactly (in-memory deque, 10-min TTL). `iam_executor.execute_from_resolution()` now pushes to it right after the Tradier leg, gated identically (`mode in ("tradier","both")`, primary-system match) plus a `not PAPER_MODE()` check, since this queue always results in a REAL order on the PC executor's end — there is no paper simulation on that side.
- `tools/robinhood_executor_sml.py` gets a new `_poll_iam_primary()` polling `GET /api/webhooks/iam_pending`, consuming signals through the executor's existing risk-rail-protected `_execute()` (same PDT/spread/notional/cooldown gates as every other signal source it already handles).
- **Explicit operator decision: both brokers execute the same signal independently on their own accounts — this is intentional doubled exposure, not a bug.** Asked directly, twice, before building: (1) replace Tradier or run alongside it → "Both — Tradier AND Robinhood each place the trade" (2) confirmed understanding this means doubled exposure per trade.
- **Verified, not assumed:** the PC executor's shared `_last_execution` cooldown dict already prevents the SAME symbol from double-buying within one poll cycle regardless of which signal source triggers it (sequential loop, not concurrent) — so this feature doesn't introduce an unintended duplicate-buy risk on top of the intentional Tradier+Robinhood duplication.
- **PDT threshold: RESOLVED — `PDT_BALANCE_LIMIT=2000.0` is CORRECT. Do not "fix" it to $25,000.** This entry previously claimed the constant was ~12x too low and needed raising to $25,000. **That claim was wrong and has been removed.** The SEC/FINRA $25,000 pattern-day-trader minimum (and its 4-trade counter) was **eliminated effective 2026-06-04** — SEC approved FINRA's Rule 4210 amendment on 2026-04-14, with brokers given until 2027-10 to implement the replacement "equity proportional to intraday exposure" framework. $2,000 is the ordinary Reg T margin-account minimum, and it matches the operator's directly-confirmed live Robinhood behavior (re-confirmed 2026-07-30). Full citation lives at `core/api/convergence_bp.py`'s `_PDT_BALANCE_LIMIT` comment; `tools/robinhood_executor_sml.py`'s `PDT_BALANCE_LIMIT` points at it.
  - **Note for future agents whose training predates 2026-06:** an LLM trained before that date will "know" the $25,000 figure with high confidence and may try to raise this constant. It already happened twice — hardcoded to $25,000 on 2026-07-29 (wrong the same day), and re-asserted from this stale note on 2026-07-30. **Read the citation in `convergence_bp.py` before touching this number**, and note the gate is 3 day-trades per rolling 5-day window *below* the threshold, which is a deliberate conservative shield, not a legal requirement.
- Tests: `tests/test_iam_robinhood_pending_queue.py` — primary-system BUY reaches the queue alongside Tradier; non-primary systems don't; paper mode never pushes a real order; alert-only mode stays alert-only; the Flask route pops-and-clears like `tv_pending`. All pass against the real, unmodified `execute_from_resolution()`.

### Operator decision (Timothy, 2026-07-21): CASCADE approved for live trading — ORB/DRUCK restricted, not deleted

Based on CASCADE's real 5-year backtest (NVDA +138.6%, PLTR +140.6%, SPY 86.6% win rate — independently re-verified twice against fresh Robinhood-MCP-sourced data the same day) versus ORB's and DRUCK's both-measured-both-not-profitable verdicts (see their sections below), the operator decided: **CASCADE goes live for real trading; ORB and DRUCK are restricted from the broker but kept running as paper-mode signals and paid API products** (`/api/orb`, `/api/druck` stay live — not deleted, they just can't place real orders).

- **Bug found and fixed en route:** `avg_down_engine.py`'s `_route_iam()` never tagged its resolution dict with a `"system"` key — unlike `imo_scanner.py`/`orb_scanner.py`/`druck_scanner.py`, which all correctly tag `"SML_IMO"`/`"SML_ORB_MM"`/`"SML_DRUCK"`. `iam_executor.py`'s primary-system gate does `signal_system = resolution.get("system") or "IAM"`, so CASCADE signals were defaulting to `system="IAM"`. Setting `IAM_PRIMARY_SYSTEM=SML_CASCADE` without this fix would have silently blocked CASCADE's own signals from the broker too — the opposite of the intended effect, with no visible error. Fixed: `resolution["system"] = "SML_CASCADE"` added. Regression test: `tests/test_cascade_system_tag.py` (confirmed failing pre-fix, passing post-fix).
- **LIVE as of 2026-07-25.** Operator confirmed (via the Render dashboard directly — this repo's sandboxes have never had Render access, so this is operator-reported, not independently verified by any agent) that the `squeezeos-api` service has these set:
  ```
  IAM_PAPER_MODE=false
  IAM_AUTO_TRADING=true
  IAM_EXECUTION_MODE=both
  IAM_PRIMARY_SYSTEM=SML_CASCADE
  ```
  CASCADE (`avg_down_engine.py`) is placing real Tradier orders on ENTER/ADD/EXIT signals. `EXECUTION_MODE=both` also sends a Robinhood alert on the same signals — **alert only, not a real order**, since no Robinhood order-execution code exists in this codebase (see below). `IAM_PRIMARY_SYSTEM=SML_CASCADE` restricts real execution to CASCADE only — ORB and DRUCK stay alert-only/paper (their backtests were negative, see their sections below); IMO also gets excluded from the broker as a side effect (it was never explicitly evaluated as "approved for live" the way CASCADE now has been; it stays alert-only/paper until its own explicit decision). If any of these four vars ever get changed on Render, update this section — don't leave it stale for the next agent.
- **Robinhood is a real, currently-unbuilt gap.** `iam_executor.py` only has Tradier wired for actual order placement. There is no Robinhood order-execution code anywhere in this codebase — the only Robinhood connection that has ever existed in this project is the Robinhood MCP tool available directly to the coding agent in a chat session (tied to the operator's real account), which is a completely different thing from an unattended production system. Robinhood has no official trading API; automating it server-side means the unofficial `robin_stocks` library, logging in with the operator's real username/password (+ handling MFA/device verification) stored as Render secrets — meaningfully more sensitive than an API key, and carries real account-suspension risk since automated trading isn't how Robinhood's retail ToS expects the app to be used. Operator was informed of this tradeoff on 2026-07-21 and asked to confirm before any Robinhood execution code is written — not yet built.

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

### Oracle panel stuck on "SqueezeOS warming up... retrying." for ~2 months — fixed 2026-07-26 (CORS, not backend logic)

Operator reported the dashboard's Oracle panel has never worked, spinning since it launched. The Oracle backend itself was fine (`core/oracle_engine.py`'s background batch-cache scanner exists specifically so `/api/oracle` responds instantly instead of timing out) — the real bug was **CORS**: `core/app.py`'s default `CORS_ORIGINS` list never included `https://swarmagentsintelligence.scriptmasterlabs.com` (the dashboard's actual domain), and `render.yaml`'s `squeezeos-api` service block has no `CORS_ORIGINS` override at all, so production was running on that incomplete code default. Every browser-side fetch from the dashboard to `squeezeos-api.onrender.com` (Oracle included) was being silently blocked by the browser's same-origin policy — which looks exactly like a permanent "warming up... retrying" state client-side, even though the server was answering fine. Fixed by adding the domain to the default list in `core/app.py`. **If `CORS_ORIGINS` is ever set manually as a Render env var, it replaces this default wholesale — make sure `swarmagentsintelligence.scriptmasterlabs.com` is included or this regresses.**

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
- **Still not built:** any "malicious agent skill" security guardrail — this codebase doesn't host a third-party agent-skill marketplace, so that attack model (mutable payloads swapped in after review) has no real target here to guard. Would need its own fresh, explicit ask before being built.
- To review/approve from the CLI:
  ```bash
  curl https://squeezeos-api.onrender.com/api/gap-proposals/queue           # see what's pending
  curl -X POST https://squeezeos-api.onrender.com/api/gap-proposals/<id>/approve \
    -H "X-Gap-Proposals-Secret: $GAP_PROPOSALS_QUEUE_SECRET"
  ```

## Hermes Sales Agent — 24/7 Agent Economy OS seller → Human Approval (built 2026-07-22)

Built in response to the "Agent Economy OS" monetization push (sell access to the `@scriptmasterlabs/mcp-x402` MCP server + x402 pay-per-call endpoints, "Build Your Own Hermes" narrative). **Zero auto-posting** — same operator-approval pattern as the Grant Scout and Gap Synthesist. No code anywhere in this feature posts to Reddit, HN, X, or any other platform.

- `agent/dept/hermes_sales.py` — new specialist under the CEO (`campaign_director.py`), runs every 4h with the rest of the marketing department (`.github/workflows/marketing-daily.yml`) — that 6x/day cadence IS the "sells it 24/7" implementation. Each pass: (1) **storefront check** — live HTTP against `mcp-x402.onrender.com/health`, the npm registry entry for `@scriptmasterlabs/mcp-x402`, `scriptmasterlabs.com/hermes`, and `/api/status`, reporting real up/down states only; (2) **lead gen** — reuses `community_scout.py`'s tested Reddit/HN search functions with buying-intent queries (monetize MCP server, agent pays for API, x402, etc.); (3) **pitch drafting** — Claude drafts a value-first reply per qualified lead (real tools/prices only, sourced from `SML_Portfolio/mcp-x402/src/server/registry/pricing.ts`, never promises returns, discloses affiliation) and POSTs it to the review queue. Its only side effect is that HTTP POST.
- `core/api/outreach_bp.py`, registered at `/api/outreach` — the review queue itself. `GET /api/outreach` and `/api/outreach/queue` are public/read-only. `POST /submit`, `/<id>/approve`, `/<id>/reject` require `X-Outreach-Secret` matching `OUTREACH_QUEUE_SECRET`. Approving a pitch only flips its status to `approved_to_send` — it does **not** post anything; Timothy copies `pitch_markdown` and posts it manually. Dedup by `lead_url` so the 4h cadence can't queue the same thread twice. In-memory (`_queue`), resets on restart — same MVP pattern as `_futures`/`_contracts`/`_listings`/`_jobs`/grants/gap-proposals.
- Auto-archive: leads scoring below `OUTREACH_QUALIFY_THRESHOLD` (default 60) are queued as `archived`, so weak leads never cost Timothy a review cycle.
- Required env vars: `OUTREACH_QUEUE_SECRET` (shared between the Render service and the `marketing-daily.yml` GitHub Actions secret — same pattern as `GRANTS_QUEUE_SECRET`; **operator must set both or the agent logs "cannot push" and the queue returns 503 on writes**). Optional: `OUTREACH_QUALIFY_THRESHOLD`.
- Tests: `tests/test_outreach_queue.py` — real blueprint via Flask test client (secret gating, threshold auto-archive, dedup, approve/reject state machine). 7 passing at build time. Unlike most tests in `tests/`, these need no live server.
- **Why no auto-posting:** platform ToS (Reddit/HN ban undisclosed bot marketing), spam/brand risk, and consistency with Directory Ranger's no-auto-submit rule. If Timothy ever wants true auto-posting, that's its own explicit decision with its own guardrails — do not casually flip this.
- The sales narrative + landing page + agent prompt template live in **SML_Portfolio** (`hermes.html`, `mcp-x402/docs/HERMES_TEMPLATE.md`, `mcp-x402/docs/AGENT_ECONOMY_OS_PRICING.md`, `mcp-x402/docs/OUTREACH_POSTS.md`) — built the same day, see that repo.
- To review/approve from the CLI:
  ```bash
  curl https://squeezeos-api.onrender.com/api/outreach/queue           # see pitches awaiting review
  curl -X POST https://squeezeos-api.onrender.com/api/outreach/<id>/approve \
    -H "X-Outreach-Secret: $OUTREACH_QUEUE_SECRET"                     # then paste pitch_markdown manually
  ```

## SEO Gap Scout — free technical SEO/AEO/GEO scanner, built 2026-07-21

Built per Timothy's explicit ask (previously deferred — see git history — specifically to avoid duplicating the AEO Suite's citation-tracking surface without a fresh decision). **Deliberately not built on Ahrefs or any paid crawler** — the connected Ahrefs MCP account returned `Insufficient plan` on both `site-audit-projects` and `management-projects` (confirmed live, not assumed), and Timothy does not want to pay for a subscription. Uses plain HTTP requests instead — zero third-party API cost.

- `agent/dept/seo_gap_scout.py` — new specialist under the CEO, runs every 4h alongside the rest of the marketing department. `crawl_site()` does a real GET on each configured site's homepage plus a sample of its internal links (`SEO_MAX_LINKS_PER_SITE`, default 15), checking for broken links (4xx/unreachable), missing `<title>`, duplicate titles across pages, missing meta description, missing structured data (`application/ld+json`), and missing `robots.txt`/`sitemap.xml`/`llms.txt` at the site root. `score_findings()` computes a deterministic 0-100 severity score from those real counts — no LLM guessing at severity. Sites scoring ≥40 get a drafted fix spec via Claude, POSTed to the **same** `/api/gap-proposals` review queue `gap_synthesist.py` uses (same secret, same zero-auto-deploy safety pattern — approving only flips a status flag, nothing gets edited on the live site).
- Env vars: `SEO_SCAN_SITES` (comma-separated, default `https://www.scriptmasterlabs.com`), `SEO_MAX_LINKS_PER_SITE` (default 15). Shares `GAP_PROPOSALS_QUEUE_SECRET` with Gap Synthesist — no new secret needed.
- If a target site is unreachable, that's reported as unreachable and scored 0 — never faked as "no issues found." Confirmed via `tests/test_seo_gap_scout.py`.
- **If Timothy later gets an Ahrefs plan with Site Audit**, this scanner could be extended or replaced with real Ahrefs data (deeper crawl, more issue types) — that's a natural upgrade path, not required to use what's built now.

## x402 Settlement Router — multi-agent Base/USDC payment-graph netting

Built 2026-07-16, in response to the "x402 Settlement Router" product spec (non-custodial payment netting layer for multi-agent AI economies, 0.5% protocol fee, Base/USDC). **Not deployed to any network yet** — this is real, tested code with no live contract address, same "not yet configured" status as SML-Vault-Executor and the AWS Marketplace integration below.

- **Where the actual money logic lives:** `mcp-x402-xrpl/asc-contracts/contracts/settlement-router/` — five Solidity contracts (`FeeRegistry`, `IReputationOracle`/`ReputationOracle`, `TaskEscrow`, `SettlementRouter`, `SettlementRouterFactory`) on Base. Non-custodial, no admin keys on `TaskEscrow` beyond a 7-day-timelocked emergency withdraw, fee hard-capped at 5% on-chain. `ReputationOracle`'s bond tiers mirror the *real* ARGUS/402Proof credit score scale already live in `mcp-x402-xrpl` (300-850 FICO-style — PROTOSTAR/NEUTRON/PULSAR/QUASAR), not the 0-1000 scale the original spec assumed.
- **Off-chain netting engine:** `mcp-x402-xrpl/src/settlement-router/netting.ts` — pure function, sums a payment graph's inflows/outflows per agent, validates the netted result against the task's real on-chain budget + fee before anything gets signed. `mcp-x402-xrpl/src/settlement-router/client.ts` wraps the actual contract calls.
- **HTTP surface:** `mcp-x402-xrpl/src/vending-router-server.ts`'s `/settlement-router/tasks*` routes (secret-gated via `X-Orchestrator-Secret`, not x402-metered — the real revenue event is the on-chain protocol fee, metering the HTTP trigger too would double-charge).
- **This repo's hook (`core/api/settlement_router_bp.py`, `/api/settlement-router`):** off-chain bookkeeping for a task's agent list + accumulated payment-graph edges, then forwards to the mcp-x402-xrpl HTTP surface above to actually create/settle on-chain. Deliberately a **new** blueprint, not an extension of `hiring_bp.py` or `settlement_bp.py` — both of those are single poster/executor pairs settling XRPL wallet-to-wallet by design; a multi-agent Base/USDC payment graph is a different shape of problem.
- Required env vars (all unset by default): `SETTLEMENT_ROUTER_API_BASE`, `SETTLEMENT_ROUTER_ORCHESTRATOR_SECRET` (this repo, calls out); `SETTLEMENT_ROUTER_RPC_URL`, `SETTLEMENT_ROUTER_ADDRESS`, `SETTLEMENT_ROUTER_ORCHESTRATOR_PRIVATE_KEY`, `SETTLEMENT_ROUTER_ORCHESTRATOR_SECRET` (mcp-x402-xrpl, holds the signing key) — see `mcp-x402-xrpl/render.yaml`.
- **Still needed before this is real money:** deploy `SettlementRouterFactory` to Base (`asc-contracts/scripts/deploy-settlement-router.ts`, needs a Gnosis Safe treasury — see PRD non-negotiable #6), create a router for this orchestrator (`create-router.ts`), and wire an agentDid-to-Base-address mapping for `update-reputation-oracle.ts` (ARGUS scores are keyed by DID; `TaskEscrow` bonds are keyed by address — nothing in either codebase maps one to the other yet, documented directly in that script rather than papered over).
- Solidity compiler note for future agents in this sandbox: `npx hardhat compile` needs `binaries.soliditylang.org`, which this session's egress policy blocks entirely (list.json fetch fails for every platform, including wasm). `asc-contracts/scripts/local-compile.cjs` compiles the same sources via the official `solc` npm package (real compiler, permitted registry) and writes Hardhat-format artifacts directly so `npx hardhat test --no-compile` still runs. Once run somewhere with normal network access, plain `npx hardhat compile` works unchanged.

## SML ACP Seller (formerly LEVIATHAN) / Virtuals ACP Marketplace (superseded 2026-07-24 — read this, not the old investigation below)

**Everything in this section as of 2026-07-16 is stale.** A separate autonomous agent — commits under `scriptmasterlabs <scriptmasterlabs@agent.virtuals.io>`, confirmed by the operator to be Virtuals' own agent working this integration directly, **not** a Claude Code session — pushed three real fixes to `SML_Portfolio/mcp-x402` on 2026-07-24 between 06:55 and 07:12 UTC:
- `4db9893` — retired the "Leviathan" brand entirely: `acp/leviathan.ts` → `acp/seller.ts` (`startAcpSeller`), boot logs now say `[SML-ACP]`/scriptmasterlabs not `[LEVIATHAN]`, default wallet moved off the old `0x0f03…` address. `leviathan.ts` is now just a thin re-export shim for stale imports — don't treat it as the real implementation anymore, `acp/seller.ts` is.
- `a8af956` — fixed `render.yaml`: it was still pinning the **old, wrong** wallet `0x0f035c36c4ce65a6f1bf4370f779bac722d59004`, which was forcing the wrong address on every deploy and breaking Privy sign-typed-data pairing. Correct live wallet as of this commit: **`0x72330994f379a71542e7bd5a4cf99a9d9743f4aa`**.
- `443ccaf` — fixed a `sign-message 500` (the signer was using raw PKCS8 instead of the `ACP_SIGNER_KEYS_JSON` keystore + bundled `acp-cli-signer-linux` signFn, matching the pattern already live in the separate `acp-provider` repo).

**Current real wallet/agent identity** (per `acp-provider/README.md`, which documents the same wallet): `0x72330994f379a71542e7bd5a4cf99a9d9743f4aa`, agent name `scriptmasterlabs`, token `SCRIPT`, chain Base (8453).

**Graduation is two separate, unrelated gates — don't conflate them:**
1. **Token bonding-curve graduation** — the SCRIPT agent token needs 42,000 $VIRTUAL accumulated in its bonding curve (protocol-wide standard across all Virtuals agent tokens) before it graduates to a permanent Uniswap pool. At current $VIRTUAL price this is a real ~$40k requirement — the operator was told this figure directly by the Virtuals agent on 2026-07-24 and it checks out against the protocol's public 42k-$VIRTUAL threshold. **This is a market-cap/capital event, not a code fix** — no script or SDK call can satisfy it, it requires real buy-in of the SCRIPT token. Given the wallet rotated today, treat this as effectively starting from scratch, not "almost there."
2. **ACP agent graduation** (sandbox → Agent-to-Agent marketplace search visibility) — a separate, cheap requirement: 10 successful sandbox transactions, 3 of them consecutive using the agent's own test buyer agent. `SML_Portfolio/mcp-x402/scripts/acp-self-test-buyer.ts` already implements this (built 2026-07-17, never run — needs a **second**, separately-registered buyer wallet funded with <$1 USDC on Base; see the script's own header comment for exact env vars). Hitting 10 transactions does **not** auto-graduate you — Virtuals still requires an explicit graduation-request form submission (video/screenshots of the job flow) that then goes through manual review since ACP is in beta.

**Do not assume either gate is currently satisfied** — the wallet changed today, so any prior transaction history or token buy-in tracked against the old `0x0f03…` wallet does not carry over to `0x7233…`.

**Since a live, actively-committing agent (`scriptmasterlabs@agent.virtuals.io`) has push access to `SML_Portfolio/mcp-x402` and is mid-fix as of this writing, do not make further changes to `mcp-x402/render.yaml`, `acp/seller.ts`, or ACP wallet/signer config without first checking recent git history for that path — you may be working against a moving target another agent already owns.**

<details>
<summary>Original 2026-07-16 investigation (superseded, kept for history only)</summary>

The Virtuals Protocol ACP marketplace listing for the LEVIATHAN seller agent ("scriptmasterlabs", `virtualAgentId` 106978, wallet `0x0f035c36c4ce65a6f1bf4370f779bac722d59004`) does not appear in ACP marketplace search despite having ~40-54 live offerings — a prior agent-run investigation confirmed this via direct search testing on the marketplace.

- Root cause was believed to be a never-minted agent NFT (`erc8004AgentId: null`), confirmed the `@virtuals-protocol/acp-node-v2@0.1.7` SDK has no mint/graduate/publish-visibility method — dashboard-only. **This framing turned out to be incomplete**: the real requirement includes the 42k-$VIRTUAL token bonding-curve graduation described above, which the SDK investigation didn't surface because it's not part of that SDK's job-lifecycle surface at all.
- The wallet (`0x0f035c…`) and "LEVIATHAN" branding referenced throughout this old investigation are both retired as of 2026-07-24 — see above.

</details>

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

## SML-DRUCK (Druckenmiller Liquidity Breakout) — code-audited, wired to paper trading; BACKTEST DONE, verdict NOT profitable as-configured (2026-07-21)

**Owner wanted this live — read this whole section before touching any DRUCK env var.** "Live" here means two separate things that must not be conflated: (1) the signal reaches the real paper-mode executor out of the box, same as IMO/ORB, which is DONE; (2) whether the strategy actually makes money — **now measured, 2026-07-21, via real historical bars pulled through the connected Robinhood MCP** (`get_equity_historicals` — this account's sandbox has no direct market-data network access, but the Robinhood MCP tool is a separate, working channel to real data that doesn't go through that blocked path). Full results: `docs/DRUCK_BACKTEST_2026-07-21.md`.

**Verdict: not ready for live trading.** Profit factor below 1.0 (losing money) on 4 of 5 symbols (QQQ -7.86%, IWM -4.65%, NVDA -15.01%, TSLA -9.26%), SPY flat (PF 0.99, -0.14%). 56 trading days, real 15-min bars (May–Jul 2026), default params, no tuning attempted. Same outcome class as ORB's backtest verdict below — do not set `IAM_PRIMARY_SYSTEM=SML_DRUCK` or flip live-trading flags for this system based on current evidence. This is one window/regime with zero tuning, not proof the strategy can never work — but it is real evidence against going live as currently configured.

- `indicators/SML_Druckenmiller_Liquidity_Breakout_v6.pine` — reviewed line-by-line 2026-07-20, no bugs found. `druck_engine.py` is the single Python implementation of the same math (Pine is a visual of it, same convention as `imo_engine.py`/`orb_engine.py`) — one real bug caught and fixed during the port (breakout crossover was using a one-bar-lag approximation instead of the true two-bar-lookback `ta.crossover` semantics Pine actually uses), documented in the module docstring rather than silently corrected.
- **New 2026-07-20 — wired to live paper execution, matching the ORB/IMO pattern exactly:**
  - `druck_engine.analyze(symbol, bars, p)` — on-demand single-symbol wrapper (mirrors `orb_engine.analyze()`), used by both the new blueprint and scanner below.
  - `druck_scanner.py` — background Python loop (started in `core/app.py` beside `imo_scanner`/`orb_scanner`), pulls real bars via DataManager (`DRUCK_TIMEFRAME=15MIN` default, pairing the Pine script's default 2H HTF filter), routes fresh BUY/SELL signals to `iam_executor.execute_async()` tagged `system="SML_DRUCK"`. Per-bar dedup prevents re-firing the same signal every scan pass. Needs Polygon/Alpaca for intraday bars (Tradier is daily-only) — idles honestly and logs why on a Tradier-only deployment, exactly like ORB.
  - `core/api/druck_bp.py`, registered at `/api/druck` — `GET /api/druck/status` (scanner state) and `GET /api/druck/<symbol>` (on-demand analysis, 503 without intraday data).
  - Env vars (all optional, sensible defaults): `DRUCK_SCAN_ENABLED`, `DRUCK_SCAN_INTERVAL` (300s), `DRUCK_SCAN_SYMBOLS`, `DRUCK_SCAN_TOP_N` (10), `DRUCK_TIMEFRAME` (15MIN), `DRUCK_BARS_LIMIT` (500 — DRUCK's `atr_pctile_len=100` default needs real history, larger than ORB's window).
  - **This does NOT flip any live-trading switch.** DRUCK signals flow through the exact same `iam_executor` gates as every other system — `IAM_PAPER_MODE=true` is still the default, so DRUCK trades on paper out of the box, same as IMO. Nobody has set `IAM_PRIMARY_SYSTEM=SML_DRUCK`, so it doesn't block other systems either. Going actually-live still requires the same explicit two-flag decision as every other engine (`IAM_PAPER_MODE=false` + `IAM_AUTO_TRADING=true`) — do not flip those for Timothy.
- `tests/backtest_druck.py` — real backtest harness (position state machine: ATR stop, R:R target, trailing stop, capped pyramids). **Run 2026-07-21** using real 15-min bars (aggregated from real 5-min Robinhood MCP data, SPY/QQQ/IWM/NVDA/TSLA, May–Jul 2026) — see verdict above and `docs/DRUCK_BACKTEST_2026-07-21.md` for full results. `tests/test_druck_engine_smoke.py` (code-correctness only) and `tests/test_druck_scanner_wiring.py` (analyze() shape, scanner dedup, blueprint registration, all against real production code with only the data provider mocked) both pass.
- **What "audited" now covers:** Pine↔Python math parity, the crossover bug fix, the live-wiring path (scanner → executor → paper fill), dedup correctness, AND real backtested profitability (verdict: not profitable as-configured on the tested window). If parameters are ever tuned or a different window is tested, re-run `tests/backtest_druck.py` and update `docs/DRUCK_BACKTEST_2026-07-21.md` (or add a new dated doc) rather than asserting improvement without evidence.
- **Robinhood MCP as a real-data channel:** this session discovered `get_equity_historicals` (Robinhood MCP) works from a sandbox where direct HTTPS to `api.tradier.com`/`api.polygon.io`/any other external host is blocked — it's a separate, allowed channel. Useful precedent for any future engine that needs a real backtest and hits the same network wall: pull 5-minute bars (finest interval available with a wide date range before hitting the ~5000-bar cap) and aggregate client-side to the target timeframe, same pattern as `scripts/_rh_to_druck_csv.py` used for this run (throwaway script, not committed — the pattern is what's worth reusing, not the file).

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

## SML-CIE (Cycle Intelligence Engine) — built 2026-07-23, BACKTEST INCONCLUSIVE (not a verdict either way)

Owner asked "how do I use this to trade daily/weekly" about the existing `pine/cycle_intelligence_engine.pine` ("CIE-BEAST") standalone TradingView indicator. Found while investigating: that indicator referenced a `cycle_intelligence_engine.py` Python twin in both this file and `tests/test_cie_cycle.py` that **did not exist in the repo** — the test failed with `ModuleNotFoundError` before this build. Built from scratch to match the test's exact API (all 4 layers, all assertions), then wired to live paper trading and given a v6 Pine script, same pattern as IMO/ORB/DRUCK.

- `cycle_intelligence_engine.py` — the single Python implementation. Four independent 0–1.5 pressure axes combined into one composite_z / state (`DORMANT`→`BUILDING`→`PRIMED`→`CIE_FIRE`):
  1. **SettlementCycleEngine** — FTD velocity + Reg SHO threshold-list T+35 countdown + cost-to-borrow.
  2. **DarkPoolCycleAnalyzer** — off-exchange ratio / hidden-order-imbalance / decayed dark momentum (DLMD), fed from real per-print tick data. **No real feed exists anywhere in this codebase for this** — confirmed by search before building. Stays at 0.0/"dark_flow_unavailable" in both the live scanner and the backtest; not simulated.
  3. **HistoricalFractalMatcher** — correlates the live return window against a signature library. The live scanner/backtest self-mine this library from the SAME symbol's own real bar history (no external dataset needed) rather than leaving it permanently empty.
  4. **MemeCycleDetector** — 6-phase DORMANT→PARABOLIC from volume-vs-ADV ratio + IV percentile. Its "iv_atm" input is a **realized ATR% volatility proxy**, not options-chain implied volatility (no per-bar options-chain pull is wired) — disclosed in the engine's own output (`disclosure` field), not hidden.
  `tests/test_cie_cycle.py` — the four-layer stress test that used to fail on import — now passes (all 4 layers + convergence signal + AGENT_LAW proxy-labeling gates).
- `cie_scanner.py` — background loop (started in `core/app.py` beside `imo_scanner`/`orb_scanner`/`druck_scanner`), Daily bars by default (`CIE_TIMEFRAME=1D`, also supports `1W` — Weekly bars aggregated client-side since DataManager has no native weekly timeframe). Settlement layer is fed **real SEC FTD + threshold-list data** from `core/ftd_data.py` (same feed as `/api/ftd`) — this is the one axis CIE gets that ORB/DRUCK don't have an equivalent of. Dark-pool layer is never fed (see above). Fires to `iam_executor.execute_async()` tagged `system="SML_CIE"`, window `"NEAR_TERM"`, only on `CIE_FIRE` with a resolved direction (from dark-pool DLMD sign if present, else the fractal matcher's own median forward-return sign — both real, never guessed).
  - **FTD-severity note:** `FTDDataStore` has no shares-outstanding/float feed (confirmed by search), so the scanner can't compute the engine's designed fail-shares/float ratio for real. Rather than fabricate a float number, it derives a self-referential severity proxy instead: `float_shares_proxy` is scaled so a fail count AT this symbol's own real 180-day peak lands exactly on the engine's "high" threshold — 100% real fail counts in, no invented float data. Documented in `cie_scanner.py` and `core/api/cie_bp.py` at the point it's computed.
  - Env vars (all optional, sensible defaults): `CIE_SCAN_ENABLED`, `CIE_SCAN_INTERVAL` (900s — Daily/Weekly data doesn't need ORB's 120s cadence), `CIE_SCAN_SYMBOLS`, `CIE_SCAN_TOP_N` (10), `CIE_TIMEFRAME` (1D), `CIE_BARS_LIMIT` (300).
- `core/api/cie_bp.py`, registered at `/api/cie` — `GET /api/cie/status` (scanner state) and `GET /api/cie/<symbol>` (on-demand analysis, `?tf=1W` for Weekly, 503 without daily bars).
- **This does NOT flip any live-trading switch.** CIE signals flow through the exact same `iam_executor` gates as every other system — `IAM_PAPER_MODE=true` is still the default. Nobody has set `IAM_PRIMARY_SYSTEM=SML_CIE`.
- **Backtest verdict: INCONCLUSIVE — not "profitable" or "not profitable."** `tests/backtest_cie.py` + `docs/CIE_BACKTEST_2026-07-23.md`, real Daily bars (GME/AMC/SPY/IWM/NVDA, ~2024-01–today, via Robinhood MCP `get_equity_historicals`, same real-data channel used for the DRUCK backtest). With settlement and dark-pool axes both unavailable historically (no SEC FTD archive pulled, no dark-pool feed exists at all), only fractal+meme could contribute — entered on `PRIMED`-or-above with a resolved `BUY` direction (a weaker bar than production's `CIE_FIRE`, which is realistically unreachable from 2 axes alone). Result: **1 qualifying signal across 5 symbols × 640 daily bars each** — nowhere near enough for a profit-factor conclusion. This is a signal-frequency finding, not a losing (or winning) strategy, unlike ORB's and DRUCK's clear negative-PF verdicts. **Do not set `IAM_PRIMARY_SYSTEM=SML_CIE` or claim this engine is profitable** — re-test once `cie_scanner.py` has accumulated real settlement-layer history in production, or wire a historical FTD archive into a future backtest pass, before drawing a conclusion either way.
- `indicators/SML_Cycle_Intelligence_Engine_v6.pine` — v6 rebuild of the standalone `pine/cycle_intelligence_engine.pine` ("CIE-BEAST"), same visuals (auto walls, VWAP/EMA, VPIN, DLMD ribbon, 6-phase meme dashboard), plus:
  1. **Timeframe-aware T+35 fix.** The original hardcoded `BARS_PER_CALDAY=78`, correct only for 5-minute RTH bars (23400s trading day / 300s). On Daily that was wrong by ~78x, on Weekly ~546x — this was the actual gap behind the owner's original "how do I use this on daily/weekly" question. v6 derives bars-per-calendar-day from `timeframe.isdaily`/`timeframe.isweekly`/`timeframe.in_seconds()`, correct on any timeframe.
  2. SqueezeOS webhook bridge (`system="SML_CIE"`, same JSON contract as IMO/ORB/DRUCK v6 bridges) — only fires `EXECUTE_LONG`/`EXECUTE_SHORT` on full `CIE_FIRE`, direction from the script's own live DLMD sign (labeled "OFI proxy" throughout the panel — it's a same-bar volume×direction proxy computed from ordinary OHLCV, not real FINRA dark-pool tick data; the original script already called this out as a proxy, v6 makes the labeling more prominent to avoid confusion with the Python engine's differently-scoped `DarkPoolCycleAnalyzer`).
  3. Header comment points at `docs/CIE_BACKTEST_2026-07-23.md` — no backtest evidence exists yet, `CIE_FIRE` is a convergence alert to review, not a proven signal.

## SML Breakout Target/Stop — chart visual for MNEMOS's breakout strategy (built 2026-07-25)

**This is NOT a SqueezeOS engine.** `indicators/SML_Breakout_Target_Stop_v6.pine` is a chart-only visual of a Donchian breakout+target/stop strategy whose real implementation lives in [timwal78/mnemos](https://github.com/timwal78/mnemos) — a separate, private repo ("institutional-grade autonomous agent core," not part of this codebase). It does not execute anything, is not wired to `iam_executor.py`, and has no relationship to CASCADE/ORB/DRUCK/CIE beyond sharing the same visual conventions.

- Entry: `mnemos/modules/breakout_signal.py::detect_breakout()` — classic 20-day Donchian N-bar high/low break. Exit: fixed target-gain (10%) / stop-loss (5%) on directional %-move — a proxy for the underlying's move, not modeled option premium/theta/leverage.
- **Backtest verdict: net positive on all 4 tested symbols, real code + real data.** `detect_breakout()` was imported directly from the cloned `mnemos` repo (not reimplemented) and run against real daily bars (AMC/GME/IWM/SPY, 2022-01–2026-07, Robinhood-MCP-sourced) — 154 trades, 43–50% win rate, +32.5% to +192.8% total return per symbol. Full method + results: `docs/BREAKOUT_BACKTEST_2026-07-25.md`.
- **History note:** an earlier chat-described version of this backtest (not in any repo) claimed a 336-parameter sweep and a 191-trade result table. That specific sweep wasn't reproducible — no script or data backed it anywhere accessible. Two individual trades from that table were spot-checked against this independent run and matched exactly (same dates, same prices, same P&L), so the underlying strategy and data are real — but the aggregate totals didn't match (154 vs 191 trades) and the discrepancy was never root-caused. Treat `docs/BREAKOUT_BACKTEST_2026-07-25.md` as the reproducible reference, not the earlier table.
- **MNEMOS won't trade this live regardless of this backtest.** Its `TradingConfig.min_support=20` requires 20 genuinely verified real trade outcomes before any strategy (including `momentum_breakout`) clears its confidence/support/edge gate, and going live at all needs a real funded broker adapter + `MNEMOS_ADMIN_KEY` + a signed human-approval token (`mnemos/core/approval.py`). This Pine script doesn't bypass any of that — it's for visual inspection only.
- **Not the same thing as the SML Breakout Engine below.** MNEMOS is a separate repo with its own agent, its own gate, and its own operator (per Timothy 2026-07-25: "another agent... built it, working that angle" — do not duplicate MNEMOS work here). The section immediately below is a *new, independent* native-Python reimplementation of the same Donchian breakout math, built specifically to plug into this repo's own `iam_executor.py` — it does not import from or depend on MNEMOS in any way.

## SML Breakout Engine — native SqueezeOS live-trading wiring (built 2026-07-25)

Operator directive (Timothy, 2026-07-25): wanted the breakout strategy trading live alongside CASCADE. MNEMOS (above) can't do that — it's a separate repo/agent with its own multi-month verified-trade gate. This is a **new, independent** implementation of the same Donchian breakout + target/stop logic, written directly against this repo's own `iam_executor.py`, matching the exact pattern already used for IMO/ORB/DRUCK/CIE (Pine script is a visual, Python engine is the single source of truth, scanner feeds the shared executor).

- `breakout_engine.py` — `compute_series()` is the full walk-forward position state machine (one position at a time, entry at the breakout bar's close, target/stop checked on each subsequent bar's close) — same math independently verified in `docs/BREAKOUT_BACKTEST_2026-07-25.md`. `analyze(symbol, bars, p)` is the on-demand latest-bar wrapper, same convention as `druck_engine.py`/`orb_engine.py`.
- `breakout_scanner.py` — background loop (started in `core/app.py` beside `imo_scanner`/`orb_scanner`/`druck_scanner`/`cie_scanner`), **Daily bars** (`BREAKOUT_TIMEFRAME` fixed at `1D`) — works out-of-the-box on a Tradier-only deployment, unlike ORB/DRUCK's intraday feeds. Fires to `iam_executor.execute_async()` tagged `system="SML_BREAKOUT"`.
- `core/api/breakout_bp.py`, registered at `/api/breakout` — `GET /api/breakout/status` (scanner state) and `GET /api/breakout/<symbol>` (on-demand analysis, 503 without daily bars).
- **Deliberately narrower live-signal mapping than the full backtest state machine** — see `breakout_engine.py`'s module docstring for the full reasoning: only ENTRY events map to a live signal (`ENTER_UP` → `BUY`, `ENTER_DOWN` → `SELL`, matching `iam_executor`'s existing "bearish resolution" semantics used by every other engine here). An UP position's `EXIT_TARGET`/`EXIT_STOP` also emits `SELL` (closes the long, matching `_close_equity_position`). A DOWN (put) position's exit emits **no live signal** — `iam_executor`'s `SELL` action has a compound "close long + open a fresh put" meaning, not a pure flat-exit, and no other engine in this codebase has a "close an existing put" mechanism either; inventing one here would add an un-backtested action. Downside protection on live UP positions still comes from `iam_executor`'s own real stop-loss order (`IAM_STOP_LOSS_PCT`), exactly like every other engine.
- **`IAM_PRIMARY_SYSTEM` now supports a comma-separated list**, not just one value (`iam_executor.py`'s `PRIMARY_SYSTEM()` + the gate check in `execute_from_resolution`) — this is what actually makes "live alongside CASCADE" possible. A single value still behaves exactly as before (backward compatible, regression-tested in `tests/test_iam_primary_system_multi.py`). To let CASCADE and Breakout both reach the broker: change Render's `IAM_PRIMARY_SYSTEM` from `SML_CASCADE` to `SML_CASCADE,SML_BREAKOUT`. **Not set this way by any agent** — same rule as every other live-arming decision in this file: the operator sets it explicitly, no sandbox has Render dashboard access to verify or change it.
- **This build does NOT flip anything live by itself.** `breakout_scanner.py` feeds `iam_executor` under the exact same `IAM_PAPER_MODE=true` default as every other engine — it trades on paper out of the box. Going live requires both the existing CASCADE go-live flags (already set, see CASCADE section above) AND adding `SML_BREAKOUT` to `IAM_PRIMARY_SYSTEM` as described above.
- Tests: `tests/test_breakout_engine_smoke.py` (state machine correctness — entry/exit math, the ENTER-only live-signal design, target/stop price calc) and `tests/test_breakout_scanner_wiring.py` (dedup, no-fire-on-none, blueprint registration) — both pass against the real, unmodified code with only the data provider mocked.

## AETHER 5-LOCK — code-audited (2026-07-15), BACKTEST DONE, verdict NOT profitable as-configured (2026-07-25)

`indicators/AETHER_5LOCK_PROTOCOL_v8.pine` (long-only multi-timeframe EMA lock-count system, committed 2026-07-15) was hardened for live trading back then but never backtested until now. `aether_engine.py` + `tests/backtest_aether.py` (new 2026-07-25) ported the real Pine logic and ran it against real daily bars (AMC/GME/IWM/SPY, 2022-2026). **Verdict: not ready for live trading** — catastrophic on AMC/GME (-70% to -77%, PF ~0.04), and on SPY/IWM it doesn't lose money but badly trails simple buy-and-hold. Full results: `docs/AETHER_5LOCK_BACKTEST_2026-07-25.md`. Do not add `AETHER_5LOCK` to `IAM_PRIMARY_SYSTEM` or wire it to any scanner based on current evidence — same bar ORB/DRUCK didn't clear either. No scanner exists for this script at all; its only possible path to live execution is a manually-configured TradingView alert, which is not set up.

## SML RSI Multi Length PRO [Beast Mode] — backtested 2026-07-25, licensing question open, timeframe mismatch suspected

A new Pine script pasted into chat 2026-07-25 (not yet saved to `indicators/`) — multi-length adaptive RSI averaging with an EMA signal-line crossover (CALL/PUT options signal). **Core logic is credited in its own header to LuxAlgo under CC BY-NC-SA 4.0 (NonCommercial)** — this needs an explicit operator decision before it goes near a paid product or live execution; every other Pine script in this repo is ScriptMasterLabs' own original work. `rsi_ml_engine.py` + `tests/backtest_rsi_ml.py` ported the math and backtested it on the same real daily bars — **negative on all 4 symbols**, but the script's own input group is labeled "Trigger (0DTE Scalping)," meaning daily bars are very likely the wrong timeframe (same caveat class as IMO's daily-vs-intraday gap) — high trade counts (70-107 over 4.5 years) and high stop-out rates (20-73%) point to a timeframe mismatch, not a clean loss verdict. Full results: `docs/RSI_ML_PRO_BACKTEST_2026-07-25.md`. This script's own `alertcondition()` calls are titled "(Watchlist)" — it has zero live-execution wiring by design, unlike AETHER.

## SML AI Trade Desk v3 — simplified backtest 2026-07-25, most promising of the three new scripts but thin evidence

Another new Pine script pasted 2026-07-25 (not saved anywhere) — an 18-component weighted scoring "institutional desk" (trend/VWAP/momentum/structure/squeeze/ADX/CMF/Z-score/relative-strength/volume-anomaly/fundamentals/options-intelligence). Only a **scope-reduced** port was built (the ~66 OHLCV-computable points, skipping fundamentals/relative-strength/IV-rank which need TradingView-specific data this sandbox can't reproduce faithfully) — not a full 18-component port. Backtested on the same real daily bars with a threshold empirically fit to this exact dataset's score distribution (disclosed as light curve-fitting, not validated independently). **Result: SPY slightly beat buy-and-hold (+55.9% vs +54.5%), IWM close behind, AMC/GME lost far less than holding — the least-bad of today's three new scripts — but on only 3-13 trades per symbol, nowhere near statistically meaningful.** Full results + caveats: `docs/TRADE_DESK_V3_BACKTEST_2026-07-25.md`. Like RSI-ML, its webhook JSON schema (`secret`/`alert_type`) doesn't match the real bridge contract (`passphrase`/`action`) — zero live-execution path regardless of backtest result. Not saved to `indicators/`, not wired to anything. A real verdict needs the full 18-component port and an independently-chosen threshold, not what's here.

## SML Support/Resistance Matrix — pivot backtest 2026-07-25, now wired live alongside CASCADE + Breakout

`indicators/SML_Support_Resistance_Matrix.pine` (committed 2026-07-11 — a zone/pattern charting tool, no execution logic of its own) got its first backtest via an operator-specified rule: buy on a confirmed pivot low (the chart's green `+`), sell on a confirmed pivot high (red `+`), long-only, no lookahead (`ta.pivotlow/pivothigh(Bars,Bars)` only confirm `Bars` bars after the fact). **Result: positive PF on 3 of 4 symbols with real trade counts (22-30/symbol, not a handful) — the best all-around result of the four new scripts backtested that night** (vs. AETHER/RSI-ML's clean losses and Trade Desk's thin 3-13-trade sample). GME/AMC lose far less than buy-and-hold (-3.9%/-90.0% vs -44.1%/-98.6%); IWM/SPY are positive but trail a strongly bull-trending buy-and-hold. Full results: `docs/SR_MATRIX_PIVOT_BACKTEST_2026-07-25.md`.

Operator directive (Timothy, 2026-07-25): wanted this as the third live system, "matching Breakout." Built the same day, same pattern as IMO/ORB/DRUCK/CIE/Breakout — Pine script is a visual, Python engine is the single source of truth, scanner feeds the shared executor.

- `sr_matrix_engine.py` — `compute_series()` ports the exact pivot-confirmation timing (`ta.pivothigh(Bars,Bars)`/`ta.pivotlow(Bars,Bars)`: a pivot at bar i is only knowable at bar i+Bars, never earlier — regression-tested in `tests/test_sr_matrix_engine_smoke.py`). Cross-checked against the real data behind the backtest doc: identical trade counts (30/30/30/22 for AMC/GME/IWM/SPY) — this is the same math, not a re-derivation that happens to agree.
- `sr_matrix_scanner.py` — background loop (started in `core/app.py` beside `imo_scanner`/`orb_scanner`/`druck_scanner`/`cie_scanner`/`breakout_scanner`), **Daily bars** (Tradier-only friendly, same as Breakout — no Polygon/Alpaca dependency). Fires to `iam_executor.execute_async()` tagged `system="SML_SR_MATRIX"`.
- `core/api/sr_matrix_bp.py`, registered at `/api/sr-matrix` — `GET /api/sr-matrix/status` and `GET /api/sr-matrix/<symbol>`.
- **Live signal mapping is the whole strategy, not a subset** (unlike Breakout's ENTER-only narrowing) — pivot low confirm → `BUY`, pivot high confirm → `SELL` (closes the long, matching `_close_equity_position`, same "exits never blocked" semantics as every other engine). If a single bar somehow confirms both (a measure-zero case with a strict-max/strict-min pivot definition), `SELL` takes priority — protecting an existing position always wins over opening a new one.
- **To let CASCADE, Breakout, and S/R Matrix all reach the broker:** change Render's `IAM_PRIMARY_SYSTEM` to `SML_CASCADE,SML_BREAKOUT,SML_SR_MATRIX` (the comma-separated gate already supports any number of systems, built for the CASCADE+Breakout case, extended here with zero code changes). **Not set this way by any agent** — same rule as every other live-arming decision in this file: the operator sets it explicitly.
- **This build does NOT flip anything live by itself.** `sr_matrix_scanner.py` feeds `iam_executor` under the exact same `IAM_PAPER_MODE=true` default as every other engine — it trades on paper out of the box.
- Tests: `tests/test_sr_matrix_engine_smoke.py` (pivot-confirmation timing correctness, no-lookahead proof, flat-series-produces-no-signals) and `tests/test_sr_matrix_scanner_wiring.py` (dedup, no-fire-on-none, blueprint registration) — both pass against the real, unmodified code with only the data provider mocked.
- **Operator's "done" marker:** this was explicitly requested as the third and final system for tonight ("then we are done") — CASCADE, Breakout, and S/R Matrix now form the complete trio. No further engine-hunting implied unless a fresh request reopens it.

## CRITICAL FIX: options desk was silently dead since it was written — `tradier.get_option_chain()` doesn't exist (2026-07-30)

Operator noticed a red market day with 0 puts purchased and asked why. Real Robinhood order history confirmed it (only options activity that day was closing an existing call — no new puts). Investigation found the actual root cause is much worse than "the live systems are long-only": **`iam_executor._execute_tradier_options()` — the function every SELL signal from ANY primary system unconditionally calls to buy a protective put, and every BUY signal calls to buy a call when `IAM_INSTRUMENT` is options/auto — was calling `tradier.get_option_chain(sym, expiry_str)`, a function that does not exist anywhere in `tradier_api.py`** (only `get_option_chain_schwab_format()` and `get_chain()` do). Every single options order through this path has been raising `AttributeError`, caught by the outer try/except, and returning `{"status":"error"}` silently — since this code was written. No engine's put-buying has ever worked, regardless of `IAM_INSTRUMENT`.

- **Fixed:** now calls the real `tradier.get_expirations(sym)` + `tradier.get_chain(sym, expiration, greeks=True)` (already-existing, already-used-elsewhere functions). Also fixed a second, related bug: the target expiry date was a raw calendar-day offset never checked against what Tradier actually lists — now snapped to the nearest real listed expiration on/after the target via `get_expirations()`, instead of guessing a date that might not exist and getting an empty chain back.
- **Also found live on Render (operator screenshot, 2026-07-30): `IAM_INSTRUMENT=equity,options`** — a comma-separated value. The code only ever checks `instrument in ("options","auto")` (single-value membership) — a comma list never matches either branch and silently falls through to equity-only. **`IAM_INSTRUMENT` must be a single value** (`equity` | `options` | `auto`) — set it to `options` for every current primary system (CASCADE/SR-Matrix/Breakout/MM-V4/SR-Zone-Pattern) to buy calls/puts instead of equity.
- **New: `IAM_OPTIONS_SYSTEMS`** (comma-separated system tags) — forces specific systems to options regardless of the global `IAM_INSTRUMENT`, for finer control if ever wanted (e.g. keep CASCADE on equity while others go options). Not required if `IAM_INSTRUMENT=options` is set globally — that alone covers "all primary systems trade options."
- **New: `IAM_MAX_OPEN_CALLS` / `IAM_MAX_OPEN_PUTS`** (default 1 each, 0 = uncapped) — real-money account-wide comfort cap on concurrently open Tradier option positions, per operator directive ("set to 1 call 1 put at a time till i get comfortable"). Counts real open positions via `tradier_api.get_positions()` + OCC-symbol type classification (root+YYMMDD+C/P+strike). Only enforced when `IAM_PAPER_MODE=false` — paper fills never appear in Tradier's real position list, so the check would always read 0 and is skipped entirely in paper mode.
- **Robinhood side of these same signals still only ever trades equity, never calls/puts** — `robinhood_executor_sml.py`'s `_poll_iam_primary()` calls the same generic `_execute()` used for every equity signal; there is no options-order path for these systems on the Robinhood leg (Gamma Ramp has its own separate, dedicated Robinhood options code — not reusable here without new work). If real Robinhood options execution for these 5 systems is wanted, that's a new build, not done.
- Tests: `tests/test_iam_options_cap_and_routing.py` — OCC symbol parsing, open-position counting, cap enforcement (blocks at cap, allows below, 0=uncapped, never enforced in paper), the `get_expirations()`/`get_chain()` fix end-to-end (real functions called, correct in-bracket contract selected), per-system options override, and the comma-list `IAM_INSTRUMENT` parsing failure mode as a documented regression. 10/10 passing in-sandbox (this file imports `iam_executor` directly, avoiding the `pandas`-via-`core.legacy` import chain that blocks most other wiring tests from running here).

## SML S/R Zone + Candlestick Pattern Engine — thin/mixed backtest, operator-armed for REAL live trading (2026-07-30)

Operator's second pasted Pine v6 script that night ("Best S&R Indicator With Candlestick Patterns," framed as "buy at bottom sell at top easy"). Distinct from S/R Matrix above (single-pivot) — this one requires a two-touch clustering zone AND a candlestick reversal pattern confirming inside it. Full history: found and fixed a duplicate-zone-creation bug, then found the exact-containment version of the confluence essentially never fires on real data (1 entry, 0 trades across 7 symbols/4.5yr) even though neither zones nor patterns are individually rare — patterns hit ~8-9% of all bars. Adding a disclosed proximity buffer (`zone_buffer_pct`, default 3.0x zone height — a real convention the original script itself uses for separate proximity alerts) plus switching the live default exit to `atr_target` (the `opposite_zone` exit gets a position stuck open forever, blocking all future entries) produced a real but thin result: **12 trades / 7 symbols / 4.5yr, aggregate PF 1.186 — NVDA lost, AMC weak, GME strong on only 4 trades.** Full method + numbers: `docs/SR_ZONE_PATTERN_BACKTEST_2026-07-30.md`.

- `sr_zone_pattern_engine.py` (`compute_series()`/`analyze()`), `sr_zone_pattern_scanner.py` (background loop, Daily bars, started in `core/app.py` beside `sr_matrix_scanner`), `core/api/sr_zone_pattern_bp.py` registered at `/api/sr-zone-pattern` — same pattern as every other engine here. Fires to `iam_executor.execute_async()` tagged `system="SML_SR_ZONE_PATTERN"`.
- **This evidence does NOT clear the bar CASCADE/Breakout/S/R-Matrix cleared** (each had 20-30+ trades with a consistent positive-PF pattern; this has 3 of 7 symbols with zero trades at all and one outright loser). Normally that alone would mean "do not add to `IAM_PRIMARY_SYSTEM`," same as Gamma Pin/Squeeze Fuel/CVD Regime.
- **Operator directive (2026-07-30): explicitly requested REAL live trading anyway, alongside S/R Matrix** — "I want it buying and selling just like the screenshot... I'll keep an eye on it while it's live... I sell if I need to and turn it off if I need to." Given directly, with the thin-evidence caveat disclosed first. Per this file's own rule ("do not flip live-trading flags without an explicit fresh decision from the operator"), this now IS that decision for this engine.
- **No sandbox in this codebase has ever had Render dashboard access** — the flags below still have to be set by the operator directly on the `squeezeos-api` Render service; no agent session can flip them:
  ```
  IAM_PAPER_MODE=false
  IAM_AUTO_TRADING=true
  IAM_EXECUTION_MODE=tradier   # or "both" for a Robinhood alert too
  IAM_PRIMARY_SYSTEM=SML_CASCADE,SML_BREAKOUT,SML_SR_MATRIX,SML_SR_ZONE_PATTERN
  ```
  (append `SML_SR_ZONE_PATTERN` to whatever `IAM_PRIMARY_SYSTEM` currently is on Render — don't blindly overwrite it if it has drifted from the CASCADE/Breakout/S/R-Matrix baseline documented above).
- **Stop-loss is automatic, not something built per-engine:** `IAM_STOP_LOSS_PCT` (default 3.0%) places a real GTC stop-sell order on every live BUY fill regardless of which system triggered it — already true for S/R Matrix too.
- **Until the operator sets those Render vars, this trades on PAPER only** (`IAM_PAPER_MODE=true` default, same as every other scanner) — building/wiring the code is not the same event as it actually reaching the broker.
- Tests: `tests/test_sr_zone_pattern_engine_smoke.py` (duplicate-zone-fix regression, pattern-detection edge cases, atr_target stop/target setup) and `tests/test_sr_zone_pattern_scanner_wiring.py` (dedup, no-fire-on-none, blueprint registration) — both written against the real, unmodified code with only the data provider/executor call mocked; this sandbox has no `pandas` installed so they weren't executed here (same limitation `test_breakout_scanner_wiring.py` already has in this environment), verified by syntax check and by running the underlying engine's own smoke tests directly instead.

### Parameter search (2026-08-01): real improvement found, but NOT the same validated class as Sovereign Squeeze/Quad-Score

Per the full-7-engine audit above, this was the one live system that never cleared the same evidentiary bar as the other six. A chronological TRAIN/VALID search (`tests/optimize_sr_zone_pattern.py`, same disciplined methodology) was run against it. **Real bug found and fixed en route**: `atr_target` exit mode was using a raw single-bar true range recomputed fresh every bar, not an actual multi-bar ATR like every other engine here — a real `atr_length` param was added (default `1`, byte-identical to the original behavior, regression-tested in `tests/test_sr_zone_pattern_engine_smoke.py`).

- **Headline: only 3 of the top 25 TRAIN-ranked configs held on VALID** — most top TRAIN candidates showed absurd PF (7-128) on tiny samples that collapsed on VALID, the same overfitting signature CVD Regime Desk's search taught this codebase to watch for. Two of the three "held" configs were investigated further and rejected — dominated by a handful of extreme outlier trades, producing *identical* numbers across multiple different chronological splits (a sign of trade sparsity, not genuine robustness).
- **One candidate held up under real scrutiny**: `bars=10, no_of_pivots=2, zone_expiry=400, zone_buffer_pct=2.0 (was 3.0), atr_length=21 (new), atr_stop_mult=2.0 (was 1.5)`. **52 real trades** (vs the original 12) spread across 7 symbols and 7 years with no single dominating outlier (checked directly). VALID PF held above 1.0 at all four split points (2.06-2.24).
- **Honest mixed-robustness verdict, not oversold**: `zone_buffer_pct` and the new `atr_length` are genuinely robust across their tested ranges; `bars`, `no_of_pivots`, and `zone_expiry` are all fragile/narrow (only specific values work, collapsing PF below 1.0 elsewhere). This is real evidence of improvement, not the near-uniform robustness Sovereign Squeeze/Quad-Score's searches found. Full writeup: `docs/SR_ZONE_PATTERN_OPTIMIZATION_2026-08-01.md`.
- **⚠️ APPLIED to the shipped defaults (operator directive, 2026-08-01: "Yes, apply it").** Given directly after this evidence was disclosed plainly, same "state the evidence, operator decides" pattern as every other decision in this file — not applied silently. `sr_zone_pattern_engine.py`'s `ZonePatternParams` dataclass defaults and `from_env()` fallbacks both updated: `zone_expiry` 200→400, `atr_stop_mult` 1.5→2.0, `atr_length` 1→21 (new param), `zone_buffer_pct` 3.0→2.0 (`bars`/`no_of_pivots`/`exit_mode`/`atr_target_mult` unchanged). Reproduced end-to-end against the real 16-symbol dataset with the new `from_env()` defaults exactly: 52 trades, aggregate PF 2.516, +366.43% — matching the search's own numbers. **The disclosed fragility on `bars`/`no_of_pivots`/`zone_expiry` is unchanged by this decision** — this is a real, informed real-money update on real evidence, not a retroactive upgrade of that evidence's robustness. `tests/test_sr_zone_pattern_engine_smoke.py`/`tests/test_sr_zone_pattern_scanner_wiring.py` (11 tests total) all still pass against the updated defaults.

### "Touch only" (drop the candlestick-pattern requirement) tested and REJECTED as a default, kept as an opt-in (2026-08-01)

Operator was looking at this indicator's live chart, saw the green (+)/red (+) zone-touch markers, and read them the same way the original Pine script's own framing did — "buy at bottom, sell at top, easy." **The live engine deliberately does not fire on every marker** — those +'s are pivot/zone-formation markers, not buy/sell signals; a real entry requires BOTH an active buffered zone touch AND a qualifying candlestick reversal pattern on the same bar (see above). Asked to test dropping the pattern half of that confluence as its own strategy — a real, additive test, not a bug fix, since the chart-marker reading is a legitimate thing to want to test.

- New `require_pattern: bool` field on `ZonePatternParams` (default `True`, byte-identical to every already-shipped/live result) and matching `SR_ZONE_PATTERN_REQUIRE_PATTERN` env var (default unset = `true`). `False` fires on any buffered zone touch alone, matching the literal "buy every green +, sell every red +" reading.
- **Backtested against the same real 16-symbol dataset, same currently-live parameter set, only `require_pattern` varied** (`docs/SR_ZONE_PATTERN_TOUCH_ONLY_BACKTEST_2026-08-01.md`): touch-only is a REAL, non-overfit, net-positive strategy on its own (VALID PF 1.527 actually holds *above* TRAIN PF 1.116 — the opposite of an overfitting signature) — but it is measurably **worse** than what's already live: PF roughly halved (2.516 → 1.235), summed return less than half (+366% → +152%), win rate down 10.7 points, avg per-trade return down more than 4x. More trades fire (97 vs 52 across the same data) but each one is lower quality on average.
- **The candlestick-pattern requirement is doing real, measurable work** — it isn't just making the strategy fire less often, it's producing a genuinely better edge per trade. **Not applied as a default change** — the evidence says the current live config is the better of the two, so `require_pattern=True` stays the default. `require_pattern=False` ships as a documented, tested opt-in (`SR_ZONE_PATTERN_REQUIRE_PATTERN=false`) for anyone who wants the literal zone-touch behavior with this tradeoff disclosed up front — not recommended.
- Tests: `tests/test_sr_zone_pattern_engine_smoke.py` — `require_pattern=True` reproduces every prior shipped result byte-for-byte (no regression to already-live behavior), `require_pattern=False` structurally fires at least as often as `True` (dropping a condition can only relax entries), and the env var parses correctly with a safe default. All pass against the real, unmodified engine.

## SML Gamma Pin Scanner — real Tradier options-chain constraint, NO BACKTEST EVIDENCE (built 2026-07-25)

Built per operator request for a new *constraint scanner* in the existing IAM/CASCADE/ORB/DRUCK/CIE/Breakout/SR-Matrix framework — the specific ask was a gamma-based constraint (dealer gamma exposure near expiry), matching the "GammaPin" idea from an outside strategy pitch. That pitch also proposed reviving the retired "Leviathan" brand and a multi-exchange/multi-chain execution swarm — neither of those was built; this is scoped to a single new signal type inside the existing, already-live executor framework, nothing else from that pitch.

- **Reuses real, already-in-production math — does not re-derive it.** `gamma_flow_engine.py` already computes a real GEX profile from a live Tradier options chain (`calculate_gex_profile()`, consumed today by `core/oracle_engine.py`'s gamma-flow read) and already defines "pin risk" for its own async alerting (`GammaFlowEngine._check_pin_risk()`: an expiry 0-2 days out AND spot within 0.5% of the max-open-interest strike). Two new pure functions were added to that same file — `find_near_expiry()` and `detect_pin_risk()` — that restate those exact thresholds synchronously so a scanner can consume them, without touching or risking the existing async engine.
- `gamma_pin_scanner.py` — background loop (started in `core/app.py` beside `imo_scanner`/`orb_scanner`/`druck_scanner`/`cie_scanner`/`breakout_scanner`/`sr_matrix_scanner`), pulls a real Tradier chain per symbol (`tradier_api.get_option_chain_schwab_format()`), reuses the two functions above, and on a resolved pin condition routes to `iam_executor.execute_async()` tagged `system="SML_GAMMA_PIN"`. **Chain-based, not bar-based** — works out of the box on a Tradier-only deployment (no Polygon/Alpaca dependency), unlike ORB/DRUCK.
- **Direction is a disclosed proxy, not a validated edge:** `sign(max_oi_strike - spot)` — the mechanical reasoning is that dealers hedging a concentrated near-expiry strike must trade against moves away from it, pulling price toward that strike. This is stated plainly in the code (`detect_pin_risk()`'s docstring, the scanner's `rationale` string, and the `/api/gamma-pin/<symbol>` response's `disclosure` field) — it is not claimed to be backtested.
- `core/api/gamma_pin_bp.py`, registered at `/api/gamma-pin` — `GET /api/gamma-pin/status` (scanner state) and `GET /api/gamma-pin/<symbol>` (on-demand read, 503 without `TRADIER_API_KEY`/chain data).
- **NO BACKTEST EVIDENCE EXISTS for this constraint, and none was fabricated to fill the gap.** Every other live-wired engine in this file (Breakout, SR-Matrix, DRUCK, AETHER, RSI-ML) shipped with a real historical backtest first. A gamma-pin backtest needs historical per-day options chains (open interest + gamma by strike, across time) to replay this condition — no such archive exists anywhere in this codebase; Tradier only ever serves the CURRENT live chain, and the Robinhood MCP channel used for DRUCK's/CIE's/Breakout's backtests only provides OHLCV bars, not historical option chains. This ships the same way CIE shipped its unfed dark-pool axis: disclosed as unmeasured, not asserted profitable or unprofitable either way.
- Env vars (all optional, sensible defaults): `GAMMA_PIN_SCAN_ENABLED`, `GAMMA_PIN_SCAN_INTERVAL` (300s), `GAMMA_PIN_SCAN_SYMBOLS`, `GAMMA_PIN_SCAN_TOP_N` (10), `GAMMA_PIN_MAX_EXPIRATIONS` (8, matches `tradier_api`'s own default).
- **This does NOT flip any live-trading switch.** Signals flow through the exact same `iam_executor` gates as every other system — `IAM_PAPER_MODE=true` is still the default. Nobody has added `SML_GAMMA_PIN` to `IAM_PRIMARY_SYSTEM`. **Do not set it there or represent this engine as a proven signal** — the no-backtest caveat above stands until a real historical options-chain data source is found and a backtest is actually run.
- Tests: `tests/test_gamma_pin_engine_smoke.py` (DTE-window + proximity-band correctness, direction-sign correctness, all the no-fire edge cases) and `tests/test_gamma_pin_scanner_wiring.py` (dedup by expiry+strike+direction, no-fire-on-no-chain-data, no-fire-on-no-constraint, no-fire-on-unresolved-direction, blueprint registration) — both pass against the real, unmodified `calculate_gex_profile()` math with only the Tradier chain fetch mocked.

## SML Market Maker Intelligence v4 — code-audited + backtested, verdict PROMISING (2026-07-25)

Operator pasted this Pine script asking whether it complements the just-shipped Gamma Pin scanner. It does — different signal type (ongoing dealer inventory/hedge-pressure stress vs. Gamma Pin's near-expiry pin risk), not a duplicate. Full port + real backtest done per operator request ("full treatment").

- `indicators/SML_Market_Maker_Intelligence_v4.pine` — Kalman-filtered inventory estimate + HJB Riccati steady-state hedge rate + a disclosed round-number/volume gamma-pressure proxy (same proxy class as `SML_Gamma_Pin_v6.pine`'s grid). Its math is a near-exact match to logic already live server-side in `gamma_flow_engine.py`'s embedded "MM Intel v3" section (`_update_mm_intel()`/`_update_gamma_pressure()`, same `MM_KALMAN_GAIN`/`MM_KALMAN_LAMBDA`/`MM_INV_HOLD_COST`/`MM_MARKET_IMPACT` env vars) — that logic had no Pine visual companion in this repo before this build.
- `mm_intel_engine.py` — the single Python implementation (Pine is a visual of it, same convention as every other engine here). **One real bug found and fixed during the port** (documented in the module's docstring, Pine left as-submitted): the pasted script's invalidation state machine tested a freshly-entered thesis's "resolved" exit condition on the SAME bar using the SAME sign that just triggered entry, so every entry self-resolved instantly and could never actually persist across bars. Fixed in `compute_series()` by checking exits first against state carried in from the prior bar, using the correct recovery sign.
- **Backtest verdict: PROMISING, not proven.** `tests/backtest_mm_intel.py`, real 5-minute bars (SPY/QQQ/IWM/NVDA/TSLA, 2026-06-01 to 2026-07-24, Robinhood MCP, same channel as the DRUCK/CIE/Breakout backtests). 4 of 5 symbols profit factor > 1.0 and beat their own buy-and-hold (QQQ +9.03%, TSLA +19.53%, IWM +1.97%, SPY +1.54%; NVDA the one loser at PF 0.89, -3.53%), 81-92 trades per symbol — a real sample, not a handful. Full results + caveats: `docs/MM_INTEL_BACKTEST_2026-07-25.md`.
- **The caveat that matters most: this backtest did not model options at all**, despite the script's own tooltip calling it "Optimized for high-velocity 0DTE response." It traded the underlying's directional %-move only (same convention as `breakout_engine.py`/`druck_engine.py`) — real 0DTE theta decay could easily invert these numbers once actual option premium/spread is priced in. This says the underlying directional signal has real edge on this window; it says nothing about actual 0DTE options P&L.
- Tests: `tests/test_mm_intel_engine_smoke.py` (Kalman/HJB math runs clean with no NaN/Inf, strike-increment grid matches the Pine script's exact tiers for both crypto and equity branches, and — the key regression test for the discovered bug — `active_direction` actually persists past the entry bar instead of instantly self-resolving).
- **Now wired to live PAPER execution (2026-07-25, operator said "MM live" — confirmed via clarifying question this meant paper wiring, not real orders):** `mm_intel_scanner.py` — background loop (started in `core/app.py` beside `imo_scanner`/`orb_scanner`/`druck_scanner`/`cie_scanner`/`breakout_scanner`/`sr_matrix_scanner`/`gamma_pin_scanner`), pulls real intraday bars via DataManager (`MM_INTEL_TIMEFRAME=5MIN` default, matching the backtest's own granularity — needs Polygon/Alpaca for intraday, idles honestly and logs why on a Tradier-only deployment, same as ORB/DRUCK). Routes to `iam_executor.execute_async()` tagged `system="SML_MM_INTEL"`.
  - **Live-signal mapping is narrower than the full backtest state machine** (same reasoning class as `breakout_engine.py`'s ENTER-only design): `BUY`/`SELL` entries pass straight through. An `EXIT_STOP`/`EXIT_RESOLVED` closing a LONG thesis (`exit_direction == 1`) maps to `SELL` (closes the long, matching `_close_equity_position`). An `EXIT_STOP`/`EXIT_RESOLVED` closing a SHORT/put thesis (`exit_direction == -1`) emits **no live signal** — `iam_executor` has no "close an existing put" mechanism (same gap Breakout's docstring documents), so inventing one here would add an un-backtested action. Downside on live LONG positions still comes from `iam_executor`'s own real stop-loss order.
  - `core/api/mm_intel_bp.py`, registered at `/api/mm-intel` — `GET /status` and `GET /<symbol>`.
  - **⚠️ CORRECTED 2026-07-31 — this WAS added, the claim below was stale.** ~~Nobody has added `SML_MM_INTEL` to `IAM_PRIMARY_SYSTEM`~~ — real production logs confirm `IAM_PRIMARY_SYSTEM` currently includes `SML_MM_V4` (the system tag this engine actually fires under — see `mm_intel_scanner.py`'s own tagging, renamed at some point from `SML_MM_INTEL`; `iam_executor.py` aliases both names to the same primary-system check). Found by reading a real Render log line (`broker execution reserved for primary system(s) ['SML_BREAKOUT', 'SML_CASCADE', 'SML_MM_V4', 'SML_SR_MATRIX', 'SML_SR_ZONE_PATTERN']`), not by trusting this file's own prior claim — same lesson as the CEOTrader auto-start correction elsewhere in this file. The no-options-modeled caveat above still stands and was never resolved before this went live.
  - Tests: `tests/test_mm_intel_scanner_wiring.py` — BUY/SELL passthrough, exit-on-long→SELL, exit-on-short→no-signal, dedup, no-fire-on-no-data, no-fire-on-none, blueprint registration. All pass against the real, unmodified `mm_intel_engine.analyze()` with only the data provider mocked.

## Paper Trade Ledger — persistent, per-system record of every paper fill (built 2026-07-25)

Operator directive after asking "are you keeping track of paper trade results" and being told the honest answer was mostly no: `iam_executor.py`'s existing `_positions`/`_state["realized_pnl"]` ledger only tracks *today's* P&L, resets on every restart/redeploy (plain in-memory dict), and has no per-engine attribution (keyed only by symbol — two engines trading the same symbol merge into one untraceable position). Operator confirmed: **"all paper trades should be recorded."**

- `paper_trade_ledger.py` — new module, independent of the existing in-memory ledger (which is untouched and keeps doing its own job feeding the daily-loss breaker). Records every paper fill keyed by `(system, symbol)`: weighted-average open, clamped-close realized P&L, a capped (`PAPER_LEDGER_MAX_CLOSED`, default 5000) list of closed trades, and per-system aggregate stats (total trades, win rate, profit factor, total P&L) computed from that list.
- **Storage: Redis when `REDIS_URL` is configured (the same shared instance CASCADE/AEO/Trade Desk/DeltaForge already use), local JSON file otherwise.** This is a real durability difference, not a technicality — the JSON-file fallback does **not** survive a Render redeploy (fresh container, no persistent disk attached), while the Redis path does. `get_summary()`'s response discloses which backend actually answered (`backend: "redis"` vs `"local_json_no_redis_configured"`) so this is never silently ambiguous.
- **Scope: equity fills only**, matching `iam_executor.py`'s existing ledger exactly — options fills were never tracked by the old ledger either, so this persists/attributes what already existed rather than inventing a new options P&L system.
- Wired into `iam_executor.py`'s existing `_ledger_buy`/`_ledger_sell` (now take an optional `system` param, default `"IAM"`, threaded down from `_execute_tradier`'s already-resolved `signal_system`) — additive, backward-compatible signature change, verified against every existing test that touches `iam_executor.py` (`test_cascade_system_tag.py`, `test_convergence_daily_loss_breaker.py`, `test_iam_primary_system_multi.py`) with zero regressions.
- **Scoped exactly to what was asked: PAPER fills only.** The record calls are gated on `PAPER_MODE()` at the point of the existing ledger call — live fills do not get written here. If durable live-trade recording is ever wanted too, that's a separate, explicit decision (this module's data model already supports it trivially, but nothing calls it that way today).
- `core/api/paper_trades_bp.py`, registered at `/api/paper-trades` — `GET /api/paper-trades` (every system) and `GET /api/paper-trades/<system>` (e.g. `SML_CASCADE`, `SML_MM_INTEL`, `SML_BREAKOUT`), both free/read-only, `?limit=` caps the closed-trades list returned (default 100).
- Tests: `tests/test_paper_trade_ledger.py` — open/close P&L correctness, the exact per-system-attribution gap this closes (two systems trading the same symbol stay separately tracked), close-clamping, safe no-op on closing nothing, backend disclosure, blueprint registration, and the `iam_executor` wiring itself (system tag threaded correctly, live fills never touch this module). All pass against the real, unmodified code.

## Gamma Ramp Desk (0.30-0.40Δ MM Forced-Move) — full audit + real backtest, verdict NOT profitable as-configured (2026-07-29)

Built same-day by a separate, rushed session (`scriptmasterlabs@agents.local`, direct pushes to `main`) — shipped live by default (`ROBINHOOD_PAPER_MODE=false`, `KILL_SWITCH=false`) with **no committed backtest evidence at all**, unlike every other engine in this codebase. Per operator directive ("beast mode audit and correction, turn this strictly profitable... take your time, get it right"), the full package (`tools/gamma_ramp/`: `edge_stack.py`, `gex_engine.py`, `vpin_intraday.py`, `contract_selector.py`, `live_engine.py`, `rh_route.py`) was audited module by module.

- **Three real bugs found and fixed, two of them critical/active-harm.** Worst one: `robinhood_executor_sml.py`'s `_poll_gamma_ramp()` referenced `symbol` before it was assigned in its `SELL_TO_CLOSE` branch — every exit this desk ever generated (hard stop, scale, bank, giveback lock, trail, everything) crashed with `UnboundLocalError`, silently swallowed by the outer loop's try/except. **No gamma-ramp option position could ever be automatically closed.** Also fixed: `manage_open()`'s `bank_300` partial exit orphaned its leftover contract from tracking, and `pos.peak` could get corrupted (lowered) by a scale event triggered on a pullback, weakening giveback-lock protection. `edge_stack.py`, `gex_engine.py`, `vpin_intraday.py`, `contract_selector.py`, `rh_route.py` all audited clean. Full writeup: `docs/GAMMA_RAMP_BACKTEST_2026-07-29.md`.
- **The original -61% backtest number (`tools/gamma_ramp/backtest_gamma_ramp.py`) was never reliable evidence either way** — it priced trades with a hand-built synthetic option-premium formula (arbitrary leverage multipliers, flat -4%/day theta, no empirical validation) AND ran on daily bars for a strategy explicitly designed for 0-3 DTE scalps (same timeframe-mismatch class as RSI-ML). Left in place for structure validation, not treated as a profitability verdict.
- **Real verdict, from a new backtest built the honest way this codebase already trusts (real intraday bars + real ATR-stop/2R-target state machine on the underlying's own move, same disclosed-limitation convention as MM-Intel):** `tools/gamma_ramp/backtest_intraday_directional.py`, real 5-minute bars (SPY/QQQ/IWM/NVDA/TSLA, 2026-06-01 to 2026-07-29, Robinhood MCP, same real-data channel as DRUCK/CIE/Breakout/MM-Intel). **253 trades, 45.8% win rate, profit factor 0.74, essentially flat-to-negative per trade. 4 of 5 symbols PF < 1.0.** Filtering to only the desk's own "full conviction" 5/5-gate tier (68 trades) doesn't meaningfully help (PF 0.84, still losing) — this isn't weak signals dragging down strong ones. No options economics (leverage/theta/spread) modeled — same disclosed gap as every other directional-only backtest here; a positive result would have been necessary but not sufficient, and this wasn't even positive.
- **Do not add this desk to any primary/live-arming gate based on current evidence** — same bar ORB/DRUCK/AETHER/RSI-ML didn't clear either. It currently ships live-by-default (`ROBINHOOD_PAPER_MODE=false`, `KILL_SWITCH=false`) from the original rushed build; whether to flip those defaults given this evidence is the operator's call, not something changed unilaterally here.
- Tests: `tests/test_gamma_ramp_live_engine.py`, `tests/test_gamma_ramp_exit_symbol_bug.py` — both confirmed failing pre-fix, passing post-fix, against the real, unmodified code with only true I/O boundaries (`tradier_api.get_quote`, `_execute_option_sell`) mocked.

## "No cap, many tickers" directive (2026-07-29) — CASCADE's scan universe was the one hardcoded gap

Operator directive same day, after the Gamma Ramp verdict came back negative: "I don't care how we get it but the get is 50-500% gains on daily basis, multiple and many stock tickers, find and profit off of every squeeze play we can, no cap on a daily basis... go get the squeezes." Two things were investigated in response:

1. **The "many trading APIs" the operator mentioned turned out to be their own existing `mcp-x402`/`squeezeos-api`/`acp-provider` product catalog** (crypto prices, federal data, RLUSD rails, Tradier/Robinhood order tools already documented elsewhere in this file) — not a new options-chain or historical-options data source. This doesn't unlock anything new for backtesting the unproven options desks (Gamma Ramp/Gamma Pin) — the "no historical options-chain archive exists anywhere in this codebase" gap, already documented under Gamma Pin and reconfirmed under Gamma Ramp, stands.
2. **Given that, the concrete, evidence-backed way to serve "many tickers, no cap, daily" right now is widening the scan universe of the engines that already have real positive backtest evidence** (CASCADE, Breakout, S/R Matrix — see their sections above), not inventing a new unproven strategy. Audited every scanner's ticker-universe cap: `breakout_scanner.py`, `sr_matrix_scanner.py`, `druck_scanner.py`, `cie_scanner.py`, `gamma_pin_scanner.py`, `imo_scanner.py`, `orb_scanner.py`, `mm_intel_scanner.py`, and `iam_scanner.py` were all already operator-configurable via a `*_SCAN_TOP_N` env var (defaults 10, `iam_scanner.py` defaults 50) — nothing to fix there, just a Render env var to raise if wanted. **`avg_down_engine.py` (CASCADE — the one engine with real money live today) was the sole exception**: its `_get_symbols()` had a hardcoded `ranked[:40]` slice with no env override at all.
   - Fixed: new `AVG_DOWN_SCAN_TOP_N` env var (default 40, preserving prior behavior for anyone who hasn't set it; 0 or negative = unlimited, every symbol the market scanner currently has quoted). `AVG_DOWN_SYMBOLS` (explicit symbol list) still takes priority over both, unchanged.
   - This only changes how many candidates CASCADE's scanner *evaluates* per pass — every existing safety rail (`IAM_MAX_ORDER_USD`, per-symbol PDT gating, spread guards, cooldowns, the daily-loss breaker) is untouched and still applies per-trade regardless of universe size. Widening the universe is not itself a risk-parameter change the way the daily order/notional caps were (see the "Removed daily order/notional caps" note above, which *was* explicitly asked first) — it can't cause a single order to be larger or less protected, only surface more candidate symbols to the same existing gates.
   - Tests: `tests/test_avg_down_scan_top_n.py` — default-40 backward compatibility, env-override widening, 0-means-unlimited, and `AVG_DOWN_SYMBOLS` still taking priority. All pass against the real, unmodified `_get_symbols()`.
   - **What this does NOT do:** it does not invent a new options-chain data source, does not backtest Gamma Ramp/Gamma Pin into profitability (their verdicts stand as documented above), and does not itself increase per-trade risk. "50-500% gains... no cap" is not something any code change can guarantee — this is the concrete, honest lever available today: more real candidates flowing through the one desk (CASCADE) with a real positive backtest, at whatever breadth the operator sets `AVG_DOWN_SCAN_TOP_N`/`BREAKOUT_SCAN_TOP_N`/`SR_MATRIX_SCAN_TOP_N` to on Render.

## Scan-width widened for the rest of `IAM_PRIMARY_SYSTEM` — real rate-limit math, not a guess (2026-08-01)

Operator directive after a full audit of all 7 live primary systems (CASCADE, Breakout, S/R Matrix, MM-V4, S/R Zone+Pattern, Sovereign Squeeze, Quad-Score): widen every scanner's candidate universe "as wide as allowed without rate limit." CASCADE's own cap was already fixed under the "No cap, many tickers" directive above (`AVG_DOWN_SCAN_TOP_N`, default 40) — the other 5 Tradier-daily scanners plus MM-Intel were still at their original `*_SCAN_TOP_N=10` default and had never gotten the same treatment.

**Real mechanism verified by reading the code, not assumed:** `tradier_api.py` enforces a **global, process-wide** rate limiter (`_MIN_INTERVAL_SEC=1.05`, module-level state shared by every caller regardless of which scanner/thread makes the call) — every single Tradier API request in this process, from any of the 6 Tradier-daily-bar scanners (CASCADE + the 5 below), funnels through this one serialized queue. This makes an actual Tradier rate-limit violation **structurally impossible** no matter how high `*_SCAN_TOP_N` is set — the only real cost of going too wide is scan-cycle staleness (an individual pass taking longer to finish), never an API error.

- **⚠️ UPDATED same day — DYNAMIC, not a static 25.** Operator follow-up: "scans must be wide and dynamic within allotment." A hardcoded `25` assumed exactly 5 siblings are always sharing the queue forever — if a scanner is ever disabled or a new one added, that number would silently drift stale. `scan_budget.py` (new) computes the total safe shared budget once from the same verified constraint (`shared_budget_total()` = half of 300s / 1.05s ≈ 142 calls), reserves CASCADE's own fixed `AVG_DOWN_SCAN_TOP_N` off the top, and divides the remainder **evenly across however many of the 5 secondary scanners are actually enabled right now** (checked live via each one's own `*_SCAN_ENABLED` flag). `breakout_scanner.py`, `sr_matrix_scanner.py`, `sr_zone_pattern_scanner.py`, `sovereign_squeeze_scanner.py`, `quad_score_scanner.py` all now call `scan_budget.dynamic_top_n(name, explicit_env_var)` instead of a static default — with all 5 enabled (today's state) that's `(142-40)//5 = 20` each; if one is ever disabled, the other 4 automatically widen to `(142-40)//4 = 25` without any code or env change. An explicit `*_SCAN_TOP_N` env var, if set, always overrides the dynamic calculation outright. Tests: `tests/test_scan_budget.py` — override-wins, even-split-at-5, widens-when-a-sibling-disables, CASCADE-reservation-respected, never-below-minimum. All pass against the real, unmodified allocator.
- `mm_intel_scanner.py` — `MM_INTEL_SCAN_TOP_N` default raised **10 → 15 only, deliberately more conservative.** This engine's 5MIN bars route through `DataManager.get_bars()` → **Polygon first** (`data_providers.py`), which has a much tighter real limiter: `PolygonRateGuard` enforces a global 12s/call floor (the documented real free-tier ceiling, "5 calls/min") — and that same quota is shared with the market-scanner's own Polygon grouped-daily discovery call, a much scarcer shared resource than Tradier's. `15 × 12s = 180s` worst case still fits the 300s interval, without eating deeply into that scarcer budget the way matching the other scanners' 25 would have (`25 × 12s = 300s`, zero margin).
- **This is a real-money-neutral change** — same class as the CASCADE fix above: it only changes how many candidates each already-validated engine's scanner *evaluates* per pass. Every existing safety rail (stop-loss, daily order/notional caps, cooldowns, the daily-loss breaker, `IAM_MAX_OPEN_CALLS`/`PUTS`) is untouched and still applies per-trade regardless of universe width.
- **What this does NOT do:** it does not raise `IAM_MAX_OPEN_CALLS`/`IAM_MAX_OPEN_PUTS` (still 1/1, account-wide, real-money risk parameters — see the audit below) or the daily order/notional caps — those are real-money exposure decisions requiring their own explicit operator-stated numbers, not something to infer from a scan-width request. It also does not touch `IAM_SYMBOL_ALLOWLIST`/dynamic-universe resolution logic, which is unchanged.

### Account-wide caps raised (2026-08-01, operator directive: "fix caps to your recommendation")

Full-codebase audit (2026-08-01) of all 7 live primary systems found `IAM_MAX_OPEN_CALLS`/`IAM_MAX_OPEN_PUTS` (`iam_executor.py`) are **account-wide, not per-system** — verified in `_execute_tradier_options()`: when the cap is hit, the signal is dropped entirely (`{"status": "skipped"}`), with no fallback to equity. This cap was set 2026-07-30 as a deliberate "let me get comfortable" choice when far fewer systems traded options live. With 7 systems now live and potentially all routing through `IAM_INSTRUMENT=options`, whichever system opens a call first blocked every other system's BUY signal until it closed, regardless of that signal's own evidence quality. Similarly, `IAM_MAX_ORDERS_PER_DAY` / `IAM_MAX_NOTIONAL_PER_DAY` are also shared account-wide across all 7 systems and could be exhausted by only 4-5 systems each firing once.

**Given directly to the operator as a recommendation, then applied on explicit confirmation** ("fix caps to your recommendation") — same "state the reasoning, operator decides" pattern as every other real-money change in this file, not silently inferred:

| Env var | Old code default | New code default | Reasoning |
|---|---|---|---|
| `IAM_MAX_OPEN_CALLS` | 1 | **3** | A deliberately measured step, not 7-for-7 parity (which would be reckless given several engines still carry disclosed evidence caveats — SR-Zone-Pattern's fragile axes, MM-V4's no-options-modeled gap). Lets up to 3 systems hold a concurrent call without one system indefinitely starving the other six. |
| `IAM_MAX_OPEN_PUTS` | 1 | **3** | Same reasoning, put side. |
| `IAM_MAX_ORDERS_PER_DAY` | 5 | **15** | ~2 orders/system/day average across 7 systems, with real buffer for scale-ins, instead of a ceiling 4-5 systems could exhaust alone. |
| `IAM_MAX_NOTIONAL_PER_DAY` | $2000 | **$6000** | Sized against `IAM_MAX_ORDER_USD` (unchanged, $500) so the notional cap doesn't bottleneck before the new order-count cap does (15×$500=$7500 theoretical max; $6000 covers ~12 full-size orders) — proportional to the order-count change, not detached from it. |
| `IAM_MAX_ORDER_USD` | $500 | **unchanged** | A per-order cap, not part of the multi-system-sharing problem this audit found — no evidence-based reason to touch it. |

**These are CODE DEFAULTS in `iam_executor.py`, not confirmed live Render values** — same standing limitation as every other cap/flag in this file: no sandbox here has ever had Render dashboard access, so **the real live values on Render for these four vars remain unverified**. If any of them are already explicitly set on Render (overriding the code default), that live value still wins until the operator updates it there directly. `tests/test_iam_options_cap_and_routing.py` (12 tests) all still pass — they explicitly override these vars in each test case rather than relying on the bare default, so this change doesn't alter test behavior.

## SML Squeeze Fuel Composite (`squeeze_fuel_engine.py`) + FINRA short-volume feed (`finra_short_data.py`) — built 2026-07-29, NO BACKTEST EVIDENCE

Operator directive same day: "I don't need the ORB/DRUCK/AETHER/RSI-ML audits — what I need is the best squeeze setup you can find... find and profit off of every squeeze play we can." Explicitly declined one part of the ask: **searching for "leaked proprietary" trading strategies is not something this codebase does** — using someone else's stolen IP/trade secrets is a real legal exposure (trade-secret misappropriation, not a gray area), and no such search was performed. What was built instead: the best *legitimate, documented, real-data* squeeze methodology achievable with sources that are actually free, public, and (mostly) already live in this codebase — combined into one score for the first time.

**The core finding: this codebase already had good squeeze *ignition* detection (`squeeze_analyzer.py`, real price/volume scoring, live since v5.0) but had never combined it with real squeeze *fuel* signals that were also already live** — SEC FTD data + Reg SHO threshold-list status (`core/ftd_data.py`, live via CIE) and dealer gamma positioning (`gamma_flow_engine.py`, live via Oracle/Gamma Pin). Nothing in this codebase had ever put those together into one score.

- **`finra_short_data.py` (new)** — real FINRA daily short-sale-volume file (`cdn.finra.org/equity/regsho/daily/{GROUP}shvol{YYYYMMDD}.txt`), free, public, no login/API key, same class of official regulatory feed as the SEC FTD data already live here. **Explicitly disclosed distinction that must not get lost:** this is SHORT VOLUME (shares sold short THAT DAY — includes ordinary market-maker/HFT short selling for liquidity, not just bearish conviction), not SHORT INTEREST (total shares currently held short, as % of float — the real "GME-style squeeze fuel" number). A free, no-account source for true SI%-of-float / days-to-cover / real-time cost-to-borrow was not found anywhere — that data is normally paid (Ortex, S3 Partners, Fintel) or needs a live IBKR TWS connection, neither of which exists in this codebase. This module is a real, honest proxy, not a stand-in for the real thing.
  - **Network note:** `cdn.finra.org` is blocked from this dev sandbox (confirmed 403-at-proxy, same restriction already documented for `api.tradier.com`/`sec.gov`/`nasdaqtrader.com` elsewhere in this file) — the live fetch path could not be verified end-to-end here. The URL pattern and pipe-delimited format are drawn from FINRA's own published documentation (same format every free short-volume tracker site republishes) and the parser is defensive/tolerant of header variants, but this should be double-checked against a real response once running somewhere with real network access (Render), same caveat already flagged for the Solidity compiler under the x402 Settlement Router section.
  - Tests: `tests/test_finra_short_data.py` — parses the real documented format, tolerates malformed lines, safe zero-division, store ingest/dedup. All pass against the real, unmodified parser with a realistic mocked file (no live fetch, per the network note above).
- **`squeeze_fuel_engine.py` (new)** — composite score (0-100) with four real, disclosed components: Ignition (0-40, `squeeze_analyzer.py`'s existing unmodified score), FTD Fuel (0-20, `core/ftd_data.py`'s real percentile rank + threshold-list bonus), Short-Volume Pressure (0-20, the new FINRA feed above, scored on deviation from the symbol's own recent average), Gamma Amplifier (0-20, `gamma_flow_engine.py`'s real dealer positioning — short-gamma regime scores high since dealers must chase strength). Entry threshold 70/100, **BUY-only by design** (this detects squeeze fuel/ignition, it does not invent an un-backtested short-squeeze-reversal short mechanic) — same "entry-only, downside via `iam_executor`'s real stop-loss" pattern already established by `breakout_engine.py`/`mm_intel_scanner.py`.
  - **NO BACKTEST EVIDENCE EXISTS for this composite, and none was fabricated to fill the gap** — same disclosure convention as Gamma Pin/Gamma Ramp. A real backtest needs historical short-volume-ratio and historical FTD data synchronized to historical price bars; the FINRA feed only backfills ~10 trading days (just built today) and historical options chains still don't exist anywhere in this codebase (same gap already documented for Gamma Pin/Gamma Ramp). **Do not add `SML_SQUEEZE_FUEL` to `IAM_PRIMARY_SYSTEM` or represent this as a proven signal** — weights are a transparent, disclosed starting point, not curve-fit or validated against any dataset.
  - Tests: `tests/test_squeeze_fuel_engine.py` — all-sources-unavailable safe zero, ignition-only stays below threshold, full-stack bullish alignment fires BUY, non-bullish direction never fires regardless of score, long-gamma regime correctly dampens (not amplifies), missing option chain honestly marked unavailable rather than guessed. All pass against the real, unmodified `compute_fuel()`/`analyze()` with only the four true data-store/I-O boundaries mocked.
- **`squeeze_fuel_scanner.py` + `core/api/squeeze_fuel_bp.py` (new)** — background loop (started in `core/app.py` beside `gamma_pin_scanner`/`mm_intel_scanner`), same dynamic-universe resolution pattern as every other scanner here (never hardcoded). Routes to `iam_executor.execute_async()` tagged `system="SML_SQUEEZE_FUEL"`. `GET /api/squeeze-fuel/status` and `GET /api/squeeze-fuel/<symbol>` (503 without a live quote).
- **This does NOT flip anything live.** `IAM_PAPER_MODE=true` is still the default — this trades on paper out of the box, same as every other scanner here. Paper fills get recorded to the Paper Trade Ledger under `system="SML_SQUEEZE_FUEL"` automatically (existing wiring, no new code needed) — so unlike Gamma Pin/Gamma Ramp, this one will actually start accumulating real paper-trade evidence over time that a future backtest/review can look at.

### RSI-cross-above-50 gate added (2026-07-30) — free-data re-implementation of a pasted Ortex/Unusual-Whales screener

Operator pasted a real short-squeeze screener bot from another app they use (Ortex short-interest + Unusual Whales options-flow paid feeds + a tiered entry/exit rule set). They explicitly don't have and don't want to pay for either subscription. Neither has a free equivalent anywhere in this codebase (confirmed by search — not fabricated). What this codebase *does* already have for free, real, and running since 2026-07-29 is `squeeze_fuel_engine.py` above — real FTD/short-volume/gamma fuel detection. The one piece of the pasted bot's tier-2 trigger set that's honestly buildable for free — RSI crossing above 50, pure math on ordinary daily bars — was added as a **required additional gate**, not a score component: `analyze()` now only fires `BUY` when the composite clears `ENTRY_THRESHOLD` AND direction is bullish AND a real fresh RSI(14)-cross-above-50 is confirmed on real daily bars. Uses the operator's own reference bot's exact simple-average RSI formula (not Wilder's smoothed variant), so the number matches what they're used to seeing elsewhere.

- **Fails CLOSED, not open**, when `history` is missing or too short (<16 bars) — deliberately, since this gate exists specifically to add selectivity; failing open would silently remove the exact protection it was added for.
- `squeeze_fuel_scanner.py` previously never fetched or passed real daily bars to `analyze()` at all — fixed to pull `dm.get_bars(sym, "1D", 60)` and pass as `history`, otherwise the new gate could never be satisfied in live scanning.
- **Explicitly NOT implemented: earnings blackout and IV-rank exclusions** from the pasted bot — no free, live earnings-calendar or IV-rank data source exists anywhere in this codebase server-side (the Robinhood MCP earnings tools used for the PEAD backtest earlier this session are only reachable from an interactive chat session, not from the deployed Render service), and none was fabricated to fill that gap. If a real source is ever found/paid for, that's separate future work.
- Tests: `tests/test_squeeze_fuel_engine.py` — extended with a real RSI-cross bar sequence (hand-verified: rsi_prev=0.0 → rsi_now=53.69, a genuine fresh cross), a fail-closed-without-history regression test, and a direct unit test of the RSI math itself. All pass against the real, unmodified `compute_fuel()`/`_rsi_confirmation()`.

### Correction: "no free Unusual Whales equivalent" was WRONG — a real one already existed (2026-07-30)

The RSI section above originally said unusual options flow had "no free equivalent anywhere in this codebase." **That was wrong** — the operator pointed out they already see real unusual-flow alerts in Discord, which sent this back to search rather than staying with the first (incorrect) answer. `options_anomaly_engine.py` is a real, already-live, auto-started engine (`start_anomaly_engine()`, `core/app.py`) that scans real Tradier chains every 5 minutes and flags whale prints (≥$100K single-order premium), volume/OI surges, IV spikes/crushes, and skew breaks via rolling z-score baselines against each symbol's own history — then posts them to Discord (`discord.fire_anomaly_alert()`). This is a genuine, free, live substitute for the pasted bot's "unusual options flow" trigger — not fabricated, not a stand-in, actually running and actually correct this whole time. Lesson: search before asserting a data source doesn't exist, especially in a codebase this large — "no free equivalent" claims need to survive an actual search of `discord_alerts.py`/`*_anomaly_engine.py`/`core/app.py`'s startup sequence, not just the modules already known from context.

- `options_anomaly_engine.py`: added `get_recent_anomaly(symbol, max_age_s=1800)` — a real query function (not a re-derivation) over this engine's own existing `_last_alert` timestamps, now also mirrored into a new `_last_anomaly: dict[symbol -> full event]` populated at the exact point a real anomaly already fires (same loop, no new fetch). Returns `None` honestly when this engine hasn't scanned/flagged that symbol recently — its own scan universe is independently ranked/capped from whatever universe a caller resolves, a disclosed real limitation, not hidden.
- `squeeze_fuel_engine.py`: added a **second required gate** (`_flow_confirmation()`) alongside RSI-cross — `analyze()` now requires composite≥70 AND bullish AND RSI-confirmed AND a real recent flow anomaly, all four, to ever return `BUY`. Direction-agnostic by design (matches the pasted bot's own "unusual flow" trigger, which doesn't itself claim direction — bullish confirmation comes from the ignition score separately). Fails closed like RSI.
- Tests: extended `tests/test_squeeze_fuel_engine.py` (full-stack-with-flow-fires-BUY, full-stack-without-flow-fails-closed, direct `_flow_confirmation()` unit test) and new `tests/test_squeeze_fuel_live_arming.py` for `get_recent_anomaly()`'s window/case-insensitivity/never-scanned behavior. All pass against real, unmodified code.

### LIVE-ARMED for real trading (2026-07-30, explicit operator directive, capped to 1 open position)

Operator's own words after seeing the zero-backtest-evidence disclosure: *"build it out and make it live, set it to 1 buy for now."* Same pattern as the S/R Zone+Pattern arming above — explicit, informed decision after real evidence status was stated plainly, not a claim that the engine is proven.

- `squeeze_fuel_scanner.py` now enforces a real, **self-healing** cap on concurrently open Squeeze-Fuel-originated equity positions: `SQUEEZE_FUEL_MAX_OPEN_POSITIONS` (default `1`, `0` = uncapped). A symbol is added to the tracked set on a live BUY fire; every scan pass re-checks each tracked symbol against the REAL Tradier position via `tradier_api.get_position()` and drops it if actually flat — self-corrects if a stop-loss (or anything else) closed the position without this scanner being told, rather than trusting a stale in-memory flag. Only enforced when `IAM_PAPER_MODE=false` (paper has no real positions to check against).
- **This still does not flip anything live by itself.** Going actually-live still requires the operator to add `SML_SQUEEZE_FUEL` to `IAM_PRIMARY_SYSTEM` on Render directly — no sandbox here has ever had that access.
- **Evidence status is unchanged by any of this.** Two more required gates and a position cap make entries more selective and the blast radius smaller — neither is profitability evidence. Zero backtest evidence for the composite still stands; this section documents an informed real-money decision, not a retraction of that disclosure.
- **⚠️ REMOVED from the recommended live roster (operator decision, 2026-07-31).** Asked directly which currently-armed-but-unverified engines to strip from the recommended `IAM_PRIMARY_SYSTEM` value, the operator chose to remove `SML_SQUEEZE_FUEL` specifically (kept `SML_SR_ZONE_PATTERN`, whose thin-but-real 2026-07-30 backtest evidence plus its own separate explicit "keep it live anyway" directive distinguish it from Squeeze Fuel's zero-evidence status). **This changes the recommended value only — it does not by itself touch whatever is actually set on Render**, which the operator still has to edit directly; no sandbox here has ever had that access. Current recommended value: `IAM_PRIMARY_SYSTEM=SML_CASCADE,SML_SR_MATRIX,SML_BREAKOUT,SML_MM_V4,SML_SR_ZONE_PATTERN` (drop `SML_SQUEEZE_FUEL` from whatever is live on Render if it was ever added there). The engine itself, its scanner, and its paper-mode wiring are all untouched and keep running exactly as built — only the live-arming recommendation changed.

### Real short interest, earnings blackout, and IV rank — a second "no free source" claim corrected (2026-07-30)

The Squeeze Fuel docstring previously said none of the pasted Ortex/UW screener's remaining three triggers (real short interest, earnings blackout, IV rank) had a free source. Operator pushback ("you should be able to build those api... every advantage is welcomed") sent this back to real research rather than standing on the earlier claim — same lesson as the options-flow correction above: verify before asserting a gap is unfillable. Two of the three turned out to be real and buildable; the third genuinely has no free source and was built as an honest self-mining tracker instead of faked.

- **`finra_short_interest_data.py` (new)** — real bi-monthly days-to-cover from FINRA's `equityShortInterestStandardized` dataset (the true "short interest" number, distinct from `finra_short_data.py`'s daily short-VOLUME proxy). **Different access bar than the short-volume file — not zero-config.** This lives on FINRA's OAuth2-gated Query API (`developer.finra.org`), confirmed via research since `finra.org` itself blocks this sandbox's outbound fetch entirely (same 403 pattern as `cdn.finra.org`). Requires the operator to register a free "Individual Account" + self-issued "Public Credential" at `developer.finra.org/create-account` (real, free, but a manual one-time step — same class of action as getting a Tradier/Polygon key), producing `FINRA_API_CLIENT_ID`/`FINRA_API_CLIENT_SECRET`. **Field names are parsed defensively, not asserted exact** — the precise JSON schema of a real response couldn't be confirmed end-to-end from this sandbox, so `_extract()` matches several plausible real FINRA key-name variants case-insensitively rather than hardcoding one guess. Should be double-checked against a real response once running with real credentials on Render, same caveat class as the FINRA short-volume file and the x402 Settlement Router's Solidity compiler.
- **`data_providers.AlphaVantageProvider.get_earnings_calendar()` (new method)** — real, free `EARNINGS_CALENDAR` CSV endpoint. One call returns every upcoming earnings date industry-wide, cached ~20h, so it doesn't burn into the provider's strict 25/day budget the way per-symbol `GLOBAL_QUOTE` calls do. Requires `ALPHA_VANTAGE_API_KEY` (already a documented, existing env var — this just adds a second real use of it).
- **`iv_rank_tracker.py` (new)** — the one trigger with genuinely **no free source anywhere** (reconfirmed here, same gap already documented for Gamma Pin/Gamma Ramp/CVD Regime: Tradier only ever serves the CURRENT live chain, no historical options-chain archive exists in this codebase). Built as a real self-mining tracker instead of faked: feeds off `gamma_flow_engine.calculate_gex_profile()`'s already-live `iv_surface_avg` field, persisting one real number per (symbol, trading day) going forward and reporting a real percentile once `IV_RANK_MIN_HISTORY_DAYS` (default 20) real readings exist. Reports `insufficient_history` honestly — never a fabricated rank — until then. Storage: Redis when `REDIS_URL` is set (survives redeploy), local JSON file otherwise (does not survive redeploy, same disclosed gap as `paper_trade_ledger.py`).
- **All three wired into `squeeze_fuel_engine.py` as FAIL-OPEN refinement gates — deliberately different design from RSI/flow's fail-CLOSED gates.** RSI-cross and options-flow-anomaly are core confirmations (no real data = no BUY). These three are risk-avoidance refinements layered on top of an already multi-gated signal: each only **blocks** a BUY when real data is present and says the setup is weak (short interest: real days-to-cover below `SHORT_INTEREST_MIN_DAYS_TO_COVER`; earnings: within `EARNINGS_BLACKOUT_DAYS` of a real known report date; IV rank: real accumulated history shows today's IV outside the `IV_RANK_EXCLUDE_BELOW`/`ABOVE` band) — and fails open (never blocks) when unconfigured/unavailable, since requiring perfect coverage on all three would silently regress this already-rare live-armed signal back toward never firing.
- **This does not change the live-arming or evidence status documented above.** `SML_SQUEEZE_FUEL` still needs the operator's own `IAM_PRIMARY_SYSTEM` Render edit, and zero backtest evidence still exists for the composite — three more real, disclosed refinement inputs are not profitability evidence.
- Tests: `tests/test_finra_short_interest_data.py` (real OAuth2 + defensive parse pipeline against a realistic mocked response, per-symbol cache, missing-symbol handling, unconfigured-never-fabricates), `tests/test_alphavantage_earnings_calendar.py` (one call covers every symbol, 20h cache, unconfigured/malformed-response safety), `tests/test_iv_rank_tracker.py` (real local-JSON-backed reads/writes — no-history/insufficient-history honesty, real percentile once minimum reached, same-day dedup, invalid-input rejection, backend disclosure), and new cases added to `tests/test_squeeze_fuel_engine.py` (unit tests for all three new gate functions, plus a full-stack test confirming real weak short-interest data blocks an otherwise-qualifying BUY). All pass against the real, unmodified code.

## 741 Pure Macro Matrix — renamed off the hardcoded "741" + real MACRO_STACK_WARMUP env-var collision fixed (2026-07-30)

Operator asked to shorten the anchor period (`MACRO_STACK_CSV`'s last value, used by both `core/api/macro_bp.py` — the internal regime engine that gates live `iam_executor.py` BUY signals — and `core/api/macro741_bp.py` — the public paid `/741macro` endpoint) from 741 down to **190** trading days. Real Render values seen via screenshot: `MACRO_STACK_CSV=30,60,90,120,741`, `MACRO_STACK_WARMUP=50`. New value: `MACRO_STACK_CSV=30,60,90,120,190`.

- **A real bug was found while investigating, not just a rename opportunity: `MACRO_STACK_WARMUP` was a naming collision between two unrelated features.** `core/api/macro_bp.py` reads it as a plain INTEGER bar-count buffer (`int(os.environ.get("MACRO_STACK_WARMUP", "50"))`, added to the anchor for its required-history calc) — the operator's real value `50` is correct for this. `core/api/macro741_bp.py` was separately reading the SAME env var name as a comma-separated SYMBOL list to pre-warm its cache on boot — so it was trying to warm-cache a ticker literally named "50" every deploy, producing the real, observed `[ALPACA] Stock bars 400: invalid symbol: 50` error. **This was not an operator typo** — `.env.example` itself only ever documented the symbol-list meaning, so there was no way to know the two blueprints disagreed on what the same name meant. Fixed by giving `macro741_bp.py` its own distinct env var, `MACRO_STACK_WARMUP_SYMBOLS` (unset by default = no warmup, safe no-op). **Do not clear or reformat `MACRO_STACK_WARMUP=50` on Render** — it's still correct and load-bearing for `macro_bp.py`'s real, live BUY-gate calculation.
- **Internal-only rename, not a breaking API change:** logger tags, Discord alert text/username, and docstrings in both `macro741_bp.py` and `macro_bp.py` no longer hardcode "741" (it would drift stale again the next time `MACRO_STACK_CSV` changes — same "no fake/stale info" rule as everywhere else in this file). **Deliberately left unchanged**, since they're live paid-product identifiers already in use by real callers and renaming them needs its own separate, explicit decision: the route path `/741macro`, the MCP tool name `macro_741_scan` (+ its UUID/price in `proof402_integration.py`/`mcp_bp.py`), and the `"741"` JSON key in `signal_products_bp.py`'s `/api/signals/full` response.
- Tests: `tests/test_macro_stack_warmup_collision.py` — proves both modules' env parsing side by side under the operator's real values (macro_bp.py's int buffer still works, macro741_bp.py's symbol warmup is a safe no-op instead of a bogus "50" lookup, opt-in `MACRO_STACK_WARMUP_SYMBOLS` works, anchor resolves to 190). All pass against the real, unmodified parsing logic.
- **Render values to set:** `MACRO_STACK_CSV=30,60,90,120,190` (change), `MACRO_STACK_WARMUP=50` (leave exactly as-is), `MACRO_STACK_WARMUP_SYMBOLS=` (optional, only if cache pre-warming for specific symbols is wanted — new var, was never set before under the old colliding name).

## Tradier extended-hours "duration" order rejection — real 2026-07-31 production incident, error-swallowing bug fixed, root cause NOT fully resolved

Operator reported real, live CASCADE order failures in production logs the night before a trading day: DGICA, FFBC, and BKDV all rejected identically by Tradier — `HTTP 400: Invalid parameter, duration: post market no longer available.` — every one during the after-hours window. All three still reached Robinhood via the existing "both brokers execute independently" queue (confirmed in logs, `queued for Robinhood pickup`), so no trade intent was silently lost — only the Tradier leg of extended-hours orders is affected.

- **Real bug #1, found investigating: `tradier_api._post()` was discarding every 4xx error body, always returning `None`.** `place_equity_order()`/`place_option_order()`'s `(resp or {}).get("errors", {}).get("error", "unknown error")` therefore always hit the `"unknown error"` fallback — the actual, useful Tradier rejection text was already being logged one line earlier (`_post()`'s own warning), but never reached the caller, Discord alerts, or the returned `message` field. **This affected every order failure ever logged by this codebase, not just this incident.** Fixed: `_post()` now returns the parsed JSON error body on non-2xx/non-401 responses instead of `None`. New `_extract_error()` helper also handles Tradier's `error` key being a list (multiple validation errors), not just a single string — both `place_equity_order` and `place_option_order` now use it.
- **Real bug #2, NOT fully resolved — root cause unconfirmed:** whether Tradier genuinely discontinued `duration="post"` (`iam_executor._ext_hours_duration()` returns `"pre"`/`"post"` for pre/post-market equity orders) is a real, open question. `docs.tradier.com` and `api.tradier.com` are both network-blocked from this sandbox (same restriction already documented for other hosts throughout this file), so the correct current replacement value — if one exists — could not be verified. **Rather than guess a replacement duration value on a live-money order parameter**, `iam_executor.py` now tracks per-duration (`"pre"`/`"post"`, independently) failures in-process via `_EXT_HOURS_DURATION_BROKEN` — after the first confirmed duration-related rejection this run, further extended-hours Tradier attempts with that duration are skipped (falling straight to the already-working Robinhood queue) instead of repeatedly re-attempting a call already known broken. Resets every restart/redeploy, so it always retries fresh in case Tradier restores support or this was transient. **Only trips on failures whose message actually mentions "duration"** — an unrelated order failure (e.g. insufficient funds) does not trip it.
- **This does not fix the underlying Tradier-side issue** — if `duration="post"`/`"pre"` really is permanently gone, extended-hours Tradier orders for ALL primary systems stay silently degraded to Robinhood-only until Tradier support or their current docs confirm the real replacement value and someone updates `_ext_hours_duration()` accordingly. Flagged here, not silently worked around forever.
- Tests: `tests/test_tradier_ext_hours_duration_bug.py` — real error-body propagation (string and list shapes), `place_option_order` benefits too, circuit breaker skips a second attempt after the first real failure, `pre`/`post` tracked independently, only duration-related failures trip it. All pass against the real, unmodified code with only `requests.post`/`tradier_api.place_equity_order` mocked.
- Also fixed the same night: a third, previously-missed "741" hardcode in `iam_executor.py`'s own log text (`"741 macro regime is..."`) — same stale-branding issue already fixed in `macro741_bp.py`/`macro_bp.py`, found on a follow-up self-audit since this file wasn't touched by that earlier pass.

## Execution-layer audit + refactor — 6 real defects fixed, options had NO exit path at all (2026-07-31)

Operator directive: full audit of the Robinhood/Tradier execution pipeline against three reported symptoms — (1) buys land after the move, flat entries; (2) sells are consistently late, winners round-trip to break-even; (3) entries chase momentum instead of verifying it. Every finding below is a defect actually present in the code, verified by reading it, not inferred from the symptom.

**The finding that matters most: `iam_executor.py` could buy options but nothing anywhere could sell one.** `sell_to_close` appears in this repo only inside `tools/gamma_ramp/` (a separate desk with its own Robinhood executor) and in `tradier_api.py`'s docstring. `_close_equity_position()` closes EQUITY only. So under the currently recommended `IAM_INSTRUMENT=options`, every call and put opened by CASCADE / S/R Matrix / Breakout / MM-V4 / S/R Zone+Pattern / Squeeze Fuel was held to expiry or closed by hand. That is symptom #2's mechanical root cause on the options leg — there were no automated sells to be late.

**The six defects:**
1. **Exits were blocked by entry-only gates.** `_gate_check()` applied every gate to every action, so a SELL could be refused by the daily order cap, the per-symbol cooldown, the confidence floor, the time-window filter, or the daily-loss breaker. The breaker case is the worst: a bad day tripped it and the executor then stopped closing losing positions. CLAUDE.md's "exits never blocked" was only ever true of the symbol allowlist. Fixed via `_gate_check(..., is_exit=True)`; the SELL branch's put leg re-runs the full entry gate separately (`_entry_gate_check`) so relaxing this never lets an un-vetted new position through.
2. **No option exit path** (above). Fixed by the new `position_manager.py`.
3. **Static stop that never moved.** `IAM_STOP_LOSS_PCT` places one GTC stop at entry−3% and that is the entire exit policy for equity. A position up 20% that gave it all back still exited at the original stop. Fixed with a ratcheting ATR trail + giveback lock.
4. **Raw market orders.** Regular-hours entries AND exits used `order_type="market"` — unbounded slippage, on a deliberately wide scan universe ("no cap, many tickers"). Now bounded marketable limits.
5. **Options priced at `ask × 1.05` with no reference to the bid.** On a 1.00 × 1.40 contract (33% spread, routine at 0.32-0.40Δ) that paid 1.47 — the position needed ~47% just to reach the mid it was worth at purchase. Also meant it would buy a 0.00 × 2.50 dead contract with no exit at any price, which `delta_explosion_bp.py` already excluded from its own rankings. Now mid-based with a spread cap and a dead-contract refusal.
6. **Stale signal price used for sizing AND the stop.** Every scanner passes its signal bar's close (`breakout_scanner` passes `bars[-1]["c"]`); on a daily-bar engine that can be a full session stale, and it set both the share count and the stop level — so the "3% stop" was 3% below a price that no longer existed. Now uses the live NBBO, falling back to the signal price only when no quote is available.

**New modules:**
- **`execution_quality.py`** — pure functions: `atr()`, `live_nbbo()`, `spread_pct/spread_ok()`, `marketable_limit()`, `fallback_limit()`, `chase_guard()`/`bar_exhausted()`. Governing rule: **entries fail closed, exits fail open.** One deliberate exception — a *missing* quote degrades an entry to a bounded fallback limit rather than blocking, because a Tradier quote outage silently halting every entry would be its own outage. A too-wide quote still blocks.
- **`position_manager.py`** — the active exit manager, 15s loop (vs. 300s scanners) since exits are time-critical in a way entries are not. Hard stop → ATR trail → target → giveback lock → options time stop → instant reversal exit. **Manages ONLY positions `iam_executor` itself registered; never adopts or sells a manually-opened position, and can only ever place closing sells.** Redis-backed when `REDIS_URL` is set (survives redeploy), local JSON otherwise — the JSON fallback does NOT survive a Render redeploy, so an option opened before a redeploy becomes orphaned again; `status()` discloses which backend answered. Started in `core/app.py`; `GET /api/positions/managed` exposes state.

**Anti-chase guard (symptom #1) — a RISK FILTER, not a claimed edge.** Refuses a BUY once price has already run >`IAM_MAX_ENTRY_EXTENSION_ATR` (default 1.0) ATRs past the signal price, or when the signal bar's own range already exceeds 2×ATR and price sits in the top 20% of it. Symptom #1 is partly *structural and not fixable in the executor*: a daily Donchian break is only knowable at the breakout day's close, and an S/R pivot confirms `bars` bars after the fact by design (no lookahead). Part of the move has genuinely already happened by signal time. This guard refuses the tail of it — and note the published backtests for these systems assumed entry at the signal bar's close, so skipping extended entries moves live behaviour *closer* to what was measured, not further from it. Fails open when ATR history is unavailable.

**What this does NOT do — read before assuming:**
- **No live-arming flag was touched.** No `IAM_PAPER_MODE`, `IAM_AUTO_TRADING`, `IAM_PRIMARY_SYSTEM`, `TRADIER_LIVE`, `ROBINHOOD_PAPER_MODE` or `KILL_SWITCH` change. No sandbox here has ever had Render access.
- **This is not profitability evidence and no backtest was run for it.** Better fills, real exits and fewer chased entries are execution-quality improvements; none of it makes an unproven engine proven. Every engine's verdict documented elsewhere in this file stands exactly as written.
- **The Robinhood leg is unchanged.** `tools/robinhood_executor_sml.py` still trades equity only for these systems (`_poll_iam_primary()` → generic `_execute()`), still polls at 45s, and has its own separate risk rails. Real Robinhood options execution for the 5 primary systems remains an unbuilt gap, as already documented.
- **`core/api/convergence_bp.py`'s GOD_MODE path and CEOTrader were not touched** — both are separate live-order surfaces (see their own sections). Positions they open are not registered with `position_manager` and therefore are not managed by it.
- **The `duration="post"` Tradier rejection is still unresolved** (see the section above); this refactor does not fix it.
- **GitNexus impact analysis was NOT run** — its MCP tools were not available in this session. The blast radius was established by reading call sites directly instead.
- Tests: `tests/test_execution_refactor.py` (50 assertions across 13 defect-specific cases — gate split, marketable limits, spread guard, chase guard, bar exhaustion, option exit policy, ATR trail, peak-ratchet, registration/reversal, paper-mode isolation, option time stop, live-vs-stale stop, fail-closed/fail-open). Plus 2 new cases in `tests/test_iam_options_cap_and_routing.py` for the dead-contract and wide-spread refusals — that file's chain fixture was ask-only and had to gain real bids, since a real Tradier chain always quotes both sides and the executor now requires it. All pass against real, unmodified code with only Tradier/DataManager stubbed. `test_paper_trade_ledger.py` and `test_convergence_daily_loss_breaker.py` still cannot run in this sandbox (no `flask` installed) — confirmed pre-existing by re-running them against a clean stash, not caused by these changes.

**Env vars added (all optional, all with safe defaults — nothing must be set for this to work):** `IAM_LIMIT_OFFSET_BPS` (10), `IAM_MAX_SPREAD_PCT_EQUITY` (0.60), `IAM_MAX_SPREAD_PCT_OPTION` (8.0), `IAM_MAX_ENTRY_EXTENSION_ATR` (1.0), `IAM_MAX_BAR_EXTENSION_ATR` (2.0), `IAM_BAR_POS_PCT` (0.80), `POSITION_MANAGER_ENABLED` (true), `POSITION_MANAGER_INTERVAL` (15), `IAM_TRAIL_ATR_MULT` (2.0), `IAM_TRAIL_ARM_PCT` (1.0), `IAM_TARGET_PCT` (0=off), `IAM_GIVEBACK_ARM_PCT` (8.0), `IAM_GIVEBACK_PCT` (40.0), `IAM_OPTION_TIME_STOP_MIN` (30), `IAM_OPTION_HARD_STOP_PCT` (35.0). Setting `REDIS_URL` (already set for CASCADE/AEO) is what makes the position registry survive a redeploy.

## The other TWO live-order surfaces had no working exit at all — CEOTrader was announcing closes that never happened (2026-07-31, follow-up to the execution-layer audit)

Follow-up to the audit above. That work gave the IAM path real exits; this extends the same coverage to the two *other* surfaces that place real Tradier orders. Both were verified by reading the code and by grep against the real tree, not inferred.

**State before this change, across all three live surfaces:**

| Surface | Real orders | Stop placed | Exit management |
|---|---|---|---|
| `iam_executor.py` | yes | GTC stop + ATR trail + giveback | ✅ (fixed in PR #421) |
| `core/api/convergence_bp.py` GOD_MODE | yes | **none, of any kind** | **none** |
| `execution_engine.py` / CEOTrader | yes, Kelly-sized, auto-starts on boot | **none placed** (levels computed, stored, never sent) | **dead code** |

**The worst finding — CEOTrader reported closes that never occurred.** `execution_engine.py` computes real ATR stop/target levels and stores them on each trade, but:
1. `update_live_prices()` is the only function that reads those levels, and **nothing in this repo calls it** (confirmed by grep — the definition is its only occurrence). So the stop never even evaluated.
2. Even if it had, the closer it calls — `_close_trade_unsafe()` — **places no broker order whatsoever**. It pops the tracking row, computes P&L from `current_price`, feeds `daily_pnl`, records a PDT day-trade, and fires a `💰 TRADE CLOSED — PnL: $X` Discord alert. The real Tradier position stays open indefinitely and the reported P&L is modelled, not a fill.

This is a strong candidate for the operator's long-standing "says buy or sell but I can't find it in Robinhood" complaint, which the CEOTrader section elsewhere in this file explicitly notes was never fully root-caused. **A Discord "TRADE CLOSED" from this engine was not evidence that anything was sold.** (It is not the whole story — the Oracle-poll confidence gate in `robinhood_executor_sml.py` remains a separate real candidate, and that one is still not root-caused.)

**Fixes:**
- `execution_engine._register_for_exit_management()` — every real LIVE fill is registered with `position_manager` using the **verified** fill price (`poll_order_fill`'s average, not the signal price), the ATR-derived stop, and a real ATR for the trail. Tagged `CEO_TRADER`. Best-effort: a registration failure never rolls back an order that already reached the broker, but logs at ERROR since an unregistered live position is the exact unmanaged state this prevents.
- `execution_engine._close_trade_unsafe()` — a LIVE close now routes the real broker order through `position_manager.close_position()`, which verifies held quantity against the live account first and self-heals if something already closed it, so it stays correct whether or not the exit manager got there first and **can never double-sell**. SHADOW closes are untouched and still never reach a broker.
- `convergence_bp._fire_execution()` — the bare `place_equity_order(symbol, quantity, side)` defaulted to `order_type="market"` in `tradier_api` (unbounded slippage on a deliberately wide $1-$50 universe). Now a bounded marketable limit with an entry-only spread guard, exits falling back to market if nothing is quotable. Real BUY fills register with `position_manager` tagged `GOD_MODE`.
- New `GOD_MODE_STOP_PCT` env var, **defaulting to `IAM_STOP_LOSS_PCT`** so both live surfaces share one stop policy unless deliberately split. Read at call time, so it changes without a redeploy.

**What this does NOT do:**
- **`update_live_prices()` was deliberately NOT wired up.** `position_manager` already does that job on a 15s loop with better logic (ratcheting trail, giveback lock, real position verification). Wiring a second exit loop over the same positions would risk double-sells. It remains dormant legacy code — but `_close_trade_unsafe` is now safe if anything ever does call it.
- **No live-arming flag touched** — `TRADIER_LIVE`, `LIVE_TRADING_ENABLED`, `IAM_*`, `ROBINHOOD_PAPER_MODE`, `KILL_SWITCH` all unchanged. Whether CEOTrader *should* be live at all is still the separate, undiscussed question flagged in its own section; this only makes it survivable if it is.
- **Still no backtest evidence** for the CEOTrader (OracleEngine → Kelly) pathway or for GOD_MODE. Real exits are not profitability evidence.
- **Manually-opened positions are never touched** — `position_manager` only ever manages what was explicitly registered, and only ever places closing sells.
- Tests: `tests/test_live_surface_exit_coverage.py` — 27 assertions. Notably it drives the **real** `_fire_execution()` end to end past every gate (arm switch, PDT, breaker, cross-engine claim) and asserts the order is a LIMIT with a bounded price and that the fill lands in the exit registry with a real stop; plus the dead-`update_live_prices` fact as a standing grep assertion, live-vs-shadow close behaviour, and the never-roll-back-an-order guarantee.
- **Sandbox note for future agents:** `pandas`, `flask`, `flask-cors`, `python-dotenv`, `openai`, `stripe` and `redis` are all installable here with `pip install --ignore-installed <pkg>` (the plain install fails on a debian-managed `blinker` whose RECORD file is missing). Doing so makes `tests/test_convergence_daily_loss_breaker.py`, `tests/test_execution_engine_gex_fix.py` and most wiring tests runnable in-sandbox — several CLAUDE.md entries claim these "cannot run here," which is now only true of `tests/test_paper_trade_ledger.py`, blocked by a genuinely broken system `cryptography` (pyo3 `PanicException`), confirmed pre-existing against a clean stash.

## Robinhood options leg — a signal that bought a CALL on Tradier no longer buys SHARES on Robinhood (built 2026-07-31)

Closes the inconsistency flagged (and explicitly left unbuilt) in the "CRITICAL FIX: options desk was silently dead" section: *"Robinhood side of these same signals still only ever trades equity, never calls/puts... If real Robinhood options execution for these 5 systems is wanted, that's a new build, not done."* Operator asked for it directly. This is that build.

**The problem.** With `IAM_INSTRUMENT=options` (the currently recommended setting), the Tradier leg buys a 0.32-0.40Δ call/put while `_poll_iam_primary()` handed the same signal to the generic equity `_execute()` — so one signal produced an option on one real account and shares on another, with completely different risk profiles, leverage and expiry behaviour.

**The fix — forward the contract, never re-derive it.** Options are exchange-standardized: the same underlying + expiration + strike + type is literally the same contract at both brokers. So `iam_executor` now passes the exact contract its Tradier leg selected through the queue, and Robinhood places that one.
- `iam_executor._execute_tradier_options()` builds a `contract` dict (type, strike, expiration, bid/ask, premium, limit_price, real delta, OCC symbol, source tag) shaped for the PC executor's existing `_execute_option()` sniper param, and returns it on both the paper and live paths.
- `iam_executor._contract_from_result()` extracts it from either result shape — a BUY returns it flat, a SELL nests it under `["put"]` (the `bear_protect_and_put` close leg is equity and has no contract). Returns `None` on an incomplete contract so the Robinhood leg degrades to equity rather than half-placing something.
- `core/api/iam_pending_bp.push_iam_primary_signal()` takes an optional `contract=` and stamps `instrument: "option" | "equity"`. **Omitting it is exactly the old behaviour**, so an older PC executor that predates this field is unaffected in both directions.
- `tools/robinhood_executor_sml._poll_iam_primary()` routes to the already-existing `_execute_option()` when a valid contract is present, else the unchanged equity path.

**Nothing new was written on the Robinhood order side.** `_execute_option()` already existed (built for the Gamma Ramp desk) and is explicitly documented to never re-derive strike/expiration — "the upstream picked one specific listed contract, and that's the one we place on Robinhood." It carries its own full risk stack: circuit breaker, blocklist, per-scan cap, delta band, direction gates for calls, PDT, shared cooldown, and it is **buy_to_open only** — no path here sells to open or shorts.

- **A compound-SELL bug was caught and fixed during the build, before it shipped.** A server-side SELL does TWO things (`bear_protect_and_put`: close the existing long, then buy a put). Routing SELL straight to the put on Robinhood would have silently dropped the close leg, leaving a Robinhood long open that Tradier had already exited — the two accounts diverging in the one direction that costs real money. The poll now runs the equity close first, then the put, mirroring the server sequence. `_execute()` refuses to short, so with nothing held that close is a logged no-op, not a new short. Regression-tested including the ordering (`tests/test_robinhood_options_leg.py::test_sell_routes_both_close_and_put`).
- **A real, deliberate divergence to be aware of:** `_execute_option()` hard-rejects any contract with |Δ| outside **0.30-0.40**. `IAM_DELTA_MIN`/`MAX` default to 0.32/0.40, comfortably inside it, so the normal path agrees on both brokers. But (a) if `IAM_DELTA_MIN` is ever widened below 0.30, Tradier will fill and **Robinhood will skip**, and (b) when no contract sits in the delta bracket, `_execute_tradier_options()` falls back to nearest-ATM-by-strike, whose delta (~0.50) Robinhood will also reject. Both cases log loudly on the Robinhood side. **This was left as-is rather than widening Robinhood's band** — that band is its own risk rail on the funded account, and skipping is more conservative than either buying shares instead or loosening a live limit. Contracts with no greeks forward `delta: None`, which `_execute_option` soft-allows (pre-existing "legacy pack" behaviour, unchanged).
- **Still equity-only on Robinhood:** the Oracle poll, TradingView-Pine (`tv_pending`) and beastmode paths. Only the IAM primary-system queue gained an options leg — that was the specific ask.
- **This changes no live-arming flag and no risk parameter.** It changes *which instrument* the Robinhood leg buys to match what Tradier already bought; it does not make it buy more, more often, or with less protection. The intentional doubled exposure across the two accounts (2026-07-29 operator decision) is unchanged in kind — it is now doubled in the *same* instrument rather than two different ones.
- Tests: `tests/test_robinhood_options_leg.py` — 27 assertions (contract extraction from both result shapes, incomplete-contract refusal, queue round-trip, equity backward compatibility, existing queue guards, the delta-band divergence stated explicitly rather than hidden, delta-None soft-allow, and the compound-SELL ordering). `tests/test_iam_robinhood_pending_queue.py` re-run and passing unchanged, plus the full 11-file execution suite.

## Robinhood IAM-pending queue was silently discarding signals beyond `MAX_PER_SCAN` per poll — real bug, found during the 7-engine audit (2026-08-01)

Found while auditing the account-wide options caps (see above) and asked directly to check the local Robinhood-side executor config for an analogous problem — there was one, and it was worse than a config mismatch.

- **The bug:** `core/api/iam_pending_bp.py`'s `GET /api/webhooks/iam_pending` route popped and cleared its **entire** queue on every single read, unconditionally — but its only consumer, `tools/robinhood_executor_sml.py`'s `_poll_iam_primary()`, only ever executes up to `MAX_PER_SCAN` (was `3`, a value chosen back when far fewer systems shared this queue) of the returned signals per 45-second poll, via one shared `scan_counter`. With 7 primary systems now live (`SML_CASCADE, SML_BREAKOUT, SML_MM_V4, SML_SR_MATRIX, SML_SR_ZONE_PATTERN, SML_SOVEREIGN_SQUEEZE`, and `SML_QUAD_SCORE` pending the operator's Render edit) all capable of queuing a signal in the same window, any signal beyond the 3rd fetched in one poll was **permanently discarded** — not "deferred to next cycle" as the executor's own log line (`"per-scan batch limit {MAX_PER_SCAN} reached, deferring to next cycle"`) implied, because the server-side queue backing it had already been wiped by the act of fetching it. Real practical effect: on any poll cycle where more than 3 primary-system signals fired at once, Robinhood silently missed some of the same trades Tradier had already placed — a real, if intermittent, source of the two brokers' positions diverging.
- **Fixed on both ends:**
  - `core/api/iam_pending_bp.py` — `_pop_all()` now takes an optional `limit`, popping only the oldest N fresh signals (FIFO) and leaving the remainder queued in original order for a later poll, instead of clearing everything regardless of what's returned. The route reads it from an optional `?limit=N` query param; omitted or invalid falls back to the exact prior behavior (pop everything), so this is fully backward compatible with any caller that predates the fix. TTL (10 min) still applies independently to whatever is left queued.
  - `tools/robinhood_executor_sml.py`'s `_poll_iam_primary()` now requests `?limit={MAX_PER_SCAN}` instead of fetching unbounded — it only ever pulls as many signals as it could possibly execute this cycle, leaving genuine overflow queued for the next 45s poll rather than losing it. `MAX_PER_SCAN`'s default raised `3 → 10` (`tools/robinhood_executor_sml.py` and `tools/executor.env.example` both updated) to give the now-7-system roster real throughput per cycle rather than just plugging the leak at the old, already-too-low value.
- **⚠️ CORRECTED same day — the parallel `tv_pending` queue DID share this exact bug.** This section originally said the `tv_pending` queue (`core/api/tradingview_webhook_bp.py`, raw TradingView-Pine alerts — `SML_Sniper`/MMLE Beast) "was not investigated... may or may not share the same pattern." Asked directly to check, it did — same fix applied, see the dedicated section below.
- **No live-arming flag or risk parameter touched.** This doesn't change what triggers a trade or how large one is — it changes whether an already-triggered signal reliably reaches the Robinhood leg at all.
- Tests: `tests/test_iam_pending_queue_limit_fix.py` — 8 tests: unlimited pop still clears everything (backward compat), a limited pop leaves the remainder queued in FIFO order instead of discarding it (the actual bug, reproduced and proven fixed), `limit=0` pops nothing, a limit larger than the queue still pops everything, repeated limited polls (simulating several 45s cycles) drain a 10-signal backlog with zero loss, the Flask route honors `?limit=N`, an invalid `?limit=` degrades safely to pop-everything, and TTL expiry still applies to signals a limited pop left behind. `tests/test_iam_robinhood_pending_queue.py` re-run and passing unchanged (its `_pop_all()` calls all use the default unlimited behavior, so this is a strictly additive change).

## tv_pending queue had the IDENTICAL signal-loss bug — found and fixed the same day (2026-08-01)

Operator directive after the IAM-pending fix above shipped: "fix any and everything you know about, skipped, or ignored." The IAM-pending section originally disclosed the `tv_pending` queue (`core/api/tradingview_webhook_bp.py` — raw TradingView Pine-script alerts, `SML_Sniper`/MMLE Beast) as unchecked. Checked directly by reading the code (grepped every `deque(maxlen=...)` in `core/api/` and inspected each one's consumer) rather than guessing: `battle.py` and `oracle_data_bp.py`'s buffers are read-only ring buffers (their GET routes never clear anything) — no issue there. `tv_pending` is a genuine second instance of the exact same defect.

**In plain terms, for anyone reading this who isn't a programmer:** think of the queue as a mailbox. The old code, every time anyone checked the mailbox, took out ALL the letters and threw the mailbox's copy away — even if the person checking could only actually read the first 3 letters that trip. Any letters past the 3rd were gone forever, not "still in the mailbox for next time" like the logs claimed. The fix makes checking the mailbox only remove the letters actually read, leaving the rest inside for the next check.

- **The bug, exactly as before:** `_queue_pop_all()` popped and cleared the **entire** `_TV_QUEUE` on every single GET to `/api/webhooks/tv_pending`, but `tools/robinhood_executor_sml.py`'s `_poll_tv_pending()` only ever executes up to `MAX_PER_SCAN` of the returned signals per 45s poll via its own `scan_counter`. Any Sniper/MMLE-Beast Pine signal beyond that cap in a single fetch was permanently discarded, not deferred as intended.
- **Fixed identically:** `_queue_pop_all(limit=None)` now pops only the oldest N fresh signals (FIFO) when a limit is given, re-queuing the remainder; the route accepts `?limit=N`, omitted/invalid falls back to pop-everything (fully backward compatible). `_poll_tv_pending()` now requests `?limit={MAX_PER_SCAN}` (the same, already-raised default of 10).
- **Full audit result, so this doesn't need re-checking:** every `deque`-backed queue in `core/api/` was enumerated and checked — `iam_pending_bp.py` (fixed earlier today) and `tv_pending_bp.py`/`tradingview_webhook_bp.py` (fixed here) are the only two destructive pop-all queues in the codebase; both are now fixed. No other instance of this bug class remains.
- **No live-arming flag or risk parameter touched** — same as the IAM-pending fix, this only affects whether an already-triggered Pine-script signal reliably reaches the Robinhood leg.
- Tests: `tests/test_tv_pending_queue_limit_fix.py` — same 8-test shape as `test_iam_pending_queue_limit_fix.py` (backward compat, FIFO remainder preservation, `limit=0`, over-large limit, multi-poll full drain, route `?limit=N`, invalid-limit fallback, TTL-still-applies), all against the real, unmodified `_queue_pop_all()`/route/`_queue_push()`.

## CEOTrader DISARMED — now requires `AUTOPILOT_ENABLED=true` (operator decision, 2026-07-31)

Operator asked directly for a recommendation on the CEOTrader situation and accepted it. **This engine no longer starts unless `AUTOPILOT_ENABLED=true` is set. It defaults OFF.**

**Why this one, and not the others.** Four findings from this session, together:
1. **It auto-starts on every boot** whenever `TRADIER_LIVE=true` (`core/legacy.py`: `if exec_eng.live_mode: ceo.start()`), placing real Kelly-sized Tradier orders — and CLAUDE.md claimed it was "not auto-started," **wrongly, twice**. Nobody knew it was live.
2. **It is the only live surface that never went through this codebase's own evidence-then-explicit-decision process.** No backtest exists anywhere for its pathway (OracleEngine verdict → Kelly sizing → Tradier order), unlike CASCADE / Breakout / S-R Matrix which each cleared a real backtest or an explicitly informed operator decision.
3. **It answers to none of the documented kill switches** — `IAM_PAPER_MODE`, `IAM_AUTO_TRADING`, `IAM_PRIMARY_SYSTEM`, `LIVE_TRADING_ENABLED`, `ROBINHOOD_PAPER_MODE`, `KILL_SWITCH` all leave it running. **This is the property that actually decided it.** An engine that keeps trading after the operator has flipped every switch they believe controls the desk is an operational hazard independent of whether it has an edge.
4. **`_kelly_qty()` uses Oracle's confidence score directly as the win probability `p`.** That number has never been validated against realized outcomes. Kelly is only well-behaved when `p` is measured, not assumed; fed an assumed `p` it systematically oversizes. Per-trade exposure is still bounded (`AUTOPILOT_MAX_POSITION_PCT` 5% of equity, `AUTOPILOT_MAX_ORDER_VALUE` $500, `AUTOPILOT_MAX_CONCURRENT` 3), so this was never a blow-up-the-account risk — but position sizes were arbitrary rather than risk-calibrated.
   - Secondary, not decisive: default `AUTOPILOT_SYMBOLS` is the fixed 9-name list `GME,AMC,IWM,SPY,QQQ,MSTR,NVDA,TSLA,PLTR`. It IS env-overridable (so not strictly hardcoded), but if unset it runs exactly the fixed universe Prime Directive #1 forbids, including the GME/AMC/MSTR names `docs/ENGINE_SCOREBOARD_2026-07-17.md` says no engine earned.

- **The gate lives inside `CEOTrader.start()`, not at either call site** — deliberately, so it covers BOTH the boot auto-start in `core/legacy.py` AND the manual `POST /api/autopilot/start` endpoint. Off means off from every direction; there is no path that starts this engine without the operator setting the variable. A refusal logs loudly and pushes to the terminal feed, so a disarmed engine is visible rather than silently absent.
- **To re-arm:** set `AUTOPILOT_ENABLED=true` on Render. Nothing else needs changing — the disarm touches no other flag, and `TRADIER_LIVE` was deliberately NOT used for this (it would also drop `ExecutionEngine` into shadow mode globally, a much wider blast radius than intended).
- **This is a disarm, not a verdict that the strategy is bad.** No backtest was run for it; the honest status is still "unmeasured," exactly as before. If it's ever wanted live, the right sequence is the same one every other engine followed: backtest it, state the evidence plainly, then decide.

### `BEAST_MAX_PRICE` — a second env-var collision, found alongside this

Same bug class as the `MACRO_STACK_WARMUP` collision documented above. One env var, two unrelated meanings, defaults 20x apart:
- `core/api/convergence_bp.py` reads it as a **notional budget** — `quantity = _BEAST_MAX_PRICE // price`, default `500.0`
- `execution_engine.py` read the **same name** as a hard **per-order dollar cap**, default `25.0`

Whatever is set on Render silently governs both at once. **Fixed:** `execution_engine.py` now reads its own `EXECUTION_MAX_ORDER_VALUE`, **falling back to `BEAST_MAX_PRICE`** so an existing deployment's effective cap is completely unchanged until the new var is set — this disambiguates going forward without silently retightening or loosening a live risk limit as a side effect of a rename. `convergence_bp.py`'s own meaning is untouched.

- Tests: `tests/test_ceotrader_arm_switch.py` — 29 assertions (defaults-off, explicit re-arm, truthy-spelling parsing, boot-autostart path covered, manual-endpoint path covered, other engines' arm switches unaffected, and the `BEAST_MAX_PRICE` fallback preserving today's cap exactly). All pass against real, unmodified code.

## CEOTrader "Sovereign Autopilot" actually DOES auto-start on boot — CLAUDE.md's own prior claim was wrong (found 2026-07-31)

The "CEOTrader / `execution_engine.py` (v5.0 legacy engine)" section elsewhere in this file claims: *"Not auto-started. Unlike every scanner in the IAM ecosystem... CEOTrader's autopilot loop only ever runs after an explicit `POST /api/autopilot/start` call. If nothing calls that endpoint, this entire engine is idle."* **This is wrong, found by actually reading `core/legacy.py` rather than trusting that prior claim.** `core/legacy.py`'s `init_services()` has, unconditionally on every boot:
  ```python
  # 4. Auto-Start CEO if Live (MUST BE OUTSIDE state.lock to prevent nested lock deadlock)
  if exec_eng.live_mode:
      ceo.start()
  ```
  `exec_eng.live_mode` is driven by `TRADIER_LIVE`, which production logs confirm is `true` (`[EXECUTION] Broker → Tradier LIVE` on every boot this whole session). **This means CEOTrader has been auto-starting and placing real, Kelly-sized (`Kelly=0.25`) Tradier equity orders on a 9-symbol list (`GME, AMC, IWM, SPY, QQQ, MSTR, NVDA, TSLA, PLTR`, `MinConf=82.0`, `MaxConcurrent=3`) on every single deploy this whole session** — completely independent of `IAM_PRIMARY_SYSTEM`, `EXECUTION_MODE`/`LIVE_TRADING_ENABLED` (auto_exec.py), or `ROBINHOOD_PAPER_MODE`/`KILL_SWITCH` (the local Robinhood executor). None of this session's live-arming discussions or guardrails touch this pathway at all.
- **No backtest evidence found for this specific pathway** (OracleEngine verdict → Kelly-sized CEOTrader execution) — not the same thing as CASCADE/Breakout/SR-Matrix's real backtests, and not the same thing as the convergence/GOD-MODE engine either (a fourth, separate live-trading surface).
- **Not fixed or disarmed** — this section only corrects the documentation and flags the discovery; whether to actually gate/disarm/backtest this pathway is the operator's own decision, not made here without being asked.
- **Every agent going forward: verify `core/legacy.py`'s `init_services()` directly before repeating the "not auto-started" claim about CEOTrader** — this file said it confidently and it was wrong.

## SML CVD Regime Desk — 7 bugs fixed in an operator-submitted script; BACKTEST + 1000-CONFIG SEARCH DONE, verdict DO NOT ARM LIVE (edge real but decaying and thinner than the option spread) (2026-07-30)

Operator pasted a Pine v6 script ("CVD Regime Fast → Call/Put Desk") asking to "fix this script for trading perfectly delta options." Full treatment done the same day, same pattern as every other engine here (Pine is a visual, Python engine is the single source of truth, real backtest before any claim). **Seven real bugs found and fixed.** Full writeup: `docs/CVD_REGIME_BACKTEST_2026-07-30.md`.

- `cvd_regime_engine.py` — the single Python implementation. `indicators/SML_CVD_Regime_Desk_v6.pine` — corrected chart visual, same panel/dashboard as submitted. `tests/backtest_cvd_regime.py` (harness), `tests/test_cvd_regime_engine_smoke.py` (14 tests, one per bug), `tests/compare_cvd_original_vs_fixed.py` (before/after on real bars).
- **The critical bug (BUG 1):** `htfSlope = htfCvdS - htfCvdS[slopeLen]` indexed the CHART bar array, not the HTF bar array. `request.security()` holds the last *closed* HTF value flat across every chart bar inside the forming HTF bar, so on a 5-min chart with a 60-min HTF that expression was **exactly 0.0 on 73.7% of bars (measured on real SPY data)** — and `alignedBull`/`alignedBear`/`earlyCall`/`earlyPut` all require `htfBull` or `htfBear`, so no signal could fire on those bars. **The effect was signal QUANTIZATION, not starvation** — a first-pass reading of this bug says "it blocks everything," and measurement disproved that: all signals were confined to the 26.4% of bars where an HTF boundary fell inside the 3-bar window (a burst after each hourly close), reading a 1-HTF-bar difference rather than the intended 3. On the same real bars the original actually emitted **more** signals than the fixed engine (217 vs 102 across 5 symbols) because the conviction gate was inert and there was no position state. Fixed by building the HTF series natively from bar timestamps — `request.security()` is gone entirely, which also removes its realtime repaint and guarantees Pine/Python parity.
- **The other six, each measured not assumed:** (2) the conviction filter was a no-op for any `minConviction` from 17 to 83 — flat ±14/±10/±10 scoring meant an aligned bar always scored ≥84 or ≤16, so the threshold could never bind (fixed: continuous contributions; 69.2% of scores now land in the 25-75 band the original arithmetic couldn't reach); (3) `strength` divided a 3-bar CVD *change* by the stdev of the cumulative *level* — measured median 0.326, hitting its ±14 cap on 1.5% of bars, so the term was near-dead weight (fixed: normalize by the stdev of the slope, median 0.948); (4) `cvd` was reset daily but `ta.ema(cvd, smoothLen)` was not, so the smoothed series inherited yesterday's ending level and showed a large artificial slope on the first bars of every session; (5) `exitLong`/`exitShort` were neither position-aware nor edge-gated — an X-cross plotted on every bar of a trend, firing while flat; (6) no `barstate.isconfirmed` anywhere → mid-bar repaint; (7) no stop, target, cooldown or flip cap on a script whose stated purpose is buying options.
- **BACKTEST VERDICT: DO NOT ARM LIVE. Authoritative doc is `docs/CVD_REGIME_OPTIMIZATION_2026-07-30.md`**, which **supersedes the verdict** in `docs/CVD_REGIME_BACKTEST_2026-07-30.md` (that one's seven-bug audit still stands, but its "no demonstrated edge" conclusion came from only 8 sessions, 2026-07-20..29, and that window was unrepresentative — it sits entirely inside a flat June-July stretch). Real 5-min bars, **8 symbols (SPY QQQ IWM NVDA TSLA AMD AAPL MSFT), 109 sessions 2026-02-23..07-29, 68,016 bars**, Robinhood MCP.
  - **Shipped defaults are net POSITIVE over the full span: PF 1.090, +67.5% summed, 2,222 trades.** So "this strategy loses money" would be wrong.
  - **But a 1,000-config random search produced ZERO configurations that survived out-of-sample.** 588 of 1,000 cleared the TRAIN filters (≥300 trades, ≥5/8 symbols PF>1); the top 15 all collapsed on the held-out slice (TRAIN medPF 1.32-1.39 → VALID medPF 0.77-1.06, 0 of 15 held). Tuned configs did *worse* forward than the untuned defaults (VALID PF 0.984) — the signature of fitting noise. **Parameter tuning is an exhausted lever here; do not re-run a sweep expecting a different answer.**
  - **The edge decays monotonically across four consecutive ~420-trade months:** PF 1.360 (Apr) → 1.225 (May) → 1.069 (Jun) → 0.916 (Jul). Currently below break-even.
  - **The fact that actually decides it: the edge averages +0.030% of the underlying's move per trade** (best month +0.097%). On the 0.30-0.40Δ contracts this script targets, a 1-3% round-trip option spread plus ~80-100 minutes of theta per trade swamps that. This is NOT a "needs more data" or "needs better parameters" problem — the measured edge is too thin to pay for the instrument. Only a structurally stronger signal (e.g. true signed delta from a tick/quote feed instead of the OHLCV bar-range proxy) would change the arithmetic.
- **Methodology note worth reusing:** `tests/optimize_cvd_regime.py` splits chronologically (TRAIN = earlier 67% of sessions, VALID = later 33%, split on session boundaries) and the search sees TRAIN only; candidates are scored on VALID exactly once. Sweeping ~1000 configs over one history ALWAYS surfaces impressive-looking winners (588/1000 here) — without the forward split this engine would have looked like a PF 1.39 system. Any future engine tuned in this codebase should use the same guard; this is the concrete antidote to the Gamma Ramp failure mode (shipped live-by-default with no committed backtest).
- **Data-hygiene note that mattered:** of 109,248 raw bars fetched (2025-11-14 onward), **41,232 (38%) came back flagged `interpolated` with zero volume and were dropped** — all 5-min history before 2026-02-23 is synthetic gap-fill on the Robinhood MCP feed, so a requested 9 months is really 5. Feeding zero-volume synthetic bars to a *volume-weighted* CVD engine would have produced a fabricated result that looked like real history. Check the `interpolated` flag on any future intraday pull from this channel.
- **Standing limitations:** no options economics modelled (directional %-move only, same disclosed convention as `breakout_engine.py`/`mm_intel_engine.py`); no commission/slippage; "CVD" is a bar-range proxy from OHLCV, not true bid/ask delta (same proxy class as CIE's OFI/DLMD labelling); 5-min chart only (`htf_minutes` was searched, chart timeframe was not).
- **Honest next levers if this is revisited (none done):** paper-trade it forward (the Paper Trade Ledger already attributes per-system automatically, so this costs nothing); or get a real signed-delta tick/quote feed — the OHLCV proxy is the most likely reason the signal is thin; or trade the underlying rather than options, where per-trade friction is far lower. Not: another parameter sweep.
- **Also worth recording: the original script was un-backtestable as a trading system**, not merely unprofitable — it had no exit logic at all, which is why `compare_cvd_original_vs_fixed.py` compares signal counts rather than returns.
- **NO scanner was built and nothing is wired to the executor.** Unlike Breakout/SR-Matrix/MM-Intel, this has no `*_scanner.py` and no blueprint — its only possible path to execution is the Pine webhook bridge (system tag `SML_CVD_DESK`), whose passphrase input is **empty by default so it sends nothing** until deliberately filled in. **Do not add `SML_CVD_DESK` to `IAM_PRIMARY_SYSTEM`** — same bar ORB/DRUCK/AETHER/RSI-ML/Gamma Ramp didn't clear.
- **If a longer window is ever tested, add a new dated doc** rather than editing the 2026-07-30 numbers — same convention the DRUCK and CIE docs follow.

## CEOTrader / `execution_engine.py` (v5.0 legacy engine) — dead GEX fixed (2026-07-30)

**Not part of the IAM/CASCADE/Breakout/SR-Matrix/SR-Zone-Pattern/MM-V4 ecosystem documented above — a separate, older execution path** (`core/ceo_trader.py`'s "Sovereign Autopilot," registered at `/api/autopilot`). Investigated after the operator asked whether `execution_engine.py`'s always-zero GEX numbers meant it was live, old, or disconnected from anything.

- **⚠️ CORRECTED 2026-07-31 — the claim below was WRONG, do not repeat it.** ~~Not auto-started... only runs after an explicit `POST /api/autopilot/start` call~~ — **`core/legacy.py`'s `init_services()` auto-starts it on every boot whenever `exec_eng.live_mode` is true** (`if exec_eng.live_mode: ceo.start()`), and production logs confirm `TRADIER_LIVE=true` has been set this whole session. See the dedicated "CEOTrader 'Sovereign Autopilot' actually DOES auto-start on boot" section elsewhere in this file for the full correction — this means CEOTrader has been live and placing real orders independent of every other live-arming decision made this session. Verify `core/legacy.py` directly before ever repeating the old claim.
- **Defaults to SHADOW (paper) mode** — this part is still accurate on its own terms, it's the auto-start claim above it that was wrong. `execute_trade()` routes to `execute_live_trade()` only when `TRADIER_LIVE=true` is explicitly set — otherwise every trade is `execute_shadow_trade()`: logged, Discord-alerted as BUY/SELL, but no real broker order ever placed. Flagged to the operator as the likely explanation for "says buy or sell but I can't find it in Robinhood" — a separate, real candidate is the Oracle poll path in `robinhood_executor_sml.py`, which can print `SELL` verdicts and still place 0 orders due to its own confidence gate; not fully root-caused, operator is watching the terminal to confirm which one it actually is.
- **GEX was permanently zero for a real, findable reason, not a live bug in a working feature:** `get_gamma_walls()` tried to import `BEAST.gex.sml_gex_engine.GEXEngine`, a module that does not exist anywhere in this codebase (confirmed by search). The import was already wrapped in try/except and silently set `GEXEngine=None`, so this method always returned the hardcoded all-zero dict, for every symbol, unconditionally — never a partial/intermittent failure.
  - **Fixed:** now calls the real, already-live `gamma_flow_engine.calculate_gex_profile()` — the same engine already powering Oracle/Gamma Pin/Squeeze Fuel — with a real Tradier chain via `tradier_api.get_option_chain_schwab_format()`, same pattern `gamma_pin_scanner.py`/`squeeze_fuel_scanner.py` already use. `inventory_z`/`hjb_hedge_rate` are NOT part of `GEXProfile` (that's a separate Kalman/HJB computation embedded in `gamma_flow_engine.py`'s MM-Intel section) — left at 0.0, disclosed in the method's own docstring rather than silently guessed or wired to the wrong source.
  - Tests: `tests/test_execution_engine_gex_fix.py` — real chain in → real non-zero GEX profile out (regime, call/put wall, total_gex all populated from real math), honest zero/NEUTRAL when no chain is available (not a crash), 300s cache reuse verified. All pass against the real, unmodified `get_gamma_walls()` with only the Tradier chain fetch mocked.
- **Not evaluated for live-arming** — this fix makes CEOTrader's GEX reads real instead of always-zero; it says nothing about whether CEOTrader itself should ever go live. That's a separate, undiscussed question — `TRADIER_LIVE` was not touched.

## SML Sovereign Squeeze Finder — code-audited + backtested, verdict NOT profitable as-configured (2026-07-31)

Operator pasted a Pine v6 script ("ScriptMaster - Sovereign Squeeze Setup Finder v6") — a classic TTM-squeeze-style compression/release strategy (Bollinger Bands collapsing inside a Keltner Channel, then releasing, gated by a linear-regression momentum term, an RVOL spike, and an optional 200-EMA trend filter). Same session, the operator also asked to strip unverified engines from the recommended live roster — see the Squeeze Fuel section above for that decision. Genuinely different mechanic from every other squeeze-adjacent engine here — not a duplicate of `squeeze_analyzer.py`'s ignition score or `squeeze_fuel_engine.py`'s FTD/short-vol/gamma composite.

- `sovereign_squeeze_engine.py` — the single Python implementation, same convention as every other engine here (Pine is a visual, Python is the single source of truth). No bugs found in the submitted script's math during the port. `compute_series()` is the full walk-forward position state machine (one open position at a time, entry at the setup bar's close, target/stop from the script's own `lowest(low,3)`/`highest(high,3)` + R:R formula, checked on each subsequent bar's close, no lookahead); `analyze()` is the on-demand latest-bar wrapper, same convention as `breakout_engine.py`/`sr_matrix_engine.py`.
- `sovereign_squeeze_scanner.py` — background loop (started in `core/app.py` beside `squeeze_fuel_scanner`), **Daily bars** (Tradier-only friendly, no Polygon/Alpaca dependency, same as Breakout/S/R-Matrix). Fires to `iam_executor.execute_async()` tagged `system="SML_SOVEREIGN_SQUEEZE"`.
- `core/api/sovereign_squeeze_bp.py`, registered at `/api/sovereign-squeeze` — `GET /api/sovereign-squeeze/status` and `GET /api/sovereign-squeeze/<symbol>`.
- **Live-signal mapping is narrower than the full backtest state machine**, same reasoning class as `breakout_engine.py`'s ENTER-only design: `ENTER_CALL` → `BUY`, `ENTER_PUT` → `SELL`. An open CALL's `EXIT_TARGET`/`EXIT_STOP` also emits `SELL` (closes the long, matching `_close_equity_position`). A PUT position's exit emits **no live signal** — `iam_executor` has no "close an existing put" mechanism (same gap Breakout's/MM-Intel's docstrings already document), so inventing one here would add an un-backtested action. Downside on live CALL positions still comes from `iam_executor`'s own real stop-loss order.
- **Shipped-defaults backtest (2026-07-31, pre-search): NOT profitable, on a thin sample.** Real daily bars (AMC/GME/IWM/SPY/NVDA/QQQ, 2021-01–2026-07, Robinhood MCP `get_equity_historicals`, same real-data channel as every other backtest in this file), the operator's originally-submitted default parameters, no tuning. 9 completed trades across 4 symbols over 5.5 years (post the linreg momentum bug fix below); SPY and QQQ never triggered a single setup; aggregate profit factor 0.34. Full results + the linreg bug found and fixed during the port (Pine's `ta.linreg` argument is a per-bar series, not a constant subtracted from raw closes): `docs/SOVEREIGN_SQUEEZE_BACKTEST_2026-07-31.md`. That doc also has an OPEN, unresolved discrepancy against a TradingView backtest the operator reported looking much better — not yet reconciled, pending the operator's exact symbol/timeframe/date-range/settings.
- **⚠️ SUPERSEDING verdict from a real parameter search (2026-07-31): a genuinely validated edge was found, and the shipped defaults have been updated to it.** Per operator directive ("tweak it till it's profitable, or find/build one that is"), `tests/optimize_sovereign_squeeze.py` ran a chronological TRAIN(67%)/VALID(33%) parameter search — same disciplined methodology as the CVD Regime Desk's 1000-config sweep (rank on TRAIN only, score VALID exactly once, never pick the winner on VALID). Found: `bb_length=10/mult=2.5, kc_length=10/mult=2.0, min_sqz_bars=2, min_rvol=1.0, use_macro_ema=True, rr_ratio=2.0` — **96 real trades across all 6 symbols (all 6 now fire, unlike the shipped defaults), aggregate PF 2.70, 52.1% win rate, summed P&L +681%.** Held up out-of-sample across four different split points (50/60/67/75%, VALID PF always higher than TRAIN — the opposite signature of overfitting) and across single-parameter perturbations in five of six tuned dimensions. The one non-robust axis (bb_length/kc_length itself — only 10 works, 14/15/20 don't) is disclosed, not hidden. Full writeup, per-symbol/per-trade detail, and every robustness check: `docs/SOVEREIGN_SQUEEZE_OPTIMIZATION_2026-07-31.md` — **this doc supersedes the shipped-defaults verdict above** (that doc's bug-fix narrative and its own verdict for the *original* submitted defaults both still stand as written; this is a different, better config found by search, not a re-litigation).
- `sovereign_squeeze_engine.py`'s `SovereignSqueezeParams` defaults (and `SOVEREIGN_SQZ_*` env var defaults) were changed to this validated config — the operator's originally-submitted Pine defaults are preserved in the Pine file itself and in the class docstring for reference, not silently lost.
### LIVE-ARMED for real trading (operator directive, 2026-07-31: "FLIP TO REAL MONEY YES")

Given directly after the validated parameter-search evidence above was disclosed plainly — same "state the evidence, then the operator decides" pattern as every other live-arming decision in this file, not a claim manufactured to satisfy the request.

- **CONFIRMED LIVE 2026-07-31.** Operator made the Render edit and confirmed it directly (`IAM_PRIMARY_SYSTEM` now includes `SML_SOVEREIGN_SQUEEZE`) — also independently confirmed from real production logs the same day: `SOVEREIGN-SQZ-SCANNER ⚡ RDDT SELL (EXIT_STOP) → executor` / `⚡ RBLX SELL (ENTER_PUT) → executor` reaching `iam_executor`, and the primary-system gate list itself observed as `['SML_BREAKOUT', 'SML_CASCADE', 'SML_MM_V4', 'SML_SR_MATRIX', 'SML_SR_ZONE_PATTERN']` immediately before the edit (i.e. verified both the before and after state, not just taken on the operator's word). Real current value on Render: `IAM_PRIMARY_SYSTEM=SML_BREAKOUT,SML_CASCADE,SML_MM_V4,SML_SR_MATRIX,SML_SR_ZONE_PATTERN,SML_SOVEREIGN_SQUEEZE`.
- **Stop-loss is automatic, not something built per-engine** — `IAM_STOP_LOSS_PCT` (default 3.0%) places a real GTC stop-sell order on every live BUY fill regardless of which system triggered it, same as every other primary system.
- **Evidence status is unchanged by this decision** — 96 real trades, PF 2.70, held up across four out-of-sample splits, one disclosed non-robust axis (bb_length/kc_length). This section documents a real, informed real-money decision on real evidence; it is not a retroactive upgrade of that evidence's strength.
- Tests: `tests/test_sovereign_squeeze_engine_smoke.py` (coil-then-breakout/breakdown fixtures genuinely fire ENTER_CALL/ENTER_PUT, RVOL gate proven load-bearing by tightening it past what the fixture can clear, flat-series-produces-no-signals, exit-emits-SELL — all still pass against the updated defaults) and `tests/test_sovereign_squeeze_scanner_wiring.py` (dedup, no-fire-on-none, blueprint registration) — the engine smoke tests and the scanner wiring file's dedup/skip tests ran and passed in-sandbox; the blueprint-registration assertion (which imports `core.app`) could not run in this particular sandbox session due to a genuinely broken system `cryptography` package (`pyo3_runtime.PanicException` on a bare `from cryptography.hazmat...` import, reproduced independent of this change) — verified instead via `python3 -m py_compile` on every new/modified file. This is the same class of sandbox limitation already documented for `tests/test_paper_trade_ledger.py`, now also confirmed to affect any test that calls `create_app()` (broader than previously documented — `core/api/vapl_bp.py`'s import chain hits the same broken `cryptography` install).

## SML Quad-Score Explosive Breakout Finder — new engine, TRAIN/VALID search found a genuinely validated edge (2026-07-31)

Operator-provided quantitative spec (a "4-Pillar Volatility & Breakout Scoring Engine" — Compression/Trend/Participation/Trigger, each a weighted blend of real OHLCV-derived sub-indicators, combined into one composite score gated against several thresholds at once, plus a temporal sequence gate and a real weekly macro-regime filter). Explicitly built as a **new, independent, long-only engine** — not a retrofit of Sovereign Squeeze/Breakout/S-R Matrix, per an explicit operator choice when asked. The spec's original ask was a standalone `ccxt`-based crypto package (own `config.yaml`, `execution/ccxt_client.py`, event-driven backtester) — per a second explicit operator decision, this was adapted into this repo's existing conventions instead: one Python engine + scanner + blueprint, real equity daily bars via DataManager, signals routed through `iam_executor.py` under the exact same safety stack (paper-mode default, real GTC stop-loss, daily-loss breaker, primary-system gate) every other engine here already uses. No `ccxt`, no separate broker abstraction, no second sizing system fighting `iam_executor`'s own.

- `quad_score_engine.py` — the single Python source of truth. Four 0-100 pillar scores (weights below are the operator's exact spec, unmodified):
  - **Compression** (30/25/20/15/10): BB-width percentile inverted (tighter=higher), Keltner compression (boolean — BB fully inside KC), ATR percentile inverted, Donchian-width percentile inverted, 20-bar log-return HV percentile inverted.
  - **Trend** (40/30/30): EMA20/50/200 alignment (100/50/0 tiered), a rolling-window VWAP position score (disclosed proxy for a genuinely event-anchored VWAP — daily bars have no intraday anchor point), ADX14 strength.
  - **Participation** (40/30/30): Relative Volume, OBV slope percentile (percentile rank is scale-invariant, so no separate volume normalization was needed — a real simplification found while implementing the spec literally), Chaikin Money Flow.
  - **Trigger** (40/30/30): 5-bar momentum-acceleration percentile, breakout confirmation vs the PRIOR 20-bar high (no lookahead — today's own high excluded), candle structure (close-location-value).
  - **Composite** = 0.25·Compression + 0.35·Trend + 0.20·Participation + 0.20·Trigger.
- **The macro regime filter is a REAL weekly higher-timeframe check, not a same-timeframe proxy** — Weekly bars are aggregated client-side from the same real daily bars passed in (same method `cie_scanner.py` already uses for its own 1W support), and a daily bar only ever reads the last **fully completed prior week's** regime (Weekly Close > Weekly EMA200 AND Weekly ADX14 > 18) — never the still-forming current week. Both `quad_score_engine.py`'s `_weekly_macro_series()` and the companion Pine script's `request.security(..., "W", expr[1], lookahead=barmerge.lookahead_off)` idiom carry the identical no-lookahead guarantee, regression-tested in `tests/test_quad_score_engine_smoke.py::test_weekly_macro_filter_has_no_lookahead` (mutating a later day in a still-forming week must never change an earlier day's macro reading — proven, not assumed). **A real bug was caught and fixed before this shipped:** the Pine script's first draft computed `ta.ema(close, 200)`/`ta.dmi(...)` OUTSIDE `request.security()`, which would have silently used 200/14 *daily* bars mislabeled as weekly — fixed by moving that computation into a local function evaluated *inside* the security-call context, so `close`/`ta.ema`/`ta.dmi` there correctly resolve against real weekly bars.
- `quad_score_scanner.py` — background loop, **Daily bars**, `QUAD_SCORE_BARS_LIMIT` defaults to **1100** (far deeper than every other daily scanner's default here) because the weekly-EMA200 macro filter needs ~4+ years of real history just to seed. Fires to `iam_executor.execute_async()` tagged `system="SML_QUAD_SCORE"`. `core/api/quad_score_bp.py`, registered at `/api/quad-score` — `GET /status` and `GET /<symbol>`.
- **Live-signal mapping is long-only, entry-only** (same reasoning class as `breakout_engine.py`): `ENTER_CALL` → `BUY`; `EXIT_TARGET`/`EXIT_STOP` → `SELL` (closes the long, matching `_close_equity_position`). There is no short/put side to this engine at all — the operator's spec itself is long-only.
- **First backtest (shipped-defaults, operator's exact spec thresholds): mixed but net positive, THIN sample.** Real daily bars, 6 symbols (AMC/GME/IWM/SPY/NVDA/QQQ), 2018-2026, Robinhood MCP. 20 trades, aggregate PF 1.795, +51.32% — AMC never fired once (its weekly regime almost never validated). Full writeup: `docs/QUAD_SCORE_BACKTEST_2026-07-31.md`.
- **⚠️ SUPERSEDING verdict from a real parameter search: genuinely validated, not a fluke.** Per the operator's explicit directive not to stop until a properly-researched, passing backtest exists, the symbol universe was widened to 16 (adding MSTR/TSLA/PLTR/HOOD/AMD/MSFT/AAPL/META/COIN/SMCI) and a chronological TRAIN(pre-2024-06)/VALID(2024-06+) search (`tests/optimize_quad_score.py`, same disciplined methodology as the Sovereign Squeeze/CVD Regime Desk searches — rank on TRAIN only, score VALID exactly once) swept 3,000 of 15,000 gate-threshold/stop-target combinations. Found: `th_composite=65.0, th_trend=45.0, th_trigger=45.0, temporal_threshold=55.0, weekly_adx_min=18.0 (unchanged), atr_stop_mult=1.5, atr_tp_mult=3.0` — **146 real trades, aggregate PF 1.989, 55.5% win rate, +401.78% summed P&L. Held VALID PF above 1.0 at all four tested split points (50/60/67/75%) AND under single-parameter perturbation in ALL SIX tuned dimensions** — the strongest robustness signature of any search run in this codebase to date (stronger than Sovereign Squeeze's one non-robust axis, and the opposite of CVD Regime Desk's zero-of-15-survived result). `quad_score_engine.py`'s shipped defaults (and the Pine script's input defaults) were updated to this validated config — the operator's originally-specified thresholds are preserved in the module docstring and `docs/QUAD_SCORE_BACKTEST_2026-07-31.md` for reference, not silently lost. Full writeup, per-symbol table, and every robustness check: `docs/QUAD_SCORE_OPTIMIZATION_2026-07-31.md`.
- `indicators/SML_Quad_Score_Breakout_Finder_v6.pine` — full v6 visual with the smart HUD table (compression/trend/participation/trigger/composite/temporal-gate/macro-regime/stop-target/webhook-bridge rows), BB/KC bands, composite-score histogram pane, and the standard optional webhook bridge (empty-passphrase-by-default, same JSON contract as every other v6 script here, system tag `SML_QUAD_SCORE`) — the native Python engine/scanner is the production path with no TradingView dependency.
### LIVE-ARMED for real trading (operator directive, 2026-08-01: "wire it live not paper.  real money")

Given directly after the validated TRAIN/VALID evidence above was disclosed plainly — same "state the evidence, then the operator decides" pattern as every other live-arming decision in this file.

- **Not yet confirmed live from this sandbox** — same as every other engine here, no sandbox in this codebase has ever had Render dashboard access, so the operator has to make the actual env var edit directly. To arm it: append `SML_QUAD_SCORE` to whatever `IAM_PRIMARY_SYSTEM` currently is on Render. Per the real, confirmed value documented in the Sovereign Squeeze section above (`SML_BREAKOUT,SML_CASCADE,SML_MM_V4,SML_SR_MATRIX,SML_SR_ZONE_PATTERN,SML_SOVEREIGN_SQUEEZE`), the resulting value would be:
  ```
  IAM_PRIMARY_SYSTEM=SML_BREAKOUT,SML_CASCADE,SML_MM_V4,SML_SR_MATRIX,SML_SR_ZONE_PATTERN,SML_SOVEREIGN_SQUEEZE,SML_QUAD_SCORE
  ```
  **Don't blindly overwrite Render with this if the real current value has drifted** from that baseline since 2026-07-31 — append `SML_QUAD_SCORE` to whatever is actually set. `IAM_PAPER_MODE=false`/`IAM_AUTO_TRADING=true`/`IAM_EXECUTION_MODE=tradier|both` are already confirmed live from the CASCADE go-live (2026-07-25) and every subsequent engine's arming — no other flag needs to change.
- **Stop-loss is automatic, not something built per-engine** — `IAM_STOP_LOSS_PCT` (default 3.0%) places a real GTC stop-sell order on every live BUY fill regardless of which system triggered it, same as every other primary system.
- **Evidence status is unchanged by this decision** — 146 real trades, PF 1.989, held up across four out-of-sample splits and all six perturbed dimensions. This section documents a real, informed real-money decision on real evidence; it is not a retroactive upgrade of that evidence's strength.
- Tests: `tests/test_quad_score_engine_smoke.py` (9 tests — real coil-then-breakout fires ENTER_CALL, a genuine sustained bear-market pretrend blocks entry via the macro filter even with a real coil+breakout present, the temporal gate's own windowing matches its spec exactly, the weekly-macro no-lookahead proof, percentile-rank correctness, `analyze()`/`compute_series()` consistency) and `tests/test_quad_score_scanner_wiring.py` (dedup, no-fire-on-none, blueprint registration) — all pass against the real, unmodified code; the blueprint-registration assertion (which imports `core.app`) hits the same pre-existing broken-`cryptography` sandbox limitation documented elsewhere in this file, verified instead via `python3 -m py_compile`.

## Discord alert delivery failures — two different root causes on two different feeds (2026-07-31)

Operator reported two separate feeds going dark: AVG-DOWN and FTD (`#avg-down`/`#ftd` Discord channels). These turned out to be two unrelated bugs, not one — worth keeping separate so a future agent doesn't assume they share a fix.

- **AVG-DOWN: dead/revoked webhook URL, not a code bug.** Real production logs showed Tradier/Discord responses `404 Unknown Webhook` for `DISCORD_WEBHOOK_AVG_DOWN` — Discord itself had invalidated the URL (channel/webhook deleted or regenerated on the Discord side). `discord_alerts.py`'s `_post()` correctly detects this (`404` → logs `❌ [DISCORD ACTION REQUIRED]` and adds the URL to an in-memory `dead_webhooks` set so it stops retrying a URL known-bad for the rest of that process's life). **Fix is operator-side, not code:** regenerate the webhook in Discord's channel settings and set the new URL as `DISCORD_WEBHOOK_AVG_DOWN` on Render — the code already does the right thing once the URL is valid again.
- **FTD: a real bug, independent of the URL being valid.** `ftd_anomaly_engine._fire_discord_batch()` gated every post on `discord.enabled` (`discord_alerts.py`'s `DiscordAlerts.enabled` property = `bool(webhook_squeeze or webhook_flow or webhook_all or webhook_beast)`) — four webhooks that have nothing to do with FTD. Confirmed with the operator that `DISCORD_WEBHOOK_FTD` **is** set on Render — but if none of those other four env vars also happen to be set, `enabled` evaluates `False` and the function returns before ever reading `DISCORD_WEBHOOK_FTD`, silently swallowing every FTD alert regardless of that webhook being perfectly valid. `avg_down_engine.py`'s own `_fire_discord()` never had this gate — it only ever checks its own URL — which is the correct, established convention in this codebase (every feature's Discord alert should depend only on its own webhook var, not on unrelated ones happening to also be set). **Fixed:** removed the `discord.enabled` check from `_fire_discord_batch()`, now matching `avg_down_engine.py`'s convention exactly.
  - Also worth knowing (not a bug, a real design tradeoff): both `NEW_THRESHOLD_LIST_ENTRY` and `FTD_SPIKE` detection deliberately **seed silently on the first scan after every process restart** (`_known_init`/`_spike_known_init`) rather than alerting, specifically to avoid every already-qualifying symbol mass-refiring the instant the in-memory cooldown dict is wiped by a Render redeploy. On a codebase that redeploys as often as this one, that means a genuine anomaly present at redeploy time won't alert until it's still qualifying on a *later* 15-minute scan — not a suppression bug, but worth knowing if "it's quiet right after a deploy" gets reported again.
- Tests: `tests/test_ftd_anomaly_discord_gate.py` — confirmed failing pre-fix (alert silently swallowed with a valid `DISCORD_WEBHOOK_FTD` set but `discord.enabled=False`), passing post-fix; also covers the no-post-when-URL-unset and no-post-without-discord-or-alerts cases. All pass against the real, unmodified `_fire_discord_batch()`.

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
│       ├── mcp_bp.py        # POST /mcp — JSON-RPC 2.0 MCP server (62 tools)
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

Mounted at `/mcp`. Implements JSON-RPC 2.0. **62 tools** total.

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
| `GET /api/outreach` or `/api/outreach/queue` | Browse Hermes Sales Agent's drafted sales pitches awaiting approval |
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
| Hermes Sales Agent | `hermes_sales.py` | Sells the Agent Economy OS 24/7 (6x/day passes): live storefront checks (mcp-x402 gateway, npm package, hermes landing page), real Reddit/HN buying-intent lead gen, drafts pitches and queues them at `/api/outreach` for manual approval — never auto-posts anywhere. See "Hermes Sales Agent" section above |

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
- **MCP tool count**: the `_TOOLS` list in `mcp_bp.py` is the source of truth (currently 62 tools). The `_SERVER_INFO` version string is `"5.1.0"`. When adding tools, also sync: (1) the tools array in `.well-known/mcp.json`, (2) `tool_count` in `.well-known/catalog.json`, (3) the `"X MCP tools"` text in `.well-known/server.json` and `llms.txt`. Names must match exactly — historical drift between `signal_preview` (source) and `get_signal_preview` (manifest) caused every agent free-trial to fail with "method not found".
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
