# 16 — Futures Market (On-Chain Futures with Bureau Discounts)

**Live URL:** https://squeezeos-api.onrender.com/api/futures
**Repo path:** `core/api/futures_bp.py`
**Language:** Python / Flask
**Deploy:** Render (part of SqueezeOS service)

---

## What It Does
On-chain futures market with FICO-style fee reduction. Settlement fees are discounted based on the winner's 402Proof bureau score — higher score = lower platform fee retained. Every settlement proof exposes the full discount calculation for transparency.

## Fee Discount by Bureau Score
| Score | Platform Fee Reduction |
|-------|----------------------|
| 300–499 | 0% |
| 500–599 | small reduction |
| 600–849 | proportional reduction |
| 800–850 | maximum reduction |

## Settlement Proof
```json
{
  "platform_fee_pct_base": 2.0,
  "platform_fee_pct_used": 1.6,
  "winner_rep_score": 680,
  "winner_rep_discount": 0.4
}
```

## Endpoints
```
POST /api/futures/settle     → settle future, apply bureau discount
GET  /api/futures/active     → list active futures
POST /api/futures/create     → create new future
```

## Links To
- **402Proof [03]** — bureau score for winner's fee discount (via `core/bureau_client.py`)
- **SqueezeOS [01]** — runs in same service
- **Ghost Layer [02]** — execution and escrow infrastructure
