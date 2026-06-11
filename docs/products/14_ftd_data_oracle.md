# 14 — FTD Data Oracle (SEC Reg SHO Data Feed)

**Live URL:** https://squeezeos-api.onrender.com/api/ftd
**Repo path:** `core/ftd_data.py` + `core/api/ftd_bp.py`
**Language:** Python / Flask
**Deploy:** Render (part of SqueezeOS service)

---

## What It Does
Per-call x402-gated data product surfacing two public SEC regulatory datasets:
1. **Fails-To-Deliver biweekly reports** (sec.gov)
2. **Reg SHO Threshold Securities List** (updated every 6 hours)

180-day rolling window per symbol. Thread-safe in-memory time series. Compliance-safe descriptive data — not a trade signal, not a squeeze prediction. Public regulatory data surfaced as a research feed.

## Endpoints

| Endpoint | Price | Description |
|----------|-------|-------------|
| GET /api/ftd/info | free | Tier discovery + compliance posture |
| GET /api/ftd/threshold-list | $0.02 USDC | Current SEC Reg SHO threshold securities |
| GET /api/ftd/series/{symbol} | $0.02 USDC | 180-day FTD time series |
| GET /api/ftd/ratio/{symbol} | $0.03 USDC | Latest record + percentile rank |
| GET /api/ftd/etf-basket/{etf} | $0.05 USDC | ETF constituents by FTD notional (XRT/IWM/IJR/KRE) |
| GET /api/ftd/cycle/{symbol} | $0.05 USDC | Settlement-cycle bundle (T+21/T+35) |

## Data Architecture
```
core/ftd_data.py
  FTDDataStore         — thread-safe, 180-day rolling window
  _poll_ftd()          — daily SEC ZIP fetcher
  _poll_threshold()    — 6h Reg SHO scraper
  ETF_BASKETS          — XRT, IWM, IJR, KRE constituent maps
  cycle_summary_for()  — descriptive bundle for /cycle
```

## Compliance
T+21/T+35 markers = calendar arithmetic on public settlement dates.
Includes explicit Reg SHO 204 bona-fide market-maker exemption notes.
No "buy/sell/squeeze imminent" language anywhere — pure descriptive data.

## Links To
- **SqueezeOS [01]** — runs in same Flask service, uses x402_flask.py guard
- **402Proof [03]** — x402 payment verification
- **Agent Credit Marketplace [18]** — FTD data can be resold via marketplace
