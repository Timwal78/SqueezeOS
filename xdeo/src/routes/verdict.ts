// /api/v1/verdict/:filingId — post-earnings scoreboard (free, highly shareable).
// "Who was right, who was wrong" once EDGAR drops the actual number.

import { Hono } from "hono";
import type { Env, Filing } from "../types.js";

export const verdict = new Hono<{ Bindings: Env }>();

verdict.get("/:filingId", async (c) => {
  const id = c.req.param("filingId");
  const filing = await c.env.DB.prepare(`SELECT * FROM filings WHERE id=?`)
    .bind(id)
    .first<Filing>();
  if (!filing) return c.json({ error: "filing not found" }, 404);

  const { results } = await c.env.DB.prepare(
    `SELECT e.id, e.analyst, e.metric, e.predicted, e.score, e.error_pct,
            a.handle, a.reputation, a.tier
       FROM estimates e JOIN analysts a ON a.address = e.analyst
      WHERE e.filing_id = ?
      ORDER BY e.score DESC`
  )
    .bind(id)
    .all<{
      id: string;
      analyst: string;
      metric: string;
      predicted: number;
      score: number;
      error_pct: number;
      handle: string | null;
      reputation: number;
      tier: string;
    }>();

  const scored = results ?? [];
  // Badges drive engagement: top = Nostradamus, bottom = RIP.
  const board = scored.map((e, i) => ({
    rank: i + 1,
    ...e,
    badge:
      i === 0 && e.score >= 80
        ? "NOSTRADAMUS"
        : e.score < 25
          ? "RIP"
          : null
  }));

  return c.json({
    filing: {
      id: filing.id,
      ticker: filing.ticker,
      form: filing.form,
      fiscal_year: filing.fiscal_year,
      fiscal_period: filing.fiscal_period,
      eps_actual: filing.eps_actual,
      revenue_actual: filing.revenue_actual,
      filed_at: filing.filed_at
    },
    scored: board.length,
    verdict: board
  });
});
