/**
 * XRPL ledger stream subscriber.
 *
 * Connects to an XRPL node and subscribes to the `ledger` and `transactions`
 * streams. Each validated transaction is forwarded to the state reconstructor.
 *
 * Reconnection: exponential backoff, capped at 60 s.
 * Duplicate protection: the state reconstructor uses ON CONFLICT idempotent upserts,
 * so receiving the same ledger twice is safe.
 *
 * ZERO CUSTODY: this process only reads from XRPL. It never signs or submits txs.
 */

import { Client, LedgerStream, TransactionStream } from "xrpl";
import { logger } from "./logger";
import { processTransaction } from "./stateReconstructor";

const XRPL_NODES: Record<string, string> = {
  xrpl_testnet: "wss://s.altnet.rippletest.net:51233",
  xrpl_mainnet: "wss://xrplcluster.com",
};

const BACKOFF_BASE_MS = 1_000;
const BACKOFF_MAX_MS  = 60_000;

export interface LedgerListenerOptions {
  network: "xrpl_mainnet" | "xrpl_testnet";
  /** Called for every new validated ledger index */
  onLedger?: (ledgerIndex: number) => void;
}

export async function startLedgerListener(options: LedgerListenerOptions): Promise<void> {
  const { network, onLedger } = options;
  const url = XRPL_NODES[network];
  let attempt = 0;

  const connectWithRetry = async (): Promise<void> => {
    const client = new Client(url);

    client.on("error", (err) => {
      logger.warn(`XRPL client error (${network}):`, { error: String(err) });
    });

    client.on("disconnected", () => {
      logger.warn(`Disconnected from XRPL (${network}). Reconnecting…`);
      scheduleReconnect();
    });

    try {
      await client.connect();
      attempt = 0; // reset backoff on successful connect
      logger.info(`Connected to XRPL ${network} (${url})`);

      await client.request({ command: "subscribe", streams: ["ledger", "transactions"] });
      logger.info(`Subscribed to ledger + transaction streams on ${network}`);

      client.on("ledgerClosed", (ledger: LedgerStream) => {
        logger.debug(`Ledger closed: ${ledger.ledger_index}`);
        onLedger?.(ledger.ledger_index);
      });

      client.on("transaction", async (tx: TransactionStream) => {
        if (!tx.validated) return;
        const txRecord = tx.transaction as unknown as Record<string, unknown>;
        const ledgerIdx = tx.ledger_index ?? 0;
        try {
          await processTransaction(txRecord, network, ledgerIdx);
        } catch (err) {
          logger.error(`Failed to process tx ${txRecord.hash}:`, err);
        }
      });
    } catch (err) {
      logger.error(`Failed to connect to XRPL (${network}):`, err);
      scheduleReconnect();
    }
  };

  const scheduleReconnect = (): void => {
    const delay = Math.min(BACKOFF_BASE_MS * 2 ** attempt, BACKOFF_MAX_MS);
    attempt++;
    logger.info(`Reconnect attempt ${attempt} in ${delay}ms…`);
    setTimeout(connectWithRetry, delay);
  };

  await connectWithRetry();
}
