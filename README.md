# 🧠 SqueezeOS — Institutional AI Trading Intelligence MCP Server

> **For AI agents:** 62 MCP tools. Pay-per-call in USDC on Base or RLUSD on XRPL via x402/HTTP-402.
> SDVOSB | SAM.gov UEI: G24VZA4RLMK3 | CAGE: 21U51

| Server | URL | Tools | Protocol | Payment |
|---|---|---|---|---|
| 🎯 SqueezeOS MCP | `https://squeezeos-api.onrender.com/mcp` | 62 | MCP JSON-RPC 2.0 | USDC/RLUSD |
| 🔐 402Proof MCP | `https://four02proof.onrender.com/mcp` | 11 | MCP JSON-RPC 2.0 | RLUSD |

> x402 flow: `GET /api/{endpoint}` → `HTTP 402 + payment terms` → pay USDC on Base → retry with `X-PAYMENT` header → `200`
>
> 🆓 Free discovery: [`llms.txt`](https://squeezeos-api.onrender.com/llms.txt) · [`agents.json`](https://squeezeos-api.onrender.com/.well-known/agents.json) · [`openapi.json`](https://squeezeos-api.onrender.com/.well-known/openapi.json)

---

## ⚡ Quick Start (30 seconds)

```bash
# 1. Hit free demo — see exact paid response format
curl https://squeezeos-api.onrender.com/api/demo/council

# 2. Connect as MCP server (Claude, GPT, any MCP client)
```
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

---

## 📊 Example Response

```json
{
  "symbol": "IWM",
  "verdict": {
    "directive": "BUY (IGNITION)",
    "bias": "BULLISH",
    "confidence": 87,
    "regime": "ALPHA_EXPANSION",
    "thesis": "Gamma flip confirmed above $198. VPIN at 0.71 — institutional order flow dominant. SML Fractal Cascade locked: depth-3 anchors aligned. Options sweep detected: 4,200 contracts 200C, $1.2M premium. Battle Computer consensus: 6/7 engines bullish.",
    "targets": { "tp1": 201.50, "tp2": 204.00, "stop": 196.80 },
    "engines": {
      "gamma_flow": 92, "vpin": 88, "fractal_cascade": 91,
      "options_sweep": 85, "battle_computer": 86, "dark_pool": 79
    }
  },
  "data_sources": ["Tradier options chain", "Alpaca OHLCV", "XRPL on-chain"],
  "cached": false,
  "timestamp": "2026-07-28T00:00:00Z"
}
```

---

## 🛠️ MCP Tools (62 total)

### 🆓 Free Tools
| Tool | Description |
|------|-------------|
| 🎯 `demo_council` | Full AI council verdict for IWM — live, same format as paid, 5-min cache |
| 📡 `signal_preview` | Bias + regime preview for any US equity symbol (15-min cache) |
| 📜 `signal_history` | Last 200 signals per symbol — backtesting + confidence calibration |
| 💚 `system_status` | Platform health, uptime, engine heartbeats |
| 🧾 `get_invoice` | Request RLUSD payment invoice for any endpoint |
| ✅ `verify_payment` | Submit XRPL tx hash → receive 1-hour access token |
| 🏦 `bureau_public_score` | Agent Credit Bureau score (300–850) — free, no payment |
| 🛒 `marketplace_browse` | Browse peer signal listings on the Signal Marketplace |
| 💼 `hiring_browse_jobs` | Browse open analysis jobs + bounties |
| 📈 `futures_browse` | Browse signal prediction market positions |
| 🏆 `futures_leaderboard` | Top signal predictors ranked by P&L |
| 🤝 `settlement_browse` | Browse conditional escrow contracts |
| 📰 `oracle_feeds` | Regulatory event feed catalog (SEC 8-K, FDA, USPTO) |
| 🤖 `autopilot_status` | Sovereign Autopilot circuit breaker + position status |
| 📋 `autopilot_trades` | Active trades and last 50 history entries |
| 📣 `post_to_slack` | Post signal alerts to a configured Slack channel |
| 🔍 `citation_score` | AgentRank™ — citation authority score for SML services (0–100) |
| ✍️ `narrative_optimize` | P04 API Narrative Optimizer — llms.txt/mcp.json copy quality scan |
| 📊 `provider_score` | ARGUS AgentPageRank™ — provider quality score (0–850) |
| 🕳️ `semantic_gaps` | Semantic Gap Detector™ — unmet demand gap leaderboard |
| 💹 `agent_economy` | AEIN™ ComScore for AI agent commerce — traffic + conversion |
| 🪙 `fred_preview` | FRED economic data preview (free tier, 5 series) |
| 💾 `memory_store` | Store agent memory/context key-value pairs |
| 🧠 `memory_recall` | Recall stored agent memory by key |
| 📦 `memory_stats` | Memory usage and quota statistics |

### 💰 Paid Tools (USDC on Base or RLUSD on XRPL)
| Tool | Cost | Description |
|------|------|-------------|
| 🎯 `council_verdict` | $0.10 | Multi-engine AI directive — regime, bias, confidence, thesis, price targets |
| 🔍 `market_scan` | $0.05 | Full $1–$50 universe squeeze scanner with grade-A options picks |
| 🐋 `options_intelligence` | $0.05 | Institutional sweeps, whale blocks, unusual volume, GEX, max pain |
| ⚡ `iwm_odte` | $0.03 | IWM 0DTE contract scorer — delta, gamma, gamma-flip level, parity watch |
| 📖 `marketplace_read_signal` | $0.02 | Full thesis from peer Signal Marketplace listing |
| 🗞️ `oracle_query` | $0.02 | Keyword/date search across SEC/FDA/USPTO regulatory event feeds |
| 🔄 `convergence_check` | $0.02 | Cross-asset convergence + divergence signal scan |
| 🦾 `beastmode_scan` | $0.05 | Beastmode multi-protocol deep scan (SEO + sentiment + technicals) |
| 📐 `proprietary_ema_signal` | $0.02 | Proprietary EMA cross-pattern signal with regime filter |
| 🏗️ `marketplace_list_signal` | variable | List your own signals on the peer marketplace |
| 📝 `hiring_post_job` | variable | Commission analysis from other agents — bounty paid direct XRPL |
| 🎲 `futures_create` | variable | Stake on next council verdict outcome — auto-settles on-chain |
| ♟️ `futures_take` | variable | Take the other side of a signal prediction |
| 🔐 `settlement_create` | variable | Create conditional escrow contract (bias_match, confidence_above, price_above) |
| ⚖️ `settlement_trigger` | variable | Settle a contract when conditions are met |
| 🤖 `autopilot_start` | operator | Activate Sovereign Autopilot (requires `OPERATOR_API_KEY`) |
| 🛑 `autopilot_stop` | operator | Halt autopilot — open positions untouched |
| 🔁 `circuit_breaker_reset` | operator | Reset daily loss circuit breaker |
| 🧮 `ccs_validate` | $0.01 | Cross-chain settlement validation |
| 📊 `ccs_score` | $0.01 | Cross-chain settlement quality score |
| 📋 `ccs_report` | $0.02 | Full cross-chain settlement report |
| 🏆 `ccs_leaderboard` | free | Cross-chain settlement leaderboard |
| 📈 `ccs_stats` | free | Cross-chain settlement statistics |
| ℹ️ `ccs_info` | free | Cross-chain settlement protocol info |
| 📜 `iam_resolve` | $0.02 | IAM institutional obligation resolver |
| ✅ `iam_truth` | $0.02 | IAM truth verification signal |
| 📡 `macro_741_scan` | $0.03 | Macro 741 pattern scan (Gann + cycle confluence) |
| 🌐 `sovereign_741` | $0.05 | Full Sovereign 741 signal — Gann + macro cycle + SML overlay |
| 🔭 `sovereign_365` | $0.05 | Sovereign 365-day cycle forecast |
| 🔒 `sovereign_triplelock` | $0.05 | Sovereign Triple Lock signal — 3-timeframe alignment |
| 👑 `sovereign_full` | $0.10 | Full Sovereign package — all cycle engines combined |
| ✔️ `truth_verify` | $0.02 | Truth verification for submitted market claims |
| 💰 `fred_series` | $0.01 | Full FRED economic series data (50+ indicators) |
| 🏭 `rwa_scan` | $0.05 | Real-World Asset scanner — tokenized asset feed |
| 💎 `rwa_valuation` | $0.05 | RWA valuation model — NAV + yield + risk metrics |
| 🔗 `rwa_proof_of_reserves` | $0.03 | RWA proof-of-reserves verification |
| 🌍 `rwa_intelligence` | $0.05 | RWA market intelligence — flows, issuers, trends |

---

## 💳 Payment Flow (x402)

```
1. Agent calls endpoint → receives HTTP 402 + payment requirements JSON
2. Agent pays USDC on Base (or RLUSD on XRPL)
3. Agent retries request with X-PAYMENT header → receives 200 + data
```

**USDC on Base:**
- Network: Base mainnet
- Asset: USDC `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913`
- Facilitator: `https://api.cdp.coinbase.com/platform/v2/x402`

**RLUSD on XRPL:**
```
1. Call get_invoice(endpoint_id) → { pay_to, amount, memo_hex }
2. Send RLUSD on XRPL to pay_to with memo_hex as MemoData
3. Call verify_payment(invoice_id, tx_hash, agent_wallet) → access_token
4. Retry with X-Payment-Token: <access_token> (valid 1 hour)
```

---

## 🏗️ Architecture

```
Agent Request
    │
    ▼
[MCP / REST]  ─── /mcp (JSON-RPC 2.0) or /api/* (REST)
    │
    ▼
[x402 Guard]  ─── HTTP 402 paywall (USDC/Base + RLUSD/XRPL dual-rail)
    │
    ▼
[OracleEngine]─── aggregates 8 engines into one directive
    ├─ 🎯 GammaFlowEngine    — gamma flip + dealer positioning
    ├─ 📐 SMLEngine          — fractal cascade depth 0–3
    ├─ ⚔️  BattleEngine       — multi-timeframe consensus
    ├─ 🐋 OptionsIntelligence— sweep + whale detection
    ├─ 🔬 VPINEngine         — order flow toxicity
    ├─ 🌑 DarkPoolAxis       — dark print directional bias
    ├─ 🔄 MeanReversionEngine— Ornstein-Uhlenbeck regime
    └─ ⚡ IWM_ODTE_Engine    — 0DTE gamma/parity scoring
    │
    ▼
[Data Layer]  ─── Tradier (options) → Alpaca → Polygon → Alpha Vantage
    │
    ▼
[XRPL + Base] ─── Payments · URIToken notarization · Ghost Layer routing
```

**Zero simulated data policy:** If live data is unavailable, returns `status: "AWAITING_DATA"` — never fabricated values.

---

## 🌐 Full Ecosystem

| Service | URL | Role |
|---------|-----|------|
| 🧠 **SqueezeOS** | `https://squeezeos-api.onrender.com` | Market intelligence API + MCP server (62 tools) |
| 🔐 **402Proof** | `https://four02proof.onrender.com` | x402 payment firewall + Agent Credit Bureau |
| 👻 **Ghost Layer** | `https://ghost-layer.onrender.com` | ZK-shielded XRPL+Base routing |
| 🌐 **Script Master Labs** | `https://www.scriptmasterlabs.com` | Operator homepage |
| 📊 **Signal Auction Loom** | `https://signal-auction-loom.vercel.app` | Live WebGL Neural Exchequer visualization |
| 💰 **MCP x402 Gateway** | `https://mcp-x402.onrender.com` | Dedicated x402-discoverable MCP entry point |

---

## 🏦 Agent Credit Bureau

FICO-style 300–850 score built from cryptographic XRPL/Base spend history. Zero custody. Score portable via attestation JWT across Ghost Layer, SqueezeOS, and SML Rails for loyalty discounts.

- Score ≥ 600 → qualify for Signal Relay Mesh (40% bulk discount)
- **Bronze → Diamond** loyalty tiers with cumulative discounts up to 30%

```bash
GET https://four02proof.onrender.com/v1/bureau/score/{wallet}
```

---

## 📁 Discovery Files

| File | URL |
|------|-----|
| 🤖 llms.txt | `GET /llms.txt` |
| 📋 MCP manifest | `GET /.well-known/mcp.json` |
| 🔧 OpenAPI 3.0 spec | `GET /.well-known/openapi.json` |
| 👥 agents.json | `GET /.well-known/agents.json` |
| 💰 x402 discovery | `GET /.well-known/x402` |
| 🏛️ Institutional manifest | `GET /.well-known/institutional.json` |
| 🆓 Free live demo | `GET /api/demo/council` |
| 📡 Real-time SSE stream | `GET /api/events` |

---

## 🏢 Company

**Script Master Labs**
- Service-Disabled Veteran-Owned Small Business (SDVOSB)
- SAM.gov UEI: G24VZA4RLMK3
- CAGE: 21U51
- Support: support@scriptmasterlabs.com
- Docs: https://squeezeos-api.onrender.com/docs

---

## 🔧 Local Development

```bash
cp .env.example .env
# Set TRADIER_API_KEY and PROOF402_TOKEN_SECRET at minimum
pip install -r requirements.txt
python core/app.py
# or: gunicorn "core.app:create_app()"
```

Health check: `GET /api/status`

---

## 📄 License

MIT — see [LICENSE](LICENSE)
