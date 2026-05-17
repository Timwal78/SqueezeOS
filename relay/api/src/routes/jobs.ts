/**
 * Job management routes.
 *
 * IMPORTANT: The server NEVER signs transactions or holds keys.
 * Routes here coordinate job state and return unsigned transaction data
 * for clients to sign and submit independently.
 */

import { Router, Request, Response } from "express";
import { v4 as uuidv4 } from "uuid";
import { query, queryOne } from "../db/pool";
import { requireFields } from "../middleware/validate";
import { strictRateLimit } from "../middleware/rateLimit";
import { getChannelInfo } from "../services/xrpl";
import { logger } from "../services/logger";

const router = Router();

// POST /api/v1/jobs — Register a new job (after hirer has created channel on-chain)
router.post(
  "/",
  strictRateLimit,
  requireFields("channelId", "hirer", "worker", "amount", "token", "milestones", "txHash"),
  async (req: Request, res: Response) => {
    const {
      channelId,
      hirer,
      worker,
      amount,
      token,
      milestones,
      txHash,
      evaluatorPool = "default",
      timeoutDays = 7,
      multiSigConfig,
      network = "xrpl_testnet",
    } = req.body;

    // Verify the channel actually exists on XRPL before recording
    const channel = await getChannelInfo(network, channelId).catch(() => null);
    if (!channel) {
      res.status(400).json({
        error: "Channel not found on XRPL. Create the channel on-chain first.",
        code: "CHANNEL_NOT_FOUND",
      });
      return;
    }

    // Verify channel parties match job params
    if (channel.account !== hirer || channel.destination !== worker) {
      res.status(400).json({
        error: "Channel account/destination does not match hirer/worker",
        code: "CHANNEL_MISMATCH",
      });
      return;
    }

    const id = uuidv4();
    const [job] = await query<Record<string, unknown>>(
      `INSERT INTO jobs
         (id, channel_id, hirer, worker, amount, token, milestones, evaluator_pool,
          timeout_days, multi_sig_config, tx_hash, network)
       VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb,$8,$9,$10::jsonb,$11,$12)
       RETURNING *`,
      [
        id,
        channelId,
        hirer,
        worker,
        amount,
        token,
        JSON.stringify(milestones),
        evaluatorPool,
        timeoutDays,
        JSON.stringify(multiSigConfig ?? null),
        txHash,
        network,
      ]
    );

    // Record reputation event for hirer (job initiated)
    await query(
      `INSERT INTO reputation_events (address, event_type, job_id, amount, metadata)
       VALUES ($1, 'job_completed', $2, $3, $4::jsonb)`,
      [hirer, id, amount, JSON.stringify({ action: "job_created", token, worker })]
    ).catch((err) => logger.warn("Failed to record rep event:", err));

    logger.info(`Job created: ${id} channel=${channelId} hirer=${hirer} worker=${worker}`);

    res.status(201).json({
      jobId: job.id,
      channelId: job.channel_id,
      status: job.status,
      txHash: job.tx_hash,
    });
  }
);

// GET /api/v1/jobs/:id — Get job details
router.get("/:id", async (req: Request, res: Response) => {
  const job = await queryOne<Record<string, unknown>>(
    "SELECT * FROM jobs WHERE id = $1",
    [req.params.id]
  );

  if (!job) {
    res.status(404).json({ error: "Job not found", code: "NOT_FOUND" });
    return;
  }

  res.json(formatJob(job));
});

// GET /api/v1/jobs?hirer=&worker=&status= — List jobs
router.get("/", async (req: Request, res: Response) => {
  const { hirer, worker, status, limit = "20", offset = "0" } = req.query;

  const conditions: string[] = [];
  const params: unknown[] = [];
  let paramIdx = 1;

  if (hirer) {
    conditions.push(`hirer = $${paramIdx++}`);
    params.push(hirer);
  }
  if (worker) {
    conditions.push(`worker = $${paramIdx++}`);
    params.push(worker);
  }
  if (status) {
    conditions.push(`status = $${paramIdx++}`);
    params.push(status);
  }

  const where = conditions.length ? `WHERE ${conditions.join(" AND ")}` : "";
  params.push(Math.min(parseInt(String(limit), 10), 100));
  params.push(Math.max(parseInt(String(offset), 10), 0));

  const jobs = await query<Record<string, unknown>>(
    `SELECT * FROM jobs ${where} ORDER BY created_at DESC LIMIT $${paramIdx} OFFSET $${paramIdx + 1}`,
    params
  );

  res.json({ jobs: jobs.map(formatJob), limit, offset });
});

// PATCH /api/v1/jobs/:id/status — Update job status (after on-chain action verified)
router.patch("/:id/status", async (req: Request, res: Response) => {
  const { status, txHash, completedAt } = req.body;
  const validStatuses = ["funded", "active", "disputed", "completed", "cancelled"];

  if (!validStatuses.includes(status)) {
    res.status(400).json({ error: "Invalid status", code: "INVALID_STATUS" });
    return;
  }

  const job = await queryOne<Record<string, unknown>>(
    "SELECT * FROM jobs WHERE id = $1",
    [req.params.id]
  );

  if (!job) {
    res.status(404).json({ error: "Job not found", code: "NOT_FOUND" });
    return;
  }

  const updated = await queryOne<Record<string, unknown>>(
    `UPDATE jobs SET status = $1, tx_hash = COALESCE($2, tx_hash),
      completed_at = CASE WHEN $1 = 'completed' THEN NOW() ELSE completed_at END
     WHERE id = $3 RETURNING *`,
    [status, txHash, req.params.id]
  );

  if (status === "completed") {
    // Record completion events for both parties
    await query(
      `INSERT INTO reputation_events (address, event_type, job_id, amount, metadata)
       VALUES
         ($1, 'job_completed', $2, $3, $4::jsonb),
         ($5, 'job_completed', $2, $3, $6::jsonb)`,
      [
        job.hirer,
        req.params.id,
        job.amount,
        JSON.stringify({ role: "hirer", txHash }),
        job.worker,
        JSON.stringify({ role: "worker", txHash }),
      ]
    ).catch((err) => logger.warn("Failed to record completion event:", err));
  }

  res.json(formatJob(updated!));
});

function formatJob(job: Record<string, unknown>): Record<string, unknown> {
  return {
    jobId: job.id,
    channelId: job.channel_id,
    hirer: job.hirer,
    worker: job.worker,
    amount: job.amount,
    token: job.token,
    status: job.status,
    milestones: job.milestones,
    evaluatorPool: job.evaluator_pool,
    timeoutDays: job.timeout_days,
    multiSigConfig: job.multi_sig_config,
    txHash: job.tx_hash,
    network: job.network,
    createdAt: job.created_at,
    completedAt: job.completed_at,
    disputeId: job.dispute_id,
  };
}

export default router;
