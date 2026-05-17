/**
 * On-chain dispute settlement via XRPL multi-sig.
 *
 * When evaluators reach threshold (3-of-5), this module:
 *   1. Builds the settlement PaymentChannelClaim transaction
 *   2. Collects evaluator multi-sig partial signatures
 *   3. Submits the combined multi-sig tx to XRPL
 *   4. Distributes evaluator rewards and applies slashing
 *
 * Zero-custody invariants maintained throughout:
 *   - Settlement tx routes funds directly to winner (hirer or worker)
 *   - Relay constructs but never signs the settlement tx
 *   - Evaluator signatures are submitted by evaluators themselves
 *   - Slashing is enforced via pre-signed escrow cancel conditions
 */

import { Wallet, multisign } from "xrpl";
import { getClient, makeError, xrpToDrops } from "./xrpl-client";
import {
  buildMultiSigTx,
  signMultiSigTx,
  submitMultiSig,
  PartialSignature,
} from "./multisig";
import { sendRlusd } from "./jobs";
import {
  resolveVotes,
  calculateEvaluatorOutcomes,
} from "./evaluators";
import {
  Network,
  DisputeVote,
  DisputeOutcome,
} from "./types";
import { RLUSD_CURRENCY, RLUSD_ISSUERS, DEFAULT_DISPUTE_THRESHOLD } from "./constants";

export interface SettlementParams {
  channelId: string;
  hirerAddress: string;
  workerAddress: string;
  totalAmountDrops: string;
  outcome: DisputeOutcome;
  partialAmountDrops?: string; // for 'partial' outcome
}

export interface SettlementResult {
  txHash: string;
  outcome: DisputeOutcome;
  amountToHirer: string;
  amountToWorker: string;
}

export interface RewardDistribution {
  evaluatorAddress: string;
  earnedRlusd: number;
  slashedRlusd: number;
  txHash?: string;
}

/**
 * Build the unsigned settlement transaction based on dispute outcome.
 * Returns unsigned tx JSON for evaluators to sign.
 *
 * The settlement tx is a PaymentChannelClaim that closes the channel
 * and routes the balance to the correct party.
 */
export async function buildSettlementTx(
  network: Network,
  params: SettlementParams
): Promise<string> {
  const client = await getClient(network);

  // Determine how much to claim for worker based on outcome
  let claimAmount: string;

  if (params.outcome === "release_to_worker") {
    claimAmount = params.totalAmountDrops;
  } else if (params.outcome === "release_to_hirer") {
    // Claim 0 — channel closes, remaining balance returns to hirer
    claimAmount = "0";
  } else {
    // Partial: split 50/50 by default, or use specified partialAmountDrops
    claimAmount = params.partialAmountDrops ??
      (BigInt(params.totalAmountDrops) / 2n).toString();
  }

  // PaymentChannelClaim with tfClose returns unclaimed balance to hirer
  const txTemplate = {
    TransactionType: "PaymentChannelClaim",
    Account: params.workerAddress,
    Channel: params.channelId,
    Amount: claimAmount,
    Flags: 0x00020000, // tfClose
  };

  return buildMultiSigTx(network, txTemplate);
}

/**
 * Evaluator signs the settlement transaction.
 * Each evaluator calls this independently with their own wallet.
 */
export function signSettlement(
  evaluatorWallet: Wallet,
  unsignedTxJson: string
): PartialSignature {
  return signMultiSigTx(evaluatorWallet, unsignedTxJson);
}

/**
 * Submit the multi-sig settlement transaction once threshold is reached.
 * Combines partial signatures and submits to XRPL.
 */
export async function executeSettlement(
  network: Network,
  partialSignatures: PartialSignature[]
): Promise<string> {
  if (partialSignatures.length < DEFAULT_DISPUTE_THRESHOLD) {
    throw makeError(
      "INSUFFICIENT_SIGNATURES",
      `Need ${DEFAULT_DISPUTE_THRESHOLD} signatures, got ${partialSignatures.length}`
    );
  }
  return submitMultiSig(network, partialSignatures);
}

/**
 * Distribute evaluator rewards after settlement.
 * Relay's fee wallet pays rewards from the pre-collected evaluator fee.
 * Slashing is handled separately via evaluator escrow cancellation.
 */
export async function distributeEvaluatorRewards(
  network: Network,
  feeWallet: Wallet,
  votes: DisputeVote[],
  outcome: "hirer" | "worker" | "partial",
  jobAmountRlusd: number,
  evaluatorStakes: Map<string, number>
): Promise<RewardDistribution[]> {
  const outcomes = calculateEvaluatorOutcomes(
    votes,
    outcome,
    jobAmountRlusd,
    evaluatorStakes
  );

  const distributions: RewardDistribution[] = [];

  for (const [address, result] of outcomes.entries()) {
    if (result.earned > 0) {
      try {
        const txHash = await sendRlusd(
          network,
          feeWallet,
          address,
          result.earned.toFixed(6),
          Buffer.from(`relay:reward:${address}`).toString("hex")
        );
        distributions.push({
          evaluatorAddress: address,
          earnedRlusd: result.earned,
          slashedRlusd: result.slashed,
          txHash,
        });
      } catch (err) {
        distributions.push({
          evaluatorAddress: address,
          earnedRlusd: result.earned,
          slashedRlusd: result.slashed,
          // txHash omitted — reward failed, will retry
        });
      }
    } else {
      distributions.push({
        evaluatorAddress: address,
        earnedRlusd: 0,
        slashedRlusd: result.slashed,
      });
    }
  }

  return distributions;
}

/**
 * Use XRPL validated ledger hash as VRF seed for evaluator selection.
 * The ledger hash is public, verifiable, and unpredictable before closure.
 */
export async function getLedgerVrfSeed(network: Network): Promise<string> {
  const client = await getClient(network);
  const response = await client.request({
    command: "ledger",
    ledger_index: "validated",
  });
  const ledger = (response.result as { ledger?: { ledger_hash?: string } }).ledger;
  if (!ledger?.ledger_hash) {
    throw makeError("VRF_UNAVAILABLE", "Could not fetch validated ledger hash");
  }
  return ledger.ledger_hash;
}

/**
 * Calculate settlement amounts from outcome.
 * Returns { toHirer, toWorker } in drops.
 */
export function calculateSettlementAmounts(
  totalDrops: string,
  outcome: DisputeOutcome,
  partialWorkerDrops?: string
): { toHirer: string; toWorker: string } {
  const total = BigInt(totalDrops);

  if (outcome === "release_to_worker") {
    return { toHirer: "0", toWorker: totalDrops };
  }
  if (outcome === "release_to_hirer") {
    return { toHirer: totalDrops, toWorker: "0" };
  }
  // partial
  const toWorker = BigInt(partialWorkerDrops ?? (total / 2n).toString());
  const toHirer = (total - toWorker).toString();
  return { toHirer, toWorker: toWorker.toString() };
}
