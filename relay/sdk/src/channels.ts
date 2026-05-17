/**
 * Zero-custody payment channel management on XRPL.
 *
 * Channels are created directly between hirer and worker. Relay never
 * holds keys or controls funds — we only construct and validate transactions.
 *
 * XRPL Payment Channel lifecycle:
 *   PaymentChannelCreate  → channel funded, locked
 *   PaymentChannelClaim   → worker claims earned portion
 *   PaymentChannelFund    → hirer tops up channel
 *   PaymentChannelClose   → closes channel, returns unclaimed balance
 */

import {
  Wallet,
  PaymentChannelCreate,
  PaymentChannelClaim,
  PaymentChannelFund,
} from "xrpl";
import { getClient, isValidXrplAddress, makeError, xrpToDrops } from "./xrpl-client";
import {
  Network,
  Token,
  PaymentChannelInfo,
  CreateJobParams,
} from "./types";
import {
  DEFAULT_SETTLE_DELAY_SECONDS,
  RLUSD_CURRENCY,
  RLUSD_ISSUERS,
  RELAY_FEE_BPS,
} from "./constants";

export interface CreateChannelResult {
  channelId: string;
  txHash: string;
  amount: string;
  settleDelay: number;
}

export interface ClaimChannelResult {
  txHash: string;
  claimedAmount: string;
}

/**
 * Create a payment channel from hirer to worker.
 * The wallet parameter must be the hirer's self-custody wallet.
 * Channel funds remain under hirer's cryptographic control until claimed.
 */
export async function createPaymentChannel(
  network: Network,
  hirerWallet: Wallet,
  workerAddress: string,
  amountXrp: number,
  timeoutDays: number = 7,
  destinationTag?: number
): Promise<CreateChannelResult> {
  if (!isValidXrplAddress(workerAddress)) {
    throw makeError("INVALID_ADDRESS", `Invalid worker address: ${workerAddress}`);
  }
  if (amountXrp <= 0) {
    throw makeError("INVALID_AMOUNT", "Channel amount must be positive");
  }

  const client = await getClient(network);
  const settleDelay = timeoutDays * 24 * 60 * 60;
  const amountDrops = xrpToDrops(amountXrp);

  const tx: PaymentChannelCreate = {
    TransactionType: "PaymentChannelCreate",
    Account: hirerWallet.classicAddress,
    Destination: workerAddress,
    Amount: amountDrops,
    SettleDelay: settleDelay,
    PublicKey: hirerWallet.publicKey,
    ...(destinationTag !== undefined && { DestinationTag: destinationTag }),
  };

  const prepared = await client.autofill(tx);
  const signed = hirerWallet.sign(prepared);
  const result = await client.submitAndWait(signed.tx_blob);

  const meta = result.result.meta as Record<string, unknown> | undefined;
  if (
    !meta ||
    (meta as { TransactionResult?: string }).TransactionResult !== "tesSUCCESS"
  ) {
    throw makeError(
      "TX_FAILED",
      "PaymentChannelCreate failed",
      (meta as { TransactionResult?: string })?.TransactionResult
    );
  }

  // Channel ID is derived from account + sequence + flags
  const channelId = extractChannelId(result.result as unknown as Record<string, unknown>);

  return {
    channelId,
    txHash: result.result.hash,
    amount: amountDrops,
    settleDelay,
  };
}

/**
 * Claim funds from a payment channel (worker-side action).
 * The amount parameter is the total cumulative amount the worker is entitled to.
 * Worker signs the claim; hirer's channel balance reduces accordingly.
 */
export async function claimPaymentChannel(
  network: Network,
  workerWallet: Wallet,
  channelId: string,
  amountDrops: string,
  signature?: string
): Promise<ClaimChannelResult> {
  const client = await getClient(network);

  const tx: PaymentChannelClaim = {
    TransactionType: "PaymentChannelClaim",
    Account: workerWallet.classicAddress,
    Channel: channelId,
    Amount: amountDrops,
    ...(signature && { Signature: signature }),
  };

  const prepared = await client.autofill(tx);
  const signed = workerWallet.sign(prepared);
  const result = await client.submitAndWait(signed.tx_blob);

  const meta = result.result.meta as { TransactionResult?: string } | undefined;
  if (meta?.TransactionResult !== "tesSUCCESS") {
    throw makeError("TX_FAILED", "PaymentChannelClaim failed", meta?.TransactionResult);
  }

  return {
    txHash: result.result.hash,
    claimedAmount: amountDrops,
  };
}

/**
 * Close a payment channel. If called by hirer before settleDelay, initiates
 * cooperative close. Unclaimed balance returns to hirer after settleDelay.
 * In XRPL, channels are closed via PaymentChannelClaim with tfClose flag.
 */
export async function closePaymentChannel(
  network: Network,
  wallet: Wallet,
  channelId: string
): Promise<string> {
  const client = await getClient(network);

  const tx: PaymentChannelClaim = {
    TransactionType: "PaymentChannelClaim",
    Account: wallet.classicAddress,
    Channel: channelId,
    Flags: 0x00020000, // tfClose
  };

  const prepared = await client.autofill(tx);
  const signed = wallet.sign(prepared);
  const result = await client.submitAndWait(signed.tx_blob);

  const meta = result.result.meta as { TransactionResult?: string } | undefined;
  if (meta?.TransactionResult !== "tesSUCCESS") {
    throw makeError("TX_FAILED", "PaymentChannelClose failed", meta?.TransactionResult);
  }

  return result.result.hash;
}

/**
 * Fund an existing channel (hirer adds more RLUSD).
 */
export async function fundPaymentChannel(
  network: Network,
  hirerWallet: Wallet,
  channelId: string,
  additionalAmountDrops: string,
  extendExpiration?: number
): Promise<string> {
  const client = await getClient(network);

  const tx: PaymentChannelFund = {
    TransactionType: "PaymentChannelFund",
    Account: hirerWallet.classicAddress,
    Channel: channelId,
    Amount: additionalAmountDrops,
    ...(extendExpiration && { Expiration: extendExpiration }),
  };

  const prepared = await client.autofill(tx);
  const signed = hirerWallet.sign(prepared);
  const result = await client.submitAndWait(signed.tx_blob);

  const meta = result.result.meta as { TransactionResult?: string } | undefined;
  if (meta?.TransactionResult !== "tesSUCCESS") {
    throw makeError("TX_FAILED", "PaymentChannelFund failed", meta?.TransactionResult);
  }

  return result.result.hash;
}

/**
 * Fetch all open payment channels for an account.
 */
export async function getAccountChannels(
  network: Network,
  account: string
): Promise<PaymentChannelInfo[]> {
  const client = await getClient(network);

  const response = await client.request({
    command: "account_channels",
    account,
    ledger_index: "validated",
  });

  const raw = response.result as unknown as { channels?: Array<Record<string, unknown>> };
  return (raw.channels ?? []).map((ch) => ({
    channelId: ch.channel_id as string,
    account: ch.account as string,
    destination: ch.destination_account as string,
    amount: ch.amount as string,
    balance: ch.balance as string,
    settleDelay: ch.settle_delay as number,
    publicKey: ch.public_key as string,
    expiration: ch.expiration as number | undefined,
    destinationTag: ch.destination_tag as number | undefined,
  }));
}

/**
 * Get a specific payment channel by ID.
 */
export async function getChannelInfo(
  network: Network,
  channelId: string
): Promise<PaymentChannelInfo | null> {
  const client = await getClient(network);

  try {
    const response = await client.request({
      command: "ledger_entry",
      payment_channel: channelId,
      ledger_index: "validated",
    });

    const node = (response.result as { node?: Record<string, unknown> }).node;
    if (!node) return null;

    return {
      channelId,
      account: node.Account as string,
      destination: node.Destination as string,
      amount: node.Amount as string,
      balance: node.Balance as string,
      settleDelay: node.SettleDelay as number,
      publicKey: node.PublicKey as string,
      expiration: node.Expiration as number | undefined,
      destinationTag: node.DestinationTag as number | undefined,
    };
  } catch {
    return null;
  }
}

/**
 * Authorize a payment channel claim off-chain.
 * Uses XRPL's native authorizeChannel helper which signs the channel ID + amount.
 * The returned signature can be included in a PaymentChannelClaim by the worker.
 */
export function authorizeChannelClaim(
  channelId: string,
  amountDrops: string,
  hirerWallet: Wallet
): string {
  const { authorizeChannel } = require("xrpl");
  return authorizeChannel(hirerWallet, channelId, amountDrops);
}

// Extract channel ID from PaymentChannelCreate result metadata
function extractChannelId(txResult: Record<string, unknown>): string {
  const meta = txResult.meta as {
    AffectedNodes?: Array<{
      CreatedNode?: {
        LedgerEntryType?: string;
        NewFields?: { index?: string };
      };
    }>;
  } | undefined;

  if (meta?.AffectedNodes) {
    for (const node of meta.AffectedNodes) {
      if (node.CreatedNode?.LedgerEntryType === "PayChannel") {
        const channelId = (node.CreatedNode as unknown as { LedgerIndex?: string }).LedgerIndex;
        if (channelId) return channelId;
      }
    }
  }

  // Fallback: use tx hash (not a real channel ID but useful for testing)
  return (txResult.hash as string) ?? "";
}
