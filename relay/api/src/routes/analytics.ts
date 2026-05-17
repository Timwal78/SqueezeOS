import { Router, Request, Response } from "express";
import { publicRateLimit } from "../middleware/rateLimit";
import {
  getProtocolStats,
  getVolumeTimeSeries,
  getReputationLeaderboard,
  getEvaluatorPerformance,
} from "../services/analytics";

const router = Router();
const CACHE_TTL = 60; // 60 second cache for analytics (non-financial data)

function setCacheHeaders(res: Response): void {
  res.set("Cache-Control", `public, max-age=${CACHE_TTL}`);
}

// GET /api/v1/analytics/stats — Protocol-wide summary
router.get("/stats", publicRateLimit, async (req: Request, res: Response) => {
  const network = (req.query.network as string) ?? "xrpl_testnet";
  setCacheHeaders(res);
  const stats = await getProtocolStats(network);
  res.json(stats);
});

// GET /api/v1/analytics/volume?days=30 — Volume time series
router.get("/volume", publicRateLimit, async (req: Request, res: Response) => {
  const network = (req.query.network as string) ?? "xrpl_testnet";
  const days = Math.min(parseInt(String(req.query.days ?? "30"), 10), 365);
  setCacheHeaders(res);
  const series = await getVolumeTimeSeries(network, days);
  res.json({ series, network, days });
});

// GET /api/v1/analytics/leaderboard — Top reputation scores
router.get("/leaderboard", publicRateLimit, async (req: Request, res: Response) => {
  const network = (req.query.network as string) ?? "xrpl_testnet";
  const limit = Math.min(parseInt(String(req.query.limit ?? "20"), 10), 100);
  setCacheHeaders(res);
  const leaderboard = await getReputationLeaderboard(network, limit);
  res.json({ leaderboard, network });
});

// GET /api/v1/analytics/evaluators — Evaluator performance rankings
router.get("/evaluators", publicRateLimit, async (req: Request, res: Response) => {
  const network = (req.query.network as string) ?? "xrpl_testnet";
  const limit = Math.min(parseInt(String(req.query.limit ?? "20"), 10), 100);
  setCacheHeaders(res);
  const performance = await getEvaluatorPerformance(network, limit);
  res.json({ evaluators: performance, network });
});

export default router;
