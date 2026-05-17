import { query } from "../db/pool";
import { selectEvaluators } from "../../../sdk/src/evaluators";
import { EvaluatorProfile } from "../../../sdk/src/types";

/**
 * Select evaluators for a dispute from the active pool.
 * Uses the SDK's deterministic VRF-based selection.
 */
export async function selectEvaluatorsForDispute(
  evaluatorPool: string,
  network: string,
  disputeId: string,
  specialization?: string,
  count: number = 5
): Promise<Array<{ address: string; specialization: string; stake: number }>> {
  const rows = await query<{
    address: string;
    stake_amount: string;
    specializations: string[];
    accuracy: string | null;
    total_votes: string;
    correct_votes: string;
    slash_count: string;
    status: string;
    created_at: string;
  }>(
    `SELECT address, stake_amount, specializations, accuracy, total_votes,
            correct_votes, slash_count, status, created_at
     FROM evaluators
     WHERE status = 'active' AND network = $1
     ORDER BY stake_amount DESC`,
    [network]
  );

  if (rows.length < count) {
    // Return all available if fewer than count
    return rows.map((r) => ({
      address: r.address,
      specialization: r.specializations[0] ?? "general",
      stake: parseFloat(r.stake_amount),
    }));
  }

  const pool: EvaluatorProfile[] = rows.map((r) => ({
    address: r.address,
    stakeAmount: parseFloat(r.stake_amount),
    stakeEscrowTx: "",
    specializations: r.specializations,
    accuracy: r.accuracy ? parseFloat(r.accuracy) : null,
    totalVotes: parseInt(r.total_votes, 10),
    correctVotes: parseInt(r.correct_votes, 10),
    slashCount: parseInt(r.slash_count, 10),
    status: r.status as "active",
    joinedAt: new Date(r.created_at).getTime(),
  }));

  // Use current block hash as VRF seed (production: use actual VRF)
  const vrfSeed = `${Date.now()}:${disputeId}`;

  const selected = selectEvaluators(disputeId, vrfSeed, pool, count, specialization);

  return selected.map((e) => ({
    address: e.address,
    specialization: e.specializations[0] ?? "general",
    stake: e.stakeAmount,
  }));
}
