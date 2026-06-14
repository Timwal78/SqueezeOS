// Admin routes — operator-only actions guarded by the ADMIN_TOKEN secret.
// Currently: manually trigger the autonomous House Analyst so you can seed
// estimates on demand (e.g. right before advertising) instead of waiting for
// the daily cron.

import { Hono } from "hono";
import { runAutonomousAnalyst } from "../analyst/autonomous.js";
import type { Env } from "../types.js";

export const admin = new Hono<{ Bindings: Env }>();

/** Constant-time token comparison. Pure — unit-tested. */
export function tokensMatch(expected: string | undefined, got: string | undefined): boolean {
  if (!expected || !got) return false;
  if (expected.length !== got.length) return false;
  let diff = 0;
  for (let i = 0; i < expected.length; i++) {
    diff |= expected.charCodeAt(i) ^ got.charCodeAt(i);
  }
  return diff === 0;
}

// POST /api/v1/admin/seed — run the House Analyst now. Requires X-Admin-Token.
admin.post("/seed", async (c) => {
  if (!c.env.ADMIN_TOKEN) {
    return c.json({ error: "ADMIN_TOKEN not configured on the worker" }, 503);
  }
  if (!tokensMatch(c.env.ADMIN_TOKEN, c.req.header("X-Admin-Token"))) {
    return c.json({ error: "unauthorized" }, 401);
  }
  const result = await runAutonomousAnalyst(c.env);
  return c.json({ ok: true, ...result });
});
