import { Router, Request, Response } from "express";
import { query, queryOne } from "../db/pool";
import { requireFields } from "../middleware/validate";
import { strictRateLimit } from "../middleware/rateLimit";
import {
  calculateReputationScore,
  getReputationTier,
  buildReputationScore,
} from "../services/reputation";

const router = Router();

// GET /api/v1/reputation/:address — Get reputation score
router.get("/:address", async (req: Request, res: Response) => {
  const { address } = req.params;

  // Aggregate from reputation_events
  const stats = await queryOne<{
    jobs_completed: string;
    total_disputes: string;
    total_volume: string;
    total_votes: string;
    correct_votes: string;
  }>(
    `SELECT
       COUNT(DISTINCT CASE WHEN re.event_type = 'job_completed' AND j.hirer != $1 THEN j.id END) AS jobs_completed,
       COUNT(DISTINCT CASE WHEN re.event_type = 'dispute_initiated' THEN re.dispute_id END) AS total_disputes,
       COALESCE(SUM(CASE WHEN re.event_type = 'job_completed' THEN re.amount ELSE 0 END), 0) AS total_volume,
       COUNT(DISTINCT CASE WHEN re.event_type = 'evaluator_vote' THEN re.id END) AS total_votes,
       COUNT(DISTINCT CASE WHEN re.event_type = 'evaluator_rewarded' THEN re.id END) AS correct_votes
     FROM reputation_events re
     LEFT JOIN jobs j ON re.job_id = j.id
     WHERE re.address = $1`,
    [address]
  );

  const completedJobs = parseInt(stats?.jobs_completed ?? "0", 10);
  const totalDisputes = parseInt(stats?.total_disputes ?? "0", 10);
  const totalVolume = parseFloat(stats?.total_volume ?? "0");
  const totalVotes = parseInt(stats?.total_votes ?? "0", 10);
  const correctVotes = parseInt(stats?.correct_votes ?? "0", 10);

  const disputeRate = completedJobs > 0 ? totalDisputes / completedJobs : 0;
  const evaluatorAccuracy =
    totalVotes > 0 ? correctVotes / totalVotes : null;

  // Get attestation data
  const attestations = await query<{ attester: string }>(
    "SELECT attester FROM attestations WHERE attestee = $1",
    [address]
  );
  const attestationsGiven = await queryOne<{ count: string }>(
    "SELECT COUNT(*) AS count FROM attestations WHERE attester = $1",
    [address]
  );

  // Get evaluator stake info
  const evaluator = await queryOne<{ stake_amount: string; created_at: string; specializations: string[] }>(
    "SELECT stake_amount, created_at, specializations FROM evaluators WHERE address = $1 AND status = 'active'",
    [address]
  );

  const stakeAmount = parseFloat(evaluator?.stake_amount ?? "0");
  const stakeDurationDays = evaluator?.created_at
    ? Math.floor((Date.now() - new Date(evaluator.created_at).getTime()) / (1000 * 60 * 60 * 24))
    : 0;

  const metrics = {
    jobs_completed: completedJobs,
    total_volume: totalVolume,
    dispute_rate: disputeRate,
    evaluator_accuracy: evaluatorAccuracy,
    stake_duration_days: stakeDurationDays,
    specializations: evaluator?.specializations ?? [],
    joined_at: "",
    last_active: "",
    vouched_by: attestations.map((a) => a.attester),
    attestations_given: parseInt(attestationsGiven?.count ?? "0", 10),
  };

  const score = buildReputationScore(address, metrics);
  score.stakeAmount = stakeAmount;

  res.json(score);
});

// POST /api/v1/reputation/attest — Issue a cryptographic attestation
router.post(
  "/attest",
  strictRateLimit,
  requireFields("attester", "attestee", "context", "signature"),
  async (req: Request, res: Response) => {
    const { attester, attestee, context, signature, jobId } = req.body;

    // Check attester has sufficient reputation (platinum tier required)
    // In production: verify signature cryptographically
    const attesterStats = await queryOne<{ count: string }>(
      `SELECT COUNT(*) AS count FROM reputation_events
       WHERE address = $1 AND event_type = 'job_completed'`,
      [attester]
    );
    const completedJobs = parseInt(attesterStats?.count ?? "0", 10);

    if (completedJobs < 10) {
      res.status(403).json({
        error: "Attester needs at least 10 completed jobs to issue attestations",
        code: "INSUFFICIENT_REPUTATION",
      });
      return;
    }

    await query(
      `INSERT INTO attestations (attester, attestee, context, signature, job_id)
       VALUES ($1,$2,$3,$4,$5)
       ON CONFLICT (attester, attestee, context) DO NOTHING`,
      [attester, attestee, context, signature, jobId ?? null]
    );

    await query(
      `INSERT INTO reputation_events (address, event_type, job_id, metadata)
       VALUES
         ($1, 'attestation_given', $3, '{"role":"attester"}'::jsonb),
         ($2, 'attestation_received', $3, '{"role":"attestee"}'::jsonb)`,
      [attester, attestee, jobId ?? null]
    ).catch(() => null);

    res.status(201).json({ success: true, attester, attestee });
  }
);

// GET /api/v1/reputation/:address/events — Reputation event history
router.get("/:address/events", async (req: Request, res: Response) => {
  const { limit = "50", offset = "0" } = req.query;

  const events = await query<Record<string, unknown>>(
    `SELECT * FROM reputation_events WHERE address = $1
     ORDER BY created_at DESC LIMIT $2 OFFSET $3`,
    [
      req.params.address,
      Math.min(parseInt(String(limit), 10), 200),
      parseInt(String(offset), 10),
    ]
  );

  res.json({ events, address: req.params.address });
});

export default router;
