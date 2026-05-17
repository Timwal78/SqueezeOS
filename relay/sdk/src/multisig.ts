/**
 * XRPL Multi-signing for dispute resolution.
 *
 * Multi-sig setup: hirer (weight 1) + worker (weight 1) + evaluators (weight 1 each)
 * Thresholds:
 *   Cooperative release: hirer + worker (2 total weight ≥ 2)
 *   Dispute resolution:  3 evaluators (3 total weight ≥ 3)
 *
 * Relay is NEVER a signer. We only coordinate evaluator selection and
 * provide the unsigned transaction for parties to sign independently.
 */

import {
  Wallet,
  SignerListSet,
  multisign,
} from "xrpl";
import { getClient, isValidXrplAddress, makeError } from "./xrpl-client";
import { Network, MultiSigConfig } from "./types";
import {
  DEFAULT_DISPUTE_THRESHOLD,
  DEFAULT_EVALUATOR_COUNT,
} from "./constants";

export interface SignerEntry {
  account: string;
  weight: number;
}

export interface MultiSigSetupResult {
  txHash: string;
  signerList: SignerEntry[];
  threshold: number;
}

export interface PartialSignature {
  signer: string;
  txBlob: string;
}

/**
 * Configure multi-signing on an account.
 * Call this on BOTH the hirer and worker accounts as part of job setup.
 *
 * Standard Relay setup:
 *   - Hirer: weight 1
 *   - Worker: weight 1
 *   - Each evaluator: weight 1
 *   - quorum: 3 (any 3 of N signers can authorize)
 */
export async function setupSignerList(
  network: Network,
  accountWallet: Wallet,
  signers: SignerEntry[],
  quorum: number
): Promise<MultiSigSetupResult> {
  if (signers.length < 1) {
    throw makeError("INVALID_SIGNERS", "At least 1 signer required");
  }
  if (quorum < 1 || quorum > signers.reduce((s, e) => s + e.weight, 0)) {
    throw makeError("INVALID_QUORUM", "Quorum must be between 1 and total weight");
  }

  for (const signer of signers) {
    if (!isValidXrplAddress(signer.account)) {
      throw makeError("INVALID_ADDRESS", `Invalid signer address: ${signer.account}`);
    }
    if (signer.account === accountWallet.classicAddress) {
      throw makeError("INVALID_SIGNER", "Account cannot be its own signer");
    }
  }

  const client = await getClient(network);

  const tx: SignerListSet = {
    TransactionType: "SignerListSet",
    Account: accountWallet.classicAddress,
    SignerQuorum: quorum,
    SignerEntries: signers.map((s) => ({
      SignerEntry: {
        Account: s.account,
        SignerWeight: s.weight,
      },
    })),
  };

  const prepared = await client.autofill(tx);
  const signed = accountWallet.sign(prepared);
  const result = await client.submitAndWait(signed.tx_blob);

  const meta = result.result.meta as { TransactionResult?: string } | undefined;
  if (meta?.TransactionResult !== "tesSUCCESS") {
    throw makeError("TX_FAILED", "SignerListSet failed", meta?.TransactionResult);
  }

  return {
    txHash: result.result.hash,
    signerList: signers,
    threshold: quorum,
  };
}

/**
 * Remove the signer list from an account (restore single-key control).
 * Called after a job completes to clean up multi-sig setup.
 */
export async function clearSignerList(
  network: Network,
  accountWallet: Wallet
): Promise<string> {
  const client = await getClient(network);

  const tx: SignerListSet = {
    TransactionType: "SignerListSet",
    Account: accountWallet.classicAddress,
    SignerQuorum: 0,
  };

  const prepared = await client.autofill(tx);
  const signed = accountWallet.sign(prepared);
  const result = await client.submitAndWait(signed.tx_blob);

  const meta = result.result.meta as { TransactionResult?: string } | undefined;
  if (meta?.TransactionResult !== "tesSUCCESS") {
    throw makeError("TX_FAILED", "SignerListSet clear failed", meta?.TransactionResult);
  }

  return result.result.hash;
}

/**
 * Build a multi-sig transaction that requires N-of-M signatures.
 * Returns an unsigned transaction blob each party must sign independently.
 * The signed blobs are then combined and submitted.
 */
export async function buildMultiSigTx(
  network: Network,
  txTemplate: Record<string, unknown>
): Promise<string> {
  const client = await getClient(network);
  const prepared = await client.autofill(txTemplate as Parameters<typeof client.autofill>[0]);
  // Multi-sig transactions need Sequence but NOT a SigningPubKey for the account
  (prepared as Record<string, unknown>)["SigningPubKey"] = "";
  return JSON.stringify(prepared);
}

/**
 * Sign a multi-sig transaction as one of the authorized signers.
 * Each party calls this independently and returns their partial signature.
 */
export function signMultiSigTx(
  signerWallet: Wallet,
  unsignedTxJson: string
): PartialSignature {
  const tx = JSON.parse(unsignedTxJson);
  const signed = signerWallet.sign(tx, true); // true = sign for multi-signing (encodes signer address)
  return {
    signer: signerWallet.classicAddress,
    txBlob: signed.tx_blob,
  };
}

/**
 * Combine partial multi-sig signatures and submit when threshold is met.
 * This is called by whoever collects enough signatures (could be evaluator coordinator).
 */
export async function submitMultiSig(
  network: Network,
  partialSignatures: PartialSignature[]
): Promise<string> {
  if (partialSignatures.length === 0) {
    throw makeError("NO_SIGNATURES", "At least one signature required");
  }

  const client = await getClient(network);

  // Combine all partial signatures
  const combined = multisign(partialSignatures.map((p) => p.txBlob));
  const result = await client.submitAndWait(combined);

  const meta = result.result.meta as { TransactionResult?: string } | undefined;
  if (meta?.TransactionResult !== "tesSUCCESS") {
    throw makeError("TX_FAILED", "Multi-sig submission failed", meta?.TransactionResult);
  }

  return result.result.hash;
}

/**
 * Get the current signer list for an account.
 */
export async function getSignerList(
  network: Network,
  account: string
): Promise<{ signers: SignerEntry[]; threshold: number } | null> {
  const client = await getClient(network);

  try {
    const response = await client.request({
      command: "account_objects",
      account,
      type: "signer_list",
      ledger_index: "validated",
    });

    const objects = (
      response.result as unknown as { account_objects?: Array<Record<string, unknown>> }
    ).account_objects;

    if (!objects?.length) return null;

    const list = objects[0];
    const entries = (list.SignerEntries as Array<{
      SignerEntry: { Account: string; SignerWeight: number };
    }>).map((e) => ({
      account: e.SignerEntry.Account,
      weight: e.SignerEntry.SignerWeight,
    }));

    return {
      signers: entries,
      threshold: list.SignerQuorum as number,
    };
  } catch {
    return null;
  }
}

/**
 * Build the standard Relay multi-sig config for a job.
 * Hirer and worker each get weight 1; evaluators each get weight 1.
 * Threshold 3 means: either cooperative (hirer+worker+1 evaluator)
 * or pure evaluator resolution (3 evaluators).
 */
export function buildJobSignerConfig(
  hirerAddress: string,
  workerAddress: string,
  evaluatorAddresses: string[]
): MultiSigConfig {
  return {
    threshold: DEFAULT_DISPUTE_THRESHOLD,
    signers: [
      { account: hirerAddress, weight: 1 },
      { account: workerAddress, weight: 1 },
      ...evaluatorAddresses.map((addr) => ({ account: addr, weight: 1 })),
    ],
  };
}
