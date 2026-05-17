import {
  classifyTransaction,
  aggregateReputation,
  computeEventMerkleRoot,
  IndexerEvent,
} from "../indexer";

// ── classifyTransaction ──────────────────────────────────────────────────────

describe("classifyTransaction", () => {
  const base = {
    hash: "A".repeat(64),
    ledger_index: 1000,
    date: 0,
    Account: "rHirer123",
  };

  it("classifies PaymentChannelCreate", () => {
    const ev = classifyTransaction({ ...base, TransactionType: "PaymentChannelCreate", Destination: "rWorker456" });
    expect(ev?.type).toBe("channel_created");
    expect(ev?.account).toBe("rHirer123");
    expect(ev?.counterparty).toBe("rWorker456");
  });

  it("classifies PaymentChannelClaim without tfClose as channel_claimed", () => {
    const ev = classifyTransaction({ ...base, TransactionType: "PaymentChannelClaim", Flags: 0 });
    expect(ev?.type).toBe("channel_claimed");
  });

  it("classifies PaymentChannelClaim with tfClose as channel_closed", () => {
    const ev = classifyTransaction({ ...base, TransactionType: "PaymentChannelClaim", Flags: 0x00020000 });
    expect(ev?.type).toBe("channel_closed");
  });

  it("classifies EscrowCreate", () => {
    const ev = classifyTransaction({ ...base, TransactionType: "EscrowCreate" });
    expect(ev?.type).toBe("escrow_created");
  });

  it("classifies EscrowFinish", () => {
    const ev = classifyTransaction({ ...base, TransactionType: "EscrowFinish", Owner: "rOwner" });
    expect(ev?.type).toBe("escrow_finished");
    expect(ev?.counterparty).toBe("rOwner");
  });

  it("classifies SignerListSet", () => {
    const ev = classifyTransaction({ ...base, TransactionType: "SignerListSet" });
    expect(ev?.type).toBe("signer_list_set");
  });

  it("classifies relay AccountSet as attestation", () => {
    const relayPrefix = Buffer.from("relay:").toString("hex");
    const ev = classifyTransaction({
      ...base,
      TransactionType: "AccountSet",
      Domain: relayPrefix + "Qm123",
    });
    expect(ev?.type).toBe("attestation");
  });

  it("returns null for unknown tx types", () => {
    expect(classifyTransaction({ ...base, TransactionType: "OfferCreate" })).toBeNull();
    expect(classifyTransaction({ ...base })).toBeNull();
  });

  it("extracts XRP amount from string Amount", () => {
    const ev = classifyTransaction({
      ...base,
      TransactionType: "PaymentChannelCreate",
      Amount: "1000000",
    });
    expect(ev?.amount).toBe("1000000");
  });

  it("extracts RLUSD value from object Amount", () => {
    const ev = classifyTransaction({
      ...base,
      TransactionType: "PaymentChannelCreate",
      Amount: { currency: "USD", issuer: "rIssuer", value: "5.00" },
    });
    expect(ev?.amount).toBe("5.00");
  });
});

// ── aggregateReputation ──────────────────────────────────────────────────────

describe("aggregateReputation", () => {
  const workerAddr = "rWorker000";

  const makeEvent = (type: IndexerEvent["type"], overrides: Partial<IndexerEvent> = {}): IndexerEvent => ({
    type,
    txHash: Math.random().toString(16).slice(2).padEnd(64, "0"),
    ledgerIndex: 1000,
    timestamp: Math.floor(Date.now() / 1000),
    account: "rHirer000",
    counterparty: workerAddr,
    raw: {},
    ...overrides,
  });

  it("counts channel_closed events as completed jobs", () => {
    const events = [
      makeEvent("channel_closed", { counterparty: workerAddr }),
      makeEvent("channel_closed", { counterparty: workerAddr }),
    ];
    const meta = aggregateReputation(workerAddr, events);
    expect(meta.jobs_completed).toBe(2);
  });

  it("calculates dispute rate from escrow_finished events", () => {
    const events = [
      makeEvent("channel_closed", { counterparty: workerAddr }),
      makeEvent("channel_closed", { counterparty: workerAddr }),
      makeEvent("escrow_finished", { account: workerAddr, counterparty: undefined }),
    ];
    const meta = aggregateReputation(workerAddr, events);
    expect(meta.dispute_rate).toBeCloseTo(0.5, 1);
  });

  it("returns zero dispute rate with no jobs", () => {
    const meta = aggregateReputation(workerAddr, []);
    expect(meta.dispute_rate).toBe(0);
    expect(meta.jobs_completed).toBe(0);
  });

  it("counts attestations given", () => {
    const events = [
      makeEvent("attestation", { account: workerAddr }),
      makeEvent("attestation", { account: workerAddr }),
    ];
    const meta = aggregateReputation(workerAddr, events);
    expect(meta.attestations_given).toBe(2);
  });
});

// ── computeEventMerkleRoot ───────────────────────────────────────────────────

describe("computeEventMerkleRoot", () => {
  const makeEv = (hash: string): IndexerEvent => ({
    type: "channel_created",
    txHash: hash,
    ledgerIndex: 1,
    timestamp: 0,
    account: "rTest",
    raw: {},
  });

  it("returns deterministic root for same events", () => {
    const events = [makeEv("AAAA"), makeEv("BBBB")];
    expect(computeEventMerkleRoot(events)).toBe(computeEventMerkleRoot(events));
  });

  it("root differs for different events", () => {
    const a = computeEventMerkleRoot([makeEv("AAAA")]);
    const b = computeEventMerkleRoot([makeEv("BBBB")]);
    expect(a).not.toBe(b);
  });

  it("root is order-independent (sorted)", () => {
    const a = computeEventMerkleRoot([makeEv("AAAA"), makeEv("BBBB")]);
    const b = computeEventMerkleRoot([makeEv("BBBB"), makeEv("AAAA")]);
    expect(a).toBe(b);
  });

  it("empty events returns zero root", () => {
    expect(computeEventMerkleRoot([])).toBe("0".repeat(64));
  });
});
