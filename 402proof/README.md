# 402proof

**Payment compliance gateway for x402 RLUSD micropayments on the XRP Ledger.**

402proof sits between your x402-gated API and the outside world. It issues payment invoices, verifies RLUSD/XRP transactions on-chain, mints signed access tokens, and generates tamper-evident compliance receipts — so every AI-agent micropayment has a complete, auditable trail.

---

## Architecture

```
  API Client / AI Agent
         |
         |  POST /v1/invoice  (request invoice for endpoint)
         v
  +--------------------------------------------------------------+
  |                        402proof                              |
  |                                                              |
  |  +------------+   +------------+   +--------------------+   |
  |  |  Invoice   |   |  Verify    |   |  Receipt Engine    |   |
  |  |  Engine    +---> Engine     +---> JSON + CSV store   |   |
  |  +------------+   +-----+------+   +--------------------+   |
  |                         |                                    |
  |                   +-----v------+                             |
  |                   | XRPL RPC   |  on-chain verify            |
  |                   | (RLUSD/XRP)|  tx_hash lookup             |
  |                   +------------+                             |
  |                                                              |
  |  +--------------------------------------------------+        |
  |  |  Merchant Layer                                  |        |
  |  |  Registration · Endpoints · Policies · Firewall  |        |
  |  |  Loyalty · Passport · Admin · Email Notify       |        |
  |  +--------------------------------------------------+        |
  +--------------------------------------------------------------+
         |
         |  access_token + compliance receipt
         v
  Your Protected API / MCP Server
```

---

## Quick Deploy

### Render (one-click Docker)

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/timwal78/squeezeos)

After clicking deploy, set the three required secrets in the Render dashboard (see Environment Variables below). The service starts on port 9090.

### Docker Compose (local)

```yaml
version: "3.9"
services:
  402proof:
    build:
      context: .
      dockerfile: Dockerfile
    ports:
      - "9090:9090"
    environment:
      PORT: "9090"
      XRPL_RPC_URL: "https://xrplcluster.com"
      RLUSD_ISSUER: "rMxCKbEDwqr76QuheSUMdEGf4B9xJ8m5De"
      SERVER_URL: "http://localhost:9090"
      GATEWAY_XRPL_ADDRESS: "rYOUR_HOT_WALLET"
      TOKEN_SECRET: "generate_with_openssl_rand_hex_32"
      ADMIN_TOKEN: "generate_with_openssl_rand_hex_32"
```

```bash
docker compose up --build
```

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `PORT` | No | `9090` | HTTP port the server listens on |
| `XRPL_RPC_URL` | No | `https://xrplcluster.com` | XRPL full-history node RPC endpoint |
| `RLUSD_ISSUER` | No | `rMxCKbEDwqr76QuheSUMdEGf4B9xJ8m5De` | Official Ripple RLUSD issuer address |
| `SERVER_URL` | No | `http://localhost:9090` | Public base URL (used in badge embeds) |
| `GATEWAY_XRPL_ADDRESS` | **Yes** | — | Your 402proof hot wallet address (NOT your Xaman treasury). Receives payments. |
| `TOKEN_SECRET` | **Yes** | — | HMAC secret for signing access tokens. Generate: `openssl rand -hex 32` |
| `ADMIN_TOKEN` | **Yes** | — | Bearer token for `/v1/admin/*` routes. Generate: `openssl rand -hex 32` |
| `SMTP_HOST` | No | — | SMTP server hostname. Enables email receipts when set. |
| `SMTP_USER` | No | — | SMTP username / sender address |
| `SMTP_PASS` | No | — | SMTP password |

> Secrets (`GATEWAY_XRPL_ADDRESS`, `TOKEN_SECRET`, `ADMIN_TOKEN`) must be set in the Render dashboard. Never commit them to `render.yaml`.

---

## API Endpoints

### Health

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Returns `{"status":"ok","gateway":"<address>"}` |

### Public Stats

| Method | Path | Description |
|---|---|---|
| `GET` | `/v1/stats` | Aggregate payment statistics |
| `GET` | `/v1/leaderboard` | All registered endpoints (public) |

### Merchant Registration

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/v1/merchant/register` | None | Register a merchant; returns `api_key` |

**Request body:**
```json
{ "name": "Acme Corp", "email": "ops@acme.io" }
```

### Endpoint Management

Requires `X-API-Key: <your_api_key>` header (or `Authorization: Bearer <key>`).

| Method | Path | Description |
|---|---|---|
| `POST` | `/v1/endpoint/` | Register a paywalled endpoint (path, price, asset) |
| `GET` | `/v1/endpoint/` | List your registered endpoints |
| `PUT` | `/v1/policy/{endpointID}` | Set access policy (rate limits, allow/block rules) |
| `GET` | `/v1/policy/{endpointID}` | Get current policy for an endpoint |

### Core x402 Payment Flow

| Step | Method | Path | Description |
|---|---|---|---|
| 1 | `POST` | `/v1/invoice` | Generate a payment invoice |
| 2 | `POST` | `/v1/verify` | Verify on-chain payment; receive access token + receipt |
| 3 | `POST` | `/v1/token/verify` | Validate an access token on each protected request |

**POST /v1/invoice — request:**
```json
{ "endpoint_id": "<uuid>" }
```
**Response:** `invoice_id`, `pay_to` (gateway XRPL address), `amount`, `asset`, `network`, `memo_hex`, `expires_at`

**POST /v1/verify — request:**
```json
{
  "invoice_id":   "<uuid>",
  "tx_hash":      "<xrpl_tx_hash>",
  "agent_wallet": "rAgentXRPLAddress",
  "agent_domain": "myagent.example.com"
}
```
**Response:** `access_token`, `receipt_id`, `risk_level`, `settled_at`, `loyalty_tier`, `free_credits`, `credits_awarded`

**POST /v1/token/verify — request:**
```json
{ "token": "<jwt>", "endpoint_id": "<uuid>" }
```

### Receipts

| Method | Path | Description |
|---|---|---|
| `GET` | `/v1/receipt/{id}` | JSON receipt (access token redacted) |
| `GET` | `/v1/receipt/{id}/json` | Downloadable JSON attachment |
| `GET` | `/v1/receipt/{id}/csv` | Downloadable CSV attachment |

### Loyalty

| Method | Path | Description |
|---|---|---|
| `GET` | `/v1/loyalty/{wallet}` | Tier, credits, and progress for a wallet |
| `POST` | `/v1/loyalty/redeem` | Burn 1 free credit to receive an access token without a new payment |

### Agent Passport

| Method | Path | Description |
|---|---|---|
| `GET` | `/v1/agent/{wallet}` | Full agent record (spend history, tier, block status, risk score) |

### Badge Embeds

| Method | Path | Description |
|---|---|---|
| `GET` | `/v1/badge/{endpointID}` | Live HTML badge page for a verified endpoint |
| `GET` | `/badge/{endpointID}` | Shortlink redirect to the badge page |

### Admin (Bearer `ADMIN_TOKEN` required)

| Method | Path | Description |
|---|---|---|
| `GET` | `/v1/admin/receipts` | Bulk CSV export of up to 500 recent receipts |
| `GET` | `/v1/admin/stats` | Server-side aggregate stats |
| `POST` | `/v1/admin/agent/{wallet}/block` | Block a wallet with an optional reason |
| `DELETE` | `/v1/admin/agent/{wallet}/block` | Unblock a wallet |

---

## Receipt Format

Every verified payment produces a compliance receipt stored server-side and available as JSON or CSV.

### Fields

| Field | Type | Description |
|---|---|---|
| `receipt_id` | string (UUID) | Unique identifier for this receipt |
| `invoice_id` | string (UUID) | Invoice that was settled |
| `agent_wallet` | string | Paying agent's XRPL address |
| `agent_domain` | string | Optional domain the agent self-reported |
| `endpoint_id` | string (UUID) | Protected endpoint that was unlocked |
| `merchant_id` | string (UUID) | Merchant who owns the endpoint |
| `path` | string | Endpoint path (e.g. `/api/weather`) |
| `amount` | string | Payment amount (e.g. `"0.01"`) |
| `asset` | string | `RLUSD` or `XRP` |
| `tx_hash` | string | On-chain XRPL transaction hash |
| `settled_at` | RFC3339 timestamp | Time the payment was verified |
| `risk_level` | string | Passport risk score: `LOW`, `MEDIUM`, or `HIGH` |
| `sanctions_check` | string | `SKIPPED` (reserved for future OFAC/SDN integration) |

### CSV Header

```
receipt_id,invoice_id,agent_wallet,agent_domain,endpoint_id,merchant_id,path,amount,asset,tx_hash,settled_at,risk_level,sanctions_check
```

### Example JSON Receipt

```json
{
  "receipt_id": "a1b2c3d4-...",
  "invoice_id": "e5f6g7h8-...",
  "agent_wallet": "rAgentWalletXXXXXXXXXXXXXXXX",
  "agent_domain": "myagent.example.com",
  "endpoint_id": "i9j0k1l2-...",
  "merchant_id": "m3n4o5p6-...",
  "path": "/api/report",
  "amount": "0.10",
  "asset": "RLUSD",
  "tx_hash": "ABCDEF1234567890...",
  "settled_at": "2026-05-17T12:00:00Z",
  "risk_level": "LOW",
  "sanctions_check": "SKIPPED"
}
```

---

## Integration Example — MCP Server or API Gateway

The pattern is three steps: issue an invoice, verify the on-chain payment, then validate the access token on every subsequent request.

```python
import requests

PROOF_URL    = "https://your-402proof.onrender.com"
ENDPOINT_ID  = "your-endpoint-uuid"

# Step 1: issue an invoice before the agent makes its payment
invoice = requests.post(f"{PROOF_URL}/v1/invoice", json={
    "endpoint_id": ENDPOINT_ID,
}).json()
# invoice["memo_hex"] goes into MemoData on the XRPL payment transaction

# Step 2: after the agent pays on XRPL, verify and collect the access token
result = requests.post(f"{PROOF_URL}/v1/verify", json={
    "invoice_id":   invoice["invoice_id"],
    "tx_hash":      "XRPL_TX_HASH_HERE",
    "agent_wallet": "rMyAgentWallet",
    "agent_domain": "myagent.example.com",
}).json()

access_token = result["access_token"]
receipt_id   = result["receipt_id"]

# Step 3: in your API middleware, validate the token before serving content
check = requests.post(f"{PROOF_URL}/v1/token/verify", json={
    "token":       access_token,
    "endpoint_id": ENDPOINT_ID,
}).json()
assert check["status"] == "VALID"
```

To embed the live "AI Agents Can Pay Here" badge in your docs or README:

```html
<!-- Dynamic badge (live stats, auto-refreshes) -->
<script src="https://your-402proof.onrender.com/badge.js?endpoint=YOUR_ENDPOINT_ID" async></script>

<!-- Static fallback for environments that block scripts -->
<a href="https://your-402proof.onrender.com/badge/YOUR_ENDPOINT_ID">
  Verified by 402proof · XRP Ledger
</a>
```

---

## Zero-Custody Design

402proof never holds private keys for your treasury. `GATEWAY_XRPL_ADDRESS` is a **public address only** — provided so the server can verify that incoming XRPL payments landed at the right destination. Access tokens are issued after on-chain verification by querying the public XRPL ledger. Your funds flow directly on-chain; 402proof only reads the ledger, it never signs transactions or controls your wallet.

---

## License

MIT
