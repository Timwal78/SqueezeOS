// Reputation engine — the credence solution. Scores how close an estimate was
// to the actual SEC-filed number, blends accuracy with timeliness, and applies
// streak multipliers. All pure functions; unit-tested in test/reputation.test.ts.
//
// Design rules:
//  - Reputation is in [0, 100]. Accuracy is in [0, 1].
//  - Slashing (wrong estimates) reduces reputation but never funds (no custody).
//  - Reputation COMPOUNDS via an exponential moving average so a long history of
//    accuracy is hard-won and a single miss can't erase it (nor a single hit
//    fake it).

import type { Tier } from "../types.js";

export interface ScoreInput {
  predicted: number;
  actual: number;
  confidence: number; // 0..1 self-reported
  /** seconds between estimate submission and the filing that scored it. */
  leadSeconds: number;
}

export interface ScoreResult {
  score: number; // 0..100 for this single estimate
  errorPct: number; // |predicted-actual| / max(|actual|, eps)
  timeliness: number; // 0..1
}

const EPS = 1e-9;

/**
 * Accuracy term: 1 when exact, decaying with relative error. A 0% error → 1.0,
 * a 10% error → ~0.5, a 25%+ error → near 0. Tuned so beating the crowd on EPS
 * (typically single-digit-% surprises) is well-resolved.
 */
export function accuracyTerm(predicted: number, actual: number): {
  acc: number;
  errorPct: number;
} {
  const denom = Math.max(Math.abs(actual), EPS);
  const errorPct = Math.abs(predicted - actual) / denom;
  // half-life at 10% error
  const acc = Math.exp(-errorPct / 0.1442695);
  return { acc: clamp01(acc), errorPct };
}

/**
 * Timeliness: estimates made further ahead of the filing are worth more (anyone
 * can be "right" minutes before results). Full credit at >= 30 days lead,
 * linearly less down to a 0.25 floor for last-minute calls.
 */
export function timelinessTerm(leadSeconds: number): number {
  const days = leadSeconds / 86400;
  const t = Math.min(days / 30, 1);
  return 0.25 + 0.75 * Math.max(t, 0);
}

export function scoreEstimate(input: ScoreInput): ScoreResult {
  const { acc, errorPct } = accuracyTerm(input.predicted, input.actual);
  const timeliness = timelinessTerm(input.leadSeconds);
  const conf = clamp01(input.confidence);
  // Confidence is a stake: high-confidence hits are rewarded and high-confidence
  // misses punished harder. We map acc from [0,1] to a signed term first.
  // Equivalent unsigned form (used by the on-chain port, see contracts/README):
  //   base = acc*w + (1-w)/2,  where w = 0.5 + 0.5*conf
  const signed = 2 * acc - 1; // [-1, 1]
  const confidenceWeighted = signed * (0.5 + 0.5 * conf);
  const base = (confidenceWeighted + 1) / 2; // back to [0,1]
  // Timeliness discounts low-lead calls toward a neutral 0.5: a last-minute
  // call (timeliness=0.25) is pulled 75% of the way to neutral, dampening both
  // its reward (if right) and its penalty (if wrong) — anyone can be "right"
  // minutes before results. Full-lead calls (timeliness=1) keep their base.
  //   effective = base*timeliness + 0.5*(1 - timeliness)
  const effective = base * timeliness + 0.5 * (1 - timeliness);
  const score = 100 * clamp01(effective);
  return { score, errorPct, timeliness };
}

export interface ReputationUpdate {
  reputation: number;
  accuracy: number;
  scored_count: number;
}

/**
 * Fold one freshly-scored estimate into an analyst's running reputation.
 * EMA with alpha that shrinks as the sample grows (early scores move more).
 */
export function updateReputation(
  prev: { reputation: number; accuracy: number; scored_count: number },
  result: ScoreResult,
  streakMultiplier: number
): ReputationUpdate {
  const n = prev.scored_count;
  const alpha = Math.max(0.08, 1 / (n + 1)); // floor keeps it adaptive
  // Streak amplifies gains only; it cannot manufacture accuracy above the score.
  const gainBoost = result.score >= 50 ? streakMultiplier : 1;
  const target = Math.min(100, result.score * gainBoost);
  const reputation = clamp(prev.reputation + alpha * (target - prev.reputation), 0, 100);
  const acc01 = result.score / 100;
  const accuracy = clamp01(prev.accuracy + alpha * (acc01 - prev.accuracy));
  return { reputation, accuracy, scored_count: n + 1 };
}

/** 7d → 1.5x, 30d → 2.5x, 100d → 5x (piecewise linear), capped at 5x. */
export function streakMultiplier(streakDays: number): number {
  if (streakDays >= 100) return 5;
  if (streakDays >= 30) return 2.5 + ((streakDays - 30) / 70) * (5 - 2.5);
  if (streakDays >= 7) return 1.5 + ((streakDays - 7) / 23) * (2.5 - 1.5);
  return 1 + (streakDays / 7) * (1.5 - 1);
}

/**
 * Advance a streak given the previous active UTC day and today. Same day → no
 * change; consecutive day → +1; gap → reset to 1.
 */
export function advanceStreak(
  prevDay: string | null,
  prevStreak: number,
  today: string
): number {
  if (prevDay === today) return prevStreak;
  if (prevDay === null) return 1;
  const prev = Date.parse(prevDay + "T00:00:00Z");
  const cur = Date.parse(today + "T00:00:00Z");
  const gapDays = Math.round((cur - prev) / 86400000);
  if (gapDays === 1) return prevStreak + 1;
  return 1;
}

/** Tier from the on-chain-mirrored stats. */
export function computeTier(stats: {
  reputation: number;
  accuracy: number;
  estimate_count: number;
  globalRank?: number; // 1-based, undefined if unranked
}): Tier {
  const { reputation, accuracy, estimate_count, globalRank } = stats;
  if (globalRank !== undefined && globalRank <= 10 && reputation >= 90)
    return reputation >= 97 ? "LEGEND" : "ORACLE";
  if (accuracy >= 0.8 && estimate_count >= 20) return "SAGE";
  if (estimate_count >= 5) return "ANALYST";
  return "OBSERVER";
}

function clamp01(x: number): number {
  return clamp(x, 0, 1);
}
function clamp(x: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, x));
}
