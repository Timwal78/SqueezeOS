/**
 * Unit tests for the disputeSettler service.
 *
 * Tests the service functions directly (no HTTP layer).
 * All DB and SDK dependencies are mocked.
 */

import { updateEvaluatorStats, finalizeSettlement } from "../services/disputeSettler";

// Mock the database pool
jest.mock("../db/pool", () => ({
  query: jest.fn(),
  queryOne: jest.fn(),
}));

// Mock SDK settlement helpers
jest.mock("../../../sdk/src/settlement", () => ({
  getLedgerVrfSeed: jest.fn(),
  buildSettlementTx: jest.fn(),
  calculateSettlementAmounts: jest.fn(() => ({
    toHirer: "500000",
    toWorker: "500000",
  })),
}));

// Mock SDK evaluators module
jest.mock("../../../sdk/src/evaluators", () => ({
  resolveVotes: jest.fn(),
}));

// Mock SDK VRF module — returns a new streak after each vote
jest.mock("../../../sdk/src/vrf", () => ({
  updateStreakAfterVote: jest.fn(() => ({
    consecutiveAccurateVotes: 1,
    newMultiplier: 1.1,
  })),
}));

// Mock logger to suppress output during tests
jest.mock("../services/logger", () => ({
  logger: { info: jest.fn(), warn: jest.fn(), error: jest.fn() },
}));

import { query, queryOne } from "../db/pool";
import { updateStreakAfterVote } from "../../../sdk/src/vrf";

const mockQuery = query as jest.Mock;
const mockQueryOne = queryOne as jest.Mock;
const mockUpdateStreak = updateStreakAfterVote as jest.Mock;

// ── shared test data ──────────────────────────────────────────────────────────

const DISPUTE_ID = "dispute-uuid-1";
const JOB_ID = "job-1";
const HIRER = "rHirer111111111111111111111111111";
const WORKER = "rWorker11111111111111111111111111";
const EVALUATOR_A = "rEvalA11111111111111111111111111";
const EVALUATOR_B = "rEvalB11111111111111111111111111";

const DISPUTE_ROW = {
  votes: [
    { evaluator: EVALUATOR_A, vote: "hirer" },
    { evaluator: EVALUATOR_B, vote: "worker" },
  ],
};

const EVALUATOR_STATS = {
  consecutive_accurate_votes: 3,
  slash_count: 0,
  stake_amount: "1000",
};

const JOB_ROW = {
  job_id: JOB_ID,
  hirer: HIRER,
  worker: WORKER,
  amount: "100",
};

beforeEach(() => {
  jest.clearAllMocks();
});

// ── updateEvaluatorStats ──────────────────────────────────────────────────────

describe("updateEvaluatorStats", () => {
  function setupForWinnerHirer() {
    // queryOne calls in order:
    //   1. dispute votes fetch
    //   2. evaluator stats for EVALUATOR_A
    //   3. evaluator stats for EVALUATOR_B
    mockQueryOne
      .mockResolvedValueOnce(DISPUTE_ROW)
      .mockResolvedValueOnce(EVALUATOR_STATS)
      .mockResolvedValueOnce(EVALUATOR_STATS);

    // query calls: DB UPDATE for each evaluator + 2 reputation_events inserts
    mockQuery.mockResolvedValue([]);
  }

  it("calls DB update for each vote in the dispute", async () => {
    setupForWinnerHirer();
    await updateEvaluatorStats(DISPUTE_ID, "hirer");

    // There are 2 votes, so we expect 2 UPDATE evaluators calls
    // plus 2 INSERT reputation_events calls → 4 query calls total
    expect(mockQuery).toHaveBeenCalledTimes(4);
  });

  it("marks winning voter (hirer) with isCorrect=true in DB update", async () => {
    setupForWinnerHirer();
    await updateEvaluatorStats(DISPUTE_ID, "hirer");

    // First UPDATE call is for EVALUATOR_A (voted hirer = winner)
    const firstUpdateCall = mockQuery.mock.calls.find(
      (call) => call[0].includes("UPDATE evaluators") && call[1][3] === EVALUATOR_A
    );
    expect(firstUpdateCall).toBeDefined();
    // correct_votes incremented by 1 (isCorrect=true)
    expect(firstUpdateCall![1][0]).toBe(1);
  });

  it("marks losing voter (worker) with isCorrect=false in DB update", async () => {
    setupForWinnerHirer();
    await updateEvaluatorStats(DISPUTE_ID, "hirer");

    // EVALUATOR_B voted "worker" but winner is "hirer" → isCorrect=false
    const secondUpdateCall = mockQuery.mock.calls.find(
      (call) => call[0].includes("UPDATE evaluators") && call[1][3] === EVALUATOR_B
    );
    expect(secondUpdateCall).toBeDefined();
    // correct_votes incremented by 0 (isCorrect=false)
    expect(secondUpdateCall![1][0]).toBe(0);
  });

  it("calls updateStreakAfterVote with wasCorrect=true for winning voter", async () => {
    setupForWinnerHirer();
    await updateEvaluatorStats(DISPUTE_ID, "hirer");

    // First call to updateStreakAfterVote should have isCorrect=true (EVALUATOR_A)
    const calls = mockUpdateStreak.mock.calls;
    expect(calls[0][1]).toBe(true); // wasCorrect
    expect(calls[0][0].address).toBe(EVALUATOR_A);
  });

  it("calls updateStreakAfterVote with wasCorrect=false for losing voter", async () => {
    setupForWinnerHirer();
    await updateEvaluatorStats(DISPUTE_ID, "hirer");

    const calls = mockUpdateStreak.mock.calls;
    expect(calls[1][1]).toBe(false); // wasCorrect
    expect(calls[1][0].address).toBe(EVALUATOR_B);
  });

  it("writes new consecutiveAccurateVotes returned by updateStreakAfterVote to DB", async () => {
    mockUpdateStreak.mockReturnValue({
      consecutiveAccurateVotes: 5,
      newMultiplier: 1.5,
    });

    mockQueryOne
      .mockResolvedValueOnce(DISPUTE_ROW)
      .mockResolvedValueOnce(EVALUATOR_STATS)
      .mockResolvedValueOnce(EVALUATOR_STATS);
    mockQuery.mockResolvedValue([]);

    await updateEvaluatorStats(DISPUTE_ID, "hirer");

    // The DB update for EVALUATOR_A should write newStreak=5 into param [2]
    const updateCallA = mockQuery.mock.calls.find(
      (call) => call[0].includes("UPDATE evaluators") && call[1][3] === EVALUATOR_A
    );
    expect(updateCallA![1][2]).toBe(5); // consecutive_accurate_votes = newStreak
  });

  it("does nothing when dispute is not found", async () => {
    mockQueryOne.mockResolvedValueOnce(null);
    await updateEvaluatorStats(DISPUTE_ID, "hirer");
    expect(mockQuery).not.toHaveBeenCalled();
  });

  it("increments slash_count by 1 for losing voter", async () => {
    setupForWinnerHirer();
    await updateEvaluatorStats(DISPUTE_ID, "hirer");

    // EVALUATOR_B (loser) — slash delta param is at index [1]
    const loserUpdate = mockQuery.mock.calls.find(
      (call) => call[0].includes("UPDATE evaluators") && call[1][3] === EVALUATOR_B
    );
    expect(loserUpdate![1][1]).toBe(1); // slash_count + 1
  });

  it("does NOT increment slash_count for winning voter", async () => {
    setupForWinnerHirer();
    await updateEvaluatorStats(DISPUTE_ID, "hirer");

    const winnerUpdate = mockQuery.mock.calls.find(
      (call) => call[0].includes("UPDATE evaluators") && call[1][3] === EVALUATOR_A
    );
    expect(winnerUpdate![1][1]).toBe(0); // slash_count + 0
  });
});

// ── finalizeSettlement ────────────────────────────────────────────────────────

describe("finalizeSettlement", () => {
  const TX_HASH = "ABCDEF1234567890";
  const OUTCOME = "release_to_hirer" as const;

  beforeEach(() => {
    // queryOne calls:
    //   1. SELECT job_id FROM disputes (to get job_id after UPDATE)
    //   2. SELECT hirer, worker, amount FROM jobs
    mockQueryOne
      .mockResolvedValueOnce({ job_id: JOB_ID })
      .mockResolvedValueOnce(JOB_ROW);

    // query calls:
    //   1. UPDATE disputes SET status='resolved'
    //   2. UPDATE jobs SET status='completed'
    //   3. INSERT reputation_events (both parties)
    mockQuery.mockResolvedValue([]);
  });

  it("updates dispute status to resolved", async () => {
    await finalizeSettlement(DISPUTE_ID, TX_HASH, OUTCOME);

    const disputeUpdate = mockQuery.mock.calls.find(
      (call) => call[0].includes("UPDATE disputes") && call[0].includes("resolved")
    );
    expect(disputeUpdate).toBeDefined();
    expect(disputeUpdate![1]).toContain(OUTCOME);
    expect(disputeUpdate![1]).toContain(TX_HASH);
    expect(disputeUpdate![1]).toContain(DISPUTE_ID);
  });

  it("updates job status to completed", async () => {
    await finalizeSettlement(DISPUTE_ID, TX_HASH, OUTCOME);

    const jobUpdate = mockQuery.mock.calls.find(
      (call) => call[0].includes("UPDATE jobs") && call[0].includes("completed")
    );
    expect(jobUpdate).toBeDefined();
    expect(jobUpdate![1]).toContain(JOB_ID);
  });

  it("records reputation events for both hirer and worker", async () => {
    await finalizeSettlement(DISPUTE_ID, TX_HASH, OUTCOME);

    const repEventInsert = mockQuery.mock.calls.find(
      (call) =>
        call[0].includes("INSERT INTO reputation_events") &&
        call[0].includes("dispute_resolved")
    );
    expect(repEventInsert).toBeDefined();
    // Both parties should appear in the params
    expect(repEventInsert![1]).toContain(HIRER);
    expect(repEventInsert![1]).toContain(WORKER);
  });

  it("returns early without error when dispute not found after UPDATE", async () => {
    mockQueryOne.mockReset();
    mockQueryOne.mockResolvedValueOnce(null); // dispute lookup returns null

    await expect(finalizeSettlement(DISPUTE_ID, TX_HASH, OUTCOME)).resolves.toBeUndefined();
  });
});
