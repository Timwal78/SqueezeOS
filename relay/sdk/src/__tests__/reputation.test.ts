import {
  calculateReputationScore,
  getReputationTier,
  computeNetworkPagerank,
  ReputationMetadata,
} from "../reputation";

const baseMetrics: ReputationMetadata = {
  jobs_completed: 10,
  total_volume: 5000,
  dispute_rate: 0.05,
  evaluator_accuracy: null,
  stake_duration_days: 30,
  specializations: [],
  joined_at: "2026-01-01",
  last_active: "2026-05-01",
  vouched_by: [],
  attestations_given: 0,
};

describe("calculateReputationScore", () => {
  it("returns 0 for fresh account with no activity", () => {
    const metrics: ReputationMetadata = {
      ...baseMetrics,
      jobs_completed: 0,
      total_volume: 0,
      dispute_rate: 0,
      stake_duration_days: 0,
    };
    const score = calculateReputationScore(metrics);
    // (0*10) + (0/1000) + (1-0)*1000 + 0*500 + 0*2 + 0*100 = 1000
    expect(score).toBe(1000);
  });

  it("includes evaluator accuracy when present", () => {
    const withAccuracy: ReputationMetadata = {
      ...baseMetrics,
      evaluator_accuracy: 0.9,
    };
    const without = calculateReputationScore(baseMetrics);
    const with_ = calculateReputationScore(withAccuracy);
    expect(with_ - without).toBeCloseTo(0.9 * 500, 0);
  });

  it("penalizes high dispute rate", () => {
    const highDispute: ReputationMetadata = { ...baseMetrics, dispute_rate: 0.5 };
    const lowDispute: ReputationMetadata = { ...baseMetrics, dispute_rate: 0.0 };
    expect(calculateReputationScore(lowDispute)).toBeGreaterThan(
      calculateReputationScore(highDispute)
    );
  });

  it("caps dispute_rate contribution at 0 when rate >= 1", () => {
    const maxDispute: ReputationMetadata = { ...baseMetrics, dispute_rate: 1.5 };
    const score = calculateReputationScore(maxDispute);
    // dispute contribution = (1 - 1) * 1000 = 0 (min clamped at 1)
    expect(score).toBeGreaterThanOrEqual(0);
  });

  it("adds pagerank bonus", () => {
    const noPagerank = calculateReputationScore(baseMetrics, 0);
    const withPagerank = calculateReputationScore(baseMetrics, 0.5);
    expect(withPagerank - noPagerank).toBeCloseTo(50, 0);
  });
});

describe("getReputationTier", () => {
  it("returns correct tier for each threshold", () => {
    expect(getReputationTier(0)).toBe("unverified");
    expect(getReputationTier(99)).toBe("unverified");
    expect(getReputationTier(100)).toBe("bronze");
    expect(getReputationTier(500)).toBe("silver");
    expect(getReputationTier(2000)).toBe("gold");
    expect(getReputationTier(5000)).toBe("platinum");
    expect(getReputationTier(9999)).toBe("platinum");
  });
});

describe("computeNetworkPagerank", () => {
  it("returns empty map for empty input", () => {
    expect(computeNetworkPagerank([])).toEqual(new Map());
  });

  it("sums to approximately 1 across all nodes", () => {
    const agents = [
      { address: "rA", completedWith: ["rB", "rC"] },
      { address: "rB", completedWith: ["rA"] },
      { address: "rC", completedWith: ["rA", "rB"] },
    ];
    const scores = computeNetworkPagerank(agents);
    const total = Array.from(scores.values()).reduce((a, b) => a + b, 0);
    expect(total).toBeCloseTo(1, 2);
  });

  it("gives higher score to well-connected nodes", () => {
    const agents = [
      { address: "rHub", completedWith: ["rA", "rB", "rC"] },
      { address: "rA", completedWith: ["rHub"] },
      { address: "rB", completedWith: ["rHub"] },
      { address: "rC", completedWith: ["rHub"] },
    ];
    const scores = computeNetworkPagerank(agents);
    // rHub receives links from A, B, C — should have highest score
    const hub = scores.get("rHub")!;
    const a = scores.get("rA")!;
    expect(hub).toBeGreaterThan(a);
  });
});
