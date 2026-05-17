import { Wallet } from "xrpl";
import type { Transaction } from "xrpl";
import { verifyPayment, createInMemoryReplayStore } from "../src/verifier";
import type { PaywallConfig } from "../src/types";

// ── Fixtures ──────────────────────────────────────────────────────────────────

const TESTNET_RLUSD_ISSUER = "rMxCKbEDwqr76QuheSUMdEGf4B9xJ8m5De";
const recipientWallet = Wallet.generate();
const payerWallet = Wallet.generate();

const config: PaywallConfig = {
  priceRlusd: 0.10,
  recipient: recipientWallet.classicAddress,
  network: "xrpl_testnet",
};

function buildProof(
  amount: unknown,
  destination = config.recipient,
  txType = "Payment"
): string {
  const tx: Record<string, unknown> = {
    TransactionType: txType,
    Account: payerWallet.classicAddress,
    Destination: destination,
    Amount: amount,
    Fee: "12",
    Sequence: 1,
    LastLedgerSequence: 9_999_999,
  };
  const { tx_blob } = payerWallet.sign(tx as unknown as Transaction);
  const envelope = {
    scheme: "exact",
    network: "xrpl-testnet",
    payload: tx_blob,
  };
  return Buffer.from(JSON.stringify(envelope)).toString("base64");
}

const validRlusdAmount = { currency: "USD", issuer: TESTNET_RLUSD_ISSUER, value: "0.10" };

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("verifyPayment — valid proofs", () => {
  it("accepts a correctly-formed RLUSD Payment proof", async () => {
    const proof = buildProof(validRlusdAmount);
    const r = await verifyPayment(proof, config, createInMemoryReplayStore());
    expect(r.valid).toBe(true);
  });

  it("accepts overpayment (value > priceRlusd)", async () => {
    const proof = buildProof({ currency: "USD", issuer: TESTNET_RLUSD_ISSUER, value: "1.00" });
    const r = await verifyPayment(proof, config, createInMemoryReplayStore());
    expect(r.valid).toBe(true);
  });

  it("accepts exact price boundary", async () => {
    const proof = buildProof({ currency: "USD", issuer: TESTNET_RLUSD_ISSUER, value: "0.10" });
    const r = await verifyPayment(proof, config, createInMemoryReplayStore());
    expect(r.valid).toBe(true);
  });
});

describe("verifyPayment — invalid proofs", () => {
  it("rejects malformed base64 envelope", async () => {
    const r = await verifyPayment("not-base64-json!!!", config, createInMemoryReplayStore());
    expect(r.valid).toBe(false);
    expect(r.reason).toMatch(/Malformed/);
  });

  it("rejects missing payload", async () => {
    const envelope = Buffer.from(JSON.stringify({ scheme: "exact" })).toString("base64");
    const r = await verifyPayment(envelope, config, createInMemoryReplayStore());
    expect(r.valid).toBe(false);
    expect(r.reason).toMatch(/Missing tx payload/);
  });

  it("rejects non-Payment tx type", async () => {
    const proof = buildProof(validRlusdAmount, config.recipient, "AccountSet");
    const r = await verifyPayment(proof, config, createInMemoryReplayStore());
    expect(r.valid).toBe(false);
    expect(r.reason).toMatch(/Payment tx/);
  });

  it("rejects wrong recipient", async () => {
    const otherWallet = Wallet.generate();
    const proof = buildProof(validRlusdAmount, otherWallet.classicAddress);
    const r = await verifyPayment(proof, config, createInMemoryReplayStore());
    expect(r.valid).toBe(false);
    expect(r.reason).toMatch(/Wrong recipient/);
  });

  it("rejects underpayment", async () => {
    const proof = buildProof({ currency: "USD", issuer: TESTNET_RLUSD_ISSUER, value: "0.05" });
    const r = await verifyPayment(proof, config, createInMemoryReplayStore());
    expect(r.valid).toBe(false);
    expect(r.reason).toMatch(/Underpayment/);
  });

  it("rejects wrong RLUSD currency", async () => {
    const proof = buildProof({ currency: "EUR", issuer: TESTNET_RLUSD_ISSUER, value: "0.10" });
    const r = await verifyPayment(proof, config, createInMemoryReplayStore());
    expect(r.valid).toBe(false);
    expect(r.reason).toMatch(/USD currency/);
  });
});

describe("verifyPayment — anti-replay", () => {
  it("rejects the same proof used twice", async () => {
    const proof = buildProof(validRlusdAmount);
    const store = createInMemoryReplayStore();
    const r1 = await verifyPayment(proof, config, store);
    const r2 = await verifyPayment(proof, config, store);
    expect(r1.valid).toBe(true);
    expect(r2.valid).toBe(false);
    expect(r2.reason).toMatch(/replay/i);
  });

  it("accepts different proofs on the same store (different signers)", async () => {
    const store = createInMemoryReplayStore();
    const payer2 = Wallet.generate();
    const tx2 = {
      TransactionType: "Payment" as const,
      Account: payer2.classicAddress,
      Destination: config.recipient,
      Amount: validRlusdAmount,
      Fee: "12",
      Sequence: 2,
      LastLedgerSequence: 9_999_999,
    };
    const proof1 = buildProof(validRlusdAmount);
    const env2 = { scheme: "exact", network: "xrpl-testnet", payload: payer2.sign(tx2).tx_blob };
    const proof2 = Buffer.from(JSON.stringify(env2)).toString("base64");

    const r1 = await verifyPayment(proof1, config, store);
    const r2 = await verifyPayment(proof2, config, store);
    expect(r1.valid).toBe(true);
    expect(r2.valid).toBe(true);
  });

  it("each call gets an independent store by default", async () => {
    const proof = buildProof(validRlusdAmount);
    // Two independent stores — both accept the same proof
    const r1 = await verifyPayment(proof, config, createInMemoryReplayStore());
    const r2 = await verifyPayment(proof, config, createInMemoryReplayStore());
    expect(r1.valid).toBe(true);
    expect(r2.valid).toBe(true);
  });
});

describe("createInMemoryReplayStore", () => {
  it("has() returns false for unknown key", () => {
    const store = createInMemoryReplayStore();
    expect(store.has("unknown")).toBe(false);
  });

  it("has() returns true immediately after set()", () => {
    const store = createInMemoryReplayStore();
    store.set("key1", Date.now() + 60_000);
    expect(store.has("key1")).toBe(true);
  });

  it("has() returns false for expired entry", () => {
    const store = createInMemoryReplayStore();
    store.set("key2", Date.now() - 1); // already expired
    expect(store.has("key2")).toBe(false);
  });

  it("sweep() removes expired entries", () => {
    const store = createInMemoryReplayStore();
    store.set("expire-soon", Date.now() - 1);
    store.set("live-key", Date.now() + 60_000);
    store.sweep();
    expect(store.has("live-key")).toBe(true);
    // expire-soon is gone after sweep
    expect(store.has("expire-soon")).toBe(false);
  });
});
