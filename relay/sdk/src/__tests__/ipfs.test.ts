import {
  buildEvidencePackage,
  EvidencePackage,
} from "../ipfs";

describe("buildEvidencePackage", () => {
  it("creates a well-formed evidence package", () => {
    const pkg = buildEvidencePackage(
      "dispute-001",
      "job-001",
      "rHirer123",
      "Worker did not complete the agreed scope.",
      [{ name: "screenshot.png", contentType: "image/png", description: "UI screenshot", dataBase64: "abc" }]
    );

    expect(pkg.disputeId).toBe("dispute-001");
    expect(pkg.jobId).toBe("job-001");
    expect(pkg.submitter).toBe("rHirer123");
    expect(pkg.statement).toBeTruthy();
    expect(pkg.files).toHaveLength(1);
    expect(pkg.timestamp).toBeGreaterThan(0);
    expect(pkg.timestamp).toBeLessThanOrEqual(Math.floor(Date.now() / 1000) + 1);
  });

  it("creates package with no files", () => {
    const pkg = buildEvidencePackage("d", "j", "rAddr", "statement");
    expect(pkg.files).toEqual([]);
  });
});
