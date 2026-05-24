# SqueezeOS — Institutional AI Market Intelligence

> **MCP Server** · x402 payment-gated · RLUSD on XRPL · 16 tools · Live data only

SqueezeOS is an institutional-grade AI trading intelligence platform for autonomous agents. Premium endpoints are pay-per-call via [402Proof](https://four02proof.onrender.com) — agents pay RLUSD on the XRP Ledger and receive a 1-hour access token. No API keys, no subscriptions.

**Live MCP endpoint:** `https://squeezeos-api.onrender.com/mcp`  
**Free demo:** `https://squeezeos-api.onrender.com/api/demo/council`  
**Agent guide:** `https://squeezeos-api.onrender.com/llms.txt`

---

## MCP Tools (16 total)

### Free Tools
| Tool | Description |
|------|-------------|
| `demo_council` | Full AI council verdict for IWM — live, no payment |
| `signal_preview` | Bias + regime preview for any symbol (15-min cache) |
| `signal_history` | Last 200 signals per symbol for backtesting |
| `system_status` | Platform health and uptime |

### Paid Tools (RLUSD via x402)
| Tool | Cost | Description |
|------|------|-------------|
| `council_verdict` | 0.10 RLUSD | AI council verdict for any symbol — regime, bias, confidence, thesis |
| `market_scan` | 0.05 RLUSD | Full $1–$50 universe squeeze scanner with options picks |
| `options_intelligence` | 0.05 RLUSD | Institutional sweeps, whale detection, unusual volume |
| `iwm_odte` | 0.03 RLUSD | IWM 0DTE contract scorer with Greeks and parity watch |
| `get_invoice` | free | Request payment invoice for any endpoint |
| `verify_payment` | free | Submit XRPL tx hash, receive 1-hour access token |
| `bureau_public_score` | free | Agent credit score (300–850) — no payment |
| `bureau_full_report` | 0.01 RLUSD | Full credit report for any agent wallet |
| `bureau_verify_threshold` | 0.005 RLUSD | Boolean creditworthiness gate for any wallet |
| `bureau_get_attestation` | 0.01 RLUSD | Signed portable credit JWT (24h TTL) |
| `bureau_verify_attestation` | free | Verify a credit attestation JWT |
| `marketplace_browse` | free | Browse peer signal marketplace |

---

## Connect via MCP

```json
{
  "mcpServers": {
    "squeezeos": {
      "url": "https://squeezeos-api.onrender.com/mcp",
      "transport": "streamable-http"
    }
  }
}
```

Or call directly:

```bash
curl -X POST https://squeezeos-api.onrender.com/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

---

## Payment Flow (x402)

1. Call `get_invoice` with the endpoint UUID → receive `pay_to` + `memo_hex`
2. Send RLUSD on XRPL to `pay_to` with `memo_hex` as MemoData (sub-5s finality)
3. Call `verify_payment` with tx hash + your wallet → receive `access_token`
4. Call any paid tool with `payment_token: <access_token>`

**Payment network:** XRPL mainnet  
**Payment asset:** RLUSD (issuer: `rMxCKbEDwqr76QuheSUMdEGf4B9xJ8m5De`)  
**Token TTL:** 1 hour (HMAC-SHA256, wallet-bound)  
**Settlement:** [402Proof](https://four02proof.onrender.com)

---

## Ecosystem

| Service | URL | Description |
|---------|-----|-------------|
| SqueezeOS | `https://squeezeos-api.onrender.com` | This service — market intelligence API |
| 402Proof | `https://four02proof.onrender.com` | x402 payment firewall + Agent Passport |
| Ghost Layer | `https://ghost-layer.onrender.com` | Dual-chain XRPL+Base toll gateway |
| Script Master Labs | `https://www.scriptmasterlabs.com` | Operator homepage |

---

## Discovery Files

- `GET /llms.txt` — full agent integration guide
- `GET /.well-known/mcp.json` — MCP manifest (16 tools)
- `GET /.well-known/server.json` — official MCP registry format
- `GET /.well-known/openapi.json` — OpenAPI 3.0 spec
- `GET /.well-known/agents.json` — agents.json discovery
- `GET /api/demo/council` — free live demo (no auth)
- `GET /api/events` — real-time SSE stream (free)

---

## License

MIT — see [LICENSE](LICENSE)
