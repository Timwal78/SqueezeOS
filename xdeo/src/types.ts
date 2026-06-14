// Shared types and the Cloudflare Worker environment binding surface.

export interface Env {
  DB: D1Database;
  KV: KVNamespace;
  ASSETS: Fetcher;
  STREAM_HUB: DurableObjectNamespace;
  AI: Ai;

  // vars (wrangler.toml [vars])
  EDGAR_USER_AGENT: string;
  X402_NETWORK: string;
  X402_ASSET: string;
  X402_FACILITATOR_URL: string;
  PROTOCOL_FEE_BPS: string;
  AGENT_AFFILIATE_BPS: string;
  TREASURY_BPS: string;

  // Autonomous House Analyst (daily cron). All optional — sensible defaults.
  XDEO_UNIVERSE?: string;          // comma-separated watchlist; defaults to large caps
  HOUSE_ANALYST_ADDRESS?: string;  // identity for house estimates
  HOUSE_ESTIMATE_PRICE?: string;   // USDC price to read a house thesis (default 0.05)
  HOUSE_MAX_PER_RUN?: string;      // max new house estimates per daily run (default 10)

  // secrets (wrangler secret put)
  X402_PAY_TO?: string;
  X402_DEV_BYPASS_TOKEN?: string;
  ADMIN_TOKEN?: string; // guards POST /api/v1/admin/* (manual House Analyst seeding)
}

export type Tier = "OBSERVER" | "ANALYST" | "SAGE" | "ORACLE" | "LEGEND";

export interface Analyst {
  address: string;
  handle: string | null;
  reputation: number;
  accuracy: number;
  scored_count: number;
  estimate_count: number;
  tier: Tier;
  streak_days: number;
  last_active_day: string | null;
  referrer: string | null;
  created_at: number;
}

export interface Estimate {
  id: string;
  ticker: string;
  analyst: string;
  metric: "eps" | "revenue";
  fiscal_year: number;
  fiscal_period: string;
  predicted: number;
  confidence: number;
  thesis: string;
  price_usdc: number;
  status: "OPEN" | "SCORED" | "VOID";
  score: number | null;
  error_pct: number | null;
  filing_id: string | null;
  created_at: number;
  scored_at: number | null;
}

export interface Filing {
  id: string;
  cik: string;
  ticker: string | null;
  form: string;
  fiscal_year: number | null;
  fiscal_period: string | null;
  period_end: string | null;
  eps_actual: number | null;
  revenue_actual: number | null;
  filed_at: string | null;
  scored: number;
  ingested_at: number;
}
