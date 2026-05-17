/**
 * demo-server.ts — Simulated MCP tool server with 3 paywalled tools.
 *
 * Exposes tool handlers directly (no MCP transport), following the same
 * pattern as __tests__/handshake.test.ts. Each handler is wrapped with
 * paywall() and returned from makeServer() so demo-agent.ts can call them
 * like a real MCP callTool function.
 *
 * Tools:
 *   crypto-price      0.02 RLUSD — spot price snapshot
 *   market-sentiment  0.05 RLUSD — sentiment analysis
 *   whale-tracker     0.10 RLUSD — large transaction feed
 */

import { paywall } from "../mcp-paywall/src/paywall";
import type {
  PaywallConfig,
  CallToolResult,
} from "../mcp-paywall/src/types";

// ── Server wallet address (set by makeServer caller) ──────────────────────────

export interface ToolServer {
  /** Call a paywalled tool by name with args (including _relay_payment if set). */
  callTool: (name: string, args: Record<string, unknown>) => Promise<CallToolResult>;
  /** Human-readable list of tools and their prices. */
  tools: Array<{ name: string; priceRlusd: number; description: string }>;
}

// ── Mock data factories ───────────────────────────────────────────────────────

function mockCryptoPrice(symbol: string): CallToolResult {
  const prices: Record<string, { price: number; change24h: number; volume: number }> = {
    BTC:  { price: 67_420,    change24h: 2.3,  volume: 28_500_000_000 },
    ETH:  { price: 3_812,     change24h: -0.8, volume: 14_200_000_000 },
    XRP:  { price: 0.5823,    change24h: 4.1,  volume: 1_980_000_000  },
    SOL:  { price: 172.44,    change24h: 1.9,  volume: 3_600_000_000  },
    RLUSD: { price: 1.00,     change24h: 0.0,  volume: 92_000_000     },
  };
  const s = String(symbol ?? "BTC").toUpperCase();
  const data = prices[s] ?? { price: 100, change24h: 0, volume: 1_000_000 };
  return {
    content: [{
      type: "text",
      text: JSON.stringify({ symbol: s, ...data }),
    }],
  };
}

function mockMarketSentiment(symbol: string): CallToolResult {
  const sentiments: Record<string, { sentiment: string; score: number; signals: string[] }> = {
    BTC: { sentiment: "Bullish",  score: 0.73, signals: ["ETF inflows +$380M", "Hash rate ATH", "Whale accumulation"] },
    ETH: { sentiment: "Neutral",  score: 0.51, signals: ["Staking APY 4.2%", "DEX volume flat", "L2 TVL growing"] },
    XRP: { sentiment: "Bullish",  score: 0.68, signals: ["SEC case resolved", "Ripple ODL volume up", "New CBDC pilots"] },
    SOL: { sentiment: "Bullish",  score: 0.81, signals: ["DePIN momentum", "Mobile wallet surge", "NFT volume +120%"] },
  };
  const s = String(symbol ?? "BTC").toUpperCase();
  const data = sentiments[s] ?? { sentiment: "Neutral", score: 0.50, signals: ["Insufficient data"] };
  return {
    content: [{
      type: "text",
      text: JSON.stringify({ symbol: s, ...data }),
    }],
  };
}

function mockWhaleTracker(): CallToolResult {
  const transactions = [
    { hash: "A1B2C3D4E5F6", from: "rWhale1...abc", to: "rExchange...def", amount: 25_000_000, asset: "XRP",  time: "14s ago" },
    { hash: "F6E5D4C3B2A1", from: "rFund1...xyz",  to: "rCustody...ghi", amount: 12_500_000, asset: "RLUSD", time: "38s ago" },
    { hash: "1A2B3C4D5E6F", from: "rMiner1...jkl", to: "rOTC...mno",     amount: 850,        asset: "BTC",   time: "1m 12s ago" },
    { hash: "6F5E4D3C2B1A", from: "rInst1...pqr",  to: "rDark...stu",    amount: 18_000_000, asset: "XRP",  time: "2m 5s ago"  },
  ];
  return {
    content: [{
      type: "text",
      text: JSON.stringify({ transactions, generatedAt: new Date().toISOString() }),
    }],
  };
}

// ── makeServer ────────────────────────────────────────────────────────────────

/**
 * Create a paywalled tool server backed by the given recipient address.
 *
 * Returns a { callTool, tools } object that demo-agent.ts passes directly to
 * agentWallet.callWithPayment() as the callTool function.
 */
export function makeServer(recipientAddress: string): ToolServer {
  const cfg = (priceRlusd: number): PaywallConfig => ({
    priceRlusd,
    recipient: recipientAddress,
    network: "xrpl_testnet",
  });

  // ── Tool 1: crypto-price (0.02 RLUSD) ──────────────────────────────────────
  const cryptoPriceHandler = paywall(
    cfg(0.02),
    async ({ symbol }) => mockCryptoPrice(String(symbol ?? "BTC"))
  );

  // ── Tool 2: market-sentiment (0.05 RLUSD) ──────────────────────────────────
  const marketSentimentHandler = paywall(
    cfg(0.05),
    async ({ symbol }) => mockMarketSentiment(String(symbol ?? "BTC"))
  );

  // ── Tool 3: whale-tracker (0.10 RLUSD) ─────────────────────────────────────
  const whaleTrackerHandler = paywall(
    cfg(0.10),
    async (_args) => mockWhaleTracker()
  );

  const handlers: Record<string, (args: Record<string, unknown>) => Promise<CallToolResult>> = {
    "crypto-price":      async (args) => cryptoPriceHandler(args),
    "market-sentiment":  async (args) => marketSentimentHandler(args),
    "whale-tracker":     async (args) => whaleTrackerHandler(args),
  };

  return {
    callTool: async (name, args) => {
      const handler = handlers[name];
      if (!handler) {
        return {
          content: [{ type: "text", text: JSON.stringify({ error: "Tool not found", name }) }],
          isError: true,
        };
      }
      return handler(args);
    },

    tools: [
      { name: "crypto-price",     priceRlusd: 0.02, description: "Real-time spot price + 24h stats" },
      { name: "market-sentiment", priceRlusd: 0.05, description: "Sentiment score + signal breakdown" },
      { name: "whale-tracker",    priceRlusd: 0.10, description: "Large transaction feed (>$1M)" },
    ],
  };
}
