# SqueezeOS — Agent Integration Guide

> Autonomous AI agent? Start here. Everything you need to pay and call.

## TL;DR

```bash
# 1. Get invoice
curl -X POST https://four02proof.onrender.com/v1/invoice \
  -H "Content-Type: application/json" \
  -d '{"endpoint_id":"12a0e7a1-6812-4c3f-aa24-de6e3bc12b5a"}'

# 2. Pay RLUSD on XRPL (use xrpl-py or xumm)
# Send amount to pay_to with memo_hex as MemoData

# 3. Verify
curl -X POST https://four02proof.onrender.com/v1/verify \
  -H "Content-Type: application/json" \
  -d '{"invoice_id":"...","tx_hash":"...","agent_wallet":"rYOURWALLET..."}'

# 4. Call
curl -X POST https://lively-fascination-production-41fa.up.railway.app/api/council \
  -H "X-Payment-Token: <token>" \
  -H "X-Agent-Wallet: rYOURWALLET..." \
  -H "X-Agent-Domain: your-agent.example.com" \
  -H "Content-Type: application/json" \
  -d '{"symbol":"IWM"}'
```

## Endpoints

| Path | Cost | Endpoint ID |
|------|------|-------------|
| `POST /api/council` | **0.10 RLUSD** | `12a0e7a1-6812-4c3f-aa24-de6e3bc12b5a` |
| `GET  /api/scan`    | **0.05 RLUSD** | `160cf28d-b364-44eb-adbd-2489c5cc2cf8` |
| `GET  /api/options` | **0.05 RLUSD** | `c951a374-2424-4064-ab80-35afe8053d29` |
| `GET  /api/iwm`     | **0.03 RLUSD** | `60f48ce0-6002-4385-9b60-03a0d2bbebab` |

**Base URL**: `https://lively-fascination-production-41fa.up.railway.app`  
**Payment gateway**: `https://four02proof.onrender.com`  
**RLUSD issuer**: `rMxCKbEDwqr76QuheSUMdEGf4B9xJ8m5De`

## Python SDK (copy-paste ready)

```python
import os
from squeezeos_sdk import SqueezeOSClient  # file in repo root

client = SqueezeOSClient(xrpl_seed=os.environ["AGENT_XRPL_SEED"])

# AI council verdict
verdict = client.council("IWM")
print(verdict["verdict"]["bias"])        # BULLISH / BEARISH / NEUTRAL
print(verdict["verdict"]["confidence"])  # 0-100

# Market scan
scan = client.scan()
print(scan["options"][:5])               # top grade-A options picks

# Check your loyalty tier
passport = client.loyalty_status()
print(passport["tier"])                  # Bronze/Silver/Gold/Platinum/Diamond
```

## Machine-Readable Discovery

- **llms.txt**: https://www.scriptmasterlabs.com/llms.txt
- **OpenAPI 3.1**: https://lively-fascination-production-41fa.up.railway.app/.well-known/openapi.json
- **MCP manifest**: https://lively-fascination-production-41fa.up.railway.app/.well-known/mcp.json
- **AI plugin**: https://lively-fascination-production-41fa.up.railway.app/.well-known/ai-plugin.json
- **Ghost Layer**: https://ghost-layer.onrender.com/.well-known/mcp.json

## Live Event Stream (Free, No Auth)

```python
import sseclient, requests

resp = requests.get(
    "https://lively-fascination-production-41fa.up.railway.app/api/events",
    stream=True
)
for event in sseclient.SSEClient(resp):
    print(event.data)  # SQUEEZE_ALERT, COUNCIL_VERDICT, AGENT_PROBE, etc.
```

## Rules

1. `X-Agent-Wallet` must match the wallet that paid the invoice (tokens are wallet-bound)
2. RLUSD trust line required before first payment
3. Tokens are valid 1 hour — cache them
4. Probing for credentials triggers a 45s tarpit
