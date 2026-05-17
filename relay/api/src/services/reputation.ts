import {
  calculateReputationScore,
  getReputationTier,
  ReputationMetadata,
} from "../../../sdk/src/reputation";
import { ReputationScore } from "../../../sdk/src/types";

export { calculateReputationScore, getReputationTier };

export function buildReputationScore(
  address: string,
  metrics: ReputationMetadata,
  networkPagerank: number = 0
): ReputationScore {
  const score = calculateReputationScore(metrics, networkPagerank);
  return {
    address,
    score,
    tier: getReputationTier(score),
    jobsCompleted: metrics.jobs_completed,
    totalVolume: metrics.total_volume,
    disputeRate: metrics.dispute_rate,
    evaluatorAccuracy: metrics.evaluator_accuracy ?? undefined,
    specializations: metrics.specializations,
    stakeAmount: 0,
    stakeDurationDays: metrics.stake_duration_days,
    vouchedBy: metrics.vouched_by,
    attestationsGiven: metrics.attestations_given,
    lastUpdated: Math.floor(Date.now() / 1000),
  };
}
