/**
 * VRF-based evaluator selection with streak multiplier.
 *
 * Base selection probability is proportional to stake (skin in the game).
 * The streak multiplier rewards evaluators who consistently vote with majority
 * consensus — each consecutive accurate vote increases their VRF weight by 1.1x,
 * capped at 3x. A single slash resets to 1.0x instantly.
 *
 * Effective weight formula:
 *   streakMultiplier = min(3.0, 1.0 + consecutiveAccurateVotes * 0.1)
 *   effectiveWeight  = stakeAmount * streakMultiplier
 *
 * This is a pure function of on-chain data — fully client-verifiable.
 * The streak is computed from the evaluator's vote history in reputation_events.
 */

import { EvaluatorProfile } from "./types";
import { hashToNumber, deterministicShuffle } from "./vrf-internal";
import { makeError } from "./xrpl-client";

// ── Constants ────────────────────────────────────────────────────────────────

export const STREAK_MULTIPLIER_STEP = 0.1;  // +10% per consecutive correct vote
export const STREAK_MULTIPLIER_CAP  = 3.0;  // maximum 3x
export const STREAK_MULTIPLIER_BASE = 1.0;  // always starts / resets here
export const SLASH_RESETS_STREAK    = true;  // one slash = back to 1.0x

// ── Types ────────────────────────────────────────────────────────────────────

export interface EvaluatorVrfState {
  address: string;
  stakeAmount: number;
  consecutiveAccurateVotes: number;
  totalSlashes: number;
  streakMultiplier: number;
  effectiveWeight: number;
}

export interface VrfSelectionResult {
  selected: EvaluatorProfile[];
  weights: Map<string, number>;          // address → effectiveWeight used
  multipliers: Map<string, number>;      // address → streakMultiplier used
  vrfSeed: string;
  proofHash: string;                     // deterministic proof for auditability
}

// ── Streak multiplier ─────────────────────────────────────────────────────────

/**
 * Compute streak multiplier from consecutive accurate vote count.
 * This is a pure function — anyone can recompute from vote history.
 */
export function computeStreakMultiplier(
  consecutiveAccurateVotes: number,
  slashCount: number
): number {
  // Any slash resets streak to base
  if (consecutiveAccurateVotes <= 0 || slashCount < 0) return STREAK_MULTIPLIER_BASE;
  const raw = STREAK_MULTIPLIER_BASE + consecutiveAccurateVotes * STREAK_MULTIPLIER_STEP;
  return Math.min(STREAK_MULTIPLIER_CAP, parseFloat(raw.toFixed(4)));
}

/**
 * Compute effective VRF weight for a single evaluator.
 * effectiveWeight = stakeAmount × streakMultiplier
 */
export function computeEffectiveWeight(
  stakeAmount: number,
  consecutiveAccurateVotes: number,
  totalSlashes: number
): number {
  const multiplier = computeStreakMultiplier(consecutiveAccurateVotes, totalSlashes);
  return stakeAmount * multiplier;
}

/**
 * Build full VRF state for an evaluator from their on-chain metrics.
 */
export function buildEvaluatorVrfState(
  address: string,
  stakeAmount: number,
  consecutiveAccurateVotes: number,
  totalSlashes: number
): EvaluatorVrfState {
  const multiplier = computeStreakMultiplier(consecutiveAccurateVotes, totalSlashes);
  return {
    address,
    stakeAmount,
    consecutiveAccurateVotes,
    totalSlashes,
    streakMultiplier: multiplier,
    effectiveWeight: stakeAmount * multiplier,
  };
}

/**
 * After a vote resolves, update the streak state.
 * Returns the new consecutiveAccurateVotes count.
 *
 * Called by the dispute settler when finalizing outcomes.
 * The result is stored in the evaluators table and feeds the next selection.
 */
export function updateStreakAfterVote(
  current: EvaluatorVrfState,
  wasCorrect: boolean
): { consecutiveAccurateVotes: number; newMultiplier: number } {
  const consecutive = wasCorrect ? current.consecutiveAccurateVotes + 1 : 0;
  const newMultiplier = computeStreakMultiplier(
    consecutive,
    current.totalSlashes + (wasCorrect ? 0 : 1)
  );
  return { consecutiveAccurateVotes: consecutive, newMultiplier };
}

// ── VRF selection with weighted probability ───────────────────────────────────

/**
 * Select N evaluators using stake-weighted + streak-boosted VRF.
 *
 * Algorithm:
 *   1. Compute effectiveWeight for each eligible evaluator
 *   2. Build cumulative weight prefix sums (for O(n) weighted sampling)
 *   3. Use deterministic hash draws from vrfSeed+disputeId+drawIndex
 *   4. Sample without replacement (reject already-selected)
 *
 * The result is fully deterministic given the same inputs — anyone can verify.
 */
export function selectEvaluatorsWithStreak(
  disputeId: string,
  vrfSeed: string,
  evaluators: EvaluatorProfile[],
  streakStates: Map<string, EvaluatorVrfState>,
  requiredCount: number,
  specialization?: string
): VrfSelectionResult {
  // Filter eligible
  const eligible = evaluators.filter(
    (e) =>
      e.status === "active" &&
      (!specialization || e.specializations.includes(specialization))
  );

  if (eligible.length < requiredCount) {
    throw makeError(
      "INSUFFICIENT_EVALUATORS",
      `Need ${requiredCount} evaluators, only ${eligible.length} eligible`
    );
  }

  // Build weight map
  const weights = new Map<string, number>();
  const multipliers = new Map<string, number>();
  let totalWeight = 0;

  for (const e of eligible) {
    const state = streakStates.get(e.address);
    const multiplier = state
      ? computeStreakMultiplier(state.consecutiveAccurateVotes, state.totalSlashes)
      : STREAK_MULTIPLIER_BASE;
    const weight = e.stakeAmount * multiplier;
    weights.set(e.address, weight);
    multipliers.set(e.address, multiplier);
    totalWeight += weight;
  }

  // Weighted selection without replacement
  const selected: EvaluatorProfile[] = [];
  const usedIndices = new Set<number>();
  const baseSeed = hashToNumber(`${disputeId}:${vrfSeed}`);

  for (let draw = 0; draw < requiredCount; draw++) {
    const drawHash = hashToNumber(`${baseSeed}:${draw}:${disputeId}`);
    let target = (drawHash % Math.floor(totalWeight * 1000)) / 1000;

    // Walk the weight prefix sums to find the selected evaluator
    for (let i = 0; i < eligible.length; i++) {
      if (usedIndices.has(i)) continue;
      target -= weights.get(eligible[i].address) ?? 0;
      if (target <= 0) {
        selected.push(eligible[i]);
        usedIndices.add(i);
        totalWeight -= weights.get(eligible[i].address) ?? 0;
        break;
      }
    }

    // Fallback: pick first unused if floating point caused overshoot
    if (selected.length <= draw) {
      for (let i = 0; i < eligible.length; i++) {
        if (!usedIndices.has(i)) {
          selected.push(eligible[i]);
          usedIndices.add(i);
          break;
        }
      }
    }
  }

  // Proof hash: deterministic fingerprint of this selection
  const proofHash = hashToNumber(
    `${disputeId}:${vrfSeed}:${selected.map((e) => e.address).join(":")}`
  ).toString(16).padStart(64, "0");

  return { selected, weights, multipliers, vrfSeed, proofHash };
}

// ── Streak computation from vote history ──────────────────────────────────────

/**
 * Compute consecutive accurate vote streak from an ordered vote history.
 * Counts backwards from the most recent vote until a loss is found.
 */
export function computeConsecutiveStreak(
  voteHistory: Array<{ wasCorrect: boolean; timestamp: number }>
): number {
  if (!voteHistory.length) return 0;
  const sorted = [...voteHistory].sort((a, b) => b.timestamp - a.timestamp);
  let streak = 0;
  for (const vote of sorted) {
    if (!vote.wasCorrect) break;
    streak++;
  }
  return streak;
}

/**
 * Generate a human-readable VRF selection proof for auditing.
 * Shows why each evaluator was chosen — verifiable by any third party.
 */
export function generateSelectionProof(result: VrfSelectionResult): string {
  const lines = [
    `VRF Selection Proof`,
    `Seed: ${result.vrfSeed}`,
    `Proof Hash: ${result.proofHash}`,
    `Selected evaluators:`,
    ...result.selected.map((e, i) => {
      const w = result.weights.get(e.address)?.toFixed(2) ?? "0";
      const m = result.multipliers.get(e.address)?.toFixed(2) ?? "1.00";
      return `  ${i + 1}. ${e.address.slice(0, 10)}... stake=${e.stakeAmount} × ${m}x = ${w} weight`;
    }),
  ];
  return lines.join("\n");
}
