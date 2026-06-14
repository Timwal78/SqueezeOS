// xDEO — x402 Decentralized Earnings Oracle. Cloudflare Worker entry point.
//
// HTTP routes (Hono) + a scheduled() cron that ingests SEC EDGAR filings and
// auto-scores open estimates. Zero custody: payments settle client -> wallet
// via the x402 facilitator; this worker never holds funds.

import { Hono } from "hono";
import { tickers } from "./routes/tickers.js";
import { estimates } from "./routes/estimates.js";
import { analysts } from "./routes/analysts.js";
import { verdict } from "./routes/verdict.js";
import { agents } from "./routes/agents.js";
import { mcp } from "./mcp/server.js";
import { agentManifest, openApiSpec } from "./lib/manifest.js";
import { estimateCardSvg } from "./og/card.js";
import { runIngest } from "./edgar/ingest.js";
import { CORS_HEADERS } from "./lib/json.js";
import type { Env, Estimate } from "./types.js";

const app = new Hono<{ Bindings: Env }>();

// CORS for browser embeds (leaderboard widgets) + agents.
app.use("*", async (c, next) => {
  if (c.req.method === "OPTIONS") return c.body(null, 204, CORS_HEADERS);
  await next();
  for (const [k, v] of Object.entries(CORS_HEADERS)) c.header(k, v);
});

app.get("/", (c) =>
  c.json({
    name: "xDEO — Decentralized Earnings Oracle",
    status: "ok",
    docs: "/api/v1/openapi.json",
    manifest: "/.well-known/agent-manifest.json",
    mcp: "/mcp",
    legal:
      "Information marketplace. Estimates are opinions, not securities or investment advice. Zero custody."
  })
);

app.get("/api/status", async (c) => {
  const counts = await c.env.DB.prepare(
    `SELECT
       (SELECT COUNT(*) FROM analysts)  AS analysts,
       (SELECT COUNT(*) FROM estimates) AS estimates,
       (SELECT COUNT(*) FROM filings)   AS filings,
       (SELECT COUNT(*) FROM reads)     AS reads`
  ).first();
  return c.json({ status: "ok", counts });
});

// REST API
app.route("/api/v1/tickers", tickers);
app.route("/api/v1/estimates", estimates);
app.route("/api/v1/analysts", analysts);
app.route("/api/v1/verdict", verdict);
app.route("/api/v1/agents", agents);

// MCP JSON-RPC
app.route("/mcp", mcp);

// Discovery surfaces
app.get("/api/v1/openapi.json", (c) =>
  c.json(openApiSpec(new URL(c.req.url).origin, c.env))
);
app.get("/.well-known/agent-manifest.json", (c) =>
  c.json(agentManifest(new URL(c.req.url).origin, c.env))
);

// Shareable OG card for an estimate (SVG)
app.get("/og/estimate/:id.svg", async (c) => {
  const est = await c.env.DB.prepare(
    `SELECT e.*, a.handle, a.reputation, a.accuracy, a.tier
       FROM estimates e JOIN analysts a ON a.address = e.analyst
      WHERE e.id = ?`
  )
    .bind(c.req.param("id"))
    .first<Estimate & { handle: string | null; reputation: number; accuracy: number; tier: string }>();
  if (!est) return c.json({ error: "estimate not found" }, 404);
  const svg = estimateCardSvg({
    ticker: est.ticker,
    handle: est.handle ?? est.analyst.slice(0, 10),
    predicted: est.predicted,
    metric: est.metric,
    confidence: est.confidence,
    reputation: est.reputation,
    accuracy: est.accuracy,
    tier: est.tier,
    period: `${est.fiscal_period} ${est.fiscal_year}`
  });
  return c.body(svg, 200, {
    "Content-Type": "image/svg+xml",
    "Cache-Control": "public, max-age=300"
  });
});

// llms.txt is served from /public by the ASSETS binding (static).

app.notFound((c) => c.json({ error: "not found" }, 404));

export default {
  fetch: app.fetch,

  // 5-minute cron: pull new EDGAR filings, score open estimates.
  async scheduled(_event: ScheduledController, env: Env, ctx: ExecutionContext) {
    ctx.waitUntil(
      runIngest(env)
        .then((r) => console.log(`xDEO ingest: ${r.filings} filings, ${r.scored} scored`))
        .catch((e) => console.error("xDEO ingest error:", e))
    );
  }
} satisfies ExportedHandler<Env>;
