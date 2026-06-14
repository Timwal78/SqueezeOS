// Shared types and the Cloudflare Worker environment binding surface.

export interface Env {
  DB: D1Database;
  KV: KVNamespace;
  ASSETS: Fetcher;

  // vars (wrangler.toml [vars])
  EDGAR_USER_AGENT: string;
  X402_NETWORK: string;
  X402_ASSET: string;
  X402_FACILITATOR_URL: string;
  PROTOCOL_FEE_BPS: string;
  AGENT_AFFILIATE_BPS: string;
  TREASURY_BPS: string;

  // secrets (wrangler secret put)
  X402_PAY_TO?: string;
  X402_DEV_BYPASS_TOKEN?: string;
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
