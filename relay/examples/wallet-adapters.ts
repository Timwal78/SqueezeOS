/**
 * Phase 3 Example: Wallet adapter patterns for different agent contexts.
 *
 * Shows how the same SDK works across:
 *   1. AgentWalletAdapter  — autonomous AI agent (programmatic, no human in loop)
 *   2. CrossmarkAdapter    — human developer reviewing agent transactions (browser)
 *   3. XamanAdapter        — mobile approval for high-value production signing
 *
 * Run: npx ts-node examples/wallet-adapters.ts
 */

import { Wallet } from "xrpl";
import {
  AgentWalletAdapter,
  CrossmarkAdapter,
  XamanAdapter,
  detectAdapterType,
  WalletAdapter,
  Network,
  createPaymentChannel,
  signVote,
  VotePayload,
} from "../sdk/src";

const NETWORK: Network = "xrpl_testnet";

// ── Shared signing logic — works with ANY adapter ────────────────────────────

async function createJobChannel(
  adapter: WalletAdapter,
  workerAddress: string,
  amountXrp: number
): Promise<string> {
  console.log(`\n  [${adapter.type.toUpperCase()}] Creating channel from ${adapter.address.slice(0, 8)}...`);
  console.log(`  Adapter type: ${adapter.type} | Connected: ${adapter.isConnected()}`);

  // In a real flow: get client, autofill tx, then use adapter.sign()
  // Here we just demo the signing interface without hitting testnet
  const mockTx = {
    TransactionType: "PaymentChannelCreate",
    Account: adapter.address,
    Destination: workerAddress,
    Amount: (amountXrp * 1_000_000).toString(),
    SettleDelay: 7 * 24 * 60 * 60,
    PublicKey: adapter.publicKey,
    Fee: "12",
    Sequence: 1,
    LastLedgerSequence: 100000,
  };

  const { txBlob, txHash } = await adapter.sign(mockTx);
  console.log(`  Signed TX hash: ${txHash.slice(0, 16)}...`);
  return txHash;
}

async function castEvaluatorVote(
  adapter: WalletAdapter,
  disputeId: string,
  jobId: string,
  vote: "hirer" | "worker"
): Promise<void> {
  const payload: VotePayload = {
    disputeId,
    jobId,
    vote,
    evidenceCids: [],
    evaluator: adapter.address,
    timestamp: Math.floor(Date.now() / 1000),
  };

  const messageHex = Buffer.from(JSON.stringify(payload)).toString("hex");
  const signature = await adapter.signMessage(messageHex);
  console.log(`  [${adapter.type}] Vote "${vote}" signed: ${signature.slice(0, 16)}...`);
}

// ── Demo ─────────────────────────────────────────────────────────────────────

async function main() {
  console.log("=== RELAY Phase 3: Wallet Adapter Architecture ===\n");

  // ── 1. Agent Wallet (primary mode for AI agents) ──────────────────────────
  console.log("1. AGENT WALLET ADAPTER (AI autonomous signing)");
  console.log("   No UI. No prompts. Signs instantly. Used by autonomous agents.");

  const agentWallet = Wallet.generate();
  const workerWallet = Wallet.generate();
  const agentAdapter = new AgentWalletAdapter(agentWallet);

  await createJobChannel(agentAdapter, workerWallet.classicAddress, 25);
  await castEvaluatorVote(agentAdapter, "dispute-001", "job-001", "worker");

  // ── 2. Crossmark Adapter (mock — no browser in Node) ─────────────────────
  console.log("\n2. CROSSMARK ADAPTER (desktop browser extension)");
  console.log("   Requires user click in Crossmark popup. Best for developer oversight.");

  const mockCrossmark = {
    signIn: async () => ({
      response: { data: { address: Wallet.generate().classicAddress, publicKey: agentWallet.publicKey } },
    }),
    signAndSubmit: async (tx: Record<string, unknown>) => ({
      response: {
        data: {
          resp: {
            txBlob: agentWallet.sign(tx as Parameters<typeof agentWallet.sign>[0]).tx_blob,
            txHash: agentWallet.sign(tx as Parameters<typeof agentWallet.sign>[0]).hash,
          },
        },
      },
    }),
    isConnected: () => true,
  };

  const crossmarkAdapter = new CrossmarkAdapter(mockCrossmark);
  await crossmarkAdapter.connect();
  console.log(`  Connected: ${crossmarkAdapter.address.slice(0, 8)}...`);
  await createJobChannel(crossmarkAdapter, workerWallet.classicAddress, 50);

  // ── 3. Xaman / environment-aware detection ────────────────────────────────
  console.log("\n3. ENVIRONMENT-AWARE ADAPTER DETECTION");
  const detected = detectAdapterType();
  console.log(`  Detected environment: ${detected}`);
  console.log(`  In Node.js/server: 'agent' (programmatic)`);
  console.log(`  In browser with Crossmark: 'crossmark'`);
  console.log(`  In browser with Xaman: 'xaman'`);
  console.log(`  Production pattern: detect → instantiate → same SDK calls`);

  // ── 4. Indexer reconstruction demo ────────────────────────────────────────
  console.log("\n4. REPUTATION INDEXER — Reconstruction demo");
  const { RelayIndexer, classifyTransaction, aggregateReputation } = await import("../sdk/src/indexer");

  // Simulate some on-chain events
  const mockEvents = [
    {
      TransactionType: "PaymentChannelCreate",
      hash: "A".repeat(64),
      ledger_index: 1000,
      date: 0,
      Account: "rHirer",
      Destination: agentWallet.classicAddress,
      Amount: "10000000",
    },
    {
      TransactionType: "PaymentChannelClaim",
      hash: "B".repeat(64),
      ledger_index: 1050,
      date: 3600,
      Account: "rHirer",
      Flags: 0x00020000, // tfClose — job completed
      counterparty: agentWallet.classicAddress,
      Destination: agentWallet.classicAddress,
      Amount: "10000000",
    },
    {
      TransactionType: "PaymentChannelClaim",
      hash: "C".repeat(64),
      ledger_index: 1100,
      date: 7200,
      Account: "rHirer2",
      Flags: 0x00020000,
      Destination: agentWallet.classicAddress,
      Amount: "5000000",
    },
  ];

  const classified = mockEvents.map(classifyTransaction).filter(Boolean);
  // For channel_closed, counterparty is destination (the worker/agent)
  const eventsForAgent = classified.map(ev => ({
    ...ev!,
    counterparty: agentWallet.classicAddress,
  }));

  const reputation = aggregateReputation(agentWallet.classicAddress, eventsForAgent);
  console.log(`\n  Reconstructed reputation for ${agentWallet.classicAddress.slice(0, 8)}...:`);
  console.log(`  Jobs completed: ${reputation.jobs_completed}`);
  console.log(`  Total volume:   ${reputation.total_volume} XRP`);
  console.log(`  Dispute rate:   ${(reputation.dispute_rate * 100).toFixed(1)}%`);
  console.log(`  (Computed from ${classified.length} on-chain events — zero Relay trust needed)`);

  // ── 5. Wallet selection guidance ─────────────────────────────────────────
  console.log("\n5. WALLET SELECTION GUIDE");
  console.log(`
  Context                          → Adapter
  ─────────────────────────────────────────────
  AI agent (autonomous)            → AgentWalletAdapter (keypair in secure env)
  Developer testing flows          → AgentWalletAdapter (Wallet.generate())
  Human operator, desktop          → CrossmarkAdapter (browser extension)
  Human operator, mobile           → XamanAdapter (push + QR approval)
  High-value tx, audit trail       → XamanAdapter (mobile confirmation)
  Evaluator voting (any context)   → AgentWalletAdapter (fast, cryptographic)
  Production agent with HSM        → AgentWalletAdapter (fromSeed from KMS)
  `);

  console.log("=== Phase 3 complete ===");
  console.log("All adapters share the same WalletAdapter interface.");
  console.log("Zero-custody: private keys never leave the adapter.");

  const { disconnectAll } = await import("../sdk/src/xrpl-client");
  await disconnectAll();
}

main().catch((err) => {
  console.error("Error:", err.message ?? err);
  process.exit(1);
});
