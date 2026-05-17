"use strict";
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
Object.defineProperty(exports, "__esModule", { value: true });
exports.paywallSchema = paywallSchema;
exports.buildInvoice = buildInvoice;
exports.paywall = paywall;
exports.is402Response = is402Response;
exports.extract402Invoice = extract402Invoice;
const zod_1 = require("zod");
const verifier_1 = require("./verifier");
// ── paywallSchema ─────────────────────────────────────────────────────────────
/**
 * Extend any Zod raw shape with the optional `_relay_payment` field.
 *
 * MCP validates tool arguments against the declared schema; additional fields
 * are stripped. Call this wrapper around your schema to let the payment proof
 * pass through to the handler.
 *
 *   server.tool("name", paywallSchema({ foo: z.string() }), paywall(cfg, handler))
 */
function paywallSchema(schema) {
    return { ...schema, _relay_payment: zod_1.z.string().optional() };
}
// ── Challenge builder ─────────────────────────────────────────────────────────
function buildInvoice(config, endpointId) {
    return {
        version: "1.0",
        priceRlusd: config.priceRlusd,
        recipient: config.recipient,
        network: config.network,
        endpointId,
        expiresAt: Math.floor(Date.now() / 1000) + Math.floor((config.gracePeriodMs ?? 300_000) / 1000),
    };
}
function challengeResult(config, endpointId) {
    const challenge = {
        error: "PAYMENT_REQUIRED",
        code: 402,
        invoice: buildInvoice(config, endpointId),
    };
    return {
        content: [{ type: "text", text: JSON.stringify(challenge) }],
        isError: true,
    };
}
function rejectionResult(reason) {
    return {
        content: [{ type: "text", text: JSON.stringify({ error: "PAYMENT_INVALID", code: 402, reason }) }],
        isError: true,
    };
}
// ── paywall ───────────────────────────────────────────────────────────────────
/**
 * Wrap any MCP tool handler behind an x402 RLUSD paywall.
 *
 * Returns a handler function that:
 *   1. Returns a 402 challenge if `_relay_payment` is absent
 *   2. Verifies the proof (amount, recipient, anti-replay)
 *   3. Calls the real handler with `_relay_payment` stripped from params
 */
function paywall(config, handler) {
    const endpointId = `${config.recipient}:${config.priceRlusd}:${config.network}`;
    // Per-instance store: each paywall() call is isolated from every other.
    // For multi-replica deployments swap this for a Redis-backed store.
    const store = (0, verifier_1.createInMemoryReplayStore)();
    return async (params, extra) => {
        const { _relay_payment, ...toolParams } = params;
        if (!_relay_payment || typeof _relay_payment !== "string") {
            return challengeResult(config, endpointId);
        }
        const result = await (0, verifier_1.verifyPayment)(_relay_payment, config, store);
        if (!result.valid) {
            return rejectionResult(result.reason ?? "Payment verification failed");
        }
        return handler(toolParams, extra);
    };
}
// ── Type guard ────────────────────────────────────────────────────────────────
/** Detect whether a CallToolResult carries a Relay 402 challenge. */
function is402Response(result) {
    if (!result.isError)
        return false;
    try {
        const first = result.content[0];
        const text = (first?.type === "text" ? first.text : undefined) ?? "";
        const parsed = JSON.parse(text);
        return parsed.code === 402;
    }
    catch {
        return false;
    }
}
/** Extract the PaymentInvoice from a 402 CallToolResult. Returns null if not a 402. */
function extract402Invoice(result) {
    try {
        const first = result.content[0];
        const text = (first?.type === "text" ? first.text : undefined) ?? "";
        const parsed = JSON.parse(text);
        if (parsed.code === 402 && parsed.invoice)
            return parsed.invoice;
    }
    catch {
        // fall through
    }
    return null;
}
//# sourceMappingURL=paywall.js.map