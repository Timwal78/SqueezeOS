// Autonomous House Analyst — the supply side of the xDEO flywheel.
//
// On a daily cron, xDEO's own AI reads each watchlist company's REAL EDGAR
// filing history, predicts the next fiscal period's diluted EPS, writes a
// thesis, and submits it as an OPEN estimate under a transparent "House AI"
// identity. The existing EDGAR cron then scores those predictions against the
// real filing when it lands — so the House AI builds a genuine, public,
// hard-won track record exactly like any human analyst.
//
// Integrity: these are real forward predictions made BEFORE the filing, scored
// honestly against SEC data. They are clearly labelled "xDEO House AI" and are
// opinions, not investment advice. No fabricated actuals — every "actual" comes
// from EDGAR via the same scoring pipeline as user estimates.
//
// Cost: runs entirely on Cloudflare Workers AI (the AI binding) + free EDGAR.
// No external API keys.

import { EdgarClient } from "../edgar/client.js";
import { ingestTicker } from "../edgar/ingest.js";
import { advanceStreak } from "../reputation/engine.js";
import { uuid, now, utcDay, lower } from "../lib/json.js";
import { publishEvent } from "../stream/publish.js";
import type { Env } from "../types.js";

export const ANALYST_MODEL = "@cf/meta/llama-3.1-8b-instruct";

// A clearly-labelled, deterministic house identity. The operator can override
// it via HOUSE_ANALYST_ADDRESS to route house-estimate read revenue to their
// own Base wallet identity.
export const HOUSE_ANALYST_FALLBACK = "0xde00000000000000000000000000000000000001";
export const HOUSE_HANDLE = "xDEO House AI";

// Large, liquid, frequent filers — a sensible default watchlist. This is a
// configuration of which public companies to track (real symbols), not data;
// all financials come from EDGAR. Override with the XDEO_UNIVERSE env var.
export const DEFAULT_UNIVERSE = [
  "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AMD",
  "NFLX", "AVGO", "JPM", "V", "WMT", "COST", "PLTR"
];

export interface FilingRow {
  fiscal_year: number;
  fiscal_period: string;
  eps_actual: number | null;
  revenue_actual: number | null;
  filed_at: string | null;
}

export interface AnalystContext {
  ticker: string;
  name: string;
  history: FilingRow[]; // chronological (oldest -> newest)
  target: { fiscal_year: number; fiscal_period: string };
}

export interface AnalystEstimate {
  predicted: number;
  confidence: number; // 0..1
  thesis: string;
}

/** The fiscal period that chronologically follows {fy, fp}. Pure. */
export function nextPeriod(
  fy: number,
  fp: string
): { fiscal_year: number; fiscal_period: string } {
  switch (fp.toUpperCase()) {
    case "Q1": return { fiscal_year: fy, fiscal_period: "Q2" };
    case "Q2": return { fiscal_year: fy, fiscal_period: "Q3" };
    case "Q3": return { fiscal_year: fy, fiscal_period: "FY" };
    case "Q4": return { fiscal_year: fy, fiscal_period: "FY" };
    case "FY": return { fiscal_year: fy + 1, fiscal_period: "Q1" };
    default: return { fiscal_year: fy, fiscal_period: "FY" };
  }
}

/** Parse the watchlist from env (comma-separated) or fall back to defaults. Pure. */
export function parseUniverse(raw: string | undefined): string[] {
  if (!raw) return DEFAULT_UNIVERSE;
  const list = raw
    .split(",")
    .map((s) => s.trim().toUpperCase())
    .filter((s) => /^[A-Z.\-]{1,8}$/.test(s));
  return list.length ? list : DEFAULT_UNIVERSE;
}

const SYSTEM_PROMPT =
  "You are a disciplined sell-side equity analyst forecasting a company's next " +
  "reported diluted EPS from its historical filing trend. Output ONLY a valid " +
  "JSON object — no markdown, no preamble. Your forecast is an informational " +
  "opinion, not investment advice.";

/** Build the forecasting prompt from real EDGAR history. Pure, unit-tested. */
export function buildAnalystPrompt(ctx: AnalystContext): string {
  const rows = ctx.history
    .map(
      (h) =>
        `  ${h.fiscal_period} FY${h.fiscal_year}: ` +
        `EPS=${h.eps_actual ?? "n/a"}` +
        (h.revenue_actual != null ? `, Revenue=${h.revenue_actual}` : "") +
        (h.filed_at ? ` (filed ${h.filed_at})` : "")
    )
    .join("\n");

  return (
    `Company: ${ctx.name} (${ctx.ticker})\n` +
    `Reported diluted EPS history (chronological, from SEC EDGAR):\n${rows}\n\n` +
    `Forecast the diluted EPS for: ${ctx.target.fiscal_period} FY${ctx.target.fiscal_year}.\n\n` +
    `Respond with exactly this JSON:\n` +
    `{\n` +
    `  "predicted": <number — your diluted EPS forecast>,\n` +
    `  "confidence": <number 0..1 — your conviction>,\n` +
    `  "thesis": "<2-4 sentences: the trend, seasonality, and key drivers behind your forecast>"\n` +
    `}`
  );
}

/** Parse the model's JSON forecast. Pure, unit-tested. Throws on unusable output. */
export function parseAnalystResponse(text: string): AnalystEstimate {
  const cleaned = text
    .replace(/```json\s*/gi, "")
    .replace(/```\s*/g, "")
    .trim();
  const start = cleaned.indexOf("{");
  const end = cleaned.lastIndexOf("}");
  if (start === -1 || end === -1 || end <= start) {
    throw new Error("no JSON object in analyst response");
  }
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const parsed: Record<string, any> = JSON.parse(cleaned.slice(start, end + 1));

  const predicted = Number(parsed["predicted"]);
  if (!Number.isFinite(predicted)) {
    throw new Error("analyst response missing a finite 'predicted'");
  }
  const thesis = String(parsed["thesis"] ?? "").trim();
  if (thesis.length < 10) {
    throw new Error("analyst response thesis too short");
  }
  let confidence = Number(parsed["confidence"]);
  if (!Number.isFinite(confidence)) confidence = 0.5;
  confidence = Math.min(1, Math.max(0, confidence));

  return { predicted, confidence, thesis };
}

/** Call Workers AI to produce one forecast. */
export async function generateAnalystEstimate(
  ai: Ai,
  ctx: AnalystContext
): Promise<AnalystEstimate> {
  const messages = [
    { role: "system" as const, content: SYSTEM_PROMPT },
    { role: "user" as const, content: buildAnalystPrompt(ctx) }
  ];
  const out = await (ai as unknown as {
    run: (m: string, i: { messages: typeof messages; max_tokens: number }) => Promise<{ response?: string }>;
  }).run(ANALYST_MODEL, { messages, max_tokens: 500 });
  return parseAnalystResponse(out.response ?? "");
}

function clampPrice(p: number): number {
  if (!Number.isFinite(p) || p < 0) return 0;
  return Math.min(p, 5);
}

/**
 * Run the autonomous analyst: seed the watchlist, ingest fresh filings, and
 * submit House AI EPS forecasts for any period that doesn't have one yet.
 */
export async function runAutonomousAnalyst(
  env: Env
): Promise<{ seeded_tickers: number; estimates: number }> {
  const universe = parseUniverse(env.XDEO_UNIVERSE);
  const edgar = new EdgarClient(env.EDGAR_USER_AGENT);
  const house = lower(env.HOUSE_ANALYST_ADDRESS || HOUSE_ANALYST_FALLBACK);
  const price = clampPrice(Number(env.HOUSE_ESTIMATE_PRICE ?? "0.05"));
  const maxPerRun = Math.max(1, Number(env.HOUSE_MAX_PER_RUN ?? "10"));

  await ensureHouseAnalyst(env, house);

  const map = await edgar
    .tickerMap()
    .catch(() => ({}) as Record<string, { cik: string; name: string }>);

  let seededTickers = 0;
  let estimates = 0;

  for (const ticker of universe) {
    if (estimates >= maxPerRun) break;
    const hit = map[ticker];
    if (!hit) continue;

    // Ensure the ticker is tracked.
    await env.DB.prepare(
      `INSERT OR IGNORE INTO tickers (ticker, cik, name, exchange, created_at)
       VALUES (?,?,?,?,?)`
    )
      .bind(ticker, hit.cik, hit.name, null, now())
      .run();
    seededTickers++;

    // Pull any new real filings (also scores open house estimates that resolved).
    await ingestTicker(env, edgar, ticker, hit.cik).catch(() => ({ filings: 0, scored: 0 }));

    // Latest reported period -> the period we forecast next.
    const latest = await env.DB.prepare(
      `SELECT fiscal_year, fiscal_period FROM filings
        WHERE ticker = ? AND fiscal_period IS NOT NULL AND eps_actual IS NOT NULL
        ORDER BY filed_at DESC LIMIT 1`
    )
      .bind(ticker)
      .first<{ fiscal_year: number; fiscal_period: string }>();
    if (!latest) continue;

    const target = nextPeriod(latest.fiscal_year, latest.fiscal_period);

    // Skip if the house already has an estimate for this exact period.
    const exists = await env.DB.prepare(
      `SELECT 1 FROM estimates
        WHERE analyst = ? AND ticker = ? AND metric = 'eps'
          AND fiscal_year = ? AND fiscal_period = ?`
    )
      .bind(house, ticker, target.fiscal_year, target.fiscal_period)
      .first();
    if (exists) continue;

    // Build chronological EPS history as context.
    const { results: histDesc } = await env.DB.prepare(
      `SELECT fiscal_year, fiscal_period, eps_actual, revenue_actual, filed_at
         FROM filings
        WHERE ticker = ? AND eps_actual IS NOT NULL
        ORDER BY filed_at DESC LIMIT 8`
    )
      .bind(ticker)
      .all<FilingRow>();
    const history = (histDesc ?? []).slice().reverse();
    if (history.length === 0) continue;

    let gen: AnalystEstimate;
    try {
      gen = await generateAnalystEstimate(env.AI, {
        ticker,
        name: hit.name,
        history,
        target
      });
    } catch {
      continue; // bad model output -> skip this ticker this run
    }

    const id = uuid();
    await env.DB.prepare(
      `INSERT INTO estimates
         (id, ticker, analyst, metric, fiscal_year, fiscal_period, predicted,
          confidence, thesis, price_usdc, status, created_at)
       VALUES (?,?,?,?,?,?,?,?,?,?, 'OPEN', ?)`
    )
      .bind(
        id,
        ticker,
        house,
        "eps",
        target.fiscal_year,
        target.fiscal_period,
        gen.predicted,
        gen.confidence,
        gen.thesis,
        price,
        now()
      )
      .run();
    estimates++;

    await bumpHouseOnSubmit(env, house);

    await publishEvent(env, "ESTIMATE_SUBMITTED", {
      id,
      ticker,
      analyst: house,
      metric: "eps",
      fiscal_year: target.fiscal_year,
      fiscal_period: target.fiscal_period,
      predicted: gen.predicted,
      house: true
    });
  }

  return { seeded_tickers: seededTickers, estimates };
}

async function ensureHouseAnalyst(env: Env, address: string): Promise<void> {
  await env.DB.prepare(
    `INSERT OR IGNORE INTO analysts (address, handle, tier, created_at)
     VALUES (?,?, 'ANALYST', ?)`
  )
    .bind(address, HOUSE_HANDLE, now())
    .run();
}

async function bumpHouseOnSubmit(env: Env, address: string): Promise<void> {
  const a = await env.DB.prepare(
    `SELECT estimate_count, streak_days, last_active_day FROM analysts WHERE address = ?`
  )
    .bind(address)
    .first<{ estimate_count: number; streak_days: number; last_active_day: string | null }>();
  if (!a) return;
  const today = utcDay();
  const streak = advanceStreak(a.last_active_day, a.streak_days, today);
  await env.DB.prepare(
    `UPDATE analysts SET estimate_count = ?, streak_days = ?, last_active_day = ? WHERE address = ?`
  )
    .bind(a.estimate_count + 1, streak, today, address)
    .run();
}
