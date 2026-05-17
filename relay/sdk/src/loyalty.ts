/**
 * Relay Loyalty Program — on-chain tenure rewards, no custodial points.
 *
 * Loyalty tiers are computed from verifiable on-chain data only.
 * There is no "points balance" Relay holds — all state is derivable
 * from XRPL transaction history.
 *
 * Tier benefits:
 *
 *   Scout    (≥1 job)     : Access to standard evaluator pool
 *   Builder  (≥10 jobs)   : Priority evaluator selection, 10% fee discount
 *   Veteran  (≥50 jobs)   : Custom evaluator pools, 20% fee discount
 *   Legend   (≥200 jobs)  : VIP evaluator pool, 30% fee discount, governance vote
 *
 * Evaluator loyalty:
 *   Apprentice (≥10 votes, ≥80% accuracy)
 *   Journeyman (≥50 votes, ≥85% accuracy)
 *   Master     (≥200 votes, ≥90% accuracy)
 *   Grandmaster(≥500 votes, ≥95% accuracy, ≥1 year tenure)
 *
 * Fee discounts are applied at payment channel creation via pre-signed splits.
 * Governance votes are recorded as XRPL account memos (immutable).
 */

import { Wallet } from "xrpl";
import { ReputationScore } from "./types";
import { makeError } from "./xrpl-client";

// ── Participant loyalty ──────────────────────────────────────────────────────

export type ParticipantTier = "scout" | "builder" | "veteran" | "legend";
export type EvaluatorTier = "apprentice" | "journeyman" | "master" | "grandmaster";
export type LoyaltyTier = ParticipantTier | EvaluatorTier | "unranked";

export interface ParticipantLoyalty {
  address: string;
  tier: ParticipantTier | "unranked";
  jobsCompleted: number;
  totalVolume: number;
  feeDiscountBps: number;
  privilegedEvaluatorPool: boolean;
  canVote: boolean;
  nextTierRequirement: string | null;
  streakDays: number;
  longestStreakDays: number;
}

export interface EvaluatorLoyalty {
  address: string;
  tier: EvaluatorTier | "unranked";
  totalVotes: number;
  accuracy: number;
  tenureDays: number;
  earnedRlusd: number;
  feeShareBps: number;
  bonusMultiplier: number;
  nextTierRequirement: string | null;
}

export interface LoyaltyBenefits {
  feeDiscountBps: number;
  evaluatorPoolTier: "standard" | "priority" | "custom" | "vip";
  canIssueAttestations: boolean;
  canVoteOnGovernance: boolean;
  bonusMultiplierBps: number;
}

// ── Volume-based fee decay (X402 decay) ─────────────────────────────────────
//
// Cumulative RLUSD volume → effective fee rate (BPS).
// Decay applies on top of — and is separate from — tier discounts.
// Both participant and agent-side fee rates use the same volume ladder.
//
//   < 1 000 RLUSD lifetime  →  50 BPS (0.50%)
//   ≥ 1 000               →  40 BPS (0.40%)
//   ≥ 10 000              →  30 BPS (0.30%)
//   ≥ 50 000              →  20 BPS (0.20%)
//   ≥ 100 000             →  10 BPS (0.10%)

export const VOLUME_FEE_LADDER: Array<{ thresholdRlusd: number; feeBps: number }> = [
  { thresholdRlusd: 100_000, feeBps: 10 },
  { thresholdRlusd:  50_000, feeBps: 20 },
  { thresholdRlusd:  10_000, feeBps: 30 },
  { thresholdRlusd:   1_000, feeBps: 40 },
  { thresholdRlusd:       0, feeBps: 50 },
];

/**
 * Return the effective fee rate (BPS) for an address with the given cumulative volume.
 * Pure function — SDK computes locally, no server round-trip required.
 */
export function computeVolumeFeeDecay(cumulativeVolumeRlusd: number): number {
  for (const step of VOLUME_FEE_LADDER) {
    if (cumulativeVolumeRlusd >= step.thresholdRlusd) return step.feeBps;
  }
  return 50; // unreachable but satisfies type checker
}

/**
 * Combine volume-decay rate with tier discount into the final effective fee BPS.
 * Tier discount is applied multiplicatively on top of the volume-decayed rate.
 *
 * Example: veteran (20% discount) at 15K volume (30 BPS base) → 30 × 0.80 = 24 BPS
 */
export function computeEffectiveFeeRate(
  cumulativeVolumeRlusd: number,
  tier: LoyaltyTier
): number {
  const baseRateBps = computeVolumeFeeDecay(cumulativeVolumeRlusd);
  const benefits = getLoyaltyBenefits(tier);
  const discountMultiplier = 1 - benefits.feeDiscountBps / 10000;
  return Math.round(baseRateBps * discountMultiplier);
}

/**
 * Compute the Relay fee amount for a transaction given the caller's volume history
 * and loyalty tier.  Returns the fee in the same unit as `amountRlusd`.
 */
export function computeFeeWithDecay(
  amountRlusd: number,
  cumulativeVolumeRlusd: number,
  tier: LoyaltyTier
): { feeRlusd: number; feeBps: number; savings: number } {
  const effectiveBps = computeEffectiveFeeRate(cumulativeVolumeRlusd, tier);
  const baseBps = 50; // canonical starting rate
  const feeRlusd = (amountRlusd * effectiveBps) / 10000;
  const baseFee  = (amountRlusd * baseBps) / 10000;
  return { feeRlusd, feeBps: effectiveBps, savings: baseFee - feeRlusd };
}

// ── Thresholds ───────────────────────────────────────────────────────────────

const PARTICIPANT_THRESHOLDS: Record<ParticipantTier, { jobs: number; feeBps: number }> = {
  scout:   { jobs: 1,   feeBps: 0 },
  builder: { jobs: 10,  feeBps: 1000 }, // 10% discount
  veteran: { jobs: 50,  feeBps: 2000 }, // 20% discount
  legend:  { jobs: 200, feeBps: 3000 }, // 30% discount
};

const EVALUATOR_THRESHOLDS: Record<EvaluatorTier, {
  votes: number;
  accuracy: number;
  tenureDays: number;
  bonusBps: number;
}> = {
  apprentice:  { votes: 10,  accuracy: 0.80, tenureDays: 0,   bonusBps: 0 },
  journeyman:  { votes: 50,  accuracy: 0.85, tenureDays: 30,  bonusBps: 500 },
  master:      { votes: 200, accuracy: 0.90, tenureDays: 90,  bonusBps: 1000 },
  grandmaster: { votes: 500, accuracy: 0.95, tenureDays: 365, bonusBps: 2000 },
};

// ── Participant loyalty computation ─────────────────────────────────────────

export function computeParticipantLoyalty(
  address: string,
  jobsCompleted: number,
  totalVolume: number,
  activityDates: number[] // unix timestamps of completed jobs
): ParticipantLoyalty {
  const tier = deriveParticipantTier(jobsCompleted);
  const thresholds = Object.entries(PARTICIPANT_THRESHOLDS) as Array<
    [ParticipantTier, { jobs: number; feeBps: number }]
  >;

  const feeBps = tier === "unranked" ? 0 : PARTICIPANT_THRESHOLDS[tier].feeBps;

  const nextTier = tier === "legend"
    ? null
    : findNextParticipantTier(jobsCompleted);

  const { streak, longest } = computeActivityStreak(activityDates);

  return {
    address,
    tier,
    jobsCompleted,
    totalVolume,
    feeDiscountBps: feeBps,
    privilegedEvaluatorPool: tier === "veteran" || tier === "legend",
    canVote: tier === "legend",
    nextTierRequirement: nextTier,
    streakDays: streak,
    longestStreakDays: longest,
  };
}

export function computeEvaluatorLoyalty(
  address: string,
  totalVotes: number,
  accuracy: number,
  tenureDays: number,
  earnedRlusd: number
): EvaluatorLoyalty {
  const tier = deriveEvaluatorTier(totalVotes, accuracy, tenureDays);
  const bonusBps = tier === "unranked" ? 0 : EVALUATOR_THRESHOLDS[tier as EvaluatorTier]?.bonusBps ?? 0;
  const nextTier = tier === "grandmaster" ? null : findNextEvaluatorTier(totalVotes, accuracy, tenureDays);

  return {
    address,
    tier,
    totalVotes,
    accuracy,
    tenureDays,
    earnedRlusd,
    feeShareBps: 20 + bonusBps, // base 0.20% + tier bonus
    bonusMultiplier: 1 + bonusBps / 10000,
    nextTierRequirement: nextTier,
  };
}

/**
 * Get the concrete benefits for a loyalty tier.
 */
export function getLoyaltyBenefits(tier: LoyaltyTier): LoyaltyBenefits {
  switch (tier) {
    case "scout":
      return {
        feeDiscountBps: 0,
        evaluatorPoolTier: "standard",
        canIssueAttestations: false,
        canVoteOnGovernance: false,
        bonusMultiplierBps: 0,
      };
    case "builder":
      return {
        feeDiscountBps: 1000,
        evaluatorPoolTier: "priority",
        canIssueAttestations: false,
        canVoteOnGovernance: false,
        bonusMultiplierBps: 0,
      };
    case "veteran":
      return {
        feeDiscountBps: 2000,
        evaluatorPoolTier: "custom",
        canIssueAttestations: true,
        canVoteOnGovernance: false,
        bonusMultiplierBps: 0,
      };
    case "legend":
      return {
        feeDiscountBps: 3000,
        evaluatorPoolTier: "vip",
        canIssueAttestations: true,
        canVoteOnGovernance: true,
        bonusMultiplierBps: 0,
      };
    case "apprentice":
      return {
        feeDiscountBps: 0,
        evaluatorPoolTier: "standard",
        canIssueAttestations: false,
        canVoteOnGovernance: false,
        bonusMultiplierBps: 0,
      };
    case "journeyman":
      return {
        feeDiscountBps: 0,
        evaluatorPoolTier: "priority",
        canIssueAttestations: false,
        canVoteOnGovernance: false,
        bonusMultiplierBps: 500,
      };
    case "master":
      return {
        feeDiscountBps: 0,
        evaluatorPoolTier: "custom",
        canIssueAttestations: true,
        canVoteOnGovernance: false,
        bonusMultiplierBps: 1000,
      };
    case "grandmaster":
      return {
        feeDiscountBps: 0,
        evaluatorPoolTier: "vip",
        canIssueAttestations: true,
        canVoteOnGovernance: true,
        bonusMultiplierBps: 2000,
      };
    default:
      return {
        feeDiscountBps: 0,
        evaluatorPoolTier: "standard",
        canIssueAttestations: false,
        canVoteOnGovernance: false,
        bonusMultiplierBps: 0,
      };
  }
}

/**
 * Apply loyalty fee discount to a job amount.
 * Returns discounted amount in the same unit as input.
 */
export function applyLoyaltyDiscount(
  amount: number,
  baseFeeRlusd: number,
  tier: LoyaltyTier
): { discountedFee: number; savings: number } {
  const benefits = getLoyaltyBenefits(tier);
  const discountMultiplier = 1 - benefits.feeDiscountBps / 10000;
  const discountedFee = baseFeeRlusd * discountMultiplier;
  return {
    discountedFee,
    savings: baseFeeRlusd - discountedFee,
  };
}

/**
 * Apply evaluator bonus multiplier to reward amount.
 */
export function applyEvaluatorBonus(
  baseRewardRlusd: number,
  tier: EvaluatorTier | "unranked"
): { boostedReward: number; bonus: number } {
  const bonusBps = tier === "unranked" ? 0 : EVALUATOR_THRESHOLDS[tier]?.bonusBps ?? 0;
  const multiplier = 1 + bonusBps / 10000;
  const boostedReward = baseRewardRlusd * multiplier;
  return {
    boostedReward,
    bonus: boostedReward - baseRewardRlusd,
  };
}

// ── Governance vote (on-chain, XRPL AccountSet memo) ────────────────────────

export interface GovernanceProposal {
  proposalId: string;
  title: string;
  description: string;
  options: string[];
  expiresAt: number;
}

export interface GovernanceVote {
  proposalId: string;
  voter: string;
  choice: string;
  timestamp: number;
  txHash: string;
}

/**
 * Build an on-chain governance vote transaction.
 * Only legend-tier participants can vote (checked at signing time).
 * Vote is immutable once submitted — encoded in XRPL AccountSet Domain.
 */
export function buildGovernanceVoteTx(
  voterAddress: string,
  proposal: GovernanceProposal,
  choice: string
): Record<string, unknown> {
  if (!proposal.options.includes(choice)) {
    throw makeError(
      "INVALID_CHOICE",
      `Choice "${choice}" not in proposal options: ${proposal.options.join(", ")}`
    );
  }
  if (Date.now() / 1000 > proposal.expiresAt) {
    throw makeError("PROPOSAL_EXPIRED", `Proposal ${proposal.proposalId} has expired`);
  }

  const voteData = {
    relay_governance: true,
    proposal_id: proposal.proposalId,
    choice,
    voter: voterAddress,
    timestamp: Math.floor(Date.now() / 1000),
  };

  return {
    TransactionType: "AccountSet",
    Account: voterAddress,
    Domain: Buffer.from(JSON.stringify(voteData)).toString("hex"),
    Memos: [
      {
        Memo: {
          MemoType: Buffer.from("relay/governance").toString("hex"),
          MemoData: Buffer.from(proposal.proposalId).toString("hex"),
        },
      },
    ],
  };
}

// ── Streak computation ────────────────────────────────────────────────────────

function computeActivityStreak(
  timestamps: number[]
): { streak: number; longest: number } {
  if (!timestamps.length) return { streak: 0, longest: 0 };

  const dayMs = 24 * 60 * 60 * 1000;
  const sorted = [...timestamps].sort((a, b) => a - b);
  const days = sorted.map((t) => Math.floor(t * 1000 / dayMs));
  const unique = [...new Set(days)];

  let current = 1;
  let longest = 1;
  let streak = 1;
  const todayDay = Math.floor(Date.now() / dayMs);

  for (let i = 1; i < unique.length; i++) {
    if (unique[i] === unique[i - 1] + 1) {
      current++;
      longest = Math.max(longest, current);
    } else {
      current = 1;
    }
  }

  // Current streak: count back from today
  streak = unique[unique.length - 1] >= todayDay - 1 ? current : 0;

  return { streak, longest };
}

// ── Tier derivation helpers ───────────────────────────────────────────────────

function deriveParticipantTier(jobs: number): ParticipantTier | "unranked" {
  if (jobs >= 200) return "legend";
  if (jobs >= 50) return "veteran";
  if (jobs >= 10) return "builder";
  if (jobs >= 1) return "scout";
  return "unranked";
}

function deriveEvaluatorTier(
  votes: number,
  accuracy: number,
  tenureDays: number
): EvaluatorTier | "unranked" {
  const tiers: EvaluatorTier[] = ["grandmaster", "master", "journeyman", "apprentice"];
  for (const tier of tiers) {
    const req = EVALUATOR_THRESHOLDS[tier];
    if (votes >= req.votes && accuracy >= req.accuracy && tenureDays >= req.tenureDays) {
      return tier;
    }
  }
  return "unranked";
}

function findNextParticipantTier(jobs: number): string | null {
  const tiers: Array<[ParticipantTier, number]> = [
    ["scout", 1], ["builder", 10], ["veteran", 50], ["legend", 200],
  ];
  for (const [tier, req] of tiers) {
    if (jobs < req) return `${req - jobs} more jobs for ${tier}`;
  }
  return null;
}

function findNextEvaluatorTier(
  votes: number,
  accuracy: number,
  tenureDays: number
): string | null {
  const tiers: EvaluatorTier[] = ["apprentice", "journeyman", "master", "grandmaster"];
  for (const tier of tiers) {
    const req = EVALUATOR_THRESHOLDS[tier];
    if (votes < req.votes || accuracy < req.accuracy || tenureDays < req.tenureDays) {
      const gaps: string[] = [];
      if (votes < req.votes) gaps.push(`${req.votes - votes} more votes`);
      if (accuracy < req.accuracy) gaps.push(`${((req.accuracy - accuracy) * 100).toFixed(1)}% accuracy improvement`);
      if (tenureDays < req.tenureDays) gaps.push(`${req.tenureDays - tenureDays} more tenure days`);
      return `${tier}: need ${gaps.join(", ")}`;
    }
  }
  return null;
}
