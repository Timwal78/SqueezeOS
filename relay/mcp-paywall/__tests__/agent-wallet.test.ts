import { Wallet } from "xrpl";
import { agentWallet } from "../src/agent-wallet";
import type { AgentWalletConfig, CallToolResult, PaymentInvoice, ToolContent } from "../src/types";

const txt = (c: ToolContent) => (c as { text?: string }).text ?? "";

// ── Fixtures ──────────────────────────────────────────────────────────────────

const TESTNET_RLUSD_ISSUER = "rMxCKbEDwqr76QuheSUMdEGf4B9xJ8m5De";

const agentWalletObj = Wallet.generate();
const serverWallet   = Wallet.generate();

const config: AgentWalletConfig = {
  seed: agentWalletObj.seed!,
  network: "xrpl_testnet",
  maxSpendPerCallRlusd: 1.0,
  _signPayment: async (invoice: PaymentInvoice) => {
    // Offline mock signer — returns a real signed tx blob without XRPL connection
    const tx = {
      TransactionType: "Payment" as const,
      Account: agentWalletObj.classicAddress,
      Destination: invoice.recipient,
      Amount: { currency: "USD", issuer: TESTNET_RLUSD_ISSUER, value: invoice.priceRlusd.toString() },
      Fee: "12",
      Sequence: Math.floor(Math.random() * 1_000_000), // unique per call
      LastLedgerSequence: 9_999_999,
    };
    return agentWalletObj.sign(tx).tx_blob;
  },
};

function make402Result(priceRlusd: number): CallToolResult {
  return {
    content: [{
      type: "text",
      text: JSON.stringify({
        error: "PAYMENT_REQUIRED",
        code: 402,
        invoice: {
          version: "1.0",
          priceRlusd,
          recipient: serverWallet.classicAddress,
          network: "xrpl_testnet",
          endpointId: "test-tool",
          expiresAt: Math.floor(Date.now() / 1000) + 300,
        },
      }),
    }],
    isError: true,
  };
}

function makeSuccessResult(text = "tool output"): CallToolResult {
  return { content: [{ type: "text", text }] };
}

// ── address ───────────────────────────────────────────────────────────────────

describe("agentWallet.address", () => {
  it("exposes the XRPL address of the agent wallet", () => {
    const w = agentWallet(config);
    expect(w.address).toBe(agentWalletObj.classicAddress);
  });
});

// ── callWithPayment — pass-through ────────────────────────────────────────────

describe("agentWallet.callWithPayment — no payment needed", () => {
  it("returns the tool result directly when no 402", async () => {
    const callTool = jest.fn(async () => makeSuccessResult("direct output"));
    const w = agentWallet(config);
    const result = await w.callWithPayment(callTool, "free-tool", { q: "test" });
    expect(txt(result.content[0])).toBe("direct output");
    expect(callTool).toHaveBeenCalledTimes(1);
  });

  it("passes tool arguments through unmodified", async () => {
    const captured: unknown[] = [];
    const callTool = jest.fn(async (_name: string, args: Record<string, unknown>) => {
      captured.push(args);
      return makeSuccessResult();
    });
    const w = agentWallet(config);
    await w.callWithPayment(callTool, "tool", { foo: "bar", count: 42 });
    expect(captured[0]).toEqual({ foo: "bar", count: 42 });
  });
});

// ── callWithPayment — auto-pay ────────────────────────────────────────────────

describe("agentWallet.callWithPayment — auto-pay 402", () => {
  it("retries with _relay_payment after receiving 402", async () => {
    const callTool = jest.fn()
      .mockResolvedValueOnce(make402Result(0.10))
      .mockResolvedValueOnce(makeSuccessResult("paid output"));
    const w = agentWallet(config);
    const result = await w.callWithPayment(callTool, "paid-tool", { q: "hello" });
    expect(txt(result.content[0])).toBe("paid output");
    expect(callTool).toHaveBeenCalledTimes(2);
  });

  it("injects _relay_payment in the retry call", async () => {
    const retryArgs: unknown[] = [];
    const callTool = jest.fn()
      .mockResolvedValueOnce(make402Result(0.10))
      .mockImplementationOnce(async (_name: string, args: Record<string, unknown>) => {
        retryArgs.push(args);
        return makeSuccessResult();
      });
    const w = agentWallet(config);
    await w.callWithPayment(callTool, "paid-tool", { query: "test" });
    expect(retryArgs[0]).toHaveProperty("_relay_payment");
    expect(typeof (retryArgs[0] as Record<string, unknown>)._relay_payment).toBe("string");
  });

  it("preserves original tool args in the retry call", async () => {
    const retryArgs: unknown[] = [];
    const callTool = jest.fn()
      .mockResolvedValueOnce(make402Result(0.10))
      .mockImplementationOnce(async (_name: string, args: Record<string, unknown>) => {
        retryArgs.push(args);
        return makeSuccessResult();
      });
    const w = agentWallet(config);
    await w.callWithPayment(callTool, "paid-tool", { query: "keep-me", id: 99 });
    const args = retryArgs[0] as Record<string, unknown>;
    expect(args.query).toBe("keep-me");
    expect(args.id).toBe(99);
  });

  it("builds a valid base64 JSON envelope as the proof", async () => {
    let capturedProof = "";
    const callTool = jest.fn()
      .mockResolvedValueOnce(make402Result(0.10))
      .mockImplementationOnce(async (_name: string, args: Record<string, unknown>) => {
        capturedProof = String(args._relay_payment ?? "");
        return makeSuccessResult();
      });
    const w = agentWallet(config);
    await w.callWithPayment(callTool, "paid-tool", {});
    const envelope = JSON.parse(Buffer.from(capturedProof, "base64").toString("utf8"));
    expect(envelope.scheme).toBe("exact");
    expect(envelope.payload).toBeTruthy();
    expect(typeof envelope.payload).toBe("string");
  });
});

// ── callWithPayment — spending guard ──────────────────────────────────────────

describe("agentWallet.callWithPayment — spending guard", () => {
  it("throws when price exceeds maxSpendPerCallRlusd", async () => {
    const callTool = jest.fn().mockResolvedValueOnce(make402Result(5.00)); // 5 RLUSD
    const w = agentWallet(config); // limit is 1.0
    await expect(
      w.callWithPayment(callTool, "expensive-tool", {})
    ).rejects.toThrow(/exceeds maxSpendPerCallRlusd/);
  });

  it("does not sign a payment when the guard fires", async () => {
    const callTool = jest.fn().mockResolvedValueOnce(make402Result(99.0));
    const signSpy = jest.fn();
    const limitedConfig: AgentWalletConfig = { ...config, _signPayment: signSpy };
    const w = agentWallet(limitedConfig);
    await expect(w.callWithPayment(callTool, "tool", {})).rejects.toThrow();
    expect(signSpy).not.toHaveBeenCalled();
  });

  it("pays exactly at the limit boundary", async () => {
    const callTool = jest.fn()
      .mockResolvedValueOnce(make402Result(1.0)) // exactly at 1.0 limit
      .mockResolvedValueOnce(makeSuccessResult("at limit OK"));
    const w = agentWallet(config);
    const result = await w.callWithPayment(callTool, "tool", {});
    expect(txt(result.content[0])).toBe("at limit OK");
  });
});

// ── callWithPayment — expired invoice ─────────────────────────────────────────

describe("agentWallet.callWithPayment — expiry", () => {
  it("throws when invoice has already expired", async () => {
    const expired402: CallToolResult = {
      content: [{
        type: "text",
        text: JSON.stringify({
          error: "PAYMENT_REQUIRED",
          code: 402,
          invoice: {
            version: "1.0",
            priceRlusd: 0.10,
            recipient: serverWallet.classicAddress,
            network: "xrpl_testnet",
            endpointId: "test",
            expiresAt: Math.floor(Date.now() / 1000) - 60, // expired 60s ago
          },
        }),
      }],
      isError: true,
    };
    const callTool = jest.fn().mockResolvedValueOnce(expired402);
    const w = agentWallet(config);
    await expect(w.callWithPayment(callTool, "tool", {})).rejects.toThrow(/expired/);
  });
});

// ── callWithPayment — payment rejected by server ──────────────────────────────

describe("agentWallet.callWithPayment — server rejects payment", () => {
  it("throws when server returns 402 on the retry call", async () => {
    const rejected402: CallToolResult = {
      content: [{
        type: "text",
        text: JSON.stringify({ error: "PAYMENT_INVALID", code: 402, reason: "Replay detected" }),
      }],
      isError: true,
    };
    const callTool = jest.fn()
      .mockResolvedValueOnce(make402Result(0.10))
      .mockResolvedValueOnce(rejected402);
    const w = agentWallet(config);
    await expect(w.callWithPayment(callTool, "tool", {})).rejects.toThrow(/Replay detected/);
  });
});
