// Applies the pure reputation engine to persisted state when a filing lands.
// Called from the EDGAR cron (ingest.ts) and reused by the verdict endpoint.

import {
  scoreEstimate,
  updateReputation,
  streakMultiplier,
  computeTier
} from "./engine.js";
import { now } from "../lib/json.js";
import type { Env, Analyst, Estimate, Tier } from "../types.js";

export interface ScoringFiling {
  id: string;
  ticker: string;
  fiscal_year: number;
  fiscal_period: string;
  eps_actual: number | null;
  revenue_actual: number | null;
}

/**
 * Score every OPEN estimate matching a filing's {ticker, fy, fp}, update each
 * analyst's reputation, and mark the filing scored. Returns count scored.
 */
export async function scoreOpenEstimatesForFiling(
  env: Env,
  filing: ScoringFiling
): Promise<number> {
  const { results } = await env.DB.prepare(
    `SELECT * FROM estimates
      WHERE status = 'OPEN' AND ticker = ? AND fiscal_year = ? AND fiscal_period = ?`
  )
    .bind(filing.ticker, filing.fiscal_year, filing.fiscal_period)
    .all<Estimate>();

  let count = 0;
  for (const est of results ?? []) {
    const actual = est.metric === "revenue" ? filing.revenue_actual : filing.eps_actual;
    if (actual === null || actual === undefined) continue; // metric not parsed -> leave open

    const result = scoreEstimate({
      predicted: est.predicted,
      actual,
      confidence: est.confidence,
      leadSeconds: Math.max(0, now() - est.created_at)
    });

    const analyst = await getAnalyst(env, est.analyst);
    const mult = streakMultiplier(analyst.streak_days);
    const upd = updateReputation(
      {
        reputation: analyst.reputation,
        accuracy: analyst.accuracy,
        scored_count: analyst.scored_count
      },
      result,
      mult
    );

    const tier: Tier = computeTier({
      reputation: upd.reputation,
      accuracy: upd.accuracy,
      estimate_count: analyst.estimate_count,
      globalRank: await globalRank(env, upd.reputation)
    });

    // Persist estimate + analyst atomically-ish (D1 batch).
    await env.DB.batch([
      env.DB.prepare(
        `UPDATE estimates
            SET status='SCORED', score=?, error_pct=?, filing_id=?, scored_at=?
          WHERE id=?`
      ).bind(result.score, result.errorPct, filing.id, now(), est.id),
      env.DB.prepare(
        `UPDATE analysts
            SET reputation=?, accuracy=?, scored_count=?, tier=?
          WHERE address=?`
      ).bind(upd.reputation, upd.accuracy, upd.scored_count, tier, est.analyst)
    ]);
    count++;
  }

  if (count >= 0) {
    await env.DB.prepare(`UPDATE filings SET scored=1 WHERE id=?`)
      .bind(filing.id)
      .run();
  }
  return count;
}

async function getAnalyst(env: Env, address: string): Promise<Analyst> {
  const a = await env.DB.prepare(`SELECT * FROM analysts WHERE address=?`)
    .bind(address)
    .first<Analyst>();
  if (a) return a;
  // Defensive: an estimate should always have an analyst row, but never crash.
  return {
    address,
    handle: null,
    reputation: 0,
    accuracy: 0,
    scored_count: 0,
    estimate_count: 0,
    tier: "OBSERVER",
    streak_days: 0,
    last_active_day: null,
    referrer: null,
    created_at: now()
  };
}

/** 1-based rank of a reputation value among all analysts (for ORACLE/LEGEND). */
async function globalRank(env: Env, reputation: number): Promise<number> {
  const row = await env.DB.prepare(
    `SELECT COUNT(*) AS ahead FROM analysts WHERE reputation > ?`
  )
    .bind(reputation)
    .first<{ ahead: number }>();
  return (row?.ahead ?? 0) + 1;
}
