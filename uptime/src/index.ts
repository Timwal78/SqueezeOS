// SML Uptime Sentinel — a tiny always-on Cloudflare cron worker that keeps the
// whole ScriptMasterLabs fleet warm 24/7.
//
// Render free-tier services spin down after ~15 minutes idle, so the next
// visitor eats a ~50s cold start. This worker pings every service every 5
// minutes (reliable Cloudflare cron) so the dynos never sleep. Any inbound
// request wakes a Render dyno regardless of status code, so a 200/404/302 all
// count as "kept warm".
//
// Zero custody, zero secrets, near-zero cost: ~9 pings × 288 runs/day ≈ 2.6k
// subrequests/day, far under the Workers free tier.

export interface Env {
  // Comma-separated list of URLs to keep warm. Edit in wrangler.toml [vars].
  UPTIME_TARGETS: string;
}

interface PingResult {
  url: string;
  ok: boolean;
  status: number;
  ms: number;
  error?: string;
}

function targets(env: Env): string[] {
  return (env.UPTIME_TARGETS || "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

async function pingOne(url: string): Promise<PingResult> {
  const t0 = Date.now();
  try {
    // 25s budget: a cold Render dyno can take ~50s, but we only need to *trigger*
    // the wake — we don't have to wait for it to finish booting.
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 25_000);
    const res = await fetch(url, {
      method: "GET",
      redirect: "manual",
      signal: ctrl.signal,
      headers: { "User-Agent": "SML-Uptime-Sentinel/1.0 (+keepalive)" },
      cf: { cacheTtl: 0, cacheEverything: false }
    });
    clearTimeout(timer);
    return { url, ok: true, status: res.status, ms: Date.now() - t0 };
  } catch (e) {
    return { url, ok: false, status: 0, ms: Date.now() - t0, error: String(e) };
  }
}

async function pingAll(env: Env): Promise<PingResult[]> {
  return Promise.all(targets(env).map(pingOne));
}

export default {
  // Manual / health view: GET / returns a live ping of every target.
  async fetch(_req: Request, env: Env): Promise<Response> {
    const results = await pingAll(env);
    const warm = results.filter((r) => r.ok).length;
    return new Response(
      JSON.stringify(
        { service: "sml-uptime-sentinel", checked: results.length, warm, results },
        null,
        2
      ),
      { headers: { "Content-Type": "application/json", "Cache-Control": "no-store" } }
    );
  },

  // Every 5 minutes (wrangler.toml): keep the whole fleet warm.
  async scheduled(_event: unknown, env: Env, ctx: { waitUntil: (p: Promise<unknown>) => void }) {
    ctx.waitUntil(
      pingAll(env).then((r) => {
        const warm = r.filter((x) => x.ok).length;
        console.log(`sml-uptime: kept ${warm}/${r.length} warm`, JSON.stringify(r));
      })
    );
  }
};
