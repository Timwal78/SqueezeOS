// End-to-end lifecycle: register -> submit -> oracle score -> reputation update
// -> settle paid read -> pull earnings. Also checks soulbound enforcement.
//
// NOTE: requires a Solidity compiler (blocked by the xDEO build sandbox egress).
// Run with `npx hardhat test` where binaries.soliditylang.org is reachable.

const { expect } = require("chai");
const { ethers } = require("hardhat");

const ORACLE_ROLE = ethers.id("ORACLE_ROLE");
const SETTLER_ROLE = ethers.id("SETTLER_ROLE");
const CORE_ROLE = ethers.id("CORE_ROLE");

describe("xDEOCore lifecycle", function () {
  let usdc, reputation, core, admin, analyst, reader;

  beforeEach(async function () {
    [admin, analyst, reader] = await ethers.getSigners();

    usdc = await (await ethers.getContractFactory("MockERC20")).deploy();
    reputation = await (await ethers.getContractFactory("xDEOReputation")).deploy(admin.address);
    core = await (await ethers.getContractFactory("xDEOCore")).deploy(
      await usdc.getAddress(),
      await reputation.getAddress(),
      admin.address
    );

    // Core must be allowed to mutate reputation; admin acts as oracle + settler.
    await reputation.grantRole(CORE_ROLE, await core.getAddress());
    await core.grantRole(ORACLE_ROLE, admin.address);
    await core.grantRole(SETTLER_ROLE, admin.address);
  });

  async function submit(predicted1e8, confWad) {
    const tx = await core
      .connect(analyst)
      .submitEstimate(ethers.encodeBytes32String("AAPL"), 2026, 0, predicted1e8, confWad);
    const rc = await tx.wait();
    const ev = rc.logs
      .map((l) => {
        try {
          return core.interface.parseLog(l);
        } catch {
          return null;
        }
      })
      .find((e) => e && e.name === "EstimateSubmitted");
    return ev.args.estimateId;
  }

  it("scores an accurate estimate and lifts reputation above zero", async function () {
    await core.connect(analyst).registerAnalyst(ethers.ZeroAddress);
    const id = await submit(605000000n, ethers.parseEther("0.9")); // $6.05, conf 0.9

    await core.scoreEstimate(id, 600000000n, 2592000n); // actual $6.00, 30d lead

    const [repWad, tier] = await core.reputationOf(analyst.address);
    expect(repWad > 0n).to.equal(true);
    expect(tier).to.be.a("bigint"); // enum -> bigint in ethers v6
  });

  it("settles a paid read and lets the analyst pull 95%", async function () {
    await core.connect(analyst).registerAnalyst(ethers.ZeroAddress);
    const id = await submit(600000000n, ethers.parseEther("0.8"));

    const amount = 500000n; // 0.5 USDC (6 decimals)
    await usdc.mint(await core.getAddress(), amount); // settlement funds the contract
    await core.settleRead(id, amount);

    const before = await usdc.balanceOf(analyst.address);
    await core.connect(analyst).claimEarnings();
    const after = await usdc.balanceOf(analyst.address);

    expect(after - before).to.equal((amount * 9500n) / 10000n); // 95%
  });

  it("credits a referrer 10% of the protocol fee, forever", async function () {
    // analyst registers with `reader` as referrer.
    await core.connect(reader).registerAnalyst(ethers.ZeroAddress);
    await core.connect(analyst).registerAnalyst(reader.address);
    const id = await submit(600000000n, ethers.parseEther("0.8"));

    const amount = 1000000n; // 1 USDC
    await usdc.mint(await core.getAddress(), amount);
    await core.settleRead(id, amount);

    // fee = 5% = 50000; referral = 10% of fee = 5000.
    const before = await usdc.balanceOf(reader.address);
    await core.connect(reader).claimEarnings();
    const after = await usdc.balanceOf(reader.address);
    expect(after - before).to.equal(5000n);
  });

  it("enforces soulbound badges (no transfer)", async function () {
    await core.connect(analyst).registerAnalyst(ethers.ZeroAddress);
    const tokenId = BigInt(analyst.address);
    await expect(
      reputation.connect(analyst).transferFrom(analyst.address, reader.address, tokenId)
    ).to.be.revertedWithCustomError(reputation, "Soulbound");
  });
});
