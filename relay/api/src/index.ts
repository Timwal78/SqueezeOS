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
