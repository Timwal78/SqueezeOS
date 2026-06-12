# ScriptMasterLabs / SqueezeOS — Architecture Map

> Master index of the agent-native financial infrastructure stack. Every product below exposes an MCP and/or HTTP-402 (x402) interface for autonomous AI agents, alongside human-facing endpoints. All payment rails settle on XRPL (RLUSD) and/or Base (USDC) via 402Proof.

**Agent discovery:** [`agents.json`](https://www.scriptmasterlabs.com/agents.json) · [`agent.md`](https://www.scriptmasterlabs.com/agent.md) · [`llms.txt`](https://www.scriptmasterlabs.com/llms.txt)
**Org:** [github.com/Timwal78/SqueezeOS](https://github.com/Timwal78/SqueezeOS) · **Brand:** [scriptmasterlabs.com](https://scriptmasterlabs.com) · [stack](https://scriptmasterlabs.com/stack)

| # | Doc | Product | Status |
|---|-----|---------|--------|
| — | [INDEX.md](./INDEX.md) | Master table + architecture map | ✅ |
| 01 | [01_squeezeos.md](./01_squeezeos.md) | SqueezeOS Signal OS — 8 x402 routes, signal tiers, mandatory tickers | ✅ Live |
| 02 | [02_ghost_layer.md](./02_ghost_layer.md) | Ghost Layer — bridge, stealth, copy, hooks, notary, marketplace | 🟡 Beta |
| 03 | [03_402proof.md](./03_402proof.md) | 402Proof — RLUSD rail + FICO bureau, discount curve | ✅ Live |
| 04 | [04_signal_loom_pne.md](./04_signal_loom_pne.md) | Signal Loom / PNE — Rust Axum proxy | 🟡 Beta |
| 05 | [05_shadow_desk.md](./05_shadow_desk.md) | Shadow Desk — dark pool surveillance | 🟡 Beta |
| 06 | [06_xah_portal.md](./06_xah_portal.md) | XAH Portal — unified chain gateway | 🟡 Beta |
| 07 | [07_nexus402.md](./07_nexus402.md) | Nexus402 — Next.js marketplace + RAG | ✅ Live |
| 08 | [08_sml_flow_interceptor.md](./08_sml_flow_interceptor.md) | SML Flow Interceptor — institutional order flow | 🟡 Beta |
| 09 | [09_stellar_forge.md](./09_stellar_forge.md) | Stellar Forge — black hole liquidity model | 🟡 Beta |
| 10 | [10_echolock.md](./10_echolock.md) | EchoLock — signal echo + lock detection | ✅ Live |
| 11 | [11_tipmaster.md](./11_tipmaster.md) | Tipmaster — tip aggregation + alert routing | 🟡 Beta |
| 12 | [12_neural_os_mobile.md](./12_neural_os_mobile.md) | Neural_OS Mobile — Capacitor Android terminal | ✅ Live |
| 13 | [13_sml_matrix_v8.md](./13_sml_matrix_v8.md) | SML Matrix v8 — TradingView script + IP rules | ✅ Live |
| 14 | [14_ftd_data_oracle.md](./14_ftd_data_oracle.md) | FTD Data Oracle — SEC Reg SHO, 6 endpoints | ✅ Live |
| 15 | [15_dream_pool_stigmergy.md](./15_dream_pool_stigmergy.md) | Dream Pool / Stigmergy — per-second bureau-discounted rent | 🟡 Beta |
| 16 | [16_futures_market.md](./16_futures_market.md) | Futures Market — bureau-discounted settlement fees | 🔵 Planned |
| 17 | [17_oracle_data_feed.md](./17_oracle_data_feed.md) | Oracle Data Feed — SEC 8-K + market structure SSE | ✅ Live |
| 18 | [18_agent_credit_marketplace.md](./18_agent_credit_marketplace.md) | Agent Credit Marketplace — XRPL P2P escrow | 🟡 Beta |
| 21 | [21_agent_top.md](./21_agent_top.md) | agent-top — live terminal dashboard for AI agents (htop for agents) | ✅ Live |
| 20 | [20_aegis_node.md](./20_aegis_node.md) | Aegis-Node — autonomous agent kill switch (token/API/loop guard) | ✅ Live |
| 19 | [19_system_circuit_breaker.md](./19_system_circuit_breaker.md) | System Circuit Breaker — kill switches + financial caps spec | 🟡 Spec |

## Conventions

- **x402 / HTTP-402**: standard agent payment flow — `GET endpoint` → `402 + payment terms (XRPL RLUSD or Base USDC)` → pay → retry with `X-PAYMENT` / `X-Payment-Token` → `200`.
- **MCP**: JSON-RPC 2.0 over HTTP, tools discoverable via `/mcp` endpoint.
- **Status**: ✅ Live (deployed, reachable) · 🟡 Beta (deployed, hardening) · 🔵 Planned (designed, not yet deployed).
- Each product doc follows the same template: Overview, Architecture, Agent/Human Access, Endpoints, Status & Roadmap.

## Compliance & Safety

All trading-adjacent products operate under the **Build Manifesto** (self-audit, Architecture.md, BEAST MODE brand standard, dual alert system, no fake data). Autonomous execution paths default to `LIVE_TRADING_ENABLED=false` with circuit breakers and PDT guards. The APEX Committee Engine is proprietary and is referenced but never reproduced in public docs.
