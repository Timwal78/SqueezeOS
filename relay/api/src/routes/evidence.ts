/**
 * Evidence upload route — stores dispute evidence on IPFS.
 *
 * Evidence is NEVER stored in Relay's database (only the CID is recorded).
 * Content lives on IPFS: decentralized, permanent, Relay-independent.
 */

import { Router, Request, Response } from "express";
import { requireFields } from "../middleware/validate";
import { strictRateLimit } from "../middleware/rateLimit";
import { queryOne } from "../db/pool";
import {
  buildEvidencePackage,
  uploadEvidence,
  fetchEvidence,
  verifyEvidenceIntegrity,
  IPFSConfig,
} from "../../../sdk/src/ipfs";
import { logger } from "../services/logger";

const router = Router();

function getIPFSConfig(): IPFSConfig {
  const provider = (process.env.IPFS_PROVIDER ?? "pinata") as IPFSConfig["provider"];
  return {
    provider,
    apiKey: process.env.PINATA_API_KEY,
    apiSecret: process.env.PINATA_SECRET_KEY,
    gatewayUrl: process.env.IPFS_GATEWAY_URL ?? "https://ipfs.io/ipfs",
    localNodeUrl: process.env.IPFS_LOCAL_NODE_URL,
  };
}

// POST /api/v1/evidence — Upload evidence for a dispute
router.post(
  "/",
  strictRateLimit,
  requireFields("disputeId", "jobId", "submitter", "statement"),
  async (req: Request, res: Response) => {
    const { disputeId, jobId, submitter, statement, files = [] } = req.body;

    // Verify dispute exists and submitter is a party
    const dispute = await queryOne<{ job_id: string; initiator: string }>(
      "SELECT job_id, initiator FROM disputes WHERE id = $1",
      [disputeId]
    );
    if (!dispute) {
      res.status(404).json({ error: "Dispute not found", code: "NOT_FOUND" });
      return;
    }

    const job = await queryOne<{ hirer: string; worker: string }>(
      "SELECT hirer, worker FROM jobs WHERE id = $1",
      [jobId]
    );
    if (!job) {
      res.status(404).json({ error: "Job not found", code: "NOT_FOUND" });
      return;
    }

    if (submitter !== job.hirer && submitter !== job.worker) {
      res.status(403).json({
        error: "Only job parties can submit evidence",
        code: "UNAUTHORIZED",
      });
      return;
    }

    // Validate file count and size
    if (files.length > 10) {
      res.status(400).json({ error: "Maximum 10 files per upload", code: "TOO_MANY_FILES" });
      return;
    }

    const pkg = buildEvidencePackage(disputeId, jobId, submitter, statement, files);

    try {
      const config = getIPFSConfig();
      const result = await uploadEvidence(pkg, config);

      logger.info(`Evidence uploaded: dispute=${disputeId} cid=${result.cid} submitter=${submitter}`);

      res.status(201).json({
        cid: result.cid,
        url: result.url,
        size: result.size,
        disputeId,
        submitter,
      });
    } catch (err) {
      logger.error("IPFS upload failed:", err);
      res.status(503).json({
        error: "Evidence upload failed. Please try again or use a direct IPFS upload.",
        code: "IPFS_UNAVAILABLE",
      });
    }
  }
);

// GET /api/v1/evidence/:cid — Retrieve evidence metadata (not content)
router.get("/:cid", async (req: Request, res: Response) => {
  const { cid } = req.params;
  const gatewayUrl = process.env.IPFS_GATEWAY_URL ?? "https://ipfs.io/ipfs";

  const { valid, package: pkg } = await verifyEvidenceIntegrity(cid, gatewayUrl);
  if (!valid || !pkg) {
    res.status(404).json({ error: "Evidence not found or invalid", code: "NOT_FOUND" });
    return;
  }

  // Return metadata only — evaluators fetch full content directly from IPFS
  res.json({
    cid,
    url: `${gatewayUrl}/${cid}`,
    disputeId: pkg.disputeId,
    jobId: pkg.jobId,
    submitter: pkg.submitter,
    timestamp: pkg.timestamp,
    statement: pkg.statement,
    fileCount: pkg.files.length,
    fileNames: pkg.files.map((f) => f.name),
  });
});

export default router;
