# 402proof — The Compliance Receipt Layer for x402 Payments

**Every AI agent micropayment, fully receipted. Risk-scored. Audit-ready.**

---

## The Problem: Your x402 Payments Have No Compliance Trail

The x402 protocol is elegant: an agent pays, your API responds. But when your finance team asks for an audit export, when a regulator asks who paid for what, or when you need to prove GENIUS Act compliance — a raw XRPL transaction hash is not an answer.

Right now, most x402 implementations:

- Have no record of who paid (agent wallet only, no domain or identity)
- Cannot export receipts in CSV or JSON for accounting systems
- Have no risk scoring on paying agents — blocked wallets can keep paying
- Have no sanctions-check field to satisfy compliance review
- Have no loyalty or access control layer — every agent is treated identically

The result: you are running a payment rail with no paper trail.

---

## The Solution: 402proof

402proof is a production Go server that drops in front of any x402-gated endpoint and adds the compliance layer you are missing.

Every settled payment produces a structured receipt with:

- On-chain XRPL transaction hash (verifiable by anyone)
- Agent wallet address and self-reported domain
- Endpoint path, merchant ID, amount, and asset
- Risk level (`LOW` / `MEDIUM` / `HIGH`) from the agent passport
- Sanctions check field (extensible to OFAC/SDN)
- Settlement timestamp in RFC3339

Receipts are available as JSON download, CSV download, and bulk admin CSV export. You can point your accounting system at `/v1/admin/receipts` and pull everything in one shot.

402proof also adds merchant registration, endpoint pricing, access policies, loyalty tiers, and an agent firewall — so you get a complete payments infrastructure layer, not just a receipt stamp.

---

## Integration: 3 Lines to Wire Up Your x402 Server

Point your existing x402 middleware at 402proof's three-step flow:

```python
# 1. Before payment: get an invoice tied to your endpoint
invoice  = requests.post("https://your-402proof.onrender.com/v1/invoice",
                         json={"endpoint_id": ENDPOINT_ID}).json()

# 2. After agent pays on XRPL: verify and collect access token + receipt
result   = requests.post("https://your-402proof.onrender.com/v1/verify",
                         json={"invoice_id": invoice["invoice_id"],
                               "tx_hash": TX_HASH, "agent_wallet": AGENT_WALLET}).json()

# 3. On every protected request: validate the token in your middleware
assert requests.post("https://your-402proof.onrender.com/v1/token/verify",
                     json={"token": result["access_token"],
                           "endpoint_id": ENDPOINT_ID}).json()["status"] == "VALID"
```

That is the full integration. Your existing XRPL payment flow does not change. 402proof reads the ledger, never writes to it from your side.

---

## Deploy

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/timwal78/squeezeos)

Set three secrets in the Render dashboard after deploy:

| Secret | How to generate |
|---|---|
| `GATEWAY_XRPL_ADDRESS` | Your 402proof hot wallet address (public key only) |
| `TOKEN_SECRET` | `openssl rand -hex 32` |
| `ADMIN_TOKEN` | `openssl rand -hex 32` |

The service starts on port 9090. Health check: `GET /health`.

---

## X/Twitter Thread

---

**Post 1 — Hook**

your x402 API is making money

but can you tell an auditor who paid, how much, from which wallet, at what risk level, with a downloadable receipt?

introducing 402proof — the compliance layer for x402 RLUSD micropayments on XRPL

---

**Post 2 — What It Does**

402proof sits between your API and the internet

every agent payment generates a signed receipt:
- on-chain tx hash
- agent wallet + domain
- risk score (LOW / MEDIUM / HIGH)
- sanctions check field
- downloadable JSON + CSV

3 lines of code to integrate with any x402 server

---

**Post 3 — Compliance Angle**

the GENIUS Act is coming

stablecoin payments need audit trails, risk scoring, and sanctions screening

402proof bakes all three into every RLUSD micropayment on XRP Ledger

your receipts are already in the format compliance teams expect

---

**Post 4 — Deploy CTA**

deploy to Render in 60 seconds

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/timwal78/squeezeos)

set 3 env vars. done.

open source, MIT license, zero custody of your keys

github.com/timwal78/squeezeos
