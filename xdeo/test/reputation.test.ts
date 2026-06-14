import { describe, it, expect } from "vitest";
import {
  accuracyTerm,
  timelinessTerm,
  scoreEstimate,
  updateReputation,
  streakMultiplier,
  advanceStreak,
  computeTier
} from "../src/reputation/engine.js";

describe("accuracyTerm", () => {
  it("is 1.0 for an exact prediction", () => {
    const { acc, errorPct } = accuracyTerm(1.47, 1.47);
    expect(acc).toBeCloseTo(1, 5);
    expect(errorPct).toBe(0);
  });

  it("decays with relative error (~0.5 at 10% error)", () => {
    const { acc, errorPct } = accuracyTerm(1.1, 1.0);
    expect(errorPct).toBeCloseTo(0.1, 5);
    expect(acc).toBeGreaterThan(0.45);
    expect(acc).toBeLessThan(0.55);
  });

  it("is near zero for a wildly wrong call", () => {
    const { acc } = accuracyTerm(5, 1);
    expect(acc).toBeLessThan(0.01);
  });

  it("handles a zero actual without dividing by zero", () => {
    const { acc } = accuracyTerm(0.01, 0);
    expect(Number.isFinite(acc)).toBe(true);
  });
});

describe("timelinessTerm", () => {
  it("gives full credit at >= 30 days lead", () => {
    expect(timelinessTerm(40 * 86400)).toBeCloseTo(1, 5);
  });
  it("floors at 0.25 for last-minute calls", () => {
    expect(timelinessTerm(0)).toBeCloseTo(0.25, 5);
  });
});

describe("scoreEstimate", () => {
  it("rewards an accurate, confident, early call highly", () => {
    const r = scoreEstimate({ predicted: 1.47, actual: 1.47, confidence: 1, leadSeconds: 30 * 86400 });
    expect(r.score).toBeGreaterThan(95);
  });
  it("punishes a confident miss more than a timid one", () => {
    const confidentMiss = scoreEstimate({ predicted: 2, actual: 1, confidence: 1, leadSeconds: 0 });
    const timidMiss = scoreEstimate({ predicted: 2, actual: 1, confidence: 0, leadSeconds: 0 });
    expect(confidentMiss.score).toBeLessThan(timidMiss.score);
  });
});

describe("updateReputation", () => {
  it("moves reputation toward a good score and compounds over hits", () => {
    let state = { reputation: 0, accuracy: 0, scored_count: 0 };
    const good = scoreEstimate({ predicted: 1, actual: 1, confidence: 0.8, leadSeconds: 30 * 86400 });
    for (let i = 0; i < 10; i++) {
      state = updateReputation(state, good, 1);
    }
    expect(state.reputation).toBeGreaterThan(70);
    expect(state.scored_count).toBe(10);
  });

  it("dents but does not erase a long good history on a single miss", () => {
    const before = 90;
    let state = { reputation: before, accuracy: 0.9, scored_count: 50 };
    const miss = scoreEstimate({ predicted: 3, actual: 1, confidence: 1, leadSeconds: 0 });
    state = updateReputation(state, miss, 1);
    // The miss must register (reputation falls) ...
    expect(state.reputation).toBeLessThan(before);
    // ... but a veteran's bounded EMA step (alpha floor 0.08) caps the drop
    // at ~10%, so one bad quarter cannot wipe out a hard-won record.
    expect(state.reputation).toBeGreaterThan(80);
    expect(before - state.reputation).toBeLessThan(10);
  });

  it("streak multiplier only boosts gains, never beyond 100", () => {
    let state = { reputation: 95, accuracy: 0.95, scored_count: 5 };
    const good = scoreEstimate({ predicted: 1, actual: 1, confidence: 1, leadSeconds: 30 * 86400 });
    state = updateReputation(state, good, 5);
    expect(state.reputation).toBeLessThanOrEqual(100);
  });
});

describe("streakMultiplier", () => {
  it("matches the spec anchor points", () => {
    expect(streakMultiplier(0)).toBeCloseTo(1, 5);
    expect(streakMultiplier(7)).toBeCloseTo(1.5, 5);
    expect(streakMultiplier(30)).toBeCloseTo(2.5, 5);
    expect(streakMultiplier(100)).toBeCloseTo(5, 5);
    expect(streakMultiplier(999)).toBe(5);
  });
});

describe("advanceStreak", () => {
  it("starts at 1 on first activity", () => {
    expect(advanceStreak(null, 0, "2026-06-14")).toBe(1);
  });
  it("increments on consecutive days", () => {
    expect(advanceStreak("2026-06-13", 4, "2026-06-14")).toBe(5);
  });
  it("is unchanged on same-day activity", () => {
    expect(advanceStreak("2026-06-14", 5, "2026-06-14")).toBe(5);
  });
  it("resets after a gap", () => {
    expect(advanceStreak("2026-06-10", 9, "2026-06-14")).toBe(1);
  });
});

describe("computeTier", () => {
  it("OBSERVER below 5 estimates", () => {
    expect(computeTier({ reputation: 0, accuracy: 0, estimate_count: 1 })).toBe("OBSERVER");
  });
  it("ANALYST at 5+ estimates", () => {
    expect(computeTier({ reputation: 30, accuracy: 0.5, estimate_count: 5 })).toBe("ANALYST");
  });
  it("SAGE at 80%+ accuracy and 20+ estimates", () => {
    expect(computeTier({ reputation: 60, accuracy: 0.82, estimate_count: 25 })).toBe("SAGE");
  });
  it("ORACLE for top-10 with high reputation", () => {
    expect(
      computeTier({ reputation: 92, accuracy: 0.9, estimate_count: 50, globalRank: 3 })
    ).toBe("ORACLE");
  });
  it("LEGEND for elite top-10", () => {
    expect(
      computeTier({ reputation: 98, accuracy: 0.95, estimate_count: 80, globalRank: 1 })
    ).toBe("LEGEND");
  });
});
