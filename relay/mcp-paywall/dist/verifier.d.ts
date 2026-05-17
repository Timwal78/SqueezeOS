/**
 * Payment proof verification.
 *
 * The proof is a base64-encoded JSON envelope:
 *   { scheme: "exact", network: string, payload: "<signed_xrpl_tx_blob>" }
 *
 * Verification steps:
 *   1. Decode the envelope
 *   2. Decode the XRPL tx blob (xrpl.decode)
 *   3. Verify TransactionType === "Payment"
 *   4. Verify Destination === config.recipient
 *   5. Verify Amount >= config.priceRlusd (RLUSD IOU or XRP)
 *   6. Anti-replay: reject if this tx_blob was used in the last gracePeriodMs
 *
 * Anti-replay is in-process (Map with TTL). For multi-instance deployments
 * replace with a shared Redis SET — the `_antiReplay` export is injectable.
 */
import type { PaywallConfig, VerificationResult } from "./types";
export interface AntiReplayStore {
    has(key: string): boolean;
    set(key: string, expiresAt: number): void;
    sweep(): void;
}
export declare function createInMemoryReplayStore(): AntiReplayStore;
export declare function verifyPayment(proofBase64: string, config: PaywallConfig, store?: AntiReplayStore): Promise<VerificationResult>;
//# sourceMappingURL=verifier.d.ts.map