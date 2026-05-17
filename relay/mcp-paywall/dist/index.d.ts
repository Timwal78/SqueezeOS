/**
 * @relay/mcp-paywall — x402 RLUSD payment layer for Model Context Protocol.
 *
 * Server (earning wedge):
 *   import { paywall, paywallSchema } from "@relay/mcp-paywall";
 *
 * Client (spending wedge):
 *   import { agentWallet } from "@relay/mcp-paywall";
 */
export { paywall, paywallSchema, is402Response, extract402Invoice, buildInvoice } from "./paywall";
export { agentWallet } from "./agent-wallet";
export { verifyPayment, createInMemoryReplayStore } from "./verifier";
export type { PaywallConfig, AgentWalletConfig, PaymentInvoice, PaymentChallenge, PaymentProof, CallToolResult, ToolHandler, ToolContent, TextContent, ImageContent, VerificationResult, Network, } from "./types";
export type { AntiReplayStore } from "./verifier";
export type { AgentWallet, CallToolFn } from "./agent-wallet";
//# sourceMappingURL=index.d.ts.map