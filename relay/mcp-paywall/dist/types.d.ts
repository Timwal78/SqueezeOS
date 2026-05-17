/**
 * Shared types for @relay/mcp-paywall.
 * Self-contained — no imports from relay/sdk to keep the package standalone.
 */
export type Network = "xrpl_mainnet" | "xrpl_testnet";
export interface PaymentInvoice {
    /** Version tag for future protocol upgrades. */
    version: "1.0";
    priceRlusd: number;
    recipient: string;
    network: Network;
    /** Unique per tool registration — prevents cross-tool replays. */
    endpointId: string;
    /** Unix timestamp. Client must pay before this. */
    expiresAt: number;
}
export interface PaymentChallenge {
    error: "PAYMENT_REQUIRED";
    code: 402;
    invoice: PaymentInvoice;
}
/** Base64-encoded JSON: { scheme, network, payload: signed_tx_blob } */
export type PaymentProof = string;
export interface PaywallConfig {
    /** Price in RLUSD for one tool call. */
    priceRlusd: number;
    /** XRPL address that receives payment. */
    recipient: string;
    network: Network;
    description?: string;
    /** If set, server submits the tx to XRPL for settlement confirmation. */
    relayApiUrl?: string;
    /** Payment window in ms. Default: 300_000 (5 min). */
    gracePeriodMs?: number;
}
export interface AgentWalletConfig {
    /** XRPL wallet seed. Held in memory only — NEVER logged or transmitted. */
    seed: string;
    network: Network;
    /** Maximum price per tool call the agent will auto-pay without human approval. */
    maxSpendPerCallRlusd: number;
    /** Relay API base URL for reputation checks before paying. */
    relayApiUrl?: string;
    /** Reject servers whose reputation score is below this threshold. */
    minServerReputationScore?: number;
    /**
     * Inject a custom signer for testing.
     * Production code omits this — real XRPL signing is used.
     */
    _signPayment?: (invoice: PaymentInvoice) => Promise<string>;
}
export interface TextContent {
    type: "text";
    text: string;
}
export interface ImageContent {
    type: "image";
    data: string;
    mimeType: string;
}
export type ToolContent = TextContent | ImageContent;
export interface CallToolResult {
    content: ToolContent[];
    isError?: boolean;
}
export type ToolHandler<P extends Record<string, unknown> = Record<string, unknown>> = (params: P, extra?: unknown) => CallToolResult | Promise<CallToolResult>;
export interface VerificationResult {
    valid: boolean;
    reason?: string;
}
//# sourceMappingURL=types.d.ts.map