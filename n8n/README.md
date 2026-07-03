# n8n — S1→S4 orchestration upgrade

The AEO self-advertising loop currently runs as a GitHub Actions cron
(`.github/workflows/aeo-selfad.yml`, daily at 06:00 ET). That keeps working
with zero setup. This directory is the upgrade path if/when you want
retries, branching logic, or a visual run history instead of GitHub Actions
logs — it is **optional**, not required for the loop to keep running.

## Deploy n8n on Render

1. Render dashboard → **New → Web Service**
2. Choose **"Deploy an existing image from a registry"**
3. Image: `docker.io/n8nio/n8n:latest`
4. Add a **persistent disk** (Render → Disks tab) mounted at `/home/node/.n8n`
   — without this, workflows and credentials are wiped on every redeploy.
5. Environment variables:
   | Var | Value |
   |---|---|
   | `N8N_BASIC_AUTH_ACTIVE` | `true` |
   | `N8N_BASIC_AUTH_USER` | pick a username |
   | `N8N_BASIC_AUTH_PASSWORD` | pick a strong password |
   | `N8N_HOST` | the Render URL once assigned, e.g. `sml-n8n.onrender.com` |
   | `N8N_PROTOCOL` | `https` |
   | `WEBHOOK_URL` | `https://sml-n8n.onrender.com/` |
   | `GENERIC_TIMEZONE` | `America/New_York` |
6. Deploy. First load will prompt for the basic-auth credentials above.

## Import the S1→S4 workflow

1. In n8n: **Workflows → Import from File**
2. Select `n8n/workflows/s1-s4-aeo-loop.json`
3. The imported workflow has a **Schedule Trigger** (06:00 America/New_York,
   matching the existing GitHub Action cadence) followed by four HTTP
   Request nodes hitting the same endpoints as
   `.github/scripts/aeo_selfad_loop.py`:
   - `GET /api/graph/gaps/` (S1)
   - `GET /api/scriptmaster/narrative` (S2)
   - `GET /api/citation-score/` (S3)
   - `GET /x402/agent-economy/` (S4)
   - final `POST /api/events/push` with the combined summary
4. Activate the workflow (toggle top-right).

## Cutover

Once the n8n workflow has run successfully a few times, disable the
GitHub Actions cron by setting `schedule:` to a commented-out block in
`.github/workflows/aeo-selfad.yml` (keep `workflow_dispatch` so it's still
manually runnable as a fallback). Don't delete the script — n8n's HTTP
Request nodes hit the same endpoints it does, so it stays useful for local
testing and as a reference if a node's config ever drifts.
