# 402Proof — x402 Payment Firewall + Agent Credit Bureau
**Date:** 2026-06-11  
**Status:** LIVE — `https://four02proof.onrender.com`  
**Language:** Go (chi v5 router)  
**Repo path:** `SqueezeOS/402proof/`

> **TL;DR:** 402Proof is the payment compliance layer for the SML stack. It issues invoices, verifies XRPL/Xahau/Base payments, scores agents like a credit bureau (FICO-style 300–850), issues JWT access tokens, and gates protected endpoints. Every x402 transaction in the ecosystem flows through it.

---

## Verified Live Routes (tested 2026-06-11)

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/health` | None | Status + active payment networks |
| GET | `/v1/stats` | None | Total calls, receipts, unique agents |
| GET | `/v1/leaderboard` | None | All registered endpoints |
| POST | `/v1/merchant/register` | None | Register merchant, receive API key |
| POST | `/v1/endpoint` | API key | Create paywall endpoint (RLUSD or XRP) |
| GET | `/v1/endpoint` | API key | List merchant endpoints |
| PUT | `/v1/policy/{id}` | API key | Set firewall policy for endpoint |
| POST | `/v1/invoice` | None | Generate payment invoice |
| POST | `/v1/verify` | None | Verify tx hash → issue JWT access token |
| POST | `/v1/token/verify` | None | Validate JWT access token |
| GET | `/v1/receipt/{id}` | None | Compliance receipt (no access token) |
| GET | `/v1/receipt/{id}/json` | None | Receipt download as JSON |
| GET | `/v1/receipt/{id}/csv` | None | Receipt download as CSV |
| GET | `/v1/loyalty/{wallet}` | None | Loyalty tier + free credit balance |
| POST | `/v1/loyalty/redeem` | None | Redeem free credit for access token |
| GET | `/v1/agent/{wallet}` | None | Full agent passport |
| GET | `/v1/bureau/score/{wallet}` | None | Public credit score (teaser) |
| GET | `/v1/bureau/report/{wallet}` | Payment token | Full credit report (0.01 RLUSD) |
| GET | `/v1/bureau/verify/{wallet}` | Payment token | Boolean threshold check (0.005 RLUSD) |
| GET | `/v1/bureau/attest/{wallet}` | Payment token | Portable attestation JWT (0.01 RLUSD) |
| POST | `/v1/bureau/verify-attest` | None | Verify attestation JWT (third-party) |
| GET/POST | `/mcp` | None | MCP JSON-RPC 2.0 (11 tools) |
| GET | `/v1/admin/*` | Admin token | Receipts, agents, block/unblock, KYB, flush |

## Payment Rails (from env config)

| Rail | Network | Currency | Gateway |
|---|---|---|---|
| Primary | XRPL | RLUSD | `rUJhaK2ibfTFVdAn8m9jMCcJQ1xo6FmNPZ` |
| Secondary | Xahau | RLUSD | `rNduuviQ3CCvHqWUTjJDD82Ko2tjqFGs3q` |
| Optional | Base (EVM) | USDC | Set via `GHOST_LAYER_ETH_ADDRESS` env |

## x402 Flow (3 steps)

```
1. POST /v1/invoice   { endpoint_id }
   ← { invoice_id, pay_to, amount, memo_hex, expires_at, payment_options[] }

2. Send payment on XRPL/Xahau/Base with memo_hex embedded

3. POST /v1/verify    { invoice_id, tx_hash, agent_wallet }
   ← { access_token (JWT), receipt_id, loyalty_tier, free_credits }
   
   access_token → use in X-Payment-Token header on protected endpoint
```

## Agent Credit Bureau (FICO-style)

Score range: 300 (no history) → 850 (institutional tier).  
Factors: payment history, spend volume, call frequency, KYB tier, risk events, loyalty tier.  
Grades: A (750+), B (650–749), C (550–649), D (below 550).  
Attestation JWT: 24h TTL, portable, verifiable by third parties at `/v1/bureau/verify-attest`.

## Loyalty Tiers (automatic)

Bronze → Silver → Gold → Platinum → Diamond, based on cumulative RLUSD spend.  
Each tier unlocks free credits and reduced firewall friction.  
KYB (Know Your Bot) elevation available via admin: `basic` (-10 risk), `verified` (-20 risk).

## MCP Tools (11 verified in source)

`platform_stats` · `get_invoice` · `verify_payment` · `check_loyalty` · `get_compliance_receipt` · `get_agent_passport` · `bureau_public_score` · `bureau_full_report` · `bureau_verify_threshold` · `bureau_get_attestation` · `bureau_verify_attestation`

## Key Env Vars

| Var | Required | Notes |
|---|---|---|
| `GATEWAY_XRPL_ADDRESS` | YES | XRPL receiving wallet |
| `TOKEN_SECRET` | YES | JWT signing secret (openssl rand -hex 32) |
| `ADMIN_TOKEN` | YES | Admin endpoint auth |
| `GHOST_LAYER_ETH_ADDRESS` | NO | Enables USDC/Base rail |
| `XRPL_RPC_URL` | NO | Default: xrplcluster.com |
| `RLUSD_ISSUER` | NO | Default: rMxCKbEDwqr76QuheSUMdEGf4B9xJ8m5De |

## Known Issues (2026-06-11)
- `GET /mcp` returning 404 on live Render deployment — possible stale build. `POST /mcp` (JSON-RPC) likely affected. Trigger a manual redeploy on Render to resolve.
