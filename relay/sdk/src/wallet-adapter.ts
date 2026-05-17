/**
 * Universal Wallet Adapter — unified signing interface for all contexts.
 *
 * Three adapter implementations:
 *
 *   AgentWalletAdapter    — programmatic keypair signing for autonomous AI agents.
 *                           The primary mode. Agents hold their own keys, sign locally.
 *
 *   CrossmarkAdapter      — browser extension (desktop). Synchronous API, best for
 *                           developer tooling and human operators monitoring agents.
 *
 *   XamanAdapter          — Xaman (XUMM) push signing. Mobile-first, QR payloads,
 *                           deep links. Best for production human oversight and
 *                           high-value transactions requiring explicit approval.
 *
 * All adapters implement WalletAdapter. The SDK never calls an adapter directly —
 * it accepts a WalletAdapter and the caller decides which backend to use.
 * Zero-custody holds: no adapter ever exposes private keys to the server.
 */

import { Wallet } from "xrpl";
import { Network } from "./types";
import { isValidXrplAddress, makeError } from "./xrpl-client";

// ── Core interface ───────────────────────────────────────────────────────────

export interface SignResult {
  txBlob: string;
  txHash: string;
}

export interface WalletAdapter {
  readonly address: string;
  readonly publicKey: string;
  readonly type: "agent" | "crossmark" | "xaman";

  /** Sign a prepared (autofilled) XRPL transaction. Returns signed tx blob. */
  sign(preparedTx: Record<string, unknown>): Promise<SignResult>;

  /** Sign for multi-signing (includes signer's address in signature). */
  signForMultisig(preparedTx: Record<string, unknown>): Promise<string>;

  /** Sign an arbitrary message hex (for vote signing, attestations). */
  signMessage(messageHex: string): Promise<string>;

  /** Check if wallet is connected / available. */
  isConnected(): boolean;
}

// ── 1. Agent Wallet Adapter (programmatic — primary for AI agents) ───────────

/**
 * AgentWalletAdapter wraps a local XRPL Wallet keypair.
 * Used by autonomous agents that hold their own keys and sign without human interaction.
 *
 * Key management is the agent's responsibility. Relay never sees the private key.
 * Agents should use hardware-backed secure storage (HSM, KMS, encrypted env) in production.
 */
export class AgentWalletAdapter implements WalletAdapter {
  readonly type = "agent" as const;

  constructor(private readonly wallet: Wallet) {}

  get address(): string {
    return this.wallet.classicAddress;
  }

  get publicKey(): string {
    return this.wallet.publicKey;
  }

  async sign(preparedTx: Record<string, unknown>): Promise<SignResult> {
    const signed = this.wallet.sign(preparedTx as Parameters<typeof this.wallet.sign>[0]);
    return { txBlob: signed.tx_blob, txHash: signed.hash };
  }

  async signForMultisig(preparedTx: Record<string, unknown>): Promise<string> {
    const signed = this.wallet.sign(
      preparedTx as Parameters<typeof this.wallet.sign>[0],
      true
    );
    return signed.tx_blob;
  }

  async signMessage(messageHex: string): Promise<string> {
    // Sign via AccountSet Domain — same approach as voting.ts
    const tx = {
      TransactionType: "AccountSet",
      Account: this.wallet.classicAddress,
      Domain: messageHex,
      Fee: "12",
      Sequence: 0,
      LastLedgerSequence: 0,
    };
    const signed = this.wallet.sign(tx as Parameters<typeof this.wallet.sign>[0]);
    return signed.tx_blob;
  }

  isConnected(): boolean {
    return true; // local keypair is always available
  }

  /** Convenience: create from XRPL seed (agent self-manages the seed). */
  static fromSeed(seed: string): AgentWalletAdapter {
    return new AgentWalletAdapter(Wallet.fromSeed(seed));
  }

  /** Generate a fresh random keypair (for testing / new agent onboarding). */
  static generate(): AgentWalletAdapter {
    return new AgentWalletAdapter(Wallet.generate());
  }
}

// ── 2. Crossmark Adapter (browser extension — developer/desktop) ─────────────

export interface CrossmarkSDK {
  signAndSubmit(tx: Record<string, unknown>): Promise<{
    response: { data: { resp: { txBlob: string; txHash: string } } };
  }>;
  signIn(): Promise<{ response: { data: { address: string; publicKey: string } } }>;
  isConnected(): boolean;
}

/**
 * CrossmarkAdapter wraps the Crossmark browser extension SDK.
 * The extension handles key storage and signing UI natively in the browser.
 *
 * Usage: inject `window.crossmark` (or the Crossmark npm SDK) as `sdk`.
 * In non-browser environments (agents), use AgentWalletAdapter instead.
 */
export class CrossmarkAdapter implements WalletAdapter {
  readonly type = "crossmark" as const;
  private _address: string = "";
  private _publicKey: string = "";
  private connected = false;

  constructor(private readonly sdk: CrossmarkSDK) {}

  get address(): string {
    if (!this._address) throw makeError("NOT_CONNECTED", "Crossmark not connected. Call connect() first.");
    return this._address;
  }

  get publicKey(): string {
    return this._publicKey;
  }

  async connect(): Promise<void> {
    const result = await this.sdk.signIn();
    this._address = result.response.data.address;
    this._publicKey = result.response.data.publicKey;
    this.connected = true;
  }

  async sign(preparedTx: Record<string, unknown>): Promise<SignResult> {
    this.assertConnected();
    const result = await this.sdk.signAndSubmit(preparedTx);
    const { txBlob, txHash } = result.response.data.resp;
    return { txBlob, txHash };
  }

  async signForMultisig(preparedTx: Record<string, unknown>): Promise<string> {
    this.assertConnected();
    // Crossmark doesn't natively support multi-sig signing mode in v1.
    // For multi-sig, fall back to requesting a raw sign via signMessage.
    throw makeError(
      "MULTISIG_UNSUPPORTED",
      "Crossmark v1 does not support multi-sig mode. Use AgentWalletAdapter for evaluator signing."
    );
  }

  async signMessage(messageHex: string): Promise<string> {
    this.assertConnected();
    const tx = {
      TransactionType: "AccountSet",
      Account: this._address,
      Domain: messageHex,
    };
    const result = await this.sdk.signAndSubmit(tx);
    return result.response.data.resp.txBlob;
  }

  isConnected(): boolean {
    return this.connected;
  }

  private assertConnected(): void {
    if (!this.connected) {
      throw makeError("NOT_CONNECTED", "Crossmark not connected. Call connect() first.");
    }
  }

  /** Factory: create from window.crossmark in browser environment. */
  static fromWindow(): CrossmarkAdapter {
    const sdk = (globalThis as Record<string, unknown>).crossmark as CrossmarkSDK | undefined;
    if (!sdk) {
      throw makeError(
        "CROSSMARK_NOT_FOUND",
        "Crossmark extension not detected. Install from crossmark.io"
      );
    }
    return new CrossmarkAdapter(sdk);
  }
}

// ── 3. Xaman Adapter (mobile push signing — production human oversight) ───────

export interface XamanPayloadOptions {
  txjson: Record<string, unknown>;
  options?: {
    submit?: boolean;
    return_url?: { web?: string; app?: string };
    expire?: number;
  };
  custom_meta?: {
    instruction?: string;
    blob?: Record<string, unknown>;
  };
}

export interface XamanPayloadResponse {
  uuid: string;
  next: { always: string }; // QR deep link URL
  refs: { qr_png: string; websocket_status: string };
  pushed: boolean;
}

export interface XamanPayloadResult {
  signed: boolean;
  txid?: string;
  hex?: string;
  payload: { tx_type: string; request_json: Record<string, unknown> };
}

export interface XamanSDK {
  payload: {
    create(payload: XamanPayloadOptions): Promise<XamanPayloadResponse>;
    get(uuid: string): Promise<{ meta: { signed: boolean; expired: boolean }; response: { hex?: string; txid?: string } }>;
    cancel(uuid: string): Promise<void>;
  };
  me?: { account: string; publicKey?: string };
}

/**
 * XamanAdapter wraps the Xaman (XUMM) SDK for mobile push signing.
 *
 * Signing flow:
 *   1. Create a payload (returns QR code + push notification)
 *   2. User approves on their Xaman mobile app
 *   3. Poll or webhook for signed result
 *
 * Best for: production human oversight, high-value job authorization,
 * evaluator stake registration where human confirmation is desired.
 */
export class XamanAdapter implements WalletAdapter {
  readonly type = "xaman" as const;
  private _address: string;
  private _publicKey: string;

  constructor(
    private readonly sdk: XamanSDK,
    address: string,
    publicKey: string = ""
  ) {
    if (!isValidXrplAddress(address)) {
      throw makeError("INVALID_ADDRESS", `Invalid Xaman address: ${address}`);
    }
    this._address = address;
    this._publicKey = publicKey;
  }

  get address(): string { return this._address; }
  get publicKey(): string { return this._publicKey; }

  async sign(preparedTx: Record<string, unknown>): Promise<SignResult> {
    const result = await this.pushAndWait({
      txjson: preparedTx,
      options: { submit: false },
      custom_meta: {
        instruction: "Relay: Please sign this transaction to proceed with your job.",
      },
    });

    if (!result.signed || !result.hex) {
      throw makeError("XAMAN_REJECTED", "Transaction rejected in Xaman");
    }
    return { txBlob: result.hex, txHash: result.txid ?? "" };
  }

  async signForMultisig(preparedTx: Record<string, unknown>): Promise<string> {
    const result = await this.pushAndWait({
      txjson: { ...preparedTx, SigningPubKey: "" },
      options: { submit: false },
      custom_meta: {
        instruction: "Relay: Multi-sig authorization required for dispute resolution.",
      },
    });
    if (!result.signed || !result.hex) {
      throw makeError("XAMAN_REJECTED", "Multi-sig rejected in Xaman");
    }
    return result.hex;
  }

  async signMessage(messageHex: string): Promise<string> {
    const result = await this.pushAndWait({
      txjson: {
        TransactionType: "AccountSet",
        Account: this._address,
        Domain: messageHex,
      },
      custom_meta: { instruction: "Relay: Sign this message to cast your evaluator vote." },
    });
    if (!result.signed || !result.hex) {
      throw makeError("XAMAN_REJECTED", "Message signing rejected in Xaman");
    }
    return result.hex;
  }

  isConnected(): boolean { return true; }

  /**
   * Build a sign-in payload and return the QR URL.
   * Used in web UIs to display a QR code for wallet connection.
   */
  async buildSignInQR(): Promise<{ qrUrl: string; uuid: string }> {
    const payload = await this.sdk.payload.create({
      txjson: {
        TransactionType: "SignIn",
      } as Record<string, unknown>,
      custom_meta: { instruction: "Connect your Xaman wallet to Relay" },
    });
    return { qrUrl: payload.refs.qr_png, uuid: payload.uuid };
  }

  /**
   * Push payload to Xaman and poll until signed or expired (max 5 min).
   */
  private async pushAndWait(options: XamanPayloadOptions): Promise<XamanPayloadResult> {
    const payload = await this.sdk.payload.create(options);
    const uuid = payload.uuid;
    const deadline = Date.now() + 5 * 60 * 1000; // 5 min timeout

    while (Date.now() < deadline) {
      await new Promise((r) => setTimeout(r, 2000));
      const status = await this.sdk.payload.get(uuid);
      if (status.meta.expired) {
        throw makeError("XAMAN_EXPIRED", "Xaman signing request expired");
      }
      if (status.meta.signed) {
        return {
          signed: true,
          txid: status.response.txid,
          hex: status.response.hex,
          payload: { tx_type: String(options.txjson.TransactionType), request_json: options.txjson },
        };
      }
    }
    await this.sdk.payload.cancel(uuid).catch(() => null);
    throw makeError("XAMAN_TIMEOUT", "Xaman signing timed out after 5 minutes");
  }
}

// ── Adapter factory ──────────────────────────────────────────────────────────

export type AdapterType = "agent" | "crossmark" | "xaman";

/**
 * Detect the best adapter for the current environment.
 * Returns "agent" if no browser extension is available (server/agent context).
 */
export function detectAdapterType(): AdapterType {
  if (typeof globalThis === "undefined") return "agent";
  const g = globalThis as Record<string, unknown>;
  if (g.crossmark) return "crossmark";
  if (g.xaman || g.xumm) return "xaman";
  return "agent";
}
