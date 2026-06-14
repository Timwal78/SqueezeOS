// EDGAR ingestion + auto-scoring. Runs on the 5-minute cron (wrangler.toml).
//
// Pipeline (spec §EDGAR INTEGRATION PIPELINE):
//   1. For each tracked ticker, pull recent submissions.
//   2. Detect new 10-K / 10-Q filings we haven't ingested.
//   3. Fetch the diluted-EPS (and revenue) XBRL facts for the reported period.
//   4. Store the filing with the actual numbers.
//   5. Score every OPEN estimate for that {ticker, fy, fp} within the run.
//
// We only track tickers that have at least one estimate — no point polling the
// whole market. This keeps each cron run well within SEC rate limits.

import { EdgarClient } from "./client.js";
import {
  EPS_TAGS,
  REVENUE_TAGS,
  selectByTags,
  normalizePeriod,
  type PeriodKey
} from "./xbrl.js";
import type { XbrlFact } from "./client.js";
import { scoreOpenEstimatesForFiling } from "../reputation/apply.js";
import { now } from "../lib/json.js";
import type { Env } from "../types.js";

export async function runIngest(env: Env): Promise<{ filings: number; scored: number }> {
  const edgar = new EdgarClient(env.EDGAR_USER_AGENT);

  // Tickers that have at least one open estimate, joined to their CIK.
  const { results } = await env.DB.prepare(
    `SELECT DISTINCT t.ticker AS ticker, t.cik AS cik
       FROM tickers t
       JOIN estimates e ON e.ticker = t.ticker
      WHERE e.status = 'OPEN'`
  ).all<{ ticker: string; cik: string }>();

  let filings = 0;
  let scored = 0;
  for (const row of results ?? []) {
    const r = await ingestTicker(env, edgar, row.ticker, row.cik);
    filings += r.filings;
    scored += r.scored;
  }
  return { filings, scored };
}

/**
 * Ingest any new 10-K/10-Q filings for ONE ticker and score the OPEN estimates
 * they resolve. Shared by the 5-minute cron (open-estimate tickers) and the
 * autonomous analyst (which seeds filing history for the whole watchlist).
 */
export async function ingestTicker(
  env: Env,
  edgar: EdgarClient,
  ticker: string,
  cik: string
): Promise<{ filings: number; scored: number }> {
  const sub = await edgar.submissions(cik);
  if (!sub) return { filings: 0, scored: 0 };
  const recent = sub.filings.recent;

  // Cache concept facts per ticker so we fetch each tag at most once.
  let epsFacts: Record<string, XbrlFact[]> | null = null;
  let revFacts: Record<string, XbrlFact[]> | null = null;

  let newFilings = 0;
  let scored = 0;

  for (let i = 0; i < recent.accessionNumber.length; i++) {
    const form = recent.form[i]!;
    if (form !== "10-K" && form !== "10-Q") continue;

    const accn = recent.accessionNumber[i]!;
    const id = accn.replace(/-/g, "");

    // Skip filings already ingested.
    const seen = await env.DB.prepare(`SELECT 1 FROM filings WHERE id = ?`)
      .bind(id)
      .first();
    if (seen) continue;

    // Lazily load concept facts (only when we actually have a new filing).
    if (!epsFacts) epsFacts = await loadTags(edgar, cik, EPS_TAGS);
    if (!revFacts) revFacts = await loadTags(edgar, cik, REVENUE_TAGS);

    const period = periodFromFacts(epsFacts, accn) ?? periodFromFacts(revFacts, accn);
    if (!period) continue; // can't anchor a fiscal period -> skip (no guessing)

    const eps = selectByTags(epsFacts, EPS_TAGS, period);
    const rev = selectByTags(revFacts, REVENUE_TAGS, period);

    await env.DB.prepare(
      `INSERT OR IGNORE INTO filings
         (id, cik, ticker, form, fiscal_year, fiscal_period, period_end,
          eps_actual, revenue_actual, filed_at, scored, ingested_at)
       VALUES (?,?,?,?,?,?,?,?,?,?,0,?)`
    )
      .bind(
        id,
        cik,
        ticker,
        form,
        period.fiscal_year,
        period.fiscal_period,
        eps?.fact.end ?? recent.reportDate[i] ?? null,
        eps?.fact.val ?? null,
        rev?.fact.val ?? null,
        recent.filingDate[i] ?? null,
        now()
      )
      .run();
    newFilings++;

    scored += await scoreOpenEstimatesForFiling(env, {
      id,
      ticker,
      fiscal_year: period.fiscal_year,
      fiscal_period: period.fiscal_period,
      eps_actual: eps?.fact.val ?? null,
      revenue_actual: rev?.fact.val ?? null
    });
  }

  return { filings: newFilings, scored };
}

async function loadTags(
  edgar: EdgarClient,
  cik: string,
  tags: string[]
): Promise<Record<string, XbrlFact[]>> {
  const out: Record<string, XbrlFact[]> = {};
  for (const tag of tags) {
    const facts = await edgar.concept(cik, tag).catch(() => [] as XbrlFact[]);
    if (facts.length) out[tag] = facts;
  }
  return out;
}

/** Find the {fy, fp} that a given accession reports, straight from XBRL. */
function periodFromFacts(
  factsByTag: Record<string, XbrlFact[]>,
  accn: string
): PeriodKey | null {
  for (const facts of Object.values(factsByTag)) {
    for (const f of facts) {
      if (f.accn === accn && f.fy && normalizePeriod(f.fp)) {
        return { fiscal_year: f.fy, fiscal_period: normalizePeriod(f.fp)! };
      }
    }
  }
  return null;
}
