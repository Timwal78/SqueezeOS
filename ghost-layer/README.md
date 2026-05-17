# ghost-layer

**Atomic bridge between Base L2 (USDC/EIP-3009) and the XRP Ledger (RLUSD) — the compliance transport layer for x402 agent payments.**

ghost-layer is a production Go facilitator node. It accepts EIP-3009 `transferWithAuthorization` signatures from Base L2 and settles the equivalent RLUSD payment on the XRP Ledger in a single coordinated flow. It exists because the x402 payment protocol targets XRPL RLUSD compliance receipts, but AI agents operating on EVM chains need a trust-minimized, auditable way to cross the chain boundary without giving up the compliance guarantees that RLUSD provides.

---

## Why This Exists

The x402 protocol lets agents pay for API access using HTTP 402 micropayments. The canonical settlement asset is RLUSD on the XRP Ledger, which has on-chain finality in 3–5 seconds and first-class GENIUS Act compliance tooling. However, many agents run on Base L2 and hold USDC — not RLUSD on XRPL. ghost-layer bridges that gap:

- Agent signs an EIP-3009 authorization on Base (no separate approval transaction required)
- ghost-layer verifies the signature, claims the USDC, and simultaneously delivers RLUSD on XRPL to the merchant
- The merchant's 402proof server sees a normal XRPL RLUSD payment and issues the compliance receipt
- The agent gets an access token. The USDC never touches the agent's XRPL wallet

---

## Flow Diagram

```
  AI Agent (EVM / Base L2)
         │
         │  1. Sign EIP-3009 transferWithAuthorization
         │     (USDC on Base, valid_after/valid_before window,
         │      unique nonce, v/r/s signature)
         │
         ▼
  ┌──────────────────────────────────────────────┐
  │              ghost-layer                     │
  │                                              │
  │  2. Verify EIP-3009 signature                │
  │  3. Check nonce — reject replays             │
  │  4. Rate-limit check (20 req/min per IP)     │
  │  5. Deduct transparent fee (basis points)    │
  │  6. engine.RouteTransactionWithDisclosure()  │
  │     ├─► BaseClient.SweepUSDCToTreasury()    │──► Base L2 (claim USDC)
  │     └─► XRPLClient.SendPayment()            │──► XRPL (deliver RLUSD)
  │                                              │
  │  Response: tx_hash, gross, fee, net          │
  └──────────────────────────────────────────────┘
         │
         ▼
  402proof server sees XRPL RLUSD payment
  → verifies on-chain → issues access token + receipt
         │
         ▼
  Agent receives access token
```

### Dry-Run Mode

Set `"is_dust_test": true` in the bridge payload to validate the full parse and signature path without broadcasting any on-chain transaction. Use this during integration testing.

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `PORT` | No | `8080` | HTTP port |
| `ENVIRONMENT` | No | `production` | Deployment environment label |
| `TREASURY_ADDRESS` | No | `rNduuviQ3CCvHqWUTjJDD82Ko2tjqFGs3q` | XRPL cold-storage treasury address. Sweeps drain here. |
| `TREASURY_ETH_ADDRESS` | No | — | EVM cold-storage treasury address |
| `BASE_RPC_URL` | No | `https://mainnet.base.org` | Base L2 JSON-RPC endpoint |
| `XRPL_RPC_URL` | No | `https://xrplcluster.com` | XRPL full-history node RPC |
| `USDC_CONTRACT_ADDRESS` | No | `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913` | Native USDC on Base |
| `GATEWAY_XRPL_PRIVATE_KEY` | **Yes** (for XRPL routing) | — | Hot wallet private key for signing XRPL payments. Set in Render secrets only. |
| `GATEWAY_ETH_PRIVATE_KEY` | **Yes** (for Base routing) | — | Hot wallet private key for claiming EIP-3009 USDC on Base. Set in Render secrets only. |
| `ADMIN_TOKEN` | **Yes** | — | Bearer token for `/v1/admin/*` routes. Generate: `openssl rand -hex 32` |

At least one of `GATEWAY_XRPL_PRIVATE_KEY` or `GATEWAY_ETH_PRIVATE_KEY` must be set or the server will refuse to start.

---

## API Endpoints

### Health

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Returns bridge status, XRPL/Base client state, and treasury address |

**Response:**
```json
{
  "status": "ok",
  "xrpl_client": "connected",
  "base_client": "connected",
  "xrpl_treasury": "rNduuviQ3CCvHqWUTjJDD82Ko2tjqFGs3q"
}
```

### Bridge Execution

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/v1/bridge/execute` | EIP-3009 sig or app-level signature | Route a cross-chain payment |

**Request payload:**
```json
{
  "signer":             "0xAgentEthAddress",
  "message_hash":       "0x...",
  "signature":          "0x...",
  "source_wallet":      "0xAgentEthAddress",
  "destination_wallet": "rMerchantXRPLAddress",
  "gross_amount":       "1.00",
  "fee_basis_points":   30,
  "eip3009": {
    "valid_after":  "0",
    "valid_before": "9999999999",
    "nonce":        "0x<32-byte-hex>",
    "v": 27,
    "r": "0x<32-byte-hex>",
    "s": "0x<32-byte-hex>"
  },
  "is_dust_test": false
}
```

**Success response:**
```json
{
  "status":           "SUCCESSFULLY_SETTLED",
  "transaction_hash": "<xrpl_or_evm_tx_hash>",
  "gross_processed":  "1.00",
  "transparent_fee":  "0.003",
  "net_delivered":    "0.997",
  "treasury_routing": "rNduuviQ3CCvHqWUTjJDD82Ko2tjqFGs3q"
}
```

**Rate limit:** 20 requests/minute per IP, burst of 5. Exceeding returns HTTP 429.

### Admin (Bearer `ADMIN_TOKEN` required)

| Method | Path | Description |
|---|---|---|
| `POST` | `/v1/admin/sweep` | Force-drain both gateway wallets to cold treasury |
| `POST` | `/v1/admin/dust-test` | Send 1 drop (XRPL) or 1 wei USDC (Base) to verify live signing |

**POST /v1/admin/dust-test body:**
```json
{ "chain": "xrpl", "destination": "rTestAddress..." }
```
`chain` must be `"xrpl"` or `"evm"`.

---

## Security Properties

### Nonce Replay Protection

Every EIP-3009 authorization carries a unique 32-byte `nonce`. ghost-layer maintains an in-memory set of consumed nonces. Any attempt to resubmit a captured authorization is rejected with HTTP 401 (`"eip3009 nonce already consumed — replay rejected"`). The nonce check is mutex-protected and happens before any chain interaction.

### Application-Level Signature Verification

For XRPL-routed payments where there is no on-chain EIP-3009 commitment, the caller must include a `signer` + `message_hash` + `signature` triplet. ghost-layer verifies the EIP-3009 style signature against the declared signer address before routing.

### Hot Wallet Hygiene

Gateway private keys sign individual transactions only. They are never exposed via any API response. The `/v1/admin/sweep` endpoint exists specifically to vacate the hot wallets to cold treasury on demand — use it after high-volume periods or before maintenance windows.

### No Custody of Client Funds

ghost-layer does not hold client funds at rest. The EIP-3009 authorization directs the USDC transfer directly from the agent's wallet to the treasury; there is no intermediate custodial balance. XRPL payments flow from the gateway hot wallet (pre-funded for liquidity) to the merchant in real time.

### Error Sanitization

Internal routing errors are logged server-side but never returned to the caller. The client receives only `"routing failed"` on HTTP 500, preventing information leakage about chain state or key configuration.

---

## Deploy to Render

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/timwal78/squeezeos)

1. Click the button above.
2. In the Render dashboard, set secrets under **Environment**:
   - `GATEWAY_XRPL_PRIVATE_KEY` — your XRPL hot wallet signing key
   - `GATEWAY_ETH_PRIVATE_KEY` — your Base L2 hot wallet signing key
   - `ADMIN_TOKEN` — `openssl rand -hex 32`
3. Optionally update `TREASURY_ADDRESS` and `TREASURY_ETH_ADDRESS` to your cold-storage addresses.
4. The health check at `/health` must return 200 before Render marks the deploy live.

The service is configured for the `starter` plan in the `oregon` region. Upgrade the plan for higher concurrency before opening to production volume.

### Pre-production Checklist

- [ ] Run `POST /v1/admin/dust-test` for both `"xrpl"` and `"evm"` chains to confirm live signing
- [ ] Submit a `"is_dust_test": true` bridge request to validate the EIP-3009 parse path
- [ ] Confirm `/health` shows both `xrpl_client` and `base_client` as `connected`
- [ ] Set cold treasury addresses; run `/v1/admin/sweep` and verify funds land correctly

---

## License

MIT
