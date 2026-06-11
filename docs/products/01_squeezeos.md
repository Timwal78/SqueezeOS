# 01 — SqueezeOS Signal Intelligence OS

**Live URL:** https://squeezeos-api.onrender.com
**Repo path:** `core/`
**Language:** Python / Flask
**Deploy:** Render (cloud, 24/7)

---

## What It Does
The flagship signal engine. Runs the full SML Sovereign Harmonic Matrix v8.0 across the entire live US market. Produces GOD MODE, TRIPLE_LOCK, and DUAL GRID LOCK signals. Hosts the AI Council multi-agent verdict system. Gates all premium endpoints behind x402 (USDC/Base + RLUSD/XRPL dual-rail).

## Signal Products

| Endpoint | Price | Signal |
|----------|-------|--------|
| POST /api/triple-lock | $0.25 RLUSD | TRIPLE_LOCK_BULL / BEAR — E1+E3+E4 across 3 dimensions |
| GET /api/triple-lock/demo | free | IWM preview |
| GET /api/beastmode?tf=1D | $0.10 | GOD_MODE + DUAL_GRID_LOCK — full market scan |
| GET /api/convergence/{symbol} | $0.05 | Per-symbol full matrix convergence |
| POST /api/council | $0.10 | AI Council multi-agent verdict |
| GET /api/scan | $0.05 | Squeeze universe scan |
| GET /api/options | $0.05 | Options intelligence |
| GET /api/iwm | $0.03 | IWM 0DTE playbook |
| GET /api/market/flow | $0.05 | Options flow — sweeps, blocks, OI |
| GET /api/market/whales | $0.05 | Whale heat map |

## Key Files
- `core/api/convergence_bp.py` — GOD MODE + DUAL GRID LOCK signal engine
- `core/api/triple_lock_bp.py` — TRIPLE_LOCK_VERDICT
- `core/api/premium_bp.py` — x402-gated premium endpoints
- `core/proprietary_ema_engine.py` — **PATENT PENDING — NEVER EXPOSE INTERNALS**
- `x402_flask.py` — x402 dual-rail guard decorator
- `data_providers.py` — Polygon + Alpaca + Tradier universe discovery

## Links To
- **402Proof [03]** — x402 payment verification (both rails)
- **Ghost Layer [02]** — fires GOD MODE → Tradier + Robinhood execution
- **Signal Loom/PNE [04]** — feeds signal quality upstream
- **Shadow Desk [05]** — dark pool data enrichment
- **Neural_OS Mobile [12]** — consumes SqueezeOS signals
- **Discord** — GOD_MODE + DUAL_GRID_LOCK alerts on 4H/Daily only
- **TradingView Script [13]** — Pine Script fires webhook → executor

## Signal Tier Hierarchy
TRIPLE_LOCK > GOD_MODE > DUAL_GRID_LOCK > HIGH_CONVERGENCE > CONVERGENCE > FRACTAL_LOCK > PARTIAL > NEUTRAL

## Mandatory Tickers
AMC, GME, IWM — always included regardless of universe discovery result

## Universe Discovery
100% live — Polygon grouped daily (ALL US stocks OHLCV) → Alpaca movers/actives → Tradier quotes. Zero hardcoded tickers beyond mandatory 3.

## x402 Discovery
`GET https://squeezeos-api.onrender.com/.well-known/x402` — lists all paid resources
CDP Bazaar facilitator: `https://x402.org/facilitator`
