/**
 * paywall() — server-side MCP tool wrapper.
 *
 * Usage:
 *   import { paywall, paywallSchema } from "@relayos/mcp-paywall";
 *   import { z } from "zod";
 *
 *   server.tool(
 *     "fetch-data",
 *     "Fetches proprietary data",
 *     paywallSchema({ query: z.string() }),
 *     paywall(
 *       { priceRlusd: 0.10, recipient: "rYourAddress", network: "xrpl_testnet" },
 *       async ({ query }) => ({ content: [{ type: "text", text: yourData(query) }] })
 *     )
 *   );
 *
 * When a tool call arrives without `_relay_payment`, the wrapper returns a
 * structured 402 challenge the agent wallet can parse and auto-pay.
 * After a valid payment proof is provided the real handler executes — with
 * `_relay_payment` stripped from params so the inner handler stays clean.
 */
import { z } from "zod";
import type { PaywallConfig, ToolHandler, CallToolResult, PaymentInvoice } from "./types";
/**
 * Extend any Zod raw shape with the optional `_relay_payment` field.
 *
 * MCP validates tool arguments against the declared schema; additional fields
 * are stripped. Call this wrapper around your schema to let the payment proof
 * pass through to the handler.
 *
 *   server.tool("name", paywallSchema({ foo: z.string() }), paywall(cfg, handler))
 */
export declare function paywallSchema<T extends z.ZodRawShape>(schema: T): T & {
    _relay_payment: z.ZodOptional<z.ZodString>;
};
export declare function buildInvoice(config: PaywallConfig, endpointId: string): PaymentInvoice;
/**
 * Wrap any MCP tool handler behind an x402 RLUSD paywall.
 *
 * Returns a handler function that:
 *   1. Returns a 402 challenge if `_relay_payment` is absent
 *   2. Verifies the proof (amount, recipient, anti-replay)
 *   3. Calls the real handler with `_relay_payment` stripped from params
 */
export declare function paywall<P extends Record<string, unknown>>(config: PaywallConfig, handler: ToolHandler<Omit<P, "_relay_payment">>): ToolHandler<P & {
    _relay_payment?: string;
}>;
/** Detect whether a CallToolResult carries a Relay 402 challenge. */
export declare function is402Response(result: CallToolResult): boolean;
/** Extract the PaymentInvoice from a 402 CallToolResult. Returns null if not a 402. */
export declare function extract402Invoice(result: CallToolResult): PaymentInvoice | null;
//# sourceMappingURL=paywall.d.ts.map