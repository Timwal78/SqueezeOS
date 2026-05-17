import { Wallet } from "xrpl";
import {
  AgentWalletAdapter,
  CrossmarkAdapter,
  XamanAdapter,
  detectAdapterType,
} from "../wallet-adapter";

// ── AgentWalletAdapter ───────────────────────────────────────────────────────

describe("AgentWalletAdapter", () => {
  let adapter: AgentWalletAdapter;
  let wallet: Wallet;

  beforeEach(() => {
    wallet = Wallet.generate();
    adapter = new AgentWalletAdapter(wallet);
  });

  it("exposes address and publicKey", () => {
    expect(adapter.address).toBe(wallet.classicAddress);
    expect(adapter.publicKey).toBe(wallet.publicKey);
    expect(adapter.type).toBe("agent");
  });

  it("isConnected returns true", () => {
    expect(adapter.isConnected()).toBe(true);
  });

  it("signs a prepared transaction", async () => {
    const tx = {
      TransactionType: "AccountSet",
      Account: wallet.classicAddress,
      Fee: "12",
      Sequence: 1,
      LastLedgerSequence: 100000,
    };
    const result = await adapter.sign(tx);
    expect(result.txBlob).toBeTruthy();
    expect(result.txHash).toHaveLength(64);
  });

  it("signForMultisig returns a blob", async () => {
    const tx = {
      TransactionType: "AccountSet",
      Account: wallet.classicAddress,
      Fee: "12",
      Sequence: 1,
      LastLedgerSequence: 100000,
      SigningPubKey: "",
    };
    const blob = await adapter.signForMultisig(tx);
    expect(blob).toBeTruthy();
    expect(typeof blob).toBe("string");
  });

  it("signMessage returns a tx_blob", async () => {
    const msgHex = Buffer.from("hello relay").toString("hex");
    const blob = await adapter.signMessage(msgHex);
    expect(blob).toBeTruthy();
  });

  it("AgentWalletAdapter.fromSeed creates from seed", () => {
    const seed = wallet.seed!;
    const fromSeed = AgentWalletAdapter.fromSeed(seed);
    expect(fromSeed.address).toBe(wallet.classicAddress);
  });

  it("AgentWalletAdapter.generate creates fresh keypair", () => {
    const a = AgentWalletAdapter.generate();
    const b = AgentWalletAdapter.generate();
    expect(a.address).not.toBe(b.address);
  });
});

// ── CrossmarkAdapter ─────────────────────────────────────────────────────────

describe("CrossmarkAdapter", () => {
  const mockAddress = "rCrossmarkTest123456789012345678901";
  const mockPublicKey = "ED" + "A".repeat(62);

  const mockSDK = {
    signIn: jest.fn().mockResolvedValue({
      response: { data: { address: mockAddress, publicKey: mockPublicKey } },
    }),
    signAndSubmit: jest.fn().mockResolvedValue({
      response: { data: { resp: { txBlob: "DEADBEEF", txHash: "A".repeat(64) } } },
    }),
    isConnected: jest.fn().mockReturnValue(true),
  };

  it("connect sets address and publicKey", async () => {
    const adapter = new CrossmarkAdapter(mockSDK);
    await adapter.connect();
    expect(adapter.address).toBe(mockAddress);
    expect(adapter.publicKey).toBe(mockPublicKey);
    expect(adapter.type).toBe("crossmark");
    expect(adapter.isConnected()).toBe(true);
  });

  it("sign calls signAndSubmit", async () => {
    const adapter = new CrossmarkAdapter(mockSDK);
    await adapter.connect();
    const result = await adapter.sign({ TransactionType: "AccountSet", Account: mockAddress });
    expect(mockSDK.signAndSubmit).toHaveBeenCalled();
    expect(result.txBlob).toBe("DEADBEEF");
  });

  it("throws NOT_CONNECTED if sign called before connect", async () => {
    const adapter = new CrossmarkAdapter(mockSDK);
    await expect(adapter.sign({ TransactionType: "AccountSet" })).rejects.toThrow(
      "not connected"
    );
  });

  it("signForMultisig throws MULTISIG_UNSUPPORTED", async () => {
    const adapter = new CrossmarkAdapter(mockSDK);
    await adapter.connect();
    await expect(adapter.signForMultisig({})).rejects.toThrow(/multi-sig/i);
  });
});

// ── detectAdapterType ────────────────────────────────────────────────────────

describe("detectAdapterType", () => {
  it("returns agent in non-browser environment", () => {
    // Node.js has no window.crossmark or xaman
    expect(detectAdapterType()).toBe("agent");
  });

  it("returns crossmark when window.crossmark present", () => {
    (globalThis as Record<string, unknown>).crossmark = {};
    expect(detectAdapterType()).toBe("crossmark");
    delete (globalThis as Record<string, unknown>).crossmark;
  });

  it("returns xaman when window.xaman present", () => {
    (globalThis as Record<string, unknown>).xaman = {};
    expect(detectAdapterType()).toBe("xaman");
    delete (globalThis as Record<string, unknown>).xaman;
  });
});
