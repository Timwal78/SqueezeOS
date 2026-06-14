// /api/v1/agents — the AI-agent distribution channel ("Agent Amplification").
//  - manifest.json: machine-readable tool catalog with x402 prices
//  - track: register/declare an agent affiliate (15% of fees it drives)
//  - leaderboard: agents compete on paid usage driven (bounty program)

import { Hono } from "hono";
import { agentManifest } from "../lib/manifest.js";
import { uuid, now, isAddress, lower } from "../lib/json.js";
import type { Env } from "../types.js";

export const agents = new Hono<{ Bindings: Env }>();

// GET /api/v1/agents/manifest.json — discovery for Claude/GPT/Gemini (free)
agents.get("/manifest.json", (c) => {
  const base = new URL(c.req.url).origin;
  return c.json(agentManifest(base, c.env));
});

// POST /api/v1/agents/track — register an agent affiliate (free)
agents.post("/track", async (c) => {
  let body: { agent_id?: string; payout_addr?: string; label?: string };
  try {
    body = await c.req.json();
  } catch {
    return c.json({ error: "invalid JSON" }, 400);
  }
  const agentId = (body.agent_id ?? c.req.header("X-AGENT-ID") ?? "").trim();
  if (!agentId) return c.json({ error: "agent_id required" }, 400);
  const payout = body.payout_addr && isAddress(body.payout_addr) ? lower(body.payout_addr) : null;

  await c.env.DB.prepare(
    `INSERT INTO agents (agent_id, payout_addr, label, created_at)
     VALUES (?,?,?,?)
     ON CONFLICT(agent_id) DO UPDATE SET
       payout_addr = COALESCE(excluded.payout_addr, agents.payout_addr),
       label = COALESCE(excluded.label, agents.label)`
  )
    .bind(agentId, payout, body.label ?? null, now())
    .run();

  return c.json({
    agent_id: agentId,
    affiliate_bps: Number(c.env.AGENT_AFFILIATE_BPS),
    instructions:
      "Send the X-AGENT-ID header on every x402 request you route. You earn " +
      `${Number(c.env.AGENT_AFFILIATE_BPS) / 100}% of fees from reads you drive.`
  });
});

// GET /api/v1/agents/leaderboard — bounty competition standings (free)
agents.get("/leaderboard", async (c) => {
  const { results } = await c.env.DB.prepare(
    `SELECT agent_id, label, reads_driven, fees_earned
       FROM agents ORDER BY reads_driven DESC, fees_earned DESC LIMIT 100`
  ).all();
  const ranked = (results ?? []).map((a, i) => ({ rank: i + 1, ...a }));
  return c.json({ count: ranked.length, agents: ranked });
});
