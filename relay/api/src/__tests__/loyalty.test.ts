import express from "express";
import supertest from "supertest";
import router from "../routes/loyalty";

// Mock the database pool
jest.mock("../db/pool", () => ({
  query: jest.fn(),
  queryOne: jest.fn(),
}));

// Mock rate limiting (let all requests through)
jest.mock("../middleware/rateLimit", () => ({
  publicRateLimit: (_: unknown, __: unknown, next: () => void) => next(),
  strictRateLimit: (_: unknown, __: unknown, next: () => void) => next(),
}));

// Mock cache — always execute the compute fn directly (no Redis)
jest.mock("../services/cache", () => ({
  getOrCompute: jest.fn((key: string, fn: () => Promise<unknown>) => fn()),
}));

// Mock SDK loyalty module
jest.mock("../../../sdk/src/loyalty", () => ({
  getLoyaltyBenefits: jest.fn(() => ({
    tier: "bronze",
    feeBps: 40,
    streakMultiplier: 1.0,
    bonuses: [],
  })),
  computeVolumeFeeDecay: jest.fn(() => 40),
  computeEffectiveFeeRate: jest.fn(() => 40),
  computeParticipantLoyalty: jest.fn((address: string, jobs: number) => ({
    address,
    tier: jobs >= 10 ? "bronze" : "unverified",
    feeDiscountBps: 0,
    canVote: jobs >= 5,
  })),
  computeEvaluatorLoyalty: jest.fn(() => ({
    address: "rEval",
    tier: "silver",
    totalVotes: 50,
    accuracy: 0.9,
    earnedRlusd: 100,
  })),
}));

// Mock SDK VRF module
jest.mock("../../../sdk/src/vrf", () => ({
  computeStreakMultiplier: jest.fn(() => 1.0),
}));

// Mock SDK jobs module (checkTenureEligibility)
jest.mock("../../../sdk/src/jobs", () => ({
  checkTenureEligibility: jest.fn(() => ({
    eligible: false,
    bondWaivedRlusd: 0,
  })),
}));

import { query, queryOne } from "../db/pool";
const mockQuery = query as jest.Mock;
const mockQueryOne = queryOne as jest.Mock;

const app = express();
app.use(express.json());
app.use("/", router);

const request = supertest(app);

beforeEach(() => {
  jest.clearAllMocks();
});

// ── GET /:address/status ──────────────────────────────────────────────────────

describe("GET /:address/status — basic response shape", () => {
  const address = "rActiveUser111111111111111111111111";

  beforeEach(() => {
    // jobStats query (jobs + volume)
    mockQueryOne
      .mockResolvedValueOnce({ jobs: "5", volume: "500" })
      // evalRow query (consecutive, slash_count, etc.)
      .mockResolvedValueOnce(null);

    // recentVotes query (returns empty by default)
    mockQuery.mockResolvedValueOnce([]);
  });

  it("returns 200", async () => {
    const res = await request.get(`/${address}/status`);
    expect(res.status).toBe(200);
  });

  it("includes tier in response", async () => {
    const res = await request.get(`/${address}/status`);
    expect(res.body).toHaveProperty("tier");
    expect(typeof res.body.tier).toBe("string");
  });

  it("includes streakMultiplier in response", async () => {
    const res = await request.get(`/${address}/status`);
    expect(res.body).toHaveProperty("streakMultiplier");
    expect(typeof res.body.streakMultiplier).toBe("number");
  });

  it("includes consecutiveAccurateVotes in response", async () => {
    const res = await request.get(`/${address}/status`);
    expect(res.body).toHaveProperty("consecutiveAccurateVotes");
    expect(typeof res.body.consecutiveAccurateVotes).toBe("number");
  });

  it("includes tenureEligible in response", async () => {
    const res = await request.get(`/${address}/status`);
    expect(res.body).toHaveProperty("tenureEligible");
    expect(typeof res.body.tenureEligible).toBe("boolean");
  });

  it("includes address in response", async () => {
    const res = await request.get(`/${address}/status`);
    expect(res.body.address).toBe(address);
  });

  it("includes volumeFeeBps in response", async () => {
    const res = await request.get(`/${address}/status`);
    expect(res.body).toHaveProperty("volumeFeeBps");
    expect(res.body.volumeFeeBps).toBe(40);
  });
});

// ── GET /:address/status — consecutiveAccurateVotes streak logic ──────────────

describe("GET /:address/status — streak calculation from recentVotes", () => {
  const address = "rEvaluator111111111111111111111111";

  it("counts consecutive evaluator_rewarded events before a slash", async () => {
    mockQueryOne
      .mockResolvedValueOnce({ jobs: "10", volume: "1000" }) // jobStats
      .mockResolvedValueOnce({                               // evalRow
        consecutive: "3",
        slash_count: "0",
        stake_amount: "2000",
        days_since_join: "90",
      });

    // 3 rewarded events, then no slash
    mockQuery.mockResolvedValueOnce([
      { event_type: "evaluator_rewarded", created_at: new Date().toISOString() },
      { event_type: "evaluator_rewarded", created_at: new Date().toISOString() },
      { event_type: "evaluator_rewarded", created_at: new Date().toISOString() },
    ]);

    const res = await request.get(`/${address}/status`);
    expect(res.status).toBe(200);
    expect(res.body.consecutiveAccurateVotes).toBe(3);
    // streakMultiplier = min(3.0, 1.0 + 3 * 0.1) = 1.3
    expect(res.body.streakMultiplier).toBeCloseTo(1.3, 4);
  });

  it("resets streak to 0 when first recent event is evaluator_slashed", async () => {
    mockQueryOne
      .mockResolvedValueOnce({ jobs: "10", volume: "1000" })
      .mockResolvedValueOnce(null);

    mockQuery.mockResolvedValueOnce([
      { event_type: "evaluator_slashed", created_at: new Date().toISOString() },
      { event_type: "evaluator_rewarded", created_at: new Date().toISOString() },
    ]);

    const res = await request.get(`/${address}/status`);
    expect(res.body.consecutiveAccurateVotes).toBe(0);
    expect(res.body.streakMultiplier).toBeCloseTo(1.0, 4);
  });

  it("returns 0 consecutiveAccurateVotes when no recent vote history", async () => {
    mockQueryOne
      .mockResolvedValueOnce({ jobs: "2", volume: "200" })
      .mockResolvedValueOnce(null);

    mockQuery.mockResolvedValueOnce([]);

    const res = await request.get(`/${address}/status`);
    expect(res.body.consecutiveAccurateVotes).toBe(0);
  });

  it("stops counting at slash boundary, not after", async () => {
    mockQueryOne
      .mockResolvedValueOnce({ jobs: "8", volume: "800" })
      .mockResolvedValueOnce(null);

    // Events in DESC order: 2 rewarded, then a slash, then more rewarded
    mockQuery.mockResolvedValueOnce([
      { event_type: "evaluator_rewarded", created_at: new Date().toISOString() },
      { event_type: "evaluator_rewarded", created_at: new Date().toISOString() },
      { event_type: "evaluator_slashed", created_at: new Date().toISOString() },
      { event_type: "evaluator_rewarded", created_at: new Date().toISOString() },
    ]);

    const res = await request.get(`/${address}/status`);
    // Only 2 rewarded before the slash break
    expect(res.body.consecutiveAccurateVotes).toBe(2);
  });
});

// ── GET /:address/status — evaluator not found (sensible defaults) ────────────

describe("GET /:address/status — sensible defaults when evaluator not found", () => {
  const address = "rNewParticipant111111111111111111111";

  beforeEach(() => {
    mockQueryOne
      .mockResolvedValueOnce(null) // no jobStats row (participant never completed jobs)
      .mockResolvedValueOnce(null); // no evaluator row

    mockQuery.mockResolvedValueOnce([]);
  });

  it("returns 200 even when evaluator not in DB", async () => {
    const res = await request.get(`/${address}/status`);
    expect(res.status).toBe(200);
  });

  it("defaults completedJobs to 0", async () => {
    const res = await request.get(`/${address}/status`);
    expect(res.body.completedJobs).toBe(0);
  });

  it("defaults streakMultiplier to 1.0", async () => {
    const res = await request.get(`/${address}/status`);
    expect(res.body.streakMultiplier).toBeCloseTo(1.0, 4);
  });

  it("defaults consecutiveAccurateVotes to 0", async () => {
    const res = await request.get(`/${address}/status`);
    expect(res.body.consecutiveAccurateVotes).toBe(0);
  });

  it("defaults tenureDays to 0", async () => {
    const res = await request.get(`/${address}/status`);
    expect(res.body.tenureDays).toBe(0);
  });
});

// ── GET /:address (full loyalty profile) ─────────────────────────────────────

describe("GET /:address — full loyalty profile", () => {
  const address = "rParticipant111111111111111111111111";

  it("returns 200 with address, participant, effectiveTier, benefits", async () => {
    mockQueryOne
      .mockResolvedValueOnce({ jobs: "20", volume: "5000", dates: [] }) // participant jobStats
      .mockResolvedValueOnce(null); // no evaluator stats

    const res = await request.get(`/${address}`);
    expect(res.status).toBe(200);
    expect(res.body.address).toBe(address);
    expect(res.body).toHaveProperty("participant");
    expect(res.body).toHaveProperty("effectiveTier");
    expect(res.body).toHaveProperty("benefits");
  });

  it("returns evaluator profile when evaluator stats found", async () => {
    mockQueryOne
      .mockResolvedValueOnce({ jobs: "20", volume: "5000", dates: [] })
      .mockResolvedValueOnce({
        total_votes: "50",
        accuracy: "0.90",
        days_since_join: "180",
        earned: "250",
      });

    const res = await request.get(`/${address}`);
    expect(res.status).toBe(200);
    expect(res.body.evaluator).not.toBeNull();
  });

  it("returns evaluator null when not an evaluator", async () => {
    mockQueryOne
      .mockResolvedValueOnce({ jobs: "5", volume: "500", dates: [] })
      .mockResolvedValueOnce(null);

    const res = await request.get(`/${address}`);
    expect(res.body.evaluator).toBeNull();
  });
});
