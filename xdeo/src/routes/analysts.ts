// /api/v1/analysts — leaderboard + individual profiles (all free / public).

import { Hono } from "hono";
import { lower } from "../lib/json.js";
import type { Env, Analyst } from "../types.js";

export const analysts = new Hono<{ Bindings: Env }>();

// GET /api/v1/analysts — global leaderboard (free)
analysts.get("/", async (c) => {
  const limit = Math.min(Number(c.req.query("limit") ?? 100), 500);
  const { results } = await c.env.DB.prepare(
    `SELECT address, handle, reputation, accuracy, scored_count, estimate_count,
            tier, streak_days
       FROM analysts
      WHERE estimate_count > 0
      ORDER BY reputation DESC, accuracy DESC
      LIMIT ?`
  )
    .bind(limit)
    .all<Analyst>();

  const ranked = (results ?? []).map((a, i) => ({ rank: i + 1, ...a }));
  return c.json({ count: ranked.length, analysts: ranked });
});

// GET /api/v1/analysts/:address — profile + estimate history (free)
analysts.get("/:address", async (c) => {
  const address = lower(c.req.param("address"));
  const a = await c.env.DB.prepare(`SELECT * FROM analysts WHERE address=?`)
    .bind(address)
    .first<Analyst>();
  if (!a) return c.json({ error: "analyst not found" }, 404);

  const rankRow = await c.env.DB.prepare(
    `SELECT COUNT(*) AS ahead FROM analysts WHERE reputation > ?`
  )
    .bind(a.reputation)
    .first<{ ahead: number }>();

  const { results: history } = await c.env.DB.prepare(
    `SELECT id, ticker, metric, fiscal_year, fiscal_period, predicted, confidence,
            price_usdc, status, score, error_pct, created_at, scored_at
       FROM estimates WHERE analyst=? ORDER BY created_at DESC LIMIT 200`
  )
    .bind(address)
    .all();

  // Referral tree size (evangelist economy).
  const refs = await c.env.DB.prepare(
    `SELECT COUNT(*) AS n FROM analysts WHERE referrer=?`
  )
    .bind(address)
    .first<{ n: number }>();

  return c.json({
    ...a,
    global_rank: (rankRow?.ahead ?? 0) + 1,
    referrals: refs?.n ?? 0,
    history: history ?? []
  });
});
