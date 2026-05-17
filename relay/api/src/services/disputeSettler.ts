/**
 * Dispute settlement orchestration service.
 *
 * Monitors disputes where vote threshold has been reached and
 * triggers on-chain settlement. This service:
 *   1. Detects when 3-of-5 evaluator votes are collected
 *   2. Builds the unsigned settlement transaction
 *   3. Notifies evaluators to sign (via webhook or polling)
 *   4. Submits the combined multi-sig tx when signatures collected
 *   5. Records outcomes and triggers reward/slash distribution
 *
 * Zero-custody: settlement tx is built here but never signed here.
 * Evaluators sign independently and submit their partial signatures.
 */

import { query, queryOne } from "../db/pool";
import { logger } from "./logger";
import { getLedgerVrfSeed, buildSettlementTx, calculateSettlementAmounts } from "../../../sdk/src/settlement";
import { resolveVotes } from "../../../sdk/src/evaluators";
import { updateStreakAfterVote } from "../../../sdk/src/vrf";
import { Network, DisputeVote, DisputeOutcome } from "../../../sdk/src/types";
import { DEFAULT_DISPUTE_THRESHOLD } from "../../../sdk/src/constants";

export interface SettlementDraft {
  disputeId: string;
  jobId: string;
  channelId: string;
  outcome: DisputeOutcome;
  unsignedTxJson: string;
  amountToHirer: string;
  amountToWorker: string;
  pendingSignatures: string[]; // evaluator addresses that still need to sign
}

/**
 * Check if a dispute has reached vote threshold and return the draft settlement.
 * Returns null if threshold not yet met.
 */
export async function checkSettlementReady(
  disputeId: string
): Promise<SettlementDraft | null> {
  const dispute = await queryOne<{
    id: string;
    job_id: string;
    votes: DisputeVote[];
    selected_evaluators: Array<{ address: string; stake: number }>;
    status: string;
    outcome: string | null;
  }>(
    "SELECT id, job_id, votes, selected_evaluators, status, outcome FROM disputes WHERE id = $1",
    [disputeId]
  );

  if (!dispute || dispute.status === "resolved") return null;

  const votes = dispute.votes as DisputeVote[];
  const winner = resolveVotes(votes, DEFAULT_DISPUTE_THRESHOLD);
  if (!winner) return null;

  const job = await queryOne<{
    channel_id: string;
    amount: string;
    network: string;
    hirer: string;
    worker: string;
  }>(
    "SELECT channel_id, amount, network, hirer, worker FROM jobs WHERE id = $1",
    [dispute.job_id]
  );
  if (!job) return null;

  const network = job.network as Network;
  const totalDrops = Math.round(parseFloat(job.amount) * 1_000_000).toString();
  const outcome = winner as DisputeOutcome;
  const { toHirer, toWorker } = calculateSettlementAmounts(totalDrops, outcome);

  let unsignedTxJson: string;
  try {
    unsignedTxJson = await buildSettlementTx(network, {
      channelId: job.channel_id,
      hirerAddress: job.hirer,
      workerAddress: job.worker,
      totalAmountDrops: totalDrops,
      outcome,
    });
  } catch (err) {
    logger.error(`Failed to build settlement tx for dispute ${disputeId}:`, err);
    return null;
  }

  // Determine which evaluators still need to sign
  const signedAddresses = new Set(votes.filter((v) => v.vote === winner).map((v) => v.evaluator));
  const allSelected = (dispute.selected_evaluators as Array<{ address: string }>).map(
    (e) => e.address
  );
  const pendingSignatures = allSelected.filter((addr) => !signedAddresses.has(addr));

  return {
    disputeId,
    jobId: dispute.job_id,
    channelId: job.channel_id,
    outcome,
    unsignedTxJson,
    amountToHirer: toHirer,
    amountToWorker: toWorker,
    pendingSignatures,
  };
}

/**
 * Record a settlement transaction hash and finalize the dispute.
 * Called after the multi-sig tx has been confirmed on XRPL.
 */
export async function finalizeSettlement(
  disputeId: string,
  txHash: string,
  outcome: DisputeOutcome
): Promise<void> {
  await query(
    `UPDATE disputes SET
       status = 'resolved',
       outcome = $1,
       resolution_tx_hash = $2,
       resolved_at = NOW()
     WHERE id = $3`,
    [outcome, txHash, disputeId]
  );

  const dispute = await queryOne<{ job_id: string }>(
    "SELECT job_id FROM disputes WHERE id = $1",
    [disputeId]
  );
  if (!dispute) return;

  await query(
    `UPDATE jobs SET status = 'completed', completed_at = NOW()
     WHERE id = $1`,
    [dispute.job_id]
  );

  // Record reputation events for both parties
  const job = await queryOne<{
    hirer: string;
    worker: string;
    amount: string;
  }>(
    "SELECT hirer, worker, amount FROM jobs WHERE id = $1",
    [dispute.job_id]
  );
  if (!job) return;

  await query(
    `INSERT INTO reputation_events (address, event_type, job_id, dispute_id, amount, metadata)
     VALUES
       ($1, 'dispute_resolved', $2, $3, $4, $5::jsonb),
       ($6, 'dispute_resolved', $2, $3, $4, $7::jsonb)`,
    [
      job.hirer, dispute.job_id, disputeId, job.amount,
      JSON.stringify({ role: "hirer", outcome, txHash }),
      job.worker,
      JSON.stringify({ role: "worker", outcome, txHash }),
    ]
  ).catch((err) => logger.warn("Failed to record resolution rep events:", err));

  logger.info(`Dispute ${disputeId} finalized: outcome=${outcome} tx=${txHash}`);
}

/**
 * Update evaluator stats after a dispute resolves.
 * Records votes as correct/incorrect for accuracy tracking.
 */
export async function updateEvaluatorStats(
  disputeId: string,
  winningVote: "hirer" | "worker" | "partial"
): Promise<void> {
  const dispute = await queryOne<{ votes: DisputeVote[] }>(
    "SELECT votes FROM disputes WHERE id = $1",
    [disputeId]
  );
  if (!dispute) return;

  const votes = dispute.votes as DisputeVote[];

  for (const vote of votes) {
    const isCorrect = vote.vote === winningVote;

    // Fetch current streak state before updating
    const evaluator = await queryOne<{
      consecutive_accurate_votes: number;
      slash_count: number;
      stake_amount: string;
    }>(
      "SELECT consecutive_accurate_votes, slash_count, stake_amount FROM evaluators WHERE address = $1",
      [vote.evaluator]
    );

    const currentStreak = evaluator?.consecutive_accurate_votes ?? 0;
    const currentSlashes = evaluator?.slash_count ?? 0;

    const { consecutiveAccurateVotes: newStreak } = updateStreakAfterVote(
      {
        address: vote.evaluator,
        stakeAmount: parseFloat(evaluator?.stake_amount ?? "0"),
        consecutiveAccurateVotes: currentStreak,
        totalSlashes: currentSlashes,
        streakMultiplier: 1,
        effectiveWeight: 0,
      },
      isCorrect
    );

    const slashDelta = isCorrect ? 0 : 1;
    await query(
      `UPDATE evaluators SET
         total_votes = total_votes + 1,
         correct_votes = correct_votes + $1,
         accuracy = (correct_votes + $1)::decimal / (total_votes + 1),
         slash_count = slash_count + $2,
         consecutive_accurate_votes = $3,
         last_vote_at = NOW()
       WHERE address = $4`,
      [isCorrect ? 1 : 0, slashDelta, newStreak, vote.evaluator]
    );

    // Record reward/slash reputation event
    const eventType = isCorrect ? "evaluator_rewarded" : "evaluator_slashed";
    await query(
      `INSERT INTO reputation_events (address, event_type, dispute_id, metadata)
       VALUES ($1, $2, $3, $4::jsonb)`,
      [vote.evaluator, eventType, disputeId, JSON.stringify({
        vote: vote.vote,
        winning: winningVote,
        streakBefore: currentStreak,
        streakAfter: newStreak,
      })]
    ).catch(() => null);
  }
}
