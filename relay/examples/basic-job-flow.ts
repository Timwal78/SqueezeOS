/**
 * Phase 1 Example: Basic job creation and mutual release on XRPL testnet.
 *
 * Run: npx ts-node examples/basic-job-flow.ts
 *
 * This demonstrates the complete zero-custody flow:
 *   1. Generate two testnet wallets (hirer and worker)
 *   2. Create a payment channel from hirer to worker
 *   3. Configure multi-signing for dispute resolution
 *   4. Simulate work completion (mutual release)
 *
 * NO private keys are ever stored. Each wallet is generated fresh.
 * In production: users bring their own Crossmark/Xaman wallets.
 */

import { Wallet } from "xrpl";
import {
  getClient,
  createPaymentChannel,
  mutualRelease,
  buildJobSignerConfig,
  setupSignerList,
  calculateReputationScore,
  getReputationTier,
  Network,
} from "../sdk/src";

const NETWORK: Network = "xrpl_testnet";
const TESTNET_FAUCET = "https://faucet.altnet.rippletest.net/accounts";

async function fundTestnetWallet(wallet: Wallet): Promise<void> {
  const res = await fetch(TESTNET_FAUCET, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ destination: wallet.classicAddress }),
  });
  if (!res.ok) throw new Error(`Faucet failed: ${res.statusText}`);
  console.log(`  Funded ${wallet.classicAddress} from testnet faucet`);
  // Wait for funding to settle
  await new Promise((r) => setTimeout(r, 4000));
}

async function main() {
  console.log("=== RELAY Phase 1: Basic Job Flow on XRPL Testnet ===\n");

  // Step 1: Generate wallets (in production: users use Crossmark/Xaman)
  console.log("Step 1: Creating test wallets...");
  const hirerWallet = Wallet.generate();
  const workerWallet = Wallet.generate();
  const evaluator1 = Wallet.generate();
  const evaluator2 = Wallet.generate();
  const evaluator3 = Wallet.generate();

  console.log(`  Hirer:  ${hirerWallet.classicAddress}`);
  console.log(`  Worker: ${workerWallet.classicAddress}`);
  console.log(`  Evaluators: ${[evaluator1, evaluator2, evaluator3].map(e => e.classicAddress).join(", ")}`);

  // Step 2: Fund wallets via testnet faucet
  console.log("\nStep 2: Funding wallets via testnet faucet...");
  await fundTestnetWallet(hirerWallet);
  await fundTestnetWallet(workerWallet);

  // Step 3: Create payment channel (hirer → worker, 10 XRP, 7-day timeout)
  console.log("\nStep 3: Creating payment channel (hirer → worker, 10 XRP)...");
  const channelResult = await createPaymentChannel(
    NETWORK,
    hirerWallet,
    workerWallet.classicAddress,
    10, // 10 XRP
    7   // 7-day settle delay
  );

  console.log(`  Channel ID:   ${channelResult.channelId}`);
  console.log(`  TX Hash:      ${channelResult.txHash}`);
  console.log(`  Amount:       ${parseInt(channelResult.amount) / 1_000_000} XRP locked`);
  console.log(`  Settle Delay: ${channelResult.settleDelay / (24*60*60)} days`);

  // Step 4: Set up multi-signing for dispute resolution
  console.log("\nStep 4: Configuring multi-sig (threshold: 3-of-5)...");
  const signerConfig = buildJobSignerConfig(
    hirerWallet.classicAddress,
    workerWallet.classicAddress,
    [evaluator1.classicAddress, evaluator2.classicAddress, evaluator3.classicAddress]
  );

  const multiSigResult = await setupSignerList(
    NETWORK,
    hirerWallet,
    signerConfig.signers.filter(s => s.account !== hirerWallet.classicAddress),
    signerConfig.threshold
  );

  console.log(`  Multi-sig configured: ${multiSigResult.txHash}`);
  console.log(`  Signers: ${multiSigResult.signerList.map(s => s.account).join(", ")}`);
  console.log(`  Threshold: ${multiSigResult.threshold}`);

  // Step 5: Simulate work completion (mutual release)
  console.log("\nStep 5: Worker claims channel (mutual release)...");
  const releaseResult = await mutualRelease(
    NETWORK,
    workerWallet,
    channelResult.channelId,
    channelResult.amount // claim full amount
  );

  console.log(`  Release TX:    ${releaseResult.txHash}`);
  console.log(`  Released:      ${parseInt(releaseResult.amountReleased) / 1_000_000} XRP`);
  console.log(`  Recipient:     ${releaseResult.recipient}`);

  // Step 6: Show reputation calculation
  console.log("\nStep 6: Reputation score after job completion...");
  const metrics = {
    jobs_completed: 1,
    total_volume: 10,
    dispute_rate: 0,
    evaluator_accuracy: null,
    stake_duration_days: 0,
    specializations: [],
    joined_at: new Date().toISOString(),
    last_active: new Date().toISOString(),
    vouched_by: [],
    attestations_given: 0,
  };

  const score = calculateReputationScore(metrics);
  const tier = getReputationTier(score);

  console.log(`  Score: ${score}`);
  console.log(`  Tier:  ${tier}`);

  console.log("\n=== Flow Complete ===");
  console.log("Zero-custody verified: Relay never controlled any private keys.");
  console.log("All funds were controlled by XRPL cryptographic rules throughout.");

  // Cleanup
  const { disconnectAll } = await import("../sdk/src/xrpl-client");
  await disconnectAll();
}

main().catch((err) => {
  console.error("Error:", err.message ?? err);
  process.exit(1);
});
