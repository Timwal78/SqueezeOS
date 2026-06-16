import {
  mysqlTable,
  mysqlEnum,
  serial,
  varchar,
  text,
  timestamp,
  int,
  boolean,
  bigint,
} from "drizzle-orm/mysql-core";

export const users = mysqlTable("users", {
  id: serial("id").primaryKey(),
  unionId: varchar("unionId", { length: 255 }).notNull().unique(),
  name: varchar("name", { length: 255 }),
  email: varchar("email", { length: 320 }),
  avatar: text("avatar"),
  role: mysqlEnum("role", ["user", "admin"]).default("user").notNull(),
  createdAt: timestamp("createdAt").defaultNow().notNull(),
  updatedAt: timestamp("updatedAt")
    .defaultNow()
    .notNull()
    .$onUpdate(() => new Date()),
  lastSignInAt: timestamp("lastSignInAt").defaultNow().notNull(),
});

export type User = typeof users.$inferSelect;
export type InsertUser = typeof users.$inferInsert;

// Registry Broadcaster module
export const registries = mysqlTable("registries", {
  id: serial("id").primaryKey(),
  name: varchar("name", { length: 255 }).notNull(),
  url: text("url").notNull(),
  type: mysqlEnum("type", ["llms_txt", "mcp_hub", "anp_registry", "agent_dir", "github_repo", "other"]).default("other").notNull(),
  status: mysqlEnum("status", ["active", "pending", "failed", "disabled"]).default("pending").notNull(),
  lastCheckedAt: timestamp("lastCheckedAt"),
  discoveredAt: timestamp("discoveredAt").defaultNow().notNull(),
  metadata: text("metadata"),
});

export type Registry = typeof registries.$inferSelect;
export type InsertRegistry = typeof registries.$inferInsert;

export const broadcasts = mysqlTable("broadcasts", {
  id: serial("id").primaryKey(),
  registryId: bigint("registryId", { mode: "number", unsigned: true }).notNull(),
  status: mysqlEnum("status", ["pending", "submitted", "accepted", "rejected", "failed"]).default("pending").notNull(),
  payloadType: mysqlEnum("payloadType", ["agents_json", "capability_card", "llms_txt", "mcp_manifest", "anp_profile"]).notNull(),
  endpoint: text("endpoint"),
  responseCode: int("responseCode"),
  responseBody: text("responseBody"),
  submittedAt: timestamp("submittedAt").defaultNow().notNull(),
  completedAt: timestamp("completedAt"),
});

export type Broadcast = typeof broadcasts.$inferSelect;
export type InsertBroadcast = typeof broadcasts.$inferInsert;

// Honeytrap Interceptor module
export const interceptedRequests = mysqlTable("intercepted_requests", {
  id: serial("id").primaryKey(),
  sourceIp: varchar("sourceIp", { length: 64 }),
  userAgent: text("userAgent"),
  requestPath: varchar("requestPath", { length: 512 }).notNull(),
  intent: mysqlEnum("intent", ["financial_data", "capability_query", "agent_discovery", "api_probe", "scraping", "unknown"]).default("unknown").notNull(),
  responseType: mysqlEnum("responseType", ["402_payment_required", "401_unauthorized", "200_sample", "404_not_found", "redirect"]).default("402_payment_required").notNull(),
  ap2Payload: text("ap2Payload"),
  agentSignature: varchar("agentSignature", { length: 512 }),
  converted: boolean("converted").default(false).notNull(),
  createdAt: timestamp("createdAt").defaultNow().notNull(),
});

export type InterceptedRequest = typeof interceptedRequests.$inferSelect;
export type InsertInterceptedRequest = typeof interceptedRequests.$inferInsert;

// Agent Hustler module
export const outboundTargets = mysqlTable("outbound_targets", {
  id: serial("id").primaryKey(),
  name: varchar("name", { length: 255 }),
  endpoint: text("endpoint").notNull(),
  source: mysqlEnum("source", ["github", "discord", "twitter", "registry", "forum", "direct"]).default("registry").notNull(),
  agentType: mysqlEnum("agentType", ["trading_bot", "data_agent", "scraper", "orchestrator", "unknown"]).default("unknown").notNull(),
  status: mysqlEnum("status", ["discovered", "contacted", "sample_sent", "engaged", "converted", "failed", "blacklisted"]).default("discovered").notNull(),
  publicKey: varchar("publicKey", { length: 512 }),
  metadata: text("metadata"),
  discoveredAt: timestamp("discoveredAt").defaultNow().notNull(),
  lastContactedAt: timestamp("lastContactedAt"),
});

export type OutboundTarget = typeof outboundTargets.$inferSelect;
export type InsertOutboundTarget = typeof outboundTargets.$inferInsert;

export const engagements = mysqlTable("engagements", {
  id: serial("id").primaryKey(),
  targetId: bigint("targetId", { mode: "number", unsigned: true }).notNull(),
  type: mysqlEnum("type", ["micro_tx", "sample_delivery", "auth_request", "ping", "capability_showcase"]).notNull(),
  status: mysqlEnum("status", ["pending", "sent", "delivered", "verified", "failed", "rejected"]).default("pending").notNull(),
  txHash: varchar("txHash", { length: 256 }),
  signature: varchar("signature", { length: 512 }),
  payloadSize: int("payloadSize"),
  responseCode: int("responseCode"),
  responseBody: text("responseBody"),
  createdAt: timestamp("createdAt").defaultNow().notNull(),
  completedAt: timestamp("completedAt"),
});

export type Engagement = typeof engagements.$inferSelect;
export type InsertEngagement = typeof engagements.$inferInsert;

// Activity log
export const activityLog = mysqlTable("activity_log", {
  id: serial("id").primaryKey(),
  module: mysqlEnum("module", ["registry", "honeytrap", "hustler", "system"]).notNull(),
  level: mysqlEnum("level", ["info", "warning", "error", "success"]).default("info").notNull(),
  message: text("message").notNull(),
  metadata: text("metadata"),
  createdAt: timestamp("createdAt").defaultNow().notNull(),
});

export type ActivityLog = typeof activityLog.$inferSelect;
export type InsertActivityLog = typeof activityLog.$inferInsert;
