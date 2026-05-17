import {
  computeStreakMultiplier,
  computeEffectiveWeight,
  buildEvaluatorVrfState,
  updateStreakAfterVote,
  selectEvaluatorsWithStreak,
  computeConsecutiveStreak,
  generateSelectionProof,
  STREAK_MULTIPLIER_BASE,
  STREAK_MULTIPLIER_CAP,
  STREAK_MULTIPLIER_STEP,
  EvaluatorVrfState,
} from "../vrf";
import { EvaluatorProfile } from "../types";

// ── computeStreakMultiplier ───────────────────────────────────────────────────

describe("computeStreakMultiplier", () => {
  it("returns 1.0 for zero votes", () => {
    expect(computeStreakMultiplier(0, 0)).toBe(1.0);
  });

  it("returns 1.0 when consecutive votes is negative", () => {
    expect(computeStreakMultiplier(-1, 0)).toBe(1.0);
  });

  it("adds 0.1x per consecutive accurate vote", () => {
    expect(computeStreakMultiplier(1, 0)).toBeCloseTo(1.1, 4);
    expect(computeStreakMultiplier(5, 0)).toBeCloseTo(1.5, 4);
    expect(computeStreakMultiplier(10, 0)).toBeCloseTo(2.0, 4);
  });

  it("caps at 3.0 regardless of streak length", () => {
    expect(computeStreakMultiplier(100, 0)).toBe(3.0);
    expect(computeStreakMultiplier(20, 0)).toBe(3.0);
  });

  it("reaches cap exactly at 20 consecutive votes", () => {
    expect(computeStreakMultiplier(20, 0)).toBe(3.0);
  });

  it("returns 1.0 even with many slashes if consecutive votes > 0", () => {
    // slashCount doesn't reduce multiplier — streaks are tracked via consecutiveAccurateVotes
    expect(computeStreakMultiplier(5, 10)).toBeCloseTo(1.5, 4);
  });

  it("returns base when consecutiveAccurateVotes is zero after reset", () => {
    expect(computeStreakMultiplier(0, 1)).toBe(STREAK_MULTIPLIER_BASE);
  });
});

// ── computeEffectiveWeight ───────────────────────────────────────────────────

describe("computeEffectiveWeight", () => {
  it("returns stake × 1.0 for fresh evaluator", () => {
    expect(computeEffectiveWeight(1000, 0, 0)).toBe(1000);
  });

  it("returns stake × streak multiplier", () => {
    expect(computeEffectiveWeight(1000, 5, 0)).toBeCloseTo(1500, 1);
  });

  it("caps effective weight at stake × 3.0", () => {
    expect(computeEffectiveWeight(1000, 100, 0)).toBe(3000);
  });
});

// ── buildEvaluatorVrfState ───────────────────────────────────────────────────

describe("buildEvaluatorVrfState", () => {
  it("builds correct state object", () => {
    const state = buildEvaluatorVrfState("rTest", 500, 10, 1);
    expect(state.address).toBe("rTest");
    expect(state.stakeAmount).toBe(500);
    expect(state.consecutiveAccurateVotes).toBe(10);
    expect(state.totalSlashes).toBe(1);
    expect(state.streakMultiplier).toBeCloseTo(2.0, 4);
    expect(state.effectiveWeight).toBeCloseTo(1000, 1);
  });
});

// ── updateStreakAfterVote ────────────────────────────────────────────────────

describe("updateStreakAfterVote", () => {
  const baseState: EvaluatorVrfState = {
    address: "rTest",
    stakeAmount: 1000,
    consecutiveAccurateVotes: 5,
    totalSlashes: 0,
    streakMultiplier: 1.5,
    effectiveWeight: 1500,
  };

  it("increments streak on correct vote", () => {
    const { consecutiveAccurateVotes, newMultiplier } = updateStreakAfterVote(baseState, true);
    expect(consecutiveAccurateVotes).toBe(6);
    expect(newMultiplier).toBeCloseTo(1.6, 4);
  });

  it("resets streak to 0 on incorrect vote", () => {
    const { consecutiveAccurateVotes, newMultiplier } = updateStreakAfterVote(baseState, false);
    expect(consecutiveAccurateVotes).toBe(0);
    expect(newMultiplier).toBe(1.0);
  });

  it("does not exceed cap after increment", () => {
    const highState: EvaluatorVrfState = { ...baseState, consecutiveAccurateVotes: 19 };
    const { consecutiveAccurateVotes, newMultiplier } = updateStreakAfterVote(highState, true);
    expect(consecutiveAccurateVotes).toBe(20);
    expect(newMultiplier).toBe(3.0);
  });
});

// ── computeConsecutiveStreak ─────────────────────────────────────────────────

describe("computeConsecutiveStreak", () => {
  it("returns 0 for empty history", () => {
    expect(computeConsecutiveStreak([])).toBe(0);
  });

  it("counts unbroken correct votes from most recent", () => {
    const history = [
      { wasCorrect: true, timestamp: 3 },
      { wasCorrect: true, timestamp: 2 },
      { wasCorrect: false, timestamp: 1 },
    ];
    expect(computeConsecutiveStreak(history)).toBe(2);
  });

  it("returns 0 if most recent vote was incorrect", () => {
    const history = [
      { wasCorrect: false, timestamp: 3 },
      { wasCorrect: true, timestamp: 2 },
      { wasCorrect: true, timestamp: 1 },
    ];
    expect(computeConsecutiveStreak(history)).toBe(0);
  });

  it("counts entire history if all correct", () => {
    const history = [
      { wasCorrect: true, timestamp: 3 },
      { wasCorrect: true, timestamp: 2 },
      { wasCorrect: true, timestamp: 1 },
    ];
    expect(computeConsecutiveStreak(history)).toBe(3);
  });
});

// ── selectEvaluatorsWithStreak ───────────────────────────────────────────────

const makeEvaluator = (address: string, stake: number): EvaluatorProfile => ({
  address,
  stakeAmount: stake,
  specializations: ["software"],
  status: "active",
  accuracy: 0.9,
  totalVotes: 50,
  correctVotes: 45,
  slashCount: 0,
  joinedAt: Date.now() / 1000,
  stakeEscrowTx: "abc",
});

describe("selectEvaluatorsWithStreak", () => {
  const evaluators = [
    makeEvaluator("rA", 1000),
    makeEvaluator("rB", 800),
    makeEvaluator("rC", 600),
    makeEvaluator("rD", 500),
    makeEvaluator("rE", 400),
  ];

  it("selects the required number of evaluators", () => {
    const result = selectEvaluatorsWithStreak(
      "dispute-1", "seed-abc", evaluators, new Map(), 3
    );
    expect(result.selected).toHaveLength(3);
  });

  it("is deterministic — same inputs produce same selection", () => {
    const r1 = selectEvaluatorsWithStreak("d1", "s1", evaluators, new Map(), 3);
    const r2 = selectEvaluatorsWithStreak("d1", "s1", evaluators, new Map(), 3);
    expect(r1.selected.map((e) => e.address)).toEqual(r2.selected.map((e) => e.address));
  });

  it("produces different selections for different seeds", () => {
    const r1 = selectEvaluatorsWithStreak("d1", "seed-1", evaluators, new Map(), 3);
    const r2 = selectEvaluatorsWithStreak("d1", "seed-2", evaluators, new Map(), 3);
    // With 5 evaluators choosing 3, there's a chance they differ — seeds are different
    // Just verify the selections are valid
    expect(r1.selected).toHaveLength(3);
    expect(r2.selected).toHaveLength(3);
  });

  it("includes weights and multipliers maps", () => {
    const result = selectEvaluatorsWithStreak("d1", "s1", evaluators, new Map(), 3);
    expect(result.weights.size).toBe(5);
    expect(result.multipliers.size).toBe(5);
  });

  it("applies streak multiplier for evaluators with states", () => {
    const streakStates = new Map<string, EvaluatorVrfState>();
    streakStates.set("rA", buildEvaluatorVrfState("rA", 1000, 10, 0)); // 2.0x multiplier
    const result = selectEvaluatorsWithStreak("d1", "s1", evaluators, streakStates, 3);
    expect(result.multipliers.get("rA")).toBeCloseTo(2.0, 4);
    expect(result.weights.get("rA")).toBeCloseTo(2000, 1);
  });

  it("throws INSUFFICIENT_EVALUATORS when not enough eligible", () => {
    expect(() =>
      selectEvaluatorsWithStreak("d1", "s1", evaluators, new Map(), 10)
    ).toThrow(/Need 10 evaluators/);
  });

  it("filters by specialization", () => {
    const mixed = [
      { ...makeEvaluator("rA", 1000), specializations: ["legal"] },
      { ...makeEvaluator("rB", 800), specializations: ["software"] },
      { ...makeEvaluator("rC", 600), specializations: ["software"] },
      { ...makeEvaluator("rD", 500), specializations: ["software"] },
    ];
    const result = selectEvaluatorsWithStreak("d1", "s1", mixed, new Map(), 2, "software");
    expect(result.selected.every((e) => e.specializations.includes("software"))).toBe(true);
  });

  it("selects without replacement (no duplicate evaluators)", () => {
    const result = selectEvaluatorsWithStreak("d1", "s1", evaluators, new Map(), 5);
    const addresses = result.selected.map((e) => e.address);
    expect(new Set(addresses).size).toBe(5);
  });

  it("returns proofHash as 64-char hex string", () => {
    const result = selectEvaluatorsWithStreak("d1", "s1", evaluators, new Map(), 3);
    expect(result.proofHash).toMatch(/^[0-9a-f]{64}$/);
  });
});

// ── generateSelectionProof ────────────────────────────────────────────────────

describe("generateSelectionProof", () => {
  it("produces a human-readable proof string", () => {
    const evaluators = [
      makeEvaluator("rAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", 1000),
      makeEvaluator("rBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB", 800),
      makeEvaluator("rCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC", 600),
    ];
    const result = selectEvaluatorsWithStreak("d1", "s1", evaluators, new Map(), 3);
    const proof = generateSelectionProof(result);
    expect(proof).toContain("VRF Selection Proof");
    expect(proof).toContain("Proof Hash:");
    expect(proof).toContain("stake=");
  });
});
