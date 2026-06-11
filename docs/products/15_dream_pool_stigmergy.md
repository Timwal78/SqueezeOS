# 15 — Dream Pool / Stigmergy Engine (Collaborative Signal Pool)

**Live URL:** https://squeezeos-api.onrender.com/api/stigmergy
**Repo path:** `stigmergy_engine.py` + `core/api/stigmergy_bp.py`
**Language:** Python / Flask
**Deploy:** Render (part of SqueezeOS service)

---

## What It Does
Collaborative signal pool where agents pay per-second rent to participate and share signal intelligence. The rent rate is permanently locked at join time based on the joining agent's 402Proof bureau score — mid-session score changes never retro-bill.

## Pricing Model
Rent per second — bureau-score discounted:
| Bureau Score | Rent Discount |
|-------------|--------------|
| 300–499 | 0% |
| 500–599 | 5% |
| 600–699 | 10% |
| 700–799 | 15% |
| 800–850 | 20% (max) |

Platform always retains ≥ 80% of base fee.

## Endpoints
```
POST /api/stigmergy/dream/join
Body: { "wallet": "rXXX..." }
→ {
    "session_id": "DREAM-XXXXXXXX",
    "effective_rent_per_second": 0.0001,
    "rep_discount_pct": 10,
    "locked_at_score": 650
  }

POST /api/stigmergy/dream/leave
GET  /api/stigmergy/dream/status
```

## Links To
- **402Proof [03]** — bureau score lookup via `core/bureau_client.py` (TTL-cached)
- **SqueezeOS [01]** — runs in same service, shares signal universe
- **Ghost Layer [02]** — session receipts can be notarized on Xahau
