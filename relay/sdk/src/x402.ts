/**
 * x402 protocol integration layer.
 *
 * x402 is the HTTP payment protocol: server responds 402 Payment Required,
 * client pays via X-PAYMENT header, server verifies and serves content.
 *
 * Relay extends x402 with:
 *   - Automatic escrow for high-value requests
 *   - Reputation gating (reject agents below threshold)
 *   - RLUSD/XRP payment channel support
 *   - Dispute resolution hooks
 *
 * This module provides the SDK-level types and helpers.
 * The Express middleware lives in relay/api/src/middleware/x402.ts.
 */

import { Network, Token, ReputationScore, ReputationTier } from "./types";
import { RLUSD_CURRENCY, RLUSD_ISSUERS, HTTP_PAYMENT_REQUIRED } from "./constants";

export interface X402Invoice {
  version: "1.0";
  scheme: "exact";
  network: string;
  asset: "XRP" | "RLUSD";
  amount: string;
  pay_to: string;
  memo_hex: string;
  endpoint_id: string;
  expires_at: number;
}

export interface X402PaymentHeader {
  scheme: "exact";
  network: string;
  payload: string; // base64-encoded signed XRPL transaction blob
}

export interface X402MiddlewareConfig {
  network: Network;
  acceptedTokens: Token[];
  escrowThresholdRlusd?: number;
  disputeResolution?: boolean;
  minReputationScore?: number;
  minReputationTier?: ReputationTier;
  relayApiUrl?: string;
  priceResolver?: (path: string, method: string) => number | null;
}

export interface X402RequestContext {
  payer?: string;
  paymentTxHash?: string;
  channelId?: string;
  amount?: string;
  reputationScore?: ReputationScore;
}

/**
 * Build a 402 Payment Required response body.
 * This is what the server sends when payment is needed.
 */
export function build402Response(
  network: Network,
  recipientAddress: string,
  amountRlusd: number,
  endpointId: string,
  token: Token = "RLUSD"
): { status: 402; body: X402Invoice } {
  const ttlSeconds = 300; // 5-minute payment window
  const memoData = Buffer.from(
    JSON.stringify({ endpoint: endpointId, ts: Date.now() })
  ).toString("hex");

  return {
    status: HTTP_PAYMENT_REQUIRED,
    body: {
      version: "1.0",
      scheme: "exact",
      network: network === "xrpl_mainnet" ? "xrpl-mainnet" : "xrpl-testnet",
      asset: token,
      amount: amountRlusd.toString(),
      pay_to: recipientAddress,
      memo_hex: memoData,
      endpoint_id: endpointId,
      expires_at: Math.floor(Date.now() / 1000) + ttlSeconds,
    },
  };
}

/**
 * Parse an X-PAYMENT header from an incoming request.
 */
export function parsePaymentHeader(headerValue: string): X402PaymentHeader | null {
  try {
    const decoded = JSON.parse(Buffer.from(headerValue, "base64").toString("utf8"));
    if (decoded.scheme && decoded.network && decoded.payload) {
      return decoded as X402PaymentHeader;
    }
    return null;
  } catch {
    return null;
  }
}

/**
 * Build an X-PAYMENT header value to include in a client request.
 * The payload is the base64-encoded signed XRPL transaction blob.
 */
export function buildPaymentHeader(
  network: Network,
  signedTxBlob: string
): string {
  const header: X402PaymentHeader = {
    scheme: "exact",
    network: network === "xrpl_mainnet" ? "xrpl-mainnet" : "xrpl-testnet",
    payload: signedTxBlob,
  };
  return Buffer.from(JSON.stringify(header)).toString("base64");
}

/**
 * Check if a reputation score meets the minimum threshold for a request.
 */
export function meetsReputationRequirement(
  score: ReputationScore,
  minScore?: number,
  minTier?: ReputationTier
): boolean {
  const tierOrder: ReputationTier[] = [
    "unverified",
    "bronze",
    "silver",
    "gold",
    "platinum",
  ];

  if (minScore !== undefined && score.score < minScore) return false;
  if (minTier !== undefined) {
    const required = tierOrder.indexOf(minTier);
    const current = tierOrder.indexOf(score.tier);
    if (current < required) return false;
  }
  return true;
}

/**
 * Determine if a payment amount warrants automatic escrow creation.
 */
export function shouldEscrow(
  amountRlusd: number,
  threshold?: number
): boolean {
  const defaultThreshold = 10; // 10 RLUSD
  return amountRlusd >= (threshold ?? defaultThreshold);
}
