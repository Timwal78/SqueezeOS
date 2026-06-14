// /api/v1/tickers — public company list + free consensus, paywalled estimates.

import { Hono } from "hono";
import { requirePayment } from "../x402/middleware.js";
import { EdgarClient } from "../edgar/client.js";
import { now } from "../lib/json.js";
import type { Env, Estimate } from "../types.js";

export const tickers = new Hono<{ Bindings: Env }>();

// GET /api/v1/tickers — list tracked tickers (free)
tickers.get("/", async (c) => {
  const { results } = await c.env.DB.prepare(
    `SELECT ticker, name, cik, exchange FROM tickers ORDER BY ticker`
  ).all();
  return c.json({ tickers: results ?? [] });
});

// GET /api/v1/tickers/:ticker — details + FREE consensus (wisdom of paid crowd)
tickers.get("/:ticker", async (c) => {
  const ticker = c.req.param("ticker").toUpperCase();
  let row = await c.env.DB.prepare(
    `SELECT ticker, name, cik, exchange FROM tickers WHERE ticker=?`
  )
    .bind(ticker)
    .first();

  // Lazily onboard a ticker from EDGAR's public map on first reference.
  if (!row) {
    row = await onboardTicker(c.env, ticker);
    if (!row) return c.json({ error: "unknown ticker" }, 404);
  }

  const consensus = await consensusFor(c.env, ticker);
  return c.json({ ...row, consensus });
});

// GET /api/v1/tickers/:ticker/estimates — all estimates for a ticker (x402 $0.01)
// Returns metadata + predicted values, but NOT the paywalled per-estimate thesis.
tickers.get(
  "/:ticker/estimates",
  requirePayment((c) => ({
    priceUsdc: 0.01,
    resource: new URL(c.req.url).toString(),
    description: `xDEO estimates index for ${(c.req.param("ticker") ?? "").toUpperCase()}`
  })),
  async (c) => {
    const ticker = c.req.param("ticker").toUpperCase();
    const { results } = await c.env.DB.prepare(
      `SELECT e.id, e.ticker, e.analyst, e.metric, e.fiscal_year, e.fiscal_period,
              e.predicted, e.confidence, e.price_usdc, e.status, e.score,
              e.error_pct, e.created_at, a.reputation, a.accuracy, a.tier
         FROM estimates e JOIN analysts a ON a.address = e.analyst
        WHERE e.ticker = ?
        ORDER BY a.reputation DESC, e.created_at DESC`
    )
      .bind(ticker)
      .all();
    return c.json({ ticker, count: results?.length ?? 0, estimates: results ?? [] });
  }
);

/** Free consensus: mean predicted EPS for the nearest open period, rep-weighted. */
async function consensusFor(env: Env, ticker: string) {
  const { results } = await env.DB.prepare(
    `SELECT e.predicted, e.fiscal_year, e.fiscal_period, a.reputation
       FROM estimates e JOIN analysts a ON a.address = e.analyst
      WHERE e.ticker = ? AND e.metric = 'eps' AND e.status = 'OPEN'`
  )
    .bind(ticker)
    .all<{ predicted: number; fiscal_year: number; fiscal_period: string; reputation: number }>();

  const rows = results ?? [];
  if (rows.length === 0) return { available: false, n: 0 };

  // Pick the most-populated open period.
  const byPeriod = new Map<string, typeof rows>();
  for (const r of rows) {
    const k = `${r.fiscal_year}-${r.fiscal_period}`;
    byPeriod.set(k, [...(byPeriod.get(k) ?? []), r]);
  }
  let best: { key: string; rows: typeof rows } | null = null;
  for (const [key, rs] of byPeriod) {
    if (!best || rs.length > best.rows.length) best = { key, rows: rs };
  }
  const sel = best!.rows;
  const simpleMean = sel.reduce((s, r) => s + r.predicted, 0) / sel.length;
  const wsum = sel.reduce((s, r) => s + Math.max(r.reputation, 1), 0);
  const weighted = sel.reduce((s, r) => s + r.predicted * Math.max(r.reputation, 1), 0) / wsum;

  return {
    available: true,
    period: best!.key,
    n: sel.length,
    mean_eps: round(simpleMean, 4),
    reputation_weighted_eps: round(weighted, 4)
  };
}

async function onboardTicker(env: Env, ticker: string) {
  const edgar = new EdgarClient(env.EDGAR_USER_AGENT);
  const map = await edgar
    .tickerMap()
    .catch(() => ({}) as Record<string, { cik: string; name: string }>);
  const hit = map[ticker];
  if (!hit) return null;
  await env.DB.prepare(
    `INSERT OR IGNORE INTO tickers (ticker, cik, name, exchange, created_at)
     VALUES (?,?,?,?,?)`
  )
    .bind(ticker, hit.cik, hit.name, null, now())
    .run();
  return { ticker, name: hit.name, cik: hit.cik, exchange: null };
}

function round(x: number, dp: number): number {
  const f = 10 ** dp;
  return Math.round(x * f) / f;
}
