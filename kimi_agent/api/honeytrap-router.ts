import { z } from "zod";
import { eq, desc, count, sql } from "drizzle-orm";
import { createRouter, publicQuery } from "./middleware";
import { getDb } from "./queries/connection";
import { interceptedRequests, activityLog } from "@db/schema";

export const honeytrapRouter = createRouter({
  list: publicQuery
    .input(z.object({
      intent: z.enum(["financial_data", "capability_query", "agent_discovery", "api_probe", "scraping", "unknown"]).optional(),
      limit: z.number().min(1).max(100).default(50),
    }).optional())
    .query(async ({ input }) => {
      const db = getDb();
      let query = db
        .select()
        .from(interceptedRequests)
        .orderBy(desc(interceptedRequests.createdAt))
        .limit(input?.limit ?? 50);

      if (input?.intent) {
        query = query.where(eq(interceptedRequests.intent, input.intent)) as typeof query;
      }

      return query;
    }),

  get: publicQuery
    .input(z.object({ id: z.number() }))
    .query(async ({ input }) => {
      const db = getDb();
      const [req] = await db
        .select()
        .from(interceptedRequests)
        .where(eq(interceptedRequests.id, input.id));
      return req ?? null;
    }),

  create: publicQuery
    .input(
      z.object({
        sourceIp: z.string().optional(),
        userAgent: z.string().optional(),
        requestPath: z.string().min(1),
        intent: z.enum(["financial_data", "capability_query", "agent_discovery", "api_probe", "scraping", "unknown"]).default("unknown"),
        responseType: z.enum(["402_payment_required", "401_unauthorized", "200_sample", "404_not_found", "redirect"]).default("402_payment_required"),
        ap2Payload: z.string().optional(),
        agentSignature: z.string().optional(),
      })
    )
    .mutation(async ({ input }) => {
      const db = getDb();
      const [request] = await db.insert(interceptedRequests).values({
        ...input,
        converted: false,
      }).$returningId();

      await db.insert(activityLog).values({
        module: "honeytrap",
        level: "warning",
        message: `Agent intercepted: ${input.intent} intent detected at ${input.requestPath}`,
        metadata: JSON.stringify({ requestId: request.id, sourceIp: input.sourceIp, intent: input.intent }),
      });

      return request;
    }),

  markConverted: publicQuery
    .input(z.object({ id: z.number() }))
    .mutation(async ({ input }) => {
      const db = getDb();
      await db
        .update(interceptedRequests)
        .set({ converted: true })
        .where(eq(interceptedRequests.id, input.id));

      await db.insert(activityLog).values({
        module: "honeytrap",
        level: "success",
        message: `Intercepted agent #${input.id} converted to paid subscriber`,
        metadata: JSON.stringify({ requestId: input.id }),
      });

      return { success: true };
    }),

  delete: publicQuery
    .input(z.object({ id: z.number() }))
    .mutation(async ({ input }) => {
      const db = getDb();
      await db.delete(interceptedRequests).where(eq(interceptedRequests.id, input.id));
      return { success: true };
    }),

  // Stats
  stats: publicQuery.query(async () => {
    const db = getDb();
    const [totalCount] = await db.select({ count: count() }).from(interceptedRequests);
    const [convertedCount] = await db
      .select({ count: count() })
      .from(interceptedRequests)
      .where(eq(interceptedRequests.converted, true));

    const intentBreakdown = await db
      .select({
        intent: interceptedRequests.intent,
        count: count(),
      })
      .from(interceptedRequests)
      .groupBy(interceptedRequests.intent);

    const recent24h = await db
      .select({ count: count() })
      .from(interceptedRequests)
      .where(
        sql`${interceptedRequests.createdAt} >= DATE_SUB(NOW(), INTERVAL 24 HOUR)`
      );

    return {
      totalRequests: totalCount?.count ?? 0,
      convertedRequests: convertedCount?.count ?? 0,
      conversionRate: totalCount?.count ? Math.round(((convertedCount?.count ?? 0) / totalCount.count) * 100) : 0,
      recent24h: recent24h[0]?.count ?? 0,
      intentBreakdown,
    };
  }),
});
