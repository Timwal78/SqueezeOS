import express from "express";
import supertest from "supertest";
import router from "../routes/evaluators";

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

// Mock logger to suppress output
jest.mock("../services/logger", () => ({
  logger: { info: jest.fn(), warn: jest.fn(), error: jest.fn() },
}));

// Mock xrpl — deriveAddress returns "r" + first 10 chars of the public key
// so we can build matching test data.
jest.mock("xrpl", () => ({
  deriveAddress: jest.fn((pk: string) => "r" + pk.slice(0, 10)),
}));

import { query, queryOne } from "../db/pool";
import { deriveAddress } from "xrpl";

const mockQuery = query as jest.Mock;
const mockQueryOne = queryOne as jest.Mock;
const mockDeriveAddress = deriveAddress as jest.Mock;

const app = express();
app.use(express.json());
app.use("/", router);

const request = supertest(app);

// Build a deterministic address that matches the mock: "r" + first 10 chars of pk
const TEST_PK = "ABCDEF1234567890FFFF";
const TEST_ADDR = "r" + TEST_PK.slice(0, 10); // "rABCDEF1234"

beforeEach(() => {
  jest.clearAllMocks();
});

// ─── POST / ──────────────────────────────────────────────────────────────────

describe("POST / (register evaluator)", () => {
  const validBody = {
    address: TEST_ADDR,
    stakeEscrowTx: "ESCROW_TX_HASH",
    stakeAmount: "1000",
    specializations: ["dispute_resolution"],
    publicKey: TEST_PK,
    network: "xrpl_testnet",
  };

  it("returns 400 when required fields are missing", async () => {
    const res = await request.post("/").send({ address: TEST_ADDR });
    expect(res.status).toBe(400);
    expect(res.body.code).toBe("MISSING_FIELDS");
  });

  it("returns 400 when publicKey is invalid (throws in deriveAddress)", async () => {
    mockDeriveAddress.mockImplementationOnce(() => {
      throw new Error("Invalid key");
    });
    const res = await request.post("/").send(validBody);
    expect(res.status).toBe(400);
    expect(res.body.code).toBe("INVALID_KEY");
  });

  it("returns 400 when publicKey does not correspond to address (mismatch)", async () => {
    mockDeriveAddress.mockReturnValueOnce("rDifferentAddress1111111111111111");
    const res = await request.post("/").send(validBody);
    expect(res.status).toBe(400);
    expect(res.body.code).toBe("KEY_MISMATCH");
  });

  it("returns 400 when stake amount is too low (< 500 RLUSD)", async () => {
    // deriveAddress returns matching address
    mockDeriveAddress.mockReturnValueOnce(TEST_ADDR);
    const res = await request.post("/").send({ ...validBody, stakeAmount: "100" });
    expect(res.status).toBe(400);
    expect(res.body.code).toBe("INSUFFICIENT_STAKE");
  });

  it("returns 400 when no specializations provided", async () => {
    mockDeriveAddress.mockReturnValueOnce(TEST_ADDR);
    const res = await request
      .post("/")
      .send({ ...validBody, specializations: [] });
    expect(res.status).toBe(400);
    expect(res.body.code).toBe("NO_SPECIALIZATIONS");
  });

  it("returns 409 when evaluator is already registered", async () => {
    mockDeriveAddress.mockReturnValueOnce(TEST_ADDR);
    mockQueryOne.mockResolvedValueOnce({ id: "existing-eval-id" });
    const res = await request.post("/").send(validBody);
    expect(res.status).toBe(409);
    expect(res.body.code).toBe("ALREADY_REGISTERED");
  });

  it("returns 201 with evaluator data on valid registration", async () => {
    mockDeriveAddress.mockReturnValueOnce(TEST_ADDR);
    mockQueryOne.mockResolvedValueOnce(null); // not already registered
    const fakeEval = {
      address: TEST_ADDR,
      stake_amount: "1000",
      stake_escrow_tx: "ESCROW_TX_HASH",
      specializations: ["dispute_resolution"],
      accuracy: null,
      total_votes: "0",
      correct_votes: "0",
      slash_count: "0",
      last_vote_at: null,
      status: "active",
      network: "xrpl_testnet",
      created_at: new Date().toISOString(),
    };
    mockQuery.mockResolvedValueOnce([fakeEval]);

    const res = await request.post("/").send(validBody);
    expect(res.status).toBe(201);
    expect(res.body.address).toBe(TEST_ADDR);
    expect(res.body.stakeAmount).toBe("1000");
    expect(res.body.status).toBe("active");
  });
});

// ─── GET / ───────────────────────────────────────────────────────────────────

describe("GET / (list evaluators)", () => {
  it("returns 200 with evaluators array", async () => {
    const fakeEvals = [
      {
        address: TEST_ADDR,
        stake_amount: "1000",
        stake_escrow_tx: "ESCROW_TX_HASH",
        specializations: ["dispute_resolution"],
        accuracy: "0.95",
        total_votes: "10",
        correct_votes: "9",
        slash_count: "0",
        last_vote_at: null,
        status: "active",
        network: "xrpl_testnet",
        created_at: new Date().toISOString(),
      },
    ];
    mockQuery.mockResolvedValueOnce(fakeEvals);

    const res = await request.get("/");
    expect(res.status).toBe(200);
    expect(Array.isArray(res.body.evaluators)).toBe(true);
    expect(res.body.evaluators).toHaveLength(1);
    expect(res.body.count).toBe(1);
    expect(res.body.evaluators[0].address).toBe(TEST_ADDR);
  });

  it("returns 200 with empty evaluators array when none found", async () => {
    mockQuery.mockResolvedValueOnce([]);
    const res = await request.get("/");
    expect(res.status).toBe(200);
    expect(res.body.evaluators).toEqual([]);
    expect(res.body.count).toBe(0);
  });
});

// ─── GET /:address ───────────────────────────────────────────────────────────

describe("GET /:address (get evaluator profile)", () => {
  it("returns 404 when evaluator not found", async () => {
    mockQueryOne.mockResolvedValueOnce(null);
    const res = await request.get("/rNonexistentAddr111111111111111111");
    expect(res.status).toBe(404);
    expect(res.body.code).toBe("NOT_FOUND");
  });

  it("returns 200 with evaluator profile when found", async () => {
    const fakeEval = {
      address: TEST_ADDR,
      stake_amount: "1000",
      stake_escrow_tx: "ESCROW_TX_HASH",
      specializations: ["dispute_resolution"],
      accuracy: "0.95",
      total_votes: "10",
      correct_votes: "9",
      slash_count: "0",
      last_vote_at: null,
      status: "active",
      network: "xrpl_testnet",
      created_at: new Date().toISOString(),
    };
    mockQueryOne.mockResolvedValueOnce(fakeEval);

    const res = await request.get(`/${TEST_ADDR}`);
    expect(res.status).toBe(200);
    expect(res.body.address).toBe(TEST_ADDR);
    expect(res.body.stakeAmount).toBe("1000");
    expect(res.body.specializations).toEqual(["dispute_resolution"]);
  });
});
