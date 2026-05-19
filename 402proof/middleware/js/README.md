# proof402-middleware

> x402/HTTP 402 payment middleware for Express, Next.js, and Cloudflare Workers.  
> Gate any API behind RLUSD micropayments on XRP Ledger via [402Proof](https://four02proof.onrender.com).  
> Sub-millisecond local HMAC verification. Zero API keys. Zero custody.

[![npm](https://img.shields.io/npm/v/proof402-middleware)](https://www.npmjs.com/package/proof402-middleware)
[![license](https://img.shields.io/badge/license-MIT-green)](LICENSE)

---

## Install

```bash
npm install proof402-middleware
```

---

## How It Works

1. Agent hits your protected route → middleware checks for `X-Payment-Token` header
2. No token (or invalid) → middleware returns `HTTP 402` + invoice (pay_to, memo_hex, amount)
3. Agent sends RLUSD on XRPL → calls `POST /v1/verify` on 402Proof → receives signed token
4. Agent retries with `X-Payment-Token: <token>` → verified locally in <1ms → access granted

Token verification is pure HMAC-SHA256 — **zero network call, sub-millisecond** when `tokenSecret` is set.

---

## Express

```javascript
const express = require('express');
const { proof402 } = require('proof402-middleware');

const app = express();

app.use('/api/premium', proof402({
  endpointId:  'your-endpoint-uuid',          // from 402Proof merchant dashboard
  serverUrl:   'https://four02proof.onrender.com',
  tokenSecret: process.env.PROOF402_TOKEN_SECRET, // enables zero-latency local verify
}));

app.get('/api/premium/data', (req, res) => {
  res.json({ data: 'paid content', verified: req.proof402 });
});
```

## Next.js App Router (middleware.ts)

```typescript
import { proof402Next } from 'proof402-middleware';

export default proof402Next({
  endpointId:  process.env.PROOF402_ENDPOINT_ID!,
  serverUrl:   'https://four02proof.onrender.com',
  tokenSecret: process.env.PROOF402_TOKEN_SECRET,
});

export const config = { matcher: ['/api/premium/:path*'] };
```

## Cloudflare Workers

```javascript
import { proof402Worker } from 'proof402-middleware';

async function myHandler(request, env, ctx) {
  return new Response(JSON.stringify({ data: 'paid' }), {
    headers: { 'Content-Type': 'application/json' }
  });
}

export default {
  fetch: proof402Worker({
    endpointId:  'your-endpoint-uuid',
    serverUrl:   'https://four02proof.onrender.com',
    tokenSecret: env.PROOF402_TOKEN_SECRET,
    handler:     myHandler,
  })
};
```

---

## HTTP 402 Response Format

When payment is required, clients receive:

```json
{
  "error": "Payment Required",
  "invoice": {
    "invoice_id": "inv_abc123",
    "pay_to": "rGATEWAY...",
    "memo_hex": "696e765f616263313233",
    "amount": "0.10",
    "asset": "RLUSD",
    "expires_at": 1747616400
  },
  "instructions": {
    "step1": "Send 0.10 RLUSD on XRPL to rGATEWAY...",
    "step2": "Include MemoData: 696e765f... in your XRPL payment",
    "step3": "POST https://four02proof.onrender.com/v1/verify with invoice_id, tx_hash, agent_wallet",
    "step4": "Retry with header: X-Payment-Token: <token>"
  }
}
```

Response headers also include `X-Payment-Address`, `X-Payment-Amount`, `X-Invoice-ID`, `X-Memo-Hex`, `X-Verify-URL` for machine-readable x402 compliance.

---

## Options

| Option | Type | Required | Description |
|--------|------|----------|-------------|
| `endpointId` | string | yes | UUID from 402Proof merchant dashboard |
| `serverUrl` | string | no | 402Proof server URL (default: `https://four02proof.onrender.com`) |
| `tokenSecret` | string | recommended | Same `TOKEN_SECRET` as your 402Proof server. Enables zero-network local verification. |

---

## Environment Variables

```bash
PROOF402_ENDPOINT_ID=your-endpoint-uuid
PROOF402_TOKEN_SECRET=your-token-secret   # from 402Proof server env
```

---

## Register Your Endpoint

1. Go to [four02proof.onrender.com](https://four02proof.onrender.com)
2. Register as a merchant → create an endpoint → copy the UUID
3. Set `endpointId` in your middleware config
4. Set `PROOF402_TOKEN_SECRET` to the same value as your 402Proof `TOKEN_SECRET`

---

## Links

- **402Proof Dashboard:** https://four02proof.onrender.com
- **402Proof llms.txt:** https://four02proof.onrender.com/llms.txt
- **SqueezeOS (live example):** https://lively-fascination-production-41fa.up.railway.app
- **Python SDK:** `pip install proof402` (see `/402proof/middleware/python/`)

---

## License

MIT © Script Master Labs
