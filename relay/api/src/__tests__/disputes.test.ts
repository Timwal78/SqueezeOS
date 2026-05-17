import express from "express";
import supertest from "supertest";
import router from "../routes/disputes";

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

// Mock the evaluator selector service
jest.mock("../services/evaluatorSelector", () => ({
  selectEvaluatorsForDispute: jest.fn(),
}));

// Mock logger to suppress output
jest.mock("../services/logger", () => ({
  logger: { info: jest.fn(), warn: jest.fn(), error: jest.fn() },
}));

// Mock the SDK voting module
jest.mock("../../../sdk/src/voting", () => ({
  validateVote: jest.fn(),
  buildVoteMessage: jest.fn(),
}));

// Mock xrpl verifySignature
jest.mock("xrpl", () => ({
  verifySignature: jest.fn(() => true),
}));

import { query, queryOne } from "../db/pool";
import { selectEvaluatorsForDispute } from "../services/evaluatorSelector";
import { validateVote } from "../../../sdk/src/voting";

const mockQuery = query as jest.Mock;
const mockQueryOne = queryOne as jest.Mock;
const mockSelectEvaluators = selectEvaluatorsForDispute as jest.Mock;
const mockValidateVote = validateVote as jest.Mock;

const app = express();
app.use(express.json());
app.use("/", router);

const request = supertest(app);

beforeEach(() => {
  jest.clearAllMocks();
});

// ─── POST / ──────────────────────────────────────────────────────────────────

describe("POST / (create dispute)", () => {
  const validBody = {
    jobId: "job-uuid-1",
    initiator: "rHirer111111111111111111111111111",
    reason: "Work not completed",
    requestedOutcome: "release_to_hirer",
  };

  const activeJob = {
    id: "job-uuid-1",
    hirer: "rHirer111111111111111111111111111",
    worker: "rWorker11111111111111111111111111",
    status: "active",
    evaluator_pool: "default",
    network: "xrpl_testnet",
    dispute_id: null,
    amount: "100",
  };

  it("returns 400 when required fields are missing", async () => {
    const res = await request.post("/").send({ jobId: "job-uuid-1" });
    expect(res.status).toBe(400);
    expect(res.body.code).toBe("MISSING_FIELDS");
  });

  it("returns 400 when requestedOutcome is invalid", async () => {
    const res = await request
      .post("/")
      .send({ ...validBody, requestedOutcome: "give_to_nobody" });
    expect(res.status).toBe(400);
    expect(res.body.code).toBe("INVALID_OUTCOME");
  });

  it("returns 404 when job not found", async () => {
    mockQueryOne.mockResolvedValueOnce(null);
    const res = await request.post("/").send(validBody);
    expect(res.status).toBe(404);
    expect(res.body.code).toBe("NOT_FOUND");
  });

  it("returns 409 when job is already closed (completed)", async () => {
    mockQueryOne.mockResolvedValueOnce({ ...activeJob, status: "completed" });
    const res = await request.post("/").send(validBody);
    expect(res.status).toBe(409);
    expect(res.body.code).toBe("JOB_CLOSED");
  });

  it("returns 409 when job is already closed (cancelled)", async () => {
    mockQueryOne.mockResolvedValueOnce({ ...activeJob, status: "cancelled" });
    const res = await request.post("/").send(validBody);
    expect(res.status).toBe(409);
    expect(res.body.code).toBe("JOB_CLOSED");
  });

  it("returns 403 when initiator is not party to job", async () => {
    mockQueryOne.mockResolvedValueOnce(activeJob);
    const res = await request
      .post("/")
      .send({ ...validBody, initiator: "rStranger111111111111111111111111" });
    expect(res.status).toBe(403);
    expect(res.body.code).toBe("UNAUTHORIZED");
  });

  it("returns 409 when dispute already exists for job", async () => {
    mockQueryOne.mockResolvedValueOnce({
      ...activeJob,
      dispute_id: "existing-dispute-id",
    });
    const res = await request.post("/").send(validBody);
    expect(res.status).toBe(409);
    expect(res.body.code).toBe("DISPUTE_EXISTS");
  });

  it("returns 201 with dispute data on valid creation", async () => {
    mockQueryOne.mockResolvedValueOnce(activeJob);
    const selectedEvaluators = [
      { address: "rEval111111111111111111111111111", specialization: "general", stake: 1000 },
    ];
    mockSelectEvaluators.mockResolvedValueOnce(selectedEvaluators);
    // INSERT dispute, UPDATE job status, INSERT reputation event (all as query calls)
    mockQuery.mockResolvedValue([]);

    const res = await request.post("/").send(validBody);
    expect(res.status).toBe(201);
    expect(res.body).toHaveProperty("disputeId");
    expect(res.body.jobId).toBe("job-uuid-1");
    expect(res.body.status).toBe("pending");
    expect(res.body.selectedEvaluators).toEqual(selectedEvaluators);
  });
});

// ─── GET /:id ────────────────────────────────────────────────────────────────

describe("GET /:id (get dispute)", () => {
  it("returns 404 when dispute not found", async () => {
    mockQueryOne.mockResolvedValueOnce(null);
    const res = await request.get("/nonexistent-dispute-id");
    expect(res.status).toBe(404);
    expect(res.body.code).toBe("NOT_FOUND");
  });

  it("returns 200 with dispute data when found", async () => {
    const fakeDispute = {
      id: "dispute-uuid-1",
      job_id: "job-uuid-1",
      initiator: "rHirer111111111111111111111111111",
      reason: "Work not completed",
      evidence: [],
      requested_outcome: "release_to_hirer",
      status: "pending",
      selected_evaluators: [],
      votes: [],
      outcome: null,
      resolution_tx_hash: null,
      created_at: new Date().toISOString(),
      resolved_at: null,
    };
    mockQueryOne.mockResolvedValueOnce(fakeDispute);

    const res = await request.get("/dispute-uuid-1");
    expect(res.status).toBe(200);
    expect(res.body.disputeId).toBe("dispute-uuid-1");
    expect(res.body.jobId).toBe("job-uuid-1");
    expect(res.body.status).toBe("pending");
  });
});

// ─── GET / ───────────────────────────────────────────────────────────────────

describe("GET / (list disputes)", () => {
  it("returns 400 when jobId query param is missing", async () => {
    const res = await request.get("/");
    expect(res.status).toBe(400);
    expect(res.body.code).toBe("MISSING_PARAM");
  });

  it("returns 200 with disputes array when jobId is provided", async () => {
    mockQuery.mockResolvedValueOnce([]);
    const res = await request.get("/?jobId=job-uuid-1");
    expect(res.status).toBe(200);
    expect(Array.isArray(res.body.disputes)).toBe(true);
  });
});

// ─── POST /:id/vote ──────────────────────────────────────────────────────────

describe("POST /:id/vote (submit vote)", () => {
  const disputeId = "dispute-uuid-1";

  const validVoteBody = {
    evaluator: "rEval111111111111111111111111111",
    vote: "hirer",
    signature: "ABCDEF1234",
    publicKey: "ED1234ABCDEF",
    timestamp: Date.now(),
  };

  const pendingDispute = {
    id: disputeId,
    job_id: "job-uuid-1",
    status: "pending",
    selected_evaluators: [
      { address: "rEval111111111111111111111111111", specialization: "general", stake: 1000 },
    ],
    votes: [],
  };

  it("returns 400 when vote value is invalid", async () => {
    // requireFields will pass since all fields are present; then vote validation runs
    const res = await request
      .post(`/${disputeId}/vote`)
      .send({ ...validVoteBody, vote: "invalid_vote" });
    expect(res.status).toBe(400);
    expect(res.body.code).toBe("INVALID_VOTE");
  });

  it("returns 404 when dispute not found", async () => {
    mockQueryOne.mockResolvedValueOnce(null);
    const res = await request.post(`/${disputeId}/vote`).send(validVoteBody);
    expect(res.status).toBe(404);
    expect(res.body.code).toBe("NOT_FOUND");
  });

  it("returns 403 when evaluator is not in selected list", async () => {
    mockQueryOne.mockResolvedValueOnce({
      ...pendingDispute,
      selected_evaluators: [
        { address: "rSomeOtherEval1111111111111111111", specialization: "general", stake: 1000 },
      ],
    });
    const res = await request.post(`/${disputeId}/vote`).send(validVoteBody);
    expect(res.status).toBe(403);
    expect(res.body.code).toBe("NOT_SELECTED");
  });

  it("returns 409 when evaluator has already voted (duplicate)", async () => {
    mockQueryOne.mockResolvedValueOnce({
      ...pendingDispute,
      votes: [{ evaluator: "rEval111111111111111111111111111", vote: "hirer" }],
    });
    const res = await request.post(`/${disputeId}/vote`).send(validVoteBody);
    expect(res.status).toBe(409);
    expect(res.body.code).toBe("DUPLICATE_VOTE");
  });

  it("returns 400 when validateVote throws (invalid signature)", async () => {
    mockQueryOne.mockResolvedValueOnce(pendingDispute);
    mockValidateVote.mockImplementationOnce(() => {
      const err = new Error("Invalid signature") as Error & { code?: string };
      err.code = "INVALID_SIGNATURE";
      throw err;
    });
    const res = await request.post(`/${disputeId}/vote`).send(validVoteBody);
    expect(res.status).toBe(400);
    expect(res.body.code).toBe("INVALID_SIGNATURE");
  });

  it("returns 200 with vote recorded on valid submission", async () => {
    mockQueryOne.mockResolvedValueOnce(pendingDispute);
    mockValidateVote.mockReturnValueOnce(undefined); // no throw = valid
    mockQuery.mockResolvedValue([]);

    const res = await request.post(`/${disputeId}/vote`).send(validVoteBody);
    expect(res.status).toBe(200);
    expect(res.body.disputeId).toBe(disputeId);
    expect(res.body.votesCount).toBe(1);
  });
});
