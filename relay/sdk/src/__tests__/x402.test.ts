import {
  build402Response,
  parsePaymentHeader,
  buildPaymentHeader,
  meetsReputationRequirement,
  shouldEscrow,
} from "../x402";
import { ReputationScore } from "../types";

const mockScore = (score: number, tier: ReputationScore["tier"]): ReputationScore => ({
  address: "rTest123",
  score,
  tier,
  jobsCompleted: 10,
  totalVolume: 5000,
  disputeRate: 0.01,
  specializations: [],
  stakeAmount: 500,
  stakeDurationDays: 30,
  vouchedBy: [],
  attestationsGiven: 0,
  lastUpdated: Date.now(),
});

describe("build402Response", () => {
  it("returns 402 status with correct structure", () => {
    const response = build402Response(
      "xrpl_testnet",
      "rRecipient123",
      1.5,
      "endpoint-001"
    );
    expect(response.status).toBe(402);
    expect(response.body.asset).toBe("RLUSD");
    expect(response.body.amount).toBe("1.5");
    expect(response.body.pay_to).toBe("rRecipient123");
    expect(response.body.expires_at).toBeGreaterThan(Math.floor(Date.now() / 1000));
  });
});

describe("parsePaymentHeader / buildPaymentHeader", () => {
  it("round-trips correctly", () => {
    const header = buildPaymentHeader("xrpl_testnet", "deadbeef");
    const parsed = parsePaymentHeader(header);
    expect(parsed).not.toBeNull();
    expect(parsed?.scheme).toBe("exact");
    expect(parsed?.payload).toBe("deadbeef");
  });

  it("returns null for invalid header", () => {
    expect(parsePaymentHeader("not-valid-base64!!")).toBeNull();
    expect(parsePaymentHeader("dGVzdA==")).toBeNull(); // valid base64, invalid JSON structure
  });
});

describe("meetsReputationRequirement", () => {
  it("passes with no requirements", () => {
    expect(meetsReputationRequirement(mockScore(0, "unverified"))).toBe(true);
  });

  it("fails when score below minimum", () => {
    expect(meetsReputationRequirement(mockScore(99, "unverified"), 100)).toBe(false);
    expect(meetsReputationRequirement(mockScore(100, "bronze"), 100)).toBe(true);
  });

  it("fails when tier below minimum", () => {
    expect(
      meetsReputationRequirement(mockScore(500, "silver"), undefined, "gold")
    ).toBe(false);
    expect(
      meetsReputationRequirement(mockScore(2000, "gold"), undefined, "gold")
    ).toBe(true);
  });
});

describe("shouldEscrow", () => {
  it("returns true above default threshold of 10 RLUSD", () => {
    expect(shouldEscrow(10)).toBe(true);
    expect(shouldEscrow(9.99)).toBe(false);
  });

  it("respects custom threshold", () => {
    expect(shouldEscrow(100, 50)).toBe(true);
    expect(shouldEscrow(49, 50)).toBe(false);
  });
});
