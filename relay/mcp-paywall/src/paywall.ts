/**
 * paywall() — server-side MCP tool wrapper.
 *
 * Usage:
 *   import { paywall, paywallSchema } from "@relay/mcp-paywall";
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
import { verifyPayment, createInMemoryReplayStore } from "./verifier";
import type {
  PaywallConfig,
  ToolHandler,
  CallToolResult,
  PaymentChallenge,
  PaymentInvoice,
} from "./types";

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
export function paywallSchema<T extends z.ZodRawShape>(
  schema: T
): T & { _relay_payment: z.ZodOptional<z.ZodString> } {
  return { ...schema, _relay_payment: z.string().optional() };
}

// ── Challenge builder ─────────────────────────────────────────────────────────

export function buildInvoice(config: PaywallConfig, endpointId: string): PaymentInvoice {
  return {
    version: "1.0",
    priceRlusd: config.priceRlusd,
    recipient: config.recipient,
    network: config.network,
    endpointId,
    expiresAt: Math.floor(Date.now() / 1000) + Math.floor((config.gracePeriodMs ?? 300_000) / 1000),
  };
}

function challengeResult(config: PaywallConfig, endpointId: string): CallToolResult {
  const challenge: PaymentChallenge = {
    error: "PAYMENT_REQUIRED",
    code: 402,
    invoice: buildInvoice(config, endpointId),
  };
  return {
    content: [{ type: "text", text: JSON.stringify(challenge) }],
    isError: true,
  };
}

function rejectionResult(reason: string): CallToolResult {
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
export function paywall<P extends Record<string, unknown>>(
  config: PaywallConfig,
  handler: ToolHandler<Omit<P, "_relay_payment">>
): ToolHandler<P & { _relay_payment?: string }> {
  const endpointId = `${config.recipient}:${config.priceRlusd}:${config.network}`;
  // Per-instance store: each paywall() call is isolated from every other.
  // For multi-replica deployments swap this for a Redis-backed store.
  const store = createInMemoryReplayStore();

  return async (params, extra): Promise<CallToolResult> => {
    const { _relay_payment, ...toolParams } = params;

    if (!_relay_payment || typeof _relay_payment !== "string") {
      return challengeResult(config, endpointId);
    }

    const result = await verifyPayment(_relay_payment, config, store);
    if (!result.valid) {
      return rejectionResult(result.reason ?? "Payment verification failed");
    }

    return handler(toolParams as Omit<P, "_relay_payment">, extra);
  };
}

// ── Type guard ────────────────────────────────────────────────────────────────

/** Detect whether a CallToolResult carries a Relay 402 challenge. */
export function is402Response(result: CallToolResult): boolean {
  if (!result.isError) return false;
  try {
    const first = result.content[0];
    const text = (first?.type === "text" ? first.text : undefined) ?? "";
    const parsed = JSON.parse(text) as { code?: number };
    return parsed.code === 402;
  } catch {
    return false;
  }
}

/** Extract the PaymentInvoice from a 402 CallToolResult. Returns null if not a 402. */
export function extract402Invoice(result: CallToolResult): PaymentInvoice | null {
  try {
    const first = result.content[0];
    const text = (first?.type === "text" ? first.text : undefined) ?? "";
    const parsed = JSON.parse(text) as Partial<PaymentChallenge>;
    if (parsed.code === 402 && parsed.invoice) return parsed.invoice;
  } catch {
    // fall through
  }
  return null;
}
