/**
 * Cryptographic vote verification for evaluator dispute resolution.
 *
 * Evaluators sign a canonical vote payload with their XRPL private key.
 * The server verifies signatures before accepting votes — no impersonation possible.
 *
 * Vote payload (canonical JSON, deterministic key order):
 *   { disputeId, jobId, vote, evidenceCids, evaluator, timestamp }
 *
 * Verification uses XRPL's native verifySignature — same crypto as on-chain txs.
 */

import { verifyKeypairSignature, Wallet, decode, encodeForSigning } from "xrpl";
import { DisputeVote } from "./types";
import { makeError } from "./xrpl-client";

export interface VotePayload {
  disputeId: string;
  jobId: string;
  vote: "hirer" | "worker" | "partial";
  evidenceCids: string[];
  evaluator: string;
  timestamp: number;
}

export interface SignedVote {
  payload: VotePayload;
  signature: string;
  publicKey: string;
}

/**
 * Build the canonical vote message that evaluators sign.
 * Key order is deterministic to ensure identical bytes across implementations.
 */
export function buildVoteMessage(payload: VotePayload): string {
  const canonical = {
    disputeId: payload.disputeId,
    evidenceCids: [...payload.evidenceCids].sort(), // sort for determinism
    evaluator: payload.evaluator,
    jobId: payload.jobId,
    timestamp: payload.timestamp,
    vote: payload.vote,
  };
  return Buffer.from(JSON.stringify(canonical)).toString("hex");
}

/**
 * Sign a vote payload with an evaluator's XRPL keypair.
 * The evaluator calls this locally — private key never leaves their device.
 */
export function signVote(wallet: Wallet, payload: VotePayload): SignedVote {
  const messageHex = buildVoteMessage(payload);
  const signature = wallet.sign({
    TransactionType: "AccountSet",
    Account: wallet.classicAddress,
    Domain: messageHex,
    Fee: "12",
    Sequence: 0,
    LastLedgerSequence: 0,
  }).tx_blob;

  return {
    payload,
    signature,
    publicKey: wallet.publicKey,
  };
}

/**
 * Verify an evaluator's vote signature.
 * Returns true if the signature was produced by the claimed evaluator address.
 */
export function verifyVoteSignature(signedVote: SignedVote): boolean {
  try {
    // Decode the signed tx blob to get TxnSignature and embedded Domain
    const decoded = decode(signedVote.signature) as Record<string, unknown>;
    const txnSignature = decoded.TxnSignature as string | undefined;
    if (!txnSignature) return false;

    // Verify the Domain field matches the canonical vote message
    // This ensures the tx was signed for THIS payload, not some other payload
    const expectedDomain = buildVoteMessage(signedVote.payload);
    const actualDomain = decoded.Domain as string | undefined;
    if (!actualDomain || actualDomain.toLowerCase() !== expectedDomain.toLowerCase()) {
      return false;
    }

    // Verify the XRPL transaction signature itself
    const msg = encodeForSigning(decoded as Parameters<typeof encodeForSigning>[0]);
    return verifyKeypairSignature(msg, txnSignature, signedVote.publicKey);
  } catch {
    return false;
  }
}

/**
 * Verify that the public key corresponds to the claimed evaluator address.
 * Guards against submitting a valid signature for a different account.
 */
export function verifyEvaluatorIdentity(
  publicKey: string,
  claimedAddress: string
): boolean {
  try {
    const { deriveAddress } = require("xrpl");
    const derived = deriveAddress(publicKey);
    return derived === claimedAddress;
  } catch {
    return false;
  }
}

/**
 * Full vote validation: verify signature AND identity in one call.
 * Throws with specific error codes on failure.
 */
export function validateVote(
  signedVote: SignedVote,
  expectedDisputeId: string,
  expectedJobId: string
): void {
  if (signedVote.payload.disputeId !== expectedDisputeId) {
    throw makeError("VOTE_DISPUTE_MISMATCH", "Vote dispute ID does not match");
  }
  if (signedVote.payload.jobId !== expectedJobId) {
    throw makeError("VOTE_JOB_MISMATCH", "Vote job ID does not match");
  }
  if (!verifyEvaluatorIdentity(signedVote.publicKey, signedVote.payload.evaluator)) {
    throw makeError(
      "IDENTITY_MISMATCH",
      "Public key does not correspond to evaluator address"
    );
  }
  if (!verifyVoteSignature(signedVote)) {
    throw makeError("INVALID_SIGNATURE", "Vote signature verification failed");
  }
  // Reject votes with timestamps more than 24h old or in the future
  const now = Math.floor(Date.now() / 1000);
  const age = now - signedVote.payload.timestamp;
  if (age > 86400 || age < -300) {
    throw makeError("VOTE_EXPIRED", `Vote timestamp out of acceptable range: age=${age}s`);
  }
}

/**
 * Convert a SignedVote to the DisputeVote shape used throughout the system.
 */
export function toDisputeVote(signedVote: SignedVote): DisputeVote {
  return {
    evaluator: signedVote.payload.evaluator,
    vote: signedVote.payload.vote,
    signature: signedVote.signature,
    timestamp: signedVote.payload.timestamp,
  };
}
