import express from "express";
import supertest from "supertest";
import router from "../routes/payments";

// Mock rate limiting (let all requests through)
jest.mock("../middleware/rateLimit", () => ({
  publicRateLimit: (_: unknown, __: unknown, next: () => void) => next(),
  strictRateLimit: (_: unknown, __: unknown, next: () => void) => next(),
}));

// Mock logger to suppress output
jest.mock("../services/logger", () => ({
  logger: { info: jest.fn(), warn: jest.fn(), error: jest.fn() },
}));

// Mock the xrpl service
jest.mock("../services/xrpl", () => ({
  verifyTxOnChain: jest.fn(),
}));

// Mock the cache service — pass-through (calls fn directly)
jest.mock("../services/cache", () => ({
  getOrCompute: jest.fn((_key: string, fn: () => Promise<unknown>) => fn()),
}));

// Mock xrpl module — decode and hashes.hashSignedTx
jest.mock("xrpl", () => ({
  decode: jest.fn(),
  hashes: {
    hashSignedTx: jest.fn(() => "A".repeat(64)),
  },
}));

import { verifyTxOnChain } from "../services/xrpl";
import { decode, hashes } from "xrpl";

const mockVerifyTxOnChain = verifyTxOnChain as jest.Mock;
const mockDecode = decode as jest.Mock;
const mockHashSignedTx = hashes.hashSignedTx as jest.Mock;

const app = express();
app.use(express.json());
app.use("/", router);

const request = supertest(app);

// A valid 64-char hex txHash
const VALID_TX_HASH = "A1B2C3D4E5F6" + "0".repeat(52);

beforeEach(() => {
  jest.clearAllMocks();
  // Default hashSignedTx to return a valid 64-char hex string
  mockHashSignedTx.mockReturnValue("A".repeat(64));
});

// ─── GET /verify/:txHash ─────────────────────────────────────────────────────

describe("GET /verify/:txHash", () => {
  it("returns 400 for invalid txHash format (too short)", async () => {
    const res = await request.get("/verify/SHORTBADHASH");
    expect(res.status).toBe(400);
    expect(res.body.code).toBe("INVALID_TX_HASH");
  });

  it("returns 400 for invalid txHash format (non-hex chars)", async () => {
    const badHash = "Z".repeat(64);
    const res = await request.get(`/verify/${badHash}`);
    expect(res.status).toBe(400);
    expect(res.body.code).toBe("INVALID_TX_HASH");
  });

  it("returns 400 for invalid network query param", async () => {
    const res = await request.get(`/verify/${VALID_TX_HASH}?network=invalid_net`);
    expect(res.status).toBe(400);
    expect(res.body.code).toBe("INVALID_NETWORK");
  });

  it("returns 200 with confirmed:false when tx not found or not tesSUCCESS", async () => {
    mockVerifyTxOnChain.mockResolvedValueOnce(false);
    const res = await request.get(`/verify/${VALID_TX_HASH}?network=xrpl_testnet`);
    expect(res.status).toBe(200);
    expect(res.body.confirmed).toBe(false);
    expect(res.body.valid).toBe(false);
  });

  it("returns 200 with confirmed:true and txHash when tx is confirmed", async () => {
    mockVerifyTxOnChain.mockResolvedValueOnce(true);
    const res = await request.get(`/verify/${VALID_TX_HASH}?network=xrpl_testnet`);
    expect(res.status).toBe(200);
    expect(res.body.confirmed).toBe(true);
    expect(res.body.valid).toBe(true);
    expect(res.body.txHash).toBe(VALID_TX_HASH);
    expect(res.body.network).toBe("xrpl_testnet");
  });

  it("uses xrpl_testnet as the default network", async () => {
    mockVerifyTxOnChain.mockResolvedValueOnce(true);
    const res = await request.get(`/verify/${VALID_TX_HASH}`);
    expect(res.status).toBe(200);
    expect(mockVerifyTxOnChain).toHaveBeenCalledWith("xrpl_testnet", VALID_TX_HASH);
  });
});

// ─── POST /verify ────────────────────────────────────────────────────────────

describe("POST /verify", () => {
  it("returns 400 when txBlob is missing", async () => {
    const res = await request.post("/verify").send({ network: "xrpl_testnet" });
    expect(res.status).toBe(400);
    expect(res.body.code).toBe("MISSING_TX_BLOB");
  });

  it("returns 400 when txBlob is not a string", async () => {
    const res = await request.post("/verify").send({ txBlob: 12345 });
    expect(res.status).toBe(400);
    expect(res.body.code).toBe("MISSING_TX_BLOB");
  });

  it("returns 400 when txBlob cannot be decoded", async () => {
    mockDecode.mockImplementationOnce(() => {
      throw new Error("Cannot decode");
    });
    const res = await request.post("/verify").send({ txBlob: "INVALIDBLOB" });
    expect(res.status).toBe(400);
    expect(res.body.code).toBe("INVALID_TX_BLOB");
  });

  it("returns 400 when TransactionType is not Payment", async () => {
    mockDecode.mockReturnValueOnce({
      TransactionType: "OfferCreate",
      Destination: "rDest1111111111111111111111111111",
      Amount: "1000000",
    });
    const res = await request.post("/verify").send({ txBlob: "SOMEBLOB" });
    expect(res.status).toBe(400);
    expect(res.body.code).toBe("WRONG_TX_TYPE");
  });

  it("returns 400 for invalid network", async () => {
    mockDecode.mockReturnValueOnce({
      TransactionType: "Payment",
      Destination: "rDest1111111111111111111111111111",
      Amount: "1000000",
    });
    const res = await request
      .post("/verify")
      .send({ txBlob: "SOMEBLOB", network: "bad_network" });
    expect(res.status).toBe(400);
    expect(res.body.code).toBe("INVALID_NETWORK");
  });

  it("returns 400 when Destination does not match recipient filter", async () => {
    mockDecode.mockReturnValueOnce({
      TransactionType: "Payment",
      Destination: "rActualDest111111111111111111111111",
      Amount: "1000000",
    });
    const res = await request.post("/verify").send({
      txBlob: "SOMEBLOB",
      recipient: "rExpectedDest11111111111111111111111",
    });
    expect(res.status).toBe(400);
    expect(res.body.code).toBe("WRONG_DESTINATION");
  });

  it("returns confirmed result when blob is valid Payment and tx is on-chain", async () => {
    mockDecode.mockReturnValueOnce({
      TransactionType: "Payment",
      Destination: "rDest1111111111111111111111111111",
      Amount: "1000000",
    });
    mockVerifyTxOnChain.mockResolvedValueOnce(true);

    const res = await request.post("/verify").send({ txBlob: "VALIDBLOB" });
    expect(res.status).toBe(200);
    expect(res.body.valid).toBe(true);
    expect(res.body.confirmed).toBe(true);
    expect(res.body.decoded.transactionType).toBe("Payment");
  });

  it("returns confirmed:false when blob is valid Payment but tx not confirmed", async () => {
    mockDecode.mockReturnValueOnce({
      TransactionType: "Payment",
      Destination: "rDest1111111111111111111111111111",
      Amount: "1000000",
    });
    mockVerifyTxOnChain.mockResolvedValueOnce(false);

    const res = await request.post("/verify").send({ txBlob: "VALIDBLOB" });
    expect(res.status).toBe(200);
    expect(res.body.valid).toBe(false);
    expect(res.body.confirmed).toBe(false);
  });
});
