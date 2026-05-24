#!/bin/bash
# PNE Gateway — Railway Deploy Script
# Run this from your machine (not Claude's cloud env)
# Requirements: railway CLI installed (npm install -g @railway/cli)

set -e

TOKEN="525452eb-ae9f-4fba-8348-aad6a5152ca8"
PROJECT_NAME="neural-exchequer"
SERVICE_NAME="pne-gateway"
MACAROON_SECRET="0c05204d6229a91acc6154fe48aa3c6410ebd0f1d4976ef65d29d7d28df69249"

export RAILWAY_TOKEN=$TOKEN

echo "==> Logging in..."
railway whoami

echo "==> Creating project: $PROJECT_NAME"
railway project create --name "$PROJECT_NAME"

echo "==> Linking to repo root (pne/gateway)..."
# Railway will pick up the Dockerfile and railway.toml automatically
cd "$(git rev-parse --show-toplevel)/pne/gateway"

railway link

echo "==> Setting environment variables..."
railway variables set \
  PORT=8402 \
  UPSTREAM_BASE_URL=https://squeezeos-api.onrender.com \
  MACAROON_SECRET=$MACAROON_SECRET \
  RUST_LOG="pne_gateway=info,tower_http=warn" \
  CORS_ORIGINS="https://squeeze-os.vercel.app,https://n-exchequer.io" \
  RATE_LIMIT_UNAUTH=100 \
  AUCTION_WINDOW_MS=5 \
  BASE_PRICE_SATS=100 \
  PLATFORM_FEE_PCT=1.0

echo ""
echo "==> IMPORTANT: Set REDIS_URL manually in Railway dashboard"
echo "    Get a free Redis at https://upstash.com (takes 60 seconds)"
echo "    Then: railway variables set REDIS_URL=redis://..."
echo ""

echo "==> Deploying..."
railway up --service "$SERVICE_NAME" --detach

echo ""
echo "==> Getting your new URL..."
railway domain

echo ""
echo "==> Done. Copy the URL above and send it to Claude."
echo "    Claude will update agents.json, llms.txt, keepalive.yml in one shot."
