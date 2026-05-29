-- PNE TimescaleDB schema

CREATE TABLE IF NOT EXISTS auction_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    window_id       BIGINT NOT NULL,
    request_id      UUID NOT NULL,
    wallet_hash     TEXT NOT NULL,
    endpoint        TEXT NOT NULL,
    grace_tip       BIGINT NOT NULL DEFAULT 0,
    auction_rank    INTEGER NOT NULL,
    execution_ms    NUMERIC(10,3) NOT NULL,
    merkle_leaf     TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

SELECT create_hypertable('auction_events', 'created_at', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_auction_events_window ON auction_events (window_id, auction_rank);
CREATE INDEX IF NOT EXISTS idx_auction_events_wallet ON auction_events (wallet_hash, created_at DESC);

CREATE TABLE IF NOT EXISTS merkle_roots (
    height          BIGINT PRIMARY KEY,
    root_hash       TEXT NOT NULL,
    leaf_count      BIGINT NOT NULL DEFAULT 0,
    published_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS agent_stats (
    wallet_hash     TEXT PRIMARY KEY,
    total_tips_sats BIGINT NOT NULL DEFAULT 0,
    total_wins      BIGINT NOT NULL DEFAULT 0,
    total_requests  BIGINT NOT NULL DEFAULT 0,
    first_seen      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
