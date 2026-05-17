import express from "express";
import supertest from "supertest";
import router from "../routes/jobs";

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

// Mock xrpl service
jest.mock("../services/xrpl", () => ({
  getChannelInfo: jest.fn(),
}));

// Mock logger to suppress output
jest.mock("../services/logger", () => ({
  logger: { info: jest.fn(), warn: jest.fn(), error: jest.fn() },
}));

import { query, queryOne } from "../db/pool";
import { getChannelInfo } from "../services/xrpl";

const mockQuery = query as jest.Mock;
const mockQueryOne = queryOne as jest.Mock;
const mockGetChannelInfo = getChannelInfo as jest.Mock;

const app = express();
app.use(express.json());
app.use("/", router);

const request = supertest(app);

beforeEach(() => {
  jest.clearAllMocks();
});

// ─── POST / ──────────────────────────────────────────────────────────────────

describe("POST /", () => {
  const validBody = {
    channelId: "CHAN001",
    hirer: "rHirer111111111111111111111111111",
    worker: "rWorker11111111111111111111111111",
    amount: "100",
    token: "RLUSD",
    milestones: [{ id: 1, description: "M1", amount: "100" }],
    txHash: "TXHASH001",
  };

  it("returns 400 when required fields are missing", async () => {
    const res = await request.post("/").send({ channelId: "CHAN001" });
    expect(res.status).toBe(400);
    expect(res.body.code).toBe("MISSING_FIELDS");
  });

  it("returns 400 with CHANNEL_NOT_FOUND when channel not found on XRPL", async () => {
    mockGetChannelInfo.mockResolvedValueOnce(null);
    const res = await request.post("/").send(validBody);
    expect(res.status).toBe(400);
    expect(res.body.code).toBe("CHANNEL_NOT_FOUND");
  });

  it("returns 400 with CHANNEL_MISMATCH when channel parties do not match", async () => {
    mockGetChannelInfo.mockResolvedValueOnce({
      account: "rOther1111111111111111111111111111",
      destination: "rWorker11111111111111111111111111",
    });
    const res = await request.post("/").send(validBody);
    expect(res.status).toBe(400);
    expect(res.body.code).toBe("CHANNEL_MISMATCH");
  });

  it("returns 201 with job data on valid creation", async () => {
    mockGetChannelInfo.mockResolvedValueOnce({
      account: "rHirer111111111111111111111111111",
      destination: "rWorker11111111111111111111111111",
    });
    const fakeJob = {
      id: "job-uuid-1",
      channel_id: "CHAN001",
      hirer: "rHirer111111111111111111111111111",
      worker: "rWorker11111111111111111111111111",
      amount: "100",
      token: "RLUSD",
      status: "pending",
      tx_hash: "TXHASH001",
    };
    // First query is the INSERT RETURNING *, second is the reputation event insert
    mockQuery.mockResolvedValueOnce([fakeJob]).mockResolvedValueOnce([]);

    const res = await request.post("/").send(validBody);
    expect(res.status).toBe(201);
    expect(res.body.jobId).toBe("job-uuid-1");
    expect(res.body.status).toBe("pending");
  });
});

// ─── GET /:id ────────────────────────────────────────────────────────────────

describe("GET /:id", () => {
  it("returns 404 when job not found", async () => {
    mockQueryOne.mockResolvedValueOnce(null);
    const res = await request.get("/nonexistent-id");
    expect(res.status).toBe(404);
    expect(res.body.code).toBe("NOT_FOUND");
  });

  it("returns 200 with job shape when found", async () => {
    const fakeJob = {
      id: "job-uuid-1",
      channel_id: "CHAN001",
      hirer: "rHirer111111111111111111111111111",
      worker: "rWorker11111111111111111111111111",
      amount: "100",
      token: "RLUSD",
      status: "pending",
      milestones: [],
      evaluator_pool: "default",
      timeout_days: 7,
      multi_sig_config: null,
      tx_hash: "TXHASH001",
      network: "xrpl_testnet",
      created_at: new Date().toISOString(),
      completed_at: null,
      dispute_id: null,
    };
    mockQueryOne.mockResolvedValueOnce(fakeJob);

    const res = await request.get("/job-uuid-1");
    expect(res.status).toBe(200);
    expect(res.body.jobId).toBe("job-uuid-1");
    expect(res.body.hirer).toBe("rHirer111111111111111111111111111");
    expect(res.body.worker).toBe("rWorker11111111111111111111111111");
    expect(res.body.status).toBe("pending");
  });
});

// ─── PATCH /:id/status ───────────────────────────────────────────────────────

describe("PATCH /:id/status", () => {
  it("returns 404 when job not found", async () => {
    // queryOne returns null for the job lookup
    mockQueryOne.mockResolvedValueOnce(null);
    const res = await request
      .patch("/nonexistent-id/status")
      .send({ status: "funded" });
    expect(res.status).toBe(404);
    expect(res.body.code).toBe("NOT_FOUND");
  });

  it("returns 400 for invalid status value", async () => {
    const res = await request
      .patch("/some-job-id/status")
      .send({ status: "invalid_status" });
    expect(res.status).toBe(400);
    expect(res.body.code).toBe("INVALID_STATUS");
  });
});

// ─── GET / ───────────────────────────────────────────────────────────────────

describe("GET / (list)", () => {
  it("returns 200 with jobs array when filtering by hirer", async () => {
    const fakeJobs = [
      {
        id: "job-uuid-1",
        channel_id: "CHAN001",
        hirer: "rHirer111111111111111111111111111",
        worker: "rWorker11111111111111111111111111",
        amount: "100",
        token: "RLUSD",
        status: "pending",
        milestones: [],
        evaluator_pool: "default",
        timeout_days: 7,
        multi_sig_config: null,
        tx_hash: "TXHASH001",
        network: "xrpl_testnet",
        created_at: new Date().toISOString(),
        completed_at: null,
        dispute_id: null,
      },
    ];
    mockQuery.mockResolvedValueOnce(fakeJobs);

    const res = await request.get("/?hirer=rHirer111111111111111111111111111");
    expect(res.status).toBe(200);
    expect(Array.isArray(res.body.jobs)).toBe(true);
    expect(res.body.jobs).toHaveLength(1);
    expect(res.body.jobs[0].jobId).toBe("job-uuid-1");
  });

  it("returns 200 with empty jobs array when no results", async () => {
    mockQuery.mockResolvedValueOnce([]);
    const res = await request.get("/");
    expect(res.status).toBe(200);
    expect(res.body.jobs).toEqual([]);
  });
});
