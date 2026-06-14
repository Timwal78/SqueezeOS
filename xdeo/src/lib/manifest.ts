// Machine-readable discovery surfaces: agent manifest + OpenAPI.
// These let AI agents discover xDEO tools and their x402 prices natively.

import type { Env } from "../types.js";

export function agentManifest(base: string, env: Env) {
  return {
    schema_version: "1.0",
    name_for_model: "xdeo",
    name_for_human: "xDEO — Decentralized Earnings Oracle",
    description_for_model:
      "Machine-native marketplace for corporate earnings estimates. Read " +
      "reputation-ranked analyst EPS/revenue estimates scored against real SEC " +
      "EDGAR filings. Pay per estimate via x402 (USDC on Base). All data is free " +
      "public data; the service holds no funds and gives no investment advice.",
    description_for_human:
      "Earnings estimates from ranked analysts, scored against SEC filings. Pay per call.",
    contact: env.EDGAR_USER_AGENT,
    legal:
      "Information marketplace only. Estimates are opinions, not securities or " +
      "investment advice. Zero custody. No KYC.",
    payment: {
      protocol: "x402",
      network: env.X402_NETWORK,
      asset: env.X402_ASSET,
      asset_symbol: "USDC",
      facilitator: env.X402_FACILITATOR_URL,
      affiliate_header: "X-AGENT-ID",
      affiliate_bps: Number(env.AGENT_AFFILIATE_BPS)
    },
    tools: [
      {
        name: "list_tickers",
        method: "GET",
        path: "/api/v1/tickers",
        price_usdc: 0,
        description: "List all tracked tickers."
      },
      {
        name: "ticker_consensus",
        method: "GET",
        path: "/api/v1/tickers/{ticker}",
        price_usdc: 0,
        description: "Ticker details + free reputation-weighted consensus estimate."
      },
      {
        name: "list_estimates",
        method: "GET",
        path: "/api/v1/tickers/{ticker}/estimates",
        price_usdc: 0.01,
        description: "All estimates for a ticker (values + analyst reputation)."
      },
      {
        name: "read_estimate",
        method: "GET",
        path: "/api/v1/estimates/{id}",
        price_usdc: "variable",
        description: "Full thesis for one estimate. Price set by the analyst."
      },
      {
        name: "submit_estimate",
        method: "POST",
        path: "/api/v1/estimates",
        price_usdc: 0,
        description: "Submit an estimate (opinion). Reputation is the only stake."
      },
      {
        name: "leaderboard",
        method: "GET",
        path: "/api/v1/analysts",
        price_usdc: 0,
        description: "Global analyst reputation leaderboard."
      },
      {
        name: "verdict",
        method: "GET",
        path: "/api/v1/verdict/{filingId}",
        price_usdc: 0,
        description: "Post-earnings scoreboard: who was right vs the SEC filing."
      }
    ],
    api: { openapi: `${base}/api/v1/openapi.json` }
  };
}

export function openApiSpec(base: string, env: Env) {
  const paymentExt = {
    "x-402-payment": {
      network: env.X402_NETWORK,
      asset: env.X402_ASSET,
      facilitator: env.X402_FACILITATOR_URL
    }
  };
  return {
    openapi: "3.1.0",
    info: {
      title: "xDEO — Decentralized Earnings Oracle",
      version: "0.1.0",
      description:
        "Machine-native earnings-estimate marketplace. x402-gated (USDC on Base). " +
        "Zero custody, public SEC EDGAR data only, no investment advice."
    },
    servers: [{ url: base }],
    paths: {
      "/api/v1/tickers": {
        get: { summary: "List tickers", responses: ok() }
      },
      "/api/v1/tickers/{ticker}": {
        get: { summary: "Ticker + free consensus", parameters: [p("ticker")], responses: ok() }
      },
      "/api/v1/tickers/{ticker}/estimates": {
        get: {
          summary: "List estimates (x402 $0.01)",
          parameters: [p("ticker")],
          responses: { ...ok(), "402": { description: "Payment required" } },
          ...paymentExt
        }
      },
      "/api/v1/estimates/{id}": {
        get: {
          summary: "Read estimate thesis (x402, analyst-priced)",
          parameters: [p("id")],
          responses: { ...ok(), "402": { description: "Payment required" } },
          ...paymentExt
        }
      },
      "/api/v1/estimates": {
        post: { summary: "Submit estimate", responses: ok() }
      },
      "/api/v1/analysts": { get: { summary: "Leaderboard", responses: ok() } },
      "/api/v1/analysts/{address}": {
        get: { summary: "Analyst profile", parameters: [p("address")], responses: ok() }
      },
      "/api/v1/verdict/{filingId}": {
        get: { summary: "Post-earnings verdict", parameters: [p("filingId")], responses: ok() }
      },
      "/api/v1/agents/manifest.json": { get: { summary: "Agent manifest", responses: ok() } },
      "/api/v1/agents/leaderboard": { get: { summary: "Agent bounty leaderboard", responses: ok() } }
    }
  };
}

function ok() {
  return { "200": { description: "OK" } };
}
function p(name: string) {
  return { name, in: "path", required: true, schema: { type: "string" } };
}
