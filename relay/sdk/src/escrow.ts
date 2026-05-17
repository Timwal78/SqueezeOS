/**
 * XRPL native escrow for high-value jobs requiring time-lock or condition-based release.
 *
 * Unlike payment channels (streaming), escrow is for milestone-gated lump sums.
 * Relay never controls escrow — release requires cryptographic conditions or time expiry.
 *
 * Release patterns:
 *   Mutual release:  EscrowFinish signed by hirer+worker (fulfills condition)
 *   Time release:    Auto-finishable after finishAfter timestamp
 *   Dispute release: 3-of-5 evaluator multi-sig fulfills condition
 */

import {
  Wallet,
  EscrowCreate,
  EscrowFinish,
  EscrowCancel,
  convertStringToHex,
} from "xrpl";
import { getClient, isValidXrplAddress, makeError, xrpToDrops } from "./xrpl-client";
import { Network } from "./types";
import { RLUSD_CURRENCY, RLUSD_ISSUERS } from "./constants";

export interface EscrowCreateResult {
  escrowId: string;
  txHash: string;
  sequence: number;
  finishAfter?: number;
  cancelAfter?: number;
}

export interface EscrowInfo {
  escrowId: string;
  account: string;
  destination: string;
  amount: string;
  finishAfter?: number;
  cancelAfter?: number;
  condition?: string;
  sequence: number;
}

/**
 * Create a time-locked XRP escrow. The hirer's funds are locked until
 * finishAfter passes, at which point anyone can finish it (releases to worker).
 * cancelAfter allows hirer to reclaim if worker never finishes.
 *
 * For RLUSD escrow, use payment channels (XRPL native escrow only supports XRP).
 */
export async function createXrpEscrow(
  network: Network,
  hirerWallet: Wallet,
  workerAddress: string,
  amountXrp: number,
  finishAfterSeconds: number,
  cancelAfterSeconds?: number,
  condition?: string
): Promise<EscrowCreateResult> {
  if (!isValidXrplAddress(workerAddress)) {
    throw makeError("INVALID_ADDRESS", `Invalid worker address: ${workerAddress}`);
  }

  const client = await getClient(network);
  const now = Math.floor(Date.now() / 1000);
  // XRPL uses seconds since Ripple Epoch (Jan 1 2000), Unix adds 946684800
  const rippleEpochOffset = 946684800;
  const finishAfter = now + finishAfterSeconds - rippleEpochOffset;
  const cancelAfter = cancelAfterSeconds
    ? now + cancelAfterSeconds - rippleEpochOffset
    : undefined;

  const tx: EscrowCreate = {
    TransactionType: "EscrowCreate",
    Account: hirerWallet.classicAddress,
    Destination: workerAddress,
    Amount: xrpToDrops(amountXrp),
    FinishAfter: finishAfter,
    ...(cancelAfter && { CancelAfter: cancelAfter }),
    ...(condition && { Condition: condition }),
  };

  const prepared = await client.autofill(tx);
  const signed = hirerWallet.sign(prepared);
  const result = await client.submitAndWait(signed.tx_blob);

  const meta = result.result.meta as { TransactionResult?: string } | undefined;
  if (meta?.TransactionResult !== "tesSUCCESS") {
    throw makeError("TX_FAILED", "EscrowCreate failed", meta?.TransactionResult);
  }

  const sequence = (prepared as { Sequence?: number }).Sequence ?? 0;

  return {
    escrowId: `${hirerWallet.classicAddress}:${sequence}`,
    txHash: result.result.hash,
    sequence,
    finishAfter: finishAfter + rippleEpochOffset,
    cancelAfter: cancelAfter ? cancelAfter + rippleEpochOffset : undefined,
  };
}

/**
 * Finish an escrow (release funds to worker).
 * Can be called by anyone after finishAfter, or by authorized party if condition met.
 */
export async function finishEscrow(
  network: Network,
  callerWallet: Wallet,
  escrowOwner: string,
  escrowSequence: number,
  fulfillment?: string
): Promise<string> {
  const client = await getClient(network);

  const tx: EscrowFinish = {
    TransactionType: "EscrowFinish",
    Account: callerWallet.classicAddress,
    Owner: escrowOwner,
    OfferSequence: escrowSequence,
    ...(fulfillment && { Fulfillment: fulfillment }),
  };

  const prepared = await client.autofill(tx);
  const signed = callerWallet.sign(prepared);
  const result = await client.submitAndWait(signed.tx_blob);

  const meta = result.result.meta as { TransactionResult?: string } | undefined;
  if (meta?.TransactionResult !== "tesSUCCESS") {
    throw makeError("TX_FAILED", "EscrowFinish failed", meta?.TransactionResult);
  }

  return result.result.hash;
}

/**
 * Cancel an expired escrow (returns funds to hirer after cancelAfter).
 */
export async function cancelEscrow(
  network: Network,
  callerWallet: Wallet,
  escrowOwner: string,
  escrowSequence: number
): Promise<string> {
  const client = await getClient(network);

  const tx: EscrowCancel = {
    TransactionType: "EscrowCancel",
    Account: callerWallet.classicAddress,
    Owner: escrowOwner,
    OfferSequence: escrowSequence,
  };

  const prepared = await client.autofill(tx);
  const signed = callerWallet.sign(prepared);
  const result = await client.submitAndWait(signed.tx_blob);

  const meta = result.result.meta as { TransactionResult?: string } | undefined;
  if (meta?.TransactionResult !== "tesSUCCESS") {
    throw makeError("TX_FAILED", "EscrowCancel failed", meta?.TransactionResult);
  }

  return result.result.hash;
}

/**
 * Look up a specific escrow by owner and sequence.
 */
export async function getEscrowInfo(
  network: Network,
  owner: string,
  sequence: number
): Promise<EscrowInfo | null> {
  const client = await getClient(network);

  try {
    const response = await client.request({
      command: "ledger_entry",
      escrow: { owner, seq: sequence },
      ledger_index: "validated",
    });

    const node = (response.result as { node?: Record<string, unknown> }).node;
    if (!node) return null;

    return {
      escrowId: `${owner}:${sequence}`,
      account: node.Account as string,
      destination: node.Destination as string,
      amount: node.Amount as string,
      finishAfter: node.FinishAfter as number | undefined,
      cancelAfter: node.CancelAfter as number | undefined,
      condition: node.Condition as string | undefined,
      sequence,
    };
  } catch {
    return null;
  }
}

/**
 * Generate a SHA-256 PREIMAGE condition for escrow.
 * The preimage (secret) is shared only with parties allowed to release.
 * This enables cryptographic enforcement without Relay involvement.
 */
export function generateEscrowCondition(preimage: string): {
  condition: string;
  fulfillment: string;
} {
  const preimageHex = convertStringToHex(preimage);
  // In production: use crypto-conditions (RFC 9021) for proper PREIMAGE-SHA-256
  // For now: return hex-encoded values (proper implementation uses cc library)
  return {
    condition: `A0258020${Buffer.from(preimage).toString("hex").padEnd(64, "0")}810100`,
    fulfillment: `A0228020${preimageHex}`,
  };
}
