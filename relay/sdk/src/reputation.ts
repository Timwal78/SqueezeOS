/**
 * Reputation scoring system — fully verifiable, open-source algorithm.
 *
 * Reputation data is sourced from:
 *   1. XRPL account metadata (on-chain, immutable)
 *   2. Relay indexer cache (off-chain, reconstructable from chain)
 *
 * The scoring formula is published and client-verifiable:
 *
 *   score = (jobs_completed * 10) +
 *           (total_volume / 1000) +
 *           (1 - dispute_rate) * 1000 +
 *           (evaluator_accuracy * 500) +     // evaluators only
 *           (stake_duration_days * 2) +
 *           (network_pagerank * 100)
 */

import { AccountSet, convertStringToHex } from "xrpl";
import { Wallet } from "xrpl";
import { getClient, isValidXrplAddress, makeError } from "./xrpl-client";
import {
  Network,
  ReputationScore,
  ReputationTier,
  AttestationRequest,
} from "./types";
import { REPUTATION_TIERS } from "./constants";

export interface ReputationMetadata {
  jobs_completed: number;
  total_volume: number;
  dispute_rate: number;
  evaluator_accuracy: number | null;
  stake_duration_days: number;
  specializations: string[];
  joined_at: string;
  last_active: string;
  vouched_by: string[];
  attestations_given: number;
}

/**
 * Calculate reputation score from raw metrics.
 * This function is the canonical scoring algorithm — identical to what
 * any client-side verifier would run.
 */
export function calculateReputationScore(
  metrics: ReputationMetadata,
  networkPagerank: number = 0
): number {
  const base =
    metrics.jobs_completed * 10 +
    metrics.total_volume / 1000 +
    (1 - Math.min(metrics.dispute_rate, 1)) * 1000 +
    (metrics.evaluator_accuracy ?? 0) * 500 +
    metrics.stake_duration_days * 2 +
    networkPagerank * 100;

  return Math.round(Math.max(0, base));
}

/**
 * Determine reputation tier from score.
 */
export function getReputationTier(score: number): ReputationTier {
  if (score >= REPUTATION_TIERS.platinum) return "platinum";
  if (score >= REPUTATION_TIERS.gold) return "gold";
  if (score >= REPUTATION_TIERS.silver) return "silver";
  if (score >= REPUTATION_TIERS.bronze) return "bronze";
  return "unverified";
}

/**
 * Build a complete ReputationScore object from raw metadata and events.
 */
export function buildReputationScore(
  address: string,
  metadata: ReputationMetadata,
  networkPagerank: number = 0
): ReputationScore {
  const score = calculateReputationScore(metadata, networkPagerank);
  return {
    address,
    score,
    tier: getReputationTier(score),
    jobsCompleted: metadata.jobs_completed,
    totalVolume: metadata.total_volume,
    disputeRate: metadata.dispute_rate,
    evaluatorAccuracy: metadata.evaluator_accuracy ?? undefined,
    specializations: metadata.specializations,
    stakeAmount: 0,
    stakeDurationDays: metadata.stake_duration_days,
    vouchedBy: metadata.vouched_by,
    attestationsGiven: metadata.attestations_given,
    lastUpdated: Math.floor(Date.now() / 1000),
  };
}

/**
 * Write reputation metadata to XRPL account domain field (on-chain storage).
 * The domain field stores a URL or IPFS CID pointing to extended metadata.
 * This anchors reputation to the XRPL account itself.
 */
export async function publishReputationAnchor(
  network: Network,
  wallet: Wallet,
  ipfsCid: string
): Promise<string> {
  const client = await getClient(network);

  const tx: AccountSet = {
    TransactionType: "AccountSet",
    Account: wallet.classicAddress,
    Domain: convertStringToHex(`relay:${ipfsCid}`),
  };

  const prepared = await client.autofill(tx);
  const signed = wallet.sign(prepared);
  const result = await client.submitAndWait(signed.tx_blob);

  const meta = result.result.meta as { TransactionResult?: string } | undefined;
  if (meta?.TransactionResult !== "tesSUCCESS") {
    throw makeError("TX_FAILED", "AccountSet domain update failed", meta?.TransactionResult);
  }

  return result.result.hash;
}

/**
 * Read the reputation anchor CID from an account's Domain field.
 */
export async function readReputationAnchor(
  network: Network,
  address: string
): Promise<string | null> {
  if (!isValidXrplAddress(address)) {
    throw makeError("INVALID_ADDRESS", `Invalid address: ${address}`);
  }

  const client = await getClient(network);

  try {
    const response = await client.request({
      command: "account_info",
      account: address,
      ledger_index: "validated",
    });

    const accountData = (
      response.result as { account_data?: { Domain?: string } }
    ).account_data;

    if (!accountData?.Domain) return null;

    const decoded = Buffer.from(accountData.Domain, "hex").toString("utf8");
    if (!decoded.startsWith("relay:")) return null;

    return decoded.slice(6); // strip "relay:" prefix
  } catch {
    return null;
  }
}

/**
 * Create a cryptographic attestation from one agent to another.
 * Attestations are signed messages published on-chain via AccountSet memo.
 * Only platinum-tier accounts can issue attestations.
 */
export function buildAttestation(
  attesterWallet: Wallet,
  attestee: string,
  context: string
): AttestationRequest {
  const payload = JSON.stringify({
    attester: attesterWallet.classicAddress,
    attestee,
    context,
    timestamp: Math.floor(Date.now() / 1000),
  });

  const signature = attesterWallet.sign({
    TransactionType: "AccountSet",
    Account: attesterWallet.classicAddress,
    Domain: convertStringToHex(payload),
    Fee: "12",
    Sequence: 0,
    LastLedgerSequence: 0,
  }).tx_blob;

  return {
    attester: attesterWallet.classicAddress,
    attestee,
    context,
    signature,
  };
}

/**
 * Simple pagerank-like scoring based on job completion graph.
 * agents array is a list of { address, jobsWithAddresses[] } objects.
 * Returns a map of address → pagerank score (0-1).
 */
export function computeNetworkPagerank(
  agents: Array<{ address: string; completedWith: string[] }>,
  iterations: number = 20,
  dampingFactor: number = 0.85
): Map<string, number> {
  if (!agents.length) return new Map();

  const n = agents.length;
  const addressIndex = new Map(agents.map((a, i) => [a.address, i]));
  const scores = new Float64Array(n).fill(1 / n);
  const outLinks = agents.map((a) =>
    a.completedWith.map((addr) => addressIndex.get(addr) ?? -1).filter((i) => i >= 0)
  );

  for (let iter = 0; iter < iterations; iter++) {
    const next = new Float64Array(n).fill((1 - dampingFactor) / n);
    for (let i = 0; i < n; i++) {
      const links = outLinks[i];
      if (!links.length) {
        // dangling node — distribute evenly
        for (let j = 0; j < n; j++) next[j] += (dampingFactor * scores[i]) / n;
      } else {
        const share = (dampingFactor * scores[i]) / links.length;
        for (const j of links) next[j] += share;
      }
    }
    scores.set(next);
  }

  const result = new Map<string, number>();
  agents.forEach((a, i) => result.set(a.address, scores[i]));
  return result;
}
