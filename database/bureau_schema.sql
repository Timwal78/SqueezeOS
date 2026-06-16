-- Credit Bureau Reputation Tracking Schema
-- Defines the mathematical accretion and decay curves for autonomous agents (300-850)

CREATE TABLE agent_reputation (
    wallet_address VARCHAR(64) PRIMARY KEY,
    base_score INTEGER DEFAULT 300,
    current_score INTEGER DEFAULT 300,
    total_tx_count INTEGER DEFAULT 0,
    total_rlusd_spent NUMERIC(16, 6) DEFAULT 0.0,
    last_settlement_ts TIMESTAMP WITH TIME ZONE,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Index for fast tier-checking (Top 800+ agents routing)
CREATE INDEX idx_agent_rep_score ON agent_reputation(current_score DESC);

-- Example mathematical calculation to be implemented in the backend/CRON:
/*
  Let:
    T = Settled transactions in the last 30 days
    R = Total RLUSD spent in the last 30 days
    D = Days since last settlement transaction

  Accretion = (T * 2.5) + (R * 0.5)
  Decay     = (D ^ 1.1) * 0.75
  
  Score     = GREATEST(300, LEAST(850, base_score + Accretion - Decay))
*/
