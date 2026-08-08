import { z } from "zod";
import { eq, desc, count, sql } from "drizzle-orm";
import { createRouter, publicQuery } from "./middleware";
import { getDb } from "./queries/connection";
import { outboundTargets, engagements, activityLog } from "@db/schema";

export const hustlerRouter = createRouter({
  // Targets
  listTargets: publicQuery
    .input(z.object({
      status: z.enum(["discovered", "contacted", "sample_sent", "engaged", "converted", "failed", "blacklisted"]).optional(),
      limit: z.number().min(1).max(100).default(50),
    }).optional())
    .query(async ({ input }) => {
      const db = getDb();
      let query = db
        .select()
        .from(outboundTargets)
        .orderBy(desc(outboundTargets.discoveredAt))
        .limit(input?.limit ?? 50);

      if (input?.status) {
        query = query.where(eq(outboundTargets.status, input.status)) as typeof query;
      }

      return query;
    }),

  getTarget: publicQuery
    .input(z.object({ id: z.number() }))
    .query(async ({ input }) => {
      const db = getDb();
      const [target] = await db
        .select()
        .from(outboundTargets)
        .where(eq(outboundTargets.id, input.id));
      return target ?? null;
    }),

  createTarget: publicQuery
    .input(
      z.object({
        name: z.string().optional(),
        endpoint: z.string().min(1),
        source: z.enum(["github", "discord", "twitter", "registry", "forum", "direct"]).default("registry"),
        agentType: z.enum(["trading_bot", "data_agent", "scraper", "orchestrator", "unknown"]).default("unknown"),
        publicKey: z.string().optional(),
        metadata: z.string().optional(),
      })
    )
    .mutation(async ({ input }) => {
      const db = getDb();
      const [target] = await db.insert(outboundTargets).values(input).$returningId();

      await db.insert(activityLog).values({
        module: "hustler",
        level: "info",
        message: `New target discovered: ${input.name ?? input.endpoint}`,
        metadata: JSON.stringify({ targetId: target.id, endpoint: input.endpoint, agentType: input.agentType }),
      });

      return target;
    }),

  updateTarget: publicQuery
    .input(
      z.object({
        id: z.number(),
        name: z.string().optional(),
        endpoint: z.string().optional(),
        source: z.enum(["github", "discord", "twitter", "registry", "forum", "direct"]).optional(),
        agentType: z.enum(["trading_bot", "data_agent", "scraper", "orchestrator", "unknown"]).optional(),
        status: z.enum(["discovered", "contacted", "sample_sent", "engaged", "converted", "failed", "blacklisted"]).optional(),
        publicKey: z.string().optional(),
        metadata: z.string().optional(),
      })
    )
    .mutation(async ({ input }) => {
      const db = getDb();
      const { id, ...data } = input;
      await db.update(outboundTargets).set(data).where(eq(outboundTargets.id, id));
      return { success: true };
    }),

  deleteTarget: publicQuery
    .input(z.object({ id: z.number() }))
    .mutation(async ({ input }) => {
      const db = getDb();
      await db.delete(outboundTargets).where(eq(outboundTargets.id, input.id));
      return { success: true };
    }),

  // Engagements
  listEngagements: publicQuery
    .input(z.object({ targetId: z.number().optional() }).optional())
    .query(async ({ input }) => {
      const db = getDb();
      let query = db.select().from(engagements).orderBy(desc(engagements.createdAt));
      if (input?.targetId) {
        query = query.where(eq(engagements.targetId, input.targetId)) as typeof query;
      }
      return query;
    }),

  createEngagement: publicQuery
    .input(
      z.object({
        targetId: z.number(),
        type: z.enum(["micro_tx", "sample_delivery", "auth_request", "ping", "capability_showcase"]),
      })
    )
    .mutation(async ({ input }) => {
      const db = getDb();

      // Update target status
      const targetStatusMap: Record<string, string> = {
        micro_tx: "engaged",
        sample_delivery: "sample_sent",
        auth_request: "contacted",
        ping: "contacted",
        capability_showcase: "engaged",
      };

      await db
        .update(outboundTargets)
        .set({
          status: targetStatusMap[input.type] as "contacted" | "sample_sent" | "engaged",
          lastContactedAt: new Date(),
        })
        .where(eq(outboundTargets.id, input.targetId));

      const [engagement] = await db.insert(engagements).values({
        ...input,
        status: "pending",
      }).$returningId();

      let txHash = "N/A";
      let signature = "N/A";
      let payloadSize = 0;

      if (input.type === "micro_tx") {
        try {
          const { Coinbase, Wallet } = await import("@coinbase/coinbase-sdk");
          Coinbase.configure({ 
            apiKeyName: process.env.CDP_API_KEY_ID || "8d05de89-19ec-4e68-b636-847ae2d0d052",
            privateKey: (process.env.CDP_API_KEY_SECRET || "Q6cSiff691s9NeOKC/Q4/MpCo6VwpZvl6ROB8oaL5dQcUM3zE4yhNWQfFhvcDyfQsgrlQbqVzZKIu0ovYp+CfA==").replace(/\\n/g, "\n")
          });
          
          const wallet = await Wallet.create({ networkId: Coinbase.networks.BaseMainnet });
          const transfer = await wallet.createTransfer({
            amount: 0.0001,
            assetId: Coinbase.assets.USDC,
            destination: process.env.PAY_TO_WALLET || "0x4e14B249D9A4c9c9352D780eCEB508A8eB7a7700"
          });
          
          await transfer.wait();
          txHash = transfer.getTransactionHash() || "N/A";
          signature = "CDP_SIGNED";
          payloadSize = 1000;
        } catch (error) {
          console.error("CDP Transfer Failed:", error);
          txHash = "FAILED";
          signature = "N/A";
        }
      } else {
        try {
          const targetRecord = await db.select().from(outboundTargets).where(eq(outboundTargets.id, input.targetId));
          if (targetRecord.length > 0 && targetRecord[0].endpoint) {
             const res = await fetch(targetRecord[0].endpoint, { method: "HEAD" }).catch(() => null);
             if (res) {
               txHash = "HTTP_" + res.status;
               payloadSize = parseInt(res.headers.get("content-length") || "0", 10) || 500;
             } else {
               txHash = "HTTP_FAILED";
               payloadSize = 0;
             }
          }
          signature = "LIVE_PING";
        } catch (error) {
          txHash = "N/A";
          signature = "N/A";
        }
      }

      await db.update(engagements)
        .set({
          status: txHash === "FAILED" || txHash === "HTTP_FAILED" ? "failed" : "delivered",
          txHash,
          signature,
          payloadSize,
          completedAt: new Date(),
        })
        .where(eq(engagements.id, engagement.id));

      await db.insert(activityLog).values({
        module: "hustler",
        level: "success",
        message: `Engagement sent to target #${input.targetId}: ${input.type}`,
        metadata: JSON.stringify({ engagementId: engagement.id, txHash, type: input.type }),
      });

      return { ...engagement, txHash, signature };
    }),

  // Stats
  stats: publicQuery.query(async () => {
    const db = getDb();
    const [totalTargets] = await db.select({ count: count() }).from(outboundTargets);
    const [convertedTargets] = await db
      .select({ count: count() })
      .from(outboundTargets)
      .where(eq(outboundTargets.status, "converted"));
    const [engagedTargets] = await db
      .select({ count: count() })
      .from(outboundTargets)
      .where(eq(outboundTargets.status, "engaged"));
    const [totalEngagements] = await db.select({ count: count() }).from(engagements);

    const typeBreakdown = await db
      .select({
        agentType: outboundTargets.agentType,
        count: count(),
      })
      .from(outboundTargets)
      .groupBy(outboundTargets.agentType);

    const recent24h = await db
      .select({ count: count() })
      .from(outboundTargets)
      .where(
        sql`${outboundTargets.discoveredAt} >= DATE_SUB(NOW(), INTERVAL 24 HOUR)`
      );

    return {
      totalTargets: totalTargets?.count ?? 0,
      convertedTargets: convertedTargets?.count ?? 0,
      engagedTargets: engagedTargets?.count ?? 0,
      totalEngagements: totalEngagements?.count ?? 0,
      recent24h: recent24h[0]?.count ?? 0,
      typeBreakdown,
    };
  }),
});
