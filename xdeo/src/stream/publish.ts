// Fire-and-forget publish to the global StreamHub Durable Object. Never throws —
// streaming is best-effort and must not break the request or cron path.

import type { Env } from "../types.js";

export async function publishEvent(
  env: Env,
  type: string,
  data: unknown
): Promise<void> {
  try {
    const id = env.STREAM_HUB.idFromName("global");
    const stub = env.STREAM_HUB.get(id);
    await stub.fetch("https://hub/publish", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ type, data, ts: Date.now() })
    });
  } catch {
    /* best-effort */
  }
}
