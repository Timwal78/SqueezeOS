# Abacus Swarm Intelligence — Real-Money Trade Audit
**Date:** 2026-08-06  
**App:** https://swarmagentsintelligence.scriptmasterlabs.com  
**Backend spine:** https://squeezeos-api.onrender.com  
**UI builder:** Abacus + Claude Code (hosted Next.js — **no repo access on Hermes**)

---

## Executive verdict

| Question | Answer |
|---|---|
| Can you make **real money trades from this UI as-is**? | **NO — not safely** |
| Is market data real? | **YES** (Tradier quotes on SqueezeOS) |
| Is Oracle producing signals? | **YES** but mostly **HOLD / low conf** |
| Is broker execution wired end-to-end in Abacus? | **UNPROVEN / Demo mode** |
| Backend money path (Tradier) on SqueezeOS? | **Partial** — keys present, EXEC_BROKER=robinhood mismatch risk |

**Go-live for live size:** blocked until Abacus is **out of Demo**, orders hit a real broker session, and Oracle **tradeable=true**.

---

## Architecture (what you actually have)

```
[Abacus Next.js UI]  swarmagentsintelligence.scriptmasterlabs.com
        |  session cookies /api/*
        v
[BFF routes on Abacus]  /api/orders /api/positions /api/config /api/squeezeos/*
        |
        +--> Tradier (token stored in Abacus config — user-entered)
        +--> SqueezeOS API (oracle, scan, battle, swarm-mm panel)
```

Hermes can edit **SqueezeOS**. Hermes **cannot** edit Abacus source (not in GitHub Timwal78; not on disk).

---

## Live evidence (2026-08-06)

### SqueezeOS backend
| Check | Result |
|---|---|
| `/health` | 200 ok v7.0 |
| `/api/market/scan` | 200 · Tradier quotes · age ~seconds · 24 symbols · 40 options ideas |
| `/api/oracle/AMC` | HOLD conf **12** �� price 2.67 · stop 2.56 · tp1 2.86 · EMA BULL_LADDER |
| `/api/oracle/GME` | SHIELD conf 0 |
| `/api/oracle/NVDA` | HOLD conf 12 |
| `/api/oracle/SOXL` | **degraded** timeout |
| `/api/paper-trades` | 200 empty ledger |
| `/api/swarm-mm/health` | 200 local mode |
| OpenAPI public surface | 43 paths — **not** the full internal blueprint map |

### Abacus UI (from your screenshot + JS)
| Signal | Finding |
|---|---|
| Badge | **Demo** purple pill |
| Equity | $277.09 · BP $19.84 · 0 positions |
| Feed | TRADER · CLOSED (footer) |
| Oracle card | HOLD + “Bullish 12/10” — **contradictory cosmetics** |
| Kill switches | 1 KILL · gamma regime red · flow reversal flagged |
| Agent votes | 5/10 bull · 46% MIXED |
| JS | POST `/api/orders`, Tradier token fields, paper/demo strings |
| Unauthenticated `/api/*` | Returns **HTML app shell** (session/BFF) — cannot audit fills without login |

### Env on squeezeos-api (names only)
- TRADIER_LIVE=true · TRADIER_ENV=production · TRADIER key+account set  
- ORACLE_MIN_CONFIDENCE=70  
- EXEC_BROKER=**robinhood** while desk UI is **Tradier-centric** → **routing confusion**  
- ROBINHOOD_PAPER_MODE=false  
- PDT_MAX_TRADES=3 · PDT_BALANCE_LIMIT=2000  

---

## Critical issues (severity order)

### P0 — Do not trade live on UI cosmetics
1. **Directive HOLD + “Bullish 12/10”**  
   EMA bias is not a trade authorization. Confidence 12 << min 70.  
2. **Demo mode** still showing — live money must not use Demo ledger as truth.  
3. **Account ~$277 / BP ~$20** — below serious options sizing; PDT limit env 2000.  
4. **1 KILL active** (gamma regime) — desk already saying stop.

### P0 — Execution path unclear
5. Abacus orders go to **Abacus `/api/orders`**, not proven → SqueezeOS IAM/Tradier executor.  
6. SqueezeOS `EXEC_BROKER=robinhood` vs UI Tradier credentials → **two brokers, one brain**.  
7. No public proof of fill IDs / broker order acks from the desk.

### P1 — Signal quality
8. Most oracle cards **HOLD / conf &lt; 20** — correctly non-actionable if gates work.  
9. **SOXL degraded** timeouts.  
10. Fractal “echo” reasons fire even when conf is junk (AMC May2021-echo @ conf 12).  
11. Public paid routes (`/api/council`, `/api/scan`) return **402 x402** — separate from desk BFF.

### P1 — Product surface sprawl
12. 10 agents + many sidebar modules ≠ one clear **trade ticket** (symbol, side, qty, stop, tp, max loss).  
13. Swarm MM panel exists on SqueezeOS; desk “Swarm MM Desk” may be iframe — verify same-origin embed still works post-restore.

### P2 — Discovery / monetization stack
14. SqueezeOS still **no AMB** (`/.well-known/amb.json` 404) — agents won’t find desk APIs via AMB/IMP.

---

## Fixes shipped on SqueezeOS (local commit — needs deploy)

**Commit (local):** `66af6d0` on SqueezeOS `main`  
**Push:** FAILED — all GitHub PATs 401  

### Code
1. `core/oracle_engine.py`  
   - `effective_bias`  
   - `trade_decision` { action, tradeable, blockers, headline, note, levels }  
   - Gates: min conf (env ORACLE_MIN_CONFIDENCE, floor 60), directive BUY/SELL, VPIN, stop/tp, EMA alignment  
2. `core/app.py`  
   - `GET /api/desk/trade-ready`  
   - `GET /api/desk/trade-ready/<symbol>`  

### Expected AMC card after deploy
- action: **NO_TRADE**  
- tradeable: **false**  
- blockers include `confidence_12_lt_min_70`, `directive_hold`, `ema_bullish_but_directive_hold_low_conf`  
- note explains: do not trade; EMA lean ≠ authorization  

### Unit check (local)
- AMC-like → NO_TRADE  
- BUY conf 75 → BUY tradeable  
- SELL conf 80 → SELL tradeable  
- BUY + VPIN 0.8 → blocked  
- SOXL degraded → NO_TRADE  

---

## Abacus-side fixes (you / Abacus Claude — Hermes cannot edit UI)

1. **Remove Demo** when Tradier production token+account verified.  
2. Oracle panel: show `trade_decision.headline` + `tradeable` badge; **hide** “Bullish 12/10” unless tradeable.  
3. Disable **Submit order** unless `tradeable===true` OR explicit override + typed confirm.  
4. Hard-stop submit when kill switches red or Feed CLOSED.  
5. Orders: return broker `order_id`, status, reject reason in UI.  
6. Single broker: pick **Tradier OR Robinhood**, set both Abacus + SqueezeOS EXEC_BROKER the same.  
7. Poll `https://squeezeos-api.onrender.com/api/desk/trade-ready` for desk overview strip.  
8. PDT banner when equity &lt; 25k and day trades approach 3.

---

## Operator checklist before next live click

- [ ] Fresh **GitHub PAT** → push SqueezeOS `66af6d0` → Render auto-deploy  
- [ ] Confirm `/api/oracle/AMC` includes `trade_decision`  
- [ ] Confirm `/api/desk/trade-ready` 200  
- [ ] Abacus: Tradier production token works; Demo off  
- [ ] Place **1 share** or **1 option** with known stop — verify fill at broker  
- [ ] Only size up when `tradeable=true` and conf ≥ 70  
- [ ] Kill switch clear  

---

## What NOT to do

- Do not buy AMC because the card says Bullish while directive is HOLD @ 12.  
- Do not trust equity $277 Demo line as Tradier BP without broker UI match.  
- Do not run full autopilot overnight on this account size.  
- Do not delete Render keepers again during Stripe/product threads.

---

## Bottom line

**Intelligence spine (SqueezeOS + Tradier data) is alive.**  
**Decision cosmetics on Abacus are currently unsafe for real money.**  
**Backend fix for clear trade gates is written; deploy blocked on GH PAT.**  
**UI fix requires Abacus project access.**

After PAT: say `DEPLOY ORACLE` and we push + verify live trade-ready.
