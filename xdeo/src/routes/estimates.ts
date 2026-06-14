// /api/v1/estimates — submit estimates, read single estimate (paywalled thesis),
// and generate AI-powered thesis analysis (x402 $0.75, 24h KV cache).

import { Hono } from "hono";
import { requirePayment, readPayment } from "../x402/middleware.js";
import { EdgarClient } from "../edgar/client.js";
import { normalizePeriod } from "../edgar/xbrl.js";
import { advanceStreak } from "../reputation/engine.js";
import { uuid, now, utcDay, lower, isAddress } from "../lib/json.js";
import { publishEvent } from "../stream/publish.js";
import { generateThesis } from "../ai/thesis.js";
import type { ThesisResult } from "../ai/thesis.js";
import type { Env, Estimate } from "../types.js";

export const estimates = new Hono<{ Bindings: Env }>();

interface SubmitBody {
  ticker?: string;
  analyst?: string;
  metric?: string;
  fiscal_year?: number;
  fiscal_period?: string;
  predicted?: number;
  confidence?: number;
  thesis?: string;
  price_usdc?: number;
  referrer?: string;
}

// POST /api/v1/estimates — submit an estimate (an OPINION, not a security).
// No funds are bonded here (zero custody); reputation is the only stake.
estimates.post("/", async (c) => {
  let body: SubmitBody;
  try {
    body = (await c.req.json()) as SubmitBody;
  } catch {
    return c.json({ error: "invalid JSON body" }, 400);
  }

  const ticker = (body.ticker ?? "").toUpperCase();
  const analyst = lower(body.analyst ?? "");
  const metric = body.metric === "revenue" ? "revenue" : "eps";
  const fp = normalizePeriod(body.fiscal_period ?? null);

  if (!ticker) return c.json({ error: "ticker required" }, 400);
  if (!isAddress(analyst)) return c.json({ error: "valid analyst address required" }, 400);
  if (typeof body.predicted !== "number" || !Number.isFinite(body.predicted))
    return c.json({ error: "predicted (number) required" }, 400);
  if (typeof body.fiscal_year !== "number" || !fp)
    return c.json({ error: "fiscal_year and fiscal_period (Q1..Q4|FY) required" }, 400);
  if (!body.thesis || body.thesis.length < 10)
    return c.json({ error: "thesis required (>=10 chars)" }, 400);
  if (body.thesis.length > 4000)
    return c.json({ error: "thesis too long (max 4000 chars)" }, 400);

  // Anti-spam: cap submissions per analyst (and per source IP) per UTC day so a
  // bot can't flood the public leaderboard/consensus or run up EDGAR/AI calls.
  const allowed = await withinSubmitLimit(c.env, analyst, c.req.header("CF-Connecting-IP"));
  if (!allowed)
    return c.json({ error: "rate limit exceeded — too many submissions today" }, 429);

  const price = clampPrice(body.price_usdc ?? 0);
  const confidence = clamp01(body.confidence ?? 0.5);

  // Ensure the ticker exists (validates it's a real SEC issuer).
  const known = await ensureTicker(c.env, ticker);
  if (!known) return c.json({ error: "unknown ticker (not found on SEC EDGAR)" }, 404);

  await ensureAnalyst(c.env, analyst, body.referrer);

  const id = uuid();
  await c.env.DB.prepare(
    `INSERT INTO estimates
       (id, ticker, analyst, metric, fiscal_year, fiscal_period, predicted,
        confidence, thesis, price_usdc, status, created_at)
     VALUES (?,?,?,?,?,?,?,?,?,?, 'OPEN', ?)`
  )
    .bind(
      id,
      ticker,
      analyst,
      metric,
      body.fiscal_year,
      fp,
      body.predicted,
      confidence,
      body.thesis,
      price,
      now()
    )
    .run();

  // Streak + estimate count + tier promotion to ANALYST at 5 estimates.
  await bumpAnalystOnSubmit(c.env, analyst);

  // Real-time fan-out (best-effort, off the response path).
  c.executionCtx.waitUntil(
    publishEvent(c.env, "ESTIMATE_SUBMITTED", {
      id,
      ticker,
      analyst,
      metric,
      fiscal_year: body.fiscal_year,
      fiscal_period: fp,
      predicted: body.predicted
    })
  );

  return c.json({ id, status: "OPEN", ticker, metric, fiscal_year: body.fiscal_year, fiscal_period: fp });
});

// GET /api/v1/tickers/:ticker/estimate/:id is aliased here as
// GET /api/v1/estimates/:id — single estimate + thesis (x402, price set by analyst)
estimates.get(
  "/:id",
  // Price is dynamic: whatever the analyst set. Free (0) estimates skip the gate.
  requirePayment(async (c) => {
    const est = await c.env.DB.prepare(`SELECT price_usdc, ticker FROM estimates WHERE id=?`)
      .bind(c.req.param("id"))
      .first<{ price_usdc: number; ticker: string }>();
    return {
      priceUsdc: est?.price_usdc ?? 0,
      resource: new URL(c.req.url).toString(),
      description: `xDEO estimate thesis ${c.req.param("id")}`,
      // Pay the analyst directly (zero custody) when configured per-analyst.
      // For MVP, settle to the protocol wallet which sweeps to analysts.
    };
  }),
  async (c) => {
    const id = c.req.param("id");
    const est = await c.env.DB.prepare(
      `SELECT e.*, a.reputation, a.accuracy, a.tier
         FROM estimates e JOIN analysts a ON a.address = e.analyst
        WHERE e.id = ?`
    )
      .bind(id)
      .first<Estimate & { reputation: number; accuracy: number; tier: string }>();
    if (!est) return c.json({ error: "estimate not found" }, 404);

    // Record the paid read for analyst earnings accounting + agent affiliate.
    const payment = readPayment(c);
    if (payment.amountUsdc > 0) {
      await recordRead(c.env, id, payment, c.req.header("X-AGENT-ID") ?? null);
    }

    return c.json(est);
  }
);

// GET /api/v1/estimates/:id/ai-thesis — AI-synthesized thesis. x402 $0.75 USDC.
// Runs once via Workers AI (Llama 3.1 8B), caches result in KV for 24h.
// Every read is charged; the generation cost is amortized across all reads of the same thesis.
estimates.get(
  "/:id/ai-thesis",
  requirePayment((_c) => ({
    priceUsdc: 0.75,
    resource: new URL(_c.req.url).toString(),
    description: `xDEO AI thesis for estimate ${_c.req.param("id")}`
  })),
  async (c) => {
    const id = c.req.param("id");
    const cacheKey = `ai-thesis:${id}`;

    // Serve cached thesis immediately (still charges for read).
    const cached = await c.env.KV.get<ThesisResult>(cacheKey, "json");
    if (cached) {
      const payment = readPayment(c);
      if (payment.amountUsdc > 0) {
        await recordRead(c.env, id, payment, c.req.header("X-AGENT-ID") ?? null);
      }
      return c.json({ ...cached, cached: true });
    }

    // Load estimate + analyst joined row.
    const est = await c.env.DB.prepare(
      `SELECT e.*, a.handle, a.reputation, a.accuracy, a.tier, a.scored_count
         FROM estimates e JOIN analysts a ON a.address = e.analyst
        WHERE e.id = ?`
    )
      .bind(id)
      .first<
        Estimate & {
          handle: string | null;
          reputation: number;
          accuracy: number;
          tier: string;
          scored_count: number;
        }
      >();
    if (!est) return c.json({ error: "estimate not found" }, 404);

    // Load actual filing result if this estimate has been scored.
    const filing = est.filing_id
      ? await c.env.DB.prepare(
          `SELECT eps_actual, revenue_actual, period_end FROM filings WHERE id = ?`
        )
          .bind(est.filing_id)
          .first<{ eps_actual: number | null; revenue_actual: number | null; period_end: string | null }>()
      : null;

    const thesis = await generateThesis(c.env.AI, {
      estimate: {
        ticker: est.ticker,
        analyst: est.analyst,
        metric: est.metric,
        fiscal_year: est.fiscal_year,
        fiscal_period: est.fiscal_period,
        predicted: est.predicted,
        confidence: est.confidence,
        thesis: est.thesis,
        status: est.status,
        score: est.score,
        error_pct: est.error_pct
      },
      analyst: {
        handle: est.handle,
        reputation: est.reputation,
        accuracy: est.accuracy,
        tier: est.tier,
        scored_count: est.scored_count
      },
      filing: filing ?? null
    });

    // Cache for 24 hours — thesis doesn't change after generation.
    await c.env.KV.put(cacheKey, JSON.stringify(thesis), { expirationTtl: 86400 });

    const payment = readPayment(c);
    if (payment.amountUsdc > 0) {
      await recordRead(c.env, id, payment, c.req.header("X-AGENT-ID") ?? null);
    }

    return c.json(thesis);
  }
);

async function recordRead(
  env: Env,
  estimateId: string,
  payment: { payer: string | null; txHash: string | null; amountUsdc: number },
  agentId: string | null
) {
  const protocolBps = Number(env.PROTOCOL_FEE_BPS);
  const agentBps = agentId ? Number(env.AGENT_AFFILIATE_BPS) : 0;
  const protocolFee = (payment.amountUsdc * protocolBps) / 10000;
  const agentFee = (payment.amountUsdc * agentBps) / 10000;

  await env.DB.prepare(
    `INSERT INTO reads
       (id, estimate_id, reader, agent_id, amount_usdc, protocol_fee, agent_fee, tx_hash, created_at)
     VALUES (?,?,?,?,?,?,?,?,?)`
  )
    .bind(uuid(), estimateId, payment.payer, agentId, payment.amountUsdc, protocolFee, agentFee, payment.txHash, now())
    .run();

  if (agentId) {
    await env.DB.prepare(
      `UPDATE agents SET reads_driven = reads_driven + 1, fees_earned = fees_earned + ?
        WHERE agent_id = ?`
    )
      .bind(agentFee, agentId)
      .run();
  }
}

async function ensureTicker(env: Env, ticker: string): Promise<boolean> {
  const row = await env.DB.prepare(`SELECT 1 FROM tickers WHERE ticker=?`).bind(ticker).first();
  if (row) return true;
  const edgar = new EdgarClient(env.EDGAR_USER_AGENT);
  const map = await edgar
    .tickerMap()
    .catch(() => ({}) as Record<string, { cik: string; name: string }>);
  const hit = map[ticker];
  if (!hit) return false;
  await env.DB.prepare(
    `INSERT OR IGNORE INTO tickers (ticker, cik, name, exchange, created_at) VALUES (?,?,?,?,?)`
  )
    .bind(ticker, hit.cik, hit.name, null, now())
    .run();
  return true;
}

async function ensureAnalyst(env: Env, address: string, referrer?: string): Promise<void> {
  const existing = await env.DB.prepare(`SELECT 1 FROM analysts WHERE address=?`).bind(address).first();
  if (existing) return;
  const ref = referrer && isAddress(referrer) ? lower(referrer) : null;
  await env.DB.prepare(
    `INSERT INTO analysts (address, referrer, created_at) VALUES (?,?,?)`
  )
    .bind(address, ref, now())
    .run();
}

async function bumpAnalystOnSubmit(env: Env, address: string): Promise<void> {
  const a = await env.DB.prepare(
    `SELECT estimate_count, streak_days, last_active_day, tier FROM analysts WHERE address=?`
  )
    .bind(address)
    .first<{ estimate_count: number; streak_days: number; last_active_day: string | null; tier: string }>();
  if (!a) return;
  const today = utcDay();
  const streak = advanceStreak(a.last_active_day, a.streak_days, today);
  const count = a.estimate_count + 1;
  // Observer -> Analyst at 5 estimates (spec tier system).
  const tier = a.tier === "OBSERVER" && count >= 5 ? "ANALYST" : a.tier;
  await env.DB.prepare(
    `UPDATE analysts SET estimate_count=?, streak_days=?, last_active_day=?, tier=? WHERE address=?`
  )
    .bind(count, streak, today, tier, address)
    .run();
}

// KV-backed daily submit limiter. Eventually-consistent (good enough for spam
// control). Caps per analyst address and per source IP.
const SUBMIT_CAP_PER_ADDRESS = 50;
const SUBMIT_CAP_PER_IP = 200;

async function withinSubmitLimit(
  env: Env,
  address: string,
  ip: string | undefined
): Promise<boolean> {
  const day = utcDay();
  const checks: Array<{ key: string; cap: number }> = [
    { key: `rl:sub:addr:${day}:${address}`, cap: SUBMIT_CAP_PER_ADDRESS }
  ];
  if (ip) checks.push({ key: `rl:sub:ip:${day}:${ip}`, cap: SUBMIT_CAP_PER_IP });

  for (const { key, cap } of checks) {
    const current = Number((await env.KV.get(key)) ?? "0");
    if (current >= cap) return false;
  }
  // Increment counters (TTL 2 days so they self-expire).
  await Promise.all(
    checks.map(async ({ key }) => {
      const current = Number((await env.KV.get(key)) ?? "0");
      await env.KV.put(key, String(current + 1), { expirationTtl: 172800 });
    })
  );
  return true;
}

function clampPrice(p: number): number {
  if (!Number.isFinite(p) || p < 0) return 0;
  return Math.min(p, 5); // spec: $0.01–$5.00 range
}
function clamp01(x: number): number {
  return Math.min(1, Math.max(0, x));
}
