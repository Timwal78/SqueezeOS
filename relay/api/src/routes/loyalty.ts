import { Router, Request, Response } from "express";
import { query, queryOne } from "../db/pool";
import { strictRateLimit, publicRateLimit } from "../middleware/rateLimit";
import {
  computeParticipantLoyalty,
  computeEvaluatorLoyalty,
  getLoyaltyBenefits,
} from "../../../sdk/src/loyalty";

const router = Router();

// GET /api/v1/loyalty/:address — Full loyalty profile for an address
router.get("/:address", publicRateLimit, async (req: Request, res: Response) => {
  const { address } = req.params;

  // Fetch participant stats
  const jobStats = await queryOne<{
    jobs: string;
    volume: string;
    dates: string[];
  }>(
    `SELECT
       COUNT(DISTINCT j.id) AS jobs,
       COALESCE(SUM(j.amount), 0) AS volume,
       ARRAY_AGG(EXTRACT(EPOCH FROM j.completed_at)) FILTER (WHERE j.completed_at IS NOT NULL) AS dates
     FROM jobs j
     WHERE (j.hirer = $1 OR j.worker = $1) AND j.status = 'completed'`,
    [address]
  );

  const jobsCompleted = parseInt(jobStats?.jobs ?? "0", 10);
  const totalVolume = parseFloat(jobStats?.volume ?? "0");
  const activityDates = (jobStats?.dates ?? []).map((d) => parseFloat(String(d)));

  const participant = computeParticipantLoyalty(
    address,
    jobsCompleted,
    totalVolume,
    activityDates
  );

  // Fetch evaluator stats (if evaluator)
  const evalStats = await queryOne<{
    total_votes: string;
    accuracy: string;
    days_since_join: string;
    earned: string;
  }>(
    `SELECT
       e.total_votes,
       COALESCE(e.accuracy, 0) AS accuracy,
       COALESCE(EXTRACT(DAY FROM NOW() - e.created_at), 0) AS days_since_join,
       COALESCE(SUM(CASE WHEN re.event_type = 'evaluator_rewarded' THEN re.amount ELSE 0 END), 0) AS earned
     FROM evaluators e
     LEFT JOIN reputation_events re ON re.address = e.address
     WHERE e.address = $1 AND e.status = 'active'
     GROUP BY e.total_votes, e.accuracy, e.created_at`,
    [address]
  );

  const evaluatorProfile = evalStats
    ? computeEvaluatorLoyalty(
        address,
        parseInt(evalStats.total_votes, 10),
        parseFloat(evalStats.accuracy),
        parseInt(evalStats.days_since_join, 10),
        parseFloat(evalStats.earned)
      )
    : null;

  // Effective tier (best of participant vs evaluator for benefits)
  const effectiveTier = evaluatorProfile?.tier ?? participant.tier;
  const benefits = getLoyaltyBenefits(effectiveTier);

  res.json({
    address,
    participant,
    evaluator: evaluatorProfile,
    effectiveTier,
    benefits,
  });
});

// GET /api/v1/loyalty/governance/proposals — Active governance proposals
router.get("/governance/proposals", publicRateLimit, async (req: Request, res: Response) => {
  const proposals = await query<Record<string, unknown>>(
    `SELECT * FROM governance_proposals
     WHERE expires_at > NOW() AND status = 'active'
     ORDER BY created_at DESC`,
    []
  ).catch(() => [] as Record<string, unknown>[]);

  res.json({ proposals });
});

// POST /api/v1/loyalty/governance/vote — Submit governance vote (legend tier only)
router.post(
  "/governance/vote",
  strictRateLimit,
  async (req: Request, res: Response) => {
    const { voter, proposalId, choice, txHash } = req.body;
    if (!voter || !proposalId || !choice || !txHash) {
      res.status(400).json({ error: "voter, proposalId, choice, txHash required", code: "MISSING_FIELDS" });
      return;
    }

    // Verify voter is legend tier
    const jobCount = await queryOne<{ count: string }>(
      `SELECT COUNT(DISTINCT j.id) AS count FROM jobs j
       WHERE (j.hirer = $1 OR j.worker = $1) AND j.status = 'completed'`,
      [voter]
    );
    if (parseInt(jobCount?.count ?? "0", 10) < 200) {
      res.status(403).json({
        error: "Legend tier (200+ completed jobs) required for governance voting",
        code: "INSUFFICIENT_TIER",
      });
      return;
    }

    // Record vote (governance_proposals table created by migration)
    await query(
      `INSERT INTO governance_votes (voter, proposal_id, choice, tx_hash)
       VALUES ($1, $2, $3, $4)
       ON CONFLICT (voter, proposal_id) DO UPDATE SET choice = $3, tx_hash = $4`,
      [voter, proposalId, choice, txHash]
    ).catch((err) => {
      // Table may not exist yet — graceful degradation
      res.status(503).json({ error: "Governance not yet available", code: "NOT_READY" });
    });

    res.status(201).json({ success: true, voter, proposalId, choice });
  }
);

export default router;
