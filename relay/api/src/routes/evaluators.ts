import { Router, Request, Response } from "express";
import { query, queryOne } from "../db/pool";
import { requireFields } from "../middleware/validate";
import { strictRateLimit } from "../middleware/rateLimit";
import { logger } from "../services/logger";

const router = Router();

// POST /api/v1/evaluators — Register as evaluator (after staking on-chain)
router.post(
  "/",
  strictRateLimit,
  requireFields("address", "stakeEscrowTx", "stakeAmount", "specializations", "publicKey"),
  async (req: Request, res: Response) => {
    const {
      address,
      stakeEscrowTx,
      stakeAmount,
      specializations,
      publicKey,
      network = "xrpl_testnet",
    } = req.body;

    // Verify publicKey derives to address (prevent impersonation)
    try {
      const { deriveAddress } = require("xrpl");
      const derived = deriveAddress(publicKey);
      if (derived !== address) {
        res.status(400).json({
          error: "publicKey does not correspond to address",
          code: "KEY_MISMATCH",
        });
        return;
      }
    } catch {
      res.status(400).json({ error: "Invalid publicKey", code: "INVALID_KEY" });
      return;
    }

    if (parseFloat(stakeAmount) < 500) {
      res.status(400).json({
        error: "Minimum stake is 500 RLUSD",
        code: "INSUFFICIENT_STAKE",
      });
      return;
    }

    if (!Array.isArray(specializations) || !specializations.length) {
      res.status(400).json({
        error: "At least one specialization required",
        code: "NO_SPECIALIZATIONS",
      });
      return;
    }

    const existing = await queryOne(
      "SELECT id FROM evaluators WHERE address = $1",
      [address]
    );
    if (existing) {
      res.status(409).json({ error: "Already registered", code: "ALREADY_REGISTERED" });
      return;
    }

    const [evaluator] = await query<Record<string, unknown>>(
      `INSERT INTO evaluators (address, stake_amount, stake_escrow_tx, specializations, network, public_key)
       VALUES ($1,$2,$3,$4::text[],$5,$6)
       RETURNING *`,
      [address, stakeAmount, stakeEscrowTx, specializations, network, publicKey]
    );

    logger.info(`Evaluator registered: ${address} stake=${stakeAmount} specs=${specializations.join(",")}`);

    res.status(201).json(formatEvaluator(evaluator));
  }
);

// GET /api/v1/evaluators — List active evaluators
router.get("/", async (req: Request, res: Response) => {
  const { specialization, network = "xrpl_testnet", limit = "50" } = req.query;

  let sql = "SELECT * FROM evaluators WHERE status = 'active' AND network = $1";
  const params: unknown[] = [network];
  let paramIdx = 2;

  if (specialization) {
    sql += ` AND $${paramIdx} = ANY(specializations)`;
    params.push(specialization);
    paramIdx++;
  }

  sql += ` ORDER BY stake_amount DESC, accuracy DESC NULLS LAST LIMIT $${paramIdx}`;
  params.push(Math.min(parseInt(String(limit), 10), 200));

  const evaluators = await query<Record<string, unknown>>(sql, params);
  res.json({ evaluators: evaluators.map(formatEvaluator), count: evaluators.length });
});

// GET /api/v1/evaluators/:address — Get evaluator profile
router.get("/:address", async (req: Request, res: Response) => {
  const evaluator = await queryOne<Record<string, unknown>>(
    "SELECT * FROM evaluators WHERE address = $1",
    [req.params.address]
  );
  if (!evaluator) {
    res.status(404).json({ error: "Evaluator not found", code: "NOT_FOUND" });
    return;
  }
  res.json(formatEvaluator(evaluator));
});

// PATCH /api/v1/evaluators/:address/deregister — Deregister evaluator
router.patch("/:address/deregister", strictRateLimit, async (req: Request, res: Response) => {
  const { signature } = req.body; // TODO: verify signature in production

  const evaluator = await queryOne<Record<string, unknown>>(
    "SELECT * FROM evaluators WHERE address = $1 AND status = 'active'",
    [req.params.address]
  );
  if (!evaluator) {
    res.status(404).json({ error: "Active evaluator not found", code: "NOT_FOUND" });
    return;
  }

  await query(
    "UPDATE evaluators SET status = 'deregistered' WHERE address = $1",
    [req.params.address]
  );

  res.json({ success: true, address: req.params.address });
});

function formatEvaluator(e: Record<string, unknown>): Record<string, unknown> {
  return {
    address: e.address,
    stakeAmount: e.stake_amount,
    stakeEscrowTx: e.stake_escrow_tx,
    specializations: e.specializations,
    accuracy: e.accuracy,
    totalVotes: e.total_votes,
    correctVotes: e.correct_votes,
    slashCount: e.slash_count,
    lastVoteAt: e.last_vote_at,
    status: e.status,
    network: e.network,
    joinedAt: e.created_at,
  };
}

export default router;
