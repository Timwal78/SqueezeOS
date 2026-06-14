// Typed client for the xDEO Worker API. All calls are read-only/free endpoints;
// paid endpoints (estimate theses, estimate index) require x402 and are not
// fetched from the browser here.

export const API_BASE =
  process.env.NEXT_PUBLIC_XDEO_API?.replace(/\/$/, "") ||
  "https://xdeo.example.workers.dev";

export type Tier = "OBSERVER" | "ANALYST" | "SAGE" | "ORACLE" | "LEGEND";

export interface TickerRow {
  ticker: string;
  name: string;
  cik: string;
  exchange: string | null;
}

export interface Consensus {
  available: boolean;
  period?: string;
  n: number;
  mean_eps?: number;
  reputation_weighted_eps?: number;
}

export interface AnalystRow {
  rank?: number;
  address: string;
  handle: string | null;
  reputation: number;
  accuracy: number;
  scored_count: number;
  estimate_count: number;
  tier: Tier;
  streak_days: number;
}

export interface VerdictEntry {
  rank: number;
  analyst: string;
  handle: string | null;
  metric: string;
  predicted: number;
  score: number;
  error_pct: number;
  reputation: number;
  tier: Tier;
  badge: "NOSTRADAMUS" | "RIP" | null;
}

export interface VerdictResponse {
  filing: {
    id: string;
    ticker: string | null;
    form: string;
    fiscal_year: number | null;
    fiscal_period: string | null;
    eps_actual: number | null;
    revenue_actual: number | null;
    filed_at: string | null;
  };
  scored: number;
  verdict: VerdictEntry[];
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { Accept: "application/json" },
    cache: "no-store"
  });
  if (!res.ok) throw new Error(`xDEO API ${res.status} for ${path}`);
  return (await res.json()) as T;
}

export const api = {
  tickers: () => get<{ tickers: TickerRow[] }>("/api/v1/tickers"),
  ticker: (t: string) =>
    get<TickerRow & { consensus: Consensus }>(`/api/v1/tickers/${encodeURIComponent(t)}`),
  analysts: (limit = 100) =>
    get<{ count: number; analysts: AnalystRow[] }>(`/api/v1/analysts?limit=${limit}`),
  analyst: (addr: string) =>
    get<AnalystRow & { global_rank: number; referrals: number; history: unknown[] }>(
      `/api/v1/analysts/${encodeURIComponent(addr)}`
    ),
  verdict: (filingId: string) =>
    get<VerdictResponse>(`/api/v1/verdict/${encodeURIComponent(filingId)}`)
};
