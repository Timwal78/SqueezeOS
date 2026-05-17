import { z } from "zod";
import type { Transaction } from "xrpl";
import {
  paywall,
  paywallSchema,
  is402Response,
  extract402Invoice,
  buildInvoice,
} from "../src/paywall";
import { createInMemoryReplayStore } from "../src/verifier";
import type { PaywallConfig, CallToolResult, ToolContent } from "../src/types";
import { Wallet } from "xrpl";

// Narrow ToolContent to its text field without discriminating every time
const txt = (c: ToolContent) => (c as { text?: string }).text ?? "";

// ── Fixtures ──────────────────────────────────────────────────────────────────

const TESTNET_RLUSD_ISSUER = "rMxCKbEDwqr76QuheSUMdEGf4B9xJ8m5De";
const recipient = Wallet.generate();
const payer    = Wallet.generate();

const config: PaywallConfig = {
  priceRlusd: 0.10,
  recipient: recipient.classicAddress,
  network: "xrpl_testnet",
};

let _proofSeq = 1;
function makeValidProof(price = 0.10): string {
  const tx = {
    TransactionType: "Payment" as const,
    Account: payer.classicAddress,
    Destination: recipient.classicAddress,
    Amount: { currency: "USD", issuer: TESTNET_RLUSD_ISSUER, value: price.toString() },
    Fee: "12",
    Sequence: _proofSeq++,   // unique per call — anti-replay never fires between tests
    LastLedgerSequence: 9_999_999,
  };
  const { tx_blob } = payer.sign(tx);
  return Buffer.from(JSON.stringify({ scheme: "exact", network: "xrpl-testnet", payload: tx_blob })).toString("base64");
}

const successHandler = jest.fn(async () => ({
  content: [{ type: "text" as const, text: "tool result" }],
}));

beforeEach(() => {
  jest.clearAllMocks();
});

// ── paywallSchema ──────────────────────────────────────────────────────────────

describe("paywallSchema", () => {
  it("adds _relay_payment as optional string", () => {
    const schema = paywallSchema({ name: z.string(), count: z.number() });
    expect(schema._relay_payment).toBeDefined();
    expect(() => schema._relay_payment?.parse(undefined)).not.toThrow();
    expect(() => schema._relay_payment?.parse("proof-string")).not.toThrow();
  });

  it("preserves existing schema fields", () => {
    const schema = paywallSchema({ query: z.string() });
    expect(schema.query).toBeDefined();
  });
});

// ── buildInvoice ──────────────────────────────────────────────────────────────

describe("buildInvoice", () => {
  it("builds invoice with correct fields", () => {
    const invoice = buildInvoice(config, "test-endpoint");
    expect(invoice.version).toBe("1.0");
    expect(invoice.priceRlusd).toBe(0.10);
    expect(invoice.recipient).toBe(config.recipient);
    expect(invoice.network).toBe("xrpl_testnet");
    expect(invoice.endpointId).toBe("test-endpoint");
    expect(invoice.expiresAt).toBeGreaterThan(Math.floor(Date.now() / 1000));
  });
});

// ── paywall — 402 challenge ───────────────────────────────────────────────────

describe("paywall — returns 402 when no payment", () => {
  const handler = paywall(config, successHandler);

  it("returns isError: true when _relay_payment is absent", async () => {
    const result = await handler({ query: "test" });
    expect(result.isError).toBe(true);
  });

  it("text content is parseable JSON with code 402", async () => {
    const result = await handler({ query: "test" });
    const body = JSON.parse(txt(result.content[0]) ?? "");
    expect(body.code).toBe(402);
    expect(body.error).toBe("PAYMENT_REQUIRED");
  });

  it("invoice in 402 body has correct price and recipient", async () => {
    const result = await handler({ query: "test" });
    const body = JSON.parse(txt(result.content[0]) ?? "");
    expect(body.invoice.priceRlusd).toBe(0.10);
    expect(body.invoice.recipient).toBe(config.recipient);
    expect(body.invoice.network).toBe("xrpl_testnet");
  });

  it("does NOT call the underlying handler", async () => {
    await handler({ query: "test" });
    expect(successHandler).not.toHaveBeenCalled();
  });
});

// ── paywall — valid payment ───────────────────────────────────────────────────

describe("paywall — executes handler on valid payment", () => {
  // Each test gets a fresh replay store via a fresh paywall wrapping fresh config
  // (config objects share recipient/network, but each call is unique due to tx Sequence)
  // We use a different sequence per proof by invoking makeValidProof once per test.

  it("calls handler and returns its result", async () => {
    const proof = makeValidProof();
    const handler = paywall(config, successHandler);
    const result = await handler({ query: "hello", _relay_payment: proof });
    expect(result.isError).toBeUndefined();
    expect(txt(result.content[0])).toBe("tool result");
    expect(successHandler).toHaveBeenCalledTimes(1);
  });

  it("strips _relay_payment from params passed to handler", async () => {
    const captured: Record<string, unknown>[] = [];
    const proof = makeValidProof();
    const h = paywall(config, async (params) => {
      captured.push(params as Record<string, unknown>);
      return { content: [{ type: "text" as const, text: "ok" }] };
    });
    const result = await h({ query: "hello", extra: 42, _relay_payment: proof });
    expect(result.isError).toBeUndefined();
    expect(captured).toHaveLength(1);
    expect(captured[0]).not.toHaveProperty("_relay_payment");
    expect(captured[0]).toHaveProperty("query", "hello");
    expect(captured[0]).toHaveProperty("extra", 42);
  });
});

// ── paywall — invalid payment ─────────────────────────────────────────────────

describe("paywall — rejects invalid payment", () => {
  const handler = paywall(config, successHandler);

  it("rejects malformed proof", async () => {
    const result = await handler({ _relay_payment: "not-valid-base64-json" });
    expect(result.isError).toBe(true);
    const body = JSON.parse(txt(result.content[0]) ?? "");
    expect(body.error).toBe("PAYMENT_INVALID");
  });

  it("does NOT call the underlying handler on invalid payment", async () => {
    await handler({ _relay_payment: "bad-proof" });
    expect(successHandler).not.toHaveBeenCalled();
  });
});

// ── is402Response ─────────────────────────────────────────────────────────────

describe("is402Response", () => {
  it("returns true for a 402 error result", () => {
    const result: CallToolResult = {
      content: [{ type: "text", text: JSON.stringify({ code: 402, error: "PAYMENT_REQUIRED", invoice: {} }) }],
      isError: true,
    };
    expect(is402Response(result)).toBe(true);
  });

  it("returns false for a success result", () => {
    const result: CallToolResult = {
      content: [{ type: "text", text: "success" }],
    };
    expect(is402Response(result)).toBe(false);
  });

  it("returns false for non-402 error", () => {
    const result: CallToolResult = {
      content: [{ type: "text", text: JSON.stringify({ code: 500, error: "INTERNAL" }) }],
      isError: true,
    };
    expect(is402Response(result)).toBe(false);
  });

  it("returns false for isError without parseable JSON", () => {
    const result: CallToolResult = {
      content: [{ type: "text", text: "plain error message" }],
      isError: true,
    };
    expect(is402Response(result)).toBe(false);
  });
});

// ── extract402Invoice ─────────────────────────────────────────────────────────

describe("extract402Invoice", () => {
  it("extracts invoice from a 402 result", () => {
    const invoice = buildInvoice(config, "test");
    const result: CallToolResult = {
      content: [{ type: "text", text: JSON.stringify({ code: 402, error: "PAYMENT_REQUIRED", invoice }) }],
      isError: true,
    };
    const extracted = extract402Invoice(result);
    expect(extracted).not.toBeNull();
    expect(extracted?.priceRlusd).toBe(0.10);
    expect(extracted?.recipient).toBe(config.recipient);
  });

  it("returns null for non-402 result", () => {
    const result: CallToolResult = {
      content: [{ type: "text", text: "success" }],
    };
    expect(extract402Invoice(result)).toBeNull();
  });

  it("returns null for malformed JSON content", () => {
    const result: CallToolResult = {
      content: [{ type: "text", text: "{not json}" }],
      isError: true,
    };
    expect(extract402Invoice(result)).toBeNull();
  });
});
