import { Router, Request, Response } from "express";
import { query, queryOne } from "../db/pool";
import { strictRateLimit, publicRateLimit } from "../middleware/rateLimit";
import {
  computeParticipantLoyalty,
  computeEvaluatorLoyalty,
  getLoyaltyBenefits,
  computeVolumeFeeDecay,
  computeEffectiveFeeRate,
} from "../../../sdk/src/loyalty";
import { checkTenureEligibility } from "../../../sdk/src/jobs";
import { getOrCompute } from "../services/cache";

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

// GET /api/v1/loyalty/:address/status — Cached fee tier, streak multiplier, tenure (<20ms)
router.get("/:address/status", publicRateLimit, async (req: Request, res: Response) => {
  const { address } = req.params;
  const cacheKey = `loyalty:status:${address}`;

  const status = await getOrCompute(
    cacheKey,
    async () => {
      // Volume + job count
      const jobStats = await queryOne<{ jobs: string; volume: string }>(
        `SELECT
           COUNT(DISTINCT j.id) AS jobs,
           COALESCE(SUM(j.amount), 0) AS volume
         FROM jobs j
         WHERE (j.hirer = $1 OR j.worker = $1) AND j.status = 'completed'`,
        [address]
      );
      const completedJobs = parseInt(jobStats?.jobs ?? "0", 10);
      const cumulativeVolume = parseFloat(jobStats?.volume ?? "0");

      // Tier
      const participant = computeParticipantLoyalty(address, completedJobs, cumulativeVolume, []);

      // Evaluator streak (consecutive accurate votes)
      const evalRow = await queryOne<{
        consecutive: string;
        slash_count: string;
        stake_amount: string;
        days_since_join: string;
      }>(
        `SELECT
           e.correct_votes - COALESCE(
             (SELECT COUNT(*) FROM reputation_events re
              WHERE re.address = $1 AND re.event_type = 'evaluator_slashed'
              AND re.created_at > (
                SELECT COALESCE(MAX(re2.created_at), '1970-01-01')
                FROM reputation_events re2
                WHERE re2.address = $1 AND re2.event_type IN ('evaluator_slashed', 'evaluator_rewarded')
                AND re2.created_at < (
                  SELECT MAX(re3.created_at) FROM reputation_events re3
                  WHERE re3.address = $1 AND re3.event_type = 'evaluator_slashed'
                )
              )), 0
           ) AS consecutive,
           e.slash_count,
           e.stake_amount,
           COALESCE(EXTRACT(DAY FROM NOW() - e.created_at), 0) AS days_since_join
         FROM evaluators e WHERE e.address = $1 AND e.status = 'active'`,
        [address]
      );

      // Simpler approach: fetch last N votes and count streak
      const recentVotes = await query<{ event_type: string; created_at: string }>(
        `SELECT event_type, created_at FROM reputation_events
         WHERE address = $1 AND event_type IN ('evaluator_vote', 'evaluator_slashed', 'evaluator_rewarded')
         ORDER BY created_at DESC LIMIT 100`,
        [address]
      ).catch(() => [] as Array<{ event_type: string; created_at: string }>);

      let consecutiveAccurateVotes = 0;
      for (const ev of recentVotes) {
        if (ev.event_type === "evaluator_slashed") break;
        if (ev.event_type === "evaluator_rewarded") consecutiveAccurateVotes++;
      }

      const streakMultiplier = Math.min(3.0, parseFloat((1.0 + consecutiveAccurateVotes * 0.1).toFixed(4)));

      // Tenure eligibility
      const tenureDays = evalRow ? parseInt(evalRow.days_since_join, 10) : 0;
      const tenure = checkTenureEligibility(tenureDays, completedJobs);

      // Fee rates
      const volumeFeeBps = computeVolumeFeeDecay(cumulativeVolume);
      const effectiveFeeBps = computeEffectiveFeeRate(cumulativeVolume, participant.tier);

      return {
        address,
        tier: participant.tier,
        completedJobs,
        cumulativeVolumeRlusd: cumulativeVolume,
        volumeFeeBps,
        effectiveFeeBps,
        feeDiscountBps: participant.feeDiscountBps,
        streakMultiplier,
        consecutiveAccurateVotes,
        tenureEligible: tenure.eligible,
        tenureDays,
        bondWaivedRlusd: tenure.bondWaivedRlusd,
        canVote: participant.canVote,
      };
    },
    60 // 60s TTL
  );

  res.setHeader("Cache-Control", "public, max-age=60");
  res.json(status);
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
