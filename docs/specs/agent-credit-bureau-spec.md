# Agent Credit Bureau — Protocol Specification

**Version:** 1.0  
**Status:** Live  
**Bureau endpoint:** `https://four02proof.onrender.com`  
**Issuer:** Script Master Labs LLC (SDVOSB)  
**Updated:** 2026-06-20

---

## Overview

The Agent Credit Bureau is a FICO-style reputation layer for autonomous AI agents. Scores are derived from on-chain payment history on the XRP Ledger (RLUSD) and reflect an agent's trustworthiness, spend depth, account age, KYB verification, and activity recency.

**Score range:** 300 (no history) → 850 (institutional tier)  
**No custody:** The bureau only reads existing agent records. No funds are held.  
**Portable attestations:** Agents can obtain a 24-hour signed JWT attesting their score, presentable to any third party without that party calling 402Proof directly.

---

## Score Model

### Base Score

Every agent starts at **300**.

### Scoring Factors

| Factor | Max Points | Description |
|---|---|---|
| Payment Volume | 150 | Total number of paid API calls ever made |
| Spend History | 200 | Cumulative RLUSD spent across all endpoints |
| Account Age | 100 | Time since first payment on record |
| KYB Verification | 100 | Know Your Bot tier assigned by operator |
| Loyalty Tier | 100 | Bronze → Diamond automatic tier |
| Domain Presence | 25 | `X-Agent-Domain` header provided |
| Recent Activity | 25 | Active within last 7 days |
| Risk Penalty | −(0–∞) | Deducted based on passport risk events |

**Maximum theoretical score:** 300 + 150 + 200 + 100 + 100 + 100 + 25 + 25 = **1,000** → clamped to **850**  
**Blocked agent hard cap:** Score cannot exceed 200 if agent is blocked.

### Factor Breakdowns

#### Payment Volume (0–150 pts)

| Total calls | Points |
|---|---|
| ≥ 1,000 | 150 |
| ≥ 100 | 100 |
| ≥ 10 | 50 |
| ≥ 1 | 20 |
| 0 | 0 |

#### Spend History (0–200 pts)

| Cumulative RLUSD | Points |
|---|---|
| ≥ 100.00 | 200 |
| ≥ 25.00 | 150 |
| ≥ 5.00 | 100 |
| ≥ 1.00 | 50 |
| > 0.00 | 20 |
| 0.00 | 0 |

#### Account Age (0–100 pts)

| Age since first payment | Points |
|---|---|
| ≥ 90 days | 100 |
| ≥ 30 days | 75 |
| ≥ 7 days | 50 |
| ≥ 24 hours | 25 |
| ≥ 1 hour | 10 |
| < 1 hour | 0 |

#### KYB Verification (0–100 pts)

| KYB Tier | Points |
|---|---|
| `verified` | 100 |
| `basic` | 50 |
| `none` | 0 |

KYB tiers are assigned by the operator via `POST /v1/admin/agent/{wallet}/kyb`.

#### Loyalty Tier (0–100 pts)

| Loyalty Tier | Points | Cumulative RLUSD required |
|---|---|---|
| Diamond | 100 | ≥ 50.00 |
| Platinum | 75 | ≥ 20.00 |
| Gold | 50 | ≥ 5.00 |
| Silver | 25 | ≥ 1.00 |
| Bronze | 0 | 0.00 |

Loyalty tiers are updated automatically on each successful payment.

#### Risk Penalty

The passport risk score (integer) is subtracted directly from the credit score. Risk events include: honeypot probes, credential scan attempts, wallet-binding violations, and operator flags. Low-risk agents have a risk score near 0; high-risk agents may see 50–200+ deducted.

---

## Grade Scale

| Grade | Score Range | Interpretation |
|---|---|---|
| AAA | 800–850 | Institutional — Diamond + verified KYB |
| AA | 750–799 | Excellent — high volume, long history |
| A | 700–749 | Strong — established agent |
| BBB | 650–699 | Good — consistent payer |
| BB | 600–649 | Fair — moderate history |
| B | 550–599 | Building — limited history |
| C | 400–549 | Weak — new or inactive |
| D | 300–399 | Minimal — no usable history |

---

## API Reference

**Base URL:** `https://four02proof.onrender.com`

### GET /v1/bureau/score/{wallet} — Free

Returns the public teaser score. No payment required.

**Path parameter:** `wallet` — XRPL r-address (e.g., `rABCDEF…`)

**Response:**
```json
{
  "wallet": "rABCDEF...",
  "score": 712,
  "grade": "A",
  "loyalty_tier": "Gold",
  "is_blocked": false,
  "generated_at": "2026-06-20T18:00:00Z"
}
```

---

### GET /v1/bureau/report/{wallet} — 0.01 RLUSD

Returns the full credit report with factor breakdown. Requires `X-Payment-Token` header from a valid 402Proof payment.

**Response:**
```json
{
  "wallet": "rABCDEF...",
  "score": 712,
  "grade": "A",
  "loyalty_tier": "Gold",
  "kyb_tier": "basic",
  "total_spend_rlusd": "8.2500",
  "total_calls": 347,
  "account_age": "42 days",
  "last_active": "2 hours ago",
  "risk_level": "Low",
  "breakdown": {
    "payment_volume": 100,
    "spend_history": 100,
    "account_age": 100,
    "kyb_verification": 50,
    "loyalty_tier": 50,
    "domain_verified": 25,
    "recent_activity": 25,
    "risk_penalty": -38
  },
  "is_blocked": false,
  "generated_at": "2026-06-20T18:00:00Z"
}
```

---

### GET /v1/bureau/verify/{wallet}?threshold=700 — 0.005 RLUSD

Returns a boolean pass/fail for a minimum score threshold. Cheaper than a full report; useful for gating access without revealing the exact score.

**Query parameter:** `threshold` — integer score (300–850)

**Response:**
```json
{
  "wallet": "rABCDEF...",
  "threshold": 700,
  "passes": true,
  "grade": "A"
}
```

---

### GET /v1/bureau/attest/{wallet} — 0.01 RLUSD

Issues a portable attestation JWT. The agent can present this token to any third-party service for 24 hours without that service needing to call 402Proof.

**Response:**
```json
{
  "attestation": "<base64url_payload>.<hex_signature>",
  "expires_at": "2026-06-21T18:00:00Z"
}
```

**Attestation payload (decoded):**
```json
{
  "wlt": "rABCDEF...",
  "score": 712,
  "grade": "A",
  "tier": "Gold",
  "kyb": "basic",
  "blocked": false,
  "iat": 1750442400,
  "exp": 1750528800
}
```

---

### POST /v1/bureau/verify-attest — Free

Verifies a portable attestation JWT issued by the bureau. Free — no payment required. Third-party services call this endpoint to validate agent-presented attestations.

**Request:**
```json
{
  "attestation": "<base64url_payload>.<hex_signature>"
}
```

**Response (valid):**
```json
{
  "valid": true,
  "wallet": "rABCDEF...",
  "score": 712,
  "grade": "A",
  "loyalty_tier": "Gold",
  "kyb_tier": "basic",
  "is_blocked": false,
  "expires_at": "2026-06-21T18:00:00Z"
}
```

**Response (invalid / expired):**
```json
{
  "valid": false,
  "error": "attestation expired"
}
```

---

## Attestation Protocol

The attestation is a two-part token: `<payload>.<signature>`.

- **Payload:** base64url-encoded JSON of `AttestClaims`
- **Signature:** `HMAC-SHA256("bureau:" + TOKEN_SECRET, payload)` encoded as lowercase hex
- **TTL:** 24 hours (`exp` field in payload)
- **Signing key:** The bureau's `TOKEN_SECRET` — never disclosed to clients

Third parties verify by calling `POST /v1/bureau/verify-attest`. They never need the signing key; verification is delegated to the bureau's free endpoint.

### Attestation Flow

```
1. Agent calls GET /v1/bureau/attest/{wallet}
   → Pays 0.01 RLUSD via x402
   → Receives { attestation: "...", expires_at: "..." }

2. Agent presents attestation to third-party service
   → Passes in request header, body, or out-of-band channel

3. Third-party calls POST /v1/bureau/verify-attest
   → Free, no payment
   → Receives { valid, wallet, score, grade, tier, kyb, blocked, expires_at }

4. Third-party gates access based on { score, grade, is_blocked }
```

---

## MCP Tools

The bureau is accessible via the 402Proof MCP server at `https://four02proof.onrender.com/mcp`.

| Tool | Cost | Description |
|---|---|---|
| `bureau_public_score` | Free | Public teaser score for any wallet |
| `bureau_full_report` | 0.01 RLUSD | Full breakdown with all factors |
| `bureau_verify_threshold` | 0.005 RLUSD | Boolean pass/fail for a minimum score |
| `bureau_get_attestation` | 0.01 RLUSD | Portable signed attestation JWT |
| `bureau_verify_attestation` | Free | Verify a third-party attestation |

**MCP client config:**
```json
{
  "mcpServers": {
    "402proof": {
      "url": "https://four02proof.onrender.com/mcp",
      "transport": "streamable-http"
    }
  }
}
```

---

## Integration Guide for Third-Party Services

To gate your service behind a minimum bureau score:

### Option A — Direct verification (recommended)

```python
import httpx

def check_agent_credit(attestation_token: str, min_score: int = 650) -> bool:
    r = httpx.post(
        "https://four02proof.onrender.com/v1/bureau/verify-attest",
        json={"attestation": attestation_token},
        timeout=5
    )
    data = r.json()
    if not data.get("valid"):
        return False
    if data.get("is_blocked"):
        return False
    return data.get("score", 0) >= min_score
```

Agents present their attestation in `X-Agent-Attestation: <token>` header. Your service validates without holding any credentials.

### Option B — Threshold check (cheaper for agents)

Have agents call `GET /v1/bureau/verify/{wallet}?threshold=650` and present the signed response. Cheaper for the agent (0.005 RLUSD vs 0.01 RLUSD for a full attestation).

### Option C — Public score check (no agent payment)

Query `GET /v1/bureau/score/{wallet}` directly (free). No agent involvement, but gives only the public teaser — not the full breakdown.

---

## Agent Self-Check Quickstart

```python
import httpx

PROOF402 = "https://four02proof.onrender.com"

# Free teaser — no payment
def get_my_score(wallet: str) -> dict:
    r = httpx.get(f"{PROOF402}/v1/bureau/score/{wallet}")
    return r.json()

# Full report — requires 0.01 RLUSD payment first
def get_full_report(wallet: str, payment_token: str) -> dict:
    r = httpx.get(
        f"{PROOF402}/v1/bureau/report/{wallet}",
        headers={"X-Payment-Token": payment_token, "X-Agent-Wallet": wallet}
    )
    return r.json()

# Get portable attestation — requires 0.01 RLUSD payment
def get_attestation(wallet: str, payment_token: str) -> str:
    r = httpx.get(
        f"{PROOF402}/v1/bureau/attest/{wallet}",
        headers={"X-Payment-Token": payment_token, "X-Agent-Wallet": wallet}
    )
    return r.json()["attestation"]
```

See `402proof/agent/client.py` and `402proof/agent/demo.py` for a full working agent implementation including XRPL payment.

---

## Score Improvement Tips for Agents

| Action | Score impact |
|---|---|
| Make your first payment | +20 payment volume, +20 spend history |
| Accumulate 1.00 RLUSD spend → Silver tier | +25 loyalty |
| Make 10+ total calls | +50 payment volume |
| Operate for 24+ hours | +25 account age |
| Operate for 7+ days | +50 account age |
| Set `X-Agent-Domain` header | +25 domain presence |
| Stay active weekly | +25 recency bonus |
| Request KYB basic from operator | +50 kyb |
| Accumulate 5.00 RLUSD spend → Gold tier | +50 loyalty |
| Never trigger honeypot/probe detection | no risk penalty |

---

## See Also

- [docs/architecture/03_402proof.md](../architecture/03_402proof.md) — Full 402Proof architecture
- [docs/architecture/18_agent_credit_marketplace.md](../architecture/18_agent_credit_marketplace.md) — Credit Marketplace (XRPL P2P escrow)
- [402proof/internal/bureau/score.go](../../402proof/internal/bureau/score.go) — Scoring source of truth
- [402proof/internal/bureau/attest.go](../../402proof/internal/bureau/attest.go) — Attestation source of truth
- [402proof/agent/demo.py](../../402proof/agent/demo.py) — Agent demo script
