# ScriptMaster DeltaForge™

> **Trade the Delta. Catch the Explosion.**

The flagship convexity-trading system from Script Master Labs. DeltaForge hunts
explosive breakouts, buys them through the **0.32–0.40 delta window** — enough
delta to participate, cheap enough to keep the convexity — and compounds
aggressively behind hard, code-enforced risk walls.

Aggressive is the strategy. Disciplined is the architecture. **Non-custodial is
the law**: DeltaForge never touches your money, never holds your keys, and
never places an order on your behalf. It signals; *you* (or your machine, with
your keys) execute.

---

## 1. What DeltaForge is

| Layer | Component | Where |
|---|---|---|
| Chart engine | Pine v6 flagship strategy (signals, visuals, alerts, aggression control, webhook bridge) | `indicators/ScriptMaster_DeltaForge_Flagship_v6.pine` (v2.1) |
| Signal API | Same engine server-side on real Tradier 15-min bars | `GET /api/deltaforge/signal/<symbol>` |
| Contract selector | 0.32–0.40 Δ contracts ranked by convexity-per-dollar | `GET /api/delta-explosion/<symbol>` |
| BYOK execution | Python client with risk engine + Tradier/Robinhood submission | `sdk/deltaforge_client.py` |
| Live feed | `DELTAFORGE_SIGNAL` events on the SSE stream | `GET /api/events` |

## 2. Framework grounding (the Nobel column)

Every mechanism in DeltaForge maps to published economics — not as decoration,
but as the reason each rule exists:

- **Prospect Theory — Kahneman & Tversky.** Humans overweight losses and cut
  winners early. DeltaForge inverts the bias structurally: max loss per trade
  is the option premium (hard-capped at a % of equity), targets are R-multiples
  (default 2R), and the breakeven-arming rule removes the "give it all back"
  failure mode instead of relying on willpower.
- **Modern Portfolio Theory / CAPM — Markowitz & Sharpe.** Position sizing is
  fixed-fraction of equity, position count is capped, and every trade's risk
  contribution is identical by construction — the compounding curve comes from
  hit-rate × convexity, not from bet-size roulette.
- **Asset pricing & microstructure — Fama, Shiller, Hansen.** Markets are
  mostly efficient, so DeltaForge only acts in the inefficient tail: regime
  filter (Kaufman Efficiency Ratio) rejects chop, and the contract ranker
  penalizes wide spreads and dead order books — microstructure edges you can
  actually capture.
- **Asymmetric information — Akerlof, Spence, Stiglitz.** A breakout without
  volume is noise; a breakout with a volume thrust means someone is paying up
  to be early. The volume-ratio term in the convexity score is an informed-flow
  detector.
- **Mental accounting — Thaler.** The daily loss bucket, consecutive-loss
  circuit breaker, and cooldown are hard accounts the code enforces so the
  human never has to argue with themselves at 3:47pm.

## 3. The Delta-Convexity logic

1. **Explosion detection** (per symbol, 15-min bars): breakout of the prior
   20-bar channel + volatility spike + momentum thrust (short-term momentum
   leading the 10-bar move) + behavioral distortion (position in channel) +
   volume-weighted convexity z-score above threshold + trending regime
   (ER ≥ 0.30). All thresholds identical to the Pine flagship.
2. **Contract selection**: calls (long) or puts (short) with |delta| in
   **[0.32, 0.40]**, 5–45 DTE, ranked by
   `explosion_score = (gamma / mid) / (1 + 10 × spread%)` — raw convexity per
   premium dollar, marked down for execution cost. No bid or no OI+volume =
   excluded. Every number is a real Tradier greek; nothing is estimated.
3. **Risk rules** (SDK-enforced, client-side):
   - Risk per trade = full premium, capped at `max_risk_pct` of equity (default 1.5%).
   - Daily loss limit (default 4% of equity) → trading halts for the day.
   - Circuit breaker: 3 consecutive losses → done for the day.
   - Max 3 open positions; 15-minute per-symbol cooldown.
   - Kill switch: `DELTAFORGE_KILL_SWITCH=true` halts everything instantly.
   - Paper mode is the default; live requires `paper=False` **and**
     `DELTAFORGE_ARM_LIVE=true`.

"Double it and double that" is the goal of the *compounding structure* —
fixed-fraction sizing on positive-expectancy convexity — not a promise. No
system wins every trade, and DeltaForge is engineered on that assumption.

## 4. API specification

Base: `https://squeezeos-api.onrender.com` · Auth: `X-DeltaForge-Key` header
(omit for free scout tier).

| Endpoint | Method | Tier | Returns |
|---|---|---|---|
| `/api/deltaforge` | GET | public | Product overview + configuration status |
| `/api/deltaforge/signal/<symbol>?aggression=0.85` | GET | scout/operator/elite | Signal (see below) |
| `/api/delta-explosion/<symbol>?direction=long\|short&delta_min=0.32&delta_max=0.40&dte_min=5&dte_max=45` | GET | public | Ranked explosion-band contracts |
| `/api/deltaforge/key/validate` | POST `{api_key}` | public | `{valid, tier}` |
| `/api/deltaforge/stripe/webhook` | POST | Stripe | Key issuance/revocation |
| `/api/events` | GET (SSE) | public | Real-time `DELTAFORGE_SIGNAL` events |

**Signal response by tier** — scout: direction + distortion + Δ-score +
regime; operator: + full metrics + the ranked contract; elite: + BYOK order
payloads (Tradier params + Robinhood kwargs, `quantity: null` — sizing happens
client-side because the server never knows your equity).

**Real-time**: signals broadcast on the existing SSE stream (`/api/events`) as
`DELTAFORGE_SIGNAL` events. Native WebSocket is not offered on the current
gunicorn deployment — SSE is the supported push channel today; a WS gateway
(via Ghost Layer, which already runs WebSockets) is the documented upgrade path.

**Errors are real**: 503 without `TRADIER_API_KEY`, 502 with insufficient
bars, 404 when no contract fits the band. Nothing is ever fabricated.

## 5. BYOK Python client

`sdk/deltaforge_client.py` — requests-only (robin_stocks optional).

```python
from deltaforge_client import DeltaForgeClient, TradierBroker, RiskEngine

client = DeltaForgeClient(df_key="df_...")            # or founder key
broker = TradierBroker(token="YOUR-TOKEN", account_id="YOUR-ACCT", sandbox=True)
risk   = RiskEngine(max_risk_pct=1.5, daily_loss_limit_pct=4.0)

print(client.run_once("NVDA", broker=broker, risk=risk))   # paper by default
```

Robinhood: `pip install robin_stocks`, log in yourself, pass
`RobinhoodBroker()`. Your credentials never pass through DeltaForge code.

## 6. TradingView

`indicators/ScriptMaster_DeltaForge_Flagship_v6.pine` (v2.1) — the same engine
as a Pine v6 strategy: aggression control, regime + HTF filters, ATR risk
engine with breakeven, signal shapes, alerts, desk dashboard, and a webhook
bridge that feeds the SqueezeOS paper executor
(`system: "SML_DELTAFORGE"` → `/api/webhooks/tradingview`).

## 7. Monetization

| Tier | Price | Gets |
|---|---|---|
| **Scout** | Free | Signal direction + core metrics, SSE feed, Pine script |
| **Operator** | $49/mo | Full metrics + ranked 0.32–0.40Δ contract per signal |
| **Elite** | $149/mo | Everything + BYOK order payloads + SDK support |
| **Founder** | Permanent free Elite | `DELTAFORGE_OWNER_KEY` — independent of Stripe/Redis, can never be locked out |

Pricing ladder matches the existing SML catalog (Trade Desk $19/$49, CASCADE
$149, AEO $49/$149). **Stripe products are not yet created** — the webhook and
key machinery are live code but no-op until `DELTAFORGE_STRIPE_OPERATOR_PRICE_ID`,
`DELTAFORGE_STRIPE_ELITE_PRICE_ID`, and `DELTAFORGE_STRIPE_WEBHOOK_SECRET` are
set on Render (same "not yet configured" pattern as Trade Desk). x402 pay-per-
call for AI agents is a natural add-on via the existing 402Proof rail.

## 8. Growth plan

1. **TradingView funnel** — publish the Pine flagship publicly; the dashboard
   and signal shapes are the ad. Script description links to the free scout API.
2. **Shareable signal cards** — every scout response is screenshot-ready
   (direction, Δ-score in σ, regime); the free tier is deliberately shareable.
3. **Agent economy** — expose `deltaforge_signal` as an x402-metered MCP tool
   (52-tool server already discoverable via `.well-known/`); AI agents pay
   RLUSD per call, LEVIATHAN lists it as an ACP offering.
4. **Proof-of-work marketing** — pipe `DELTAFORGE_SIGNAL` events into the
   marketing activity feed; the self-advertising loop (AEO) cites live signals
   instead of claims.
5. **Founder story** — build-in-public thread format: signal screenshot →
   contract → R-multiple outcome, win or lose. Losses posted too; the
   discipline *is* the brand.

## 9. History (do not repeat)

v1.1 (draft) / v1.2 / v2.0 had a mathematically impossible entry gate
(20-bar-high breakout + negative 10-bar momentum) — zero trades ever, fixed in
PR #351 (v2.1 / v1.3). Never copy DeltaForge code from old chat logs; the repo
is the source of truth.
