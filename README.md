# SqueezeOS — AI Agent Infrastructure

## @relayos/mcp-paywall

HTTP 402 paywall middleware for MCP servers. XRPL/RLUSD native settlement, Phase 3 compliance receipts, zero API keys required.

### Install
npm install @relayos/mcp-paywall

### Usage
import { mcpPaywall } from "@relayos/mcp-paywall";
app.use("/mcp", mcpPaywall({ feeAddress: "YOUR_XRPL_WALLET", feeDrops: "1000" }));

### Live Dashboard
https://four02proof.onrender.com

### NPM
https://www.npmjs.com/package/@relayos/mcp-paywall
