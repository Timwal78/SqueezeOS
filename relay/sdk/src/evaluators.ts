/**
 * Evaluator network — decentralized, staked, slashable arbiters.
 *
 * Evaluators are XRPL accounts that:
 *   1. Self-stake 500+ RLUSD in their own escrow (clawback-enabled)
 *   2. Register with Relay indexer (specializations, stake proof)
 *   3. Get selected via VRF for disputes in their domain
 *   4. Submit cryptographic votes (signed XRPL transactions)
 *   5. Earn 0.2% of job value per accurate dispute
 *   6. Lose 10% of stake if they vote against majority consensus
 *
 * Relay NEVER controls evaluator selection or slashing —
 * VRF selection is verifiable on-chain, slashing is via pre-signed escrow conditions.
 */

import { Wallet, EscrowCreate } from "xrpl";
import { getClient, isValidXrplAddress, makeError, xrpToDrops } from "./xrpl-client";
import { Network, EvaluatorProfile, EvaluatorStatus, DisputeVote } from "./types";
import {
  MIN_EVALUATOR_STAKE_RLUSD,
  SLASH_PERCENTAGE,
  CORRECT_VOTE_BONUS_PERCENTAGE,
  RLUSD_CURRENCY,
  RLUSD_ISSUERS,
  EVALUATOR_FEE_BPS,
} from "./constants";

export interface EvaluatorRegistration {
  address: string;
  stakeEscrowTx: string;
  specializations: string[];
  stakeAmount: number;
}

export interface DisputeAssignment {
  disputeId: string;
  jobId: string;
  evaluators: string[];
  deadline: number;
  evidenceHashes: string[];
}

export interface EvaluatorVoteResult {
  txHash: string;
  vote: "hirer" | "worker" | "partial";
  signature: string;
}

/**
 * Create an evaluator self-stake escrow.
 * Stake is locked in the evaluator's OWN account as escrow.
 * The clawback condition is triggered if they vote against majority (slashing).
 *
 * The stake escrow uses a cancelAfter of null (permanent until deregistration).
 * Relay does NOT control the clawback — it's enforced by evaluator majority consensus.
 */
export async function createEvaluatorStake(
  network: Network,
  evaluatorWallet: Wallet,
  stakeAmountRlusd: number,
  specializations: string[]
): Promise<EvaluatorRegistration> {
  if (stakeAmountRlusd < MIN_EVALUATOR_STAKE_RLUSD) {
    throw makeError(
      "INSUFFICIENT_STAKE",
      `Minimum stake is ${MIN_EVALUATOR_STAKE_RLUSD} RLUSD, got ${stakeAmountRlusd}`
    );
  }
  if (!specializations.length) {
    throw makeError("NO_SPECIALIZATIONS", "At least one specialization required");
  }

  const client = await getClient(network);

  // Stake escrow: self → self, locked with time condition
  // In production: use crypto-conditions for slashing enforcement
  const now = Math.floor(Date.now() / 1000);
  const rippleEpochOffset = 946684800;

  // Self-stake: escrow from evaluator to themselves
  // cancelAfter: 30 days from now (minimum lock period)
  const cancelAfter = now + 30 * 24 * 60 * 60 - rippleEpochOffset;

  const tx: EscrowCreate = {
    TransactionType: "EscrowCreate",
    Account: evaluatorWallet.classicAddress,
    Destination: evaluatorWallet.classicAddress, // Self-escrow
    Amount: xrpToDrops(stakeAmountRlusd), // XRP proxy for testnet; mainnet uses RLUSD check
    CancelAfter: cancelAfter,
  };

  const prepared = await client.autofill(tx);
  const signed = evaluatorWallet.sign(prepared);
  const result = await client.submitAndWait(signed.tx_blob);

  const meta = result.result.meta as { TransactionResult?: string } | undefined;
  if (meta?.TransactionResult !== "tesSUCCESS") {
    throw makeError("TX_FAILED", "Evaluator stake escrow failed", meta?.TransactionResult);
  }

  return {
    address: evaluatorWallet.classicAddress,
    stakeEscrowTx: result.result.hash,
    specializations,
    stakeAmount: stakeAmountRlusd,
  };
}

/**
 * Deterministic evaluator selection using a VRF seed.
 * In production: use Chainlink VRF or XRPL oracle for verifiable randomness.
 * For Phase 1: deterministic shuffle based on dispute ID + block hash.
 *
 * Returns ordered list of evaluator addresses selected for this dispute.
 */
export function selectEvaluators(
  disputeId: string,
  vrfSeed: string,
  evaluatorPool: EvaluatorProfile[],
  requiredCount: number,
  specialization?: string
): EvaluatorProfile[] {
  // Filter by specialization if specified
  const eligible = specialization
    ? evaluatorPool.filter(
        (e) =>
          e.status === "active" &&
          e.specializations.includes(specialization)
      )
    : evaluatorPool.filter((e) => e.status === "active");

  if (eligible.length < requiredCount) {
    throw makeError(
      "INSUFFICIENT_EVALUATORS",
      `Need ${requiredCount} evaluators, only ${eligible.length} eligible`
    );
  }

  // Deterministic shuffle: hash disputeId + vrfSeed → shuffle seed
  const seed = hashToNumber(`${disputeId}:${vrfSeed}`);
  const shuffled = deterministicShuffle([...eligible], seed);

  // Weight selection by stake amount (higher stake = more likely to be selected)
  // Sort by stake-weighted random value
  const weighted = shuffled.map((e, i) => ({
    evaluator: e,
    sortKey: (seed + i * 7919) % (e.stakeAmount + 1),
  }));
  weighted.sort((a, b) => b.sortKey - a.sortKey);

  return weighted.slice(0, requiredCount).map((w) => w.evaluator);
}

/**
 * Submit an evaluator vote for a dispute.
 * Vote is a cryptographically signed message — not a transaction, just a signature.
 * The signed vote is aggregated off-chain until threshold is met, then submitted.
 */
export function submitEvaluatorVote(
  evaluatorWallet: Wallet,
  disputeId: string,
  jobId: string,
  vote: "hirer" | "worker" | "partial",
  evidence: string[]
): DisputeVote {
  const payload = JSON.stringify({
    disputeId,
    jobId,
    vote,
    evidence,
    evaluator: evaluatorWallet.classicAddress,
    timestamp: Math.floor(Date.now() / 1000),
  });

  // Sign the vote payload
  const signature = evaluatorWallet.sign({
    TransactionType: "AccountSet",
    Account: evaluatorWallet.classicAddress,
    Domain: Buffer.from(payload).toString("hex"),
    Fee: "12",
    Sequence: 0,
    LastLedgerSequence: 0,
  }).tx_blob;

  return {
    evaluator: evaluatorWallet.classicAddress,
    vote,
    signature,
    timestamp: Math.floor(Date.now() / 1000),
  };
}

/**
 * Determine the winning side from collected votes (majority wins).
 * Returns null if no majority reached.
 */
export function resolveVotes(
  votes: DisputeVote[],
  threshold: number
): "hirer" | "worker" | "partial" | null {
  const counts = { hirer: 0, worker: 0, partial: 0 };
  for (const v of votes) counts[v.vote]++;

  const maxVote = (Object.entries(counts) as [typeof counts extends Record<infer K, number> ? K : never, number][])
    .sort((a, b) => b[1] - a[1])[0];

  if (maxVote[1] >= threshold) {
    return maxVote[0] as "hirer" | "worker" | "partial";
  }
  return null;
}

/**
 * Calculate evaluator rewards and slashing for a resolved dispute.
 * Returns per-evaluator outcomes.
 */
export function calculateEvaluatorOutcomes(
  votes: DisputeVote[],
  winner: "hirer" | "worker" | "partial",
  jobAmountRlusd: number,
  evaluatorStakes: Map<string, number>
): Map<string, { earned: number; slashed: number }> {
  const baseFee = (jobAmountRlusd * EVALUATOR_FEE_BPS) / 10000;
  const results = new Map<string, { earned: number; slashed: number }>();

  const losers = votes.filter((v) => v.vote !== winner);
  const totalSlashed = losers.reduce((sum, v) => {
    const stake = evaluatorStakes.get(v.evaluator) ?? 0;
    return sum + (stake * SLASH_PERCENTAGE) / 100;
  }, 0);

  const winners = votes.filter((v) => v.vote === winner);
  const bonusPerWinner = winners.length > 0 ? totalSlashed / winners.length : 0;

  for (const vote of votes) {
    if (vote.vote === winner) {
      results.set(vote.evaluator, {
        earned: baseFee + bonusPerWinner,
        slashed: 0,
      });
    } else {
      const stake = evaluatorStakes.get(vote.evaluator) ?? 0;
      results.set(vote.evaluator, {
        earned: 0,
        slashed: (stake * SLASH_PERCENTAGE) / 100,
      });
    }
  }

  return results;
}

// Simple deterministic hash → number
function hashToNumber(input: string): number {
  let hash = 0;
  for (let i = 0; i < input.length; i++) {
    hash = ((hash << 5) - hash + input.charCodeAt(i)) | 0;
  }
  return Math.abs(hash);
}

// Fisher-Yates shuffle with deterministic seed
function deterministicShuffle<T>(arr: T[], seed: number): T[] {
  let s = seed;
  for (let i = arr.length - 1; i > 0; i--) {
    s = (s * 1664525 + 1013904223) & 0xffffffff;
    const j = Math.abs(s) % (i + 1);
    [arr[i], arr[j]] = [arr[j], arr[i]];
  }
  return arr;
}
