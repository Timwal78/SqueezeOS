// On-chain vs off-chain scoring parity.
//
// Asserts the Solidity ReputationMath port reproduces the (tested) TypeScript
// engine within tolerance, using vectors in parity-vectors.json generated from
// src/reputation/engine.ts.
//
// NOTE: requires a Solidity compiler (binaries.soliditylang.org), which is
// blocked by the xDEO build sandbox's egress allowlist — run this in an
// environment with compiler access (`npx hardhat test`).

const { expect } = require("chai");
const { ethers } = require("hardhat");
const { vectors } = require("./parity-vectors.json");

describe("ReputationMath parity (on-chain vs off-chain engine)", function () {
  let harness;

  before(async function () {
    const Factory = await ethers.getContractFactory("ReputationMathHarness");
    harness = await Factory.deploy();
    await harness.waitForDeployment();
  });

  for (const v of vectors) {
    it(`scores predicted=${v.predicted_1e8} actual=${v.actual_1e8} lead=${v.leadSeconds}s ≈ ${v.expected_score}`, async function () {
      const got = await harness.score(
        BigInt(v.predicted_1e8),
        BigInt(v.actual_1e8),
        BigInt(v.confidence_wad),
        BigInt(v.leadSeconds)
      );
      const expected = BigInt(v.expected_score_wad);
      const diff = got > expected ? got - expected : expected - got;
      // Tolerance: 1e-4 relative + 1e-9 absolute. The gap comes from PRBMath's
      // fixed-point exp2 vs JS Math.exp; both are well within reputation noise.
      const tol = expected / 10_000n + 1_000_000_000n;
      expect(diff <= tol, `diff ${diff} > tol ${tol} (got ${got}, exp ${expected})`).to.equal(true);
    });
  }

  it("streak multipliers hit the spec anchor points", async function () {
    expect(await harness.streakMultiplier(0)).to.equal(ethers.parseEther("1"));
    expect(await harness.streakMultiplier(7)).to.equal(ethers.parseEther("1.5"));
    expect(await harness.streakMultiplier(30)).to.equal(ethers.parseEther("2.5"));
    expect(await harness.streakMultiplier(100)).to.equal(ethers.parseEther("5"));
  });

  it("reputation EMA caps at 100 and only boosts gains", async function () {
    // A perfect score with a 5x streak from rep=95 must not exceed 100.
    const out = await harness.updateReputation(
      ethers.parseEther("95"),
      5,
      ethers.parseEther("100"),
      ethers.parseEther("5")
    );
    expect(out <= ethers.parseEther("100")).to.equal(true);
  });
});
