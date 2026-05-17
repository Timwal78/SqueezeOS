FROM node:20-alpine AS builder
WORKDIR /app

COPY package.json package-lock.json ./
COPY sdk/package.json ./sdk/
COPY api/package.json ./api/
COPY mcp-paywall/package.json ./mcp-paywall/
COPY indexer/package.json ./indexer/

RUN npm ci --workspace=indexer --workspace=sdk --include-workspace-root

COPY sdk/ ./sdk/
COPY indexer/ ./indexer/

WORKDIR /app/indexer
RUN npm run build

FROM node:20-alpine AS runner
RUN addgroup -S relay && adduser -S relay -G relay
WORKDIR /app

COPY --from=builder /app/indexer/dist ./dist
COPY --from=builder /app/indexer/package.json ./
COPY --from=builder /app/node_modules ./node_modules

USER relay
ENV NODE_ENV=production
CMD ["node", "dist/index.js"]
