import { getDb } from "../api/queries/connection";
import {
  registries,
  broadcasts,
  interceptedRequests,
  outboundTargets,
  engagements,
  activityLog,
} from "./schema";

async function seed() {
  const db = getDb();
  console.log("Seeding database...");

  // Seed registries
  const registryData = [
    { name: "llms.txt Directory", url: "https://llmstxt.org/directory", type: "llms_txt" as const, status: "active" as const, metadata: JSON.stringify({ stars: 1240, language: "en" }) },
    { name: "MCP Hub Registry", url: "https://hub.mcp.run/registry", type: "mcp_hub" as const, status: "active" as const, metadata: JSON.stringify({ agents: 340 }) },
    { name: "ANP Global Registry", url: "https://registry.anp.network", type: "anp_registry" as const, status: "active" as const, metadata: JSON.stringify({ version: "2.1.0" }) },
    { name: "AgentRank Directory", url: "https://agentrank.io/agents", type: "agent_dir" as const, status: "pending" as const, metadata: JSON.stringify({ category: "finance" }) },
    { name: "GitHub AI Agents", url: "https://github.com/topics/ai-agent", type: "github_repo" as const, status: "active" as const, metadata: JSON.stringify({ repos: 8900 }) },
    { name: "OpenAgents Map", url: "https://openagents.com/map", type: "agent_dir" as const, status: "failed" as const, metadata: JSON.stringify({ error: "timeout" }) },
    { name: "MCP Community Hub", url: "https://mcp.community/hub", type: "mcp_hub" as const, status: "active" as const, metadata: JSON.stringify({ contributors: 45 }) },
  ];

  for (const r of registryData) {
    await db.insert(registries).values(r);
  }
  console.log("Registries seeded");

  // Seed broadcasts
  const broadcastData = [
    { registryId: 1, payloadType: "agents_json" as const, status: "accepted" as const, endpoint: "https://llmstxt.org/api/submit", responseCode: 200 },
    { registryId: 2, payloadType: "capability_card" as const, status: "accepted" as const, endpoint: "https://hub.mcp.run/api/v1/cards", responseCode: 201 },
    { registryId: 3, payloadType: "anp_profile" as const, status: "submitted" as const, endpoint: "https://registry.anp.network/v2/agents", responseCode: 202 },
    { registryId: 4, payloadType: "agents_json" as const, status: "pending" as const, endpoint: "https://agentrank.io/api/register" },
    { registryId: 5, payloadType: "capability_card" as const, status: "accepted" as const, endpoint: "https://api.github.com/repos/topic/ai-agent", responseCode: 200 },
    { registryId: 7, payloadType: "mcp_manifest" as const, status: "submitted" as const, endpoint: "https://mcp.community/api/manifests", responseCode: 200 },
  ];

  for (const b of broadcastData) {
    await db.insert(broadcasts).values(b);
  }
  console.log("Broadcasts seeded");

  // Seed intercepted requests
  const interceptedData = [
    { sourceIp: "203.0.113.42", userAgent: "AI-Agent/1.0 (TraderBot; compatible)", requestPath: "/api/v2/market-data", intent: "financial_data" as const, responseType: "402_payment_required" as const, ap2Payload: JSON.stringify({ endpoint: "https://api.orion.network/v1/premium", tier: "pro", price: "0.001 ETH/request" }), agentSignature: "agent_sig_trader_v2", converted: true },
    { sourceIp: "198.51.100.17", userAgent: "DataScraper/3.1 (+http://bot.example.com)", requestPath: "/api/capabilities", intent: "capability_query" as const, responseType: "401_unauthorized" as const, ap2Payload: JSON.stringify({ auth_url: "https://orion.network/auth", scopes: ["read", "trade"] }), agentSignature: "agent_sig_datascraper", converted: false },
    { sourceIp: "192.0.2.88", userAgent: "AgentDiscovery/0.9 (MCP-compatible)", requestPath: "/.well-known/agent.json", intent: "agent_discovery" as const, responseType: "200_sample" as const, ap2Payload: JSON.stringify({ manifest: { name: "Orion Protocol", version: "2.4.1" } }), agentSignature: "agent_sig_discovery", converted: false },
    { sourceIp: "203.0.113.91", userAgent: "TradingBot-Alpha/4.2", requestPath: "/api/anomaly-feed", intent: "financial_data" as const, responseType: "402_payment_required" as const, ap2Payload: JSON.stringify({ endpoint: "https://api.orion.network/v1/anomaly", tier: "enterprise", price: "0.005 ETH/request" }), agentSignature: "agent_sig_alpha", converted: true },
    { sourceIp: "198.51.100.203", userAgent: "ScrapeBot/1.0", requestPath: "/docs/api-reference", intent: "scraping" as const, responseType: "404_not_found" as const, agentSignature: "agent_sig_scraper", converted: false },
    { sourceIp: "192.0.2.156", userAgent: "Orchestrator/2.0 (ANP-compatible)", requestPath: "/api/v1/agents", intent: "agent_discovery" as const, responseType: "200_sample" as const, ap2Payload: JSON.stringify({ agents: ["market-data", "anomaly-detection", "risk-assessment"] }), agentSignature: "agent_sig_orch", converted: true },
    { sourceIp: "203.0.113.17", userAgent: "APIProbe/0.1", requestPath: "/api/v1/status", intent: "api_probe" as const, responseType: "redirect" as const, ap2Payload: JSON.stringify({ redirect: "https://status.orion.network" }), agentSignature: "agent_sig_probe", converted: false },
    { sourceIp: "198.51.100.44", userAgent: "FinAgent/3.0 (Quantitative)", requestPath: "/api/v2/orderbook", intent: "financial_data" as const, responseType: "402_payment_required" as const, ap2Payload: JSON.stringify({ endpoint: "https://api.orion.network/v1/orderbook", tier: "pro", trial: "100 requests" }), agentSignature: "agent_sig_fin", converted: true },
  ];

  for (const i of interceptedData) {
    await db.insert(interceptedRequests).values(i);
  }
  console.log("Intercepted requests seeded");

  // Seed outbound targets
  const targetData = [
    { name: "AlphaTrader Bot", endpoint: "https://alphatrader.io/api/webhook", source: "github" as const, agentType: "trading_bot" as const, status: "converted" as const, publicKey: "0x742d35Cc6634C0532925a3b844Bc9e7595f0bEb", metadata: JSON.stringify({ stars: 340, language: "Python" }) },
    { name: "DataHarvester", endpoint: "https://harvester.agent.network/ingest", source: "registry" as const, agentType: "data_agent" as const, status: "engaged" as const, publicKey: "0x8ba1f109551bD432803012645Hac136c82C3e8C", metadata: JSON.stringify({ lastActive: "2h ago" }) },
    { name: "SentimentScraper", endpoint: "https://sentibot.dev/api/receive", source: "discord" as const, agentType: "scraper" as const, status: "sample_sent" as const, metadata: JSON.stringify({ channels: ["#trading", "#alpha"] }) },
    { name: "OrchestratorX", endpoint: "https://orchx.ai/agents/inbox", source: "twitter" as const, agentType: "orchestrator" as const, status: "contacted" as const, publicKey: "0x3f5CE5FBFe3E9af3971dD833A64d4b452Cde3b3B", metadata: JSON.stringify({ followers: 12000 }) },
    { name: "FlashLoanBot", endpoint: "https://flashy.loans/hook", source: "github" as const, agentType: "trading_bot" as const, status: "discovered" as const, metadata: JSON.stringify({ forked_from: "aave/flash-loan" }) },
    { name: "MarketMaker Pro", endpoint: "https://mmpro.trade/signal", source: "forum" as const, agentType: "trading_bot" as const, status: "converted" as const, publicKey: "0xdAC17F958D2ee523a2206206994597C13D831ec7", metadata: JSON.stringify({ volume: "$2.4M daily" }) },
    { name: "ArbitrageAgent", endpoint: "https://arb.agent.dex/api", source: "registry" as const, agentType: "trading_bot" as const, status: "failed" as const, metadata: JSON.stringify({ error: "endpoint unreachable" }) },
    { name: "NewsFlow AI", endpoint: "https://newsflow.ai/feed", source: "direct" as const, agentType: "data_agent" as const, status: "engaged" as const, publicKey: "0xA0b86a33E6441e3d96C5b0F9E97d7c6B8A2c4E5f", metadata: JSON.stringify({ feed_count: 12 }) },
  ];

  for (const t of targetData) {
    await db.insert(outboundTargets).values(t);
  }
  console.log("Outbound targets seeded");

  // Seed engagements
  const engagementData = [
    { targetId: 1, type: "sample_delivery" as const, status: "verified" as const, txHash: "0x3a2f1e9d8c7b6a5f4e3d2c1b0a9f8e7d6c5b4a3f2e1d0c9b8a7f6e5d4c3b2a1f0", signature: "sig_a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6", payloadSize: 24576, responseCode: 200 },
    { targetId: 1, type: "micro_tx" as const, status: "verified" as const, txHash: "0x7f8e9d0c1b2a3f4e5d6c7b8a9f0e1d2c3b4a5f6e7d8c9b0a1f2e3d4c5b6a7f8e9", signature: "sig_q1w2e3r4t5y6u7i8o9p0a1s2d3f4g5h6", payloadSize: 1024, responseCode: 200 },
    { targetId: 2, type: "capability_showcase" as const, status: "delivered" as const, txHash: "0x1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p7q8r9s0t1u2v3w4x5y6z7a8b9c0", signature: "sig_z1x2c3v4b5n6m7a8s9d0f1g2h3j4k5l6", payloadSize: 48192, responseCode: 202 },
    { targetId: 3, type: "sample_delivery" as const, status: "delivered" as const, txHash: "0x9f8e7d6c5b4a3f2e1d0c9b8a7f6e5d4c3b2a1f0e9d8c7b6a5f4e3d2c1b0a9f8e7", signature: "sig_m1n2b3v4c5x6z7l8k9j0h1g2f3d4s5a6", payloadSize: 16384, responseCode: 200 },
    { targetId: 4, type: "ping" as const, status: "sent" as const, txHash: "0x2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p7q8r9s0t1u2v3w4x5y6z7a8b9c0d1e2", signature: "sig_p1o2i3u4y5t6r7e8w9q0a1s2d3f4g5h6", payloadSize: 256, responseCode: 200 },
    { targetId: 6, type: "sample_delivery" as const, status: "verified" as const, txHash: "0x4d5e6f7g8h9i0j1k2l3m4n5o6p7q8r9s0t1u2v3w4x5y6z7a8b9c0d1e2f3g4", signature: "sig_l1k2j3h4g5f6d7s8a9p0o1i2u3y4t5r6", payloadSize: 32768, responseCode: 200 },
    { targetId: 6, type: "micro_tx" as const, status: "verified" as const, txHash: "0x6f7g8h9i0j1k2l3m4n5o6p7q8r9s0t1u2v3w4x5y6z7a8b9c0d1e2f3g4h5i6", signature: "sig_w1e2r3t4y5u6i7o8p9a0s1d2f3g4h5j6", payloadSize: 512, responseCode: 200 },
    { targetId: 8, type: "auth_request" as const, status: "delivered" as const, txHash: "0x8h9i0j1k2l3m4n5o6p7q8r9s0t1u2v3w4x5y6z7a8b9c0d1e2f3g4h5i6j7k8", signature: "sig_e1r2t3y4u5i6o7p8a9s0d1f2g3h4j5k6l7", payloadSize: 2048, responseCode: 201 },
  ];

  for (const e of engagementData) {
    await db.insert(engagements).values(e);
  }
  console.log("Engagements seeded");

  // Seed activity log
  const activityData = [
    { module: "registry" as const, level: "success" as const, message: "Capability card accepted by MCP Hub Registry", metadata: JSON.stringify({ registryId: 2, payloadType: "capability_card" }) },
    { module: "honeytrap" as const, level: "warning" as const, message: "Agent intercepted: financial_data intent at /api/v2/market-data", metadata: JSON.stringify({ sourceIp: "203.0.113.42", intent: "financial_data" }) },
    { module: "hustler" as const, level: "success" as const, message: "Sample delivered to AlphaTrader Bot — verified ingestion", metadata: JSON.stringify({ targetId: 1, txHash: "0x3a2f..." }) },
    { module: "system" as const, level: "info" as const, message: "Orion Protocol daemon started — all modules active", metadata: JSON.stringify({ version: "2.4.1", uptime: "0s" }) },
    { module: "registry" as const, level: "success" as const, message: "ANP profile submitted to Global Registry", metadata: JSON.stringify({ registryId: 3, status: "pending_verification" }) },
    { module: "honeytrap" as const, level: "success" as const, message: "FinAgent converted to Pro tier after 402 response", metadata: JSON.stringify({ requestId: 8, tier: "pro" }) },
    { module: "hustler" as const, level: "info" as const, message: "New target discovered: FlashLoanBot via GitHub scan", metadata: JSON.stringify({ targetId: 5, source: "github" }) },
    { module: "honeytrap" as const, level: "warning" as const, message: "ScrapeBot blocked at /docs/api-reference", metadata: JSON.stringify({ requestId: 5, action: "404_response" }) },
    { module: "hustler" as const, level: "success" as const, message: "MarketMaker Pro converted — enterprise tier", metadata: JSON.stringify({ targetId: 6, revenue: "0.05 ETH" }) },
    { module: "registry" as const, level: "error" as const, message: "OpenAgents Map registry unreachable", metadata: JSON.stringify({ registryId: 6, error: "timeout" }) },
  ];

  for (const a of activityData) {
    await db.insert(activityLog).values(a);
  }
  console.log("Activity log seeded");

  console.log("Database seeded successfully!");
}

seed().catch(console.error);
