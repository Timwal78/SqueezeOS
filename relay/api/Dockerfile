FROM node:20-alpine AS builder
WORKDIR /app

# Copy monorepo manifests first for layer caching
COPY package.json package-lock.json ./
COPY sdk/package.json ./sdk/
COPY api/package.json ./api/
COPY mcp-paywall/package.json ./mcp-paywall/
COPY indexer/package.json ./indexer/

# Install all workspace deps
RUN npm ci --workspace=api --workspace=sdk --include-workspace-root

# Copy source
COPY sdk/ ./sdk/
COPY api/ ./api/

# Build SDK first (api imports from ../../sdk/src directly, no separate build needed for ts imports)
WORKDIR /app/api
RUN npm run build

FROM node:20-alpine AS runner
RUN addgroup -S relay && adduser -S relay -G relay
WORKDIR /app

COPY --from=builder /app/api/dist ./dist
COPY --from=builder /app/api/package.json ./
COPY --from=builder /app/node_modules ./node_modules

# SDK source needed at runtime (relative imports go to ../../sdk/src)
COPY --from=builder /app/sdk ./sdk

USER relay
EXPOSE 3001
ENV NODE_ENV=production
CMD ["node", "dist/index.js"]
