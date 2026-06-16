const { buildModule } = require("@nomicfoundation/hardhat-ignition/modules");

module.exports = buildModule("xDEOModule", (m) => {
  // Use deployer as the admin for setup
  const admin = m.getAccount(0);

  // In production, this would be the Base L2 USDC token address.
  // For this scaffold, we optionally deploy a Mock ERC20 if no address is provided.
  const usdcAddress = m.getParameter("usdcAddress", "0x0000000000000000000000000000000000000000");

  let usdc = usdcAddress;
  if (usdcAddress === "0x0000000000000000000000000000000000000000") {
     const mockUsdc = m.contract("MockERC20");
     usdc = mockUsdc;
  }

  const reputation = m.contract("xDEOReputation", [admin]);
  
  const core = m.contract("xDEOCore", [
    usdc,
    reputation,
    admin
  ]);

  // Set roles
  // We grant the CORE_ROLE on reputation to the xDEOCore contract.
  m.call(reputation, "grantRole", [
    "0x39a0673f88f1dc97034c56b744d0df965cd79d72dc2463e8a604cfb9cbcc1b50",
    core
  ], { id: "grantCoreRole" });

  // Grant ORACLE_ROLE and SETTLER_ROLE to admin (or dedicated addresses)
  m.call(core, "grantRole", [
    "0x1db3b15a6b738e4a83416b2b5ed7f02b37ba42a425313936087d1dfcde8dfcb3",
    admin
  ], { id: "grantOracleRole" });

  m.call(core, "grantRole", [
    "0x2cd586a111a4cf13251508db86551b9e0f6667d8f3702122b516b328a6f3b060",
    admin
  ], { id: "grantSettlerRole" });

  return { reputation, core };
});
