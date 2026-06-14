# SML Uptime Sentinel

A tiny always-on Cloudflare cron worker that keeps the ScriptMasterLabs fleet
warm 24/7. Render free-tier services sleep after ~15 min idle (≈50s cold start
for the next visitor); this worker pings them every 5 minutes so they never
spin down.

- **Always-on:** Cloudflare crons fire reliably from the edge — no keepalive,
  no babysitting. (More reliable than GitHub Actions crons, which drift enough
  to let dynos sleep.)
- **Free:** ~9 pings × 288 runs/day ≈ 2.6k subrequests/day, far under the
  Workers free tier.
- **Zero new secrets:** deploys via `uptime-deploy.yml` using the same
  `CLOUDFLARE_API_TOKEN` already configured for xDEO.

## What it watches

The list lives in `wrangler.toml` → `UPTIME_TARGETS` (comma-separated). Edit it
and push — it redeploys automatically. Current targets are the canonical Render
service URLs from `SqueezeOS/CLAUDE.md`.

## Endpoints

- `GET /` — live ping of every target (status + latency). Use it as a dashboard
  or an external monitor's check URL.

## Deploy

Automatic on merge to `main` (paths `uptime/**`). Manual: Actions tab →
`uptime-deploy` → Run workflow. Live at `https://sml-uptime.<subdomain>.workers.dev`.
