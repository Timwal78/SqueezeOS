// MCP server (JSON-RPC 2.0) mounted at POST /mcp. Lets Claude/GPT/Gemini call
// xDEO tools natively. Tools proxy to the REST API on the same origin so there
// is a single source of truth for behavior and x402 gating.
//
// Mirrors the SqueezeOS MCP pattern: _dispatch forwards payment headers
// (X-PAYMENT, X-AGENT-ID) so an agent pays through the same flow as REST.

import { Hono } from "hono";
import type { Env } from "../types.js";

export const mcp = new Hono<{ Bindings: Env }>();

const SERVER_INFO = { name: "xdeo", version: "0.1.0" };
const PROTOCOL_VERSION = "2024-11-05";

const TOOLS = [
  {
    name: "list_tickers",
    description: "List all tracked tickers. Free.",
    inputSchema: { type: "object", properties: {} }
  },
  {
    name: "ticker_consensus",
    description: "Ticker details + free reputation-weighted consensus estimate.",
    inputSchema: {
      type: "object",
      properties: { ticker: { type: "string" } },
      required: ["ticker"]
    }
  },
  {
    name: "list_estimates",
    description: "All estimates for a ticker. Costs 0.01 USDC via x402.",
    inputSchema: {
      type: "object",
      properties: {
        ticker: { type: "string" },
        payment_token: { type: "string", description: "base64 x402 payload" }
      },
      required: ["ticker"]
    }
  },
  {
    name: "read_estimate",
    description: "Full thesis for one estimate. Analyst-priced x402 payment.",
    inputSchema: {
      type: "object",
      properties: {
        id: { type: "string" },
        payment_token: { type: "string" }
      },
      required: ["id"]
    }
  },
  {
    name: "submit_estimate",
    description: "Submit an earnings estimate (opinion). Free; reputation is the stake.",
    inputSchema: {
      type: "object",
      properties: {
        ticker: { type: "string" },
        analyst: { type: "string", description: "0x address (Base)" },
        metric: { type: "string", enum: ["eps", "revenue"] },
        fiscal_year: { type: "number" },
        fiscal_period: { type: "string", enum: ["Q1", "Q2", "Q3", "Q4", "FY"] },
        predicted: { type: "number" },
        confidence: { type: "number" },
        thesis: { type: "string" },
        price_usdc: { type: "number" }
      },
      required: ["ticker", "analyst", "fiscal_year", "fiscal_period", "predicted", "thesis"]
    }
  },
  {
    name: "leaderboard",
    description: "Global analyst reputation leaderboard. Free.",
    inputSchema: { type: "object", properties: { limit: { type: "number" } } }
  },
  {
    name: "verdict",
    description: "Post-earnings scoreboard for a filing. Free.",
    inputSchema: {
      type: "object",
      properties: { filingId: { type: "string" } },
      required: ["filingId"]
    }
  }
];

mcp.post("/", async (c) => {
  let req: any;
  try {
    req = await c.req.json();
  } catch {
    return c.json(rpcError(null, -32700, "Parse error"), 200);
  }

  const { id, method, params } = req ?? {};

  switch (method) {
    case "initialize":
      return c.json(
        rpcResult(id, {
          protocolVersion: PROTOCOL_VERSION,
          capabilities: { tools: {} },
          serverInfo: SERVER_INFO
        })
      );
    case "ping":
      return c.json(rpcResult(id, {}));
    case "tools/list":
      return c.json(rpcResult(id, { tools: TOOLS }));
    case "tools/call": {
      const result = await dispatch(c.env, c.req.raw, params?.name, params?.arguments ?? {});
      return c.json(
        rpcResult(id, {
          content: [{ type: "text", text: JSON.stringify(result.body) }],
          isError: !result.ok
        })
      );
    }
    default:
      if (typeof method === "string" && method.startsWith("notifications/")) {
        return c.body(null, 204);
      }
      return c.json(rpcError(id, -32601, `Method not found: ${method}`));
  }
});

/** Proxy a tool call to the REST API on the same origin, forwarding payment. */
async function dispatch(
  env: Env,
  original: Request,
  name: string,
  args: Record<string, any>
): Promise<{ ok: boolean; body: unknown }> {
  const origin = new URL(original.url).origin;
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  // Forward x402 payment + agent affiliate from args or the MCP request headers.
  const pay = args.payment_token ?? original.headers.get("X-PAYMENT");
  if (pay) headers["X-PAYMENT"] = pay;
  const agent = args.agent_id ?? original.headers.get("X-AGENT-ID");
  if (agent) headers["X-AGENT-ID"] = agent;

  let url: string;
  let init: RequestInit = { headers };

  switch (name) {
    case "list_tickers":
      url = `${origin}/api/v1/tickers`;
      break;
    case "ticker_consensus":
      url = `${origin}/api/v1/tickers/${encodeURIComponent(args.ticker)}`;
      break;
    case "list_estimates":
      url = `${origin}/api/v1/tickers/${encodeURIComponent(args.ticker)}/estimates`;
      break;
    case "read_estimate":
      url = `${origin}/api/v1/estimates/${encodeURIComponent(args.id)}`;
      break;
    case "submit_estimate":
      url = `${origin}/api/v1/estimates`;
      init = { method: "POST", headers, body: JSON.stringify(args) };
      break;
    case "leaderboard":
      url = `${origin}/api/v1/analysts${args.limit ? `?limit=${args.limit}` : ""}`;
      break;
    case "verdict":
      url = `${origin}/api/v1/verdict/${encodeURIComponent(args.filingId)}`;
      break;
    default:
      return { ok: false, body: { error: `unknown tool: ${name}` } };
  }

  const res = await fetch(url, init);
  const body = await res.json().catch(() => ({ error: "non-JSON response" }));
  return { ok: res.ok, body };
}

function rpcResult(id: unknown, result: unknown) {
  return { jsonrpc: "2.0", id: id ?? null, result };
}
function rpcError(id: unknown, code: number, message: string) {
  return { jsonrpc: "2.0", id: id ?? null, error: { code, message } };
}
