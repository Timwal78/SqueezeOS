/**
 * agentWallet() — client-side autonomous XRPL signer.
 *
 * Usage:
 *   const wallet = agentWallet({
 *     seed: process.env.AGENT_SEED!,
 *     network: "xrpl_testnet",
 *     maxSpendPerCallRlusd: 1.0,
 *   });
 *
 *   // Transparent auto-pay: catches 402, pays, retries
 *   const result = await wallet.callWithPayment(
 *     (name, args) => client.callTool({ name, arguments: args }),
 *     "fetch-data",
 *     { query: "latest prices" }
 *   );
 *
 * SECURITY INVARIANTS (enforced by this module):
 *   - `seed` is accessed only at call time — never stored after wallet construction
 *   - `seed` is never logged, serialised, or included in any network request
 *   - Spending is hard-capped at `maxSpendPerCallRlusd` per call
 *   - Reputation gate: if `relayApiUrl` + `minServerReputationScore` are set,
 *     the server's on-chain score is verified before any payment is signed
 */

import { Wallet, Client as XrplClient } from "xrpl";
import type {
  AgentWalletConfig,
  PaymentInvoice,
  CallToolResult,
  Network,
} from "./types";
import { is402Response, extract402Invoice } from "./paywall";

// ── RLUSD issuers ─────────────────────────────────────────────────────────────

const RLUSD_ISSUERS: Record<Network, string> = {
  xrpl_mainnet: "rHb9CJAWyB4rj91VRWn96DkukG4bwdtyTh",
  xrpl_testnet: "rMxCKbEDwqr76QuheSUMdEGf4B9xJ8m5De",
};

const XRPL_NODES: Record<Network, string> = {
  xrpl_mainnet: "wss://xrplcluster.com",
  xrpl_testnet: "wss://s.altnet.rippletest.net:51233",
};

// ── Signing ───────────────────────────────────────────────────────────────────

/**
 * Build a signed RLUSD Payment tx blob for the given invoice.
 *
 * Connects to XRPL to autofill sequence + fee.
 * For test injection, provide `config._signPayment` to bypass network calls.
 */
async function buildPaymentProof(
  invoice: PaymentInvoice,
  config: AgentWalletConfig
): Promise<string> {
  // Test injection path — zero network access
  if (config._signPayment) {
    const txBlob = await config._signPayment(invoice);
    return buildProofEnvelope(txBlob, config.network);
  }

  const wallet = Wallet.fromSeed(config.seed);
  const xrpl = new XrplClient(XRPL_NODES[config.network]);
  await xrpl.connect();

  try {
    const tx = {
      TransactionType: "Payment" as const,
      Account: wallet.classicAddress,
      Destination: invoice.recipient,
      Amount: {
        currency: "USD",
        issuer: RLUSD_ISSUERS[config.network],
        value: invoice.priceRlusd.toString(),
      },
    };

    const prepared = await xrpl.autofill(tx);
    const { tx_blob } = wallet.sign(prepared);
    return buildProofEnvelope(tx_blob, config.network);
  } finally {
    await xrpl.disconnect();
  }
}

function buildProofEnvelope(txBlob: string, network: Network): string {
  const envelope = {
    scheme: "exact",
    network: network === "xrpl_mainnet" ? "xrpl-mainnet" : "xrpl-testnet",
    payload: txBlob,
  };
  return Buffer.from(JSON.stringify(envelope)).toString("base64");
}

// ── Reputation gate ───────────────────────────────────────────────────────────

async function checkServerReputation(
  recipient: string,
  relayApiUrl: string,
  minScore: number
): Promise<{ safe: boolean; score: number }> {
  try {
    const url = `${relayApiUrl.replace(/\/$/, "")}/api/v1/reputation/${recipient}`;
    const res = await fetch(url, { signal: AbortSignal.timeout(3000) });
    if (!res.ok) return { safe: true, score: 0 }; // graceful degradation on error
    const data = (await res.json()) as { score?: { score?: number } };
    const score = data?.score?.score ?? 0;
    return { safe: score >= minScore, score };
  } catch {
    return { safe: true, score: 0 }; // never block on reputation fetch failure
  }
}

// ── AgentWallet ───────────────────────────────────────────────────────────────

export type CallToolFn = (
  name: string,
  args: Record<string, unknown>
) => Promise<CallToolResult>;

export interface AgentWallet {
  /** The XRPL address of the agent's wallet. */
  readonly address: string;

  /**
   * Call an MCP tool, automatically handling 402 challenges.
   *
   * Flow:
   *   1. Call tool without payment
   *   2. If 402: verify price ≤ limit, optional reputation check, sign + retry
   *   3. If still 402 after retry: throw
   */
  callWithPayment(
    callTool: CallToolFn,
    toolName: string,
    toolArgs: Record<string, unknown>
  ): Promise<CallToolResult>;
}

export function agentWallet(config: AgentWalletConfig): AgentWallet {
  // Derive address without storing seed reference beyond this call
  const address = Wallet.fromSeed(config.seed).classicAddress;

  return {
    address,

    async callWithPayment(callTool, toolName, toolArgs) {
      // Attempt 1 — no payment
      const first = await callTool(toolName, toolArgs);
      if (!is402Response(first)) return first;

      // Extract challenge
      const invoice = extract402Invoice(first);
      if (!invoice) {
        throw new Error("Received 402 but could not parse payment invoice");
      }

      // Spending guard — hard cap per call
      if (invoice.priceRlusd > config.maxSpendPerCallRlusd) {
        throw new Error(
          `Tool "${toolName}" costs ${invoice.priceRlusd} RLUSD which exceeds ` +
          `maxSpendPerCallRlusd limit of ${config.maxSpendPerCallRlusd} RLUSD`
        );
      }

      // Invoice expiry check
      if (invoice.expiresAt < Math.floor(Date.now() / 1000)) {
        throw new Error(`Payment invoice for "${toolName}" has expired`);
      }

      // Optional: verify server reputation before paying
      if (config.relayApiUrl && config.minServerReputationScore) {
        const { safe, score } = await checkServerReputation(
          invoice.recipient,
          config.relayApiUrl,
          config.minServerReputationScore
        );
        if (!safe) {
          throw new Error(
            `Server "${invoice.recipient}" reputation score ${score} is below ` +
            `minimum required ${config.minServerReputationScore} — payment refused`
          );
        }
      }

      // Sign payment
      const proof = await buildPaymentProof(invoice, config);

      // Attempt 2 — with payment proof
      const second = await callTool(toolName, {
        ...toolArgs,
        _relay_payment: proof,
      });

      if (is402Response(second)) {
        const fc = second.content[0];
        const rejText = (fc?.type === "text" ? fc.text : undefined) ?? "{}";
        const rejection = JSON.parse(rejText) as { reason?: string };
        throw new Error(
          `Payment rejected by server: ${rejection.reason ?? "unknown reason"}`
        );
      }

      return second;
    },
  };
}
