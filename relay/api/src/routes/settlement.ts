/**
 * Settlement routes — multi-sig tx coordination for dispute resolution.
 *
 * Flow:
 *   GET  /api/v1/settlement/:disputeId/draft  → returns unsigned tx for signing
 *   POST /api/v1/settlement/:disputeId/sign   → evaluator submits partial signature
 *   GET  /api/v1/settlement/:disputeId/status → how many sigs collected, ready?
 *   POST /api/v1/settlement/:disputeId/submit → submit combined tx when threshold met
 */

import { Router, Request, Response } from "express";
import { query, queryOne } from "../db/pool";
import { requireFields } from "../middleware/validate";
import { strictRateLimit } from "../middleware/rateLimit";
import {
  checkSettlementReady,
  finalizeSettlement,
  updateEvaluatorStats,
} from "../services/disputeSettler";
import { submitMultiSig } from "../../../sdk/src/multisig";
import { Network, DisputeVote } from "../../../sdk/src/types";
import { DEFAULT_DISPUTE_THRESHOLD } from "../../../sdk/src/constants";
import { logger } from "../services/logger";

const router = Router();

// GET /api/v1/settlement/:disputeId/draft — Get unsigned settlement tx
router.get("/:disputeId/draft", async (req: Request, res: Response) => {
  const draft = await checkSettlementReady(req.params.disputeId);

  if (!draft) {
    // Check if dispute exists and threshold not yet met
    const dispute = await queryOne<{ status: string; votes: DisputeVote[] }>(
      "SELECT status, votes FROM disputes WHERE id = $1",
      [req.params.disputeId]
    );
    if (!dispute) {
      res.status(404).json({ error: "Dispute not found", code: "NOT_FOUND" });
      return;
    }
    res.json({
      ready: false,
      status: dispute.status,
      votesCollected: (dispute.votes as DisputeVote[]).length,
      threshold: DEFAULT_DISPUTE_THRESHOLD,
    });
    return;
  }

  res.json({
    ready: true,
    disputeId: draft.disputeId,
    outcome: draft.outcome,
    unsignedTxJson: draft.unsignedTxJson,
    amountToHirer: draft.amountToHirer,
    amountToWorker: draft.amountToWorker,
    pendingSignatures: draft.pendingSignatures,
    threshold: DEFAULT_DISPUTE_THRESHOLD,
  });
});

// POST /api/v1/settlement/:disputeId/sign — Submit evaluator partial signature
router.post(
  "/:disputeId/sign",
  strictRateLimit,
  requireFields("evaluator", "txBlob"),
  async (req: Request, res: Response) => {
    const { evaluator, txBlob } = req.body;

    // Verify evaluator is selected for this dispute
    const dispute = await queryOne<{
      id: string;
      job_id: string;
      status: string;
      selected_evaluators: Array<{ address: string }>;
    }>(
      "SELECT id, job_id, status, selected_evaluators FROM disputes WHERE id = $1",
      [req.params.disputeId]
    );

    if (!dispute) {
      res.status(404).json({ error: "Dispute not found", code: "NOT_FOUND" });
      return;
    }
    if (dispute.status === "resolved") {
      res.status(409).json({ error: "Dispute already resolved", code: "RESOLVED" });
      return;
    }

    const selected = dispute.selected_evaluators as Array<{ address: string }>;
    if (!selected.some((e) => e.address === evaluator)) {
      res.status(403).json({ error: "Not a selected evaluator", code: "NOT_SELECTED" });
      return;
    }

    // Store partial signature (append to settlement_signatures JSONB)
    await query(
      `UPDATE disputes SET
         settlement_signatures = COALESCE(settlement_signatures, '[]'::jsonb)
           || $1::jsonb
       WHERE id = $2`,
      [JSON.stringify([{ evaluator, txBlob, timestamp: Date.now() }]), req.params.disputeId]
    );

    // Check if we have enough signatures to submit
    const updated = await queryOne<{
      settlement_signatures: Array<{ evaluator: string; txBlob: string }>;
      job_id: string;
      outcome: string | null;
    }>(
      "SELECT settlement_signatures, job_id, outcome FROM disputes WHERE id = $1",
      [req.params.disputeId]
    );

    const sigs = updated?.settlement_signatures ?? [];
    if (sigs.length >= DEFAULT_DISPUTE_THRESHOLD) {
      res.json({
        signaturesCollected: sigs.length,
        threshold: DEFAULT_DISPUTE_THRESHOLD,
        readyToSubmit: true,
        message: "Threshold reached. Call POST /submit to finalize.",
      });
    } else {
      res.json({
        signaturesCollected: sigs.length,
        threshold: DEFAULT_DISPUTE_THRESHOLD,
        readyToSubmit: false,
        remaining: DEFAULT_DISPUTE_THRESHOLD - sigs.length,
      });
    }
  }
);

// GET /api/v1/settlement/:disputeId/status — Check signature collection status
router.get("/:disputeId/status", async (req: Request, res: Response) => {
  const dispute = await queryOne<{
    status: string;
    outcome: string | null;
    resolution_tx_hash: string | null;
    settlement_signatures: Array<{ evaluator: string }> | null;
  }>(
    "SELECT status, outcome, resolution_tx_hash, settlement_signatures FROM disputes WHERE id = $1",
    [req.params.disputeId]
  );

  if (!dispute) {
    res.status(404).json({ error: "Dispute not found", code: "NOT_FOUND" });
    return;
  }

  const sigs = dispute.settlement_signatures ?? [];
  res.json({
    status: dispute.status,
    outcome: dispute.outcome,
    resolutionTxHash: dispute.resolution_tx_hash,
    signaturesCollected: sigs.length,
    threshold: DEFAULT_DISPUTE_THRESHOLD,
    readyToSubmit: sigs.length >= DEFAULT_DISPUTE_THRESHOLD && dispute.status !== "resolved",
    signers: sigs.map((s) => s.evaluator),
  });
});

// POST /api/v1/settlement/:disputeId/submit — Submit combined multi-sig tx
router.post("/:disputeId/submit", strictRateLimit, async (req: Request, res: Response) => {
  const dispute = await queryOne<{
    id: string;
    job_id: string;
    status: string;
    outcome: string | null;
    settlement_signatures: Array<{ evaluator: string; txBlob: string }> | null;
  }>(
    "SELECT id, job_id, status, outcome, settlement_signatures FROM disputes WHERE id = $1",
    [req.params.disputeId]
  );

  if (!dispute) {
    res.status(404).json({ error: "Dispute not found", code: "NOT_FOUND" });
    return;
  }
  if (dispute.status === "resolved") {
    res.status(409).json({ error: "Already resolved", code: "RESOLVED" });
    return;
  }

  const sigs = dispute.settlement_signatures ?? [];
  if (sigs.length < DEFAULT_DISPUTE_THRESHOLD) {
    res.status(400).json({
      error: `Need ${DEFAULT_DISPUTE_THRESHOLD} signatures, have ${sigs.length}`,
      code: "INSUFFICIENT_SIGNATURES",
    });
    return;
  }

  const job = await queryOne<{ network: string }>(
    "SELECT network FROM jobs WHERE id = $1",
    [dispute.job_id]
  );
  if (!job) {
    res.status(404).json({ error: "Job not found", code: "NOT_FOUND" });
    return;
  }

  try {
    const txHash = await submitMultiSig(
      job.network as Network,
      sigs.map((s) => ({ signer: s.evaluator, txBlob: s.txBlob }))
    );

    const outcome = dispute.outcome as "hirer" | "worker" | "partial" | null ?? "partial";
    await finalizeSettlement(req.params.disputeId, txHash, outcome as any);
    await updateEvaluatorStats(req.params.disputeId, outcome as "hirer" | "worker" | "partial");

    logger.info(`Settlement submitted: dispute=${req.params.disputeId} tx=${txHash}`);

    res.json({
      txHash,
      outcome,
      disputeId: req.params.disputeId,
      status: "resolved",
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    logger.error(`Settlement submission failed for ${req.params.disputeId}:`, err);
    res.status(500).json({ error: message, code: "SUBMISSION_FAILED" });
  }
});

export default router;
