/**
 * End-to-end 402 handshake integration test.
 *
 * Tests the full loop: paywall() intercepts → 402 challenge → agentWallet
 * detects, signs, retries → paywall() validates → tool executes.
 *
 * Does NOT use real MCP transport (InMemoryTransport keeps open handles in Jest).
 * Uses paywall() and agentWallet() as drop-in function implementations instead,
 * which are the actual protocol implementations under test.
 *
 * XRPL network is NOT touched — payment signing is injected via _signPayment.
 * verifyPayment is mocked to accept any non-empty proof.
 */

jest.mock("../src/verifier", () => ({
  ...jest.requireActual("../src/verifier"),
  verifyPayment: jest.fn(async (proof: string) => {
    if (!proof || proof === "BAD") return { valid: false, reason: "Mock rejection" };
    return { valid: true };
  }),
}));

import { Wallet } from "xrpl";
import { paywall, paywallSchema } from "../src/paywall";
import { agentWallet } from "../src/agent-wallet";
import type { PaywallConfig, AgentWalletConfig, PaymentInvoice, CallToolResult, ToolContent } from "../src/types";

// Safely read text from any content item
const txt = (c: ToolContent | unknown): string => (c as { text?: string })?.text ?? "";

// ── Fixtures ──────────────────────────────────────────────────────────────────

const TESTNET_RLUSD_ISSUER = "rMxCKbEDwqr76QuheSUMdEGf4B9xJ8m5De";
const serverOwner  = Wallet.generate();
const agentW       = Wallet.generate();

const wallCfg = (price: number): PaywallConfig => ({
  priceRlusd: price,
  recipient: serverOwner.classicAddress,
  network: "xrpl_testnet",
});

const walletCfg: AgentWalletConfig = {
  seed: agentW.seed!,
  network: "xrpl_testnet",
  maxSpendPerCallRlusd: 2.0,
  _signPayment: async (invoice: PaymentInvoice) => {
    const tx = {
      TransactionType: "Payment" as const,
      Account: agentW.classicAddress,
      Destination: invoice.recipient,
      Amount: { currency: "USD", issuer: TESTNET_RLUSD_ISSUER, value: invoice.priceRlusd.toString() },
      Fee: "12",
      Sequence: Math.floor(Math.random() * 10_000_000),
      LastLedgerSequence: 9_999_999,
    };
    return agentW.sign(tx).tx_blob;
  },
};

// Simulate the server side: paywall-wrapped handler exposed as a callTool function
function makeServer(price: number, toolFn: (args: Record<string, unknown>) => Promise<CallToolResult>) {
  const handler = paywall(wallCfg(price), toolFn);
  return async (name: string, args: Record<string, unknown>): Promise<CallToolResult> => {
    return handler(args);
  };
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("Full 402 handshake: paywall() ↔ agentWallet()", () => {
  afterEach(() => jest.clearAllMocks());

  it("free (unpaywalled) tool passes through without any 402 flow", async () => {
    const callTool = jest.fn(async () => ({
      content: [{ type: "text" as const, text: "free result" }],
    }));
    const wallet = agentWallet(walletCfg);
    const result = await wallet.callWithPayment(callTool, "free-tool", { q: "test" });
    expect(txt(result.content[0])).toBe("free result");
    expect(callTool).toHaveBeenCalledTimes(1);
  });

  it("paid tool: agentWallet pays 402 and receives tool output", async () => {
    const server = makeServer(0.05, async ({ query }) => ({
      content: [{ type: "text" as const, text: `result for: ${query}` }],
    }));
    const wallet = agentWallet(walletCfg);
    const result = await wallet.callWithPayment(server, "data-tool", { query: "eth" });
    expect(result.isError).toBeUndefined();
    expect(txt(result.content[0])).toBe("result for: eth");
  });

  it("server receives exactly two calls: challenge then paid", async () => {
    let calls = 0;
    const server = makeServer(0.10, async () => {
      calls++;
      return { content: [{ type: "text" as const, text: "ok" }] };
    });
    const wallet = agentWallet(walletCfg);
    await wallet.callWithPayment(server, "tool", { x: 1 });
    // The inner handler runs once (only on the paid retry call)
    expect(calls).toBe(1);
  });

  it("original tool args are preserved after payment injection", async () => {
    let receivedArgs: Record<string, unknown> | null = null;
    const server = makeServer(0.10, async (args) => {
      receivedArgs = args;
      return { content: [{ type: "text" as const, text: "ok" }] };
    });
    const wallet = agentWallet(walletCfg);
    await wallet.callWithPayment(server, "tool", { field1: "keep-me", nested: { v: 99 } });
    expect(receivedArgs).not.toBeNull();
    expect(receivedArgs!.field1).toBe("keep-me");
    expect(receivedArgs!.nested).toEqual({ v: 99 });
    expect(receivedArgs!._relay_payment).toBeUndefined();
  });

  it("multiple concurrent tool calls, different prices, all succeed", async () => {
    const cheap  = makeServer(0.01, async ({ id }) => ({ content: [{ type: "text" as const, text: `cheap:${id}` }] }));
    const medium = makeServer(0.50, async ({ id }) => ({ content: [{ type: "text" as const, text: `medium:${id}` }] }));
    const wallet = agentWallet(walletCfg); // limit: 2.0 RLUSD

    const [r1, r2, r3] = await Promise.all([
      wallet.callWithPayment(cheap, "cheap", { id: "A" }),
      wallet.callWithPayment(medium, "medium", { id: "B" }),
      wallet.callWithPayment(cheap, "cheap", { id: "C" }),
    ]);
    expect(txt(r1.content[0])).toBe("cheap:A");
    expect(txt(r2.content[0])).toBe("medium:B");
    expect(txt(r3.content[0])).toBe("cheap:C");
  });

  it("agentWallet refuses if tool price exceeds maxSpendPerCallRlusd", async () => {
    const expensive = makeServer(5.0, async () => ({ content: [{ type: "text" as const, text: "never" }] }));
    const wallet = agentWallet(walletCfg); // limit: 2.0
    await expect(
      wallet.callWithPayment(expensive, "expensive", { q: "x" })
    ).rejects.toThrow(/exceeds maxSpendPerCallRlusd/);
  });

  it("server rejects invalid proof and agentWallet throws", async () => {
    // Mock verifyPayment to reject specifically 'BAD' proofs
    const { verifyPayment } = require("../src/verifier");
    (verifyPayment as jest.Mock).mockResolvedValueOnce({ valid: false, reason: "Tampered proof" });

    const server = makeServer(0.10, async () => ({ content: [{ type: "text" as const, text: "ok" }] }));
    const wallet = agentWallet(walletCfg);
    await expect(
      wallet.callWithPayment(server, "tool", { q: "x" })
    ).rejects.toThrow(/Tampered proof/);
  });

  it("tool result content is delivered unmodified after payment flow", async () => {
    const expected = { status: "ok", data: [1, 2, 3], meta: { pages: 5 } };
    const server = makeServer(0.10, async () => ({
      content: [{ type: "text" as const, text: JSON.stringify(expected) }],
    }));
    const wallet = agentWallet(walletCfg);
    const result = await wallet.callWithPayment(server, "json-tool", { q: "x" });
    expect(JSON.parse(txt(result.content[0]))).toEqual(expected);
  });

  it("same tool can be called multiple times with independent payment proofs", async () => {
    const results: string[] = [];
    const server = makeServer(0.05, async ({ id }) => ({
      content: [{ type: "text" as const, text: String(id) }],
    }));
    const wallet = agentWallet(walletCfg);
    for (const id of ["A", "B", "C"]) {
      const r = await wallet.callWithPayment(server, "tool", { id });
      results.push(txt(r.content[0]));
    }
    expect(results).toEqual(["A", "B", "C"]);
  });
});
