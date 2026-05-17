/**
 * Database migration runner.
 * Run: npm run migrate
 *
 * Migrations are idempotent (CREATE TABLE IF NOT EXISTS).
 * Financial source of truth is XRPL — this DB is an indexer cache.
 */

import { getPool } from "./pool";
import * as dotenv from "dotenv";

dotenv.config();

const MIGRATIONS = [
  // Migration 001: Core tables
  `
  CREATE TABLE IF NOT EXISTS jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    channel_id VARCHAR(64) UNIQUE NOT NULL,
    hirer VARCHAR(35) NOT NULL,
    worker VARCHAR(35) NOT NULL,
    amount DECIMAL(20, 6) NOT NULL,
    token VARCHAR(10) NOT NULL CHECK (token IN ('RLUSD', 'XRP')),
    status VARCHAR(20) NOT NULL DEFAULT 'pending'
      CHECK (status IN ('pending','funded','active','disputed','completed','cancelled')),
    milestones JSONB NOT NULL DEFAULT '[]',
    evaluator_pool VARCHAR(50) DEFAULT 'default',
    timeout_days INTEGER NOT NULL DEFAULT 7,
    multi_sig_config JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    dispute_id UUID,
    tx_hash VARCHAR(64) NOT NULL,
    network VARCHAR(20) NOT NULL DEFAULT 'xrpl_testnet'
  );

  CREATE INDEX IF NOT EXISTS idx_jobs_hirer ON jobs(hirer);
  CREATE INDEX IF NOT EXISTS idx_jobs_worker ON jobs(worker);
  CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
  CREATE INDEX IF NOT EXISTS idx_jobs_channel_id ON jobs(channel_id);
  `,

  // Migration 002: Disputes
  `
  CREATE TABLE IF NOT EXISTS disputes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID REFERENCES jobs(id) ON DELETE RESTRICT,
    initiator VARCHAR(35) NOT NULL,
    reason TEXT NOT NULL,
    evidence TEXT[] NOT NULL DEFAULT '{}',
    requested_outcome VARCHAR(20) NOT NULL
      CHECK (requested_outcome IN ('release_to_hirer','release_to_worker','partial')),
    status VARCHAR(20) NOT NULL DEFAULT 'pending'
      CHECK (status IN ('pending','evaluating','resolved')),
    selected_evaluators JSONB NOT NULL DEFAULT '[]',
    votes JSONB NOT NULL DEFAULT '[]',
    outcome VARCHAR(20) CHECK (outcome IN ('release_to_hirer','release_to_worker','partial')),
    resolution_tx_hash VARCHAR(64),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    resolved_at TIMESTAMPTZ
  );

  CREATE INDEX IF NOT EXISTS idx_disputes_job_id ON disputes(job_id);
  CREATE INDEX IF NOT EXISTS idx_disputes_status ON disputes(status);
  `,

  // Migration 003: Evaluators
  `
  CREATE TABLE IF NOT EXISTS evaluators (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    address VARCHAR(35) UNIQUE NOT NULL,
    stake_amount DECIMAL(20, 6) NOT NULL,
    stake_escrow_tx VARCHAR(64) NOT NULL,
    specializations TEXT[] NOT NULL DEFAULT '{}',
    accuracy DECIMAL(5, 4),
    total_votes INTEGER NOT NULL DEFAULT 0,
    correct_votes INTEGER NOT NULL DEFAULT 0,
    slash_count INTEGER NOT NULL DEFAULT 0,
    last_vote_at TIMESTAMPTZ,
    status VARCHAR(20) NOT NULL DEFAULT 'active'
      CHECK (status IN ('active','suspended','deregistered')),
    network VARCHAR(20) NOT NULL DEFAULT 'xrpl_testnet',
    created_at TIMESTAMPTZ DEFAULT NOW()
  );

  CREATE INDEX IF NOT EXISTS idx_evaluators_status ON evaluators(status);
  CREATE INDEX IF NOT EXISTS idx_evaluators_specializations ON evaluators USING GIN(specializations);
  CREATE INDEX IF NOT EXISTS idx_evaluators_network ON evaluators(network);
  `,

  // Migration 004: Reputation events (audit trail)
  `
  CREATE TABLE IF NOT EXISTS reputation_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    address VARCHAR(35) NOT NULL,
    event_type VARCHAR(30) NOT NULL
      CHECK (event_type IN (
        'job_completed','job_cancelled',
        'dispute_initiated','dispute_resolved',
        'evaluator_vote','evaluator_slashed','evaluator_rewarded',
        'stake_increased','stake_decreased',
        'attestation_given','attestation_received'
      )),
    job_id UUID REFERENCES jobs(id) ON DELETE SET NULL,
    dispute_id UUID REFERENCES disputes(id) ON DELETE SET NULL,
    amount DECIMAL(20, 6),
    metadata JSONB,
    tx_hash VARCHAR(64),
    created_at TIMESTAMPTZ DEFAULT NOW()
  );

  CREATE INDEX IF NOT EXISTS idx_rep_events_address ON reputation_events(address);
  CREATE INDEX IF NOT EXISTS idx_rep_events_type ON reputation_events(event_type);
  CREATE INDEX IF NOT EXISTS idx_rep_events_created ON reputation_events(created_at DESC);
  `,

  // Migration 008: Governance tables
  `
  CREATE TABLE IF NOT EXISTS governance_proposals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    proposal_id VARCHAR(32) UNIQUE NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    options TEXT[] NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'active'
      CHECK (status IN ('active','closed','enacted','rejected')),
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
  );

  CREATE TABLE IF NOT EXISTS governance_votes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    voter VARCHAR(35) NOT NULL,
    proposal_id VARCHAR(32) NOT NULL REFERENCES governance_proposals(proposal_id),
    choice TEXT NOT NULL,
    tx_hash VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(voter, proposal_id)
  );

  CREATE INDEX IF NOT EXISTS idx_gov_votes_proposal ON governance_votes(proposal_id);
  `,

  // Migration 006: Settlement signatures column
  `
  ALTER TABLE disputes
    ADD COLUMN IF NOT EXISTS settlement_signatures JSONB DEFAULT '[]';
  `,

  // Migration 007: Evaluator public keys (for vote verification)
  `
  ALTER TABLE evaluators
    ADD COLUMN IF NOT EXISTS public_key VARCHAR(66);
  `,

  // Migration 005: Attestations (peer vouching)
  `
  CREATE TABLE IF NOT EXISTS attestations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    attester VARCHAR(35) NOT NULL,
    attestee VARCHAR(35) NOT NULL,
    context TEXT NOT NULL,
    signature TEXT NOT NULL,
    job_id UUID REFERENCES jobs(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(attester, attestee, context)
  );

  CREATE INDEX IF NOT EXISTS idx_attestations_attestee ON attestations(attestee);
  CREATE INDEX IF NOT EXISTS idx_attestations_attester ON attestations(attester);
  `,

  // Migration 009: Streak counter for VRF weight calculation
  // Separate from correct_votes (total count) — this is the running consecutive streak.
  // Resets to 0 on any incorrect vote or slash; used by computeStreakMultiplier().
  `
  ALTER TABLE evaluators
    ADD COLUMN IF NOT EXISTS consecutive_accurate_votes INTEGER NOT NULL DEFAULT 0;

  CREATE INDEX IF NOT EXISTS idx_evaluators_streak ON evaluators(consecutive_accurate_votes DESC);
  `,
];

async function migrate(): Promise<void> {
  const pool = getPool();

  // Create migrations tracking table
  await pool.query(`
    CREATE TABLE IF NOT EXISTS _relay_migrations (
      id SERIAL PRIMARY KEY,
      applied_at TIMESTAMPTZ DEFAULT NOW()
    );
  `);

  const { rows } = await pool.query("SELECT COUNT(*) AS count FROM _relay_migrations");
  const applied = parseInt(rows[0].count, 10);

  const pending = MIGRATIONS.slice(applied);
  if (!pending.length) {
    console.log(`All ${applied} migrations already applied.`);
    await pool.end();
    return;
  }

  const client = await pool.connect();
  try {
    for (let i = 0; i < pending.length; i++) {
      await client.query("BEGIN");
      await client.query(pending[i]);
      await client.query("INSERT INTO _relay_migrations DEFAULT VALUES");
      await client.query("COMMIT");
      console.log(`Migration ${applied + i + 1} applied.`);
    }
    console.log(`Applied ${pending.length} migration(s). Total: ${applied + pending.length}`);
  } catch (err) {
    await client.query("ROLLBACK");
    throw err;
  } finally {
    client.release();
    await pool.end();
  }
}

migrate().catch((err) => {
  console.error("Migration failed:", err);
  process.exit(1);
});
