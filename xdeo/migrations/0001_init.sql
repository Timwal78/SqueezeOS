-- xDEO core schema (Cloudflare D1 / SQLite)
-- Zero custody: this database stores OPINIONS, public filing facts, and
-- reputation only. It never stores private keys or routes funds.

-- ---------------------------------------------------------------------------
-- Tickers: the public companies analysts estimate on. CIK links to SEC EDGAR.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tickers (
  ticker        TEXT PRIMARY KEY,          -- e.g. "AAPL"
  cik           TEXT NOT NULL,             -- zero-padded 10-digit, e.g. "0000320193"
  name          TEXT NOT NULL,
  exchange      TEXT,
  created_at    INTEGER NOT NULL           -- unix seconds
);
CREATE INDEX IF NOT EXISTS idx_tickers_cik ON tickers(cik);

-- ---------------------------------------------------------------------------
-- Analysts: identified solely by their wallet address (permissionless, no KYC).
-- Reputation is derived, never custodial.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS analysts (
  address          TEXT PRIMARY KEY,       -- lowercase 0x... (Base)
  handle           TEXT,                   -- optional display name
  reputation       REAL NOT NULL DEFAULT 0,-- composite score 0..100
  accuracy         REAL NOT NULL DEFAULT 0,-- rolling accuracy 0..1
  scored_count     INTEGER NOT NULL DEFAULT 0,
  estimate_count   INTEGER NOT NULL DEFAULT 0,
  tier             TEXT NOT NULL DEFAULT 'OBSERVER', -- OBSERVER|ANALYST|SAGE|ORACLE|LEGEND
  streak_days      INTEGER NOT NULL DEFAULT 0,
  last_active_day  TEXT,                   -- "YYYY-MM-DD" UTC, for streak math
  referrer         TEXT,                   -- address of referrer (10% forever)
  created_at       INTEGER NOT NULL,
  FOREIGN KEY (referrer) REFERENCES analysts(address)
);
CREATE INDEX IF NOT EXISTS idx_analysts_reputation ON analysts(reputation DESC);

-- ---------------------------------------------------------------------------
-- Filings: actual results pulled from SEC EDGAR. The source of truth for
-- scoring. metric/value parsed from XBRL companyconcept.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS filings (
  id            TEXT PRIMARY KEY,          -- accession number (no dashes)
  cik           TEXT NOT NULL,
  ticker        TEXT,
  form          TEXT NOT NULL,             -- 10-K | 10-Q | 8-K
  fiscal_year   INTEGER,
  fiscal_period TEXT,                      -- FY|Q1|Q2|Q3|Q4
  period_end    TEXT,                      -- "YYYY-MM-DD"
  eps_actual    REAL,                      -- diluted EPS from XBRL, null until parsed
  revenue_actual REAL,
  filed_at      TEXT,                      -- "YYYY-MM-DD"
  scored        INTEGER NOT NULL DEFAULT 0,-- 0/1: have we scored estimates against it
  ingested_at   INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_filings_ticker ON filings(ticker);
CREATE INDEX IF NOT EXISTS idx_filings_unscored ON filings(scored) WHERE scored = 0;

-- ---------------------------------------------------------------------------
-- Estimates: the marketplace inventory. An OPINION about a future metric.
-- price_usdc is what a reader pays (via x402) to unlock the full thesis.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS estimates (
  id            TEXT PRIMARY KEY,          -- uuid
  ticker        TEXT NOT NULL,
  analyst       TEXT NOT NULL,             -- analyst address
  metric        TEXT NOT NULL DEFAULT 'eps', -- 'eps' | 'revenue'
  fiscal_year   INTEGER NOT NULL,
  fiscal_period TEXT NOT NULL,             -- Q1..Q4|FY — the period predicted
  predicted     REAL NOT NULL,            -- the estimate value
  confidence    REAL NOT NULL DEFAULT 0.5,-- 0..1 self-reported confidence interval width proxy
  thesis        TEXT NOT NULL,            -- paywalled long-form reasoning
  price_usdc    REAL NOT NULL DEFAULT 0,  -- 0 = free; else x402 price to read thesis
  status        TEXT NOT NULL DEFAULT 'OPEN', -- OPEN|SCORED|VOID
  score         REAL,                     -- 0..100 accuracy score once filing lands
  error_pct     REAL,                     -- |predicted-actual|/|actual|
  filing_id     TEXT,                     -- the filing that scored it
  created_at    INTEGER NOT NULL,
  scored_at     INTEGER,
  FOREIGN KEY (ticker) REFERENCES tickers(ticker),
  FOREIGN KEY (analyst) REFERENCES analysts(address),
  FOREIGN KEY (filing_id) REFERENCES filings(id)
);
CREATE INDEX IF NOT EXISTS idx_estimates_ticker ON estimates(ticker, fiscal_year, fiscal_period);
CREATE INDEX IF NOT EXISTS idx_estimates_analyst ON estimates(analyst);
CREATE INDEX IF NOT EXISTS idx_estimates_open ON estimates(status) WHERE status = 'OPEN';

-- ---------------------------------------------------------------------------
-- Reads: append-only ledger of paid unlocks (x402). Drives analyst earnings
-- accounting (self-custody withdrawal happens on-chain; this is the record).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS reads (
  id            TEXT PRIMARY KEY,          -- uuid
  estimate_id   TEXT NOT NULL,
  reader        TEXT,                      -- payer address (from settled payment)
  agent_id      TEXT,                      -- X-AGENT-ID affiliate, if any
  amount_usdc   REAL NOT NULL,
  protocol_fee  REAL NOT NULL,
  agent_fee     REAL NOT NULL DEFAULT 0,
  tx_hash       TEXT,                      -- Base settlement tx
  created_at    INTEGER NOT NULL,
  FOREIGN KEY (estimate_id) REFERENCES estimates(id)
);
CREATE INDEX IF NOT EXISTS idx_reads_estimate ON reads(estimate_id);
CREATE INDEX IF NOT EXISTS idx_reads_agent ON reads(agent_id);

-- ---------------------------------------------------------------------------
-- Agents: AI agent affiliates (the primary distribution channel).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS agents (
  agent_id      TEXT PRIMARY KEY,          -- self-declared stable id (X-AGENT-ID)
  payout_addr   TEXT,                      -- where affiliate fees settle (Base)
  label         TEXT,
  reads_driven  INTEGER NOT NULL DEFAULT 0,
  fees_earned   REAL NOT NULL DEFAULT 0,
  created_at    INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_agents_reads ON agents(reads_driven DESC);
