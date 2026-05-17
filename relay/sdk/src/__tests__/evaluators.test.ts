import {
  selectEvaluators,
  resolveVotes,
  calculateEvaluatorOutcomes,
} from "../evaluators";
import { EvaluatorProfile, DisputeVote } from "../types";

const makeEvaluator = (address: string, stake = 500, specs = ["general"]): EvaluatorProfile => ({
  address,
  stakeAmount: stake,
  stakeEscrowTx: `tx_${address}`,
  specializations: specs,
  accuracy: 0.9,
  totalVotes: 10,
  correctVotes: 9,
  slashCount: 0,
  status: "active",
  joinedAt: Date.now() - 30 * 24 * 60 * 60 * 1000,
});

const pool: EvaluatorProfile[] = [
  makeEvaluator("rEval1", 1000, ["code_review"]),
  makeEvaluator("rEval2", 800, ["code_review", "design"]),
  makeEvaluator("rEval3", 600, ["design"]),
  makeEvaluator("rEval4", 700, ["legal"]),
  makeEvaluator("rEval5", 500, ["general"]),
  makeEvaluator("rEval6", 900, ["code_review"]),
  makeEvaluator("rEval7", 550, ["general"]),
];

describe("selectEvaluators", () => {
  it("returns the requested count", () => {
    const selected = selectEvaluators("dispute-1", "seed-abc", pool, 3);
    expect(selected).toHaveLength(3);
  });

  it("returns unique evaluators", () => {
    const selected = selectEvaluators("dispute-2", "seed-xyz", pool, 5);
    const addresses = selected.map((e) => e.address);
    expect(new Set(addresses).size).toBe(5);
  });

  it("is deterministic for same inputs", () => {
    const a = selectEvaluators("dispute-3", "seed-123", pool, 3).map((e) => e.address);
    const b = selectEvaluators("dispute-3", "seed-123", pool, 3).map((e) => e.address);
    expect(a).toEqual(b);
  });

  it("differs for different dispute IDs", () => {
    const a = selectEvaluators("dispute-A", "seed-123", pool, 3).map((e) => e.address);
    const b = selectEvaluators("dispute-B", "seed-123", pool, 3).map((e) => e.address);
    // Should not always be identical (probabilistic, but true for these inputs)
    expect(a.join(",")).not.toBe(b.join(","));
  });

  it("filters by specialization", () => {
    const selected = selectEvaluators("dispute-5", "seed-abc", pool, 2, "code_review");
    for (const e of selected) {
      expect(e.specializations).toContain("code_review");
    }
  });

  it("throws if insufficient evaluators", () => {
    expect(() => selectEvaluators("dispute-6", "seed", pool, 100)).toThrow(
      /Need 100 evaluators/
    );
  });
});

describe("resolveVotes", () => {
  const makeVote = (evaluator: string, vote: "hirer" | "worker" | "partial"): DisputeVote => ({
    evaluator,
    vote,
    signature: `sig_${evaluator}`,
    timestamp: Date.now(),
  });

  it("returns winner when threshold is met", () => {
    const votes = [
      makeVote("rEval1", "worker"),
      makeVote("rEval2", "worker"),
      makeVote("rEval3", "worker"),
    ];
    expect(resolveVotes(votes, 3)).toBe("worker");
  });

  it("returns null when threshold not met", () => {
    const votes = [
      makeVote("rEval1", "worker"),
      makeVote("rEval2", "hirer"),
    ];
    expect(resolveVotes(votes, 3)).toBeNull();
  });

  it("handles partial vote majority", () => {
    const votes = [
      makeVote("rEval1", "partial"),
      makeVote("rEval2", "partial"),
      makeVote("rEval3", "partial"),
    ];
    expect(resolveVotes(votes, 3)).toBe("partial");
  });
});

describe("calculateEvaluatorOutcomes", () => {
  const makeVote = (evaluator: string, vote: "hirer" | "worker" | "partial"): DisputeVote => ({
    evaluator,
    vote,
    signature: `sig_${evaluator}`,
    timestamp: Date.now(),
  });

  it("rewards correct voters and slashes incorrect", () => {
    const votes = [
      makeVote("rEval1", "worker"), // correct
      makeVote("rEval2", "worker"), // correct
      makeVote("rEval3", "hirer"),  // incorrect
    ];
    const stakes = new Map([
      ["rEval1", 500],
      ["rEval2", 500],
      ["rEval3", 1000],
    ]);

    const outcomes = calculateEvaluatorOutcomes(votes, "worker", 1000, stakes);

    // rEval3 loses 10% of 1000 = 100
    expect(outcomes.get("rEval3")!.slashed).toBe(100);
    expect(outcomes.get("rEval3")!.earned).toBe(0);

    // rEval1 and rEval2 earn base fee + bonus
    expect(outcomes.get("rEval1")!.earned).toBeGreaterThan(0);
    expect(outcomes.get("rEval2")!.earned).toBeGreaterThan(0);
  });

  it("base fee is 0.2% of job amount", () => {
    const votes = [makeVote("rEval1", "worker")];
    const stakes = new Map([["rEval1", 500]]);
    const outcomes = calculateEvaluatorOutcomes(votes, "worker", 1000, stakes);
    // 0.2% of 1000 = 2 RLUSD base fee, no slashing bonus (no losers)
    expect(outcomes.get("rEval1")!.earned).toBeCloseTo(2, 1);
  });
});
