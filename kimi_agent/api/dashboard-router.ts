import { desc, count, sql } from "drizzle-orm";
import { createRouter, publicQuery } from "./middleware";
import { getDb } from "./queries/connection";
import {
  registries,
  broadcasts,
  interceptedRequests,
  outboundTargets,
  engagements,
  activityLog,
} from "@db/schema";

export const dashboardRouter = createRouter({
  overview: publicQuery.query(async () => {
    const db = getDb();

    const [registryCount] = await db.select({ count: count() }).from(registries);
    const [broadcastCount] = await db.select({ count: count() }).from(broadcasts);
    const [interceptCount] = await db.select({ count: count() }).from(interceptedRequests);
    const [convertedCount] = await db
      .select({ count: count() })
      .from(interceptedRequests)
      .where(sql`${interceptedRequests.converted} = true`);
    const [targetCount] = await db.select({ count: count() }).from(outboundTargets);
    const [engagementCount] = await db.select({ count: count() }).from(engagements);

    const recentActivity = await db
      .select()
      .from(activityLog)
      .orderBy(desc(activityLog.createdAt))
      .limit(20);

    const dailyStats = await db
      .select({
        date: sql<string>`DATE(${activityLog.createdAt})`,
        count: count(),
      })
      .from(activityLog)
      .where(sql`${activityLog.createdAt} >= DATE_SUB(NOW(), INTERVAL 7 DAY)`)
      .groupBy(sql`DATE(${activityLog.createdAt})`)
      .orderBy(sql`DATE(${activityLog.createdAt})`);

    return {
      registries: registryCount?.count ?? 0,
      broadcasts: broadcastCount?.count ?? 0,
      intercepts: interceptCount?.count ?? 0,
      converted: convertedCount?.count ?? 0,
      targets: targetCount?.count ?? 0,
      engagements: engagementCount?.count ?? 0,
      recentActivity,
      dailyStats,
    };
  }),
});

export const activityRouter = createRouter({
  list: publicQuery.query(async () => {
    const db = getDb();
    return db
      .select()
      .from(activityLog)
      .orderBy(desc(activityLog.createdAt))
      .limit(50);
  }),

  create: publicQuery
    .input(
      (input: unknown) => {
        const data = input as { module: string; level: string; message: string; metadata?: string };
        return data;
      }
    )
    .mutation(async ({ input }) => {
      const db = getDb();
      const [log] = await db.insert(activityLog).values({
        module: input.module as "registry" | "honeytrap" | "hustler" | "system",
        level: input.level as "info" | "warning" | "error" | "success",
        message: input.message,
        metadata: input.metadata,
      }).$returningId();
      return log;
    }),
});
