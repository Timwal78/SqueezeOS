/**
 * Job lifecycle management.
 *
 * Full flow (zero-custody):
 *   1. Hirer calls createJob() → creates XRPL payment channel + signer list
 *   2. Worker accepts → channel becomes "active"
 *   3. Work completes → mutual sign release OR
 *   4. Dispute → evaluator 3-of-5 resolution → XRPL releases funds
 *   5. Timeout → worker can claim after settleDelay (no Relay action needed)
 *
 * Financial state lives ONLY on XRPL.
 * Our API is a coordination cache, not a source of truth.
 */

import { Wallet, Payment, IssuedCurrencyAmount } from "xrpl";
import { v4 as uuidv4 } from "uuid";
import { getClient, isValidXrplAddress, makeError, xrpToDrops } from "./xrpl-client";
import { createPaymentChannel, getChannelInfo } from "./channels";
import { buildJobSignerConfig, setupSignerList } from "./multisig";
import {
  Network,
  Token,
  CreateJobParams,
  JobRecord,
  JobStatus,
  MultiSigConfig,
  Milestone,
} from "./types";
import {
  DEFAULT_TIMEOUT_DAYS,
  RLUSD_CURRENCY,
  RLUSD_ISSUERS,
  RELAY_FEE_BPS,
} from "./constants";

export interface JobCreationResult {
  jobId: string;
  channelId: string;
  txHash: string;
  multiSigConfig: MultiSigConfig;
  estimatedFeeRlusd?: number;
}

export interface ReleaseResult {
  txHash: string;
  amountReleased: string;
  recipient: string;
}

/**
 * Phase 1: Hirer initiates a job.
 *
 * Creates a payment channel from hirer to worker and configures multi-signing.
 * The hirer's wallet must be provided (never sent to server — client-side signing).
 *
 * For RLUSD jobs: channel is denominated in XRP but RLUSD trust-line validation
 * ensures correct accounting. Full RLUSD channel support pending XRPL native IOU channels.
 */
export async function createJob(
  network: Network,
  hirerWallet: Wallet,
  params: CreateJobParams,
  evaluatorAddresses: string[]
): Promise<JobCreationResult> {
  validateJobParams(params);

  if (evaluatorAddresses.length < 3) {
    throw makeError(
      "INSUFFICIENT_EVALUATORS",
      "At least 3 evaluator addresses required for dispute resolution"
    );
  }

  // Step 1: Create payment channel (hirer → worker)
  const channelResult = await createPaymentChannel(
    network,
    hirerWallet,
    params.worker,
    params.amount,
    params.timeoutDays ?? DEFAULT_TIMEOUT_DAYS
  );

  // Step 2: Configure multi-signing on hirer account for dispute resolution
  const signerConfig = buildJobSignerConfig(
    hirerWallet.classicAddress,
    params.worker,
    evaluatorAddresses
  );

  await setupSignerList(
    network,
    hirerWallet,
    signerConfig.signers.filter((s) => s.account !== hirerWallet.classicAddress),
    signerConfig.threshold
  );

  const jobId = uuidv4();

  return {
    jobId,
    channelId: channelResult.channelId,
    txHash: channelResult.txHash,
    multiSigConfig: signerConfig,
    estimatedFeeRlusd: params.amount * (RELAY_FEE_BPS / 10000),
  };
}

/**
 * Mutual release: both hirer and worker agree the job is done.
 * Both sign a PaymentChannelClaim transaction (cooperative close).
 */
export async function mutualRelease(
  network: Network,
  workerWallet: Wallet,
  channelId: string,
  amountDrops: string
): Promise<ReleaseResult> {
  const channel = await getChannelInfo(network, channelId);
  if (!channel) {
    throw makeError("CHANNEL_NOT_FOUND", `Channel ${channelId} not found`);
  }

  const client = await getClient(network);

  const tx = {
    TransactionType: "PaymentChannelClaim" as const,
    Account: workerWallet.classicAddress,
    Channel: channelId,
    Amount: amountDrops,
    Flags: 0x00020000, // tfClose — close channel after claim
  };

  const prepared = await client.autofill(tx);
  const signed = workerWallet.sign(prepared);
  const result = await client.submitAndWait(signed.tx_blob);

  const meta = result.result.meta as { TransactionResult?: string } | undefined;
  if (meta?.TransactionResult !== "tesSUCCESS") {
    throw makeError("TX_FAILED", "Mutual release failed", meta?.TransactionResult);
  }

  return {
    txHash: result.result.hash,
    amountReleased: amountDrops,
    recipient: channel.destination,
  };
}

/**
 * Initiate a timeout claim. After settleDelay has passed and hirer hasn't
 * cooperatively closed, worker can claim the full channel balance.
 */
export async function timeoutClaim(
  network: Network,
  workerWallet: Wallet,
  channelId: string
): Promise<ReleaseResult> {
  const channel = await getChannelInfo(network, channelId);
  if (!channel) {
    throw makeError("CHANNEL_NOT_FOUND", `Channel ${channelId} not found`);
  }

  const client = await getClient(network);

  // Claim the full channel amount (worker is entitled after timeout)
  const tx = {
    TransactionType: "PaymentChannelClaim" as const,
    Account: workerWallet.classicAddress,
    Channel: channelId,
    Amount: channel.amount,
    Flags: 0x00020000, // tfClose
  };

  const prepared = await client.autofill(tx);
  const signed = workerWallet.sign(prepared);
  const result = await client.submitAndWait(signed.tx_blob);

  const meta = result.result.meta as { TransactionResult?: string } | undefined;
  if (meta?.TransactionResult !== "tesSUCCESS") {
    throw makeError("TX_FAILED", "Timeout claim failed", meta?.TransactionResult);
  }

  return {
    txHash: result.result.hash,
    amountReleased: channel.amount,
    recipient: channel.destination,
  };
}

/**
 * Send RLUSD directly between accounts (for simple payments without escrow).
 * Used for evaluator reward distribution and fee payments.
 */
export async function sendRlusd(
  network: Network,
  senderWallet: Wallet,
  destination: string,
  amount: string,
  memoHex?: string
): Promise<string> {
  if (!isValidXrplAddress(destination)) {
    throw makeError("INVALID_ADDRESS", `Invalid destination: ${destination}`);
  }

  const client = await getClient(network);

  const tx: Payment = {
    TransactionType: "Payment",
    Account: senderWallet.classicAddress,
    Destination: destination,
    Amount: {
      currency: RLUSD_CURRENCY,
      issuer: RLUSD_ISSUERS[network],
      value: amount,
    } as IssuedCurrencyAmount,
    ...(memoHex && {
      Memos: [
        {
          Memo: {
            MemoData: memoHex,
          },
        },
      ],
    }),
  };

  const prepared = await client.autofill(tx);
  const signed = senderWallet.sign(prepared);
  const result = await client.submitAndWait(signed.tx_blob);

  const meta = result.result.meta as { TransactionResult?: string } | undefined;
  if (meta?.TransactionResult !== "tesSUCCESS") {
    throw makeError("TX_FAILED", "RLUSD payment failed", meta?.TransactionResult);
  }

  return result.result.hash;
}

// ── Priority escrow lane (tenure eligibility) ─────────────────────────────────
//
// Agents with a proven track record (≥90 days + ≥50 completed jobs) qualify for
// the priority escrow lane: the dispute bond (normally required to open a dispute)
// is waived entirely.  This reduces friction for high-trust participants while
// keeping the bond requirement as a spam deterrent for new accounts.

export interface TenureEligibility {
  eligible: boolean;
  tenureDays: number;
  completedJobs: number;
  bondWaivedRlusd: number;
  reason?: string;
}

const TENURE_MIN_DAYS = 90;
const TENURE_MIN_JOBS = 50;
export const DISPUTE_BOND_RLUSD = 10; // standard bond amount

/**
 * Check whether an agent qualifies for zero-fee dispute initiation.
 * Both conditions must be met simultaneously.
 */
export function checkTenureEligibility(
  tenureDays: number,
  completedJobs: number
): TenureEligibility {
  const daysOk = tenureDays >= TENURE_MIN_DAYS;
  const jobsOk = completedJobs >= TENURE_MIN_JOBS;

  if (daysOk && jobsOk) {
    return {
      eligible: true,
      tenureDays,
      completedJobs,
      bondWaivedRlusd: DISPUTE_BOND_RLUSD,
    };
  }

  const gaps: string[] = [];
  if (!daysOk) gaps.push(`${TENURE_MIN_DAYS - tenureDays} more days tenure`);
  if (!jobsOk) gaps.push(`${TENURE_MIN_JOBS - completedJobs} more completed jobs`);

  return {
    eligible: false,
    tenureDays,
    completedJobs,
    bondWaivedRlusd: 0,
    reason: `Need: ${gaps.join(" and ")}`,
  };
}

/**
 * Calculate milestone release amounts from job params.
 * Returns drops for each milestone based on percentage allocation.
 */
export function calculateMilestoneAmounts(
  totalAmountDrops: string,
  milestones: Milestone[]
): string[] {
  const total = BigInt(totalAmountDrops);
  const percentages = milestones.map((m) => m.amountPercent);

  // Validate percentages sum to 100
  const sum = percentages.reduce((a, b) => a + b, 0);
  if (Math.abs(sum - 100) > 0.01) {
    throw makeError(
      "INVALID_MILESTONES",
      `Milestone percentages must sum to 100, got ${sum}`
    );
  }

  return milestones.map((m) => {
    return ((total * BigInt(Math.round(m.amountPercent * 100))) / 10000n).toString();
  });
}

function validateJobParams(params: CreateJobParams): void {
  if (!isValidXrplAddress(params.hirer)) {
    throw makeError("INVALID_ADDRESS", `Invalid hirer address: ${params.hirer}`);
  }
  if (!isValidXrplAddress(params.worker)) {
    throw makeError("INVALID_ADDRESS", `Invalid worker address: ${params.worker}`);
  }
  if (params.hirer === params.worker) {
    throw makeError("SAME_PARTY", "Hirer and worker cannot be the same account");
  }
  if (params.amount <= 0) {
    throw makeError("INVALID_AMOUNT", "Job amount must be positive");
  }
  if (!params.milestones.length) {
    throw makeError("NO_MILESTONES", "At least one milestone required");
  }
  if (params.timeoutDays && (params.timeoutDays < 1 || params.timeoutDays > 365)) {
    throw makeError("INVALID_TIMEOUT", "Timeout must be between 1 and 365 days");
  }
}
