import "dotenv/config";
import express from "express";
import cors from "cors";
import helmet from "helmet";
import { errorHandler } from "./middleware/validate";
import { publicRateLimit } from "./middleware/rateLimit";
import jobsRouter from "./routes/jobs";
import disputesRouter from "./routes/disputes";
import reputationRouter from "./routes/reputation";
import evaluatorsRouter from "./routes/evaluators";
import evidenceRouter from "./routes/evidence";
import settlementRouter from "./routes/settlement";
import analyticsRouter from "./routes/analytics";
import loyaltyRouter from "./routes/loyalty";
import paymentsRouter from "./routes/payments";
import { x402 } from "./middleware/x402";
import { logger } from "./services/logger";

const app = express();
const PORT = parseInt(process.env.PORT ?? "3001", 10);

// Security middleware
app.use(helmet());
app.use(
  cors({
    origin: process.env.CORS_ORIGIN ?? "*",
    methods: ["GET", "POST", "PATCH", "DELETE"],
    allowedHeaders: ["Content-Type", "Authorization", "X-PAYMENT"],
  })
);

// Body parsing (no large payloads — no file uploads server-side)
app.use(express.json({ limit: "64kb" }));
app.use(publicRateLimit);

// Health check (no auth, no DB required)
app.get("/health", (_, res) => {
  res.json({
    status: "ok",
    service: "relay-api",
    version: "0.1.0",
    timestamp: new Date().toISOString(),
    custody: "zero",
  });
});

// API v1 routes
app.use("/api/v1/jobs", jobsRouter);
app.use("/api/v1/disputes", disputesRouter);
app.use("/api/v1/reputation", reputationRouter);
app.use("/api/v1/evaluators", evaluatorsRouter);
app.use("/api/v1/evidence", evidenceRouter);
app.use("/api/v1/settlement", settlementRouter);
app.use("/api/v1/analytics", analyticsRouter);
app.use("/api/v1/loyalty", loyaltyRouter);
app.use("/api/v1/payments", paymentsRouter);

// Premium endpoints gated by x402 micropayment (only when RELAY_FEE_ADDRESS configured)
if (process.env.RELAY_FEE_ADDRESS) {
  app.use(
    "/api/premium/analytics",
    x402({
      network: (process.env.XRPL_NETWORK ?? "xrpl_testnet") as "xrpl_mainnet" | "xrpl_testnet",
      recipientAddress: process.env.RELAY_FEE_ADDRESS,
      priceRlusd: parseFloat(process.env.PREMIUM_PRICE_RLUSD ?? "0.05"),
      endpointId: "premium-analytics",
    }),
    analyticsRouter
  );
  logger.info("Premium analytics endpoint enabled via x402 at /api/premium/analytics");
}

// 404 handler
app.use((_, res) => {
  res.status(404).json({ error: "Not found", code: "NOT_FOUND" });
});

// Error handler (must be last)
app.use(errorHandler);

app.listen(PORT, () => {
  logger.info(`Relay API v0.1.0 listening on port ${PORT}`);
  logger.info(`Network: ${process.env.XRPL_NETWORK ?? "xrpl_testnet"}`);
  logger.info("Zero-custody: ✓ (no private keys, no fund control)");
});

export default app;
