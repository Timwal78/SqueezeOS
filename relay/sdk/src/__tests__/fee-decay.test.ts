import {
  computeVolumeFeeDecay,
  computeEffectiveFeeRate,
  computeFeeWithDecay,
  VOLUME_FEE_LADDER,
} from "../loyalty";
import { checkTenureEligibility, DISPUTE_BOND_RLUSD } from "../jobs";

// ── computeVolumeFeeDecay ────────────────────────────────────────────────────

describe("computeVolumeFeeDecay", () => {
  it("returns 50 BPS for zero volume (new account)", () => {
    expect(computeVolumeFeeDecay(0)).toBe(50);
  });

  it("returns 50 BPS just below 1K threshold", () => {
    expect(computeVolumeFeeDecay(999)).toBe(50);
  });

  it("returns 40 BPS at exactly 1K", () => {
    expect(computeVolumeFeeDecay(1_000)).toBe(40);
  });

  it("returns 40 BPS between 1K and 10K", () => {
    expect(computeVolumeFeeDecay(5_000)).toBe(40);
  });

  it("returns 30 BPS at exactly 10K", () => {
    expect(computeVolumeFeeDecay(10_000)).toBe(30);
  });

  it("returns 20 BPS at 50K", () => {
    expect(computeVolumeFeeDecay(50_000)).toBe(20);
  });

  it("returns 10 BPS at 100K (floor rate)", () => {
    expect(computeVolumeFeeDecay(100_000)).toBe(10);
  });

  it("returns 10 BPS for any volume above 100K", () => {
    expect(computeVolumeFeeDecay(1_000_000)).toBe(10);
  });

  it("VOLUME_FEE_LADDER has 5 entries ordered descending by threshold", () => {
    expect(VOLUME_FEE_LADDER).toHaveLength(5);
    for (let i = 1; i < VOLUME_FEE_LADDER.length; i++) {
      expect(VOLUME_FEE_LADDER[i - 1].thresholdRlusd).toBeGreaterThan(
        VOLUME_FEE_LADDER[i].thresholdRlusd
      );
    }
  });
});

// ── computeEffectiveFeeRate ──────────────────────────────────────────────────

describe("computeEffectiveFeeRate", () => {
  it("applies no discount for unranked tier", () => {
    expect(computeEffectiveFeeRate(0, "unranked")).toBe(50);
  });

  it("applies no discount for scout tier", () => {
    expect(computeEffectiveFeeRate(0, "scout")).toBe(50);
  });

  it("applies 10% discount for builder tier at base rate", () => {
    // 50 BPS × (1 - 0.10) = 45 BPS
    expect(computeEffectiveFeeRate(0, "builder")).toBe(45);
  });

  it("applies volume decay + tier discount multiplicatively", () => {
    // veteran at 15K volume: volume rate = 30 BPS, tier discount = 20%
    // 30 × 0.80 = 24 BPS
    expect(computeEffectiveFeeRate(15_000, "veteran")).toBe(24);
  });

  it("applies legend 30% discount on top of volume decay", () => {
    // legend at 100K volume: volume rate = 10 BPS, tier discount = 30%
    // 10 × 0.70 = 7 BPS
    expect(computeEffectiveFeeRate(100_000, "legend")).toBe(7);
  });
});

// ── computeFeeWithDecay ──────────────────────────────────────────────────────

describe("computeFeeWithDecay", () => {
  it("returns correct fee amounts for a 1000 RLUSD job at base rate", () => {
    const { feeRlusd, feeBps, savings } = computeFeeWithDecay(1000, 0, "unranked");
    expect(feeBps).toBe(50);
    expect(feeRlusd).toBeCloseTo(5.0, 4);
    expect(savings).toBeCloseTo(0, 4);
  });

  it("shows savings vs base rate for high-volume legend", () => {
    // 1000 RLUSD job, 100K volume, legend tier
    // effectiveBps = 7, fee = 0.70, base fee = 5.00, savings = 4.30
    const { feeRlusd, feeBps, savings } = computeFeeWithDecay(1000, 100_000, "legend");
    expect(feeBps).toBe(7);
    expect(feeRlusd).toBeCloseTo(0.70, 4);
    expect(savings).toBeCloseTo(4.30, 4);
  });

  it("savings increases with cumulative volume", () => {
    const r1 = computeFeeWithDecay(1000, 0, "unranked");
    const r2 = computeFeeWithDecay(1000, 50_000, "unranked");
    expect(r2.savings).toBeGreaterThan(r1.savings);
  });
});

// ── checkTenureEligibility ────────────────────────────────────────────────────

describe("checkTenureEligibility", () => {
  it("eligible when both thresholds are met", () => {
    const result = checkTenureEligibility(90, 50);
    expect(result.eligible).toBe(true);
    expect(result.bondWaivedRlusd).toBe(DISPUTE_BOND_RLUSD);
    expect(result.reason).toBeUndefined();
  });

  it("not eligible with insufficient tenure days", () => {
    const result = checkTenureEligibility(45, 100);
    expect(result.eligible).toBe(false);
    expect(result.bondWaivedRlusd).toBe(0);
    expect(result.reason).toMatch(/more days tenure/);
  });

  it("not eligible with insufficient completed jobs", () => {
    const result = checkTenureEligibility(200, 10);
    expect(result.eligible).toBe(false);
    expect(result.reason).toMatch(/more completed jobs/);
  });

  it("not eligible when both conditions fail", () => {
    const result = checkTenureEligibility(10, 5);
    expect(result.eligible).toBe(false);
    expect(result.reason).toContain("tenure");
    expect(result.reason).toContain("jobs");
  });

  it("eligible at exactly the threshold boundaries", () => {
    expect(checkTenureEligibility(90, 50).eligible).toBe(true);
  });

  it("not eligible one day or one job short of threshold", () => {
    expect(checkTenureEligibility(89, 50).eligible).toBe(false);
    expect(checkTenureEligibility(90, 49).eligible).toBe(false);
  });

  it("reflects correct tenureDays and completedJobs in result", () => {
    const r = checkTenureEligibility(120, 75);
    expect(r.tenureDays).toBe(120);
    expect(r.completedJobs).toBe(75);
  });
});
