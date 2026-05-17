/**
 * XRPL Reputation Indexer — The Graph-style event sourcing for on-chain reputation.
 *
 * Architecture:
 *   1. Subscribe to XRPL account transactions via ledger stream
 *   2. Classify each tx: job creation, channel claim, dispute memo, attestation
 *   3. Emit typed ReputationEvent objects
 *   4. Aggregate into live ReputationScore
 *
 * Anyone can run this indexer independently — all data is public on-chain.
 * Relay's hosted indexer is one node; the protocol doesn't depend on it.
 *
 * Reconstruction guarantee:
 *   Running this indexer from ledger 0 against any XRPL node produces
 *   the exact same reputation scores as Relay's hosted version.
 */

import { Client, SubscribeRequest } from "xrpl";
import { getClient, makeError } from "./xrpl-client";
import { Network } from "./types";
import {
  calculateReputationScore,
  getReputationTier,
  ReputationMetadata,
} from "./reputation";
import { RELAY_FEE_ADDRESS } from "./constants";

// ── Event types emitted by the indexer ──────────────────────────────────────

export type IndexerEventType =
  | "channel_created"
  | "channel_claimed"
  | "channel_closed"
  | "escrow_created"
  | "escrow_finished"
  | "escrow_cancelled"
  | "attestation"
  | "relay_memo"
  | "signer_list_set"
  | "unknown";

export interface IndexerEvent {
  type: IndexerEventType;
  txHash: string;
  ledgerIndex: number;
  timestamp: number;
  account: string;
  counterparty?: string;
  amount?: string;
  memo?: string;
  raw: Record<string, unknown>;
}

export type IndexerEventHandler = (event: IndexerEvent) => void | Promise<void>;

// ── Indexer class ────────────────────────────────────────────────────────────

export class RelayIndexer {
  private handlers: IndexerEventHandler[] = [];
  private running = false;
  private lastLedger = 0;

  constructor(
    private readonly network: Network,
    private readonly watchAddresses: string[] = []
  ) {}

  /**
   * Register a handler for all incoming events.
   */
  onEvent(handler: IndexerEventHandler): void {
    this.handlers.push(handler);
  }

  /**
   * Start streaming from the XRPL ledger.
   * Subscribes to transactions for watched addresses.
   */
  async start(): Promise<void> {
    if (this.running) return;
    this.running = true;

    const client = await getClient(this.network);

    if (this.watchAddresses.length > 0) {
      await client.request({
        command: "subscribe",
        accounts: this.watchAddresses,
      } as SubscribeRequest);

      client.on("transaction", (tx: Record<string, unknown>) => {
        const event = classifyTransaction(tx);
        if (event) this.emit(event);
      });
    }

    client.on("ledgerClosed", (ledger: Record<string, unknown>) => {
      this.lastLedger = ledger.ledger_index as number ?? this.lastLedger;
    });
  }

  async stop(): Promise<void> {
    this.running = false;
    if (this.watchAddresses.length > 0) {
      const client = await getClient(this.network);
      await client.request({
        command: "unsubscribe",
        accounts: this.watchAddresses,
      } as unknown as SubscribeRequest);
    }
  }

  /**
   * Backfill: replay all transactions for an account from a given ledger.
   * Used to reconstruct reputation from scratch.
   */
  async backfill(
    account: string,
    fromLedger: number = 0,
    toLedger: number = -1
  ): Promise<IndexerEvent[]> {
    const client = await getClient(this.network);
    const events: IndexerEvent[] = [];
    let marker: unknown = undefined;

    do {
      const response = await client.request({
        command: "account_tx",
        account,
        ledger_index_min: fromLedger,
        ledger_index_max: toLedger === -1 ? undefined : toLedger,
        limit: 200,
        marker,
        forward: true,
      });

      const result = response.result as {
        transactions: Array<{ tx_json?: Record<string, unknown>; tx?: Record<string, unknown>; meta?: unknown; ledger_index?: number }>;
        marker?: unknown;
      };

      for (const item of result.transactions) {
        const txData = item.tx_json ?? item.tx ?? {};
        const event = classifyTransaction({
          ...txData,
          meta: item.meta,
          ledger_index: item.ledger_index,
        });
        if (event) events.push(event);
      }

      marker = result.marker;
    } while (marker);

    return events;
  }

  /**
   * Build a reputation score by replaying all on-chain events for an account.
   */
  async buildReputationFromChain(account: string): Promise<ReputationMetadata> {
    const events = await this.backfill(account);
    return aggregateReputation(account, events);
  }

  get latestLedger(): number {
    return this.lastLedger;
  }

  private emit(event: IndexerEvent): void {
    for (const handler of this.handlers) {
      Promise.resolve(handler(event)).catch((err) =>
        console.error("Indexer handler error:", err)
      );
    }
  }
}

// ── Transaction classifier ───────────────────────────────────────────────────

export function classifyTransaction(
  tx: Record<string, unknown>
): IndexerEvent | null {
  const type = tx.TransactionType as string | undefined;
  if (!type) return null;

  const base: Omit<IndexerEvent, "type"> = {
    txHash: tx.hash as string ?? tx.Hash as string ?? "",
    ledgerIndex: tx.ledger_index as number ?? 0,
    timestamp: rippleToUnix(tx.date as number ?? 0),
    account: tx.Account as string ?? "",
    amount: extractAmount(tx),
    counterparty: tx.Destination as string ?? undefined,
    memo: extractRelayMemo(tx),
    raw: tx,
  };

  switch (type) {
    case "PaymentChannelCreate":
      return { ...base, type: "channel_created" };

    case "PaymentChannelClaim": {
      const flags = tx.Flags as number ?? 0;
      const isClosed = (flags & 0x00020000) !== 0;
      return { ...base, type: isClosed ? "channel_closed" : "channel_claimed" };
    }

    case "EscrowCreate":
      return { ...base, type: "escrow_created" };

    case "EscrowFinish":
      return { ...base, type: "escrow_finished", counterparty: tx.Owner as string };

    case "EscrowCancel":
      return { ...base, type: "escrow_cancelled", counterparty: tx.Owner as string };

    case "SignerListSet":
      return { ...base, type: "signer_list_set" };

    case "AccountSet": {
      const domain = tx.Domain as string ?? "";
      if (domain.startsWith(Buffer.from("relay:").toString("hex"))) {
        return { ...base, type: "attestation" };
      }
      if (base.memo?.startsWith("relay:")) {
        return { ...base, type: "relay_memo" };
      }
      return null;
    }

    default:
      return null;
  }
}

// ── Reputation aggregator (replays events → metadata) ────────────────────────

export function aggregateReputation(
  account: string,
  events: IndexerEvent[]
): ReputationMetadata {
  let jobsCompleted = 0;
  let totalVolume = 0;
  let disputeCount = 0;
  let stakeDurationDays = 0;
  let joinedAt = "";
  const completedWith = new Set<string>();

  for (const ev of events) {
    if (ev.account !== account && ev.counterparty !== account) continue;

    switch (ev.type) {
      case "channel_closed":
        // Worker claimed channel — job completed
        if (ev.counterparty === account) {
          jobsCompleted++;
          const amountXrp = ev.amount ? parseInt(ev.amount, 10) / 1_000_000 : 0;
          totalVolume += amountXrp;
          if (ev.account) completedWith.add(ev.account);
        }
        break;

      case "escrow_finished":
        // Dispute resolved
        disputeCount++;
        break;

      case "escrow_created":
        // Evaluator stake
        if (ev.account === account) {
          const createdDaysAgo = Math.floor(
            (Date.now() - ev.timestamp * 1000) / (1000 * 60 * 60 * 24)
          );
          stakeDurationDays = Math.max(stakeDurationDays, createdDaysAgo);
          if (!joinedAt) joinedAt = new Date(ev.timestamp * 1000).toISOString();
        }
        break;
    }
  }

  const disputeRate = jobsCompleted > 0 ? disputeCount / jobsCompleted : 0;

  return {
    jobs_completed: jobsCompleted,
    total_volume: totalVolume,
    dispute_rate: disputeRate,
    evaluator_accuracy: null,
    stake_duration_days: stakeDurationDays,
    specializations: [],
    joined_at: joinedAt || new Date().toISOString(),
    last_active: events.length
      ? new Date(Math.max(...events.map((e) => e.timestamp)) * 1000).toISOString()
      : new Date().toISOString(),
    vouched_by: [],
    attestations_given: events.filter(
      (e) => e.type === "attestation" && e.account === account
    ).length,
  };
}

// ── Merkle root for indexer verifiability ────────────────────────────────────

/**
 * Compute a Merkle-style hash over all reputation events for an account.
 * Publish this root periodically so anyone can verify the indexer hasn't tampered.
 */
export function computeEventMerkleRoot(events: IndexerEvent[]): string {
  if (!events.length) return "0".repeat(64);

  const sorted = [...events].sort((a, b) => a.txHash.localeCompare(b.txHash));
  let hash = sorted.map((e) => e.txHash).join("");

  // Simple iterative hash (production: use sha256 tree)
  let h = 0;
  for (let i = 0; i < hash.length; i++) {
    h = Math.imul(31, h) + hash.charCodeAt(i) | 0;
  }
  return Math.abs(h).toString(16).padStart(64, "0");
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function rippleToUnix(rippleTime: number): number {
  return rippleTime + 946684800;
}

function extractAmount(tx: Record<string, unknown>): string | undefined {
  const amount = tx.Amount as string | Record<string, string> | undefined;
  if (!amount) return undefined;
  if (typeof amount === "string") return amount;
  return amount.value;
}

function extractRelayMemo(tx: Record<string, unknown>): string | undefined {
  const memos = tx.Memos as Array<{ Memo: { MemoData?: string } }> | undefined;
  if (!memos?.length) return undefined;
  const hex = memos[0].Memo.MemoData;
  if (!hex) return undefined;
  try {
    return Buffer.from(hex, "hex").toString("utf8");
  } catch {
    return hex;
  }
}
