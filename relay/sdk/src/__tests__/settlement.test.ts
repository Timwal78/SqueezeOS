import {
  calculateSettlementAmounts,
} from "../settlement";

describe("calculateSettlementAmounts", () => {
  it("release_to_worker gives all funds to worker", () => {
    const { toHirer, toWorker } = calculateSettlementAmounts(
      "1000000",
      "release_to_worker"
    );
    expect(toHirer).toBe("0");
    expect(toWorker).toBe("1000000");
  });

  it("release_to_hirer gives all funds to hirer", () => {
    const { toHirer, toWorker } = calculateSettlementAmounts(
      "1000000",
      "release_to_hirer"
    );
    expect(toHirer).toBe("1000000");
    expect(toWorker).toBe("0");
  });

  it("partial defaults to 50/50 split", () => {
    const { toHirer, toWorker } = calculateSettlementAmounts("1000000", "partial");
    expect(toHirer).toBe("500000");
    expect(toWorker).toBe("500000");
  });

  it("partial with custom worker amount", () => {
    const { toHirer, toWorker } = calculateSettlementAmounts(
      "1000000",
      "partial",
      "700000"
    );
    expect(toWorker).toBe("700000");
    expect(toHirer).toBe("300000");
  });

  it("amounts sum to total", () => {
    const total = "999999";
    const { toHirer, toWorker } = calculateSettlementAmounts(total, "partial");
    expect(BigInt(toHirer) + BigInt(toWorker)).toBe(BigInt(total));
  });
});
