/**
 * Analytics service — aggregates protocol-wide metrics for the dashboard API.
 *
 * All metrics are derived from the reputation_events and jobs tables.
 * No private data is exposed — all figures are public protocol statistics.
 */

import { query, queryOne } from "../db/pool";

export interface ProtocolStats {
  totalJobs: number;
  activeJobs: number;
  completedJobs: number;
  disputedJobs: number;
  totalVolumeRlusd: number;
  totalEvaluators: number;
  activeEvaluators: number;
  averageDisputeRate: number;
  averageJobValueRlusd: number;
  disputeResolutionRatePercent: number;
  topSpecializations: Array<{ specialization: string; count: number }>;
}

export interface VolumeTimeSeries {
  date: string;
  jobCount: number;
  volumeRlusd: number;
  disputeCount: number;
}

export interface LeaderboardEntry {
  address: string;
  score: number;
  tier: string;
  jobsCompleted: number;
  totalVolume: number;
  disputeRate: number;
}

export async function getProtocolStats(network: string): Promise<ProtocolStats> {
  const [jobStats, evalStats, disputeStats] = await Promise.all([
    queryOne<{
      total: string;
      active: string;
      completed: string;
      disputed: string;
      total_volume: string;
      avg_value: string;
    }>(
      `SELECT
         COUNT(*) AS total,
         COUNT(*) FILTER (WHERE status = 'active') AS active,
         COUNT(*) FILTER (WHERE status = 'completed') AS completed,
         COUNT(*) FILTER (WHERE status = 'disputed') AS disputed,
         COALESCE(SUM(amount), 0) AS total_volume,
         COALESCE(AVG(amount), 0) AS avg_value
       FROM jobs WHERE network = $1`,
      [network]
    ),
    queryOne<{ total: string; active: string }>(
      `SELECT
         COUNT(*) AS total,
         COUNT(*) FILTER (WHERE status = 'active') AS active
       FROM evaluators WHERE network = $1`,
      [network]
    ),
    queryOne<{ resolved: string; total: string }>(
      `SELECT
         COUNT(*) FILTER (WHERE status = 'resolved') AS resolved,
         COUNT(*) AS total
       FROM disputes d
       JOIN jobs j ON d.job_id = j.id
       WHERE j.network = $1`,
      [network]
    ),
  ]);

  const totalJobs = parseInt(jobStats?.total ?? "0", 10);
  const completedJobs = parseInt(jobStats?.completed ?? "0", 10);
  const disputedJobs = parseInt(jobStats?.disputed ?? "0", 10);
  const totalDisputes = parseInt(disputeStats?.total ?? "0", 10);
  const resolvedDisputes = parseInt(disputeStats?.resolved ?? "0", 10);

  // Top specializations from evaluators
  const specRows = await query<{ spec: string; count: string }>(
    `SELECT unnest(specializations) AS spec, COUNT(*) AS count
     FROM evaluators WHERE network = $1 AND status = 'active'
     GROUP BY spec ORDER BY count DESC LIMIT 5`,
    [network]
  );

  return {
    totalJobs,
    activeJobs: parseInt(jobStats?.active ?? "0", 10),
    completedJobs,
    disputedJobs,
    totalVolumeRlusd: parseFloat(jobStats?.total_volume ?? "0"),
    totalEvaluators: parseInt(evalStats?.total ?? "0", 10),
    activeEvaluators: parseInt(evalStats?.active ?? "0", 10),
    averageDisputeRate: totalJobs > 0 ? disputedJobs / totalJobs : 0,
    averageJobValueRlusd: parseFloat(jobStats?.avg_value ?? "0"),
    disputeResolutionRatePercent:
      totalDisputes > 0 ? (resolvedDisputes / totalDisputes) * 100 : 100,
    topSpecializations: specRows.map((r) => ({
      specialization: r.spec,
      count: parseInt(r.count, 10),
    })),
  };
}

export async function getVolumeTimeSeries(
  network: string,
  days: number = 30
): Promise<VolumeTimeSeries[]> {
  const rows = await query<{
    date: string;
    job_count: string;
    volume: string;
    dispute_count: string;
  }>(
    `SELECT
       DATE_TRUNC('day', j.created_at)::date AS date,
       COUNT(*) AS job_count,
       COALESCE(SUM(j.amount), 0) AS volume,
       COUNT(*) FILTER (WHERE j.status = 'disputed') AS dispute_count
     FROM jobs j
     WHERE j.network = $1
       AND j.created_at >= NOW() - ($2 || ' days')::interval
     GROUP BY DATE_TRUNC('day', j.created_at)
     ORDER BY date ASC`,
    [network, days.toString()]
  );

  return rows.map((r) => ({
    date: r.date,
    jobCount: parseInt(r.job_count, 10),
    volumeRlusd: parseFloat(r.volume),
    disputeCount: parseInt(r.dispute_count, 10),
  }));
}

export async function getReputationLeaderboard(
  network: string,
  limit: number = 20
): Promise<LeaderboardEntry[]> {
  // Aggregate from reputation events, join evaluator stake info
  const rows = await query<{
    address: string;
    jobs_completed: string;
    total_volume: string;
    disputes: string;
    stake_amount: string;
    stake_days: string;
  }>(
    `SELECT
       re.address,
       COUNT(DISTINCT CASE WHEN re.event_type = 'job_completed' THEN re.job_id END) AS jobs_completed,
       COALESCE(SUM(CASE WHEN re.event_type = 'job_completed' THEN re.amount ELSE 0 END), 0) AS total_volume,
       COUNT(DISTINCT CASE WHEN re.event_type = 'dispute_initiated' THEN re.dispute_id END) AS disputes,
       COALESCE(ev.stake_amount, 0) AS stake_amount,
       COALESCE(EXTRACT(DAY FROM NOW() - ev.created_at), 0) AS stake_days
     FROM reputation_events re
     LEFT JOIN evaluators ev ON ev.address = re.address AND ev.network = $1
     LEFT JOIN jobs j ON re.job_id = j.id
     WHERE (j.network = $1 OR j.network IS NULL)
     GROUP BY re.address, ev.stake_amount, ev.created_at
     ORDER BY jobs_completed DESC, total_volume DESC
     LIMIT $2`,
    [network, limit]
  );

  return rows.map((r) => {
    const jobs = parseInt(r.jobs_completed, 10);
    const volume = parseFloat(r.total_volume);
    const disputes = parseInt(r.disputes, 10);
    const disputeRate = jobs > 0 ? disputes / jobs : 0;
    const stakeDays = parseInt(r.stake_days, 10);

    const score = Math.round(
      jobs * 10 +
      volume / 1000 +
      (1 - Math.min(disputeRate, 1)) * 1000 +
      stakeDays * 2
    );

    const tier =
      score >= 5000 ? "platinum" :
      score >= 2000 ? "gold" :
      score >= 500  ? "silver" :
      score >= 100  ? "bronze" : "unverified";

    return {
      address: r.address,
      score,
      tier,
      jobsCompleted: jobs,
      totalVolume: volume,
      disputeRate,
    };
  });
}

export async function getEvaluatorPerformance(
  network: string,
  limit: number = 20
): Promise<Array<{
  address: string;
  totalVotes: number;
  accuracy: number;
  earnedRlusd: number;
  slashCount: number;
  stake: number;
}>> {
  const rows = await query<{
    address: string;
    total_votes: string;
    accuracy: string;
    slash_count: string;
    stake_amount: string;
    earned: string;
  }>(
    `SELECT
       e.address,
       e.total_votes,
       COALESCE(e.accuracy, 0) AS accuracy,
       e.slash_count,
       e.stake_amount,
       COALESCE(SUM(CASE WHEN re.event_type = 'evaluator_rewarded' THEN re.amount ELSE 0 END), 0) AS earned
     FROM evaluators e
     LEFT JOIN reputation_events re ON re.address = e.address
     WHERE e.network = $1 AND e.status = 'active'
     GROUP BY e.address, e.total_votes, e.accuracy, e.slash_count, e.stake_amount
     ORDER BY accuracy DESC, total_votes DESC
     LIMIT $2`,
    [network, limit]
  );

  return rows.map((r) => ({
    address: r.address,
    totalVotes: parseInt(r.total_votes, 10),
    accuracy: parseFloat(r.accuracy),
    earnedRlusd: parseFloat(r.earned),
    slashCount: parseInt(r.slash_count, 10),
    stake: parseFloat(r.stake_amount),
  }));
}
