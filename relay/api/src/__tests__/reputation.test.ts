import express from "express";
import supertest from "supertest";
import router from "../routes/reputation";

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

// Mock validate middleware
jest.mock("../middleware/validate", () => ({
  requireFields:
    (...fields: string[]) =>
    (req: express.Request, res: express.Response, next: express.NextFunction) => {
      for (const f of fields) {
        if (!req.body?.[f]) {
          res.status(400).json({ error: `${f} required`, code: "MISSING_FIELDS" });
          return;
        }
      }
      next();
    },
}));

// Mock logger to suppress output
jest.mock("../services/logger", () => ({
  logger: { info: jest.fn(), warn: jest.fn(), error: jest.fn() },
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

// ── GET /:address — zeroed stats for new address ──────────────────────────────

describe("GET /:address — zeroed stats for new address", () => {
  const address = "rNewAddress11111111111111111111111";

  beforeEach(() => {
    // queryOne sequence: stats → attestations_given → evaluator
    mockQueryOne
      .mockResolvedValueOnce({
        jobs_completed: "0",
        total_disputes: "0",
        total_volume: "0",
        total_votes: "0",
        correct_votes: "0",
      })
      .mockResolvedValueOnce({ count: "0" }) // attestations given
      .mockResolvedValueOnce(null);           // no evaluator row

    // query for attestations received
    mockQuery.mockResolvedValueOnce([]);
  });

  it("returns 200", async () => {
    const res = await request.get(`/${address}`);
    expect(res.status).toBe(200);
  });

  it("returns jobsCompleted = 0", async () => {
    const res = await request.get(`/${address}`);
    expect(res.body.jobsCompleted).toBe(0);
  });

  it("returns totalVolume = 0", async () => {
    const res = await request.get(`/${address}`);
    expect(res.body.totalVolume).toBe(0);
  });

  it("returns tier = silver for a fresh address (dispute_rate=0 gives base score 1000)", async () => {
    const res = await request.get(`/${address}`);
    // formula: (1 - dispute_rate) * 1000 = 1000 → silver (≥500)
    expect(res.body.tier).toBe("silver");
  });

  it("returns score >= 0", async () => {
    const res = await request.get(`/${address}`);
    expect(res.body.score).toBeGreaterThanOrEqual(0);
  });

  it("returns empty vouchedBy array", async () => {
    const res = await request.get(`/${address}`);
    expect(res.body.vouchedBy).toEqual([]);
  });

  it("returns attestationsGiven = 0", async () => {
    const res = await request.get(`/${address}`);
    expect(res.body.attestationsGiven).toBe(0);
  });

  it("returns stakeAmount = 0 when no evaluator row", async () => {
    const res = await request.get(`/${address}`);
    expect(res.body.stakeAmount).toBe(0);
  });
});

// ── GET /:address — address with job history ──────────────────────────────────

describe("GET /:address — address with job history", () => {
  const address = "rActiveWorker1111111111111111111111";

  beforeEach(() => {
    mockQueryOne
      .mockResolvedValueOnce({
        jobs_completed: "15",
        total_disputes: "1",
        total_volume: "12500",
        total_votes: "0",
        correct_votes: "0",
      })
      .mockResolvedValueOnce({ count: "3" }) // attestations given
      .mockResolvedValueOnce(null);           // no evaluator row

    mockQuery.mockResolvedValueOnce([
      { attester: "rVoucher1" },
      { attester: "rVoucher2" },
    ]);
  });

  it("returns 200", async () => {
    const res = await request.get(`/${address}`);
    expect(res.status).toBe(200);
  });

  it("returns score > 0 when jobs_completed > 0", async () => {
    const res = await request.get(`/${address}`);
    expect(res.body.score).toBeGreaterThan(0);
  });

  it("returns jobsCompleted = 15", async () => {
    const res = await request.get(`/${address}`);
    expect(res.body.jobsCompleted).toBe(15);
  });

  it("returns totalVolume = 12500", async () => {
    const res = await request.get(`/${address}`);
    expect(res.body.totalVolume).toBe(12500);
  });

  it("returns attestations array with vouchers", async () => {
    const res = await request.get(`/${address}`);
    expect(res.body.vouchedBy).toEqual(["rVoucher1", "rVoucher2"]);
  });

  it("returns attestationsGiven = 3", async () => {
    const res = await request.get(`/${address}`);
    expect(res.body.attestationsGiven).toBe(3);
  });
});

// ── GET /:address — tier logic mapping ───────────────────────────────────────

describe("GET /:address — score maps to correct tier", () => {
  function setupStats(overrides: Record<string, string>) {
    const defaults = {
      jobs_completed: "0",
      total_disputes: "0",
      total_volume: "0",
      total_votes: "0",
      correct_votes: "0",
    };
    mockQueryOne
      .mockResolvedValueOnce({ ...defaults, ...overrides })
      .mockResolvedValueOnce({ count: "0" })
      .mockResolvedValueOnce(null);
    mockQuery.mockResolvedValueOnce([]);
  }

  it("returns tier = silver for 0-job address (base dispute-free score = 1000)", async () => {
    setupStats({ jobs_completed: "0", total_volume: "0" });
    const res = await request.get("/rUnverified11111111111111111111111");
    // (1 - 0) * 1000 = 1000 → silver
    expect(res.body.tier).toBe("silver");
  });

  it("score increases with more jobs_completed", async () => {
    setupStats({ jobs_completed: "5", total_volume: "500" });
    const r1 = await request.get("/rAddr1");

    setupStats({ jobs_completed: "20", total_volume: "2000" });
    const r2 = await request.get("/rAddr2");

    expect(r2.body.score).toBeGreaterThan(r1.body.score);
  });
});

// ── GET /:address — evaluator data included in response ──────────────────────

describe("GET /:address — evaluator data included in response", () => {
  const address = "rEvaluator111111111111111111111111";

  beforeEach(() => {
    mockQueryOne
      .mockResolvedValueOnce({
        jobs_completed: "5",
        total_disputes: "0",
        total_volume: "5000",
        total_votes: "30",
        correct_votes: "27",
      })
      .mockResolvedValueOnce({ count: "1" })  // attestations given
      .mockResolvedValueOnce({                 // evaluator row
        stake_amount: "5000",
        created_at: new Date(Date.now() - 90 * 24 * 60 * 60 * 1000).toISOString(),
        specializations: ["defi", "nft"],
      });

    mockQuery.mockResolvedValueOnce([{ attester: "rVoucher1" }]);
  });

  it("returns stakeAmount from evaluator row", async () => {
    const res = await request.get(`/${address}`);
    expect(res.body.stakeAmount).toBe(5000);
  });

  it("returns specializations from evaluator row", async () => {
    const res = await request.get(`/${address}`);
    expect(res.body.specializations).toEqual(["defi", "nft"]);
  });

  it("returns stakeDurationDays > 0 when evaluator has a created_at", async () => {
    const res = await request.get(`/${address}`);
    expect(res.body.stakeDurationDays).toBeGreaterThan(0);
  });

  it("includes attestations in response", async () => {
    const res = await request.get(`/${address}`);
    expect(Array.isArray(res.body.vouchedBy)).toBe(true);
    expect(res.body.vouchedBy).toContain("rVoucher1");
  });
});

// ── GET /:address/events ──────────────────────────────────────────────────────

describe("GET /:address/events", () => {
  it("returns 200 with events array", async () => {
    mockQuery.mockResolvedValueOnce([
      { id: "1", address: "rAddr1", event_type: "job_completed", created_at: new Date().toISOString() },
    ]);
    const res = await request.get("/rAddr1/events");
    expect(res.status).toBe(200);
    expect(Array.isArray(res.body.events)).toBe(true);
    expect(res.body.events).toHaveLength(1);
    expect(res.body.address).toBe("rAddr1");
  });

  it("returns empty events array when no history", async () => {
    mockQuery.mockResolvedValueOnce([]);
    const res = await request.get("/rNoHistory11111111111111111111111/events");
    expect(res.status).toBe(200);
    expect(res.body.events).toEqual([]);
  });
});

// ── POST /attest ──────────────────────────────────────────────────────────────

describe("POST /attest", () => {
  const validAttest = {
    attester: "rAttester1111111111111111111111111",
    attestee: "rAttestee1111111111111111111111111",
    context: "completed-job-123",
    signature: "FAKESIG",
  };

  it("returns 400 when required fields are missing", async () => {
    const res = await request.post("/attest").send({ attester: "rAddr" });
    expect(res.status).toBe(400);
    expect(res.body.code).toBe("MISSING_FIELDS");
  });

  it("returns 403 when attester has fewer than 10 completed jobs", async () => {
    mockQueryOne.mockResolvedValueOnce({ count: "5" });
    const res = await request.post("/attest").send(validAttest);
    expect(res.status).toBe(403);
    expect(res.body.code).toBe("INSUFFICIENT_REPUTATION");
  });

  it("returns 201 when attester has 10+ completed jobs", async () => {
    mockQueryOne.mockResolvedValueOnce({ count: "10" });
    mockQuery
      .mockResolvedValueOnce([]) // INSERT attestation
      .mockResolvedValueOnce([]); // INSERT reputation_events

    const res = await request.post("/attest").send(validAttest);
    expect(res.status).toBe(201);
    expect(res.body.success).toBe(true);
    expect(res.body.attester).toBe(validAttest.attester);
    expect(res.body.attestee).toBe(validAttest.attestee);
  });
});
