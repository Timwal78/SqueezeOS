import { Wallet } from "xrpl";
import {
  buildVoteMessage,
  signVote,
  verifyVoteSignature,
  verifyEvaluatorIdentity,
  validateVote,
  toDisputeVote,
  VotePayload,
} from "../voting";

// Generate a real wallet for cryptographic tests
const wallet = Wallet.generate();

const basePayload: VotePayload = {
  disputeId: "dispute-test-001",
  jobId: "job-test-001",
  vote: "worker",
  evidenceCids: ["QmTest1", "QmTest2"],
  evaluator: wallet.classicAddress,
  timestamp: Math.floor(Date.now() / 1000),
};

describe("buildVoteMessage", () => {
  it("produces deterministic hex output", () => {
    const msg1 = buildVoteMessage(basePayload);
    const msg2 = buildVoteMessage(basePayload);
    expect(msg1).toBe(msg2);
    expect(msg1).toMatch(/^[0-9a-f]+$/);
  });

  it("sorts evidenceCids for canonical form", () => {
    const p1: VotePayload = { ...basePayload, evidenceCids: ["QmB", "QmA"] };
    const p2: VotePayload = { ...basePayload, evidenceCids: ["QmA", "QmB"] };
    expect(buildVoteMessage(p1)).toBe(buildVoteMessage(p2));
  });

  it("produces different output for different votes", () => {
    const worker = buildVoteMessage({ ...basePayload, vote: "worker" });
    const hirer = buildVoteMessage({ ...basePayload, vote: "hirer" });
    expect(worker).not.toBe(hirer);
  });
});

describe("signVote / verifyVoteSignature", () => {
  it("signed vote verifies successfully", () => {
    const signed = signVote(wallet, basePayload);
    expect(verifyVoteSignature(signed)).toBe(true);
  });

  it("tampered payload fails verification", () => {
    const signed = signVote(wallet, basePayload);
    const tampered = {
      ...signed,
      payload: { ...signed.payload, vote: "hirer" as const },
    };
    expect(verifyVoteSignature(tampered)).toBe(false);
  });

  it("wrong public key fails verification", () => {
    const signed = signVote(wallet, basePayload);
    const otherWallet = Wallet.generate();
    const withWrongKey = { ...signed, publicKey: otherWallet.publicKey };
    expect(verifyVoteSignature(withWrongKey)).toBe(false);
  });
});

describe("verifyEvaluatorIdentity", () => {
  it("returns true for matching address", () => {
    expect(verifyEvaluatorIdentity(wallet.publicKey, wallet.classicAddress)).toBe(true);
  });

  it("returns false for mismatched address", () => {
    const other = Wallet.generate();
    expect(verifyEvaluatorIdentity(wallet.publicKey, other.classicAddress)).toBe(false);
  });
});

describe("validateVote", () => {
  it("passes for valid signed vote", () => {
    const signed = signVote(wallet, basePayload);
    expect(() =>
      validateVote(signed, basePayload.disputeId, basePayload.jobId)
    ).not.toThrow();
  });

  it("throws VOTE_DISPUTE_MISMATCH for wrong disputeId", () => {
    const signed = signVote(wallet, basePayload);
    expect(() =>
      validateVote(signed, "wrong-dispute-id", basePayload.jobId)
    ).toThrow(/dispute ID does not match/);
  });

  it("throws VOTE_JOB_MISMATCH for wrong jobId", () => {
    const signed = signVote(wallet, basePayload);
    expect(() =>
      validateVote(signed, basePayload.disputeId, "wrong-job-id")
    ).toThrow(/job ID does not match/);
  });

  it("throws VOTE_EXPIRED for stale timestamp", () => {
    const stalePayload: VotePayload = {
      ...basePayload,
      timestamp: Math.floor(Date.now() / 1000) - 90000, // 25h ago
    };
    const staleWallet = Wallet.generate();
    const stalePayloadWithAddress: VotePayload = {
      ...stalePayload,
      evaluator: staleWallet.classicAddress,
    };
    const signed = signVote(staleWallet, stalePayloadWithAddress);
    expect(() =>
      validateVote(signed, stalePayloadWithAddress.disputeId, stalePayloadWithAddress.jobId)
    ).toThrow(/timestamp out of acceptable range/);
  });
});

describe("toDisputeVote", () => {
  it("maps signed vote to dispute vote format", () => {
    const signed = signVote(wallet, basePayload);
    const dv = toDisputeVote(signed);
    expect(dv.evaluator).toBe(basePayload.evaluator);
    expect(dv.vote).toBe(basePayload.vote);
    expect(dv.signature).toBe(signed.signature);
    expect(dv.timestamp).toBe(basePayload.timestamp);
  });
});
