/**
 * Relay Indexer — entry point.
 *
 * Boots the XRPL ledger listener for each configured network.
 * On first start (or after a configurable gap), replays missing ledgers
 * to ensure the cache DB is fully in sync before switching to live streaming.
 *
 * Environment variables:
 *   DATABASE_URL          — Postgres connection string (required)
 *   XRPL_NETWORK          — xrpl_testnet | xrpl_mainnet (default: xrpl_testnet)
 *   INDEXER_REPLAY_FROM   — ledger index to replay from on startup (default: skip replay)
 *   LOG_LEVEL             — debug | info | warn | error (default: info)
 */

import * as dotenv from "dotenv";
import { Client } from "xrpl";
import { logger } from "./logger";
import { startLedgerListener } from "./ledgerListener";
import { replayLedgerRange } from "./stateReconstructor";
import { getPool } from "./db";

dotenv.config();

type Network = "xrpl_mainnet" | "xrpl_testnet";

const NETWORK = (process.env.XRPL_NETWORK ?? "xrpl_testnet") as Network;
const REPLAY_FROM = process.env.INDEXER_REPLAY_FROM
  ? parseInt(process.env.INDEXER_REPLAY_FROM, 10)
  : null;

const XRPL_NODES: Record<Network, string> = {
  xrpl_testnet: "wss://s.altnet.rippletest.net:51233",
  xrpl_mainnet: "wss://xrplcluster.com",
};

async function ensureIndexerSchema(): Promise<void> {
  const pool = getPool();

  // Indexed payment table — stores every RLUSD/XRP Payment tx for fast hash lookup
  await pool.query(`
    CREATE TABLE IF NOT EXISTS indexed_payments (
      tx_hash       VARCHAR(64) PRIMARY KEY,
      sender        VARCHAR(35) NOT NULL,
      recipient     VARCHAR(35) NOT NULL,
      amount        DECIMAL(20,6) NOT NULL,
      token         VARCHAR(10)  NOT NULL,
      fee_drops     VARCHAR(20),
      ledger_index  INTEGER NOT NULL,
      network       VARCHAR(20) NOT NULL,
      indexed_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_ip_recipient   ON indexed_payments(recipient);
    CREATE INDEX IF NOT EXISTS idx_ip_sender      ON indexed_payments(sender);
    CREATE INDEX IF NOT EXISTS idx_ip_ledger      ON indexed_payments(ledger_index);
    CREATE INDEX IF NOT EXISTS idx_ip_network     ON indexed_payments(network);
  `);

  // Payment channels — one row per channel open tx
  await pool.query(`
    CREATE TABLE IF NOT EXISTS indexed_channels (
      create_tx_hash   VARCHAR(64) PRIMARY KEY,
      hirer            VARCHAR(35) NOT NULL,
      worker           VARCHAR(35) NOT NULL,
      amount_drops     VARCHAR(30) NOT NULL,
      settle_delay_s   INTEGER NOT NULL DEFAULT 86400,
      network          VARCHAR(20) NOT NULL,
      ledger_index     INTEGER NOT NULL,
      indexed_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_ic_hirer   ON indexed_channels(hirer);
    CREATE INDEX IF NOT EXISTS idx_ic_worker  ON indexed_channels(worker);
  `);

  // Channel claims
  await pool.query(`
    CREATE TABLE IF NOT EXISTS indexed_channel_claims (
      tx_hash                 VARCHAR(64) PRIMARY KEY,
      channel_id              VARCHAR(64) NOT NULL,
      claimed_amount_drops    VARCHAR(30) NOT NULL,
      channel_balance_drops   VARCHAR(30) NOT NULL,
      network                 VARCHAR(20) NOT NULL,
      ledger_index            INTEGER NOT NULL,
      indexed_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_icc_channel ON indexed_channel_claims(channel_id);
  `);

  // Escrows
  await pool.query(`
    CREATE TABLE IF NOT EXISTS indexed_escrows (
      create_tx_hash  VARCHAR(64) PRIMARY KEY,
      creator         VARCHAR(35) NOT NULL,
      recipient       VARCHAR(35),
      amount_drops    VARCHAR(30) NOT NULL,
      finish_after    INTEGER,
      cancel_after    INTEGER,
      status          VARCHAR(20) NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending','finished','cancelled')),
      finish_tx_hash  VARCHAR(64),
      cancel_tx_hash  VARCHAR(64),
      network         VARCHAR(20) NOT NULL,
      ledger_index    INTEGER NOT NULL,
      indexed_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_ie_creator  ON indexed_escrows(creator);
    CREATE INDEX IF NOT EXISTS idx_ie_status   ON indexed_escrows(status);
  `);

  // Cursor: last fully processed ledger per network
  await pool.query(`
    CREATE TABLE IF NOT EXISTS indexer_cursors (
      network       VARCHAR(20) PRIMARY KEY,
      last_ledger   INTEGER NOT NULL DEFAULT 0,
      updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
  `);

  logger.info("Indexer schema ready");
}

async function getLastProcessedLedger(network: string): Promise<number> {
  const pool = getPool();
  const result = await pool.query(
    "SELECT last_ledger FROM indexer_cursors WHERE network = $1",
    [network]
  );
  return (result.rows[0]?.last_ledger as number | undefined) ?? 0;
}

async function updateCursor(network: string, ledgerIndex: number): Promise<void> {
  const pool = getPool();
  await pool.query(
    `INSERT INTO indexer_cursors (network, last_ledger, updated_at)
     VALUES ($1, $2, NOW())
     ON CONFLICT (network) DO UPDATE
       SET last_ledger = GREATEST(indexer_cursors.last_ledger, $2),
           updated_at  = NOW()`,
    [network, ledgerIndex]
  );
}

async function getCurrentLedger(url: string): Promise<number> {
  const client = new Client(url);
  await client.connect();
  try {
    const res = await client.request({ command: "ledger", ledger_index: "validated" });
    return (res.result as { ledger?: { ledger_index?: number } }).ledger?.ledger_index ?? 0;
  } finally {
    await client.disconnect();
  }
}

async function runReplay(network: Network): Promise<void> {
  if (REPLAY_FROM === null) return;

  const url = XRPL_NODES[network];
  const replayClient = new Client(url);
  await replayClient.connect();

  try {
    const lastProcessed = await getLastProcessedLedger(network);
    const currentLedger = await getCurrentLedger(url);
    const from = Math.max(REPLAY_FROM, lastProcessed + 1);

    if (from > currentLedger) {
      logger.info(`Replay: already up to date at ledger ${lastProcessed}`);
      return;
    }

    logger.info(`Replay: processing ledgers ${from}–${currentLedger} on ${network}`);
    await replayLedgerRange(replayClient as unknown as { request: (req: unknown) => Promise<{ result: unknown }> }, network, from, currentLedger);
    await updateCursor(network, currentLedger);
  } finally {
    await replayClient.disconnect();
  }
}

async function main(): Promise<void> {
  logger.info("Relay Indexer starting", { network: NETWORK });

  if (!process.env.DATABASE_URL) {
    logger.error("DATABASE_URL is required");
    process.exit(1);
  }

  await ensureIndexerSchema();
  await runReplay(NETWORK);

  await startLedgerListener({
    network: NETWORK,
    onLedger: (ledgerIndex) => updateCursor(NETWORK, ledgerIndex).catch(() => null),
  });

  logger.info("Relay Indexer live — streaming from XRPL");
}

main().catch((err) => {
  logger.error("Fatal indexer error:", err);
  process.exit(1);
});
