# xDEO — Deployment Reference

Quick reference for deploying xDEO to Cloudflare Workers. Keep this handy.

> ⚠️ **The only true secret (the Cloudflare API token) is NOT stored in this file
> and must never be.** Secrets go ONLY in GitHub → Settings → Secrets → Actions,
> where they are encrypted and write-only. A token in a file = an account that
> gets drained. Everything below is non-secret resource info, safe to keep.

---

## Cloudflare resources (already created + wired into wrangler.toml)

| What | Value | Where it's used |
|------|-------|-----------------|
| Account ID | `de174553560f13ed28ab35f8fc160215` | `wrangler.toml` → `account_id` |
| D1 database ID | `87531ee2-9c6b-48bf-aa6a-01737f534915` | `wrangler.toml` → `[[d1_databases]] database_id` |
| D1 database name | `xdeo` (label) | `wrangler.toml` → `database_name` |
| KV namespace ID | `e8879156f30a4b8bb398b50a56abbc55` | `wrangler.toml` → `[[kv_namespaces]] id` |
| KV namespace name | `xdeo-KV` (label) | — |

These are identifiers, not credentials. They're already committed in `wrangler.toml`.

---

## GitHub Secrets (you set these — only 2 required)

Add at: **github.com/Timwal78/SqueezeOS → Settings → Secrets and variables → Actions → New repository secret**

| Secret name | What it is | Where to get it |
|-------------|-----------|-----------------|
| `CLOUDFLARE_API_TOKEN` | **THE secret.** Lets GitHub deploy to your CF account. | dash.cloudflare.com/profile/api-tokens → Create Token → "Edit Cloudflare Workers" template |
| `X402_PAY_TO` | Your Base wallet address (`0x...`). **USDC fees land here.** | Your MetaMask / Coinbase Wallet, Base network |

Optional:

| Secret name | What it is |
|-------------|-----------|
| `X402_DEV_BYPASS_TOKEN` | Local/dev test bypass. Skip for production. |

---

## How deploys happen

`.github/workflows/xdeo-deploy.yml` runs automatically on every merge to `main`
that touches `xdeo/**`. It:

1. Runs typecheck + all tests (deploy aborts if anything fails)
2. Applies D1 migrations to the live database
3. Deploys the Worker
4. Sets the `X402_PAY_TO` secret on the Worker

You can also trigger it manually: **Actions tab → xdeo-deploy → Run workflow.**

---

## Live URLs (after first deploy)

- Worker:   `https://xdeo.<your-subdomain>.workers.dev`
- Health:   `/api/status`
- Share:    `/share.html`
- Manifest: `/.well-known/agent-manifest.json`
- MCP:      `/mcp`

## Revenue endpoints

| Endpoint | Price |
|----------|-------|
| `GET /api/v1/tickers/:t/estimates` | $0.01 USDC |
| `GET /api/v1/estimates/:id` | analyst-priced $0.01–$5.00 |
| `GET /api/v1/estimates/:id/ai-thesis` | $0.75 USDC |
