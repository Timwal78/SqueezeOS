import { Router, Request, Response } from "express";
import { v4 as uuidv4 } from "uuid";
import { query, queryOne } from "../db/pool";
import { requireFields } from "../middleware/validate";
import { strictRateLimit } from "../middleware/rateLimit";
import { selectEvaluatorsForDispute } from "../services/evaluatorSelector";
import { logger } from "../services/logger";
import { validateVote, buildVoteMessage } from "../../../sdk/src/voting";
import { verifySignature } from "xrpl";

const router = Router();

// POST /api/v1/disputes — Initiate a dispute
router.post(
  "/",
  strictRateLimit,
  requireFields("jobId", "initiator", "reason", "requestedOutcome"),
  async (req: Request, res: Response) => {
    const { jobId, initiator, reason, evidenceHashes = [], requestedOutcome } = req.body;

    const validOutcomes = ["release_to_hirer", "release_to_worker", "partial"];
    if (!validOutcomes.includes(requestedOutcome)) {
      res.status(400).json({ error: "Invalid requestedOutcome", code: "INVALID_OUTCOME" });
      return;
    }

    const job = await queryOne<Record<string, unknown>>(
      "SELECT * FROM jobs WHERE id = $1",
      [jobId]
    );
    if (!job) {
      res.status(404).json({ error: "Job not found", code: "NOT_FOUND" });
      return;
    }

    if (job.status === "completed" || job.status === "cancelled") {
      res.status(409).json({ error: "Cannot dispute a closed job", code: "JOB_CLOSED" });
      return;
    }

    if (job.hirer !== initiator && job.worker !== initiator) {
      res.status(403).json({ error: "Only job parties can initiate disputes", code: "UNAUTHORIZED" });
      return;
    }

    if (job.dispute_id) {
      res.status(409).json({ error: "Dispute already exists for this job", code: "DISPUTE_EXISTS" });
      return;
    }

    // Select evaluators from the pool (VRF-based selection)
    const evaluators = await selectEvaluatorsForDispute(
      job.evaluator_pool as string,
      job.network as string,
      jobId
    );

    const disputeId = uuidv4();
    await query(
      `INSERT INTO disputes (id, job_id, initiator, reason, evidence, requested_outcome, selected_evaluators)
       VALUES ($1,$2,$3,$4,$5::text[],$6,$7::jsonb)`,
      [
        disputeId,
        jobId,
        initiator,
        reason,
        evidenceHashes,
        requestedOutcome,
        JSON.stringify(evaluators),
      ]
    );

    // Link dispute to job and update status
    await query(
      "UPDATE jobs SET status = 'disputed', dispute_id = $1 WHERE id = $2",
      [disputeId, jobId]
    );

    // Record reputation event
    await query(
      `INSERT INTO reputation_events (address, event_type, job_id, dispute_id, metadata)
       VALUES ($1, 'dispute_initiated', $2, $3, $4::jsonb)`,
      [initiator, jobId, disputeId, JSON.stringify({ requestedOutcome })]
    ).catch((err) => logger.warn("Failed to record dispute event:", err));

    logger.info(`Dispute created: ${disputeId} job=${jobId} initiator=${initiator}`);

    res.status(201).json({
      disputeId,
      jobId,
      status: "pending",
      selectedEvaluators: evaluators,
      createdAt: new Date().toISOString(),
    });
  }
);

// GET /api/v1/disputes/:id — Get dispute status
router.get("/:id", async (req: Request, res: Response) => {
  const dispute = await queryOne<Record<string, unknown>>(
    "SELECT * FROM disputes WHERE id = $1",
    [req.params.id]
  );
  if (!dispute) {
    res.status(404).json({ error: "Dispute not found", code: "NOT_FOUND" });
    return;
  }
  res.json(formatDispute(dispute));
});

// POST /api/v1/disputes/:id/vote — Submit evaluator vote with cryptographic verification
router.post(
  "/:id/vote",
  strictRateLimit,
  requireFields("evaluator", "vote", "signature", "publicKey", "timestamp"),
  async (req: Request, res: Response) => {
    const { evaluator, vote, signature, publicKey, timestamp, evidenceCids = [] } = req.body;
    const validVotes = ["hirer", "worker", "partial"];

    if (!validVotes.includes(vote)) {
      res.status(400).json({ error: "Invalid vote", code: "INVALID_VOTE" });
      return;
    }

    const dispute = await queryOne<Record<string, unknown>>(
      "SELECT * FROM disputes WHERE id = $1",
      [req.params.id]
    );
    if (!dispute) {
      res.status(404).json({ error: "Dispute not found", code: "NOT_FOUND" });
      return;
    }
    if (dispute.status === "resolved") {
      res.status(409).json({ error: "Dispute already resolved", code: "ALREADY_RESOLVED" });
      return;
    }

    // Verify evaluator is in the selected list
    const selected = dispute.selected_evaluators as Array<{ address: string }>;
    if (!selected.some((e) => e.address === evaluator)) {
      res.status(403).json({ error: "Not a selected evaluator", code: "NOT_SELECTED" });
      return;
    }

    // Check for duplicate vote
    const votes = dispute.votes as Array<{ evaluator: string; vote?: string }>;
    if (votes.some((v) => v.evaluator === evaluator)) {
      res.status(409).json({ error: "Already voted", code: "DUPLICATE_VOTE" });
      return;
    }

    // Cryptographically verify the vote signature
    try {
      validateVote(
        { payload: { disputeId: req.params.id, jobId: dispute.job_id as string, vote, evidenceCids, evaluator, timestamp }, signature, publicKey },
        req.params.id,
        dispute.job_id as string
      );
    } catch (err) {
      const code = (err as { code?: string }).code ?? "INVALID_SIGNATURE";
      const message = err instanceof Error ? err.message : "Signature verification failed";
      res.status(400).json({ error: message, code });
      return;
    }

    const newVote = { evaluator, vote, signature, timestamp };
    const updatedVotes = [...votes, newVote] as Array<{ evaluator: string; vote: string }>;

    // Check if threshold reached (3-of-5 default)
    const threshold = 3;
    const voteCounts = { hirer: 0, worker: 0, partial: 0 } as Record<string, number>;
    for (const v of updatedVotes) voteCounts[v.vote]++;
    const winner = Object.entries(voteCounts).find(([, count]) => count >= threshold);

    let newStatus = dispute.status as string;
    let outcome: string | null = null;

    if (winner) {
      newStatus = "resolved";
      outcome = winner[0];
    } else if (updatedVotes.length === selected.length && !winner) {
      // All voted, no majority — use plurality
      const plurality = Object.entries(voteCounts).sort((a, b) => b[1] - a[1])[0];
      newStatus = "resolved";
      outcome = plurality[0];
    }

    await query(
      `UPDATE disputes SET votes = $1::jsonb, status = $2, outcome = $3,
        resolved_at = CASE WHEN $2 = 'resolved' THEN NOW() ELSE NULL END
       WHERE id = $4`,
      [JSON.stringify(updatedVotes), newStatus, outcome, req.params.id]
    );

    // Record evaluator vote event
    await query(
      `INSERT INTO reputation_events (address, event_type, dispute_id, metadata)
       VALUES ($1, 'evaluator_vote', $2, $3::jsonb)`,
      [evaluator, req.params.id, JSON.stringify({ vote, outcome })]
    ).catch((err) => logger.warn("Failed to record vote event:", err));

    if (outcome) {
      logger.info(`Dispute ${req.params.id} resolved: ${outcome}`);
    }

    res.json({
      disputeId: req.params.id,
      status: newStatus,
      votesCount: updatedVotes.length,
      outcome: outcome ?? undefined,
    });
  }
);

// GET /api/v1/disputes?jobId= — List disputes for a job
router.get("/", async (req: Request, res: Response) => {
  const { jobId } = req.query;
  if (!jobId) {
    res.status(400).json({ error: "jobId query param required", code: "MISSING_PARAM" });
    return;
  }

  const disputes = await query<Record<string, unknown>>(
    "SELECT * FROM disputes WHERE job_id = $1 ORDER BY created_at DESC",
    [jobId]
  );
  res.json({ disputes: disputes.map(formatDispute) });
});

function formatDispute(d: Record<string, unknown>): Record<string, unknown> {
  return {
    disputeId: d.id,
    jobId: d.job_id,
    initiator: d.initiator,
    reason: d.reason,
    evidence: d.evidence,
    requestedOutcome: d.requested_outcome,
    status: d.status,
    selectedEvaluators: d.selected_evaluators,
    votes: d.votes,
    outcome: d.outcome,
    resolutionTxHash: d.resolution_tx_hash,
    createdAt: d.created_at,
    resolvedAt: d.resolved_at,
  };
}

export default router;
