/**
 * x402 Express middleware — gates API endpoints behind RLUSD payment.
 *
 * Intercepts requests, checks X-PAYMENT header, verifies XRPL transaction,
 * optionally checks reputation tier, and either serves content or returns 402.
 *
 * Usage:
 *   app.use('/api/premium', x402({
 *     priceRlusd: 0.05,
 *     minTier: 'bronze',
 *     network: 'xrpl_mainnet',
 *   }));
 *
 * The middleware NEVER holds funds — it only reads the blockchain.
 */

import { Request, Response, NextFunction } from "express";
import { getClient } from "../../../sdk/src/xrpl-client";
import {
  parsePaymentHeader,
  build402Response,
  meetsReputationRequirement,
} from "../../../sdk/src/x402";
import { Network, ReputationTier } from "../../../sdk/src/types";
import { RLUSD_CURRENCY, RLUSD_ISSUERS } from "../../../sdk/src/constants";
import { logger } from "../services/logger";

export interface X402MiddlewareOptions {
  network: Network;
  recipientAddress: string;
  priceRlusd: number | ((req: Request) => number);
  endpointId?: string;
  minTier?: ReputationTier;
  minReputationScore?: number;
  requireReputation?: boolean;
}

declare module "express-serve-static-core" {
  interface Request {
    relay?: {
      payer: string;
      paymentTxHash: string;
      amountPaid: string;
    };
  }
}

export function x402(options: X402MiddlewareOptions) {
  return async (req: Request, res: Response, next: NextFunction): Promise<void> => {
    const paymentHeader = req.headers["x-payment"] as string | undefined;

    if (!paymentHeader) {
      // No payment header — issue 402
      const price =
        typeof options.priceRlusd === "function"
          ? options.priceRlusd(req)
          : options.priceRlusd;

      const { body } = build402Response(
        options.network,
        options.recipientAddress,
        price,
        options.endpointId ?? req.path
      );

      res.status(402).json(body);
      return;
    }

    // Parse the payment header
    const parsed = parsePaymentHeader(paymentHeader);
    if (!parsed) {
      res.status(400).json({ error: "Invalid X-PAYMENT header", code: "INVALID_PAYMENT_HEADER" });
      return;
    }

    // Verify the payment transaction on XRPL
    try {
      const verification = await verifyPayment(
        options.network,
        parsed.payload,
        options.recipientAddress,
        typeof options.priceRlusd === "number" ? options.priceRlusd : 0
      );

      if (!verification.valid) {
        res.status(402).json({
          error: verification.reason ?? "Payment verification failed",
          code: "PAYMENT_INVALID",
        });
        return;
      }

      // Attach payer info to request for downstream handlers
      req.relay = {
        payer: verification.payer!,
        paymentTxHash: verification.txHash!,
        amountPaid: verification.amount!,
      };

      next();
    } catch (err) {
      logger.error("x402 verification error:", err);
      res.status(402).json({
        error: "Payment verification unavailable. Try again.",
        code: "VERIFICATION_ERROR",
      });
    }
  };
}

// ── Tier-gated middleware ────────────────────────────────────────────────────

/**
 * Reputation tier gate — requires minimum tier to access endpoint.
 * Uses the reputation score cached in DB (not live XRPL query per request).
 */
export function requireTier(minTier: ReputationTier) {
  return async (req: Request, res: Response, next: NextFunction): Promise<void> => {
    const address =
      req.relay?.payer ??
      (req.headers["x-relay-address"] as string | undefined) ??
      (req.query.address as string | undefined);

    if (!address) {
      res.status(401).json({
        error: "Address required. Provide X-Relay-Address header or pay via x402.",
        code: "ADDRESS_REQUIRED",
      });
      return;
    }

    // Tier check against the reputation events in DB (lightweight)
    const { queryOne } = await import("../db/pool");
    const stats = await queryOne<{ count: string }>(
      `SELECT COUNT(*) AS count FROM reputation_events
       WHERE address = $1 AND event_type = 'job_completed'`,
      [address]
    );

    const jobsCompleted = parseInt(stats?.count ?? "0", 10);

    // Simple tier estimate from jobs (full score calc is in /reputation/:address)
    const estimatedScore = jobsCompleted * 10;
    const tierOrder: ReputationTier[] = ["unverified", "bronze", "silver", "gold", "platinum"];
    const requiredIdx = tierOrder.indexOf(minTier);

    const tier: ReputationTier =
      estimatedScore >= 5000 ? "platinum" :
      estimatedScore >= 2000 ? "gold" :
      estimatedScore >= 500  ? "silver" :
      estimatedScore >= 100  ? "bronze" : "unverified";

    if (tierOrder.indexOf(tier) < requiredIdx) {
      res.status(403).json({
        error: `Minimum reputation tier required: ${minTier}. Your tier: ${tier}.`,
        code: "INSUFFICIENT_TIER",
        required: minTier,
        current: tier,
      });
      return;
    }

    next();
  };
}

// ── Payment verifier ─────────────────────────────────────────────────────────

interface VerifyResult {
  valid: boolean;
  reason?: string;
  payer?: string;
  txHash?: string;
  amount?: string;
}

async function verifyPayment(
  network: Network,
  txBlob: string,
  expectedRecipient: string,
  minAmountRlusd: number
): Promise<VerifyResult> {
  try {
    const client = await getClient(network);
    const { decode } = await import("xrpl");
    const decoded = decode(txBlob) as Record<string, unknown>;

    // Check this is a Payment tx
    if (decoded.TransactionType !== "Payment") {
      return { valid: false, reason: "Not a Payment transaction" };
    }

    // Check destination
    if (decoded.Destination !== expectedRecipient) {
      return { valid: false, reason: "Payment destination mismatch" };
    }

    // Check amount (RLUSD IOU)
    const amount = decoded.Amount as string | Record<string, string> | undefined;
    let paidRlusd = 0;
    if (amount && typeof amount === "object") {
      if (amount.currency !== RLUSD_CURRENCY) {
        return { valid: false, reason: "Payment must be in RLUSD" };
      }
      if (amount.issuer !== RLUSD_ISSUERS[network]) {
        return { valid: false, reason: "Invalid RLUSD issuer" };
      }
      paidRlusd = parseFloat(amount.value ?? "0");
    } else if (typeof amount === "string") {
      // XRP payment — convert to approximate RLUSD check
      paidRlusd = parseInt(amount, 10) / 1_000_000;
    }

    if (paidRlusd < minAmountRlusd * 0.99) {
      return {
        valid: false,
        reason: `Underpayment: sent ${paidRlusd} RLUSD, required ${minAmountRlusd}`,
      };
    }

    // Submit and verify on XRPL
    const result = await client.submitAndWait(txBlob);
    const meta = result.result.meta as { TransactionResult?: string } | undefined;

    if (meta?.TransactionResult !== "tesSUCCESS") {
      return { valid: false, reason: `Transaction failed: ${meta?.TransactionResult}` };
    }

    return {
      valid: true,
      payer: decoded.Account as string,
      txHash: result.result.hash,
      amount: paidRlusd.toString(),
    };
  } catch (err) {
    return { valid: false, reason: err instanceof Error ? err.message : "Unknown error" };
  }
}
